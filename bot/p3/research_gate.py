"""Read-only, non-operational screening of already classified LaunchLab snapshots.

This module deliberately does not import a wallet, HTTP client, order router or
financial ledger. It does not change classify_snapshot, select_cohort, or
operational admission. A result of RESEARCH_ONLY is not identity certification,
a permitted trade, a qualified economic cycle, or a prospective experiment.

Inputs must originate from the pinned parser and classifier, with their
original capture provenance retained by the caller. UNKNOWN is not VERIFIED.
"""

_ALLOWED_UNKNOWN = ('platform_pda', 'original_platform_admin_seed_not_retained')
_REQUIRED_PDA = frozenset({
    'pool_pda', 'vault_a_pda', 'vault_b_pda', 'config_pda',
    'authority_pda', 'platform_pda',
})
_REQUIRED_DISCRIMINATORS = frozenset({
    'pool_discriminator', 'config_discriminator', 'platform_discriminator',
})
_REQUIRED_RELATIONS = frozenset({
    'input_graph', 'pool_layout_owner', 'config_layout_owner',
    'platform_layout_owner', 'pool_link_config', 'pool_link_platform',
    'pool_link_mint_a', 'pool_link_mint_b', 'pool_link_vault_a',
    'pool_link_vault_b', 'mint_a_program_owner', 'mint_b_program_owner',
    'vault_a_layout_owner', 'vault_b_layout_owner', 'vault_a_mint_link',
    'vault_b_mint_link', 'config_quote_link', 'platform_empty_curve_params',
})


def assess_research_only(analysis, screen):
    """Fail closed except for a single missing historical platform admin seed.

    Requires all other identity checks to PASS, observed activity, and full-size
    modeled exit capacity. These output flags grant no operational permission.
    """
    reasons = []

    def refuse(reason):
        reasons.append(reason)
        return {'status': 'REJECTED', 'research_only': False,
                'strict_identity_verified': False, 'trade_allowed': False,
                'economic_cycle_qualified': False, 'reasons': reasons}

    if type(analysis) is not dict or type(screen) is not dict:
        return refuse('analysis_or_screen_missing')
    if analysis.get('evidence_profile') != 'published_metadata_v1':
        return refuse('pinned_evidence_profile_required')
    if type(analysis.get('context_slot')) is not int or analysis['context_slot'] <= 0:
        return refuse('positive_source_context_slot_required')
    facts = analysis.get('facts')
    if (type(facts) is not dict
            or facts.get('account_context_basis') != 'caller_supplied_single_getMultipleAccounts_response'):
        return refuse('same_bank_account_context_required')
    if (type(facts.get('supply_consistency')) is not dict
            or facts['supply_consistency'].get('matches') is not True):
        return refuse('supply_not_certified')
    if analysis.get('risk_flags') != []:
        return refuse('risk_flags_not_clear')
    identity = facts.get('identity_certification')
    if type(identity) is not dict:
        return refuse('identity_certification_missing')
    if (identity.get('account_discriminators_verified') is not True
            or identity.get('program_derived_addresses_verified') is not False):
        return refuse('unexpected_certification_status')
    checks = identity.get('checks')
    if type(checks) is not list or not checks:
        return refuse('individual_identity_checks_required')
    statuses = {}
    for item in checks:
        if (type(item) is not dict or type(item.get('name')) is not str
                or item['name'] in statuses
                or item.get('status') not in ('PASS', 'FAIL', 'UNKNOWN')):
            return refuse('malformed_or_duplicate_identity_check')
        statuses[item['name']] = (item['status'], item.get('reason'))
    if not (_REQUIRED_PDA | _REQUIRED_DISCRIMINATORS | _REQUIRED_RELATIONS) <= statuses.keys():
        return refuse('mandatory_identity_check_missing')
    if statuses['platform_pda'] != ('UNKNOWN', _ALLOWED_UNKNOWN[1]):
        return refuse('platform_administrator_not_the_only_allowed_unknown')
    if any(status != 'PASS' for name, (status, _) in statuses.items()
           if name != _ALLOWED_UNKNOWN[0]):
        return refuse('other_identity_checks_not_verified')
    if (screen.get('screen_eligible') is not False
            or screen.get('selection_reasons') != ['identity_supply_or_permissions_unqualified']):
        return refuse('strict_screen_not_isolated_to_platform_identity')
    age = screen.get('local_snapshot_age_ms')
    if type(age) is not int or not 0 <= age <= 5000:
        return refuse('local_snapshot_age_not_acceptable')
    if (screen.get('activity_state') != 'active'
            or screen.get('observed_full_exit_capacity') is not True):
        return refuse('activity_or_model_exit_capacity_unavailable')
    entry = screen.get('own_entry_projection')
    exit_projection = screen.get('observed_exit_projection')
    if type(entry) is not dict or type(exit_projection) is not dict:
        return refuse('conditional_buy_or_sell_projection_missing')
    quantity = entry.get('buy_output_atomic')
    if (type(quantity) is not str or not quantity.isdecimal() or int(quantity) <= 0
            or str(quantity) != str(exit_projection.get('input_token_atomic'))):
        return refuse('exact_projected_token_quantity_mismatch')
    return {
        'status': 'RESEARCH_ONLY', 'research_only': True,
        'strict_identity_verified': False, 'trade_allowed': False,
        'economic_cycle_qualified': False,
        'unknown_identity_check': _ALLOWED_UNKNOWN[0],
        'reason': _ALLOWED_UNKNOWN[1],
        'scope': 'offline_conditional_research_not_prospective_selection_or_execution',
        'source_context_slot': analysis['context_slot'],
        'reasons': [_ALLOWED_UNKNOWN[1]],
    }


def assess_retained_cohort(selection):
    """Review retained records without altering the preregistered selection.

    The denominator includes failed, duplicate, and absent rows. Results are
    retrospective descriptions, not new prospective market evidence.
    """
    if type(selection) is not dict or type(selection.get('records')) is not list:
        raise ValueError('complete_prior_selection_records_required')
    records = []
    for item in selection['records']:
        if type(item) is not dict:
            raise ValueError('invalid_retained_selection_record')
        row = item.get('source_row')
        analysis = row.get('snapshot') if type(row) is dict else None
        verdict = assess_research_only(analysis, item.get('screen'))
        records.append({'universe_index': item.get('universe_index'), 'research': verdict,
                        'original_selection_reason': item.get('selection_reason')})
    return {
        'schema': 'p3-retained-offline-research-review-v1',
        'scope': 'retrospective_read_only_not_a_new_prospective_cohort',
        'universe_size': len(records),
        'research_only_count': sum(item['research']['research_only'] for item in records),
        'strict_selection_unchanged': True, 'trade_allowed': False,
        'economic_cycle_qualified': False, 'records': records,
    }
