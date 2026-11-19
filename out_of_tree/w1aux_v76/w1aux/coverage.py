"""W1 auxiliary tools: S0 and the getBlock coverage audit (protocol w1_start_rule and data/coverage_audit).

Lives OUTSIDE the frozen tree aff97638 (RUGGER 02, 2026-11-09 12:01Z/12:02Z): no file of that tree is
added or changed; this package only imports it read-only (run with the frozen checkout as the current
directory and the parent of ``w1aux/`` on PYTHONPATH). It holds no evaluation logic.

* ``s0``: S0 = the smallest PRODUCED finalized slot whose blockTime is >= 1794218340
  (2026-11-09T09:59:00Z, RUGGER 02 anchoring fad499c3), by bisection with getBlocksWithLimit and
  getBlockTime; the produced slot just before it (blockTime < target) is published as the proof of
  minimality.
* ``slots``: the 200 drawn slots, random.Random(20261108).sample(range(S0 + 402800, S0 + 2015600), 200),
  sorted, without replacement. Fixed in this audited code before S0 is known.
* ``fetch`` (phase 1, right after the window ends and BEFORE the LaunchLab collection): a drawn slot
  whose leader skipped it is replaced by the next produced slot (noted in the summary and the log);
  one getBlock per audited slot; the blocks are NOT archived, only a per-slot summary (blockhash,
  parentSlot, blockTime, transaction count, sha256 of the canonical response, every LaunchLab
  signature with its meta.err). The summary file's sha256 is then anchored by RUGGER 02.
* ``compare`` (phase 2, AFTER the collection, offline): the anchored summary against the verified,
  complete LaunchLab run. PASS only with zero missing signature (and no collected signature that the
  block does not hold).
* A produced block the node cannot serve (-32004, -32007, -32009: retention) or a transaction
  version it refuses (-32015) is a STOP of the coverage audit: neither PASS nor a miss.
* Network: dry run unless --network; at most one call per second; every attempt, retries included,
  charged to --max-requests and written to a JSONL log with its outcome; the URL is never logged.
"""
import hashlib
import json
import os
import random
import time
from pathlib import Path

from bot.market import backfill as bf
from bot.market import w1_collection

FREEZE_ANCHOR_TIME = 1_794_218_340            # 2026-11-09T09:59:00Z (RUGGER 02 anchoring fad499c3)
AUDIT_SEED = 20_261_108
AUDIT_SLOTS = 200
SUMMARY_SCHEMA = 'rugger-w1-coverage-summary-v1'
RESULT_SCHEMA = 'rugger-w1-coverage-result-v1'
DETAILS = ('accounts', 'full')
TX_VERSIONS = (0, 1)
PRODUCED_PAGE = 8                             # getBlocksWithLimit page when looking for produced slots
FINALIZED = {'commitment': 'finalized'}


class CoverageError(RuntimeError):
    """An error of the tool; a message containing ``_STOP`` is a STOP of the coverage audit."""


# ----------------------------------------------------------------- S0
def find_s0(first_produced, block_time, lo, hi, target):
    """Smallest produced slot whose block time is >= ``target``.

    ``first_produced(slot)``: the first produced slot >= ``slot`` (getBlocksWithLimit(slot, 1));
    ``block_time(slot)``: its blockTime. ``lo``: a slot whose first produced slot is before the
    target; ``hi``: a slot whose first produced slot is at or after it. Returns (s0, calls, checks).
    """
    calls = [0]

    def produced(slot):
        calls[0] += 1
        value = first_produced(slot)
        if type(value) is not int or value < slot:
            raise CoverageError('invalid_first_produced_slot')
        return value

    def time_of(slot):
        calls[0] += 1
        value = block_time(slot)
        if type(value) is not int:
            raise CoverageError('missing_block_time')
        return value

    lo = produced(lo)
    if time_of(lo) >= target:
        raise CoverageError('lo_is_not_before_the_target')
    answer = produced(hi)
    if time_of(answer) < target:
        raise CoverageError('hi_is_not_after_the_target')
    while hi - lo > 1:
        mid = (lo + hi) // 2
        slot = produced(mid)
        if slot >= hi:                      # [mid, hi) holds no produced slot
            hi = mid
        elif time_of(slot) >= target:
            hi, answer = mid, slot
        else:
            lo = slot
    checks = {'previous_produced_slot': lo, 'previous_block_time': time_of(lo), 's0_block_time': time_of(answer)}
    return answer, calls[0], checks


# ----------------------------------------------------------------- audited slots
def evaluation_range(s0, evaluation_slots=w1_collection.EVALUATION_SLOTS):
    """[start, end) of the evaluation range of the W1 bounds."""
    bounds = w1_collection.bounds(s0, evaluation_slots)
    return s0 + w1_collection.WARMUP_SLOTS, bounds['entry_cutoff_slot'] + 1


def draw_audit_slots(s0, *, evaluation_slots=w1_collection.EVALUATION_SLOTS, count=AUDIT_SLOTS, seed=AUDIT_SEED):
    """The drawn slots, uniformly without replacement from the evaluation range, sorted."""
    start, end = evaluation_range(s0, evaluation_slots)
    return sorted(random.Random(seed).sample(range(start, end), count))


def resolve_audit_slots(drawn, produced_from, end):
    """Replace each drawn slot its leader skipped by the next produced slot.

    ``produced_from(slot)``: produced slots >= ``slot``, increasing, non-empty (getBlocksWithLimit).
    Drawn slots are taken in increasing order; a skipped one is replaced by the first produced slot
    after it that is neither a drawn slot nor an earlier replacement, so the audited slots stay
    distinct. A replacement must lie in the evaluation range (< ``end``), otherwise STOP.
    Returns (sorted audited slots, [{'drawn', 'replacement'}]).
    """
    drawn_set, taken, audited, replacements = set(drawn), set(), [], []
    for slot in sorted(drawn):
        produced = produced_from(slot)
        if produced[0] == slot:
            audited.append(slot)
            taken.add(slot)
            continue
        pick = None
        while pick is None:
            for candidate in produced:
                if candidate >= end:
                    raise CoverageError(f'no_replacement_in_the_evaluation_range_STOP:{slot}')
                if candidate not in drawn_set and candidate not in taken:
                    pick = candidate
                    break
            else:
                produced = produced_from(produced[-1] + 1)
        audited.append(pick)
        taken.add(pick)
        replacements.append({'drawn': slot, 'replacement': pick})
    return sorted(audited), replacements


# ----------------------------------------------------------------- block parsing
def _pubkeys(entry, details):
    tx, meta = entry['transaction'], entry['meta']
    loaded = meta.get('loadedAddresses')
    if details == 'accounts':
        keys = tx['accountKeys']
        if not isinstance(keys, list) or not all(
                isinstance(k, dict) and isinstance(k.get('pubkey'), str) and k.get('source') in ('transaction', 'lookupTable')
                for k in keys):
            raise CoverageError('accounts_mode_key_without_source')          # use transactionDetails full
        pubkeys = [k['pubkey'] for k in keys]
    else:
        keys = tx['message']['accountKeys']
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise CoverageError('full_mode_malformed_account_keys')
        if loaded is None and entry.get('version', 'legacy') != 'legacy':
            raise CoverageError('full_mode_versioned_transaction_without_loadedAddresses')
        pubkeys = list(keys)
    if loaded:                                       # also present in accounts mode: duplicates are harmless
        pubkeys += list(loaded.get('writable') or []) + list(loaded.get('readonly') or [])
    return pubkeys


def launchlab_entries(block, details, program=bf.LAUNCHLAB_PROGRAM):
    """[{'signature', 'err'}] of the block's transactions whose static or loaded keys contain ``program``."""
    if details not in DETAILS:
        raise CoverageError('unknown_transaction_details')
    if not isinstance(block, dict) or not isinstance(block.get('transactions'), list):
        raise CoverageError('malformed_block')
    found = []
    for entry in block['transactions']:
        try:
            if not isinstance(entry['meta'], dict):
                raise TypeError
            signature = entry['transaction']['signatures'][0]
            pubkeys = _pubkeys(entry, details)
        except (KeyError, TypeError, IndexError):
            raise CoverageError('malformed_block_transaction') from None
        if program in pubkeys:
            found.append({'signature': signature, 'err': entry['meta'].get('err')})
    return found


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
                          .encode('utf-8')).hexdigest()


def summarize_block(slot, block, details, program=bf.LAUNCHLAB_PROGRAM):
    """Per-slot summary kept instead of the block (RUGGER 02 12:02Z)."""
    entries = launchlab_entries(block, details, program)
    for key, kind in (('blockhash', str), ('parentSlot', int)):
        if type(block.get(key)) is not kind:
            raise CoverageError(f'malformed_block:{key}')
    if block.get('blockTime') is not None and type(block['blockTime']) is not int:
        raise CoverageError('malformed_block:blockTime')
    return {'slot': slot, 'blockhash': block['blockhash'], 'parentSlot': block['parentSlot'],
            'blockTime': block.get('blockTime'), 'transactions': len(block['transactions']),
            'response_sha256': canonical_sha256(block), 'launchlab': entries}


# ----------------------------------------------------------------- phase 2: comparison (offline)
def collected_signatures_by_slot(run_dir, slots):
    """Signatures of a VERIFIED, COMPLETE collection, for the given slots."""
    checked = bf.verify(run_dir)
    if not checked['ok'] or not checked['complete']:
        raise CoverageError('collection_not_verified_or_incomplete')
    wanted, out = set(slots), {slot: set() for slot in slots}
    manifest = json.loads((Path(run_dir) / 'manifest.json').read_text(encoding='utf-8'))
    for seg in manifest['segments']:
        if seg['kind'] != 'tx':
            continue
        for row in bf.read_segment(Path(run_dir) / seg['path']):
            if row.get('slot') in wanted:
                out[row['slot']].add(row['signature'])
    return out


def check_summary(summary):
    """Structural checks of a summary before it is used (it is anchored by its file sha256)."""
    if not isinstance(summary, dict) or summary.get('schema') != SUMMARY_SCHEMA:
        raise CoverageError('not_a_coverage_summary')
    s0, evaluation_slots = summary.get('s0'), summary.get('evaluation_slots')
    drawn = draw_audit_slots(s0, evaluation_slots=evaluation_slots)
    if summary.get('drawn') != drawn or summary.get('seed') != AUDIT_SEED:
        raise CoverageError('summary_drawn_slots_do_not_match_the_protocol_draw')
    slots = [block['slot'] for block in summary.get('blocks', [])]
    replaced = {r['drawn']: r['replacement'] for r in summary.get('replacements', [])}
    expected = sorted(replaced.get(slot, slot) for slot in drawn)
    if slots != expected or summary.get('slots') != expected or len(set(slots)) != len(drawn):
        raise CoverageError('summary_audited_slots_inconsistent')
    start, end = evaluation_range(s0, evaluation_slots)
    if not all(start <= slot < end for slot in slots):
        raise CoverageError('summary_slot_outside_the_evaluation_range')
    return slots


def compare(summary, collected):
    """PASS only if every LaunchLab signature of every audited block is in the collection
    (threshold zero, protocol data/coverage_audit) and the collection holds no signature at an
    audited slot that the block does not hold."""
    slots = check_summary(summary)
    missing, extra, counted, failed = {}, {}, 0, 0
    for block in summary['blocks']:
        slot, held = block['slot'], {e['signature'] for e in block['launchlab']}
        counted += len(held)
        failed += sum(1 for e in block['launchlab'] if e['err'] is not None)
        got = collected.get(slot, set())
        if held - got:
            missing[slot] = sorted(held - got)
        if got - held:
            extra[slot] = sorted(got - held)
    verdict = 'PASS' if not missing and not extra else 'FAIL'
    return dict(schema=RESULT_SCHEMA, verdict=verdict, s0=summary['s0'], slots=len(slots),
                replacements=len(summary['replacements']), launchlab_transactions=counted,
                launchlab_failed_transactions=failed, missing=missing, collected_not_in_block=extra)


# ----------------------------------------------------------------- network (read-only)
RETRYABLE = ('http_429', 'http_500', 'http_502', 'http_503', 'http_504', 'rpc_error_-32005', 'rpc_error_429',
             'URLError', 'TimeoutError', 'OSError')
NOT_AVAILABLE = ('rpc_error_-32004', 'rpc_error_-32007', 'rpc_error_-32009')
VERSION_REFUSED = ('rpc_error_-32015',)


class LoggedRpc:
    """Read-only JSON-RPC: <= 1 call per second, every attempt charged to the cap and logged (JSONL)."""

    def __init__(self, url, max_requests, log_path, *, opener=None, min_interval=1.0, max_attempts=4,
                 sleep=time.sleep):
        from bot.market.collector import Budget, JsonRpc
        kwargs = {} if opener is None else {'opener': opener}
        self.rpc = JsonRpc(url, Budget(max_requests), min_interval=min_interval, max_retries=0, sleep=sleep, **kwargs)
        self.log_path, self.max_attempts, self.sleep = Path(log_path), max_attempts, sleep

    @property
    def used(self):
        return self.rpc.budget.used

    def note(self, **line):
        with self.log_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(line, at=round(time.time(), 3)), sort_keys=True) + '\n')

    def call(self, method, params):
        from bot.market.collector import BudgetExhausted, RpcError
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = self.rpc.call(method, params)
            except BudgetExhausted as exc:
                self.note(method=method, params=params, attempt=attempt, outcome=str(exc))
                raise
            except RpcError as exc:
                cause = str(exc).split(':', 1)[1]
                self.note(method=method, params=params, attempt=attempt, outcome=cause)
                if cause in RETRYABLE and attempt < self.max_attempts:
                    self.sleep(min(30.0, 2.0 * 2 ** attempt))
                    continue
                raise
            self.note(method=method, params=params, attempt=attempt, outcome='ok')
            return result
        raise AssertionError('unreachable')                             # pragma: no cover


def _rpc(environ, endpoint_env, max_requests, log_path, opener=None, sleep=time.sleep):
    if environ.get('RUGGER_NO_DOTENV') != '1':
        raise CoverageError('set_RUGGER_NO_DOTENV_1')
    url = bf.endpoint_from_env(endpoint_env, environ)
    return LoggedRpc(url, max_requests, log_path, opener=opener, sleep=sleep)


def produced_from_online(rpc):
    def produced_from(slot):
        result = rpc.call('getBlocksWithLimit', [slot, PRODUCED_PAGE, FINALIZED])
        if (not isinstance(result, list) or not result or not all(type(s) is int for s in result)
                or result[0] < slot or any(b <= a for a, b in zip(result, result[1:]))):
            raise CoverageError(f'unexpected_getBlocksWithLimit_answer:{slot}')
        return result
    return produced_from


def find_s0_online(rpc, lo, target=None):
    """find_s0 over a JSON-RPC endpoint (finalized); hi = the current finalized slot."""
    produced_from = produced_from_online(rpc)
    hi = rpc.call('getSlot', [FINALIZED])
    return find_s0(lambda slot: produced_from(slot)[0], lambda slot: rpc.call('getBlockTime', [slot]),
                   lo, hi, FREEZE_ANCHOR_TIME if target is None else target)


def fetch(rpc, s0, *, details, max_tx_version, evaluation_slots=w1_collection.EVALUATION_SLOTS):
    """Phase 1: the per-slot summary of the audited blocks (no block archived)."""
    from bot.market.collector import RpcError
    if details not in DETAILS or max_tx_version not in TX_VERSIONS:
        raise CoverageError('invalid_fetch_options')
    window_slot_max = w1_collection.bounds(s0, evaluation_slots)['window_slot_max']
    current = rpc.call('getSlot', [FINALIZED])
    if type(current) is not int or current <= window_slot_max:
        raise CoverageError('window_not_finished')
    drawn = draw_audit_slots(s0, evaluation_slots=evaluation_slots)
    start, end = evaluation_range(s0, evaluation_slots)
    slots, replacements = resolve_audit_slots(drawn, produced_from_online(rpc), end)
    for replacement in replacements:
        rpc.note(event='skipped_drawn_slot_replaced', **replacement)
    options = {'encoding': 'json', 'transactionDetails': details, 'maxSupportedTransactionVersion': max_tx_version,
               'rewards': False, 'commitment': 'finalized'}
    blocks = []
    for slot in slots:
        try:
            block = rpc.call('getBlock', [slot, options])
        except RpcError as exc:
            cause = str(exc).split(':', 1)[1]
            if cause in NOT_AVAILABLE:
                raise CoverageError(f'block_not_available_STOP:{slot}:{cause}') from None
            if cause in VERSION_REFUSED:
                raise CoverageError(f'transaction_version_refused_STOP:{slot}:{cause}') from None
            raise
        if block is None:
            raise CoverageError(f'block_not_available_STOP:{slot}:null')
        blocks.append(summarize_block(slot, block, details))
    return {'schema': SUMMARY_SCHEMA, 's0': s0, 'seed': AUDIT_SEED, 'evaluation_slots': evaluation_slots,
            'evaluation_range': [start, end], 'window_slot_max': window_slot_max, 'finalized_slot_at_start': current,
            'program': bf.LAUNCHLAB_PROGRAM, 'transaction_details': details,
            'max_supported_transaction_version': max_tx_version, 'drawn': drawn, 'replacements': replacements,
            'slots': slots, 'blocks': blocks}


# ----------------------------------------------------------------- command
def _file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None, *, environ=None, opener=None, out=None, sleep=time.sleep):
    """``s0``, ``slots``, ``fetch`` (network, dry run unless --network) and ``compare`` (offline)."""
    import argparse
    import sys
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description='W1 S0 and getBlock coverage audit (read-only)')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('s0')
    s.add_argument('--lo', type=int, required=True, help='a produced slot known to be before the anchor time')
    d = sub.add_parser('slots')
    d.add_argument('--s0', type=int, required=True)
    f = sub.add_parser('fetch')
    f.add_argument('--s0', type=int, required=True)
    f.add_argument('--out', type=Path, required=True, help='summary file to create (never overwritten)')
    f.add_argument('--details', choices=DETAILS, default='accounts')
    f.add_argument('--max-tx-version', type=int, choices=TX_VERSIONS, required=True,
                   help='getBlock maxSupportedTransactionVersion: an explicit, anchored decision')
    for p in (d, f):
        p.add_argument('--evaluation-slots', type=int, default=w1_collection.EVALUATION_SLOTS)
    c = sub.add_parser('compare')
    c.add_argument('--summary', type=Path, required=True)
    c.add_argument('--summary-sha256', required=True, help='the sha256 anchored by RUGGER 02 after fetch')
    c.add_argument('--run', type=Path, required=True, help='verified, complete LaunchLab W1 run directory')
    for p, cap in ((s, 120), (f, 600)):
        p.add_argument('--network', action='store_true')
        p.add_argument('--endpoint-env', default='RUGGER_COVERAGE_RPC_URL')
        p.add_argument('--max-requests', type=int, default=cap, help='every attempt counts, retries included')
        p.add_argument('--log', type=Path, help='JSONL log of every attempt (required with --network)')
    args = parser.parse_args(argv)
    emit = lambda obj: out.write(json.dumps(obj, indent=1, sort_keys=True) + '\n')     # noqa: E731
    if args.command == 'slots':
        emit({'s0': args.s0, 'seed': AUDIT_SEED, 'evaluation_slots': args.evaluation_slots,
              'drawn': draw_audit_slots(args.s0, evaluation_slots=args.evaluation_slots)})
        return 0
    if args.command == 'compare':
        if _file_sha256(args.summary) != args.summary_sha256:
            raise CoverageError('summary_sha256_does_not_match_the_anchor')
        summary = json.loads(args.summary.read_text(encoding='utf-8'))
        result = compare(summary, collected_signatures_by_slot(args.run, check_summary(summary)))
        emit(dict(result, summary_sha256=args.summary_sha256))
        return 0 if result['verdict'] == 'PASS' else 4
    if args.command == 'fetch' and args.out.exists():
        raise CoverageError('summary_file_already_exists')
    if not args.network:
        emit({'dry_run': True, 'requests_sent': 0, 'command': args.command,
              'message': 'no request sent; add --network to run (owner decision)'})
        return 0
    if args.log is None:
        raise CoverageError('network_runs_need_a_log_file')
    rpc = _rpc(environ, args.endpoint_env, args.max_requests, args.log, opener, sleep)
    try:
        if args.command == 's0':
            s0, calls, checks = find_s0_online(rpc, args.lo)
            emit(dict(s0=s0, target_block_time=FREEZE_ANCHOR_TIME, bisection_steps=calls,
                      requests_used=rpc.used, **checks))
            return 0
        summary = fetch(rpc, args.s0, details=args.details, max_tx_version=args.max_tx_version,
                        evaluation_slots=args.evaluation_slots)
    except CoverageError as exc:
        if '_STOP' not in str(exc):
            raise
        emit({'verdict': 'STOP', 'cause': str(exc), 'requests_used': rpc.used})
        return 5
    summary['requests_used'] = rpc.used
    with args.out.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    emit({'summary': str(args.out), 'summary_sha256': _file_sha256(args.out), 'slots': len(summary['slots']),
          'replacements': len(summary['replacements']),
          'launchlab_transactions': sum(len(b['launchlab']) for b in summary['blocks']),
          'requests_used': rpc.used})
    return 0


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
