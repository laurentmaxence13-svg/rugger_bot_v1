"""W1 protocol R6: W1 bounds, cap rule and export on top of the audited backfill (offline)."""
import importlib.util
import json
from pathlib import Path

import pytest

from bot.market import backfill as bf
from bot.market import w1_collection as w1

_spec = importlib.util.spec_from_file_location('backfill_tests', Path(__file__).parent / 'test_launchlab_backfill.py')
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


QUOTA = dict(remaining=10 ** 9, reset_date='2026-12-01', owner_message='test reading')


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    monkeypatch.setattr(bf, 'GSFA_PAGE', 25)
    monkeypatch.setattr(bf, 'GTFA_FULL_PAGE', 10)


def test_full_bounds_are_the_protocol_numbers():
    b = w1.bounds(1_000_000)
    assert (b['slot_min'], b['slot_max']) == (1_000_000, 1_000_000 + 2_020_112)
    assert b['collected_slots'] == 2_020_113
    assert b['warmup'] == (1_000_000, 1_000_000 + 402_800)
    assert b['evaluation'] == (1_000_000 + 402_800, 1_000_000 + 2_015_600)
    assert b['entry_cutoff_slot'] == 1_000_000 + 2_015_599 and b['window_slot_max'] == 1_000_000 + 2_020_112
    assert b['window_slot_max'] - b['entry_cutoff_slot'] == w1.GAP_SLOTS == 4_513
    assert w1.GAP_SLOTS >= w1.bx.MIN_CUTOFF_GAP_SLOTS
    short = w1.bounds(1_000_000, w1.MIN_EVALUATION_SLOTS)
    assert short['evaluation'] == (1_402_800, 1_402_800 + 806_400) and short['window_slot_max'] - short['entry_cutoff_slot'] == 4_513
    for bad in (dict(s0=0), dict(s0='1'), dict(s0=1, evaluation_slots=806_399), dict(s0=1, evaluation_slots=1_612_801)):
        with pytest.raises(bf.BackfillError):
            w1.bounds(**bad)


def test_cap_rule_full_shortened_or_stop():
    collected = 2_020_113
    assert w1.fit_to_cap(10, pilot_credits=1, pilot_slots=1, credits_left=collected)[0] == 'FULL'
    status, b = w1.fit_to_cap(10, pilot_credits=1, pilot_slots=1, credits_left=collected - 1)
    assert status == 'SHORTENED' and b['collected_slots'] == collected - 1
    status, b = w1.fit_to_cap(10, pilot_credits=1, pilot_slots=1, credits_left=402_800 + 806_400 + 4_513)
    assert status == 'SHORTENED' and b['evaluation_slots'] == 806_400
    assert w1.fit_to_cap(10, pilot_credits=1, pilot_slots=1, credits_left=402_800 + 806_399 + 4_513) == ('STOP', None)
    # The P0 rate (30 105 credits over 216 000 slots) fits a full W1 under 950 000 credits left.
    status, b = w1.fit_to_cap(10, pilot_credits=30_105, pilot_slots=216_000, credits_left=950_000)
    assert status == 'FULL'
    status, b = w1.fit_to_cap(10, pilot_credits=30_105 * 4, pilot_slots=216_000, credits_left=950_000)
    assert status == 'SHORTENED' and b['collected_slots'] * 30_105 * 4 <= 950_000 * 216_000
    assert (b['collected_slots'] + 1) * 30_105 * 4 > 950_000 * 216_000             # the largest that fits
    # Fractional projection: ceil(2 020 113 / 2) = 1 010 057 credits; one less does not fit.
    assert w1.fit_to_cap(10, pilot_credits=1, pilot_slots=2, credits_left=1_010_057)[0] == 'FULL'
    assert w1.fit_to_cap(10, pilot_credits=1, pilot_slots=2, credits_left=1_010_056)[0] == 'SHORTENED'
    with pytest.raises(bf.BackfillError):
        w1.fit_to_cap(10, pilot_credits=0, pilot_slots=1, credits_left=1)


def _pilot(tmp_path, credits, *, window=w1.PILOT_SLOTS, cap=w1.PILOT_MAX_CREDITS, costs=w1.COSTS, name='pilot'):
    """A pilot run directory: its manifest window and a spend ledger charged ``credits`` times."""
    run = tmp_path / name
    budget = bf.CreditBudget(10**6, cap, bf.COST_PRESETS[costs], ledger=run / 'spend.json')
    for _ in range(credits):
        budget.next_method = 'getSignaturesForAddress' if costs == w1.COSTS else 'getTransaction'
        budget.charge()
    (run / 'manifest.json').write_text(json.dumps({'window': {
        'address': bf.LAUNCHLAB_PROGRAM, 'slot_min': window[0], 'slot_max': window[1]}}))
    return run


def test_documented_cost_table_and_pilot_cap(tmp_path):
    costs = bf.COST_PRESETS[w1.COSTS]
    assert costs == {'getSignaturesForAddress': 1, 'getTransaction': 1, 'getTransactionsForAddress': 10}
    assert w1.PILOT_SLOTS == (466_226_737, 466_248_336)
    assert (w1.CREDIT_CAP, w1.PILOT_MAX_CREDITS) == (1_000_000, 50_000)     # the whole free month, pilot included
    pilot = _pilot(tmp_path, 11)
    assert w1.main_run_cap(pilot) == w1.CREDIT_CAP - 11
    assert w1.check_run_cap(w1.CREDIT_CAP - 11, pilot, quota_reading=QUOTA) == w1.CREDIT_CAP - 11
    with pytest.raises(bf.BackfillError, match='run_cap_above_credits_left_after_the_pilot'):
        w1.check_run_cap(w1.CREDIT_CAP - 10, pilot, quota_reading=QUOTA)                          # R02 R6-1: 1 M + pilot refused
    with pytest.raises(bf.BackfillError, match='cost_table'):
        w1.main_run_cap(_pilot(tmp_path, 1, costs='public', name='public'))
    with pytest.raises(bf.BackfillError, match='not_the_pilot_window'):     # R02 R6-3
        w1.main_run_cap(_pilot(tmp_path, 1, window=(466_226_737, 466_248_337), name='other'))
    with pytest.raises(bf.BackfillError, match='pilot_spend_above_its_cap'):
        w1.main_run_cap(_pilot(tmp_path, 1, cap=w1.PILOT_MAX_CREDITS + 1, name='bigcap'))
    ledger = pilot / 'spend.json'
    data = json.loads(ledger.read_text())
    ledger.write_text(json.dumps(dict(data, credits=w1.PILOT_MAX_CREDITS + 1)))
    with pytest.raises(bf.BackfillError, match='pilot_spend_above_its_cap'):
        w1.main_run_cap(pilot)


def _w1_window(tmp_path, s0, *, max_credits=w1.CREDIT_CAP - 11, costs=w1.COSTS):
    b, chain = w1.bounds(s0), T.FakeChain()
    budget = bf.CreditBudget(10**6, max_credits, bf.COST_PRESETS[costs], ledger=tmp_path / 'w' / 'spend.json')
    rpc = bf.open_rpc(T.URL, budget, opener=chain)
    manifest = bf.Backfill(rpc, bf.Window(bf.LAUNCHLAB_PROGRAM, b['slot_min'], b['slot_max']), tmp_path / 'w').run()
    return chain, manifest


def test_export_carries_the_spend_the_code_and_the_w1_window(tmp_path):
    s0 = T.SLOT_MIN - w1.WARMUP_SLOTS                    # fixture pools open the evaluation range
    pilot = _pilot(tmp_path, 11)
    chain, manifest = _w1_window(tmp_path, s0)
    assert manifest['complete'] and manifest['budget']['costs'] == bf.COST_PRESETS[w1.COSTS]
    export = w1.export(tmp_path / 'w', tmp_path / 'pools', s0, pilot_dir=pilot)
    written = json.loads((tmp_path / 'pools' / 'MANIFEST.json').read_text())
    assert written['entry_cutoff_slot'] == s0 + 2_015_599 and written['window_slot_max'] == s0 + 2_020_112
    assert written['collection_budget'] == manifest['budget'] == export['collection_budget']
    spend = written['collection_budget']
    gtfa = sum(1 for method, _ in chain.calls if method == 'getTransactionsForAddress')
    gsfa = sum(1 for method, _ in chain.calls if method == 'getSignaturesForAddress')
    assert gtfa and gsfa and spend['requests'] == gtfa + gsfa == len(chain.calls)
    assert spend['credits'] == 10 * gtfa + gsfa and spend['max_credits'] == w1.CREDIT_CAP - 11
    assert all(params[1]['limit'] <= bf.GTFA_FULL_PAGE and params[1]['transactionDetails'] == 'full'
               for method, params in chain.calls if method == 'getTransactionsForAddress')
    assert len(written['pools']) == 3
    code = written['collector_code']
    assert code == w1.collector_code() and set(w1.COLLECTOR_ROOTS) <= set(code['modules'])
    for path in ('bot/market/collector.py', 'bot/market/launchlab_events.py', 'bot/live/compiled_launchlab.py',
                 'bot/live/migration_rpc_json.py'):
        assert path in code['modules'], path


def test_collector_code_follows_the_decoding_source(monkeypatch, tmp_path):
    import shutil
    from bot.master_v2 import harness as h
    copy = tmp_path / 'root'
    for path in w1.collector_code()['modules']:
        (copy / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(h._ROOT / path, copy / path)
    monkeypatch.setattr(h, '_ROOT', copy)
    base = w1.collector_code()['sha256']
    decoder = copy / 'bot/market/launchlab_events.py'
    decoder.write_text(decoder.read_text() + '\n# edit\n')
    assert w1.collector_code()['sha256'] != base


def test_export_refuses_another_window_or_cap(tmp_path):
    s0 = T.SLOT_MIN - w1.WARMUP_SLOTS
    pilot = _pilot(tmp_path, 11)
    _w1_window(tmp_path, s0)
    with pytest.raises(bf.BackfillError, match='window_is_not_the_w1_window'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0 - 1, pilot_dir=pilot)
    with pytest.raises(bf.BackfillError, match='window_is_not_the_w1_window'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, evaluation_slots=w1.MIN_EVALUATION_SLOTS, pilot_dir=pilot)
    manifest = json.loads((tmp_path / 'w' / 'manifest.json').read_text())             # R02 R6-2
    other = tmp_path / 'other_program'
    other.mkdir()
    (other / 'manifest.json').write_text(json.dumps(dict(manifest, window=dict(manifest['window'], address='So11111111111111111111111111111111111111112'))))
    with pytest.raises(bf.BackfillError, match='window_is_not_the_w1_window'):
        w1.export(other, tmp_path / 'p', s0, pilot_dir=pilot)
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):   # 1 M after a pilot of 12
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, pilot_dir=_pilot(tmp_path, 12, name='pilot12'))
    for name, kwargs in (('public', dict(costs='public')), ('full_month', dict(max_credits=w1.CREDIT_CAP))):
        run = tmp_path / name
        run.mkdir()
        _w1_window(run, s0, **kwargs)
        with pytest.raises(bf.BackfillError, match='w1_cost_table|window_not_collected_under_the_w1_cap'):
            w1.export(run / 'w', run / 'p', s0, pilot_dir=pilot)


def test_export_reads_every_cap_ever_used_and_the_manifest_cost_table(tmp_path):
    s0 = T.SLOT_MIN - w1.WARMUP_SLOTS
    pilot = _pilot(tmp_path, 11)
    _w1_window(tmp_path, s0)
    ledger = tmp_path / 'w' / 'spend.json'
    spend = json.loads(ledger.read_text())
    raised = dict(spend, cap_history=[{'max_requests': 10**6, 'max_credits': w1.CREDIT_CAP}] + spend['cap_history'])
    ledger.write_text(json.dumps(raised))                    # ran under 1 M once, then resumed lower
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, pilot_dir=pilot)
    ledger.write_text(json.dumps(spend))
    path = tmp_path / 'w' / 'manifest.json'
    manifest = json.loads(path.read_text())
    path.write_text(json.dumps(dict(manifest, budget=dict(manifest['budget'], costs=bf.COST_PRESETS['public']))))
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, pilot_dir=pilot)


def test_corrupted_ledgers_are_refused_r02(tmp_path):
    """R02 survivors: ledger spend above what is left, manifest above the ledger, empty pilot
    cap history, negative pilot spend (it would raise the credits left above 1 M)."""
    s0 = T.SLOT_MIN - w1.WARMUP_SLOTS
    pilot = _pilot(tmp_path, 11)
    _w1_window(tmp_path, s0)
    run_ledger = tmp_path / 'w' / 'spend.json'
    run_spend = json.loads(run_ledger.read_text())
    run_ledger.write_text(json.dumps(dict(run_spend, credits=w1.CREDIT_CAP - 10)))            # (b)
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, pilot_dir=pilot)
    path = tmp_path / 'w' / 'manifest.json'
    manifest = json.loads(path.read_text())
    run_ledger.write_text(json.dumps(run_spend))
    path.write_text(json.dumps(dict(manifest, budget=dict(manifest['budget'], credits=run_spend['credits'] + 1))))  # (c)
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, pilot_dir=pilot)
    path.write_text(json.dumps(manifest))
    assert w1.export(tmp_path / 'w', tmp_path / 'p', s0, pilot_dir=pilot)['pools']             # the untampered pair passes
    pilot_ledger = pilot / 'spend.json'
    pilot_spend = json.loads(pilot_ledger.read_text())
    pilot_ledger.write_text(json.dumps(dict(pilot_spend, cap_history=[])))                       # (h)
    with pytest.raises(bf.BackfillError, match='pilot_spend_above_its_cap'):
        w1.main_run_cap(pilot)
    pilot_ledger.write_text(json.dumps(dict(pilot_spend, credits=-5)))                           # (i)
    with pytest.raises(bf.BackfillError, match='invalid_spend_ledger'):
        w1.main_run_cap(pilot)
    with pytest.raises(bf.BackfillError, match='invalid_spend_ledger'):
        w1.check_run_cap(w1.CREDIT_CAP, pilot, quota_reading=QUOTA)
    pilot_ledger.write_text(json.dumps(dict(pilot_spend, credits=True)))
    with pytest.raises(bf.BackfillError, match='invalid_spend_ledger'):
        w1.main_run_cap(pilot)


def test_other_runs_of_the_month_reserve_their_largest_cap_v2_4(tmp_path):
    """v2.4: the SOL/USD runs share the 1 M with the pilot and the LaunchLab run."""
    pilot = _pilot(tmp_path, 11)
    study = _pilot(tmp_path, 3, cap=2_000, name='pyth_study')               # spent 3, may spend 2 000
    pyth_run = _pilot(tmp_path, 0, cap=60_000, name='pyth_run')
    assert w1.reserved_credits([study, pyth_run]) == 62_000
    assert w1.main_run_cap(pilot, [study, pyth_run]) == w1.CREDIT_CAP - 11 - 62_000
    w1.check_run_cap(w1.CREDIT_CAP - 11 - 62_000, pilot, [study, pyth_run], quota_reading=QUOTA)
    with pytest.raises(bf.BackfillError, match='run_cap_above_credits_left_after_the_pilot'):
        w1.check_run_cap(w1.CREDIT_CAP - 11 - 61_999, pilot, [study, pyth_run], quota_reading=QUOTA)
    ledger = study / 'spend.json'
    data = json.loads(ledger.read_text())
    ledger.write_text(json.dumps(dict(data, credits=2_500)))               # spent above its cap: counted in full
    assert w1.reserved_credits([study]) == 2_500
    ledger.write_text(json.dumps(dict(data, cap_history=[])))
    with pytest.raises(bf.BackfillError, match='run_without_cap_history'):
        w1.reserved_credits([study])
    s0 = T.SLOT_MIN - w1.WARMUP_SLOTS
    _w1_window(tmp_path, s0)                                               # run cap 1 M - 11
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, pilot_dir=pilot, other_runs=[pyth_run])


def test_run_cap_must_fit_the_provider_quota_left_v2_6_1(tmp_path):
    """R02 B-2: on the Free plan an exhausted quota stops the run; cap <= quota left - 2 %."""
    pilot = _pilot(tmp_path, 11)
    reading = dict(remaining=942_812, reset_date='2026-12-01', owner_message='session x 2026-11-09T08:11Z')
    assert w1.quota_cap(reading) == 923_955
    assert w1.check_run_cap(923_955, pilot, quota_reading=reading) == 923_955
    with pytest.raises(bf.BackfillError, match='run_cap_above_the_provider_quota_left'):
        w1.check_run_cap(923_956, pilot, quota_reading=reading)
    assert w1.check_run_cap(w1.CREDIT_CAP - 11, pilot, quota_reading=QUOTA) == w1.CREDIT_CAP - 11
    for bad in (dict(reading, remaining=-1), dict(reading, remaining='942812'), dict(reading, remaining=True),
                dict(reading, reset_date='01/12/2026'), dict(reading, reset_date=None), dict(reading, owner_message=''),
                {k: v for k, v in reading.items() if k != 'reset_date'}, None):
        with pytest.raises(bf.BackfillError, match='quota_reading_incomplete'):
            w1.check_run_cap(1, pilot, quota_reading=bad)
    with pytest.raises(TypeError):
        w1.check_run_cap(1, pilot)                                                     # the reading is required
