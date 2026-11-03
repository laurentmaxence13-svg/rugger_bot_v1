"""Fail-closed checks for offline research while strict P3 remains untouched."""
from copy import deepcopy

import pytest

from bot.p3.research_gate import assess_research_only, assess_retained_cohort


IDENTITY_NAMES = (
    'input_graph', 'pool_layout_owner', 'config_layout_owner', 'platform_layout_owner',
    'pool_discriminator', 'config_discriminator', 'platform_discriminator',
    'pool_link_config', 'pool_link_platform', 'pool_link_mint_a',
    'pool_link_mint_b', 'pool_link_vault_a', 'pool_link_vault_b',
    'mint_a_program_owner', 'mint_b_program_owner', 'vault_a_layout_owner',
    'vault_b_layout_owner', 'vault_a_mint_link', 'vault_b_mint_link',
    'pool_pda', 'vault_a_pda', 'vault_b_pda', 'config_pda', 'authority_pda',
    'config_quote_link', 'platform_empty_curve_params', 'platform_pda',
)


def sample():
    from test_p3_research_integration import research_snapshot
    return research_snapshot()


def test_platform_admin_unknown_may_be_studied_but_is_never_verified_or_tradable():
    analysis, screen = sample()
    before = deepcopy((analysis, screen))
    result = assess_research_only(analysis, screen)
    assert result['status'] == 'RESEARCH_ONLY'
    assert result['research_only'] is True
    assert result['strict_identity_verified'] is result['trade_allowed'] is False
    assert result['economic_cycle_qualified'] is False
    assert (analysis, screen) == before


@pytest.mark.parametrize('change', ['missing_identity', 'other_unknown', 'bad_pda', 'unsafe_flags',
                                  'supply_mismatch', 'stale', 'quantity_mismatch',
                                  'bad_context', 'strict_gate_passed'])
def test_every_other_gap_fails_closed(change):
    a, s = sample()
    checks = a['facts']['identity_certification']['checks']
    if change == 'missing_identity':
        checks.pop(0)
    elif change == 'other_unknown':
        checks[0]['status'] = 'UNKNOWN'
    elif change == 'bad_pda':
        checks[19]['status'] = 'FAIL'
    elif change == 'unsafe_flags':
        a['risk_flags'] = ['freeze_authority_present']
    elif change == 'supply_mismatch':
        a['facts']['supply_consistency']['matches'] = False
    elif change == 'stale':
        s['local_snapshot_age_ms'] = 5001
    elif change == 'quantity_mismatch':
        s['observed_exit_projection']['input_token_atomic'] = '12344'
    elif change == 'bad_context':
        a['facts']['account_context_basis'] = 'mixed_contexts'
    elif change == 'strict_gate_passed':
        s['screen_eligible'] = True
    result = assess_research_only(a, s)
    assert result['status'] == 'REJECTED' and not result['trade_allowed']


def test_full_denominator_and_original_selection_unchanged():
    a, s = sample()
    selection = {'records': [
        {'universe_index': 0, 'source_row': {'snapshot': a}, 'screen': s,
         'selection_reason': 'excluded_by_preregistered_activity_capacity_or_identity'},
        {'universe_index': 1, 'source_row': {}, 'screen': None,
         'selection_reason': 'outside_fixed_screen_prefix'},
    ]}
    before = deepcopy(selection)
    result = assess_retained_cohort(selection)
    assert result['universe_size'] == 2
    assert result['research_only_count'] == 1
    assert result['strict_selection_unchanged'] and not result['trade_allowed']
    assert result['records'][1]['research']['status'] == 'REJECTED'
    assert selection == before
