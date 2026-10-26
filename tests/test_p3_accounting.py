"""Exact, point-in-time SOL accounting projections; synthetic inputs only."""
from dataclasses import replace
from decimal import Decimal
import json

import pytest

from bot.p3.accounting import (
    FxSnapshot, InsufficientAccountingData, SolFeeBreakdown,
    accounting_json_safe, lamports_to_sol, native_sol_round_trip,
    usd_marked_round_trip, validate_fx_as_of,
)


D = Decimal


def zero_fees():
    return SolFeeBreakdown(0, 0, (), provenance='synthetic')


def native(**changes):
    values = dict(entry_spent_lamports=1_000_000_000,
                  exit_received_lamports=1_200_000_000,
                  acquired_token_atomic=12_345_678,
                  sold_token_atomic=12_345_678,
                  token_mint='synthetic-mint', fees=zero_fees(),
                  available_cash_lamports=10_000_000_000)
    values.update(changes)
    return native_sol_round_trip(**values)


def marked(**changes):
    values = dict(position_lamports=1_000_000_000,
                  entry_token_usd=D('100'), exit_token_usd=D('100'),
                  entry_fx=FxSnapshot(D('100'), 980, 990),
                  exit_fx=FxSnapshot(D('120'), 1980, 1990),
                  entry_at_ms=1000, exit_at_ms=2000, max_fx_age_ms=50,
                  fees=zero_fees(), available_cash_lamports=10_000_000_000)
    values.update(changes)
    return usd_marked_round_trip(**values)


def test_native_sol_full_round_trip_charges_only_explicit_additional_fees_once():
    fees = SolFeeBreakdown(5000, 6000, (3000, 2000), provenance='estimate')
    result = native(fees=fees)
    assert result['total_extra_fee_lamports'] == 16000
    assert result['net_pnl_lamports'] == 199_984_000
    assert result['net_pnl_sol'] == D('0.199984000')
    assert result['final_available_cash_lamports'] == 10_199_984_000
    assert result['reserved_cash_lamports'] == 1_000_016_000
    assert result['remaining_token_atomic'] == 0
    assert result['fx_required_for_sol_pnl'] is False
    assert result['fee_provenance'] == 'estimate'
    assert result['execution_verified'] is result['model_eligible'] is False
    assert result['economic_verdict'] == 'INSUFFICIENT DATA'


def test_constant_usd_token_and_sol_up_twenty_percent_loses_one_sixth_in_sol():
    result = marked()
    # floor((1 SOL * 100 USD/SOL) / 120 USD/SOL), with no hidden USD/SOL=1.
    assert result['exit_received_lamports'] == 833_333_333
    assert result['net_pnl_lamports'] == -166_666_667
    assert result['net_pnl_sol'] == D('-0.166666667')
    assert result['unrounded_gross_return_sol'] == pytest.approx(-D(1) / D(6))
    assert D(0) <= result['discarded_fractional_lamports'] < D(1)
    assert result['rounding_policy'] == 'floor_exact_exit_lamports'


def test_matching_twenty_percent_token_and_fx_rises_cancel_before_costs():
    result = marked(exit_token_usd=D('120'),
                    fees=SolFeeBreakdown(5000, 5000, (), provenance='synthetic'))
    assert result['exit_received_lamports'] == 1_000_000_000
    assert result['unrounded_gross_return_sol'] == 0
    assert result['net_pnl_lamports'] == -10_000


def test_constant_fx_preserves_token_return_and_cost_reservation():
    result = marked(exit_token_usd=D('120'),
                    exit_fx=FxSnapshot(D('100'), 1980, 1990),
                    fees=SolFeeBreakdown(10_000_000, 10_000_000, (), provenance='synthetic'))
    assert result['exit_received_lamports'] == 1_200_000_000
    assert result['net_pnl_lamports'] == 180_000_000
    assert result['net_return_on_position'] == D('.18')


@pytest.mark.parametrize('snapshot', [
    None,
    FxSnapshot(D('120'), None, 1990),
    FxSnapshot(D('120'), 1980, 2001),
    FxSnapshot(D('120'), 1995, 1990),
    FxSnapshot(D('120'), 1900, 1990),
    FxSnapshot(D('120'), 1980, 1990, quote_currency='USDC'),
    FxSnapshot(D('120'), 1980, 1990, base_currency='USD', quote_currency='SOL'),
    FxSnapshot(D('120'), 1980, 1990, available_at_ms=2001),
    FxSnapshot(D('120'), 1980, 1990, available_at_ms=1989),
])
def test_unknown_future_stale_or_wrong_currency_fx_cannot_value_a_past_exit(snapshot):
    with pytest.raises(InsufficientAccountingData):
        marked(exit_fx=snapshot)


def test_entry_and_exit_fx_are_each_validated_at_their_own_decision_time():
    with pytest.raises(InsufficientAccountingData):
        marked(entry_fx=FxSnapshot(D('100'), 980, 1001))
    with pytest.raises(InsufficientAccountingData):
        marked(exit_at_ms=999)
    snapshot = FxSnapshot(D('100'), 980, 990, available_at_ms=995)
    assert validate_fx_as_of(snapshot, as_of_ms=1000, max_age_ms=20) == D('100')
    with pytest.raises(InsufficientAccountingData):
        validate_fx_as_of(snapshot, as_of_ms=994, max_age_ms=20)
    with pytest.raises(InsufficientAccountingData):
        validate_fx_as_of(snapshot, as_of_ms=1001, max_age_ms=20)


@pytest.mark.parametrize('fees', [
    None,
    SolFeeBreakdown(None, 0, ()),
    SolFeeBreakdown(0, None, ()),
    SolFeeBreakdown(0, 0, None),
    SolFeeBreakdown(0, 0, (None,)),
    SolFeeBreakdown(0, 0, (-1,)),
    SolFeeBreakdown(0, 0, (), quote_amounts_net_of_pool_fees=False),
    SolFeeBreakdown(0, 0, (), extra_fees_exclude_pool_fees=False),
    SolFeeBreakdown(0, 0, (), provenance='unknown'),
])
def test_unknown_or_double_counted_fees_cannot_be_silently_zeroed(fees):
    with pytest.raises(InsufficientAccountingData):
        native(fees=fees)


@pytest.mark.parametrize('exit_amount', [None, -1, 1.0, True])
def test_failed_or_unknown_exit_is_not_a_closed_zero_return(exit_amount):
    with pytest.raises(InsufficientAccountingData):
        native(exit_received_lamports=exit_amount)


@pytest.mark.parametrize('sold', [None, 0, 12_345_677, 12_345_679])
def test_partial_or_excess_sale_cannot_claim_closed_inventory(sold):
    with pytest.raises(InsufficientAccountingData):
        native(sold_token_atomic=sold)


def test_zero_proceeds_is_explicit_total_loss_including_known_extra_costs():
    result = native(exit_received_lamports=0,
                    fees=SolFeeBreakdown(5000, 5000, (5000,), provenance='synthetic'))
    assert result['net_pnl_lamports'] == -1_000_015_000
    assert result['final_available_cash_lamports'] == 8_999_985_000
    assert result['net_pnl_sol'] == D('-1.000015000')
    assert result['execution_verified'] is False


def test_fee_budget_is_reserved_before_an_assumed_profitable_exit_can_fund_it():
    fees = SolFeeBreakdown(5000, 5000, (), provenance='synthetic')
    with pytest.raises(InsufficientAccountingData, match='Available cash'):
        native(available_cash_lamports=1_000_009_999, fees=fees)
    result = native(available_cash_lamports=1_000_010_000, fees=fees)
    assert result['final_available_cash_lamports'] == 1_200_000_000


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 100.0, True, D('NaN'), D('Infinity'), '1e10000000'])
def test_binary_floats_and_nonfinite_or_unsupported_decimals_are_refused(bad):
    with pytest.raises(InsufficientAccountingData):
        marked(entry_token_usd=bad)


def test_exact_fraction_prevents_false_lamport_gain_near_an_integer_boundary():
    result = marked(position_lamports=1,
                    entry_token_usd=D('1'), exit_token_usd=D('0.999999999999999999999999999999999999'),
                    entry_fx=FxSnapshot(D('1'), 980, 990),
                    exit_fx=FxSnapshot(D('1'), 1980, 1990))
    assert result['exit_received_lamports'] == 0
    assert result['net_pnl_lamports'] == -1


def test_decimal_and_atomic_json_export_preserves_values_above_javascript_integer_range():
    result = native(entry_spent_lamports=9_007_199_254_740_993,
                    exit_received_lamports=9_007_199_254_740_994,
                    available_cash_lamports=9_007_199_254_740_993)
    assert result['net_pnl_lamports'] == 1
    assert result['net_pnl_sol'] == D('0.000000001')
    safe = accounting_json_safe(result)
    parsed = json.loads(json.dumps(safe, allow_nan=False))
    assert parsed['entry_spent_lamports'] == '9007199254740993'
    assert parsed['net_pnl_lamports'] == '1'
    assert parsed['acquired_token_atomic'] == '12345678'
    assert parsed['net_pnl_sol'] == '1E-9'
    assert parsed['execution_verified'] is False
    assert lamports_to_sol(9_007_199_254_740_993) == D('9007199.254740993')
