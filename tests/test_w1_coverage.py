"""W1 S0 search and getBlock coverage audit (bot/market/w1_coverage.py), offline with fake RPCs."""
import io
import json
import random

import pytest

from bot.market import backfill as bf
from bot.market import w1_collection
from bot.market import w1_coverage as cov

LL = bf.LAUNCHLAB_PROGRAM
OTHER = 'So11111111111111111111111111111111111111112'


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


# ----------------------------------------------------------------- audit slots
def test_audit_slots_are_200_distinct_slots_of_the_evaluation_range_and_reproducible():
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


# ----------------------------------------------------------------- block parsing and audit
def _tx(signature, keys, loaded=(), err=None):
    return {'transaction': {'signatures': [signature], 'message': {'accountKeys': list(keys)}},
            'meta': {'err': err, 'loadedAddresses': {'writable': list(loaded), 'readonly': []}}}


def _acc(signature, keys, err=None):
    """transactionDetails 'accounts': keys listed with their source (static or lookupTable)."""
    return {'transaction': {'signatures': [signature],
                            'accountKeys': [{'pubkey': k, 'signer': i == 0, 'source': 'lookupTable' if i else 'transaction',
                                             'writable': False} for i, k in enumerate(keys)]},
            'meta': {'err': err}, 'version': 0}


def test_launchlab_signatures_cover_static_and_loaded_keys_and_failures():
    block = {'blockTime': 1, 'transactions': [
        _tx('a', [OTHER, LL]), _tx('b', [OTHER], loaded=[LL]), _tx('c', [OTHER]),
        _tx('d', [{'pubkey': LL, 'signer': False}]), _tx('e', [LL], err={'x': 1}),
        _acc('f', [OTHER, LL]), _acc('g', [OTHER]), _acc('h', [OTHER, LL], err={'y': 2})]}
    assert cov.launchlab_signatures(block) == ['a', 'b', 'd', 'e', 'f', 'h']
    with pytest.raises(cov.CoverageError, match='malformed_block'):
        cov.launchlab_signatures({'transactions': None})
    with pytest.raises(cov.CoverageError, match='malformed_block_transaction'):
        cov.launchlab_signatures({'transactions': [{'transaction': {}}]})


def test_audit_threshold_zero_and_skipped_slots():
    blocks = {10: {'transactions': [_tx('a', [LL]), _tx('x', [OTHER])]}, 11: None,
              12: {'transactions': [_tx('b', [LL]), _tx('c', [OTHER], loaded=[LL])]}}
    collected = {10: {'a'}, 11: set(), 12: {'b', 'c'}}
    result = cov.audit(blocks, collected)
    assert result['verdict'] == 'PASS' and result['launchlab_transactions'] == 3
    assert result['skipped_slots'] == [11] and result['missing'] == {}
    lost = cov.audit(blocks, {**collected, 12: {'b'}})
    assert lost['verdict'] == 'FAIL' and lost['missing'] == {12: ['c']}
    contradiction = cov.audit(blocks, {**collected, 11: {'z'}})
    assert contradiction['verdict'] == 'FAIL' and contradiction['collected_in_skipped_slots'] == [11]


# ----------------------------------------------------------------- collection side and command
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


def _entry(slot, i):
    return {'slot': slot, 'blockTime': 1_700_000_000 + slot, 'transactionIndex': i,
            'transaction': {'signatures': [f's{slot}x{i}'], 'message': {'accountKeys': [LL]}}, 'meta': {'err': None}}


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


class BlockRpc:
    """Fake public RPC for the command: getSlot, getBlocksWithLimit, getBlockTime, getBlock."""

    def __init__(self, chain, blocks, skipped=(), unavailable=(), throttle_once=()):
        self.chain, self.blocks, self.skipped, self.calls = chain, blocks, set(skipped), []
        self.unavailable, self.throttle = set(unavailable), set(throttle_once)

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        method, params = body['method'], body['params']
        self.calls.append(method)
        error = None
        if params and isinstance(params[0], int) and (method, params[0]) in self.throttle:
            self.throttle.discard((method, params[0]))
            import urllib.error
            raise urllib.error.HTTPError('https://public.example.test/', 429, 'busy', {}, None)
        if method == 'getBlocks':
            result = [] if params[0] in self.skipped else [params[0]]
        elif method == 'getSlot':
            result = self.chain.produced[-1]
        elif method == 'getBlocksWithLimit':
            result = [self.chain.first_produced(params[0])]
        elif method == 'getBlockTime':
            result = self.chain.block_time(params[0])
        elif params[0] in self.unavailable:
            result, error = None, {'code': -32009, 'message': 'missing in long-term storage'}
        else:
            result = self.blocks.get(params[0], {'transactions': []})
        payload = {'jsonrpc': '2.0', 'id': 1, 'result': result} if error is None else \
            {'jsonrpc': '2.0', 'id': 1, 'error': error}
        return io.BytesIO(json.dumps(payload).encode())


ENV = {'RUGGER_NO_DOTENV': '1', 'RUGGER_COVERAGE_RPC_URL': 'https://public.example.test/'}


def _main(args, opener=None, environ=ENV):
    out = io.StringIO()
    code = cov.main(args, environ=environ, opener=opener, out=out, sleep=lambda s: None)
    return code, json.loads(out.getvalue())


def test_command_dry_run_slots_and_s0(tmp_path):
    code, report = _main(['s0', '--lo', '150'])
    assert code == 0 and report['requests_sent'] == 0
    code, report = _main(['slots', '--s0', '470000000'])
    assert code == 0 and report['slots'] == cov.draw_audit_slots(470_000_000) and report['seed'] == 20_261_108
    chain = Chain()
    target = 1_000 + 4_000
    original = cov.FREEZE_ANCHOR_TIME
    cov.FREEZE_ANCHOR_TIME = target
    try:
        rpc = BlockRpc(chain, {})
        code, report = _main(['s0', '--lo', '150', '--network', '--log', str(tmp_path / 's0.jsonl')], opener=rpc)
    finally:
        cov.FREEZE_ANCHOR_TIME = original
    assert code == 0 and report['s0'] == _expected(chain, target)
    assert 'public.example.test' not in json.dumps(report)
    with pytest.raises(cov.CoverageError, match='RUGGER_NO_DOTENV'):
        _main(['s0', '--lo', '150', '--network', '--log', str(tmp_path / 'x.jsonl')], opener=BlockRpc(chain, {}), environ={})
    with pytest.raises(cov.CoverageError, match='network_runs_need_a_log_file'):
        _main(['s0', '--lo', '150', '--network'], opener=BlockRpc(chain, {}))
    log = [json.loads(line) for line in (tmp_path / 's0.jsonl').read_text().splitlines()]
    assert log and all(line['outcome'] == 'ok' for line in log) and 'public.example.test' not in (tmp_path / 's0.jsonl').read_text()


def test_command_audit_end_to_end(tmp_path, monkeypatch):
    s0 = 1
    monkeypatch.setattr(cov, 'draw_audit_slots', lambda s0: [5, 6, 7])
    _collect(tmp_path / 'run', [_entry(5, 0), _entry(7, 0)], (1, 9))
    blocks = {5: {'transactions': [_tx('s5x0', [LL]), _tx('noise', [OTHER])]}, 7: {'transactions': [_tx('s7x0', [LL])]}}
    log = tmp_path / 'audit.jsonl'
    args = ['audit', '--s0', str(s0), '--run', str(tmp_path / 'run'), '--network', '--log', str(log)]
    rpc = BlockRpc(Chain(), blocks, skipped=[6], throttle_once=[('getBlock', 7)])
    code, report = _main(args, opener=rpc)
    assert code == 0 and report['verdict'] == 'PASS' and report['skipped_slots'] == [6]
    assert rpc.calls.count('getBlock') == 3 and rpc.calls.count('getBlocks') == 3     # slot 6 skipped: no getBlock; 7 retried
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    retried = [line for line in lines if line['method'] == 'getBlock' and line['params'][0] == 7]
    assert [line['outcome'] for line in retried] == ['http_429', 'ok'] and [l['attempt'] for l in retried] == [1, 2]
    blocks[7]['transactions'].append(_tx('lost', [LL]))
    code, report = _main(args, opener=BlockRpc(Chain(), blocks, skipped=[6]))
    assert code == 4 and report['missing'] == {'7': ['lost']}
    with pytest.raises(cov.CoverageError, match='audit_needs_the_verified_run_directory'):
        _main(['audit', '--s0', '1', '--network', '--log', str(log)], opener=BlockRpc(Chain(), blocks))
    with pytest.raises(cov.CoverageError, match='block_not_available_STOP:7:rpc_error_-32009'):
        _main(args, opener=BlockRpc(Chain(), blocks, skipped=[6], unavailable=[7]))
    from bot.market.collector import BudgetExhausted
    with pytest.raises(BudgetExhausted):
        _main(args + ['--max-requests', '3'], opener=BlockRpc(Chain(), blocks, skipped=[6]))


def test_an_unexpected_getblocks_answer_stops_the_audit():
    class Odd:
        def __init__(self):
            self.calls = []

        def call(self, method, params):
            self.calls.append(method)
            return [params[0] + 1]                        # a slot other than the one asked
    rpc = Odd()
    with pytest.raises(cov.CoverageError, match='unexpected_getBlocks_answer:5'):
        cov.fetch_blocks(rpc, [5])
    assert rpc.calls == ['getBlocks']
