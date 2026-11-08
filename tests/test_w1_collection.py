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


def test_documented_cost_table_and_pilot_ledger(tmp_path):
    costs = bf.COST_PRESETS[w1.COSTS]
    assert costs == {'getSignaturesForAddress': 1, 'getTransaction': 1, 'getTransactionsForAddress': 10}
    assert w1.PILOT_SLOTS == (466_226_737, 466_248_336)
    assert (w1.CREDIT_CAP, w1.PILOT_MAX_CREDITS) == (1_000_000, 50_000)     # the whole free month, pilot included
    ledger = tmp_path / 'spend.json'
    budget = bf.CreditBudget(10, w1.PILOT_MAX_CREDITS, costs, ledger=ledger)
    for method in ('getTransactionsForAddress', 'getSignaturesForAddress'):
        budget.next_method = method
        budget.charge()
    assert w1.main_run_cap(ledger) == w1.CREDIT_CAP - 11
    bf.CreditBudget(10, 10**6, bf.COST_PRESETS['public'], ledger=tmp_path / 'other.json')
    with pytest.raises(bf.BackfillError, match='cost_table'):
        w1.main_run_cap(tmp_path / 'other.json')
    data = json.loads(ledger.read_text())
    ledger.write_text(json.dumps(dict(data, credits=w1.PILOT_MAX_CREDITS + 1)))
    with pytest.raises(bf.BackfillError, match='pilot_spend_above_its_cap'):
        w1.main_run_cap(ledger)


def _w1_window(tmp_path, s0, *, max_credits=w1.CREDIT_CAP, costs=w1.COSTS):
    b, chain = w1.bounds(s0), T.FakeChain()
    rpc = bf.open_rpc(T.URL, bf.CreditBudget(10**6, max_credits, bf.COST_PRESETS[costs]), opener=chain)
    manifest = bf.Backfill(rpc, bf.Window(bf.LAUNCHLAB_PROGRAM, b['slot_min'], b['slot_max']), tmp_path / 'w').run()
    return chain, manifest


def test_export_carries_the_spend_and_the_w1_window(tmp_path):
    s0 = T.SLOT_MIN - w1.WARMUP_SLOTS                    # fixture pools open the evaluation range
    chain, manifest = _w1_window(tmp_path, s0)
    assert manifest['complete'] and manifest['budget']['costs'] == bf.COST_PRESETS[w1.COSTS]
    export = w1.export(tmp_path / 'w', tmp_path / 'pools', s0)
    written = json.loads((tmp_path / 'pools' / 'MANIFEST.json').read_text())
    assert written['entry_cutoff_slot'] == s0 + 2_015_599 and written['window_slot_max'] == s0 + 2_020_112
    assert written['collection_budget'] == manifest['budget'] == export['collection_budget']
    spend = written['collection_budget']
    gtfa = sum(1 for method, _ in chain.calls if method == 'getTransactionsForAddress')
    gsfa = sum(1 for method, _ in chain.calls if method == 'getSignaturesForAddress')
    assert gtfa and gsfa and spend['requests'] == gtfa + gsfa == len(chain.calls)
    assert spend['credits'] == 10 * gtfa + gsfa and spend['max_credits'] == w1.CREDIT_CAP
    assert all(params[1]['limit'] <= bf.GTFA_FULL_PAGE and params[1]['transactionDetails'] == 'full'
               for method, params in chain.calls if method == 'getTransactionsForAddress')
    assert len(written['pools']) == 3


def test_export_refuses_another_window_or_cap(tmp_path):
    s0 = T.SLOT_MIN - w1.WARMUP_SLOTS
    _w1_window(tmp_path, s0)
    with pytest.raises(bf.BackfillError, match='window_is_not_the_w1_window'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0 - 1)
    with pytest.raises(bf.BackfillError, match='window_is_not_the_w1_window'):
        w1.export(tmp_path / 'w', tmp_path / 'p', s0, evaluation_slots=w1.MIN_EVALUATION_SLOTS)
    other = tmp_path / 'o'
    other.mkdir()
    _w1_window(other, s0, costs='public')
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):
        w1.export(other / 'w', other / 'p', s0)
    big = tmp_path / 'big'
    big.mkdir()
    _w1_window(big, s0, max_credits=w1.CREDIT_CAP + 1)
    with pytest.raises(bf.BackfillError, match='window_not_collected_under_the_w1_cap'):
        w1.export(big / 'w', big / 'p', s0)
