"""Immutable P3-012 public-chain OBSERVATION protocol, not a network runner.

P3-011 found static reserves on the two selected pools and provider quotes had
no source clock. P3-012 instead preselects from twelve S0->S1 same-bank
snapshots, freezes decisions before S2, and prices only *conditional* markouts.
No provider quote or wallet/order endpoint is authorized by this plan.
"""
from copy import deepcopy
import hashlib
import json
import re


FIXED=dict(
    schema='p3-asof-bank-012-plan-v1',
    run_id='p3_asof_012',
    index_source='https://launch-mint-v1.raydium.io/get/list',
    index_sort='lastTrade',
    rpc_source='https://api.mainnet.solana.com',
    commitment='confirmed',
    universe_limit=100,
    unique_native_SOL_prefix=12,
    max_pools_per_group=12,
    max_accounts_per_getMultipleAccounts=100,
    candidates_max=2,
    initial_budget_lamports=100000000,
    separate_reference_budget_lamports=1000000000,
    provider_quotes_authorized=False,
    external_orders_authorized=False,
    market_connection_requires_registered_plan_and_preflight=True,
    snapshots=['S0_predecision','S1_predecision','S2_postdecision'],
    first_interval_minimum_ms=15000,
    second_interval_minimum_ms=15000,
    max_S1_receipt_age_ms=5000,
    max_S0_receipt_age_at_decision_ms=30000,
    phase_timeouts_seconds=dict(total=8,connect=4,sock_connect=3,sock_read=4),
    process_child_deadline_seconds=58,
    process_termination_reserve_seconds=2,
    primary_model_input_lamports=100000000,
    position_sizes_lamports=[100000000,1000000000],
    source_clock='solana_getMultipleAccounts_context_slot_only',
    bank_time='getBlockTime_estimate_not_provider_quote_source_clock',
    selection='pinned_STRICT_or_RESEARCH_ONLY_plus_S0_S1_net_buy_compatible_change',
    selection_function='bot.p3.asof_wide_selection.select_twelve_prefix_asof_research',
    selection_known_before_S2=True,
    all_universe_rows_refusals_and_static_pools_retained=True,
    S2_winner_only_selection_prohibited=True,
    quote_resizing_prohibited=True,
    unknown_admin_never_promoted=True,
    cost_basis='separate_explicit_paper_legacy_v0_bounds_not_observed',
    cost_assumptions=dict(buy_signatures=1,sell_signatures=1,
        buy_cu_limit=1400000,sell_cu_limit=1400000,
        priority_price_min_micro_lamports=0,priority_price_max_micro_lamports=1000,
        extra_failed_transactions_max=2,worst_failed_transaction_fee_lamports=6400),
    ATA_scenarios=['unknown_ATA','hypothetical_existing_ATA','hypothetical_new_classic_ATA'],
    classic_ATA_deposit_hypothesis_lamports=2039280,
    historical_signature_page_limit=1000,
    historical_platforms_max=2,
    historical_selection='first_two_unique_platforms_of_fixed_S0_native_prefix',
    historical_tx_selection='oldest_successful_signature_in_single_received_page_at_or_before_S0',
    historical_lookup_timing='inside_S0_S1_interval; proof_available_before_decision_or_no_refinement',
    decisions='existing_Master_reference_paired_research_abstentions_when_USD_features_unknown; freeze_before_S2',
    partial_capture_policy='retain_committed_prefix_and_close_as_interrupted; never_resume_market_requests',
    own_buy_impact_on_actual_S2='unmodeled; no certified_strict_cycle_or_market_PnL',
    max_requests=20,
    max_elapsed_ms=60000,
    no_retry=True,
    stop_at_first_malformed_or_transport_source_error=True,
    request_budget=dict(
        discovery=1,pool_roots=1,
        S0_group_bank=1,S1_group_bank=1,S2_selected_group_bank=1,
        optional_S0_S1_S2_bank_times=3,
        bounded_historical_platform_signature_and_tx_pages=4,
        reserve_unspent=8),
    output_label='conditional_slot_markout_not_fill_not_realized_profit',
    historical_archive_reuse_as_new_capture=False,
    policy_active_change=False,
    ledger_mutation=False,
    trade_allowed=False,
)


def make_plan(*,registered_at_ms,source_revision):
    if (type(registered_at_ms) is not int or registered_at_ms<=0
            or type(source_revision) is not str
            or re.fullmatch('[0-9a-f]{40}',source_revision) is None):
        raise ValueError('explicit_registration_and_source_git_commit_required')
    return dict(deepcopy(FIXED),registered_at_ms=registered_at_ms,
                source_revision=source_revision)


def validate_plan(plan,*,first_observation_at_ms=None):
    if type(plan) is not dict:
        raise ValueError('exact_registered_P3_012_protocol_required')
    try:
        expected=make_plan(registered_at_ms=plan['registered_at_ms'],
                           source_revision=plan['source_revision'])
    except (KeyError,TypeError,ValueError):
        raise ValueError('exact_registered_P3_012_protocol_required') from None
    if plan!=expected:
        raise ValueError('altered_or_unsupported_P3_012_plan')
    if sum(plan['request_budget'].values())!=plan['max_requests']:
        raise ValueError('request_budget_not_bound')
    if (first_observation_at_ms is not None
            and (type(first_observation_at_ms) is not int
                 or first_observation_at_ms<=plan['registered_at_ms'])):
        raise ValueError('first_observation_must_follow_published_registration')
    return hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':'),
                                     allow_nan=False).encode()).hexdigest()
