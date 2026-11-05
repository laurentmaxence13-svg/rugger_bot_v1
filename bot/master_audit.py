"""Durable shadow decisions in the existing PAPER database, never a bankroll.

The caller owns the existing ledger transaction. No schema initialization,
commit, rollback, capital change or execution is hidden in an event writer.
"""
import hashlib
import json
import sqlite3
import time


def _json(value):
    encoded=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(encoded.encode())>1048576:
        raise ValueError('Master event exceeds its bounded evidence size')
    return encoded


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def setup_master_schema(con):
    """Explicit startup only; keep every financial table and initial capital."""
    if con.in_transaction:
        raise ValueError('Initialize master audit outside an active ledger transaction')
    con.executescript('''
        CREATE TABLE IF NOT EXISTS paper_master_decisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_key TEXT NOT NULL UNIQUE, mint TEXT NOT NULL,
          decision_ms INTEGER NOT NULL, policy_sha256 TEXT NOT NULL,
          input_sha256 TEXT NOT NULL, decision_sha256 TEXT NOT NULL,
          frame_json TEXT NOT NULL, decision_json TEXT NOT NULL,
          reference_outcome_json TEXT,
          mode TEXT NOT NULL CHECK(mode='shadow'));
        CREATE INDEX IF NOT EXISTS idx_master_mint_time
          ON paper_master_decisions(mint,decision_ms,id);
        CREATE TABLE IF NOT EXISTS paper_master_comparisons (
          event_key TEXT PRIMARY KEY, decision_ms INTEGER NOT NULL,
          reference_sha256 TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL,
          reference_json TEXT NOT NULL, snapshot_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS paper_master_latencies (
          event_key TEXT NOT NULL, stage TEXT NOT NULL, elapsed_ns INTEGER NOT NULL,
          PRIMARY KEY(event_key,stage));
    ''')


def _exists(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE name='paper_master_decisions'").fetchone())


def shadow_attempt(con, callback):
    """Isolate optional audit failures inside the caller's ledger transaction.

    The caller must refuse new entries on an evaluation error, while continuing
    existing position protection. Cancellation and process interrupts propagate.
    """
    if not con.in_transaction:
        raise ValueError('Shadow audit requires the existing ledger transaction')
    con.execute('SAVEPOINT master_shadow_audit')
    try:
        value = callback()
    except Exception as error:
        con.execute('ROLLBACK TO master_shadow_audit')
        con.execute('RELEASE master_shadow_audit')
        return None, type(error).__name__
    except BaseException:
        con.execute('ROLLBACK TO master_shadow_audit')
        con.execute('RELEASE master_shadow_audit')
        raise
    con.execute('RELEASE master_shadow_audit')
    return value, None


def master_history(con,mint,*,as_of_ms,limit=32):
    if type(as_of_ms) is not int or type(limit) is not int or not 1<=limit<=64:
        raise ValueError('A bounded causal master history is required')
    rows=con.execute('''SELECT frame_json FROM paper_master_decisions
        WHERE mint=? AND decision_ms<=? ORDER BY decision_ms DESC,id DESC LIMIT ?''',
        (mint,as_of_ms,limit)).fetchall()
    return [json.loads(row[0]) for row in reversed(rows)]


def record_master_decision(con,frame,decision,*,inputs=None):
    """Idempotent immutable event; a reused identity with other facts is refused."""
    at=frame.get('available_at_ms');mint=frame.get('mint');frame_id=frame.get('id')
    policy=decision.get('policy_sha256')
    if (type(at) is not int or at<0 or type(mint) is not str or not mint
            or type(frame_id) is not str or not frame_id or type(policy) is not str
            or len(policy)!=64 or decision.get('promotion_allowed') is not False):
        raise ValueError('Explicit as-of shadow decision identity and policy required')
    key=_hash({'frame_id':frame_id,'mint':mint,'policy_sha256':policy})
    body=_json(frame);proposal=_json(decision);fingerprint=_hash({'frame':frame,'inputs':inputs})
    decision_hash=_hash(decision)
    previous=con.execute('SELECT input_sha256,decision_sha256 FROM paper_master_decisions WHERE event_key=?',
        (key,)).fetchone()
    if previous is not None:
        if previous!=(fingerprint,decision_hash):
            raise ValueError('Master event identity conflicts with retained evidence')
        return key
    written=con.execute('''INSERT INTO paper_master_decisions
        (event_key,mint,decision_ms,policy_sha256,input_sha256,decision_sha256,
         frame_json,decision_json,mode) VALUES(?,?,?,?,?,?,?,?,'shadow')''',
        (key,mint,at,policy,fingerprint,decision_hash,body,proposal))
    if written.rowcount!=1:
        raise ValueError('Master decision was not retained exactly once')
    return key


def complete_master_reference(con,key,outcome):
    """Link the existing engine's outcome, explicitly separate from the proposal."""
    if outcome.get('proposal_applied') is not False:
        raise ValueError('Shadow audit cannot report proposal execution')
    body=_json(outcome)
    row=con.execute('SELECT reference_outcome_json FROM paper_master_decisions WHERE event_key=?',(key,)).fetchone()
    if row is None:raise ValueError('Missing master decision event')
    if row[0] is not None:
        if row[0]!=body:raise ValueError('Reference outcome already retained with different facts')
        return
    written=con.execute('UPDATE paper_master_decisions SET reference_outcome_json=? WHERE event_key=? AND reference_outcome_json IS NULL',
        (body,key))
    if written.rowcount!=1:raise ValueError('Master reference outcome did not persist')


def _normalized_action(value):
    return 'BUY' if value=='ENTER' else value


def comparison_snapshot(frame,decision,reference):
    """Freeze both available intentions and twelve fields before any outcome.

    The reference is an intent reported by the existing engine, not proof of
    admission, execution or profitability. Missing fields remain explicit nulls.
    """
    at=frame.get('available_at_ms')
    observed=(reference.get('observed_at_ms',reference.get('available_at_ms'))
              if type(reference) is dict else None)
    valid_actions=('BUY','ENTER','WAIT','NO_TRADE','HOLD','REDUCE','TAKE_PROFIT',
                   'EXIT','EMERGENCY_EXIT','WAIT_FOR_DATA')
    if (type(at) is not int or type(observed) is not int or not 0<=observed<=at
            or decision.get('decision_at_ms',at)!=at
            or decision.get('frame_id',frame.get('id'))!=frame.get('id')
            or reference.get('action') not in valid_actions
            or reference.get('intent_only') is not True
            or reference.get('execution_verified',False) is not False
            or reference.get('promotion_allowed',False) is not False):
        raise ValueError('A causal conditional reference intent is required')
    # Validate JSON/finiteness and take independent copies of caller inputs.
    frame=json.loads(_json(frame));decision=json.loads(_json(decision))
    reference=json.loads(_json(reference))
    questions={q.get('number'):q.get('metrics',{}) for q in decision.get('questions',[])
               if type(q) is dict}
    ref_action=_normalized_action(reference['action'])
    master_action=_normalized_action(decision.get('action'))
    if master_action not in valid_actions:
        raise ValueError('Explicit conditional master action required')
    action_disagrees=ref_action!=master_action
    both_buy=ref_action==master_action=='BUY'
    ref_strategy=reference.get('selected_strategy')
    strategy_disagrees=(ref_strategy!=decision.get('selected_strategy')
        if both_buy and ref_strategy is not None and decision.get('selected_strategy') is not None else None)
    ref_size=reference.get('input_lamports');master_size=decision.get('input_lamports')
    size_disagrees=(str(ref_size)!=str(master_size)
        if both_buy and ref_size is not None and master_size is not None else None)
    reasons=[]
    if action_disagrees:reasons.append('different_conditional_action')
    if strategy_disagrees:reasons.append('different_admissible_strategy')
    if size_disagrees:reasons.append('different_exact_position_budget')
    if reasons:
        reasons.extend('master:'+str(reason) for reason in decision.get('reasons',[]))
        reasons.extend('reference:'+str(reason) for reason in reference.get('reasons',[]))
    context=frame.get('inventory_context',frame.get('buy_context'))
    fee=context.get('fees') if type(context) is dict else None
    fields=dict(
        available_observations=frame,
        token_score=dict(reference=reference.get('score'),master=questions.get(2,{}).get('score')),
        detected_risks=dict(reference=reference.get('risks'),master=questions.get(2,{}).get('risk_flags')),
        admissible_strategies=decision.get('alternatives'),
        selected_strategy=dict(reference=ref_strategy,master=decision.get('selected_strategy')),
        conditional_action=dict(reference=ref_action,master=master_action),
        contemplated_position=dict(reference_input_lamports=ref_size,master_input_lamports=master_size,
            reference_quantity_atomic=reference.get('quantity_atomic'),master_quantity_atomic=decision.get('quantity_atomic')),
        costs_known_and_unknown=dict(retained_fee_context=fee,reference=reference.get('costs'),
            master_size_assessments=decision.get('size_assessments'),missing_costs_are_not_zero=True),
        exit_conditions=dict(reference=reference.get('exit_conditions'),
            frozen_entry_plan=frame.get('entry_plan'),master=decision.get('position_plan')),
        reference_decision=reference,
        master_decision=decision,
        admissible_future_results=dict(status='PENDING',source='separate_later_outcome_record',
            execution_verified=False))
    return dict(schema='rugger-master-reference-snapshot-v1',decision_at_ms=at,
        fields=fields,field_count=12,action_disagreement=action_disagrees,
        strategy_disagreement=strategy_disagrees,size_disagreement=size_disagrees,
        disagreement=bool(action_disagrees or strategy_disagrees or size_disagrees),
        disagreement_reasons=reasons,intent_only=True,proposal_applied=False,
        promotion_allowed=False,scope='same_available_observations_before_future_outcomes')


def record_master_comparison(con,key,frame,decision,reference):
    """Write immutable paired intentions before the separately linked outcome."""
    snapshot=comparison_snapshot(frame,decision,reference)
    body=_json(snapshot);ref=_json(reference)
    fingerprint=_hash(snapshot);ref_hash=_hash(reference)
    previous=con.execute('SELECT snapshot_sha256 FROM paper_master_comparisons WHERE event_key=?',(key,)).fetchone()
    if previous is not None:
        if previous!=(fingerprint,):raise ValueError('Paired intentions conflict with retained evidence')
        return snapshot
    retained=con.execute('SELECT frame_json,decision_json,reference_outcome_json FROM paper_master_decisions WHERE event_key=?',(key,)).fetchone()
    if retained is None or retained[:2]!=(_json(frame),_json(decision)):
        raise ValueError('Paired intentions require the same retained master decision and frame')
    if retained[2] is not None:
        raise ValueError('Cannot first register paired intentions after their reference outcome')
    written=con.execute('''INSERT INTO paper_master_comparisons
        (event_key,decision_ms,reference_sha256,snapshot_sha256,reference_json,snapshot_json)
        VALUES(?,?,?,?,?,?)''',(key,frame['available_at_ms'],ref_hash,fingerprint,ref,body))
    if written.rowcount!=1:raise ValueError('Paired intentions were not retained exactly once')
    return snapshot


def record_master_latency(con,key,stage,elapsed_ns):
    """Retain the first measured local sample; a replay cannot rewrite it."""
    if (stage not in ('history_read_and_master_evaluation','decision_audit_write')
            or type(elapsed_ns) is not int or not 0<=elapsed_ns<2**63):
        raise ValueError('A bounded measured monotonic latency is required')
    if not con.execute('SELECT 1 FROM paper_master_decisions WHERE event_key=?',(key,)).fetchone():
        raise ValueError('Latency requires its retained decision')
    con.execute('INSERT INTO paper_master_latencies(event_key,stage,elapsed_ns) VALUES(?,?,?) '
        'ON CONFLICT(event_key,stage) DO NOTHING',(key,stage,elapsed_ns))
    if not con.execute('SELECT 1 FROM paper_master_latencies WHERE event_key=? AND stage=?',(key,stage)).fetchone():
        raise ValueError('Measured latency was not retained')


def _comparison_report(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_master_comparisons'").fetchone():
        return None
    rows=con.execute('SELECT snapshot_json,snapshot_sha256,reference_json,reference_sha256 '
        'FROM paper_master_comparisons ORDER BY decision_ms DESC,event_key LIMIT 1000').fetchall()
    if not rows:return None
    snapshots=[json.loads(row[0]) for row in rows]
    for stored,snapshot in zip(rows,snapshots):
        ref=json.loads(stored[2])
        if (_hash(snapshot)!=stored[1] or _hash(ref)!=stored[3]
                or type(snapshot.get('fields')) is not dict or len(snapshot['fields'])!=12
                or snapshot['fields'].get('reference_decision')!=ref):
            raise ValueError('Paired-decision evidence fingerprint mismatch')
    if any(type(row) is not dict or row.get('schema')!='rugger-master-reference-snapshot-v1'
            or type(row.get('disagreement')) is not bool for row in snapshots):
        raise ValueError('Unreadable paired-decision audit')
    total=con.execute('SELECT COUNT(*) FROM paper_master_comparisons').fetchone()[0]
    timings={}
    for stage in ('history_read_and_master_evaluation','decision_audit_write'):
        values=[row[0] for row in con.execute('SELECT elapsed_ns FROM paper_master_latencies WHERE stage=? '
            'ORDER BY rowid DESC LIMIT 1000',(stage,))]
        if any(type(v) is not int or v<0 for v in values):raise ValueError('Unreadable measured latency')
        values.sort()
        def quantile(numerator):
            return values[max(0,(len(values)*numerator+99)//100-1)]/1e6 if values else None
        timings[stage]=dict(samples=len(values),p50_ms=quantile(50),p95_ms=quantile(95),p99_ms=quantile(99),
            scope='first_measured_local_sample_per_event; last_1000_samples; excludes_network_and_execution_latency')
    return dict(paired_decisions=total,sample=len(rows),scope='last_1000_paired_decisions',
        disagreements=sum(row['disagreement'] for row in snapshots),
        action_disagreements=sum(row['action_disagreement'] for row in snapshots),
        strategy_disagreements=sum(row['strategy_disagreement'] is True for row in snapshots),
        size_disagreements=sum(row['size_disagreement'] is True for row in snapshots),
        outcome_quality='not_inferred_from_disagreement',economic_winner=None,
        evaluation_latency=timings)


def master_report(con):
    """Read-only aggregates; missing schema adds no fields to older reports."""
    if not _exists(con):return None
    try:
        return _master_report(con)
    except (sqlite3.Error,ValueError,TypeError,KeyError,AttributeError):
        return dict(schema='rugger-master-shadow-report-v1',mode='shadow',
            status='unavailable',decisions=None,pending_reference_outcomes=None,
            actions=None,proposed_strategies=None,proposal_applied=False,
            promotion_allowed=False,economic_profitability_verified=False,
            error='retained_shadow_audit_unreadable',
            scope='optional_shadow_audit; financial_ledger_not_repaired_or_reset')


def _master_report(con):
    total,pending=con.execute('SELECT COUNT(*),SUM(reference_outcome_json IS NULL) FROM paper_master_decisions').fetchone()
    rows=con.execute('SELECT decision_json,reference_outcome_json FROM paper_master_decisions ORDER BY id DESC LIMIT 1000').fetchall()
    actions={};strategies={}
    for proposal,outcome in rows:
        decision=json.loads(proposal)
        if type(decision) is not dict or decision.get('promotion_allowed') is not False:
            raise ValueError('Unreadable shadow policy record')
        action=decision.get('action')
        if action not in ('ENTER','WAIT','NO_TRADE','HOLD','REDUCE','TAKE_PROFIT',
                'EXIT','EMERGENCY_EXIT','WAIT_FOR_DATA'):
            raise ValueError('Unreadable shadow action')
        if outcome is not None:
            reference=json.loads(outcome)
            if type(reference) is not dict or reference.get('proposal_applied') is not False:
                raise ValueError('Unreadable reference-engine outcome')
        actions[action]=actions.get(action,0)+1
        strategy=decision.get('selected_strategy')
        if strategy is not None and strategy not in ('early_sniping','confirmed_momentum','adaptive_hybrid'):
            raise ValueError('Unreadable shadow strategy')
        if strategy is not None:strategies[strategy]=strategies.get(strategy,0)+1
    result=dict(schema='rugger-master-shadow-report-v1',mode='shadow',status='available',decisions=total,
        actions=actions,proposed_strategies=strategies,pending_reference_outcomes=pending or 0,
        action_counts_scope='last_1000_decisions',action_counts_sample=len(rows),
        proposal_applied=False,promotion_allowed=False,economic_profitability_verified=False,
        strict_economic_cycles=0,scope='shadow_proposals_and_existing_reference_engine_outcomes')
    comparison=_comparison_report(con)
    if comparison is not None:result['master_reference_comparison']=comparison
    return result


class MasterShadow:
    """Bounded evaluator attached to collect_once, without execution authority."""
    def __init__(self,orchestrator=None):
        if orchestrator is None:
            from bot.master_decision import MasterDecisionOrchestrator
            orchestrator=MasterDecisionOrchestrator()
        self.orchestrator=orchestrator

    def evaluate(self,con,frame,*,inventory=None,health=None,capital=None,reference=None,measure_latency=False):
        if type(measure_latency) is not bool:raise ValueError('Explicit latency measurement flag required')
        start=time.perf_counter_ns() if measure_latency else None
        # A retry must see the same strict prefix, never its retained proposal.
        history=master_history(con,frame['mint'],as_of_ms=frame['available_at_ms']-1)
        decision=self.orchestrator.evaluate(frame,history,inventory=inventory,health=health,capital=capital)
        evaluated=time.perf_counter_ns() if measure_latency else None
        key=record_master_decision(con,frame,decision,inputs=dict(inventory=inventory,health=health,capital=capital))
        if reference is not None:record_master_comparison(con,key,frame,decision,reference)
        written=time.perf_counter_ns() if measure_latency else None
        if measure_latency:
            record_master_latency(con,key,'history_read_and_master_evaluation',evaluated-start)
            record_master_latency(con,key,'decision_audit_write',written-evaluated)
        return key,decision


def paper_context(con,*,mint,creator,pool,signal_time,decision_ms,features,
                  inventory_context,health,financial_allowed):
    """Read already available engine inputs; add no source call or invented fact."""
    from dataclasses import asdict,is_dataclass
    from bot.analyser.token_inventory import inventory_state,_lamports
    from bot.analyser.paper_trader import _paper_free_capital
    context=dict(inventory_context or {})
    if is_dataclass(context.get('fees')):context['fees']=asdict(context['fees'])
    observation=context.get('sell_observation') or context.get('buy_observation') or {}
    bank=context.get('bank_state')
    slot=bank.get('source_slot') if type(bank) is dict else observation.get('source_slot')
    slot_available=bank.get('available_at_ms') if type(bank) is dict else observation.get('available_at_ms')
    frame=dict(mint=mint,creator=creator,pool=pool,detected_at_ms=int(signal_time)*1000,
        available_at_ms=decision_ms,features_available_at_ms=decision_ms,
        features=asdict(features),source_slot=slot,slot_available_at_ms=slot_available,
        independent_buyers=None,inventory_context=context,data_kind='market_observation',
        observation_scope='existing_PAPER_inputs_and_local_availability_not_provider_clock')
    if type(bank) is dict:frame['bank_state']=bank
    frame['id']=_hash(dict(mint=mint,pool=pool,decision_ms=decision_ms,
        observation_id=observation.get('id'),features=frame['features']))
    inventory=inventory_state(con,mint)
    cursor=con.execute('SELECT * FROM paper_trades WHERE mint=?',(mint,));row=cursor.fetchone()
    if row is not None:
        trade=dict(zip((column[0] for column in cursor.description),row))
        if trade['status']=='open':
            frame['position_reference']={key:trade.get(key) for key in (
                'entry_time','entry_price','peak_price','last_price','status','cost_bps')}
            entry=con.execute('''SELECT tp_pct,sl_pct,trailing_stop_pct,hold_seconds
                FROM paper_decisions WHERE mint=? AND decision_time<=?
                ORDER BY decision_time DESC,id DESC LIMIT 1''',(mint,trade['entry_time'])).fetchone()
            if entry is not None:
                frame['entry_plan']=dict(zip(('tp_pct','sl_pct','trailing_stop_pct','hold_seconds'),entry))
            if inventory is None:
                inventory=dict(mint=mint,remaining_atomic=None,legacy_inventory_unknown=True)
    capital=dict(available_cash_lamports=None,open_positions=None,entries_today=None,
        daily_loss_limit_reached=None,financial_entry_allowed=bool(financial_allowed),observed_at_ms=decision_ms)
    try:
        _capital,free=_paper_free_capital(con)
        capital['available_cash_lamports']=_lamports(free)
        capital['open_positions']=con.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open'").fetchone()[0]
        day=decision_ms//1000;day-=day%86400
        capital['entries_today']=con.execute('SELECT COUNT(*) FROM paper_trades WHERE entry_time>=? AND entry_time<=?',
            (day,decision_ms//1000)).fetchone()[0]
    except (ValueError,TypeError):
        pass  # Never turn unproven available cash into a numeric zero.
    return frame,inventory,health,capital
