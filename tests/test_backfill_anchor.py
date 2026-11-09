"""--anchor-after-window: the getSignaturesForAddress listing starts after the window, not at the head.

R02 audit points: the anchor is the FIRST request, charged before it is sent; no GSFA request leaves
without ``before``; the anchor must be a successful transaction strictly after slot_max, recorded in
state and manifest and checked by verify(); the window stays exact when slot_max + 1 holds several
transactions; off by default; plan() counts it; gtfa, rpc and sampled modes are covered.
"""
import importlib.util
import io
import json
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import backfill_cli
from bot.market import w1_collection

ADDRESS = '7UVimffxr9ow1uXYxsr4LHAcV58mLzhmwaeKvJ1pjLiE'
WINDOW = (1_000, 1_999)
COSTS = bf.COST_PRESETS[w1_collection.COSTS]


def _entry(slot, index, err=None):
    return {'slot': slot, 'blockTime': 1_700_000_000 + slot, 'transactionIndex': index,
            'transaction': {'signatures': [f's{slot}x{index}'], 'message': {}}, 'meta': {'err': err}}


def _sig(e):
    return e['transaction']['signatures'][0]


class Chain:
    """Fake Helius RPC: GTFA (full or signatures; slot and status filters; asc; limit), GSFA (newest
    first, ``before`` exclusive) and getTransaction. ``strict``: a GSFA request without ``before`` fails."""

    def __init__(self, entries, *, strict=False, gtfa_order=None):
        self.entries = sorted(entries, key=lambda e: (e['slot'], e['transactionIndex']))
        self.strict, self.gtfa_order, self.calls = strict, gtfa_order, []

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        method, params = body['method'], body['params']
        self.calls.append((method, params[1]))
        result = getattr(self, method)(*params)
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result}).encode())

    def _row(self, e):
        return {'signature': _sig(e), 'slot': e['slot'], 'err': e['meta']['err'], 'blockTime': e['blockTime'],
                'transactionIndex': e['transactionIndex']}

    def getTransactionsForAddress(self, address, options):
        assert address == ADDRESS
        slot, status = options['filters']['slot'], options['filters']['status']
        rows = [e for e in (self.gtfa_order or self.entries)
                if slot.get('gte', 0) <= e['slot'] <= slot.get('lte', 10 ** 12)
                and (status == 'any' or e['meta']['err'] is None)]
        start = int(options.get('paginationToken') or 0)
        page = rows[start:start + options['limit']]
        more = start + options['limit'] < len(rows)
        if options['transactionDetails'] == 'signatures':
            page = [self._row(e) for e in page]
        return {'data': page, 'paginationToken': str(start + options['limit']) if more else None}

    def getSignaturesForAddress(self, address, options):
        assert address == ADDRESS
        if self.strict:
            assert 'before' in options, 'GSFA without before: listing from the chain head'
        newest_first = list(reversed(self.entries))
        sigs = [_sig(e) for e in newest_first]
        start = sigs.index(options['before']) + 1 if 'before' in options else 0
        return [dict(self._row(e), memo=None, confirmationStatus='finalized')
                for e in newest_first[start:start + options['limit']]]

    def getTransaction(self, signature, options):
        return next(e for e in self.entries if _sig(e) == signature)


def _entries(after=2_500):
    inside = [_entry(WINDOW[0] + 3 * i, 0) for i in range(300)]          # 300 tx inside the window
    before = [_entry(WINDOW[0] - 1 - i, 0) for i in range(5)]
    later = [_entry(WINDOW[1] + 1 + i, i % 2) for i in range(after)]     # the chain after the window
    return before + inside + later


def _run(tmp_path, chain, cap=1_000, **options):
    budget = bf.CreditBudget(1_000, cap, COSTS, ledger=Path(tmp_path) / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=chain)
    return bf.Backfill(rpc, bf.Window(ADDRESS, *WINDOW), tmp_path, **options).run()


def test_default_is_unchanged_and_lists_from_the_head(tmp_path):
    chain = Chain(_entries())
    manifest = _run(tmp_path, chain)
    assert manifest['complete'] and manifest['gsfa_anchor'] is None
    assert not any(o.get('limit') == 1 for _, o in chain.calls)
    assert sum(1 for m, _ in chain.calls if m == 'getSignaturesForAddress') == 3     # 2500 newer + 300 + 5
    assert manifest['budget']['credits'] == 3 * 10 + 3


def test_anchor_is_the_first_request_and_no_gsfa_leaves_without_before(tmp_path):
    chain = Chain(_entries(), strict=True)
    manifest = _run(tmp_path, chain, anchor_after_window=True)
    assert manifest['complete'] and manifest['reconciliation']['equal']
    assert manifest['totals']['transactions'] == 300
    assert manifest['gsfa_anchor'] == {'signature': 's2000x0', 'slot': 2_000, 'transaction_index': 0}
    method, first = chain.calls[0]
    assert method == 'getTransactionsForAddress' and first['limit'] == 1
    assert first['filters'] == {'status': 'succeeded', 'slot': {'gte': 2_000}}
    assert first['transactionDetails'] == 'signatures' and first['sortOrder'] == 'asc'
    gsfa = [o for m, o in chain.calls if m == 'getSignaturesForAddress']
    assert len(gsfa) == 1 and gsfa[0]['before'] == 's2000x0'
    assert manifest['budget']['credits'] == 10 + 3 * 10 + 1
    assert bf.verify(tmp_path)['ok']


def test_anchor_is_charged_before_it_is_sent(tmp_path):
    chain = Chain(_entries(), strict=True)
    manifest = _run(tmp_path, chain, cap=9, anchor_after_window=True)
    assert chain.calls == [] and manifest['stopped_by'].startswith('credit_cap_reached')
    assert not manifest['complete'] and manifest['gsfa_anchor'] is None
    assert json.loads((tmp_path / 'spend.json').read_text())['credits'] == 0


def test_rpc_mode_lists_from_the_anchor_too(tmp_path):
    chain = Chain(_entries(), strict=True)
    manifest = _run(tmp_path, chain, bodies='rpc', anchor_after_window=True)
    assert manifest['complete'] and manifest['totals']['transactions'] == 300
    assert chain.calls[0][0] == 'getTransactionsForAddress' and chain.calls[0][1]['limit'] == 1
    assert manifest['gsfa_anchor']['slot'] == 2_000


def test_several_transactions_in_the_first_slot_after_the_window(tmp_path):
    entries = [e for e in _entries(after=0)] + [_entry(2_000, i) for i in range(3)] + [_entry(2_001, 0)]
    manifest = _run(tmp_path / 'a', Chain(entries, strict=True), anchor_after_window=True)
    assert manifest['complete'] and manifest['gsfa_anchor']['signature'] == 's2000x0'
    assert manifest['totals']['transactions'] == 300 and manifest['reconciliation']['equal']
    # A provider whose GTFA order disagrees with GSFA within the slot: rows of slot 2000 listed
    # before the anchor are still dropped by the slot filter, and no window row is lost.
    odd = sorted(entries, key=lambda e: (e['slot'], -e['transactionIndex']))
    manifest = _run(tmp_path / 'b', Chain(entries, strict=True, gtfa_order=odd), anchor_after_window=True)
    assert manifest['gsfa_anchor']['signature'] == 's2000x2'
    assert manifest['complete'] and manifest['totals']['transactions'] == 300 and manifest['reconciliation']['equal']


def test_a_failed_first_transaction_is_skipped_by_the_status_filter(tmp_path):
    entries = _entries(after=0) + [_entry(2_000, 0, err={'InstructionError': [0, 'Custom']}), _entry(2_000, 1)]
    manifest = _run(tmp_path, Chain(entries, strict=True), anchor_after_window=True)
    assert manifest['gsfa_anchor'] == {'signature': 's2000x1', 'slot': 2_000, 'transaction_index': 1}
    assert manifest['complete']


class Answer(Chain):
    def __init__(self, data, **kw):
        super().__init__(_entries(), **kw)
        self.data = data

    def getTransactionsForAddress(self, address, options):
        if options['limit'] == 1:
            return {'data': self.data, 'paginationToken': None}
        return super().getTransactionsForAddress(address, options)


@pytest.mark.parametrize('data', [
    [{'signature': 'inside', 'slot': WINDOW[1], 'err': None}],
    [{'signature': 'failed', 'slot': 2_000, 'err': {'x': 1}}],
    [{'signature': '', 'slot': 2_000, 'err': None}],
    [{'signature': 'idx', 'slot': 2_000, 'err': None, 'transactionIndex': '0'}],
    [{'signature': 'noidx', 'slot': 2_000, 'err': None}],
    [{'signature': 'negidx', 'slot': 2_000, 'err': None, 'transactionIndex': -1}],
    [{'signature': 'noslot', 'err': None}],
    ['not-a-dict'],
])
def test_an_invalid_anchor_stops_the_run(tmp_path, data):
    chain = Answer(data, strict=True)
    with pytest.raises(bf.BackfillError, match='anchor_not_a_successful_transaction_after_the_window'):
        _run(tmp_path, chain, anchor_after_window=True)
    assert [m for m, _ in chain.calls] == ['getTransactionsForAddress']


def test_anchor_errors(tmp_path):
    with pytest.raises(bf.BackfillError, match='exclusive'):
        _run(tmp_path / 'a', Chain(_entries()), anchor_after_window=True, before_signature='x')
    with pytest.raises(bf.BackfillError, match='needs_the_gsfa_listing'):
        _run(tmp_path / 'b', Chain(_entries()), anchor_after_window=True, check=False)
    chain = Chain(_entries(after=0), strict=True)
    with pytest.raises(bf.BackfillError, match='no_transaction_after_the_window'):
        _run(tmp_path / 'c', chain, anchor_after_window=True)
    assert [m for m, _ in chain.calls] == ['getTransactionsForAddress']
    with pytest.raises(bf.BackfillError, match='malformed_result'):
        _run(tmp_path / 'd', Answer(None), anchor_after_window=True)


def test_anchor_is_committed_and_reused_on_resume(tmp_path):
    chain = Chain(_entries(), strict=True)
    stopped = _run(tmp_path, chain, cap=40, anchor_after_window=True)          # 10 anchor + 30 GTFA: GSFA stops
    assert not stopped['complete'] and stopped['stopped_by'].startswith('credit_cap_reached')
    assert stopped['gsfa_anchor']['signature'] == 's2000x0'
    chain.calls.clear()
    resumed = _run(tmp_path, chain, cap=60, anchor_after_window=True)
    assert resumed['complete'] and [m for m, _ in chain.calls] == ['getSignaturesForAddress']
    assert chain.calls[0][1]['before'] == 's2000x0'


def test_verify_checks_the_anchor(tmp_path):
    _run(tmp_path, Chain(_entries(), strict=True), anchor_after_window=True)
    assert bf.verify(tmp_path)['ok']
    manifest_path, state_path = tmp_path / 'manifest.json', tmp_path / 'state.json'
    manifest, state = json.loads(manifest_path.read_text()), json.loads(state_path.read_text())
    for anchor in ({'signature': 's2000x0', 'slot': WINDOW[1], 'transaction_index': 0},
                   {'signature': 'other', 'slot': 2_000, 'transaction_index': 0},
                   {'signature': '', 'slot': 2_000, 'transaction_index': 0}, 'x'):
        manifest_path.write_text(json.dumps(dict(manifest, gsfa_anchor=anchor)))
        assert 'gsfa_anchor_invalid' in bf.verify(tmp_path)['problems']
    manifest_path.write_text(json.dumps(manifest))
    state['phases']['anchor']['cursor'] = {'signature': 'forged', 'slot': 2_000, 'transaction_index': 0}
    state_path.write_text(json.dumps(state))
    assert 'gsfa_anchor_invalid' in bf.verify(tmp_path)['problems']
    for anchor in ({'signature': 's1999x0', 'slot': WINDOW[1], 'transaction_index': 0},     # same in both files
                   {'signature': '', 'slot': 2_000, 'transaction_index': 0}):
        manifest_path.write_text(json.dumps(dict(manifest, gsfa_anchor=anchor)))
        state['phases']['anchor']['cursor'] = anchor
        state_path.write_text(json.dumps(state))
        assert 'gsfa_anchor_invalid' in bf.verify(tmp_path)['problems']


def test_plan_and_cli_count_the_anchor_call(tmp_path):
    window = bf.Window(ADDRESS, *WINDOW)
    base = bf.plan(window, COSTS, expected_tx_per_slot=0.3)
    anchored = bf.plan(window, COSTS, expected_tx_per_slot=0.3, anchor=True)
    assert anchored['requests']['getTransactionsForAddress'] == base['requests']['getTransactionsForAddress'] + 1
    assert anchored['credits'] == base['credits'] + 10 and anchored['requests']['getSignaturesForAddress'] == 1
    assert bf.plan(window, COSTS, expected_tx_per_slot=0.3, check=False, anchor=True)['credits'] == \
        bf.plan(window, COSTS, expected_tx_per_slot=0.3, check=False)['credits']
    out = io.StringIO()
    code = backfill_cli.main(['run', '--address', ADDRESS, '--slot-min', '1000', '--slot-max', '1999',
                              '--costs', w1_collection.COSTS, '--max-requests', '10', '--max-credits', '100',
                              '--anchor-after-window', '--out', str(tmp_path / 'dry')], environ={}, out=out)
    assert code == 0 and json.loads(out.getvalue())['anchor_after_window'] is True
    assert not (tmp_path / 'dry').exists()
    chain, out = Chain(_entries(), strict=True), io.StringIO()
    code = backfill_cli.main(['run', '--network', '--endpoint-env', 'RPC', '--address', ADDRESS, '--slot-min', '1000',
                              '--slot-max', '1999', '--costs', w1_collection.COSTS, '--max-requests', '50',
                              '--max-credits', '100', '--anchor-after-window', '--out', str(tmp_path / 'net')],
                             environ={'RPC': 'https://rpc.example.test/?api-key=SECRET'}, opener=chain, out=out)
    result = json.loads(out.getvalue())
    assert code == 0 and result['complete'] and result['gsfa_anchor']['slot'] == 2_000
    assert 'SECRET' not in out.getvalue()


# ----------------------------------------------------------------- sampled mode (SampledBackfill)
_spec = importlib.util.spec_from_file_location('_launchlab_backfill_helpers',
                                               Path(__file__).with_name('test_launchlab_backfill.py'))
_lb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lb)


class AnchoredDensePool(_lb.DensePool):
    """The dense synthetic pool, with GSFA refused without ``before`` and GTFA without ``lte``."""

    def getSignaturesForAddress(self, address, options):
        assert 'before' in options, 'GSFA without before: listing from the chain head'
        return super().getSignaturesForAddress(address, options)

    def getTransactionsForAddress(self, address, options):
        assert address == _lb.SOL_POOL and options['limit'] == 1
        gte = options['filters']['slot']['gte']
        rows = sorted((r for r in self.rows.values() if r['slot'] >= gte and r['err'] is None),
                      key=lambda r: (r['slot'], r['transactionIndex']))
        return {'data': rows[:1], 'paginationToken': None}


def _sample(tmp_path, chain, *extra, out='s'):
    buf = io.StringIO()
    code = _lb.cli.main(['sample', '--network', '--pool', _lb.SOL_POOL, '--sol-vault', _lb.SOL_VAULT,
                         '--usdc-vault', _lb.USDC_VAULT, '--slot-min', '2000', '--slot-max', '2079',
                         '--grid-seconds', '4', '--costs', w1_collection.COSTS, '--max-requests', '100000',
                         '--max-credits', '100000000', '--out', str(tmp_path / out), *extra],
                        environ=_lb.ENV, opener=chain, out=buf)
    return code, json.loads(buf.getvalue())


def test_sampled_mode_anchors_first_and_matches_the_unanchored_listing(tmp_path):
    chain = AnchoredDensePool()
    code, report = _sample(tmp_path, chain, '--anchor-after-window')
    assert code == 0 and report['complete']
    assert chain.calls[0][0] == 'getTransactionsForAddress'
    assert report['gsfa_anchor']['slot'] == 2_080 and report['gsfa_anchor']['signature'] == 'd080'
    plain = _lb.DensePool()
    code, reference = _sample(tmp_path, plain, out='ref')
    assert code == 0 and reference['gsfa_anchor'] is None
    assert reference['totals'] == report['totals'] and reference['sampling'] == report['sampling']
    with pytest.raises(AssertionError, match='GSFA without before'):
        _sample(tmp_path, AnchoredDensePool(), out='strict')


# ----------------------------------------------------------------- R02 observations O-1, O-2, M20
def test_resume_with_the_other_anchor_option_is_refused(tmp_path):
    stopped = _run(tmp_path / 'a', Chain(_entries(), strict=True), cap=40, anchor_after_window=True)
    assert not stopped['complete'] and json.loads((tmp_path / 'a' / 'state.json').read_text())['anchor_after_window'] is True
    with pytest.raises(bf.BackfillError, match='resume_parameters_differ_from_state'):
        _run(tmp_path / 'a', Chain(_entries()), cap=60)
    plain = _run(tmp_path / 'b', Chain(_entries()), cap=20)
    assert not plain['complete'] and 'anchor_after_window' not in json.loads((tmp_path / 'b' / 'state.json').read_text())
    with pytest.raises(bf.BackfillError, match='resume_parameters_differ_from_state'):
        _run(tmp_path / 'b', Chain(_entries()), cap=60, anchor_after_window=True)
    assert _run(tmp_path / 'b', Chain(_entries()), cap=60)['complete']


def test_verify_flags_an_anchor_dropped_from_the_manifest(tmp_path):
    _run(tmp_path, Chain(_entries(), strict=True), anchor_after_window=True)
    manifest_path = tmp_path / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest_path.write_text(json.dumps(dict(manifest, gsfa_anchor=None)))
    assert 'gsfa_anchor_missing_from_manifest' in bf.verify(tmp_path)['problems']


def test_cli_plan_counts_the_anchor(tmp_path):
    def plan(*extra):
        out = io.StringIO()
        assert backfill_cli.main(['plan', '--address', ADDRESS, '--slot-min', '466226737', '--slot-max', '466243519',
                                  '--costs', w1_collection.COSTS, '--expected-tx-per-slot', '0.27', *extra],
                                 environ={}, out=out) == 0
        return json.loads(out.getvalue())
    base, anchored = plan(), plan('--anchor-after-window')
    assert (base['credits'], anchored['credits']) == (465, 475)
    assert anchored['requests']['getTransactionsForAddress'] == base['requests']['getTransactionsForAddress'] + 1
