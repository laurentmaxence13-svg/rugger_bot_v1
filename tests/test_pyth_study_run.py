"""Offline runner of the SOL/USD age study, on a fake RPC serving synthetic push transactions."""
import copy
import io
import json
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import pyth_push
from bot.market import pyth_study_run as run
from bot.market import w1_collection
from bot.market.launchlab_events import b58encode

FIX = Path(__file__).parent / 'fixtures' / 'pyth_push'
BASE = json.loads((FIX / 'pyth_push_466226774_5KohzTfi.json').read_text())


def _push(slot, block_time, publish_time, signature):
    """The archived push transaction moved to ``slot`` with a new SOL/USD publish_time."""
    import struct
    entry = copy.deepcopy(BASE)
    entry['slot'], entry['blockTime'], entry['transactionIndex'] = slot, block_time, 0
    entry['transaction']['signatures'] = [signature] + entry['transaction']['signatures'][1:]
    keys = pyth_push.account_keys(entry)
    for ix in pyth_push._instructions(entry):
        if keys[ix['programIdIndex']] != pyth_push.PUSH_ORACLE_PROGRAM:
            continue
        data = pyth_push.b58decode(ix['data'])
        if pyth_push.decode_update(data)['feed_id'] != pyth_push.SOL_USD_FEED_ID:
            continue
        at = 12 + 33 + 8 + 8 + 4                                    # publish_time i64 BE in the message
        ix['data'] = b58encode(data[:at] + struct.pack('>q', publish_time) + data[at + 8:])
    return entry


class Chain:
    def __init__(self, entries, address=pyth_push.SOL_USD_ACCOUNT):
        self.entries, self.address = entries, address

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        address, options = body['params']
        assert address == self.address
        if body['method'] == 'getTransactionsForAddress':
            slot = options['filters']['slot']
            result = {'data': [e for e in self.entries if slot['gte'] <= e['slot'] <= slot['lte']], 'paginationToken': None}
        else:
            lo, hi = self.window
            result = [] if 'before' in options else [
                {'signature': e['transaction']['signatures'][0], 'slot': e['slot'], 'err': None, 'blockTime': e['blockTime'],
                 'memo': None, 'confirmationStatus': 'finalized'}
                for e in sorted(self.entries, key=lambda e: e['slot'], reverse=True) if lo <= e['slot'] <= hi]
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result}).encode())


def _collect(tmp_path, name, slots, entries, costs=w1_collection.COSTS, address=pyth_push.SOL_USD_ACCOUNT, cap=200):
    chain = Chain(entries, address)
    chain.window = slots
    budget = bf.CreditBudget(10_000, cap, bf.COST_PRESETS[costs], ledger=tmp_path / name / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=chain)
    return bf.Backfill(rpc, bf.Window(address, *slots), tmp_path / name).run()


def _window_entries(start_slot, start_time, count, gap_s=30):
    return [_push(start_slot + 10 + 140 * i, start_time + gap_s * i + 1, start_time + gap_s * i, f'sig{start_slot}x{i}')
            for i in range(count)]


def _failed(slot, block_time, signature):
    """A failed transaction on the account (no point, but a block_time of the window)."""
    entry = _push(slot, block_time, block_time - 1, signature)
    entry['meta']['err'] = {'InstructionError': [0, 'Custom']}
    return entry


def _study_dirs(tmp_path, window_cap=800, last_failed_gap=0):
    _collect(tmp_path, 'probe', run.PROBE, _window_entries(run.PROBE[0], 1_793_993_000, 10))
    dirs = []
    for k, slots in enumerate(run.STUDY_WINDOWS):
        entries = _window_entries(slots[0], 1_793_993_000 + 20_000 * k, 100)
        if last_failed_gap:
            last = entries[-1]
            entries.append(_failed(last['slot'] + 5, last['blockTime'] + last_failed_gap, f'fail{k}'))
        _collect(tmp_path, f'w{k}', slots, entries, cap=window_cap)
        dirs.append(tmp_path / f'w{k}')
    return dirs


def _dashboard(tmp_path, probe='probe', **change):
    spent = json.loads((tmp_path / probe / 'spend.json').read_text())['credits']
    readings = dict(read_by='owner', before_probe=dict(plan='Developer', credits_remaining=9_000_000, autoscaling='disabled'),
                    after_probe=dict(credits_remaining=9_000_000 - spent, autoscaling='disabled'))
    for key, value in change.items():
        part, field = key.split('__')
        if part == 'top':
            readings[field] = value
        else:
            readings[part][field] = value
    return readings


@pytest.fixture
def no_dotenv(monkeypatch):
    monkeypatch.setenv('RUGGER_NO_DOTENV', '1')


def test_probe_decision_projects_the_windows(tmp_path, no_dotenv):
    entries = _window_entries(run.PROBE[0], 1_793_993_000, 10)
    _collect(tmp_path, 'probe', run.PROBE, entries)
    decision = run.probe_decision(tmp_path / 'probe')
    assert decision['decision'] == 'GO' and decision['probe_transactions'] == 10 and decision['probe_slots'] == 2_797
    assert decision['projected_credits'] == 10 * -(-(-(-10 * 50_349 // 2_797)) // 100)
    assert decision['windows_slots'] == 50_349 and decision['probe_spend']['costs'] == bf.COST_PRESETS[w1_collection.COSTS]
    assert decision['probe_credits']['cap'] == 200 and decision['probe_credits']['spent'] == decision['probe_spend']['credits']


def test_probe_above_its_cap_is_refused(tmp_path, no_dotenv):
    _collect(tmp_path, 'probe', run.PROBE, _window_entries(run.PROBE[0], 1_793_993_000, 3), cap=201)
    with pytest.raises(run.StudyRunError, match='probe_spend_above_its_cap'):
        run.probe_decision(tmp_path / 'probe')
    _collect(tmp_path, 'resumed', run.PROBE, _window_entries(run.PROBE[0], 1_793_993_000, 3))
    ledger = tmp_path / 'resumed' / 'spend.json'
    spend = json.loads(ledger.read_text())
    assert [c['max_credits'] for c in spend['cap_history']] == [200]
    spend['cap_history'] = [dict(spend['cap_history'][0], max_credits=250)] + spend['cap_history']
    ledger.write_text(json.dumps(spend))
    with pytest.raises(run.StudyRunError, match='probe_spend_above_its_cap'):      # largest cap ever, not the last
        run.probe_decision(tmp_path / 'resumed')
    spend['cap_history'] = []
    ledger.write_text(json.dumps(spend))
    with pytest.raises(run.StudyRunError, match='run_without_cap_history'):
        run.probe_decision(tmp_path / 'resumed')


def test_study_report_from_three_verified_windows(tmp_path, no_dotenv):
    dirs = _study_dirs(tmp_path)
    report, sha = run.run_study(dirs, tmp_path / 'report.json', probe_dir=tmp_path / 'probe',
                                dashboard=_dashboard(tmp_path))
    assert report['verdict'] == 'ACCEPTED' and report['acceptance']['max_age_ms'] == 35_000
    assert [w['points'] for w in report['windows']] == [100, 100, 100] and report['windows'][0]['not_newer'] == 0
    import hashlib
    data = (tmp_path / 'report.json').read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha
    assert data == json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    first = min(_window_entries(run.STUDY_WINDOWS[0][0], 1_793_993_000, 100), key=lambda e: e['slot'])
    assert report['windows'][0]['seconds'] == [first['blockTime'] + 1, 1_793_993_000 + 30 * 99 + 1]
    assert report['probe']['decision'] == 'GO' and report['probe']['transactions'] == 10
    credits = report['credits']
    assert [c['cap'] for c in credits['windows']] == [800] * 3 and credits['probe']['cap'] == 200
    assert credits['reserved_total'] == 200 + 3 * 800 and credits['total_max'] == 2_600
    assert credits['window_max'] == 800 and credits['window_projection']['decision'] == 'GO'
    spent = credits['probe']['spent']
    assert spent > 0 and report['dashboard'] == dict(plan='Developer', before=9_000_000, after=9_000_000 - spent,
                                                     real_probe_credits=spent, counted_probe_credits=spent,
                                                     autoscaling='disabled')


@pytest.mark.parametrize('change, error', [
    (dict(before_probe__autoscaling='enabled'), 'autoscaling_not_disabled'),
    (dict(after_probe__autoscaling='enabled'), 'autoscaling_not_disabled'),
    (dict(after_probe__credits_remaining=8_000_000), 'dashboard_cost_differs_from_the_w1_cost_table'),
    (dict(after_probe__credits_remaining=9_000_000), 'dashboard_cost_differs_from_the_w1_cost_table'),
    (dict(top__read_by='rugger03'), 'dashboard_readings_incomplete'),
    (dict(before_probe__plan=''), 'dashboard_readings_incomplete'),
    (dict(before_probe__credits_remaining='9M'), 'dashboard_readings_incomplete'),
    (dict(after_probe__credits_remaining=-1), 'dashboard_readings_incomplete'),
])
def test_dashboard_readings_stop_the_study(tmp_path, no_dotenv, change, error):
    dirs = _study_dirs(tmp_path)
    with pytest.raises(run.StudyRunError, match=error):
        run.run_study(dirs, tmp_path / 'report.json', probe_dir=tmp_path / 'probe', dashboard=_dashboard(tmp_path, **change))
    assert not (tmp_path / 'report.json').exists()
    with pytest.raises(run.StudyRunError, match='dashboard_readings_incomplete'):
        run.dashboard_check(tmp_path / 'probe', dict(read_by='owner', before_probe={}))
    assert run.dashboard_check(tmp_path / 'probe', _dashboard(tmp_path))['real_probe_credits'] > 0


def test_final_gap_is_measured_up_to_the_last_transaction(tmp_path, no_dotenv):
    dirs = _study_dirs(tmp_path, last_failed_gap=50)
    report, _ = run.run_study(dirs, tmp_path / 'report.json', probe_dir=tmp_path / 'probe', dashboard=_dashboard(tmp_path))
    last_push = 1_793_993_000 + 30 * 99 + 1
    assert report['windows'][0]['seconds'][1] == last_push + 50 and report['windows'][0]['points'] == 100
    assert report['windows'][0]['transactions'] == 101


def test_study_refuses_a_stop_probe_or_a_window_cap_above_800(tmp_path, no_dotenv):
    dirs = _study_dirs(tmp_path, window_cap=801)
    with pytest.raises(run.StudyRunError, match='study_window_cap_above_800'):
        run.run_study(dirs, tmp_path / 'report.json', probe_dir=tmp_path / 'probe', dashboard=_dashboard(tmp_path))
    dense = [_push(run.PROBE[0] + 2 * i, 1_793_993_000 + i, 1_793_993_000 + i - 1, f'd{i}') for i in range(1_112)]
    _collect(tmp_path, 'dense', run.PROBE, dense)
    assert run.probe_decision(tmp_path / 'dense')['decision'] == 'STOP'
    with pytest.raises(run.StudyRunError, match='probe_decision_is_not_go'):
        run.run_study(dirs, tmp_path / 'r2.json', probe_dir=tmp_path / 'dense', dashboard=_dashboard(tmp_path, 'dense'))
    assert not (tmp_path / 'report.json').exists() and not (tmp_path / 'r2.json').exists()


def test_measured_seconds_start_after_the_first_point_and_end_at_the_last_block_time():
    points = [dict(slot=12, transaction_index=0, block_time=150), dict(slot=10, transaction_index=1, block_time=100),
              dict(slot=10, transaction_index=0, block_time=101), dict(slot=11, transaction_index=0, block_time=160)]
    rows = [{'blockTime': 101}, {'blockTime': 175}, {'blockTime': 160}]
    assert run.measured_seconds(points, rows) == (102, 175)
    with pytest.raises(run.StudyRunError, match='without_point'):
        run.measured_seconds([], rows)
    with pytest.raises(run.StudyRunError, match='without_block_times'):
        run.measured_seconds(points, rows + [{'blockTime': None}])
    with pytest.raises(run.StudyRunError, match='without_block_times'):
        run.measured_seconds(points, [])
    with pytest.raises(run.StudyRunError, match='without_measured_second'):
        run.measured_seconds(points, [{'blockTime': 102}])


def test_tampered_segment_or_other_account_is_refused(tmp_path, no_dotenv):
    _collect(tmp_path, 'probe', run.PROBE, _window_entries(run.PROBE[0], 1_793_993_000, 3))
    manifest = json.loads((tmp_path / 'probe' / 'manifest.json').read_text())
    seg = next(tmp_path / 'probe' / s['path'] for s in manifest['segments'] if s['kind'] == 'tx')
    seg.write_bytes(seg.read_bytes() + b'\n')
    assert manifest['complete']
    with pytest.raises(run.StudyRunError, match='not_verified_or_incomplete'):
        run.probe_decision(tmp_path / 'probe')
    other = 'So11111111111111111111111111111111111111112'
    _collect(tmp_path, 'other', run.PROBE, _window_entries(run.PROBE[0], 1_793_993_000, 3), address=other)
    with pytest.raises(run.StudyRunError, match='not_the_preregistered_study_window'):
        run.probe_decision(tmp_path / 'other')


def test_wrong_window_cost_table_or_dotenv_are_refused(tmp_path, monkeypatch, no_dotenv):
    _collect(tmp_path, 'other', (run.PROBE[0], run.PROBE[1] + 1), _window_entries(run.PROBE[0], 1_793_993_000, 3))
    with pytest.raises(run.StudyRunError, match='not_the_preregistered_study_window'):
        run.probe_decision(tmp_path / 'other')
    _collect(tmp_path, 'public', run.PROBE, _window_entries(run.PROBE[0], 1_793_993_000, 3), costs='public')
    with pytest.raises(run.StudyRunError, match='w1_cost_table'):
        run.probe_decision(tmp_path / 'public')
    with pytest.raises(run.StudyRunError, match='three_study_windows_required'):
        run.run_study([tmp_path / 'public'], tmp_path / 'r.json', probe_dir=tmp_path / 'public', dashboard={})
    monkeypatch.delenv('RUGGER_NO_DOTENV')
    with pytest.raises(run.StudyRunError, match='RUGGER_NO_DOTENV'):
        run.probe_decision(tmp_path / 'public')


def test_incomplete_window_is_refused(tmp_path, no_dotenv):
    class Partial(Chain):
        def __call__(self, request, timeout):
            body = json.loads(request.data)
            if body['method'] == 'getSignaturesForAddress':
                self.entries = self.entries[:-1]
            return super().__call__(request, timeout)
    chain_entries = _window_entries(run.PROBE[0], 1_793_993_000, 5)
    chain = Partial(chain_entries)
    chain.window = run.PROBE
    budget = bf.CreditBudget(10_000, 2_000, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / 'p' / 'spend.json')
    bf.Backfill(bf.open_rpc('https://rpc.example.test/?k=S', budget, opener=chain),
                bf.Window(pyth_push.SOL_USD_ACCOUNT, *run.PROBE), tmp_path / 'p').run()
    with pytest.raises(run.StudyRunError, match='not_verified_or_incomplete'):
        run.probe_decision(tmp_path / 'p')


# ---------------------------------------------------------------- owner option B (2026-11-09)
class PagedChain(Chain):
    """GTFA pages of ``page`` entries with a paginationToken, as Helius pages a busy account."""

    def __init__(self, entries, page):
        super().__init__(entries)
        self.page = page

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        options = body['params'][1]
        if body['method'] != 'getTransactionsForAddress' or options.get('limit') == 1:
            return super().__call__(request, timeout)
        slot = options['filters']['slot']
        rows = [e for e in self.entries if slot['gte'] <= e['slot'] <= slot['lte']]
        start = int(options.get('paginationToken') or 0)
        more = start + self.page < len(rows)
        result = {'data': rows[start:start + self.page], 'paginationToken': str(start + self.page) if more else None}
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result}).encode())


def _paged_probe(tmp_path, count, page, name='probe'):
    chain = PagedChain(_window_entries(run.PROBE[0], 1_793_993_000, count), page)
    chain.window = run.PROBE
    budget = bf.CreditBudget(10_000, 200, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / name / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=chain)
    return bf.Backfill(rpc, bf.Window(pyth_push.SOL_USD_ACCOUNT, *run.PROBE), tmp_path / name).run()


def test_every_call_is_logged_with_what_came_back(tmp_path):
    manifest = _paged_probe(tmp_path, 15, 6)
    lines = [json.loads(raw) for raw in (tmp_path / 'probe' / bf.CALLS_LOG).read_text().splitlines()]
    gtfa = [line for line in lines if line['method'] == 'getTransactionsForAddress']
    assert [(line['received'], line['pagination_token']) for line in gtfa] == [(6, True), (6, True), (3, False)]
    assert all(line['credits'] == 10 and line['requests'] == 1 and line['phase'] == 'gtfa' for line in gtfa)
    gsfa = [line for line in lines if line['method'] == 'getSignaturesForAddress']
    assert [(line['received'], line['credits'], line['pagination_token']) for line in gsfa] == [(15, 1, None)]
    calls = manifest['calls']
    assert (calls['requests'], calls['credits']) == (manifest['budget']['requests'], manifest['budget']['credits'])
    assert calls['by_method']['getTransactionsForAddress'] == dict(calls=3, received=15, credits=30,
                                                                     with_pagination_token=2, errors=0)
    assert bf.verify(tmp_path / 'probe')['ok']


def test_calls_log_tampered_or_short_of_the_ledger_fails_verify(tmp_path):
    _paged_probe(tmp_path, 15, 6)
    log = tmp_path / 'probe' / bf.CALLS_LOG
    lines = log.read_text().splitlines()
    log.write_text('\n'.join(lines[:-1]) + '\n')
    assert bf.verify(tmp_path / 'probe')['problems'] == ['calls_log_differs_from_manifest']
    manifest_path = tmp_path / 'probe' / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['calls'] = bf._calls_summary(tmp_path / 'probe')
    manifest_path.write_text(json.dumps(manifest))
    assert bf.verify(tmp_path / 'probe')['problems'] == ['calls_log_differs_from_ledger']


def test_a_call_charged_then_failing_is_logged_with_its_error(tmp_path):
    def broken(request, timeout):
        raise OSError('connection reset')
    budget = bf.CreditBudget(3, 200, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / 'b' / 'spend.json')
    rpc = bf.ReadOnlyRpc('https://rpc.example.test/', budget, opener=broken, sleep=lambda _s: None, max_retries=1)
    backfill = bf.Backfill(rpc, bf.Window(pyth_push.SOL_USD_ACCOUNT, *run.PROBE), tmp_path / 'b')
    with pytest.raises(Exception):
        backfill._call('gtfa', 'getTransactionsForAddress', [pyth_push.SOL_USD_ACCOUNT, {}])
    lines = [json.loads(raw) for raw in (tmp_path / 'b' / bf.CALLS_LOG).read_text().splitlines()]
    assert len(lines) == 1 and lines[0]['error'] and lines[0]['credits'] == budget.credits > 0


def test_window_projection_uses_the_real_pages_of_the_probe(tmp_path, no_dotenv):
    _paged_probe(tmp_path, 19, 2)                       # 10 GTFA pages (9 x 2 + 1): 100 + 1 GSFA = 101 credits
    projection = run.window_projection(tmp_path / 'probe')
    assert projection['probe_gtfa_pages'] == 10 and projection['transactions_per_page'] == 1
    window = projection['windows'][0]
    assert window['transactions'] == -(-(-(-19 * 1000 // 2_797)) * 16_783 // 1000)
    assert window['gtfa_pages'] == window['transactions'] + 1
    assert window['credits'] == (window['gtfa_pages'] + 1) * 10 + window['gsfa_pages'] > run.WINDOW_PROJECTION_LIMIT
    assert projection['decision'] == 'STOP'
    _paged_probe(tmp_path, 10, 100, name='light')
    assert run.window_projection(tmp_path / 'light')['decision'] == 'GO'


def test_probe_page_split_from_the_ledger_alone():
    manifest = {'bodies': 'gtfa', 'gsfa_anchor': {'slot': 466_229_534},
                'budget': {'requests': 13, 'credits': 121, 'costs': bf.COST_PRESETS[w1_collection.COSTS]}}
    assert run._probe_gtfa_pages('unused', manifest) == 11          # 1 anchor + 11 GTFA + 1 GSFA
    manifest['budget'] = dict(manifest['budget'], credits=120)
    with pytest.raises(run.StudyRunError, match='probe_ledger_has_no_gtfa_gsfa_split'):
        run._probe_gtfa_pages('unused', manifest)


def test_option_b_caps_fit_the_strict_2600_ceiling():
    assert run.STUDY_TOTAL_MAX_CREDITS == 2_600 and run.WINDOW_MAX_CREDITS == 800
    assert run.PROBE_MAX_CREDITS + 3 * run.WINDOW_MAX_CREDITS <= run.STUDY_TOTAL_MAX_CREDITS
    assert run.WINDOW_PROJECTION_LIMIT * 1.1 <= run.WINDOW_MAX_CREDITS


def test_t1_run_study_refuses_a_stop_window_projection(tmp_path, no_dotenv):
    dirs = _study_dirs(tmp_path)
    _paged_probe(tmp_path, 19, 2, name='paged')           # probe_decision GO, window_projection STOP
    assert run.probe_decision(tmp_path / 'paged')['decision'] == 'GO'
    assert run.window_projection(tmp_path / 'paged')['decision'] == 'STOP'
    with pytest.raises(run.StudyRunError, match='window_projection_is_not_go'):
        run.run_study(dirs, tmp_path / 'report.json', probe_dir=tmp_path / 'paged',
                      dashboard=_dashboard(tmp_path, 'paged'))
    assert not (tmp_path / 'report.json').exists()


def _real_probe_numbers(monkeypatch):
    real = dict(decision='GO', projected_credits=1_800, probe_transactions=995, probe_slots=2_797,
                probe_credits=dict(cap=200, reserved=200, spent=121))
    monkeypatch.setattr(run, 'probe_decision', lambda _d: real)


def test_t2_exact_projection_of_the_real_probe_from_its_ledger(tmp_path, no_dotenv, monkeypatch):
    _real_probe_numbers(monkeypatch)
    (tmp_path / 'manifest.json').write_text(json.dumps({
        'bodies': 'gtfa', 'gsfa_anchor': {'slot': 466_229_534},
        'budget': {'requests': 13, 'credits': 121, 'costs': bf.COST_PRESETS[w1_collection.COSTS]}}))
    projection = run.window_projection(tmp_path)
    assert (projection['probe_gtfa_pages'], projection['transactions_per_page'], projection['density_tx_per_slot']) == (11, 90, 0.356)
    assert [(w['transactions'], w['gtfa_pages'], w['gsfa_pages'], w['credits']) for w in projection['windows']] == [(5_975, 68, 7, 697)] * 3
    assert projection['decision'] == 'GO' and projection['reserved_with_window_caps'] == 2_600


def test_t2_calls_log_with_the_anchor_counts_11_gtfa_pages(tmp_path, no_dotenv, monkeypatch):
    _real_probe_numbers(monkeypatch)
    line = lambda phase, method, credits: json.dumps({'phase': phase, 'method': method, 'credits': credits, 'requests': 1})
    lines = [line('anchor', 'getTransactionsForAddress', 10)] + [line('gtfa', 'getTransactionsForAddress', 10)] * 11 \
        + [line('gsfa', 'getSignaturesForAddress', 1)]
    (tmp_path / bf.CALLS_LOG).write_text('\n'.join(lines) + '\n')
    (tmp_path / 'manifest.json').write_text(json.dumps({'bodies': 'gtfa', 'gsfa_anchor': {'slot': 466_229_534}, 'calls': {},
                                                        'budget': {'requests': 13, 'credits': 121}}))
    projection = run.window_projection(tmp_path)
    assert projection['probe_gtfa_pages'] == 11 and projection['windows'][0]['credits'] == 697


def test_t3_a_charged_retry_is_logged_as_two_requests(tmp_path):
    attempts = []

    def flaky(request, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError('connection reset')
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'data': [], 'paginationToken': None}}).encode())
    budget = bf.CreditBudget(10, 200, bf.COST_PRESETS[w1_collection.COSTS], ledger=tmp_path / 'r' / 'spend.json')
    rpc = bf.ReadOnlyRpc('https://rpc.example.test/', budget, opener=flaky, sleep=lambda _s: None, max_retries=2)
    backfill = bf.Backfill(rpc, bf.Window(pyth_push.SOL_USD_ACCOUNT, *run.PROBE), tmp_path / 'r')
    backfill._call('gtfa', 'getTransactionsForAddress', [pyth_push.SOL_USD_ACCOUNT, {}])
    lines = [json.loads(raw) for raw in (tmp_path / 'r' / bf.CALLS_LOG).read_text().splitlines()]
    assert [(l['requests'], l['credits'], l['received'], l['pagination_token']) for l in lines] == [(2, 20, 0, False)]
    assert (budget.used, budget.credits) == (2, 20)
