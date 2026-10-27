"""Read-only functional dashboard over the active PAPER ledger.

Counts describe stored observations, not market coverage. Financial values reuse
ledger reconciliation and its constant SOL/USD model; they never certify an
executed price, an available exit or market profitability. No database is created,
repaired, migrated or committed by reporting.
"""
import math
import re


def _columns(con, table):
    return {row[1] for row in con.execute('PRAGMA table_info('+table+')')}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _metric(value, unit, source, *, reliability='recorded', scope='database_cumulative', reason=None):
    if type(value) is float and not math.isfinite(value):
        value, reason = None, 'nonfinite_value'
    result = {'value': value, 'unit': unit, 'source': source,
              'reliability': reliability if value is not None else 'unknown', 'scope': scope}
    if value is None:
        result['reason'] = reason or 'required_data_not_recorded'
    return result


def build_functional_report(con, *, data_kind='unknown', latency_samples_ms=None,
                            exit_qualification_by_mint=None):
    """Build a JSON-safe dashboard, without assuming missing values are zero.

    ``latency_samples_ms`` maps stage names to actual measured millisecond samples;
    it never derives network latency from test runtime. Exit qualifications are
    optional caller attestations for currently open mints (True/False/unknown).
    Qualified exit quotations do not establish a fill or certify position value.
    """
    if data_kind not in ('unknown', 'synthetic', 'market_observation', 'mixed'):
        raise ValueError('Explicit supported report data kind is required')
    # Local import allows paper_engine to attach this dashboard to its reports.
    from bot.analyser.paper_engine import _realized_metrics, _valuation_scope
    from bot.analyser.paper_trader import _paper_free_capital

    metrics = {}
    def put(name, value, unit, source, **kwargs):
        metrics[name] = _metric(value, unit, source, **kwargs)
    def model(name, value, unit, source, **kwargs):
        put(name, value, unit, source, reliability='model_only', **kwargs)

    mints, detected_tables = set(), []
    for table in ('launch_candidates', 'research_launches'):
        if 'mint' in _columns(con, table):
            detected_tables.append(table)
            mints.update(row[0] for row in con.execute('SELECT DISTINCT mint FROM '+table)
                         if isinstance(row[0], str) and row[0].strip())
    put('tokens_unique_detected', len(mints) if detected_tables else None, 'mints',
        '+'.join(detected_tables) or 'launch_tables_missing', scope='recorded_mints_not_complete_market_universe')

    decisions = None
    if {'mint', 'enter', 'entry_allowed'} <= _columns(con, 'paper_decisions'):
        decisions = con.execute('SELECT mint,enter,entry_allowed FROM paper_decisions').fetchall()
    accepted = [row for row in decisions or () if row[1] == 1 and row[2] == 1]
    rejected = [row for row in decisions or () if row[1] == 0 or (row[1] == 1 and row[2] == 0)]
    for name, value, unit in (
        ('analysis_decisions', len(decisions or ()), 'decisions'),
        ('opportunities_analysed', len({row[0] for row in decisions or ()}), 'mints'),
        ('decisions_accepted', len(accepted), 'decisions'),
        ('decisions_rejected', len(rejected), 'decisions'),
        ('opportunities_accepted', len({row[0] for row in accepted}), 'mints'),
        ('opportunities_rejected', len({row[0] for row in rejected}), 'mints'),
    ):
        put(name, value if decisions is not None else None, unit, 'paper_decisions',
            scope='cumulative; repeated_mints_may_have_both_accepted_and_rejected_decisions')

    trade_columns = _columns(con, 'paper_trades')
    trades_known = {'mint', 'status'} <= trade_columns
    opened = [row[0] for row in con.execute("SELECT mint FROM paper_trades WHERE status='open'")] if trades_known else None
    closed_count = con.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'").fetchone()[0] if trades_known else None
    put('positions_open', len(opened) if opened is not None else None, 'positions', 'paper_trades.status')
    put('positions_closed', closed_count, 'positions', 'paper_trades.status')
    qualifications = {} if exit_qualification_by_mint is None else exit_qualification_by_mint
    if not isinstance(qualifications, dict):
        raise ValueError('Exit qualification must be a mapping by mint')
    unknown_exits = sum(type(qualifications.get(mint)) is not bool for mint in opened or ())
    without_exit = sum(qualifications.get(mint) is False for mint in opened or ())
    put('positions_without_qualified_exit', without_exit if opened is not None and not unknown_exits else None,
        'positions', 'caller_exit_qualification_by_mint', scope='currently_open_positions',
        reliability='attested', reason='open_position_exit_qualification_not_recorded')
    put('positions_with_unknown_exit_qualification', unknown_exits if opened is not None else None,
        'positions', 'caller_exit_qualification_by_mint', scope='currently_open_positions')

    required = {'exit_time', 'net_return', 'cost_bps', 'pnl_sol', 'position_sol', 'status', 'mint'}
    finance = {}
    closed_rows = []
    if required <= trade_columns and {'id', 'initial_capital_sol', 'realized_capital_sol'} <= _columns(con, 'paper_portfolio'):
        finance = _realized_metrics(con)
        closed_rows = con.execute("SELECT pnl_sol,position_sol,cost_bps FROM paper_trades WHERE status='closed'").fetchall()
    complete = finance.get('performance_data_complete', False)
    for name, key, unit in (
        ('capital_initial_sol', 'capital_start_sol', 'SOL'), ('capital_final_sol', 'capital_end_sol', 'SOL'),
        ('pnl_net_sol', 'pnl_sol', 'SOL'), ('portfolio_return', 'net_return_after_costs', 'fraction'),
        ('win_rate', 'win_rate', 'fraction'), ('profit_factor', 'profit_factor', 'ratio'),
        ('max_drawdown', 'max_drawdown', 'fraction'),
    ):
        model(name, finance.get(key) if complete else None, unit, 'paper_engine._realized_metrics',
              scope='realized_ledger_equity; excludes_unrealized_positions')
    pnls = [row[0] for row in closed_rows] if complete else []
    gains, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    model('average_gain_sol', math.fsum(gains)/len(gains) if gains else None, 'SOL', 'paper_trades.pnl_sol', scope='winning_closed_positions')
    model('average_loss_sol', math.fsum(losses)/len(losses) if losses else None, 'SOL', 'paper_trades.pnl_sol', scope='losing_closed_positions; negative_values')
    model('net_expectancy_sol', math.fsum(pnls)/len(pnls) if pnls else None, 'SOL', 'paper_trades.pnl_sol', scope='mean_of_closed_ledger_positions_not_population_expectation')
    valid_costs = complete and all(_finite(size) and size > 0 and _finite(cost) and cost >= 0
                                   for _, size, cost in closed_rows)
    modeled_cost = math.fsum(size*cost/10_000 for _, size, cost in closed_rows) if valid_costs else None
    gross = finance['pnl_sol']+modeled_cost if modeled_cost is not None else None
    model('modeled_cost_sol', modeled_cost, 'SOL', 'paper_trades.position_sol*cost_bps/10000',
          scope='closed_positions; cost_already_deducted_from_pnl_net')
    model('pnl_gross_sol', gross, 'SOL', 'pnl_net_sol+modeled_cost_sol',
          scope='ledger_model_before_stored_cost_bps; not_executed_gross_profit')
    free = committed = None
    if complete and 'capital_after_sol' in trade_columns:
        try:
            capital, free = _paper_free_capital(con)
            committed = capital-free
        except (TypeError, ValueError):
            pass
    model('capital_available_sol', free, 'SOL', 'paper_trader._paper_free_capital')
    model('capital_committed_sol', committed, 'SOL', 'paper_trader._paper_free_capital')
    put('observed_execution_fees_sol', None, 'SOL', 'not_in_legacy_ledger', reason='network_priority_ata_failure_costs_not_observed')
    put('realized_slippage_sol', None, 'SOL', 'not_in_legacy_ledger', reason='execution_prices_and_effective_sizes_not_observed')

    # Nearest-rank percentiles describe actual samples only, without treating
    # source block-time estimates as complete end-to-end execution latency.
    stages = {}
    if 'detection_latency_ms' in _columns(con, 'launch_candidates'):
        stages['scanner_detection'] = ([r[0] for r in con.execute('SELECT detection_latency_ms FROM launch_candidates')],
            'launch_candidates.detection_latency_ms; chain_block_time_based')
    else:
        stages['scanner_detection'] = ([], 'scanner_detection_latency_not_recorded')
    for name, values in (latency_samples_ms or {}).items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', name) or name in stages:
            raise ValueError('Distinct supported latency stage name is required')
        stages[name] = (list(values), 'caller_supplied_measured_latency_samples_ms')
    latency_counts = {}
    for name, (values, source) in stages.items():
        samples = sorted(value for value in values if _finite(value) and value >= 0)
        latency_counts[name] = {'valid_samples': len(samples), 'missing_or_invalid_samples': len(values)-len(samples)}
        for label, quantile in (('p50', .5), ('p95', .95), ('p99', .99)):
            value = samples[max(0, math.ceil(len(samples)*quantile)-1)] if samples else None
            put(name+'_latency_'+label+'_ms', value, 'ms', source,
                scope='observed_samples_nearest_rank; not_execution_latency_guarantee')

    prices = _columns(con, 'paper_prices')
    quote_count = con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0] if prices else None
    # Legacy paper_prices has no provider source timestamp; collection timestamp
    # is deliberately not substituted for it.
    missing = {'decisions_without_classifiable_permission':
                   len(decisions)-len(accepted)-len(rejected) if decisions is not None else None,
               'closed_ledger_records_incomplete': finance.get('incomplete_closed_trades'),
               'closed_ledger_records_inconsistent': finance.get('inconsistent_closed_trades'),
               'price_observations_without_provider_source_time': quote_count,
               'open_positions_with_unknown_exit_qualification': unknown_exits if opened is not None else None}
    return {'schema': 'rugger-functional-dashboard-v1', 'paper_only': True,
            'real_orders_enabled': False, 'data_kind': data_kind,
            'performance_data_complete': bool(complete),
            'capital_reconciled': finance.get('capital_reconciled', False),
            'valuation_scope': _valuation_scope(), 'economic_pnl_verified': False,
            'economic_verdict': 'INSUFFICIENT DATA', 'metrics': metrics,
            'latency_sample_counts': latency_counts, 'missing_data_counts': missing,
            'metrics_unknown_count': sum(metric['value'] is None for metric in metrics.values()),
            'missing_count_scope': 'categories_may_overlap; do_not_sum_as_unique_events'}


def summarize_market_quote_admission(admission):
    """Summarize existing offline pair classifications, never classify a fill.

    This adapter consumes the established qualification report. It does not
    re-read all archive bundles or turn incomplete quote pairs into P&L labels.
    The smoke-access pair is counted separately from LaunchLab observations.
    """
    if (type(admission) is not dict
            or admission.get('schema') != 'p3-archived-quote-pair-admission-v1'
            or type(admission.get('pairs')) is not list
            or type(admission.get('pairs_checked')) is not int
            or admission['pairs_checked'] != len(admission['pairs'])
            or type(admission.get('full_position_closures_verified')) is not int
            or admission['full_position_closures_verified'] != 0
            or admission.get('ledger_mutated') is not False
            or type(admission.get('new_network_requests')) is not int
            or admission['new_network_requests'] != 0
            or admission.get('economic_verdict') != 'INSUFFICIENT DATA'):
        raise ValueError('Unsupported or inconsistent offline quote admission report')
    pairs, seen, blockers = admission['pairs'], set(), {}
    for row in pairs:
        if (type(row) is not dict or type(row.get('run_id')) is not str
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', row['run_id'])
                or type(row.get('mint')) is not str or not row['mint'].strip()
                or type(row.get('buy_id')) is not int or row['buy_id'] < 1
                or type(row.get('sell_id')) is not int or row['sell_id'] <= row['buy_id']
                or row.get('qualification') not in ('UNQUALIFIED', 'MINIMUM_SIZE_MATCH_ONLY', 'CONDITIONAL_QUOTE_SCENARIO_ONLY')
                or row.get('net_pnl_lamports') is not None
                or type(row.get('reasons')) is not list
                or any(type(reason) is not str or not re.fullmatch(r'[a-z0-9_]{1,128}', reason)
                       for reason in row['reasons'])):
            raise ValueError('Unsupported archived pair classification')
        key = (row['run_id'], row['buy_id'], row['sell_id'])
        if key in seen:
            raise ValueError('Duplicate archived pair would inflate the observed count')
        seen.add(key)
        for reason in row['reasons']:
            blockers[reason] = blockers.get(reason, 0)+1
    reference = [row for row in pairs if row['run_id'] == 'pr19_access_smoke']
    candidates = [row for row in pairs if row['run_id'].startswith('launchlab_')
                  or row['run_id'] == 'retention_003']
    return {
        'schema': 'rugger-functional-market-evaluation-v1', 'data_kind': 'market_observation',
        'paper_only': True, 'network_requests': 0, 'ledger_mutated': False,
        'quote_pairs_checked': len(pairs), 'unique_quote_mints': len({row['mint'] for row in pairs}),
        'launchlab_quote_pairs': len(candidates), 'reference_access_smoke_pairs': len(reference),
        'other_pair_observations': len(pairs)-len(candidates)-len(reference),
        'source_runs': sorted({row['run_id'] for row in pairs}),
        'pair_qualification_counts': {state: sum(row['qualification'] == state for row in pairs)
                                    for state in sorted({row['qualification'] for row in pairs})},
        'blocker_counts': dict(sorted(blockers.items())),
        'economically_qualified_cycles': 0, 'positions_acquired': False, 'execution_verified': False,
        'pnl_gross_sol': None, 'pnl_net_sol': None, 'observed_execution_costs_sol': None,
        'realized_slippage_sol': None, 'win_rate': None, 'profit_factor': None,
        'economic_verdict': 'INSUFFICIENT DATA',
        'metric_reliability': {'counts': 'recorded_offline_quote_classifications',
            'economic_metrics': 'unknown_no_qualified_full_position_cycle'},
        'scope': 'quote_observations_include_reference_probe; not_trades_or_independent_market_sample',
        'missing_cost_evidence': admission.get('additional_fee_evidence'),
        'max_source_age_policy_ms': admission.get('max_source_age_ms'),
    }
