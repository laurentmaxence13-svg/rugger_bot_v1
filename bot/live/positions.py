"""Causal native-SOL position proposals over finalized live inventory.

No network or signing occurs here. Exit values are explicitly conditional pinned
curve models over observed banks, not fills or external executable quotes. The
same Master trigger precedence is reused without inventing USD prices. Entry
thresholds must have been frozen before the original order was prepared.
"""
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import re

from bot.master_positions import choose_frozen_position_action, _features, _integer
from bot.p3 import launchlab
from bot.p3.certification import _decode
from bot.p3.observed_activity import snapshot_transition_reason
from .journal import ACTIVE, canonical, uint
from .route import PreparedLaunchLabOrder, validate_prepared_order
from .safety import HealthEvidence


@dataclass(frozen=True)
class FrozenEntryPlan:
    entry_decision_id: str
    entry_at_ms: int
    tp_pct: str
    sl_pct: str
    trailing_stop_pct: str
    hold_seconds: int
    net_take_profit_lamports: int
    max_observation_age_ms: int
    max_price_impact_bps: int

    def __post_init__(self):
        if type(self.entry_decision_id) is not str or not 1 <= len(self.entry_decision_id) <= 128:
            raise ValueError('frozen_entry_decision_identity_required')
        uint(self.entry_at_ms, positive=True)
        for name in ('tp_pct', 'sl_pct', 'trailing_stop_pct'):
            value = getattr(self, name)
            if (type(value) is not str or re.fullmatch(r'(0|[1-9][0-9]*)(\.[0-9]{1,6})?', value) is None
                    or not 0 <= Fraction(value) <= 10000):
                raise ValueError('explicit_bounded_decimal_threshold_required')
        if Fraction(self.sl_pct) > 100 or Fraction(self.trailing_stop_pct) > 100:
            raise ValueError('loss_and_trailing_threshold_must_not_exceed_100_percent')
        uint(self.hold_seconds); uint(self.net_take_profit_lamports)
        if type(self.max_observation_age_ms) is not int or not 0 < self.max_observation_age_ms <= 5000:
            raise ValueError('explicit_bounded_observation_age_required')
        if type(self.max_price_impact_bps) is not int or not 0 <= self.max_price_impact_bps < 10000:
            raise ValueError('explicit_price_impact_ceiling_required')

    @property
    def digest(self):
        return hashlib.sha256(canonical(asdict(self)).encode()).hexdigest()

    def master_model(self):
        # At most six decimal places, preserved by str(float(value)) for these
        # bounded human thresholds. All currency/quantity arithmetic stays int.
        return dict(tp_pct=float(self.tp_pct), sl_pct=float(self.sl_pct),
            trailing_stop_pct=float(self.trailing_stop_pct), hold_seconds=self.hold_seconds,
            net_take_profit_lamports=self.net_take_profit_lamports)


def _tables(journal):
    journal.con.executescript('''
      CREATE TABLE IF NOT EXISTS live_position_plans(
        mint TEXT NOT NULL,pool TEXT NOT NULL,plan_json TEXT NOT NULL,
        registered_at_ms INTEGER NOT NULL,PRIMARY KEY(mint,pool));
      CREATE TABLE IF NOT EXISTS live_position_decisions(
        mint TEXT NOT NULL,pool TEXT NOT NULL,frame_id TEXT NOT NULL,
        frame_sha256 TEXT NOT NULL,result_json TEXT NOT NULL,
        PRIMARY KEY(mint,pool,frame_id));
      CREATE TABLE IF NOT EXISTS live_position_peaks(
        mint TEXT NOT NULL,pool TEXT NOT NULL,numerator TEXT NOT NULL,
        denominator TEXT NOT NULL,last_available_at_ms INTEGER NOT NULL,
        last_source_slot INTEGER NOT NULL,PRIMARY KEY(mint,pool));
    ''')


def _verify(journal):
    journal.verify_audit()
    plans, decisions, peaks = {}, {}, {}
    for row in journal.con.execute('SELECT event_json FROM audit ORDER BY sequence'):
        event = json.loads(row[0])
        kind = event['kind']
        if kind not in ('live_position_plan', 'live_position_decision'):
            continue
        key = (event['mint'], event['pool'])
        if kind == 'live_position_plan':
            if key in plans:
                raise ValueError('position_plan_duplicate_audit')
            plans[key] = (event['plan_json'], event['at_ms'])
        else:
            decisions[(*key, event['frame_id'])] = (event['frame_sha256'], event['result_json'])
            if event['peak_record'] is not None:
                peaks[key] = tuple(event['peak_record'])
    actual_plans = {(r['mint'], r['pool']): (r['plan_json'], r['registered_at_ms'])
                    for r in journal.con.execute('SELECT * FROM live_position_plans')}
    actual_decisions = {(r['mint'], r['pool'], r['frame_id']): (r['frame_sha256'], r['result_json'])
                        for r in journal.con.execute('SELECT * FROM live_position_decisions')}
    actual_peaks = {(r['mint'], r['pool']): (r['numerator'], r['denominator'],
                        r['last_available_at_ms'], r['last_source_slot'])
                    for r in journal.con.execute('SELECT * FROM live_position_peaks')}
    if (plans, decisions, peaks) != (actual_plans, actual_decisions, actual_peaks):
        raise ValueError('live_position_state_not_bound_to_durable_audit')


def persist_entry_plan(journal, mint, pool, plan, *, at_ms):
    """Call at Master ENTER, before execute() creates/prepares the buy order."""
    _decode(mint); _decode(pool); uint(at_ms, positive=True)
    if type(plan) is not FrozenEntryPlan or plan.entry_at_ms > at_ms:
        raise ValueError('explicit_asof_frozen_entry_plan_required')
    _tables(journal); _verify(journal)
    encoded = canonical(asdict(plan))
    with journal.atomic():
        old = journal.con.execute('SELECT plan_json FROM live_position_plans WHERE mint=? AND pool=?', (mint,pool)).fetchone()
        if old:
            if old[0] != encoded:
                raise ValueError('entry_plan_is_immutable')
            return plan.digest
        if journal.get(plan.entry_decision_id) is not None:
            raise ValueError('entry_plan_must_be_frozen_before_order_preparation')
        journal.con.execute('INSERT INTO live_position_plans VALUES(?,?,?,?)', (mint,pool,encoded,at_ms))
        journal._audit('live_position_plan', at_ms, mint=mint, pool=pool, plan_json=encoded)
    return plan.digest


def _healthy(health, at, maximum_age):
    if type(health) is HealthEvidence:
        clocks = (health.observed_at_ms, health.scanner_heartbeat_at_ms,
                  health.rpc_success_at_ms, health.websocket_heartbeat_at_ms)
        return (health.scanner_connected and health.rpc_connected and health.websocket_connected
                and all(type(t) is int and 0 <= at-t <= maximum_age for t in clocks))
    return (type(health) is dict and health.get('allow_position_management') is True
            and type(health.get('observed_at_ms')) is int
            and 0 <= at-health['observed_at_ms'] <= maximum_age)


def _analysis(order):
    request = json.loads(order.rebuild_request_json)
    return launchlab.analyze_snapshot(request['accounts'], context_slot=order.source_slot,
        expected_mint=order.mint, pool_address=order.pool, input_lamports=1,
        evidence_profile='published_metadata_v1', compute_projection=False)


def evaluate_live_position(journal, mint, pool, frame, *, entry_plan=None, health=None, at):
    _decode(mint); _decode(pool); uint(at, positive=True)
    _tables(journal); _verify(journal)
    result = dict(schema='rugger-live-position-decision-v1', action='WAIT_FOR_DATA',
        input_quantity_atomic=None, remaining_atomic=None, remaining_basis_lamports=None,
        conditional_full_net_lamports=None, conditional_position_net_lamports=None,
        conditional_exit_gross_lamports=None, exit_fee_upper_lamports=None,
        frozen_plan_sha256=None, decision_at_ms=at, source_frame_id=None,
        source_slot=None, route_semantic_digest=None, reasons=[], quote_refusals=[],
        execution_blocked=True, liquidity_model_qualified=False,
        liquidation_basis='CONDITIONAL_PINNED_CURVE_AT_OBSERVED_BANK',
        costs_scope='actual_finalized_entry_basis_plus_explicit_exit_network_upper_bound; curve_fees_already_in_output; ATA_rent_is_locked_asset',
        observed_inventory_finalized=False, execution_verified=False,
        economic_edge_proven=False, active_policy_changed=False)
    record = journal.con.execute('SELECT * FROM live_position_plans WHERE mint=? AND pool=?', (mint,pool)).fetchone()
    if not record:
        return dict(result, reasons=['pre_entry_frozen_plan_missing'])
    plan = FrozenEntryPlan(**json.loads(record['plan_json']))
    if entry_plan is not None and entry_plan != plan:
        return dict(result, reasons=['supplied_entry_plan_differs_from_frozen_plan'])
    result['frozen_plan_sha256'] = plan.digest
    original = journal.get(plan.entry_decision_id)
    if not original or original['state'] != 'RECONCILED':
        return dict(result, reasons=['original_buy_not_finalized_and_reconciled'])
    original_order = json.loads(original['order_json'])
    original_fill = json.loads(original['reconciliation_json'])
    if (original_order['side'] != 'BUY' or original_order['mint'] != mint or original_order['pool'] != pool
            or original_fill['chain_error'] is not None or record['registered_at_ms'] > original['created_at_ms']):
        return dict(result, reasons=['frozen_entry_binding_invalid'])
    position = journal.con.execute('SELECT * FROM positions WHERE mint=? AND pool=?', (mint,pool)).fetchone()
    if not position:
        return dict(result, reasons=['finalized_native_inventory_missing'])
    remaining, basis = position['quantity_atomic'], position['entry_cost_lamports']
    result.update(remaining_atomic=str(remaining), remaining_basis_lamports=str(basis), observed_inventory_finalized=True)
    if remaining == 0:
        return dict(result, action='HOLD', input_quantity_atomic='0', reasons=['position_already_closed'])
    if type(frame) is not dict or type(frame.get('id')) is not str or not 1 <= len(frame['id']) <= 128:
        return dict(result, reasons=['causal_position_frame_identity_missing'])
    available = frame.get('available_at_ms')
    if (type(available) is not int or not plan.entry_at_ms <= available <= at
            or at-available > plan.max_observation_age_ms or frame.get('mint') != mint or frame.get('pool') != pool):
        return dict(result, reasons=['position_frame_stale_future_or_identity_mismatch'])
    orders = [frame.get('prepared_full_exit')]
    partials = frame.get('prepared_partial_exits', ())
    if type(partials) not in (tuple,list) or len(partials)>4:
        return dict(result, reasons=['bounded_exact_partial_routes_required'])
    orders += list(partials)
    fingerprint = hashlib.sha256(canonical(dict(id=frame['id'], mint=mint, pool=pool,
        available_at_ms=available, source_slot=frame.get('source_slot'),
        inventory_quantity=remaining,inventory_basis=basis,ledger_sha256=journal._ledger_digest(),
        order_digests=[o.semantic_digest if type(o) is PreparedLaunchLabOrder else None for o in orders],
        features=frame.get('features'), features_available_at_ms=frame.get('features_available_at_ms'))).encode()).hexdigest()
    old = journal.con.execute('SELECT * FROM live_position_decisions WHERE mint=? AND pool=? AND frame_id=?', (mint,pool,frame['id'])).fetchone()
    if old:
        if old['frame_sha256'] != fingerprint:
            raise ValueError('position_frame_id_reused_with_changed_observations')
        restored=json.loads(old['result_json'])
        if journal.killed or not _healthy(health,at,plan.max_observation_age_ms):
            return dict(restored,execution_blocked=True,
                reasons=restored['reasons']+['current_health_or_kill_blocks_replayed_decision'])
        return restored
    result.update(source_frame_id=frame['id'], source_slot=frame.get('source_slot'))
    state = journal.con.execute('SELECT * FROM live_position_peaks WHERE mint=? AND pool=?', (mint,pool)).fetchone()
    if state and (available <= state['last_available_at_ms'] or type(frame.get('source_slot')) is not int
                  or frame['source_slot'] < state['last_source_slot']):
        return dict(result, reasons=['position_frame_reversed_or_duplicate_clock'])
    settled = []
    for row in journal.con.execute("SELECT * FROM orders WHERE state='RECONCILED'"):
        order = json.loads(row['order_json'])
        if order['mint'] == mint and order['pool'] == pool:
            settled.append((row,json.loads(row['reconciliation_json'])))
    last_slot = max(fill['slot'] for _,fill in settled)
    last_at = max(row['updated_at_ms'] for row,_ in settled)
    realized = 0
    successful_buys=[row['decision_id'] for row,fill in settled
                     if json.loads(row['order_json'])['side']=='BUY' and fill['chain_error'] is None]
    if successful_buys != [plan.entry_decision_id]:
        return dict(result,reasons=['additional_entry_without_matching_frozen_position_plan'])
    for row, fill in settled:
        order = json.loads(row['order_json'])
        if order['side']=='SELL' and fill['chain_error'] is None:
            realized += fill['gross_output_lamports']-fill['fee_lamports']
        elif fill['chain_error'] is not None:
            realized -= fill['fee_lamports']
    # Total realized plus current liquidation minus original actual entry cost.
    original_cost = original_order['input_amount']+original_fill['fee_lamports']
    accepted=[]
    initial_request=json.loads(original_order['rebuild_request_json'])
    initial_analysis=launchlab.analyze_snapshot(initial_request['accounts'],
        context_slot=original_order['source_slot'], expected_mint=mint,pool_address=pool,
        input_lamports=1,evidence_profile='published_metadata_v1',compute_projection=False)
    for order in orders:
        try:
            order=validate_prepared_order(order)
            if (order.side!='SELL' or order.mint!=mint or order.pool!=pool or order.user!=original_order['user']
                    or not 0<order.input_amount<=remaining or order.base_balance_before!=remaining
                    or not last_at<=order.source_available_at_ms<=available
                    or not 0<=at-order.source_available_at_ms<=plan.max_observation_age_ms
                    or not order.source_available_at_ms<=order.decision_at_ms<=available
                    or order.source_slot<last_slot or order.source_slot!=frame.get('source_slot')
                    or order.price_impact_bps>plan.max_price_impact_bps):
                raise ValueError('exit_model_quantity_causality_identity_or_limits_invalid')
            changed=snapshot_transition_reason(initial_analysis,_analysis(order))
            if changed:
                raise ValueError('entry_exit_bank_terms_changed:'+changed)
            net=order.expected_output-order.network_fee_upper_lamports
            allocated=basis*order.input_amount//remaining
            accepted.append(dict(quantity_atomic=str(order.input_amount),
                proceeds_lamports=str(order.expected_output),
                extra_fees_lamports=str(order.network_fee_upper_lamports),
                conditional_net_lamports=str(net-allocated),
                conditional_total_position_net_lamports=str(realized+net-original_cost) if order.input_amount==remaining else None,
                route_semantic_digest=order.semantic_digest,order=order))
        except (ValueError,TypeError,KeyError,OverflowError) as error:
            result['quote_refusals'].append(type(error).__name__+':'+str(error))
    full=next((v for v in accepted if int(v['quantity_atomic'])==remaining),None)
    partial=max((v for v in accepted if int(v['quantity_atomic'])<remaining),key=lambda v:int(v['quantity_atomic']),default=None)
    ratio=Fraction(int(full['proceeds_lamports'])-int(full['extra_fees_lamports']),basis)-1 if full and basis>0 else None
    previous_peak=Fraction(int(state['numerator']),int(state['denominator'])) if state else Fraction(1)
    current_factor=ratio+1 if ratio is not None else None
    peak=max(previous_peak,current_factor) if current_factor is not None else previous_peak
    features=_features(frame,at,plan.max_observation_age_ms)
    creator_risk=(features is not None and any(_integer(features.get(k)) and features[k]>0 for k in ('dev_sales','relay_transfers')))
    emergency=journal.killed or (type(health) is dict and health.get('emergency_stop') is True)
    healthy=_healthy(health,at,plan.max_observation_age_ms)
    action,reasons,chosen=choose_frozen_position_action(emergency=emergency,
        creator_risk=creator_risk,ratio=ratio,
        trailing_drawdown_ratio=current_factor/peak if current_factor is not None and peak>0 else None,
        trailing_armed=peak>1,age_ms=at-plan.entry_at_ms,model=plan.master_model(),
        features=features,full=full,partial=partial,
        observations_complete=full is not None and healthy)
    pending=[]
    for row in journal.con.execute('SELECT * FROM orders WHERE state IN (%s)' % ','.join('?' for _ in ACTIVE),ACTIVE):
        order=json.loads(row['order_json'])
        if order['mint']==mint and order['pool']==pool:pending.append(row)
    blocked=bool(journal.killed or pending or not healthy or chosen is None)
    if pending:reasons.append('position_has_unreconciled_or_reserved_order')
    if journal.killed:reasons.append('persistent_kill_blocks_financial_submission')
    if not healthy:reasons.append('operational_health_unknown_or_stale')
    result.update(action=action,reasons=reasons,execution_blocked=blocked,
        conditional_full_net_lamports=full['conditional_net_lamports'] if full else None,
        conditional_position_net_lamports=full['conditional_total_position_net_lamports'] if full else None,
        peak_net_liquidation_factor=dict(numerator=str(peak.numerator),denominator=str(peak.denominator)))
    if action in ('EMERGENCY_EXIT','EXIT','TAKE_PROFIT'):
        result['input_quantity_atomic']=str(remaining)
        if full is None:result['reasons'].append('full_exact_exit_model_unavailable')
    if chosen is not None and action in ('EMERGENCY_EXIT','EXIT','TAKE_PROFIT','REDUCE'):
        result.update(input_quantity_atomic=chosen['quantity_atomic'],
            conditional_exit_gross_lamports=chosen['proceeds_lamports'],
            exit_fee_upper_lamports=chosen['extra_fees_lamports'],
            route_semantic_digest=chosen['route_semantic_digest'],liquidity_model_qualified=True)
    peak_record=[str(peak.numerator),str(peak.denominator),available,frame['source_slot']] if full else None
    encoded=canonical(result)
    with journal.atomic():
        journal.con.execute('INSERT INTO live_position_decisions VALUES(?,?,?,?,?)',(mint,pool,frame['id'],fingerprint,encoded))
        if peak_record is not None:
            journal.con.execute('INSERT OR REPLACE INTO live_position_peaks VALUES(?,?,?,?,?,?)',(mint,pool,*peak_record))
        journal._audit('live_position_decision',at,mint=mint,pool=pool,frame_id=frame['id'],
            frame_sha256=fingerprint,result_json=encoded,peak_record=peak_record)
    return result
