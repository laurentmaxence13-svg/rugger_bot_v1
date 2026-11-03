"""Read-only functional dashboard over the active PAPER ledger.

Counts describe stored observations, not market coverage. Financial values reuse
ledger reconciliation and its constant SOL/USD model; they never certify an
executed price, an available exit or market profitability. No database is created,
repaired, migrated or committed by reporting.
"""
from fractions import Fraction
import json
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


def _atomic_integer(value):
    if type(value) is not str or not re.fullmatch(r'-?[0-9]{1,128}', value):
        raise ValueError('Atomic inventory amount is not retained exact decimal text')
    number = int(value)
    if str(number) != value:
        raise ValueError('Atomic inventory text is not canonical')
    return number


def _atomic_inventory_report(con):
    """Display persisted quantities per mint; never synthesize legacy holdings."""
    fields = ('mint', 'acquired_atomic', 'remaining_atomic', 'token_decimals',
              'entry_budget_lamports', 'entry_extra_lamports', 'cost_basis_total_lamports',
              'cost_basis_remaining_lamports', 'realized_pnl_lamports', 'version',
              'source_provenance', 'inventory_basis', 'entry_decision_ms',
              'last_settlement_ms', 'entry_fee_provenance')
    columns = _columns(con, 'paper_token_inventory')
    trade_mints = ({r[0] for r in con.execute('SELECT mint FROM paper_trades')}
                   if 'mint' in _columns(con, 'paper_trades') else None)
    result = {'schema': 'paper-atomic-inventory-report-v1', 'available': bool(columns),
              'positions': [], 'positions_with_atomic_inventory': 0 if not columns else None,
              'positions_fully_settled': 0 if not columns else None,
              'positions_open_partial': 0 if not columns else None,
              'positions_with_remaining_inventory': 0 if not columns else None,
              'legacy_positions_inventory_unknown': len(trade_mints) if trade_mints is not None else None,
              'realized_pnl_lamports': '0' if not columns else None,
              'settled_exit_extra_fee_lamports': '0' if not columns else None,
              'entry_extra_fee_capitalized_lamports': '0' if not columns else None,
              'recognized_extra_fee_lamports': '0' if not columns else None,
              'quantity_scope': 'per_mint_atomic_text; never_sum_different_tokens',
              'reliability': 'projected_paper_inventory_not_blockchain_execution',
              'attempts': {'accepted': None, 'rejected': None, 'unknown': None}}
    if not columns or not set(fields) <= columns:
        return result
    leg_fields = {'mint', 'quantity_atomic', 'proceeds_lamports', 'extra_fee_lamports',
                  'allocated_basis_lamports', 'pnl_lamports', 'id', 'decision_ms', 'fee_provenance'}
    legs_known = leg_fields <= _columns(con, 'paper_token_legs')
    inventory_mints, valid = set(), True
    net, exit_extra, recognized_extra, entry_extra_total = 0, 0, 0, 0
    full, partial, remaining_count = 0, 0, 0
    for raw in con.execute('SELECT '+','.join(fields)+' FROM paper_token_inventory ORDER BY mint'):
        row = dict(zip(fields, raw)); mint = row['mint']; inventory_mints.add(mint)
        try:
            acquired, remaining = (_atomic_integer(row[k]) for k in ('acquired_atomic','remaining_atomic'))
            if acquired <= 0 or not 0 <= remaining <= acquired:
                raise ValueError('Invalid persisted inventory conservation')
            legs = (con.execute('SELECT quantity_atomic,extra_fee_lamports,allocated_basis_lamports,pnl_lamports '
                                'FROM paper_token_legs WHERE mint=?', (mint,)).fetchall() if legs_known else None)
            parsed = [tuple(_atomic_integer(v) for v in leg) for leg in legs or ()]
            realized = _atomic_integer(row['realized_pnl_lamports'])
            if legs is None or sum(v[0] for v in parsed)+remaining != acquired or sum(v[3] for v in parsed) != realized:
                raise ValueError('Inventory legs and summary disagree')
            entry_extra = None if row['entry_extra_lamports'] is None else _atomic_integer(row['entry_extra_lamports'])
            if ((entry_extra is not None and entry_extra < 0)
                    or any(v[0] <= 0 or v[1] < 0 or v[2] < 0 for v in parsed)):
                raise ValueError('Negative extra fee')
            full += remaining == 0; partial += 0 < remaining < acquired; remaining_count += remaining > 0
            net += realized; exit_extra += sum(v[1] for v in parsed)
            if entry_extra is None:
                entry_extra_total = None
            elif entry_extra_total is not None:
                entry_extra_total += entry_extra
            # Entry fees are capitalized in cost basis. A partial allocation of
            # total basis does not retain a separate integer entry-fee allocation.
            # Display the exact capitalized total, but do not invent its split.
            if not parsed:
                recognized_entry = 0
            elif remaining == 0 or entry_extra == 0:
                recognized_entry = entry_extra
            else:
                recognized_entry = None
            if recognized_entry is None:
                recognized_extra = None
            elif recognized_extra is not None:
                recognized_extra += recognized_entry+sum(v[1] for v in parsed)
            exit_legs = [dict(zip(('id','decision_ms','quantity_atomic','proceeds_lamports',
                'extra_fee_lamports','allocated_basis_lamports','pnl_lamports','fee_provenance'), leg))
                for leg in con.execute('SELECT id,decision_ms,quantity_atomic,proceeds_lamports,'
                    'extra_fee_lamports,allocated_basis_lamports,pnl_lamports,fee_provenance '
                    'FROM paper_token_legs WHERE mint=? ORDER BY decision_ms,rowid',(mint,))]
            row.update(liquidated_atomic=str(acquired-remaining),
                       settled_fraction=str(Fraction(acquired-remaining, acquired)),
                       position_state='fully_settled' if remaining == 0 else 'partial' if remaining < acquired else 'open',
                       settled_legs=len(parsed), settled_exit_legs=exit_legs, inventory_consistent=True,
                       acquisition_executed=False)
        except (ValueError, TypeError):
            valid = False
            row.update(inventory_consistent=False, position_state='unqualified')
        result['positions'].append(row)
    result.update(positions_with_atomic_inventory=len(inventory_mints),
                  legacy_positions_inventory_unknown=len(trade_mints-inventory_mints) if trade_mints is not None else None,
                  positions_fully_settled=full if valid else None,
                  positions_open_partial=partial if valid else None,
                  positions_with_remaining_inventory=remaining_count if valid else None,
                  realized_pnl_lamports=str(net) if valid else None,
                  settled_exit_extra_fee_lamports=str(exit_extra) if valid else None,
                  entry_extra_fee_capitalized_lamports=str(entry_extra_total) if valid and entry_extra_total is not None else None,
                  recognized_extra_fee_lamports=str(recognized_extra) if valid and recognized_extra is not None else None,
                  inventory_consistent=valid,
                  recognized_fee_scope='settled_exit_extra_plus_entry_extra_only_when_allocation_unambiguous; pool_fees_stay_in_quotes')
    if {'qualification_json'} <= _columns(con, 'paper_token_exit_attempts'):
        counts = {'accepted': 0, 'rejected': 0, 'unknown': 0}
        for (text,) in con.execute('SELECT qualification_json FROM paper_token_exit_attempts'):
            try:
                flag = json.loads(text).get('accepted')
            except (ValueError, TypeError, AttributeError):
                flag = None
            counts['accepted' if flag is True else 'rejected' if flag is False else 'unknown'] += 1
        result['attempts'] = counts
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

    atomic_inventory = _atomic_inventory_report(con)
    native_mints = {row['mint'] for row in atomic_inventory['positions']}
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
        closed_rows = con.execute("SELECT mint,pnl_sol,position_sol,cost_bps FROM paper_trades WHERE status='closed'").fetchall()
    complete = finance.get('performance_data_complete', False)
    for name, key, unit in (
        ('capital_initial_sol', 'capital_start_sol', 'SOL'), ('capital_final_sol', 'capital_end_sol', 'SOL'),
        ('pnl_net_sol', 'pnl_sol', 'SOL'), ('portfolio_return', 'net_return_after_costs', 'fraction'),
        ('win_rate', 'win_rate', 'fraction'), ('profit_factor', 'profit_factor', 'ratio'),
        ('max_drawdown', 'max_drawdown', 'fraction'),
    ):
        model(name, finance.get(key) if complete else None, unit, 'paper_engine._realized_metrics',
              scope='realized_ledger_equity; excludes_unrealized_positions')
    pnls = [row[1] for row in closed_rows] if complete else []
    gains, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    model('average_gain_sol', math.fsum(gains)/len(gains) if gains else None, 'SOL', 'paper_trades.pnl_sol', scope='winning_closed_positions')
    model('average_loss_sol', math.fsum(losses)/len(losses) if losses else None, 'SOL', 'paper_trades.pnl_sol', scope='losing_closed_positions; negative_values')
    model('net_expectancy_sol', math.fsum(pnls)/len(pnls) if pnls else None, 'SOL', 'paper_trades.pnl_sol', scope='mean_of_closed_ledger_positions_not_population_expectation')
    legacy_rows = [row for row in closed_rows if row[0] not in native_mints]
    valid_costs = complete and all(_finite(size) and size > 0 and _finite(cost) and cost >= 0
                                   for _, _, size, cost in legacy_rows)
    native_cost = atomic_inventory['recognized_extra_fee_lamports']
    modeled_cost = (math.fsum(size*cost/10_000 for _, _, size, cost in legacy_rows)+int(native_cost)/1_000_000_000
                    if valid_costs and native_cost is not None else None)
    gross = finance['pnl_sol']+modeled_cost if modeled_cost is not None else None
    model('modeled_cost_sol', modeled_cost, 'SOL', 'legacy_position_sol*cost_bps/10000+exact_native_recognized_extra_fees',
          scope='realized_events; excludes_unrecognized_capitalized_entry_fees; never_recounts_pool_fees')
    model('pnl_gross_sol', gross, 'SOL', 'pnl_net_sol+modeled_cost_sol',
          scope='before_legacy_stored_cost_and_native_recognized_extra_fees; native_pool_fees_stay_embedded; not_executed_profit')
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
    for key in ('positions_with_atomic_inventory', 'positions_fully_settled', 'positions_open_partial',
                'positions_with_remaining_inventory', 'legacy_positions_inventory_unknown'):
        put(key, atomic_inventory[key], 'positions', 'paper_token_inventory',
            reliability='recorded_projected_inventory', scope='paper_token_inventory_persistence; not_blockchain_execution')
    valuation_scope = _valuation_scope()
    if native_mints:
        valuation_scope = dict(valuation_scope, native_quote_inventory_present=True,
            native_return_basis='exact_SOL_lamport_legs_no_FX_required',
            legacy_return_basis='USD_marks_with_constant_SOL_USD_assumption',
            native_fx_required=False)
    report = {'schema': 'rugger-functional-dashboard-v1', 'paper_only': True,
            'real_orders_enabled': False, 'data_kind': data_kind,
            'performance_data_complete': bool(complete),
            'capital_reconciled': finance.get('capital_reconciled', False),
            'valuation_scope': valuation_scope, 'economic_pnl_verified': False,
            'economic_verdict': 'INSUFFICIENT DATA', 'metrics': metrics,
            'atomic_inventory': atomic_inventory,
            'latency_sample_counts': latency_counts, 'missing_data_counts': missing,
            'metrics_unknown_count': sum(metric['value'] is None for metric in metrics.values()),
            'missing_count_scope': 'categories_may_overlap; do_not_sum_as_unique_events'}
    from bot.master_audit import master_report
    master_summary=master_report(con)
    if master_summary is not None:
        report['master_shadow']=master_summary
    return report


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


def summarize_atomic_market_events(events, control, *, token_decimals):
    """Relate control007's indicative sells to one projected buy, without settling.

    The caller verifies the one retained bundle against its separate anchor.
    Inventory arithmetic and strict exit admission remain separate: absent
    provider clocks and extra fees do not become synthetic market settlement.
    """
    from decimal import Decimal, localcontext
    from bot.p3.exit_qualification import inventory_from_buy, qualify_inventory_exit
    if (control.get('schema') != 'p3-active-exit-result-v1'
            or control.get('position_acquired') is not False
            or control.get('execution_verified') is not False
            or control.get('net_pnl_lamports') is not None
            or control.get('records') != len(events)):
        raise ValueError('Unsupported active-exit observation control')
    quotes = [e for e in events if e.get('kind') == 'quote_attempt'
              and e.get('payload', {}).get('provider') == 'raydium_trade_api']
    by_phase = {}
    for event in quotes:
        payload = event['payload']
        key = (payload.get('probe_phase'), payload.get('quote_side'))
        if key in by_phase:
            raise ValueError('Duplicate control quote phase')
        by_phase[key] = event
    if set(by_phase) != {(phase, side) for phase in ('initial','followup') for side in ('buy','sell')}:
        raise ValueError('Both observed periods and quote sides are required')
    buy = by_phase[('initial','buy')]
    inventory = inventory_from_buy(buy, basis='expected_buy_output', token_decimals=token_decimals,
        entry_decision_at_ms=buy['available_at_ms'], max_source_age_ms=5000)
    if not inventory['accepted'] or inventory['mint'] != control['selected_mint']:
        raise ValueError('Control buy cannot establish its declared projected inventory')
    acquired = int(inventory['acquired_atomic'])
    minimum = int(inventory['minimum_atomic'])
    q = int(control['fixed_sell_quantity_atomic'])
    if not 0 < q <= acquired:
        raise ValueError('Diagnostic sell quantity exceeds projected inventory')
    attempts, available_sells, full_requests, full_quotes_available = [], 0, 0, 0
    for phase in ('initial','followup'):
        sell = by_phase[(phase,'sell')]; payload = sell['payload']
        if sell.get('mint') != inventory['mint'] or int(payload['input_amount_atomic']) != q:
            raise ValueError('Control sell does not retain its fixed mint and quantity')
        available_sells += sell.get('outcome') == 'quoted'
        full_requests += int(payload['input_amount_atomic']) == acquired
        full_quotes_available += int(payload['input_amount_atomic']) == acquired and sell.get('outcome') == 'quoted'
        decision = max(sell['available_at_ms'], inventory['entry_decision_at_ms'])
        verdict = qualify_inventory_exit(inventory, sell, requested_quantity_atomic=str(q),
            exit_decision_at_ms=decision, max_source_age_ms=5000)
        attempts.append({'phase':phase, 'sell_observation_id':sell['id'],
                         'quantity_atomic':str(q), 'quoted_proceeds_lamports':payload.get('output_amount_atomic'),
                         'strict_exit_accepted':verdict['accepted'], 'reasons':verdict['reasons']})
    with localcontext() as context:
        context.prec = 40
        percent = str(Decimal(q)*100/Decimal(acquired))
    return {
        'schema': 'rugger-atomic-market-evaluation-v1', 'data_kind':'market_observation',
        'new_network_requests':0, 'ledger_mutated':False,
        'mint':inventory['mint'], 'token_decimals':token_decimals,
        'projected_entry_inventory_atomic':str(acquired), 'minimum_buy_output_atomic':str(minimum),
        'entry_budget_lamports':inventory['budget_lamports'],
        'projected_inventory_accepted':True,
        'inventory_acquisition_executed':False,
        'freshness_status':'QUALIFIED' if inventory['source_timing_qualified'] else 'UNKNOWN',
        'inventory_timing_limits':inventory['reasons'],
        'indicative_sell_quantity_atomic':str(q), 'indicative_sell_coverage_percent':percent,
        'projected_remaining_after_one_indicative_sale_atomic':str(acquired-q),
        'indicative_sell_quotes_available':available_sells, 'indicative_sell_quotes_attempted':2,
        'full_projected_quantity_sell_requests':full_requests,
        'full_projected_quantity_quote_availability_rate':None if not full_requests else
            full_quotes_available/full_requests,
        'strict_qualified_partial_exit_observations':sum(e['strict_exit_accepted'] for e in attempts),
        'settled_legs':0, 'qualified_economic_cycles':0,
        'pnl_gross_sol':None, 'pnl_net_sol':None, 'additional_execution_costs_lamports':None,
        'exit_impossibility_frequency':None, 'hypothetical_entry_impact_applied':False,
        'attempts':attempts, 'economic_verdict':'INSUFFICIENT DATA',
        'tableau':[
            {'indicateur':'Inventaire projeté pour 1 SOL','valeur':str(acquired),'effectif':1,
             'source':'007 achat initial '+str(buy['id']),'limite':'Quantité attendue, acquisition non exécutée'},
            {'indicateur':'Cotations de vente indicatives disponibles','valeur':str(available_sells)+'/2','effectif':2,
             'source':'007 ventes initiale et ultérieure','limite':'Quantité diagnostique '+str(q)+', pas toute la position'},
            {'indicateur':'Demandes de vente de toute la quantité achetée','valeur':full_requests,'effectif':full_requests,
             'source':'007 paramètres des demandes','limite':'Aucune demande complète : disponibilité complète inconnue'},
            {'indicateur':'Cycles économiques complets qualifiés','valeur':0,'effectif':1,
             'source':'Qualification stricte du scénario projeté','limite':'Horloges fournisseur et frais additionnels inconnus'},
        ],
        'scope':'projected_buy_inventory_and_indicative_partial_quote_evidence; no_cashflow_settlement_or_full_exit_inference'}
