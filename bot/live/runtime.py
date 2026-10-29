"""Causal Master-to-execution bridge. Imports/startup never arm or trade.

The normal scanner supplies observations; it cannot supply financial authority.
Decisions are durably frozen before awaiting route acquisition or simulation.
The native execution journal remains separate from the existing PAPER book.
"""
import hashlib
import json
import time
from fractions import Fraction

from bot.master_decision import MasterDecisionOrchestrator
from bot.p3.certification import PROGRAM
from .journal import ACTIVE, canonical
from .route import build_launchlab_order
from .route_dispatch import validate_execution_order,execution_program,route_kind
from .safety import Mode
from .positions import FrozenEntryPlan,persist_entry_plan,evaluate_live_position


def _hash(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def _validate_source_availability(value,source_at):
    """A delayed consumer cannot add future embedded facts to a source frame."""
    if type(value) is dict:
        for key,item in value.items():
            if key=='available_at_ms' or key.endswith('_available_at_ms') or key=='observed_at_ms':
                if item is not None and (type(item) is not int or not 0<=item<=source_at):
                    raise ValueError('future_or_invalid_source_availability')
            _validate_source_availability(item,source_at)
    elif type(value) is list:
        for item in value:_validate_source_availability(item,source_at)


def freeze_entry_thresholds(proposal,decision_id,*,max_price_impact_bps):
    """Freeze the existing Master's actual exit plan, without tuning thresholds."""
    model=proposal.get('decision_evidence',{}).get('reference_exit_conditions')
    if proposal.get('action')!='ENTER' or type(model) is not dict:
        raise ValueError('Master_entry_with_explicit_exit_conditions_required')
    values={}
    for key in ('tp_pct','sl_pct','trailing_stop_pct'):
        if key not in model:raise ValueError('incomplete_frozen_Master_exit_conditions')
        value=model[key]
        if value is None:value=0  # The existing model explicitly disables this trigger.
        if type(value) not in (int,float,str):raise ValueError('invalid_frozen_Master_threshold')
        values[key]=str(value)
        try:
            if Fraction(values[key])<0:raise ValueError()
        except (ValueError,ZeroDivisionError):
            raise ValueError('invalid_frozen_Master_threshold') from None
    return FrozenEntryPlan(entry_decision_id=decision_id,
        entry_at_ms=proposal['decision_at_ms'],hold_seconds=model.get('hold_seconds'),
        net_take_profit_lamports=0,max_observation_age_ms=5000,
        max_price_impact_bps=max_price_impact_bps,**values)


class JournalDecisionContext:
    """Read actual supervision callbacks and the authorized wallet's balance.

    Missing authority or scanner observations remain unknown. A launch timestamp,
    price refresh or this function's invocation cannot create a heartbeat.
    """
    def __init__(self,engine,scanner_health,*,clock_ms=None):
        self.engine,self.scanner_health=engine,scanner_health
        self.clock_ms=clock_ms or (lambda:time.time_ns()//1_000_000)

    async def __call__(self):
        now=self.clock_ms();observed=self.scanner_health.operational_observations()
        scanner=observed.get('scanner',{})
        healthy=(self.scanner_health.services_fresh(max_age_ms=5000)
            and scanner.get('state')=='ready')
        health=dict(allow_new_entries=healthy,observed_at_ms=scanner.get('observed_at_ms'),
            blocking_reasons=[] if healthy else ['actual_scanner_or_services_unavailable'])
        envelope=self.engine.envelope
        if envelope is None:return dict(health=health,capital=None)
        balance=await self.engine.rpc.get_balance(envelope.wallet)
        now=self.clock_ms()
        risk=self.engine.journal.risk_snapshot(at=now,wallet_balance_lamports=balance)
        start=now-now%86_400_000
        entries=self.engine.journal.con.execute(
            "SELECT COUNT(*) FROM orders WHERE created_at_ms>=? AND created_at_ms<=? AND json_extract(order_json,'$.side')='BUY'",
            (start,now)).fetchone()[0]
        capital=dict(available_cash_lamports=max(0,balance-risk.reserved_lamports),
            open_positions=risk.open_positions,entries_today=entries,
            daily_loss_limit_reached=risk.realized_daily_loss_lamports+ risk.pending_loss_lamports>=envelope.max_daily_loss_lamports,
            financial_entry_allowed=not(risk.kill_switch or risk.unresolved_orders),
            observed_at_ms=now,scope='authorized_native_execution_journal_not_PAPER')
        return dict(health=health,capital=capital)


class LiveRuntime:
    def __init__(self,*,engine,decision_context_provider,route_request_provider,
                 approved_policy_sha256=None,clock_ms=None):
        self.engine=engine
        self.context_provider=decision_context_provider
        self.route_request_provider=route_request_provider
        self.core=MasterDecisionOrchestrator()
        self.approved_policy_sha256=approved_policy_sha256
        self.clock_ms=clock_ms or (lambda:time.time_ns()//1_000_000)

    def _retained(self,decision_id):
        rows=self.engine.journal.con.execute("SELECT event_json FROM audit WHERE json_extract(event_json,'$.kind')='master_decision' AND json_extract(event_json,'$.decision_id')=?",(decision_id,))
        values=[json.loads(r[0]) for r in rows]
        if len(values)>1:raise ValueError('duplicate_immutable_master_decision')
        return values[0] if values else None

    def _freeze(self,decision_id,frame,history,proposal,source_hash):
        payload=dict(frame=frame,history_sha256=_hash(history),proposal=proposal,
            source_frame_sha256=source_hash,policy_sha256=self.core.policy_sha256)
        if len(canonical(payload).encode())>1_048_576:
            raise ValueError('bounded_master_decision_required')
        with self.engine.journal.atomic():
            old=self._retained(decision_id)
            if old:
                if old['payload']!=payload:raise ValueError('master_decision_identity_reused')
            else:self.engine.journal._audit('master_decision',self.clock_ms(),
                decision_id=decision_id,payload=payload)

    async def observe(self,frame,history=()):
        if (type(frame) is not dict or type(frame.get('id')) is not str or not frame['id']
                or type(frame.get('mint')) is not str or type(history) not in (list,tuple)
                or len(history)>32):
            raise ValueError('bounded_identified_causal_frame_required')
        # JSON serialization rejects nonfinite values and mutable opaque objects.
        frame=json.loads(canonical(frame));history=json.loads(canonical(history))
        source_hash=_hash(frame)
        decision_id='master-live-'+_hash(dict(frame_id=frame['id'],mint=frame['mint'],
                                              policy=self.core.policy_sha256))
        retained=self._retained(decision_id)
        if retained:
            if retained['payload']['source_frame_sha256']!=source_hash:
                raise ValueError('master_source_frame_identity_reused')
            return dict(decision_id=decision_id,proposal=retained['payload']['proposal'],
                execution=self.engine.result(decision_id),duplicate=True)
        available=frame.get('available_at_ms')
        if type(available) is not int or not 0<=self.clock_ms()-available<=5000:
            raise ValueError('frame_unavailable_or_stale_at_actual_decision')
        _validate_source_availability(frame,available)
        context=await self.context_provider()
        now=self.clock_ms();available=frame.get('available_at_ms')
        if type(available) is not int or not 0<=now-available<=5000:
            raise ValueError('frame_unavailable_or_stale_at_actual_decision')
        if any(type(h) is not dict or type(h.get('available_at_ms')) is not int
               or h['available_at_ms']>=available for h in history):
            raise ValueError('future_or_nonprior_master_history')
        frame['source_frame_available_at_ms']=available
        frame['available_at_ms']=now  # actual decision clock; source clocks stay intact
        proposal=self.core.evaluate(frame,history,health=context.get('health'),capital=context.get('capital'))
        self._freeze(decision_id,frame,history,proposal,source_hash)
        result=dict(decision_id=decision_id,proposal=proposal,execution=None,duplicate=False)
        if proposal['action']!='ENTER' or self.engine.mode in (Mode.RESEARCH,Mode.SHADOW):return result
        if self.engine.journal.killed:raise ValueError('persistent_kill_switch_active')
        if (self.engine.mode is Mode.LIVE_ENABLED
                and self.approved_policy_sha256!=self.core.policy_sha256):
            raise ValueError('explicit_unchanged_strategy_policy_approval_required')
        if self.engine.mode is Mode.LIVE_ENABLED and frame.get('data_kind')!='market_observation':
            raise ValueError('synthetic_frames_cannot_authorize_live_route')
        request=await self.route_request_provider(decision_id,proposal,frame)
        if (type(request) is not dict or request.get('decision_id')!=decision_id
                or request.get('side')!='BUY' or request.get('mint')!=frame.get('mint')
                or request.get('pool_address')!=frame.get('pool')
                or request.get('amount_in')!=int(proposal['input_lamports'])):
            raise ValueError('route_differs_from_frozen_Master_intent')
        order=build_launchlab_order(**request)
        plan=freeze_entry_thresholds(proposal,decision_id,
            max_price_impact_bps=order.max_price_impact_bps)
        persist_entry_plan(self.engine.journal,order.mint,order.pool,plan,at_ms=self.clock_ms())
        result['execution']=await self.engine.execute(decision_id,order)
        return result

    async def observe_position(self,frame):
        """Drive the same native engine from frozen Master position triggers."""
        if type(frame) is not dict:raise ValueError('explicit_native_position_frame_required')
        available=frame.get('available_at_ms')
        if type(available) is not int or not 0<=self.clock_ms()-available<=5000:
            raise ValueError('position_frame_unavailable_or_stale_at_actual_decision')
        _validate_source_availability(frame,available)
        context=await self.context_provider();now=self.clock_ms()
        source_health=context.get('health')
        health=(dict(source_health,allow_position_management=
            source_health.get('allow_new_entries') is True) if type(source_health) is dict else None)
        proposal=evaluate_live_position(self.engine.journal,frame.get('mint'),frame.get('pool'),
            frame,health=health,at=now)
        result=dict(proposal=proposal,execution=None)
        if (proposal['execution_blocked'] or proposal['action'] not in
                ('REDUCE','EXIT','TAKE_PROFIT','EMERGENCY_EXIT')
                or self.engine.mode in (Mode.RESEARCH,Mode.SHADOW)):
            return result
        if (self.engine.mode is Mode.LIVE_ENABLED
                and self.approved_policy_sha256!=self.core.policy_sha256):
            raise ValueError('explicit_unchanged_strategy_policy_approval_required')
        orders=[frame.get('prepared_full_exit'),*frame.get('prepared_partial_exits',())]
        matches=[o for o in orders if o is not None
            and o.semantic_digest==proposal['route_semantic_digest']]
        if len(matches)!=1:raise ValueError('unique_exact_position_route_required')
        order=validate_execution_order(matches[0])
        if str(order.input_amount)!=proposal['input_quantity_atomic']:
            raise ValueError('position_quantity_differs_from_frozen_proposal')
        if proposal['inventory_pool']!=frame['pool'] or proposal['execution_pool']!=order.pool:
            raise ValueError('position_execution_or_inventory_identity_changed')
        if route_kind(order)=='CPMM':
            binding=self.engine.journal.bound_migration(order.mint,order.pool,
                at_ms=self.clock_ms(),source_slot=order.source_slot,wallet=order.user)
            if (binding['inventory_pool']!=frame['pool']
                    or binding['binding_sha256']!=proposal['migration_binding_sha256']):
                raise ValueError('position_migration_binding_changed_after_decision')
        decision_id=json.loads(order.rebuild_request_json)['decision_id']
        result['execution']=await self.engine.execute(decision_id,order)
        result.update(inventory_pool=frame['pool'],execution_pool=order.pool,
            execution_program=execution_program(order),route_kind=route_kind(order))
        return result

    async def recover_pending(self):
        rows=list(self.engine.journal.con.execute('SELECT decision_id FROM orders WHERE state IN (%s)' %
            ','.join('?' for _ in ACTIVE),ACTIVE))
        return [await self.engine.recover(row[0]) for row in rows]

    async def run(self,frames):
        """Explicit scanner consumer; returns on input end, failure or kill latch."""
        await self.recover_pending()
        histories={}
        async for frame in frames:
            if self.engine.journal.killed:break
            if frame.get('kind')=='position':
                try:yield await self.observe_position(frame)
                except BaseException:
                    self.engine.journal.kill('native_position_runtime_interrupted_or_failed',self.clock_ms())
                    raise
                continue
            history=histories.setdefault(frame.get('mint'),[])
            try:
                yield await self.observe(frame,history[-32:])
            except BaseException:
                self.engine.journal.kill('master_runtime_interrupted_or_failed',self.clock_ms())
                raise
            history.append(json.loads(canonical(frame)))
