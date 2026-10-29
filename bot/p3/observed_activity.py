"""Strictly as-of, read-only reserve-change evidence for LaunchLab research.

Two snapshots are PRE-DECISION features only. An entry must be decided after the
second snapshot and future exits require a *third* subsequently received state.
No price, fill, wallet, identity certification or permission is inferred here.

A nonzero net reserve change may be compatible with a buy or a sell, but does
NOT independently certify on-chain trade volume, wallet independence, or a
provider quote's freshness. Zero changes do not prove no trades occurred.
"""

from __future__ import annotations


_IMMUTABLE_POOL_KEYS = ('mint_a', 'mint_b', 'config', 'platform', 'vault_a', 'vault_b', 'creator')
_IMMUTABLE_POOL_AMOUNTS = ('supply', 'total_sell_a', 'total_fundraising_b',
                          'virtual_a', 'virtual_b', 'decimals_a', 'decimals_b',
                          'migrate_type', 'mint_program_flag', 'migrate_fee')
_IMMUTABLE_CONFIG = ('curve_type', 'trade_fee_rate_ppm', 'max_share_fee_rate_ppm')
_IMMUTABLE_PLATFORM = ('platform_fee_rate_ppm', 'creator_fee_rate_ppm')
_REQUIRED_CHECKS = frozenset((
    'input_graph', 'pool_layout_owner', 'config_layout_owner', 'platform_layout_owner',
    'pool_discriminator', 'config_discriminator', 'platform_discriminator',
    'pool_link_config', 'pool_link_platform', 'pool_link_mint_a', 'pool_link_mint_b',
    'pool_link_vault_a', 'pool_link_vault_b', 'mint_a_program_owner', 'mint_b_program_owner',
    'vault_a_layout_owner', 'vault_b_layout_owner', 'vault_a_mint_link', 'vault_b_mint_link',
    'pool_pda', 'vault_a_pda', 'vault_b_pda', 'config_pda', 'authority_pda',
    'config_quote_link', 'platform_empty_curve_params', 'platform_pda'))
_ADMIN_UNKNOWN = 'original_platform_admin_seed_not_retained'


def _nat(value):
    """Exact unsigned atomic integer with no floats or bools."""
    if type(value) is int and 0 <= value < 2**64:
        return value
    if type(value) is str and value.isascii() and value.isdecimal() and len(value) <= 20 and str(int(value)) == value:
        converted = int(value)
        if converted < 2**64:
            return converted
    raise ValueError('noncanonical_atomic_amount')


def snapshot_safety_reason(state):
    """Validate the pinned decoded structure; callers still verify raw replay.

    These are observational checks, never a replacement for STRICT admission.
    The only accepted identity UNKNOWN is the historical platform-admin seed.
    """
    from bot.p3.certification import SOURCE_PINS,ROLES,find_program_address
    from bot.p3.quotes import SOL_MINT
    if (type(state) is not dict or state.get('evidence_profile')!='published_metadata_v1'
            or state.get('risk_flags')!=[]):
        return 'source_pin_or_risk_flag_unqualified'
    if type(state.get('context_slot')) is not int or state['context_slot']<=0:
        return 'source_slot_missing'
    facts=state.get('facts')
    if (type(facts) is not dict
            or facts.get('account_context_basis')!='caller_supplied_single_getMultipleAccounts_response'):
        return 'same_bank_source_graph_required'
    if (type(facts.get('supply_consistency')) is not dict
            or facts['supply_consistency'].get('matches') is not True):
        return 'supply_not_certified'
    identity=facts.get('identity_certification')
    if (type(identity) is not dict or identity.get('source_pins')!=SOURCE_PINS
            or identity.get('account_discriminators_verified') is not True):
        return 'account_discriminators_or_source_pins_not_verified'
    checks=identity.get('checks')
    if (type(checks) is not list
            or any(type(c) is not dict or type(c.get('name')) is not str for c in checks)):
        return 'identity_failed_or_missing_check_list'
    by_name={c.get('name'):c for c in checks}
    if len(by_name)!=len(checks) or not _REQUIRED_CHECKS <= by_name.keys():
        return 'mandatory_identity_check_missing_or_duplicate'
    for name,check in by_name.items():
        if check.get('status')=='PASS':continue
        if (name=='platform_pda' and check.get('status')=='UNKNOWN'
                and check.get('reason')==_ADMIN_UNKNOWN):continue
        return 'identity_check_failed_or_unknown_outside_research_scope'
    platform_unknown=by_name['platform_pda']['status']=='UNKNOWN'
    if (identity.get('program_derived_addresses_verified') is not (not platform_unknown)
            or identity.get('blocking_reasons')!=([_ADMIN_UNKNOWN] if platform_unknown else [])):
        return 'identity_summary_inconsistent_with_checks'
    if any(type(facts.get(k)) is not dict for k in
           ('pool','config','platform','base_mint','quote_mint','base_vault','quote_vault','addresses')):
        return 'reserves_or_program_layout_missing'
    addresses=facts['addresses'];pool=facts['pool']
    if (set(addresses)!=set(ROLES) or addresses['pool']!=state.get('pool_address')
            or addresses['mint_a']!=state.get('mint')
            or addresses['mint_b']!=SOL_MINT
            or any(pool.get(k)!=addresses[k] for k in ROLES if k!='pool')
            or facts['config'].get('quote_mint')!=SOL_MINT):
        return 'decoded_pool_graph_relation_inconsistent'
    authority=find_program_address((b'vault_auth_seed',))[0]
    for role,mint_role in (('base_vault','mint_a'),('quote_vault','mint_b')):
        vault=facts[role]
        if (vault.get('mint')!=addresses[mint_role] or vault.get('authority')!=authority
                or vault.get('delegate_present') is not False
                or vault.get('close_authority_present') is not False):
            return 'vault_identity_or_permissions_unqualified'
    base=facts['base_mint'];quote=facts['quote_mint']
    if (base.get('mint_authority_present') is not False
            or base.get('freeze_authority_present') is not False
            or quote.get('freeze_authority_present') is not False
            or base.get('initialized') is not True or quote.get('initialized') is not True):
        return 'mint_permissions_unqualified'
    try:
        if (_nat(pool['supply'])!=_nat(base['supply_atomic'])
                or _nat(pool['decimals_a'])!=_nat(base['decimals'])
                or _nat(pool['decimals_b'])!=_nat(quote['decimals'])):
            return 'pool_mint_supply_or_decimals_inconsistent'
        if _nat(pool['status'])!=0 or _nat(facts['config']['curve_type'])!=0:
            return 'inactive_or_migrated_curve'
        if _nat(facts['share_fee_assumption_ppm'])>_nat(facts['config']['max_share_fee_rate_ppm']):
            return 'share_fee_exceeds_configured_maximum'
        if (_nat(facts['base_vault']['state'])!=1 or _nat(facts['quote_vault']['state'])!=1
                or facts['quote_vault'].get('is_native') is not True):
            return 'vault_state_or_native_quote_unqualified'
    except (ValueError,TypeError,KeyError,OverflowError):
        return 'invalid_or_missing_identity_terms'
    return None


def snapshot_transition_reason(before,after):
    """Refuse changing security/curve terms across two independently read banks."""
    for state in (before,after):
        reason=snapshot_safety_reason(state)
        if reason:return reason
    if before.get('mint')!=after.get('mint') or before.get('pool_address')!=after.get('pool_address'):
        return 'different_mint_or_pool'
    initial,recent=before['facts'],after['facts']
    try:
        if (initial['addresses']!=recent['addresses']
                or any(initial['pool'].get(k)!=recent['pool'].get(k) for k in _IMMUTABLE_POOL_KEYS)
                or any(_nat(initial['pool'][k])!=_nat(recent['pool'][k]) for k in _IMMUTABLE_POOL_AMOUNTS)):
            return 'pool_identity_or_terms_changed'
        if any(_nat(initial['config'][k])!=_nat(recent['config'][k]) for k in _IMMUTABLE_CONFIG):
            return 'curve_or_fee_configuration_changed'
        if any(_nat(initial['platform'][k])!=_nat(recent['platform'][k]) for k in _IMMUTABLE_PLATFORM):
            return 'platform_fee_terms_changed'
        if _nat(initial['share_fee_assumption_ppm'])!=_nat(recent['share_fee_assumption_ppm']):
            return 'share_fee_assumption_changed'
        mint_terms=('supply_atomic','decimals','mint_authority_present','mint_authority',
                    'freeze_authority_present','freeze_authority','token_program','extension_types')
        if any(initial['base_mint'].get(k)!=recent['base_mint'].get(k) for k in mint_terms):
            return 'base_mint_supply_or_permissions_changed'
        for role in ('base_vault','quote_vault'):
            if any(initial[role].get(k)!=recent[role].get(k) for k in
                   ('mint','authority','delegate_present','close_authority_present','state','is_native','token_program')):
                return 'vault_identity_or_permissions_changed'
    except (ValueError,TypeError,KeyError,OverflowError):
        return 'invalid_or_missing_identity_terms'
    return None


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
    reason=snapshot_transition_reason(before,after)
    if reason:return reject(reason)
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
    base_inventory_conserved=deltas['real_a_atomic']==-deltas['base_vault_atomic']
    # real_a is sold/outstanding tokens, not the base asset reserve. A buy
    # increases real_a while decreasing the physical base-vault balance.
    buy_compatible = (deltas['real_a_atomic'] > 0 and deltas['real_b_lamports'] > 0
                      and deltas['base_vault_atomic'] < 0 and deltas['quote_vault_lamports'] > 0
                      and base_inventory_conserved)
    sell_compatible = (deltas['real_a_atomic'] < 0 and deltas['real_b_lamports'] < 0
                       and deltas['base_vault_atomic'] > 0 and deltas['quote_vault_lamports'] < 0
                       and base_inventory_conserved)
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
            'base_inventory_delta_conserved':base_inventory_conserved,
            'zero_net_change_does_not_prove_zero_trades': True,
            'net_buy_compatible_does_not_certify_swap_or_creator_independence': True}
