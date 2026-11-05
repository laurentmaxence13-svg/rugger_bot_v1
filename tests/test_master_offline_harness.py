"""RUGGER 03 harness: causality, missing data, lookahead, failure traces (SYNTHETIC)."""
from copy import deepcopy
import json

import pytest

from bot import master_offline_harness as h
from test_master_comparison import plan, available_corpus, qualified_corpus


def dev(report, fee=1, delay=0):
    return next(s for s in report['scenarios'] if s['split'] == 'development'
                and s['fee_multiplier'] == fee and s['decision_delay_ms'] == delay)


def test_refuses_non_synthetic_journal_and_never_claims_profitability():
    bad = qualified_corpus(); bad['data_kind'] = 'market_observation'
    with pytest.raises(ValueError, match='synthetic'):
        h.run_harness(bad, plan())
    r = h.run_harness(qualified_corpus(), plan())
    assert r['real_profitability_claim'] == 'REFUSED'
    assert r['profitability_verdict'].startswith('NOT_DEMONSTRATED')
    assert r['data_kind'] == 'SYNTHETIC' and r['network_requests'] == r['trades_executed'] == 0
    assert r['promotion_allowed'] is False
    json.dumps(r, allow_nan=False)


def test_net_pnl_in_sol_common_costs_and_freeze_are_deterministic():
    p = plan(sensitivity=True)
    a = h.run_harness(qualified_corpus(partial=True), p)
    b = h.run_harness(qualified_corpus(partial=True), p)
    assert a == b and len(a['frozen_before_results']['freeze_sha256']) == 64
    s = dev(a)
    assert s['master']['realized_pnl_sol'] == pytest.approx(.149975)
    assert s['reference']['realized_pnl_sol'] == pytest.approx(.199985)
    assert s['master_minus_reference_net_sol'] == pytest.approx(-.05001)
    assert dev(a, fee=2)['master']['modeled_extra_costs_sol'] == pytest.approx(2 * dev(a)['master']['modeled_extra_costs_sol'])
    assert dev(a)['reference']['modeled_extra_costs_sol'] > 0
    assert a['frozen_before_results']['freeze_sha256'] != h.run_harness(qualified_corpus(), p)['frozen_before_results']['freeze_sha256']


def test_no_lookahead_audit_passes_and_detects_a_leaking_decision(monkeypatch):
    r = h.run_harness(qualified_corpus(partial=True), plan())
    assert r['causality_lookahead_audit']['passed'] and r['causality_lookahead_audit']['checked_cutoffs'] >= 2
    # Sanity of the audit itself: a decision function that peeks at the last frame must be caught.
    from bot import master_comparison as mc
    original = mc.evaluate_comparison

    def leaky(corpus, p):
        out = original(corpus, p)
        last = corpus['frames'][-1]['features']['price_usd']
        for pair in out['pairs']:
            for arm in ('reference', 'master'):
                for t in pair[arm]['trace']:
                    t['decision_snapshot']['leak'] = last
        return out
    monkeypatch.setattr(h.mc, 'evaluate_comparison', leaky)
    audit = h.lookahead_audit(qualified_corpus(partial=True), plan())
    assert audit['passed'] is False and audit['violations']


def test_missing_health_blocks_both_arms_with_failure_traces():
    j = available_corpus()
    for f in j['frames']:
        f.pop('health')
    s = dev(h.run_harness(j, plan()))
    assert s['reference']['entered'] == s['master']['entered'] == 0
    assert s['failure_traces'] and all(t['action'] in ('WAIT', 'NO_TRADE', 'WAIT_FOR_DATA') for t in s['failure_traces'])


def test_refused_exit_quote_keeps_pnl_unknown_not_zero():
    s = dev(h.run_harness(qualified_corpus(refused=True), plan()))
    for arm in ('reference', 'master'):
        assert s[arm]['pnl_known'] is False and s[arm]['portfolio_pnl_sol'] is None
        assert s[arm]['qualification_failures'] >= 1 and s[arm]['all_liquidated'] is False
    assert s['master_minus_reference_net_sol'] is None
    assert any(t['action'] == 'EXIT_QUOTE_REFUSED' for t in s['failure_traces'])


def test_master_wait_reasons_are_reported():
    s = dev(h.run_harness(available_corpus(), plan()))
    assert s['master_wait_reason_counts'].get('additional_costs_unknown', 0) >= 1
    assert s['master']['entered'] == 0 and s['reference']['entered'] == 1


def test_future_perturbation_changes_only_later_outputs():
    base = qualified_corpus(partial=True)
    changed = h._corrupt_future(base, base['frames'][0]['available_at_ms'])
    assert changed['frames'][0] == base['frames'][0] and changed['frames'][-1] != base['frames'][-1]
