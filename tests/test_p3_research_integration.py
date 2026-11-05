"""Research admission uses actual pinned-parser structures and no financial book.

All account bytes here are generated locally. They are neither retained market
observations nor evidence of profitable parameter settings.
"""
from copy import deepcopy

import pytest

from bot.p3 import certification as cert
from bot.p3 import launchlab
from bot.p3.cohort import classify_snapshot, select_cohort
from bot.p3.quotes import SOL_MINT
from bot.p3.research_gate import assess_research_only, assess_retained_cohort
from test_p3_launchlab import fixture, decode, encode, mutate_account


def research_snapshot(index=0, *, available_at_ms=1000, decision_at_ms=1100,
                      size_lamports=100_000_000, platform_verified=False,return_accounts=False):
    """Return (analysis, strict screen) decoded from a coherent synthetic bank."""
    original, old = fixture()
    addresses = dict(old)
    addresses['mint_a'] = encode(bytes([31+index])*32)
    addresses['platform'] = encode(bytes([61+index])*32)
    if platform_verified:
        addresses['platform'], _ = cert.find_program_address(
            (b'platform_config', bytes([61+index])*32))
    addresses['pool'], _ = cert.find_program_address(
        (b'pool', decode(addresses['mint_a']), decode(SOL_MINT)))
    addresses['config'], _ = cert.find_program_address(
        (b'global_config', decode(SOL_MINT), b'\0', b'\0\0'))
    for role, mint in (('vault_a', 'mint_a'), ('vault_b', 'mint_b')):
        addresses[role], _ = cert.find_program_address(
            (b'pool_vault', decode(addresses['pool']), decode(addresses[mint])))
    accounts = {addresses[role]: deepcopy(original[old[role]])
                for role in launchlab.ACCOUNT_ROLES}
    for role in cert.DISCRIMINATORS:
        mutate_account(accounts, addresses[role], 0, cert.DISCRIMINATORS[role])
    if platform_verified:
        mutate_account(accounts, addresses['platform'], 16, bytes([61+index])*32)
    for role, offset in (('config',141), ('platform',173), ('mint_a',205),
                         ('mint_b',237), ('vault_a',269), ('vault_b',301)):
        mutate_account(accounts, addresses['pool'], offset, decode(addresses[role]))
    mutate_account(accounts, addresses['pool'], 333, bytes([91+index])*32)
    mutate_account(accounts, addresses['vault_a'], 0, decode(addresses['mint_a']))
    authority, bump = cert.find_program_address((b'vault_auth_seed',))
    mutate_account(accounts, addresses['pool'], 16, bump)
    for role in ('vault_a', 'vault_b'):
        mutate_account(accounts, addresses[role], 32, decode(authority))
    analysis = launchlab.analyze_snapshot(accounts, context_slot=1234+index,
        expected_mint=addresses['mint_a'], pool_address=addresses['pool'],
        input_lamports=size_lamports, evidence_profile='published_metadata_v1')
    screen = classify_snapshot(analysis, size_lamports=size_lamports,
        available_at_ms=available_at_ms, decision_at_ms=decision_at_ms,
        expected_mint=addresses['mint_a'], expected_pool=addresses['pool'])
    return (accounts,addresses,analysis,screen) if return_accounts else (analysis,screen)


def research_row(index=0, *, available_at_ms=1000, decision_at_ms=1100,
                 platform_verified=False):
    analysis, _ = research_snapshot(index, available_at_ms=available_at_ms,
        decision_at_ms=decision_at_ms, platform_verified=platform_verified)
    return dict(mint=analysis['mint'], pool=analysis['pool_address'],
        quote_mint_claim=SOL_MINT, creator_claim=analysis['facts']['pool']['creator'],
        snapshot=analysis, snapshot_available_at_ms=available_at_ms)


def test_pinned_parser_graph_with_single_unknown_has_research_permission_only():
    analysis, screen = research_snapshot()
    before = deepcopy((analysis, screen))
    identity = analysis['facts']['identity_certification']
    assert analysis['risk_flags'] == []
    assert identity['blocking_reasons'] == ['original_platform_admin_seed_not_retained']
    assert screen['selection_reasons'] == ['identity_supply_or_permissions_unqualified']
    assert screen['observed_full_exit_capacity'] is True
    result = assess_research_only(analysis, screen)
    assert result['status'] == 'RESEARCH_ONLY'
    assert result['research_only'] is True
    assert result['trade_allowed'] is False
    assert result['strict_identity_verified'] is False
    assert result['economic_cycle_qualified'] is False
    assert (analysis, screen) == before


def test_two_real_structure_candidates_are_described_without_altering_strict_cohort():
    universe = [research_row(0), research_row(1)]
    before = deepcopy(universe)
    strict = select_cohort(universe, decision_at_ms=1100)
    strict_before = deepcopy(strict)
    review = assess_retained_cohort(strict)
    assert strict['selected_count'] == 0
    assert review['research_only_count'] == 2
    assert review['universe_size'] == 2
    assert review['strict_selection_unchanged'] is True
    assert review['trade_allowed'] is False
    assert review['economic_cycle_qualified'] is False
    assert strict == strict_before and universe == before


@pytest.mark.parametrize('failure_name', [
    'pool_pda', 'vault_a_pda', 'vault_b_pda', 'authority_pda',
    'config_pda', 'platform_pda', 'pool_discriminator',
    'pool_link_mint_a', 'vault_b_mint_link', 'mint_a_program_owner',
])
def test_any_failed_identity_check_blocks_research(failure_name):
    analysis, screen = research_snapshot()
    check = next(item for item in analysis['facts']['identity_certification']['checks']
                 if item['name'] == failure_name)
    check['status'] = 'FAIL'
    check['reason'] = 'synthetic_security_failure'
    result = assess_research_only(analysis, screen)
    assert result['research_only'] is False
    assert result['trade_allowed'] is False
    assert result['economic_cycle_qualified'] is False


@pytest.mark.parametrize('damage', [
    'another_mint', 'another_pool', 'different_size', 'quantity', 'modeled_proceeds',
    'supply', 'freeze',
])
def test_detached_screen_or_inconsistent_facts_cannot_grant_research(damage):
    analysis, screen = research_snapshot()
    if damage == 'another_mint':
        analysis['mint'] = research_snapshot(1)[0]['mint']
    elif damage == 'another_pool':
        analysis['pool_address'] = research_snapshot(1)[0]['pool_address']
    elif damage == 'different_size':
        screen['size_lamports'] = '1000000000'
    elif damage == 'quantity':
        screen['own_entry_projection']['buy_output_atomic'] = '1'
        screen['observed_exit_projection']['input_token_atomic'] = '1'
    elif damage == 'modeled_proceeds':
        screen['observed_exit_projection']['output_lamports'] = '999999999999'
    elif damage == 'supply':
        analysis['facts']['supply_consistency']['matches'] = False
    elif damage == 'freeze':
        analysis['risk_flags'] = ['freeze_authority_present']
    result = assess_research_only(analysis, screen)
    assert result['research_only'] is False
    assert result['trade_allowed'] is False


def test_research_permission_never_fabricates_costs_or_market_profit():
    analysis, screen = research_snapshot()
    result = assess_research_only(analysis, screen)
    model = screen['own_entry_projection']
    assert result['research_only'] is True
    assert model['additional_execution_costs_known'] is False
    assert model['net_economic_pnl_sol'] is None
    assert model['execution_verified'] is False
    assert model['position_acquired'] is False
    assert analysis['candidate_eligible'] is False
    assert analysis['real_orders_enabled'] is False
    assert analysis['creation_transaction_verified'] is False


def test_research_review_does_not_open_network_or_mutate_a_financial_book(monkeypatch):
    import socket
    import sqlite3
    def forbidden(*args, **kwargs):
        pytest.fail('Research screening attempted network or financial database access')
    analysis, screen = research_snapshot()
    before = deepcopy((analysis, screen))
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    result = assess_research_only(analysis, screen)
    assert result['research_only'] is True
    assert result['trade_allowed'] is result['economic_cycle_qualified'] is False
    assert (analysis, screen) == before


def test_research_selector_recomputes_the_same_strict_denominator_and_is_readonly(monkeypatch):
    import socket
    import sqlite3
    from bot.p3.research_gate import select_research_cohort
    universe = [research_row(0), research_row(1)]
    before = deepcopy(universe)
    strict = select_cohort(universe, decision_at_ms=1100)
    def forbidden(*args, **kwargs):
        pytest.fail('Selector attempted network or database access')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    result = select_research_cohort(universe, decision_at_ms=1100)
    assert result['strict_selection'] == strict
    assert strict['selected_count'] == 0
    assert result['selected_count'] == 2
    assert result['universe_size'] == 2
    assert result['strict_selection_unchanged'] is True
    assert result['selection_uses_provider_outcomes'] is False
    assert result['trade_allowed'] is result['economic_cycle_qualified'] is False
    for row in result['selected']:
        assert row['admission_lane'] == 'RESEARCH_ONLY'
        assert row['trade_allowed'] is False
        assert row['size_lamports'] == '100000000'
    assert universe == before


@pytest.mark.parametrize('damage', ['future', 'stale', 'mint_binding', 'pool_binding', 'non_native'])
def test_research_selector_uses_actual_availability_clock_and_bound_identity(damage):
    from bot.p3.research_gate import select_research_cohort
    row = research_row()
    decision_at_ms = 1100
    if damage == 'future':
        row['snapshot_available_at_ms'] = 1101
    elif damage == 'stale':
        row['snapshot_available_at_ms'] = 0
        decision_at_ms = 6000
    elif damage == 'mint_binding':
        row['mint'] = research_row(1)['mint']
    elif damage == 'pool_binding':
        row['pool'] = research_row(1)['pool']
    elif damage == 'non_native':
        row['quote_mint_claim'] = research_row(1)['mint']
    result = select_research_cohort([row], decision_at_ms=decision_at_ms)
    assert result['selected_count'] == 0
    assert result['strict_selection']['selected_count'] == 0
    assert result['records'][0]['research']['research_only'] is False
    assert result['universe_size'] == 1


def test_research_selector_retains_duplicates_and_fixed_prefix_without_replacement():
    from bot.p3.research_gate import select_research_cohort
    universe = [research_row(i) for i in range(7)]
    universe.insert(1, deepcopy(universe[0]))
    before = deepcopy(universe)
    result = select_research_cohort(universe, decision_at_ms=1100)
    assert result['universe_size'] == len(universe) == len(result['records'])
    assert result['selected_count'] == 2
    assert [row['universe_index'] for row in result['selected']] == [0, 2]
    assert result['strict_selection']['records'][1]['selection_reason'] == 'duplicate_mint_or_pool'
    assert result['strict_selection']['records'][-1]['selection_reason'] == 'outside_fixed_screen_prefix'
    assert result['records'][-1]['research']['research_only'] is False
    assert universe == before


def test_unrepresented_additional_identity_blocker_cannot_hide_behind_platform_unknown():
    analysis, screen = research_snapshot()
    analysis['facts']['identity_certification']['blocking_reasons'].append(
        'synthetic_additional_historical_identity_gap')
    result = assess_research_only(analysis, screen)
    assert result['research_only'] is False
    assert result['trade_allowed'] is result['economic_cycle_qualified'] is False


def test_fully_verified_snapshot_is_observed_in_its_own_lane_without_trading_permission():
    from bot.p3.research_gate import select_research_cohort
    row = research_row(platform_verified=True)
    before = deepcopy(row)
    analysis = row['snapshot']
    identity = analysis['facts']['identity_certification']
    assert identity['blocking_reasons'] == []
    assert identity['program_derived_addresses_verified'] is True
    assert all(check['status'] == 'PASS' for check in identity['checks'])
    result = select_research_cohort([row], decision_at_ms=1100)
    assert result['strict_selection']['selected_count'] == 1
    assert result['selected_count'] == 1
    assert result['selected'][0]['admission_lane'] == 'STRICT_OBSERVATION'
    assert result['selected'][0]['trade_allowed'] is False
    assert result['trade_allowed'] is result['economic_cycle_qualified'] is False
    assert analysis['candidate_eligible'] is analysis['real_orders_enabled'] is False
    assert row == before


def test_strict_and_research_observations_share_one_fixed_candidate_budget():
    from bot.p3.research_gate import select_research_cohort
    universe = [research_row(0, platform_verified=True), research_row(1),
                research_row(2, platform_verified=True)]
    strict = select_cohort(universe, decision_at_ms=1100)
    result = select_research_cohort(universe, decision_at_ms=1100)
    assert result['strict_selection'] == strict
    assert strict['selected_count'] == 2
    assert result['selected_count'] == 2
    assert [row['universe_index'] for row in result['selected']] == [0, 1]
    assert [row['admission_lane'] for row in result['selected']] == [
        'STRICT_OBSERVATION', 'RESEARCH_ONLY']
    assert result['records'][2]['selection_reason'] == 'outside_fixed_research_selected_count'
    assert all(row['trade_allowed'] is False for row in result['selected'])
