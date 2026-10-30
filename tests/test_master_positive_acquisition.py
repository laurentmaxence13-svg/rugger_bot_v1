"""P3 positive-cycle acquisition is analyzable but never auto-promoted.

All observations here are isolated fixtures, not independently verified
mainnet market fills, wallet execution, or economic edge evidence.
"""
from copy import deepcopy
import pytest
from bot.master_comparison import evaluate_acquired_comparison, make_plan
from test_p3_master_acquisition import capture, build


def acquired_fixture(tmp_path):
    selection, events, tail, _ = capture(tmp_path, features=False)
    acquisition = build(selection, events, tail)
    plan = make_plan(
        registered_at_ms=1, development_end_ms=200000,
        holdout_end_ms=500000)
    return acquisition, plan


def test_reported_positive_qualified_cycles_reach_master_comparison_without_claim_of_profit(tmp_path):
    acquisition, plan = acquired_fixture(tmp_path)
    acquisition['qualified_economic_cycles'] = 2
    frozen = deepcopy(acquisition)
    report = evaluate_acquired_comparison(acquisition, plan)
    assert acquisition == frozen
    assert report['acquisition_reported_qualified_economic_cycles'] == 2
    assert report['strict_market_economic_cycles'] == 0
    assert report['independent_market_edge_verified'] is False
    assert report['acquisition_authentication_verified'] is False
    assert report['promotion_allowed'] is False
    assert report['execution_verified'] is False


@pytest.mark.parametrize('invalid', [True, False, -1, '2', None, 2.0])
def test_invalid_qualified_cycle_counters_still_fail_closed(tmp_path, invalid):
    acquisition, plan = acquired_fixture(tmp_path)
    acquisition['qualified_economic_cycles'] = invalid
    with pytest.raises(ValueError, match='envelope'):
        evaluate_acquired_comparison(acquisition, plan)


def test_zero_qualified_cycles_still_explicit_in_report(tmp_path):
    acquisition, plan = acquired_fixture(tmp_path)
    report = evaluate_acquired_comparison(acquisition, plan)
    assert report['acquisition_reported_qualified_economic_cycles'] == 0
    assert report['promotion_allowed'] is False
