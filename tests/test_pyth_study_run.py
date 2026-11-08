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


def _study_dirs(tmp_path, window_cap=666, last_failed_gap=0):
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
    assert [c['cap'] for c in credits['windows']] == [666] * 3 and credits['probe']['cap'] == 200
    assert credits['reserved_total'] == 200 + 3 * 666 and credits['total_max'] == 2_200
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


def test_study_refuses_a_stop_probe_or_reserved_credits_above_2200(tmp_path, no_dotenv):
    dirs = _study_dirs(tmp_path, window_cap=667)
    with pytest.raises(run.StudyRunError, match='study_reserved_credits_above_2200'):
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
