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


def _collect(tmp_path, name, slots, entries, costs=w1_collection.COSTS, address=pyth_push.SOL_USD_ACCOUNT):
    chain = Chain(entries, address)
    chain.window = slots
    budget = bf.CreditBudget(10_000, 2_000, bf.COST_PRESETS[costs], ledger=tmp_path / name / 'spend.json')
    rpc = bf.open_rpc('https://rpc.example.test/?api-key=SECRET', budget, opener=chain)
    return bf.Backfill(rpc, bf.Window(address, *slots), tmp_path / name).run()


def _window_entries(start_slot, start_time, count, gap_s=30):
    return [_push(start_slot + 10 + 140 * i, start_time + gap_s * i + 1, start_time + gap_s * i, f'sig{start_slot}x{i}')
            for i in range(count)]


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


def test_study_report_from_three_verified_windows(tmp_path, no_dotenv):
    dirs = []
    for k, slots in enumerate(run.STUDY_WINDOWS):
        name = f'w{k}'
        _collect(tmp_path, name, slots, _window_entries(slots[0], 1_793_993_000 + 20_000 * k, 100))
        dirs.append(tmp_path / name)
    report, sha = run.run_study(dirs, tmp_path / 'report.json')
    assert report['verdict'] == 'ACCEPTED' and report['acceptance']['max_age_ms'] == 35_000
    assert [w['points'] for w in report['windows']] == [100, 100, 100] and report['windows'][0]['not_newer'] == 0
    import hashlib
    data = (tmp_path / 'report.json').read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha
    assert data == json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    first = min(_window_entries(run.STUDY_WINDOWS[0][0], 1_793_993_000, 100), key=lambda e: e['slot'])
    assert report['windows'][0]['seconds'] == [first['blockTime'] + 1, 1_793_993_000 + 30 * 99 + 1]


def test_measured_seconds_start_after_the_first_point_and_end_at_the_last_block_time():
    points = [dict(slot=12, transaction_index=0, block_time=150), dict(slot=10, transaction_index=1, block_time=100),
              dict(slot=10, transaction_index=0, block_time=101), dict(slot=11, transaction_index=0, block_time=160)]
    assert run.measured_seconds(points) == (102, 160)
    with pytest.raises(run.StudyRunError, match='without_point'):
        run.measured_seconds([])


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
        run.run_study([tmp_path / 'public'], tmp_path / 'r.json')
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
