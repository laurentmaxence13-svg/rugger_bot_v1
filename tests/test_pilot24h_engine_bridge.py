"""Real MASTER + baseline engines -> pilot24h ledger, offline. Fixtures are SYNTHETIC (source: tests)."""
from copy import deepcopy
import json
import pytest

from bot.p3 import pilot24h as p, pilot24h_engine_bridge as b, pilot24h_offline as o
from bot.p4 import paired_research_ledger as pl
from test_master_decision import qualified


def frames():
    core, f, health, capital = qualified()
    return f, health, capital


def outcome(f, entry=b.BUY_LAMPORTS, out=1_100_000_000, extra=15000, failed=0, kind='FULL_QUOTE'):
    return dict(source_slot=f['source_slot'] + 5, available_at_ms=f['available_at_ms'] + 30000,
                entry_quote_lamports=entry, exact_lot_atomic=1000, exit_kind=kind,
                exit_quote_lamports=out if kind == 'FULL_QUOTE' else None, extra_costs_lamports=extra,
                failure_costs_lamports=failed, provider_quote_source_clock_verified=True,
                actual_fills_verified=False)


def test_real_engines_decide_same_event_and_freeze_before_outcome():
    f, h, c = frames()
    r = b.decide_all([f], h, c)
    engines = {d['engine']: d for d in r['decisions']}
    assert set(engines) == {'MASTER', 'REFERENCE'}
    assert engines['MASTER']['action'] == 'ENTER'          # real orchestrator on qualified synthetic fixture
    assert r['decisions'][0]['obs'] == r['decisions'][1]['obs']
    assert r['frozen_pairs'][0]['phase'] == 'FROZEN_PRE_OUTCOME'
    assert o.check_decisions_causal(r['decisions'], r['observations']) == []
    assert r['digest'] == b.decide_all([deepcopy(f)], h, c)['digest']   # deterministic, reproducible SHA
    json.dumps(r, allow_nan=False)


def test_anti_lookahead_future_frames_do_not_change_past_decisions():
    f, h, c = frames()
    fut = deepcopy(f); fut['id'] += '-later'; fut['available_at_ms'] += 100000
    fut['features_available_at_ms'] += 100000; fut['source_slot'] += 50; fut['slot_available_at_ms'] += 100000
    fut['features']['price_usd'] = 10 ** 6
    alone = b.decide_all([f], h, c)['decisions']
    both = b.decide_all([f, fut], h, c)['decisions'][:2]
    assert alone == both


def test_decision_using_later_slot_is_flagged_lookahead():
    f, h, c = frames()
    r = b.decide_all([f], h, c)
    bad = deepcopy(r['decisions']); bad[0]['data_max_slot'] += 1
    assert o.check_decisions_causal(bad, r['observations'])


def test_tampered_decisions_refused_at_scoring():
    f, h, c = frames()
    r = b.decide_all([f], h, c)
    r['decisions'][1]['action'] = 'ENTER' if r['decisions'][1]['action'] != 'ENTER' else 'WAIT'
    with pytest.raises(p.ProtocolError):
        b.score_all(r, [outcome(f)])


def test_known_costs_give_conditional_not_realized_pnl_and_unknown_costs_give_none():
    f, h, c = frames()
    r = b.decide_all([f], h, c)
    s, = b.score_all(r, [outcome(f)])
    m = s['master_and_reference']['master']
    assert m['conditional_net_if_all_costs_provided_lamports'] == 100_000_000 - 15000
    assert m['actual_realized_net_pnl_lamports'] is None and s['qualified_executed_economic_cycles'] == 0
    assert s['market_profitability_verified'] is False and s['financial_order_submitted'] is False
    s2, = b.score_all(r, [outcome(f, extra=None)])
    assert s2['master_and_reference']['master']['conditional_net_if_all_costs_provided_lamports'] is None
    s3, = b.score_all(r, [outcome(f, kind='FAILED_EXIT')])
    assert s3['conditional_cost_adjusted_delta_lamports'] is None      # censored, never a zero loss
    assert b.score_all(r, [None]) == [None]                              # no outcome => nothing invented


def test_same_buy_size_enforced_and_followup_must_be_later():
    f, h, c = frames()
    r = b.decide_all([f], h, c)
    with pytest.raises(ValueError):
        b.score_all(r, [outcome(f, entry=b.BUY_LAMPORTS + 1)])
    late = outcome(f); late['available_at_ms'] = f['available_at_ms']
    with pytest.raises(ValueError):
        b.score_all(r, [late])


def test_zero_cycles_and_synthetic_provenance_are_insufficient_data():
    assert b.final_verdict([], [], 'synthetic')['status'] == 'INSUFFICIENT DATA'
    assert b.final_verdict([], [], 'live')['status'] == 'INSUFFICIENT DATA'
    assert (p.MIN_CREATORS, p.MIN_CYCLES) == (50, 20)                    # thresholds unchanged
    # a synthetic cycle with unknown costs is neither qualified nor given a P&L
    cyc = {'creator': 'C', 'creator_authenticated': False,
           'buy': {'slot': 1, 'sol_lamports': 10, 'failed': False},
           'sell': {'slot': 2, 'sol_lamports': 12, 'failed': False}}
    d = [{'engine': 'MASTER', 'action': 'ENTER'}]
    led = o.build_ledger(d, p.freeze(d), {'MASTER': [cyc]}, 'synthetic')
    assert led['rows'][0]['net_lamports'] is None and led['rows'][0]['qualified'] is False


def test_observer_rows_cannot_reconstruct_cycles():
    rep = o.qualification_report([{'signature': 's', 'slot': 1, 'event_index': 0, 'pool': 'P',
        'kind': 'launchlab_trade_buy', 'program': 'X', 'recv_utc': '2026-11-06T00:00:10.000000Z',
        'chain_time': 1793923200, 'causality': 'ok', 'decoded': 1, 'slippage_bps': None,
        'slippage_status': 'unknown', 'payload_json': '{}'}])
    assert rep['qualified_cycles'] == 0 and 'creator' in rep['fields_never_provided']
