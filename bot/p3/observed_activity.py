"""Strictly as-of, read-only reserve-change evidence for LaunchLab research.

Two snapshots are PRE-DECISION features only. An entry must be decided after the
second snapshot and future exits require a *third* subsequently received state.
No price, fill, wallet, identity certification or permission is inferred here.

In LaunchLab a buy INCREASES pool real_a (sold-to-public circulation) while
reducing the token vault; a sell decreases real_a. A nonzero net change may
be compatible with a buy or a sell, but does
NOT independently certify on-chain trade volume, wallet independence, or a
provider quote's freshness. Zero changes do not prove no trades occurred.
"""

from __future__ import annotations


_IMMUTABLE_POOL = ('mint_a', 'mint_b', 'total_sell_a', 'total_fundraising_b')
_IMMUTABLE_CONFIG = ('curve_type', 'trade_fee_rate_ppm')
_IMMUTABLE_PLATFORM = ('platform_fee_rate_ppm', 'creator_fee_rate_ppm')


def _nat(value):
    """Exact unsigned atomic integer with no floats or bools."""
    if type(value) is int and 0 <= value < 2**64:
        return value
    if type(value) is str and value.isascii() and value.isdecimal() and len(value) <= 20 and str(int(value)) == value:
        converted = int(value)
        if converted < 2**64:
            return converted
    raise ValueError('noncanonical_atomic_amount')


def classify_predecision_reserve_change(
    before, after, *, before_available_at_ms, after_available_at_ms,
    decision_at_ms, max_receipt_age_ms=5000,
):
    """Return fail-closed as-of evidence, never trading admission or market PnL.

    Only a *pair of different context slots* from the same pinned pool is
    considered. A positive candidate signal requires compatible directional
    changes in pool real reserves AND both native token-vault balances. This
    is observational flow, not authenticated swap/independent-buyer evidence.
    """
    base = dict(schema='p3-predecision-reserve-activity-v1',
                scope='research_only_asof_net_reserve_change_not_trade_or_fill',
                status='REJECTED', signal='UNKNOWN',
                candidate_recent_net_buy_change=False,
                trade_allowed=False, strict_identity_verified=False,
                provider_quote_clock_verified=False,
                market_profitability_verified=False,
                independent_buyer_count=None,
                reason=None)

    def reject(reason):
        return {**base, 'reason': reason}

    if any(type(t) is not int for t in
           (before_available_at_ms, after_available_at_ms, decision_at_ms, max_receipt_age_ms)):
        return reject('timestamps_must_be_integers')
    if not (0 <= before_available_at_ms < after_available_at_ms <= decision_at_ms
            and 0 <= decision_at_ms-after_available_at_ms <= max_receipt_age_ms <= 60000):
        return reject('asof_receipt_or_age_invalid')
    if type(before) is not dict or type(after) is not dict:
        return reject('snapshots_missing')
    for state in (before, after):
        if (state.get('evidence_profile') != 'published_metadata_v1'
                or state.get('risk_flags') != []):
            return reject('source_pin_or_risk_flag_unqualified')
        facts = state.get('facts')
        if type(facts) is not dict or facts.get('account_context_basis') != 'caller_supplied_single_getMultipleAccounts_response':
            return reject('same_bank_source_graph_required')
        if (type(facts.get('supply_consistency')) is not dict
                or facts['supply_consistency'].get('matches') is not True):
            return reject('supply_not_certified')
        identity = facts.get('identity_certification')
        if type(identity) is not dict or identity.get('account_discriminators_verified') is not True:
            return reject('account_discriminators_not_verified')
        checks = identity.get('checks')
        if type(checks) is not list or any(type(c) is not dict or c.get('status') == 'FAIL' for c in checks):
            return reject('identity_failed_or_missing_check_list')
        if any(type(facts.get(k)) is not dict for k in ('pool', 'config', 'platform', 'base_vault', 'quote_vault')):
            return reject('reserves_or_program_layout_missing')
    if any(type(state.get('context_slot')) is not int or state['context_slot'] <= 0 for state in (before, after)):
        return reject('source_slot_missing')
    if before['context_slot'] >= after['context_slot']:
        return reject('same_or_reversed_context_slot')
    if any(type(state.get(field)) is not str or not state[field] for state in (before, after)
           for field in ('mint', 'pool_address')):
        return reject('pool_or_mint_missing')
    if before['mint'] != after['mint'] or before['pool_address'] != after['pool_address']:
        return reject('different_mint_or_pool')
    initial, recent = before['facts'], after['facts']
    try:
        if any(initial['pool'].get(k) != recent['pool'].get(k) for k in _IMMUTABLE_POOL):
            return reject('pool_identity_or_terms_changed')
        if any(str(initial['config'].get(k)) != str(recent['config'].get(k)) for k in _IMMUTABLE_CONFIG):
            return reject('curve_or_fee_configuration_changed')
        if any(str(initial['platform'].get(k)) != str(recent['platform'].get(k)) for k in _IMMUTABLE_PLATFORM):
            return reject('platform_fee_terms_changed')
        if _nat(initial['pool']['status']) != 0 or _nat(recent['pool']['status']) != 0:
            return reject('inactive_or_migrated_curve')
        measurements = {
            'real_a_atomic': (_nat(initial['pool']['real_a']), _nat(recent['pool']['real_a'])),
            'real_b_lamports': (_nat(initial['pool']['real_b']), _nat(recent['pool']['real_b'])),
            'base_vault_atomic': (_nat(initial['base_vault']['amount_atomic']), _nat(recent['base_vault']['amount_atomic'])),
            'quote_vault_lamports': (_nat(initial['quote_vault']['amount_atomic']), _nat(recent['quote_vault']['amount_atomic'])),
        }
    except (ValueError, TypeError, KeyError, OverflowError):
        return reject('invalid_or_missing_atomic_reserves')
    deltas = {name: end-start for name, (start, end) in measurements.items()}
    all_same = all(amount == 0 for amount in deltas.values())
    buy_compatible = (deltas['real_a_atomic'] > 0 and deltas['real_b_lamports'] > 0
                      and deltas['base_vault_atomic'] < 0 and deltas['quote_vault_lamports'] > 0)
    sell_compatible = (deltas['real_a_atomic'] < 0 and deltas['real_b_lamports'] < 0
                       and deltas['base_vault_atomic'] > 0 and deltas['quote_vault_lamports'] < 0)
    if all_same:
        signal = 'NO_NET_RESERVE_CHANGE_OBSERVED'
    elif buy_compatible:
        signal = 'NET_BUY_COMPATIBLE_CHANGE'
    elif sell_compatible:
        signal = 'NET_SELL_COMPATIBLE_CHANGE'
    else:
        signal = 'MIXED_OR_NONSWAP_CHANGE'
    return {**base, 'status': 'OBSERVED', 'reason': None,
            'signal': signal, 'candidate_recent_net_buy_change': buy_compatible,
            'observed_before_slot': before['context_slot'],
            'observed_after_slot': after['context_slot'],
            'available_before_ms': before_available_at_ms,
            'available_after_ms': after_available_at_ms,
            'decision_at_ms': decision_at_ms,
            'observed_net_deltas': {k: str(v) for k, v in deltas.items()},
            'zero_net_change_does_not_prove_zero_trades': True,
            'net_buy_compatible_does_not_certify_swap_or_creator_independence': True}
