"""Durable shadow decisions in the existing PAPER database, never a bankroll.

The caller owns the existing ledger transaction. No schema initialization,
commit, rollback, capital change or execution is hidden in an event writer.
"""
import hashlib
import json


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


def master_report(con):
    """Read-only aggregates; missing schema adds no fields to older reports."""
    if not _exists(con):return None
    total,pending=con.execute('SELECT COUNT(*),SUM(reference_outcome_json IS NULL) FROM paper_master_decisions').fetchone()
    rows=con.execute('SELECT decision_json,reference_outcome_json FROM paper_master_decisions ORDER BY id DESC LIMIT 1000').fetchall()
    actions={};strategies={}
    for proposal,outcome in rows:
        decision=json.loads(proposal);action=decision.get('action','UNKNOWN')
        actions[action]=actions.get(action,0)+1
        strategy=decision.get('selected_strategy')
        if strategy is not None:strategies[strategy]=strategies.get(strategy,0)+1
    return dict(schema='rugger-master-shadow-report-v1',mode='shadow',decisions=total,
        actions=actions,proposed_strategies=strategies,pending_reference_outcomes=pending or 0,
        action_counts_scope='last_1000_decisions',action_counts_sample=len(rows),
        proposal_applied=False,promotion_allowed=False,economic_profitability_verified=False,
        strict_economic_cycles=0,scope='shadow_proposals_and_existing_reference_engine_outcomes')


class MasterShadow:
    """Bounded evaluator attached to collect_once, without execution authority."""
    def __init__(self,orchestrator=None):
        if orchestrator is None:
            from bot.master_decision import MasterDecisionOrchestrator
            orchestrator=MasterDecisionOrchestrator()
        self.orchestrator=orchestrator

    def evaluate(self,con,frame,*,inventory=None,health=None,capital=None):
        history=master_history(con,frame['mint'],as_of_ms=frame['available_at_ms'])
        decision=self.orchestrator.evaluate(frame,history,inventory=inventory,health=health,capital=capital)
        key=record_master_decision(con,frame,decision,inputs=dict(inventory=inventory,health=health,capital=capital))
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
