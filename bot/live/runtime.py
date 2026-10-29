"""Causal Master-to-execution bridge. Imports/startup never arm or trade.

The normal scanner supplies observations; it cannot supply financial authority.
Decisions are durably frozen before awaiting route acquisition or simulation.
The native execution journal remains separate from the existing PAPER book.
"""
import hashlib
import json
import time

from bot.master_decision import MasterDecisionOrchestrator
from bot.p3.certification import PROGRAM
from .journal import ACTIVE, canonical
from .route import build_launchlab_order
from .safety import Mode


def _hash(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


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
        result['execution']=await self.engine.execute(decision_id,order)
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
            history=histories.setdefault(frame.get('mint'),[])
            try:
                yield await self.observe(frame,history[-32:])
            except BaseException:
                self.engine.journal.kill('master_runtime_interrupted_or_failed',self.clock_ms())
                raise
            history.append(json.loads(canonical(frame)))
