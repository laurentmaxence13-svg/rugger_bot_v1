"""Non-operational activity gate: P3-011 retained reserves and adversarial as-of tests."""
from copy import deepcopy
from bot.p3.observed_activity import classify_predecision_reserve_change as classify


def state(mint='Ev5yE7hgt6nLjugY7o8P1tiBAdRfLoQ2zAzv3N7YpSpF', slot=462777990,
          real_a=628873252768491, real_b=42478068677,
          base=371126747231509, quote=44847327076):
    return {'mint': mint, 'pool_address': 'DpMcLGPcCbhfi6v3yAv9cQ1HXDC35jFtzer5bLfaN6jm',
            'context_slot': slot, 'evidence_profile':'published_metadata_v1', 'risk_flags': [],
            'facts': {'account_context_basis': 'caller_supplied_single_getMultipleAccounts_response',
                      'supply_consistency': {'matches':True},
                      'identity_certification': {'account_discriminators_verified':True,
                         'program_derived_addresses_verified':False,
                         'checks':[{'name':'platform_pda','status':'UNKNOWN'}]},
                      'pool': {'real_a': str(real_a), 'real_b':str(real_b),
                               'mint_a':mint,'mint_b':'So11111111111111111111111111111111111111112',
                               'total_sell_a':'793100000000000','total_fundraising_b':'85000000000','status':'0'},
                      'base_vault': {'amount_atomic':str(base)},
                      'quote_vault': {'amount_atomic':str(quote)},
                      'config': {'curve_type':0,'trade_fee_rate_ppm':12500},
                      'platform': {'platform_fee_rate_ppm':0,'creator_fee_rate_ppm':0}}}


def run(a,b):
    return classify(a,b,before_available_at_ms=1000,after_available_at_ms=2000,
                    decision_at_ms=2001)


def test_p3_011_identical_reserves_during_95_slots_are_not_momentum():
    a=state(); b=state(slot=462778085)
    original=deepcopy((a,b)); r=run(a,b)
    assert r['status']=='OBSERVED'
    assert r['signal']=='NO_NET_RESERVE_CHANGE_OBSERVED'
    assert not r['candidate_recent_net_buy_change']
    assert not r['trade_allowed']
    assert (a,b)==original


def test_p3_011_second_mint_same_reserves_is_not_momentum():
    # Only the pool reserve values come from the published RESERVE_CHANGE report;
    # vault amounts below are illustrative and not asserted to be archived bytes.
    a=state(mint='6NPuKFJh1tsYsdMEmnYpgkYoWggLaXV7i6rfHVUMVocs',real_a=63809513392877,
            real_b=1896858290,base=85000000000000,quote=1900000000)
    b=deepcopy(a);b['context_slot']=462778085
    assert run(a,b)['signal']=='NO_NET_RESERVE_CHANGE_OBSERVED'


def test_positive_directional_net_change_is_only_a_candidate():
    a=state();b=state(slot=462777991,real_a=628873252768591,real_b=42478068777,
                      base=371126747231409,quote=44847327176)
    r=run(a,b)
    assert r['signal']=='NET_BUY_COMPATIBLE_CHANGE'
    assert r['candidate_recent_net_buy_change']
    assert not r['trade_allowed'] and not r['market_profitability_verified']
    assert r['independent_buyer_count'] is None


def test_net_sell_compatible_is_not_positive():
    a=state();b=state(slot=462777991,real_a=628873252768391,real_b=42478068577,
                      base=371126747231609,quote=44847326976)
    r=run(a,b)
    assert r['signal']=='NET_SELL_COMPATIBLE_CHANGE'
    assert not r['candidate_recent_net_buy_change']


def test_same_context_slot_fails_even_when_local_receipt_changes():
    assert run(state(),state())['reason']=='same_or_reversed_context_slot'


def test_future_data_cannot_be_used_at_past_decision():
    r=classify(state(),state(slot=462777991),before_available_at_ms=1000,
               after_available_at_ms=3001,decision_at_ms=3000)
    assert r['status']=='REJECTED'
    assert r['reason']=='asof_receipt_or_age_invalid'


def test_different_pool_or_mint_is_rejected():
    a=state();b=state(slot=462777991)
    b['pool_address']='other';assert run(a,b)['status']=='REJECTED'
    b=state(mint='DifferentMint',slot=462777991)
    assert run(a,b)['status']=='REJECTED'


def test_risk_and_supply_failure_cannot_be_used():
    a=state(); b=state(slot=462777991)
    b['risk_flags']=['freeze_authority'];assert run(a,b)['status']=='REJECTED'
    b=state(slot=462777991);b['facts']['supply_consistency']['matches']=False
    assert run(a,b)['status']=='REJECTED'


def test_missing_atomic_reserves_do_not_become_zero():
    a=state(); b=state(slot=462777991)
    del b['facts']['quote_vault']['amount_atomic']
    assert run(a,b)['reason']=='invalid_or_missing_atomic_reserves'


def test_config_changes_refuse_momentum_signal():
    a=state();b=state(slot=462777991)
    b['facts']['config']['trade_fee_rate_ppm']=57500
    assert run(a,b)['reason']=='curve_or_fee_configuration_changed'


def test_mixed_changes_cannot_be_treated_as_buys():
    a=state();b=state(slot=462777991,real_a=628873252768591,real_b=42478068777,
                      base=371126747231609,quote=44847327176)
    assert run(a,b)['signal']=='MIXED_OR_NONSWAP_CHANGE'
    assert not run(a,b)['candidate_recent_net_buy_change']


def test_excessively_long_atomic_number_is_rejected_without_conversion():
    a=state(); b=state(slot=462777991)
    b['facts']['pool']['real_b']='9'*10000
    assert run(a,b)['reason']=='invalid_or_missing_atomic_reserves'
