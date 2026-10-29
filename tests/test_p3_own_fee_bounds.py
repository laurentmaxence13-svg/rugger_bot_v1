"""Native fee bound arithmetic and rejection tests; no network or wallet."""
import pytest
from bot.p3.own_fee_bounds import legacy_v0_roundtrip_fee_bounds as fee


def params():
    return dict(buy_signatures=1,sell_signatures=1,buy_cu_limit=400000,
                sell_cu_limit=400000,priority_price_min_micro_lamports=10,
                priority_price_max_micro_lamports=100,
                extra_failed_transactions_max=1,
                worst_failed_transaction_fee_lamports=5100,
                ata_rent_locked_lamports=2039280,ata_recovered_at_horizon=None)


def test_fee_rounded_up_and_rent_separate():
    r=fee(**params())
    assert r['buy_fee_lower_lamports']=='5004'
    assert r['sell_fee_lower_lamports']=='5004'
    assert r['buy_fee_upper_lamports']=='5040'
    assert r['cost_lower_lamports']=='10008'
    assert r['cost_upper_excluding_unknown_ATA_lamports']=='15180'
    assert r['cost_upper_lamports']=='2054460'
    assert not r['all_applicable_costs_known']
    assert r['route_fees_already_in_quote_not_counted_twice']


def test_unknown_ATA_never_becomes_zero():
    p=params();p['ata_rent_locked_lamports']=None
    r=fee(**p)
    assert r['cost_upper_lamports'] is None
    assert r['rent_nonrecoverable_upper_lamports'] is None


def test_recovered_rent_only_conditional():
    p=params();p['ata_recovered_at_horizon']=True
    r=fee(**p)
    assert r['cost_upper_lamports']=='15180'
    assert r['ata_recovered_at_horizon_hypothesis'] is True
    assert r['not_a_profitability_or_fill_certificate']


@pytest.mark.parametrize('change',[{'buy_signatures':0},{'sell_cu_limit':1400001},
    {'priority_price_min_micro_lamports':101},{'buy_signatures':True},
    {'extra_failed_transactions_max':2,'worst_failed_transaction_fee_lamports':0},
    {'ata_recovered_at_horizon':'yes'},{'base_lamports_per_signature':0}])
def test_invalid_assumptions_fail_closed(change):
    p=params();p.update(change)
    with pytest.raises(ValueError):fee(**p)


def test_priority_rounding_is_per_transaction_not_per_roundtrip():
    p=params();p.update(buy_cu_limit=1,sell_cu_limit=1,
        priority_price_min_micro_lamports=1,priority_price_max_micro_lamports=1,
        extra_failed_transactions_max=0,worst_failed_transaction_fee_lamports=0,
        ata_rent_locked_lamports=0)
    r=fee(**p)
    assert r['buy_fee_lower_lamports']==r['sell_fee_lower_lamports']=='5001'
    assert r['cost_lower_lamports']==r['cost_upper_lamports']=='10002'


def test_failed_retry_bound_cannot_be_lower_than_the_declared_route_fee_ceiling():
    p=params();p['worst_failed_transaction_fee_lamports']=5039
    with pytest.raises(ValueError,match='failed_attempt_fee_bound_below_route_ceiling'):
        fee(**p)


@pytest.mark.parametrize('change',[
    {'buy_signatures':256,'base_lamports_per_signature':2**64-1},
    {'buy_cu_limit':1400000,'priority_price_max_micro_lamports':2**64-1},
    {'base_lamports_per_signature':2**63,'priority_price_min_micro_lamports':0,
     'priority_price_max_micro_lamports':0,'extra_failed_transactions_max':0},
    {'extra_failed_transactions_max':1000,'worst_failed_transaction_fee_lamports':2**64-1},
    {'ata_rent_locked_lamports':2**64-1},
])
def test_combined_native_amounts_cannot_escape_uint64_even_when_inputs_fit(change):
    p=params();p.update(change)
    with pytest.raises(ValueError,match='overflow'):
        fee(**p)


@pytest.mark.parametrize('recovered,locked_low,locked_high',[
    (True,'0','0'),(False,'2039280','2039280'),(None,'0','2039280'),
])
def test_refundable_deposit_is_separate_from_irreversible_fees(recovered,locked_low,locked_high):
    p=params();p['ata_recovered_at_horizon']=recovered
    r=fee(**p)
    assert r['economic_fee_cost_lower_lamports']=='10008'
    assert r['economic_fee_cost_upper_lamports']=='15180'
    assert r['ata_locked_at_horizon_lower_lamports']==locked_low
    assert r['ata_locked_at_horizon_upper_lamports']==locked_high
    assert r['cash_commitment_upper_lamports']=='2054460'
    assert r['rent_irrecoverability_observed'] is False
    assert r['all_applicable_costs_known'] is False


def test_unknown_deposit_keeps_cash_requirement_unknown_without_erasing_fee_scenario():
    p=params();p['ata_rent_locked_lamports']=None
    r=fee(**p)
    assert r['economic_fee_cost_upper_lamports']=='15180'
    assert r['cash_commitment_upper_lamports'] is None
    assert r['ata_locked_at_horizon_upper_lamports'] is None
    assert r['cost_upper_lamports'] is None
