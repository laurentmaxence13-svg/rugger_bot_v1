"""w1aux.coverage: S0, drawn slots and their replacement, block summaries, fetch then compare."""
import hashlib
import io
import json
import random
import urllib.error
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import w1_collection
from w1aux import coverage as cov

LL = bf.LAUNCHLAB_PROGRAM
OTHER = 'So11111111111111111111111111111111111111112'
FIXTURES = Path(__file__).parent / 'fixtures'


# ----------------------------------------------------------------- S0
class Chain:
    """Produced slots every 1 to 3 slots, block time = 1000 + slot // 3 (monotone)."""

    def __init__(self, upto=20_000, seed=1):
        rnd, slot, self.produced = random.Random(seed), 100, []
        while slot < upto:
            self.produced.append(slot)
            slot += rnd.choice((1, 1, 2, 3))
        self.calls = []

    def time(self, slot):
        return 1_000 + slot // 3

    def first_produced(self, slot):
        self.calls.append(('first', slot))
        return next(p for p in self.produced if p >= slot)

    def produced_from(self, slot, limit=cov.PRODUCED_PAGE):
        return [p for p in self.produced if p >= slot][:limit]

    def block_time(self, slot):
        self.calls.append(('time', slot))
        assert slot in self.produced
        return self.time(slot)


def _expected(chain, target):
    return next(p for p in chain.produced if chain.time(p) >= target)


@pytest.mark.parametrize('target', [1_000 + 3_000, 1_000 + 3_001, 1_000 + 5_555, 1_000 + 6_600])
def test_find_s0_returns_the_first_produced_slot_at_or_after_the_target(target):
    chain = Chain()
    s0, calls, checks = cov.find_s0(chain.first_produced, chain.block_time, 150, 19_990, target)
    assert s0 == _expected(chain, target) and s0 in chain.produced
    assert checks['s0_block_time'] >= target > checks['previous_block_time']
    previous = max(p for p in chain.produced if p < s0)
    assert checks['previous_produced_slot'] == previous
    assert calls <= 2 * 16 + 6                                      # bisection, not a scan


def test_find_s0_with_a_long_gap_and_a_plateau_of_equal_block_times():
    class Plateau(Chain):
        def __init__(self):
            self.produced, self.calls = [100, 101, 102] + list(range(500, 520)) + [900, 901], []
            self.times = {100: 10, 101: 10, 102: 11}
            self.times.update({s: 50 for s in range(500, 510)})        # plateau before the target
            self.times.update({s: 60 for s in range(510, 520)})        # plateau AT the target
            self.times.update({900: 60, 901: 70})

        def time(self, slot):
            return self.times[slot]
    chain = Plateau()
    s0, _, checks = cov.find_s0(chain.first_produced, chain.block_time, 100, 901, 60)
    assert s0 == 510 and checks['previous_produced_slot'] == 509          # first slot of the plateau at 60
    s0, _, checks = cov.find_s0(chain.first_produced, chain.block_time, 100, 901, 55)
    assert s0 == 510
    s0, _, checks = cov.find_s0(chain.first_produced, chain.block_time, 100, 901, 12)
    assert s0 == 500 and checks['previous_produced_slot'] == 102          # across the gap 103..499


def test_find_s0_checks_its_bounds_and_inputs():
    chain = Chain()
    with pytest.raises(cov.CoverageError, match='lo_is_not_before_the_target'):
        cov.find_s0(chain.first_produced, chain.block_time, 15_000, 19_990, 1_000 + 3_000)
    with pytest.raises(cov.CoverageError, match='hi_is_not_after_the_target'):
        cov.find_s0(chain.first_produced, chain.block_time, 150, 900, 1_000 + 3_000)
    with pytest.raises(cov.CoverageError, match='invalid_first_produced_slot'):
        cov.find_s0(lambda s: s - 1, chain.block_time, 150, 19_990, 1_000 + 3_000)
    with pytest.raises(cov.CoverageError, match='missing_block_time'):
        cov.find_s0(chain.first_produced, lambda s: None, 150, 19_990, 1_000 + 3_000)


def test_freeze_anchor_time_is_2026_11_09T09_59Z():
    import datetime
    assert datetime.datetime.fromtimestamp(cov.FREEZE_ANCHOR_TIME, datetime.timezone.utc).isoformat() == \
        '2026-11-09T09:59:00+00:00'


# ----------------------------------------------------------------- drawn slots and replacement
def test_drawn_slots_are_200_distinct_slots_of_the_evaluation_range_and_reproducible():
    s0 = 470_000_000
    assert cov.evaluation_range(s0) == (s0 + 402_800, s0 + 2_015_600)
    assert cov.evaluation_range(s0, w1_collection.MIN_EVALUATION_SLOTS) == (s0 + 402_800, s0 + 402_800 + 806_400)
    slots = cov.draw_audit_slots(s0)
    assert len(slots) == len(set(slots)) == 200 and slots == sorted(slots)
    assert s0 + w1_collection.WARMUP_SLOTS <= slots[0] and slots[-1] <= s0 + 2_015_599
    assert slots == cov.draw_audit_slots(s0)
    assert slots == sorted(random.Random(20_261_108).sample(range(s0 + 402_800, s0 + 2_015_600), 200))
    assert cov.draw_audit_slots(s0 + 1) != slots
    short = cov.draw_audit_slots(s0, evaluation_slots=w1_collection.MIN_EVALUATION_SLOTS)
    assert short[-1] < s0 + 402_800 + w1_collection.MIN_EVALUATION_SLOTS


def _produced_from(produced, limit=cov.PRODUCED_PAGE, calls=None):
    def produced_from(slot):
        if calls is not None:
            calls.append(slot)
        return [p for p in produced if p >= slot][:limit]
    return produced_from


def test_a_skipped_drawn_slot_is_replaced_by_the_next_produced_slot():
    produced = [10, 11, 13, 14, 20, 21, 22, 30]
    slots, replacements = cov.resolve_audit_slots([10, 12, 15], _produced_from(produced), end=100)
    assert (slots, replacements) == ([10, 13, 20], [{'drawn': 12, 'replacement': 13}, {'drawn': 15, 'replacement': 20}])
    # 13 is itself drawn: the replacement of 12 skips it (audited slots stay distinct)
    slots, replacements = cov.resolve_audit_slots([10, 12, 13], _produced_from(produced), end=100)
    assert (slots, replacements) == ([10, 13, 14], [{'drawn': 12, 'replacement': 14}])
    # two skipped slots in a row with the same next produced slot: the second takes the following one
    slots, replacements = cov.resolve_audit_slots([15, 16], _produced_from(produced), end=100)
    assert (slots, replacements) == ([20, 21], [{'drawn': 15, 'replacement': 20}, {'drawn': 16, 'replacement': 21}])
    # a page with no eligible candidate asks the next page
    calls = []
    slots, replacements = cov.resolve_audit_slots([12, 13, 14], _produced_from(produced, limit=2, calls=calls), end=100)
    assert (slots, replacements) == ([13, 14, 20], [{'drawn': 12, 'replacement': 20}]) and calls == [12, 15, 13, 14]
    with pytest.raises(cov.CoverageError, match='no_replacement_in_the_evaluation_range_STOP:23'):
        cov.resolve_audit_slots([23], _produced_from(produced), end=30)
    assert cov.resolve_audit_slots([23], _produced_from(produced), end=31) == ([30], [{'drawn': 23, 'replacement': 30}])
    assert cov.resolve_audit_slots([21, 10], _produced_from(produced), end=100) == ([10, 21], [])


# ----------------------------------------------------------------- block parsing: accounts ≡ full
def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def test_fixture_pair_is_the_same_block_in_both_modes():
    full, accounts = _fixture('block_full.json'), _fixture('block_accounts.json')
    assert {k: v for k, v in full.items() if k != 'transactions'} == \
        {k: v for k, v in accounts.items() if k != 'transactions'}
    assert len(full['transactions']) == len(accounts['transactions']) == 6
    for f, a in zip(full['transactions'], accounts['transactions']):
        assert f['transaction']['signatures'] == a['transaction']['signatures'] and f['version'] == a['version']
        assert f['meta']['err'] == a['meta']['err'] and 'loadedAddresses' not in a['meta']
        loaded = f['meta']['loadedAddresses']
        static = f['transaction']['message']['accountKeys']
        assert [k['pubkey'] for k in a['transaction']['accountKeys']] == static + loaded['writable'] + loaded['readonly']
        assert [k['source'] for k in a['transaction']['accountKeys']] == \
            ['transaction'] * len(static) + ['lookupTable'] * (len(loaded['writable']) + len(loaded['readonly']))
    assert any(k['source'] == 'lookupTable' and k['pubkey'] == LL
               for tx in accounts['transactions'] for k in tx['transaction']['accountKeys'])


def test_accounts_and_full_give_exactly_the_same_launchlab_set_failures_included():
    full = cov.launchlab_entries(_fixture('block_full.json'), 'full')
    accounts = cov.launchlab_entries(_fixture('block_accounts.json'), 'accounts')
    assert full == accounts and len(full) == 4                     # static, loaded writable, loaded readonly, both
    assert sum(1 for e in full if e['err'] is not None) == 2
    block = _fixture('block_full.json')
    sigs = [tx['transaction']['signatures'][0] for tx in block['transactions']]
    assert [e['signature'] for e in full] == [sigs[0], sigs[1], sigs[2], sigs[5]]
    # the loaded keys are what makes the difference: without them both modes would miss two
    for tx in block['transactions']:
        tx['meta']['loadedAddresses'] = {'writable': [], 'readonly': []}
    assert len(cov.launchlab_entries(block, 'full')) == 2


def test_block_parsing_refuses_what_it_cannot_read_safely():
    accounts = _fixture('block_accounts.json')
    del accounts['transactions'][1]['transaction']['accountKeys'][2]['source']    # a loaded key, unlabelled
    with pytest.raises(cov.CoverageError, match='accounts_mode_key_without_source'):
        cov.launchlab_entries(accounts, 'accounts')
    with pytest.raises(cov.CoverageError, match='malformed_block_transaction'):
        cov.launchlab_entries(_fixture('block_full.json'), 'accounts')          # full shape read as accounts
    with pytest.raises(cov.CoverageError, match='malformed_block_transaction'):
        cov.launchlab_entries(_fixture('block_accounts.json'), 'full')          # accounts shape read as full
    accounts = _fixture('block_accounts.json')
    accounts['transactions'][0]['transaction']['accountKeys'][0] = LL     # a bare string: no source
    with pytest.raises(cov.CoverageError, match='accounts_mode_key_without_source'):
        cov.launchlab_entries(accounts, 'accounts')
    full = _fixture('block_full.json')
    del full['transactions'][1]['meta']['loadedAddresses']                  # versioned, loaded keys unknown
    with pytest.raises(cov.CoverageError, match='full_mode_versioned_transaction_without_loadedAddresses'):
        cov.launchlab_entries(full, 'full')
    full = _fixture('block_full.json')
    del full['transactions'][0]['meta']['loadedAddresses']                  # legacy: nothing can be loaded
    assert len(cov.launchlab_entries(full, 'full')) == 4
    full['transactions'][0]['transaction']['message']['accountKeys'][0] = {'pubkey': OTHER}
    with pytest.raises(cov.CoverageError, match='full_mode_malformed_account_keys'):
        cov.launchlab_entries(full, 'full')
    full = _fixture('block_full.json')
    full['transactions'][0]['meta'] = None
    with pytest.raises(cov.CoverageError, match='malformed_block_transaction'):
        cov.launchlab_entries(full, 'full')
    with pytest.raises(cov.CoverageError, match='malformed_block'):
        cov.launchlab_entries({'transactions': None}, 'full')
    with pytest.raises(cov.CoverageError, match='unknown_transaction_details'):
        cov.launchlab_entries(_fixture('block_full.json'), 'signatures')


def test_block_summary_keeps_no_block_but_a_canonical_hash():
    block = _fixture('block_accounts.json')
    summary = cov.summarize_block(467_700_100, block, 'accounts')
    assert set(summary) == {'slot', 'blockhash', 'parentSlot', 'blockTime', 'transactions', 'response_sha256', 'launchlab'}
    assert summary['transactions'] == 6 and summary['parentSlot'] == 467_700_099 and len(summary['launchlab']) == 4
    canonical = json.dumps(block, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert summary['response_sha256'] == hashlib.sha256(canonical).hexdigest()
    reordered = json.loads(json.dumps(block), object_pairs_hook=lambda pairs: dict(reversed(pairs)))
    assert cov.summarize_block(467_700_100, reordered, 'accounts')['response_sha256'] == summary['response_sha256']
    block['transactions'][0]['meta']['fee'] = 5001
    assert cov.summarize_block(467_700_100, block, 'accounts')['response_sha256'] != summary['response_sha256']
    for key, bad in (('blockhash', None), ('parentSlot', '1'), ('blockTime', 1.5)):
        broken = dict(_fixture('block_accounts.json'), **{key: bad})
        with pytest.raises(cov.CoverageError, match=f'malformed_block:{key}'):
            cov.summarize_block(1, broken, 'accounts')


# ----------------------------------------------------------------- collection side
def _collect(tmp_path, entries, window, cap=10_000):
    class FakeRpc:
        def __init__(self):
            self.entries = sorted(entries, key=lambda e: (e['slot'], e['transactionIndex']))

        def __call__(self, request, timeout):
            body = json.loads(request.data)
            method, (address, options) = body['method'], body['params']
            if method == 'getTransactionsForAddress':
                slot = options['filters']['slot']
                rows = [e for e in self.entries if slot['gte'] <= e['slot'] <= slot['lte']]
                if options['transactionDetails'] == 'signatures':
                    rows = [{'signature': e['transaction']['signatures'][0], 'slot': e['slot'], 'err': None,
                             'blockTime': e['blockTime']} for e in rows]
                result = {'data': rows, 'paginationToken': None}
            else:
                result = [] if 'before' in options else [
                    {'signature': e['transaction']['signatures'][0], 'slot': e['slot'], 'err': None,
                     'blockTime': e['blockTime'], 'memo': None, 'confirmationStatus': 'finalized'}
                    for e in reversed(self.entries)]
            return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result}).encode())
    budget = bf.CreditBudget(1_000, cap, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=FakeRpc())
    return bf.Backfill(rpc, bf.Window(LL, *window), tmp_path).run()


def _entry(slot, i, signature=None):
    return {'slot': slot, 'blockTime': 1_700_000_000 + slot, 'transactionIndex': i,
            'transaction': {'signatures': [signature or f's{slot}x{i}'], 'message': {'accountKeys': [LL]}},
            'meta': {'err': None}}


def test_collected_signatures_need_a_verified_complete_run(tmp_path):
    manifest = _collect(tmp_path / 'run', [_entry(5, 0), _entry(5, 1), _entry(7, 0)], (1, 9))
    assert manifest['complete']
    assert cov.collected_signatures_by_slot(tmp_path / 'run', [5, 6, 7]) == {5: {'s5x0', 's5x1'}, 6: set(), 7: {'s7x0'}}
    stopped = _collect(tmp_path / 'stopped', [_entry(5, 0), _entry(7, 0)], (1, 9), cap=5)
    assert not stopped['complete'] and bf.verify(tmp_path / 'stopped')['ok']
    with pytest.raises(cov.CoverageError, match='collection_not_verified_or_incomplete'):
        cov.collected_signatures_by_slot(tmp_path / 'stopped', [5])
    seg = next(p for p in (tmp_path / 'run').glob('tx-*.jsonl.gz'))
    seg.write_bytes(seg.read_bytes() + b'\n')
    with pytest.raises(cov.CoverageError, match='collection_not_verified_or_incomplete'):
        cov.collected_signatures_by_slot(tmp_path / 'run', [5])


# ----------------------------------------------------------------- network fakes and command
S0 = 467_276_000
SMALL = w1_collection.MIN_EVALUATION_SLOTS            # keeps the fake chain small: the draw is still 200 slots


class BlockRpc:
    """Fake public RPC: produced slots = all slots except ``skipped``; getBlock from ``blocks``."""

    def __init__(self, blocks=None, skipped=(), unavailable=(), refused=(), throttle_once=(), finalized=None,
                 chain=None, null=()):
        self.blocks, self.skipped, self.calls, self.params = blocks or {}, set(skipped), [], []
        self.null = set(null)
        self.unavailable, self.refused, self.throttle = set(unavailable), set(refused), set(throttle_once)
        self.finalized = S0 + 3_000_000 if finalized is None else finalized
        self.chain = chain

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        method, params = body['method'], body['params']
        self.calls.append(method)
        self.params.append((method, params))
        error = None
        if params and isinstance(params[0], int) and (method, params[0]) in self.throttle:
            self.throttle.discard((method, params[0]))
            raise urllib.error.HTTPError('https://public.example.test/', 429, 'busy', {}, None)
        if method == 'getSlot':
            result = self.chain.produced[-1] if self.chain else self.finalized
        elif method == 'getBlocksWithLimit':
            if self.chain:
                result = self.chain.produced_from(params[0], params[1])
            else:
                result, slot = [], params[0]
                while len(result) < params[1]:
                    if slot not in self.skipped:
                        result.append(slot)
                    slot += 1
        elif method == 'getBlockTime':
            result = self.chain.block_time(params[0])
        elif params[0] in self.unavailable:
            result, error = None, {'code': -32009, 'message': 'missing in long-term storage'}
        elif params[0] in self.null:
            result = None
        elif params[0] in self.refused:
            result, error = None, {'code': -32015, 'message': 'Transaction version (1) is not supported'}
        else:
            block = self.blocks.get(params[0])
            result = block if block is not None else {'blockhash': f'h{params[0]}', 'parentSlot': params[0] - 1,
                                                      'blockTime': 1_794_300_000, 'transactions': []}
        payload = {'jsonrpc': '2.0', 'id': 1, 'result': result} if error is None else \
            {'jsonrpc': '2.0', 'id': 1, 'error': error}
        return io.BytesIO(json.dumps(payload).encode())


ENV = {'RUGGER_NO_DOTENV': '1', 'RUGGER_COVERAGE_RPC_URL': 'https://public.example.test/'}


def _main(args, opener=None, environ=ENV):
    out = io.StringIO()
    code = cov.main(args, environ=environ, opener=opener, out=out, sleep=lambda s: None)
    return code, json.loads(out.getvalue())


def _fetch_args(tmp_path, name='summary.json', extra=()):
    return ['fetch', '--s0', str(S0), '--out', str(tmp_path / name), '--max-tx-version', '1',
            '--evaluation-slots', str(SMALL), '--network', '--log', str(tmp_path / f'{name}.log'), *extra]


def test_command_dry_runs_slots_and_s0(tmp_path):
    code, report = _main(['s0', '--lo', '150'])
    assert code == 0 and report['requests_sent'] == 0
    code, report = _main(['fetch', '--s0', str(S0), '--out', str(tmp_path / 'x.json'), '--max-tx-version', '0'])
    assert code == 0 and report['requests_sent'] == 0 and not (tmp_path / 'x.json').exists()
    with pytest.raises(SystemExit):
        _main(['fetch', '--s0', str(S0), '--out', str(tmp_path / 'x.json')])         # version is not defaulted
    code, report = _main(['slots', '--s0', '470000000'])
    assert code == 0 and report['drawn'] == cov.draw_audit_slots(470_000_000) and report['seed'] == 20_261_108
    chain = Chain()
    target = 1_000 + 4_000
    original = cov.FREEZE_ANCHOR_TIME
    cov.FREEZE_ANCHOR_TIME = target
    try:
        code, report = _main(['s0', '--lo', '150', '--network', '--log', str(tmp_path / 's0.jsonl')],
                             opener=BlockRpc(chain=chain))
    finally:
        cov.FREEZE_ANCHOR_TIME = original
    assert code == 0 and report['s0'] == _expected(chain, target)
    assert report['requests_used'] == report['bisection_steps'] + 1           # + getSlot; proof reads counted
    assert 'public.example.test' not in json.dumps(report)
    with pytest.raises(cov.CoverageError, match='RUGGER_NO_DOTENV'):
        _main(['s0', '--lo', '150', '--network', '--log', str(tmp_path / 'x.jsonl')], opener=BlockRpc(chain=chain),
              environ={})
    with pytest.raises(cov.CoverageError, match='network_runs_need_a_log_file'):
        _main(['s0', '--lo', '150', '--network'], opener=BlockRpc(chain=chain))
    log = (tmp_path / 's0.jsonl').read_text()
    assert all(json.loads(line)['outcome'] == 'ok' for line in log.splitlines()) and 'public.example.test' not in log


def test_fetch_then_compare_end_to_end(tmp_path, monkeypatch):
    drawn = cov.draw_audit_slots(S0, evaluation_slots=SMALL)
    skipped = drawn[3]
    target, other = drawn[10], drawn[20]
    block = _fixture('block_accounts.json')
    rpc = BlockRpc({target: block}, skipped=[skipped], throttle_once=[('getBlock', other)])
    code, report = _main(_fetch_args(tmp_path), opener=rpc)
    assert code == 0 and report['slots'] == 200 and report['replacements'] == 1 and report['launchlab_transactions'] == 4
    summary_path = tmp_path / 'summary.json'
    assert report['summary_sha256'] == hashlib.sha256(summary_path.read_bytes()).hexdigest()
    summary = json.loads(summary_path.read_text())
    assert summary['replacements'] == [{'drawn': skipped, 'replacement': skipped + 1}]
    assert summary['max_supported_transaction_version'] == 1 and summary['transaction_details'] == 'accounts'
    assert summary['drawn'] == drawn and len(summary['slots']) == 200 and skipped not in summary['slots']
    assert 'transactions' not in json.dumps(summary['blocks'][0]).replace('"transactions": ', '')     # no block kept
    getblock = [p for m, p in rpc.params if m == 'getBlock']
    assert getblock[0][1] == {'encoding': 'json', 'transactionDetails': 'accounts', 'maxSupportedTransactionVersion': 1,
                              'rewards': False, 'commitment': 'finalized'}
    assert rpc.calls.count('getBlock') == 201 and rpc.calls.count('getBlocksWithLimit') == 200   # one retry
    assert report['requests_used'] == 1 + 200 + 201
    lines = [json.loads(line) for line in (tmp_path / 'summary.json.log').read_text().splitlines()]
    events = [line for line in lines if 'event' in line]
    assert [(e['event'], e['drawn'], e['replacement']) for e in events] == \
        [('skipped_drawn_slot_replaced', skipped, skipped + 1)]
    assert 'public.example.test' not in (tmp_path / 'summary.json.log').read_text()
    retried = [l for l in lines if l.get('method') == 'getBlock' and l['params'][0] == other]
    assert [l['outcome'] for l in retried] == ['http_429', 'ok'] and [l['attempt'] for l in retried] == [1, 2]
    with pytest.raises(cov.CoverageError, match='summary_file_already_exists'):
        _main(_fetch_args(tmp_path), opener=BlockRpc())

    # phase 2: compare, offline, against the anchored sha256
    sigs = [e['signature'] for e in cov.launchlab_entries(block, 'accounts')]
    _collect(tmp_path / 'run', [_entry(target, i, s) for i, s in enumerate(sigs)] + [_entry(S0 + 5, 0)],
             (S0, S0 + 2_000_000))
    args = ['compare', '--summary', str(summary_path), '--summary-sha256', report['summary_sha256'],
            '--run', str(tmp_path / 'run')]
    code, result = _main(args)
    assert code == 0 and result['verdict'] == 'PASS' and result['launchlab_transactions'] == 4
    assert result['launchlab_failed_transactions'] == 2 and result['replacements'] == 1
    with pytest.raises(cov.CoverageError, match='summary_sha256_does_not_match_the_anchor'):
        _main(args[:4] + ['0' * 64] + args[5:])
    _collect(tmp_path / 'short', [_entry(target, i, s) for i, s in enumerate(sigs[:-1])], (S0, S0 + 2_000_000))
    code, result = _main(args[:-1] + [str(tmp_path / 'short')])                 # one signature missing, nothing else
    assert code == 4 and result['verdict'] == 'FAIL'
    assert result['missing'] == {str(target): [sigs[-1]]} and result['collected_not_in_block'] == {}
    _collect(tmp_path / 'ghost', [_entry(target, i, s) for i, s in enumerate(sigs)] + [_entry(other, 0, 'ghost')],
             (S0, S0 + 2_000_000))
    code, result = _main(args[:-1] + [str(tmp_path / 'ghost')])                 # nothing missing, one foreign
    assert code == 4 and result['verdict'] == 'FAIL'
    assert result['missing'] == {} and result['collected_not_in_block'] == {str(other): ['ghost']}


def test_fetch_stops_and_refusals(tmp_path):
    drawn = cov.draw_audit_slots(S0, evaluation_slots=SMALL)
    code, report = _main(_fetch_args(tmp_path, 'a.json'), opener=BlockRpc(unavailable=[drawn[7]]))
    assert code == 5 and report['verdict'] == 'STOP' and report['cause'].startswith(f'block_not_available_STOP:{drawn[7]}')
    assert not (tmp_path / 'a.json').exists()
    code, report = _main(_fetch_args(tmp_path, 'b.json'), opener=BlockRpc(refused=[drawn[0]]))
    assert code == 5 and report['cause'] == f'transaction_version_refused_STOP:{drawn[0]}:rpc_error_-32015'
    code, report = _main(_fetch_args(tmp_path, 'n.json'), opener=BlockRpc(null=[drawn[2]]))
    assert code == 5 and report['cause'] == f'block_not_available_STOP:{drawn[2]}:null'
    window_slot_max = w1_collection.bounds(S0, SMALL)['window_slot_max']
    with pytest.raises(cov.CoverageError, match='window_not_finished'):
        _main(_fetch_args(tmp_path, 'c.json'), opener=BlockRpc(finalized=window_slot_max))
    code, _ = _main(_fetch_args(tmp_path, 'd.json'), opener=BlockRpc(finalized=window_slot_max + 1))
    assert code == 0
    from bot.market.collector import BudgetExhausted
    with pytest.raises(BudgetExhausted):
        _main(_fetch_args(tmp_path, 'e.json', ['--max-requests', '50']), opener=BlockRpc())
    assert not (tmp_path / 'e.json').exists()


def test_unexpected_getblockswithlimit_answers_stop_the_fetch():
    class Odd:
        def __init__(self, answer):
            self.answer = answer

        def call(self, method, params):
            return self.answer
    for answer in ([], None, [4], [6, 6], [6, 5], ['6']):
        with pytest.raises(cov.CoverageError, match='unexpected_getBlocksWithLimit_answer:5'):
            cov.produced_from_online(Odd(answer))(5)
    assert cov.produced_from_online(Odd([5, 7]))(5) == [5, 7]


def test_a_tampered_or_foreign_summary_is_refused(tmp_path):
    rpc = BlockRpc(skipped=[cov.draw_audit_slots(S0, evaluation_slots=SMALL)[0]])
    code, report = _main(_fetch_args(tmp_path), opener=rpc)
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert cov.check_summary(summary) == summary['slots']
    for mutate, cause in (
            (lambda s: s.update(schema='other'), 'not_a_coverage_summary'),
            (lambda s: s.update(s0=S0 + 1), 'summary_drawn_slots_do_not_match_the_protocol_draw'),
            (lambda s: s['blocks'].pop(), 'summary_audited_slots_inconsistent'),
            (lambda s: s['replacements'].clear(), 'summary_audited_slots_inconsistent'),
            (lambda s: s['slots'].reverse(), 'summary_audited_slots_inconsistent')):
        broken = json.loads(json.dumps(summary))
        mutate(broken)
        with pytest.raises(cov.CoverageError, match=cause):
            cov.check_summary(broken)
    far = json.loads(json.dumps(summary))
    end = far['evaluation_range'][1]
    far['replacements'][0]['replacement'] = end
    far['blocks'][0]['slot'] = end
    far['slots'] = sorted([end] + far['slots'][1:])
    far['blocks'].sort(key=lambda b: b['slot'])
    with pytest.raises(cov.CoverageError, match='summary_slot_outside_the_evaluation_range'):
        cov.check_summary(far)
