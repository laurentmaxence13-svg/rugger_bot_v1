"""Partial-leg arithmetic does not invent an upfront funding balance."""
import pytest

from bot.p3.accounting import native_sol_inventory_totals, InsufficientAccountingData

MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'


def leg(quantity,proceeds,fee):
    return dict(quantity_atomic=quantity,proceeds_lamports=proceeds,extra_fee_lamports=fee)


def totals(legs,**changes):
    args=dict(entry_spent_lamports=1_000_000_000,acquired_token_atomic=1000,
              token_mint=MINT,entry_extra_lamports=5000,legs=legs)
    args.update(changes)
    return native_sol_inventory_totals(**args)


def test_full_partial_leg_sum_is_exact_and_additional_costs_are_counted_once():
    result=totals([leg(400,500_000_000,10000),leg(600,550_000_000,10000)])
    assert result['sold_token_atomic']==1000 and result['remaining_token_atomic']==0
    assert result['total_proceeds_lamports']==1_050_000_000
    assert result['total_extra_fee_lamports']==25000
    assert result['net_pnl_lamports']==49_975_000
    assert result['position_fully_disposed'] is True
    assert result['funding_verified'] is result['execution_verified'] is False
    assert 'initial_available_cash_lamports' not in result
    assert 'final_available_cash_lamports' not in result


def test_remaining_inventory_has_no_full_position_pnl_even_with_positive_proceeds():
    result=totals([leg(400,500_000_000,10000)])
    assert result['remaining_token_atomic']==600
    assert result['total_proceeds_lamports']==500_000_000
    assert result['net_pnl_lamports'] is None
    assert result['position_fully_disposed'] is False


def test_sequentially_funded_costs_can_be_summed_without_claiming_upfront_cash():
    result=totals([leg(400,2_000_000_000,500_000_000),leg(600,1_000_000_000,1_000_000_000)])
    assert result['total_exit_extra_lamports']==1_500_000_000
    assert result['net_pnl_lamports']==499_995_000
    assert result['funding_verified'] is False  # Funding belongs to the active ledger.


@pytest.mark.parametrize('bad', [
    [leg(1001,100,0)], [leg(500,100,0),leg(501,100,0)],
    [leg(0,100,0)], [leg(1000,100,None)], [leg(1000,100,-1)],
    [leg(1000.0,100,0)], [leg(True,100,0)], None,
])
def test_oversale_unknown_fees_and_noninteger_quantities_are_refused(bad):
    with pytest.raises(InsufficientAccountingData):totals(bad)


def test_public_identity_and_exact_entry_cost_are_required():
    with pytest.raises(InsufficientAccountingData):totals([],token_mint='not-a-public-mint')
    with pytest.raises(InsufficientAccountingData):totals([],entry_extra_lamports=None)
