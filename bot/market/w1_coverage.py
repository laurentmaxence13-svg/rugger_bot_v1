"""W1 start slot (S0) and getBlock coverage audit (protocol data/coverage_audit, independence/w1_start_rule).

Offline core plus a small read-only command. NOT part of the frozen collection or evaluation code
(outside COLLECTOR_ROOTS and CODE_ROOTS): it only establishes S0 and audits a finished collection.

* ``find_s0``: S0 = the first PRODUCED, finalized slot whose blockTime is >= the freeze anchor time
  (RUGGER 02 anchoring fad499c3: T = 2026-11-09T09:59:00Z = 1794218340). Bisection over slots with
  getBlocksWithLimit (to skip empty slots) and getBlockTime; the result is checked against the
  previous produced slot.
* ``draw_audit_slots``: 200 slots drawn uniformly, without replacement, from the evaluation range
  [S0 + 402800, S0 + 2015600) with random.Random(20261108), published BEFORE the collection.
* ``launchlab_signatures``: signatures of a getBlock (transactionDetails ``accounts``, which lists
  every account key, static or loaded through address lookup tables, with meta.err; ``full`` is
  also understood) whose keys contain the LaunchLab program; failed transactions included (same
  scope as getTransactionsForAddress with status any).
* ``audit``: for each audited slot, LaunchLab signatures of the block missing from the verified
  collection. Threshold zero: any missing signature fails the audit. Whether an audited slot was
  produced is asked first (getBlocks(slot, slot)): a slot its leader skipped holds no transaction
  and fails only if the collection holds one; a PRODUCED slot whose block the node cannot serve
  (-32004, -32007, -32009: retention) is a STOP, never a miss nor a pass. Run the audit soon after
  the window ends: the public RPC does not keep a long history.
* Network: one call per second at most, every attempt (retries included) charged to the request
  cap and written to a JSONL log with its outcome (status or RPC error code), the URL never.
"""
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
SCHEMA = 'rugger-w1-coverage-audit-v1'


class CoverageError(RuntimeError):
    pass


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
    return answer, calls[0], {'previous_produced_slot': lo, 'previous_block_time': time_of(lo),
                              's0_block_time': time_of(answer)}


# ----------------------------------------------------------------- audit slots
def evaluation_range(s0, evaluation_slots=w1_collection.EVALUATION_SLOTS):
    """[start, end) of the evaluation range of the W1 bounds."""
    bounds = w1_collection.bounds(s0, evaluation_slots)
    return s0 + w1_collection.WARMUP_SLOTS, bounds['entry_cutoff_slot'] + 1


def draw_audit_slots(s0, *, evaluation_slots=w1_collection.EVALUATION_SLOTS, count=AUDIT_SLOTS, seed=AUDIT_SEED):
    """The audited slots, drawn uniformly without replacement from the evaluation range, sorted."""
    start, end = evaluation_range(s0, evaluation_slots)
    return sorted(random.Random(seed).sample(range(start, end), count))


# ----------------------------------------------------------------- block parsing
def launchlab_signatures(block, program=bf.LAUNCHLAB_PROGRAM):
    """Signatures of the block's transactions whose static or loaded account keys contain ``program``."""
    if not isinstance(block, dict) or not isinstance(block.get('transactions'), list):
        raise CoverageError('malformed_block')
    found = []
    for entry in block['transactions']:
        try:
            tx, meta = entry['transaction'], entry.get('meta') or {}
            keys = list(tx['accountKeys'] if 'accountKeys' in tx else tx['message']['accountKeys'])
            signature = tx['signatures'][0]
        except (KeyError, TypeError, IndexError):
            raise CoverageError('malformed_block_transaction') from None
        loaded = meta.get('loadedAddresses') or {}
        keys += list(loaded.get('writable') or []) + list(loaded.get('readonly') or [])
        keys = [k['pubkey'] if isinstance(k, dict) else k for k in keys]
        if program in keys:
            found.append(signature)
    return found


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


def audit(blocks, collected):
    """``blocks``: {slot: getBlock result or None (skipped)}; ``collected``: {slot: set of signatures}.

    PASS only if every LaunchLab signature of every audited block is in the collection (threshold
    zero, protocol data/coverage_audit) and no skipped slot holds a collected transaction.
    """
    missing, skipped, counted, contradictions = {}, [], 0, []
    for slot in sorted(blocks):
        block = blocks[slot]
        if block is None:
            skipped.append(slot)
            if collected.get(slot):
                contradictions.append(slot)
            continue
        signatures = launchlab_signatures(block)
        counted += len(signatures)
        lost = sorted(set(signatures) - collected.get(slot, set()))
        if lost:
            missing[slot] = lost
    verdict = 'PASS' if not missing and not contradictions else 'FAIL'
    return dict(schema=SCHEMA, verdict=verdict, slots=len(blocks), launchlab_transactions=counted,
                missing=missing, skipped_slots=skipped, collected_in_skipped_slots=contradictions)


# ----------------------------------------------------------------- network command (read-only)
RETRYABLE = ('http_429', 'http_500', 'http_502', 'http_503', 'http_504', 'rpc_error_-32005', 'rpc_error_429',
             'URLError', 'TimeoutError', 'OSError')
NOT_AVAILABLE = ('rpc_error_-32004', 'rpc_error_-32007', 'rpc_error_-32009')


class LoggedRpc:
    """Read-only JSON-RPC: <= 1 call per second, every attempt charged to the cap and logged (JSONL)."""

    def __init__(self, url, max_requests, log_path, *, opener=None, min_interval=1.0, max_attempts=4,
                 sleep=time.sleep):
        from bot.market.collector import Budget, JsonRpc
        kwargs = {} if opener is None else {'opener': opener}
        self.rpc = JsonRpc(url, Budget(max_requests), min_interval=min_interval, max_retries=0, sleep=sleep, **kwargs)
        self.log_path, self.max_attempts, self.sleep = Path(log_path), max_attempts, sleep

    def _log(self, **line):
        with self.log_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(line, at=round(time.time(), 3)), sort_keys=True) + '\n')

    def call(self, method, params):
        from bot.market.collector import BudgetExhausted, RpcError
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = self.rpc.call(method, params)
            except BudgetExhausted as exc:
                self._log(method=method, params=params, attempt=attempt, outcome=str(exc))
                raise
            except RpcError as exc:
                cause = str(exc).split(':', 1)[1]
                self._log(method=method, params=params, attempt=attempt, outcome=cause)
                if cause in RETRYABLE and attempt < self.max_attempts:
                    self.sleep(min(30.0, 2.0 * 2 ** attempt))
                    continue
                raise
            self._log(method=method, params=params, attempt=attempt, outcome='ok')
            return result
        raise AssertionError('unreachable')                             # pragma: no cover


def _rpc(environ, endpoint_env, max_requests, log_path, opener=None, sleep=time.sleep):
    if environ.get('RUGGER_NO_DOTENV') != '1':
        raise CoverageError('set_RUGGER_NO_DOTENV_1')
    url = bf.endpoint_from_env(endpoint_env, environ)
    return LoggedRpc(url, max_requests, log_path, opener=opener, sleep=sleep)


FINALIZED = {'commitment': 'finalized'}


def find_s0_online(rpc, lo, target=None):
    """find_s0 over a JSON-RPC endpoint (finalized); hi = the current finalized slot."""
    def first_produced(slot):
        result = rpc.call('getBlocksWithLimit', [slot, 1, FINALIZED])
        if not isinstance(result, list) or not result:
            raise CoverageError('no_produced_slot_after')
        return result[0]

    def block_time(slot):
        return rpc.call('getBlockTime', [slot])

    hi = rpc.call('getSlot', [FINALIZED])
    return find_s0(first_produced, block_time, lo, hi, FREEZE_ANCHOR_TIME if target is None else target)


def fetch_blocks(rpc, slots):
    """{slot: block (accounts) or None if its leader skipped it}; a produced slot not served: STOP."""
    from bot.market.collector import MAX_TX_VERSION, RpcError
    blocks = {}
    for slot in slots:
        produced = rpc.call('getBlocks', [slot, slot, FINALIZED])
        if produced == []:
            blocks[slot] = None
            continue
        if produced != [slot]:
            raise CoverageError(f'unexpected_getBlocks_answer:{slot}')
        try:
            blocks[slot] = rpc.call('getBlock', [slot, {'encoding': 'json', 'transactionDetails': 'accounts',
                                                        'maxSupportedTransactionVersion': MAX_TX_VERSION,
                                                        'rewards': False, 'commitment': 'finalized'}])
        except RpcError as exc:
            cause = str(exc).split(':', 1)[1]
            if cause in NOT_AVAILABLE:
                raise CoverageError(f'block_not_available_STOP:{slot}:{cause}') from None
            raise
    return blocks


def main(argv=None, *, environ=None, opener=None, out=None, sleep=time.sleep):
    """Read-only: ``s0 --lo SLOT`` or ``audit --s0 S0 --run DIR``; dry run unless --network."""
    import argparse
    import sys
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description='W1 S0 and getBlock coverage audit (read-only)')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('s0')
    s.add_argument('--lo', type=int, required=True, help='a produced slot known to be before the anchor time')
    a = sub.add_parser('audit')
    a.add_argument('--s0', type=int, required=True)
    a.add_argument('--run', type=Path, help='verified LaunchLab W1 run directory (needed with --network)')
    d = sub.add_parser('slots')
    d.add_argument('--s0', type=int, required=True)
    for p, cap in ((s, 120), (a, 600)):
        p.add_argument('--network', action='store_true')
        p.add_argument('--endpoint-env', default='RUGGER_COVERAGE_RPC_URL')
        p.add_argument('--max-requests', type=int, default=cap, help='every attempt counts, retries included')
        p.add_argument('--log', type=Path, help='JSONL log of every attempt (required with --network)')
    args = parser.parse_args(argv)
    emit = lambda obj: out.write(json.dumps(obj, indent=1, sort_keys=True) + '\n')     # noqa: E731
    if args.command == 'slots':
        emit({'s0': args.s0, 'seed': AUDIT_SEED, 'slots': draw_audit_slots(args.s0)})
        return 0
    if not args.network:
        emit({'dry_run': True, 'requests_sent': 0, 'command': args.command,
              'message': 'no request sent; add --network to run (owner decision)'})
        return 0
    if args.log is None:
        raise CoverageError('network_runs_need_a_log_file')
    rpc = _rpc(environ, args.endpoint_env, args.max_requests, args.log, opener, sleep)
    if args.command == 's0':
        s0, calls, checks = find_s0_online(rpc, args.lo)
        emit(dict(s0=s0, target_block_time=FREEZE_ANCHOR_TIME, rpc_calls=calls, **checks))
        return 0
    if args.run is None:
        raise CoverageError('audit_needs_the_verified_run_directory')
    slots = draw_audit_slots(args.s0)
    collected = collected_signatures_by_slot(args.run, slots)        # verified before any request
    result = audit(fetch_blocks(rpc, slots), collected)
    emit(dict(result, s0=args.s0, seed=AUDIT_SEED))
    return 0 if result['verdict'] == 'PASS' else 4
