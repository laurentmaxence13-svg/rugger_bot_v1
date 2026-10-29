"""Paired offline Master/reference replay through the existing PAPER ledger.

Each arm owns an isolated simulated book using the same native accountant.
Decisions are frozen before replaying their outcomes. No active book is opened.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

from bot import p4_experiment as p4


def make_plan(*,registered_at_ms,development_end_ms,holdout_end_ms,
              exit_horizon_ms=3600000,sensitivity=False):
    values=(registered_at_ms,development_end_ms,holdout_end_ms)
    if any(type(x) is not int or x<=0 for x in values) or not values[0]<values[1]<values[2]:
        raise ValueError('Explicit ordered registration and partition clocks required')
    if type(exit_horizon_ms) is not int or not 30000<=exit_horizon_ms<=3600000 or type(sensitivity) is not bool:
        raise ValueError('Bounded registered horizon and sensitivity flag required')
    from bot.master_decision import MasterDecisionOrchestrator
    return dict(schema='rugger-master-reference-plan-v1',registered_at_ms=registered_at_ms,
        development_end_ms=development_end_ms,holdout_end_ms=holdout_end_ms,
        exit_horizon_ms=exit_horizon_ms,sensitivity=sensitivity,
        fee_multipliers=[1,2] if sensitivity else [1],
        decision_delays_ms=[0,250] if sensitivity else [0],
        maximum_frames=1000,reference='current_final_decision_engine_and_native_ledger',
        master_policy_sha256=MasterDecisionOrchestrator().policy_sha256,
        base_policy_sha256=p4._hash(p4.POLICY),initial_capital_lamports='10000000000',
        reference_position_pct=10.0,
        operational_admission='same_retained_health_for_both_arms',
        selection='NONE; paired descriptive comparison, no promotion',
        market_qualification='indicative_quote_replay_is_not_observed_execution')


def _health(frame,at):
    value=deepcopy(frame.get('health'))
    if type(value) is not dict:return None,False
    clock=value.get('observed_at_ms')
    ready=(value.get('allow_new_entries') is True and type(clock) is int
        and 0<=at-clock<=5000)
    return value,ready


def _capital(con,at,api):
    from bot.analyser.paper_trader import _paper_free_capital,entry_allowed
    allowed=entry_allowed(con,at//1000,max_open=p4.POLICY['max_open'],
        max_entries_day=p4.POLICY['max_entries_day'],max_daily_loss_pct=p4.POLICY['max_daily_loss_pct'])
    capital=dict(available_cash_lamports=None,open_positions=None,entries_today=None,
        daily_loss_limit_reached=False if allowed else None,financial_entry_allowed=allowed,
        observed_at_ms=at,scope='this_isolated_replay_book_not_active_wallet')
    try:
        _,free=_paper_free_capital(con)
        capital['available_cash_lamports']=api['_lamports'](free)
        capital['open_positions']=con.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open'").fetchone()[0]
        day=at//1000;day-=day%86400
        capital['entries_today']=con.execute('SELECT COUNT(*) FROM paper_trades WHERE entry_time>=? AND entry_time<=?',(day,at//1000)).fetchone()[0]
    except (ValueError,TypeError):pass
    return capital


def _buy_context(frame,budget):
    sizes=frame.get('size_contexts',{})
    context=sizes.get(str(budget)) if type(sizes) is dict else None
    fallback=frame.get('buy_context')
    if context is None and type(fallback) is dict:
        event=fallback.get('buy_observation',{})
        if event.get('payload',{}).get('input_amount_atomic')==str(budget):context=fallback
    if type(context) is not dict:return None
    context=deepcopy(context)
    event=context.get('buy_observation',{})
    if event.get('payload',{}).get('input_amount_atomic')!=str(budget):return None
    common=frame.get('inventory_context') or fallback or {}
    for name in ('fees','token_decimals'):
        if name not in context and name in common:context[name]=deepcopy(common[name])
    return context


def _sell_contexts(frame,state):
    buy_id=json.loads(state['entry_observation_json']).get('id')
    values=list(frame.get('sell_contexts',[]))
    if type(frame.get('inventory_context')) is dict:values.append(frame['inventory_context'])
    result=[]
    for value in values:
        if type(value) is not dict:continue
        if value.get('inventory_buy_observation_id') not in (None,buy_id):continue
        quote=value.get('sell_observation')
        if type(quote) is not dict or quote.get('mint')!=frame['mint']:continue
        q=value.get('requested_quantity_atomic')
        if type(q) is not str or not q.isdecimal() or not 0<int(q)<=int(state['remaining_atomic']):continue
        item=deepcopy(value);item['inventory_version']=state['version']
        result.append(item)
    if len(result)>8:raise ValueError('At most eight retained exact exit contexts per decision')
    return result


def reference_position_intent(con,mint,at,price,model,*,forced=None):
    """Describe the current reference's pre-settlement rules, including floats."""
    from bot.analyser.paper_trader import model_risk
    row=con.execute('SELECT entry_time,entry_price,status,peak_price FROM paper_trades WHERE mint=?',(mint,)).fetchone()
    if row is None:return None,None
    if row[2]!='open':return 'HOLD','reference_position_already_closed'
    if forced:return 'EMERGENCY_EXIT',forced
    if price is None:return 'WAIT_FOR_DATA','reference_current_price_unavailable'
    entry_time,entry_price,_,previous_peak=row
    hold,_cost,tp,sl,trailing=model_risk(model)
    gross=price/entry_price-1;peak=max(previous_peak or entry_price,price)
    if tp is not None and gross>=tp/100:return 'TAKE_PROFIT','TP'
    if sl is not None and gross<=-sl/100:return 'EXIT','SL'
    if trailing is not None and peak>entry_price and price<=peak*(1-trailing/100):return 'EXIT','TRAILING_STOP'
    if at//1000>=entry_time+hold:return 'EXIT','TIMEOUT'
    return 'HOLD','reference_position_rules_not_triggered'


def _scenario_frame(frame,multiplier):
    value=deepcopy(frame)
    for key in ('buy_context','inventory_context'):
        if type(value.get(key)) is dict:value[key]=p4._scaled_context(value[key],multiplier)
    value['sell_contexts']=[p4._scaled_context(c,multiplier) for c in value.get('sell_contexts',[])]
    if type(value.get('size_contexts')) is dict:
        value['size_contexts']={k:p4._scaled_context(c,multiplier) for k,c in value['size_contexts'].items()}
    value['scenario']=dict(fee_multiplier=multiplier,quote_amounts_scaled=False,
        original_frame_sha256=p4._hash(frame),costs_are_hypothetical_stress=multiplier!=1)
    return value


class _Adapter:
    def __init__(self,arm,kind,reference=None):
        self.arm=arm;self.kind=kind;self.reference=reference or {};self.snapshots={};self.events={}

    def setup(self,con,api):
        from bot.master_audit import setup_master_schema
        setup_master_schema(con)
        from bot.master_decision import MasterDecisionOrchestrator
        self.core=MasterDecisionOrchestrator()

    def evaluate(self,con,frame,history,at,api,state,frozen):
        from bot.master_audit import record_master_decision,record_master_comparison
        f,feature_reason=p4._features(frame,api,at)
        base=api['decide'](f) if f is not None else None
        health,healthy=_health(frame,at);capital=_capital(con,at,api)
        current=deepcopy(frame);current['data_kind']=self.kind
        current['available_at_ms']=at
        current['health']=deepcopy(health);current['capital_snapshot']=deepcopy(capital)
        # Availability is not retimed: latency can make the retained facts stale.
        contexts=[] if state is None else _sell_contexts(frame,state)
        if state is not None:
            current['sell_contexts']=contexts
            current.pop('inventory_context',None)
            current['entry_plan']=deepcopy(frozen or {})
            row=con.execute('SELECT entry_price,peak_price,last_price,entry_time FROM paper_trades WHERE mint=?',(frame['mint'],)).fetchone()
            current['position_reference']=dict(zip(('entry_price','peak_price','last_price','entry_time'),row))
        model=base.to_paper_model() if base else frozen
        if self.arm=='reference':
            action=('BUY' if base and base.enter and healthy and capital['financial_entry_allowed']
                else 'NO_TRADE' if base and not base.enter else 'WAIT')
            reason=feature_reason or ('current_scorer_and_admission' if action=='BUY' else 'current_risk_or_admission_refusal')
            force=None
            if state is not None:
                if base and 'vente_developpeur' in base.risk_flags:force='DEV_SALE_RISK'
                elif base and 'transfert_relais' in base.risk_flags:force='RELAY_RISK'
                action,reason=reference_position_intent(con,frame['mint'],at,f.price_usd if f else None,model,forced=force)
            budget=p4.POLICY['position_lamports']
            if state is None and capital['available_cash_lamports'] is not None:
                budget=min(capital['available_cash_lamports'],
                    api['_lamports'](api['_paper_reconciled_capital'](con)*10.0/100))
            context=(_buy_context(frame,budget) if state is None else
                max(contexts,key=lambda item:int(item['requested_quantity_atomic']),default=None))
            snapshot=dict(action=action,selected_strategy='reference_current',score=base.score if base else None,
                risks=list(base.risk_flags) if base else None,reasons=[reason],input_lamports=str(budget) if action=='BUY' else None,
                quantity_atomic=(context.get('buy_observation',{}).get('payload',{}).get('output_amount_atomic')
                    if context and state is None else state['remaining_atomic'] if state else None),
                exit_conditions=model,costs=context.get('fees') if context else None,
                observed_at_ms=at,intent_only=True,execution_verified=False,promotion_allowed=False)
            enter=action=='BUY'
        else:
            proposal=self.core.evaluate(current,history[-32:],inventory=state,health=health,capital=capital)
            action=proposal['action'];snapshot=deepcopy(proposal)
            snapshot['intent_only']=True;snapshot['observed_at_ms']=at
            budget=int(proposal['input_lamports']) if proposal.get('input_lamports') else p4.POLICY['position_lamports']
            if state is None:context=_buy_context(frame,budget)
            else:
                plan=proposal.get('position_plan') or {}
                quote_id=plan.get('quote_id')
                context=next((item for item in contexts if item['sell_observation'].get('id')==quote_id),None)
                model=frozen
            force='MASTER_'+action if action in ('REDUCE','TAKE_PROFIT','EXIT','EMERGENCY_EXIT') else None
            enter=action=='ENTER'
            retained=deepcopy(current)
            # The table's identity is policy+frame, with all as-of inputs fingerprinted.
            key=record_master_decision(con,retained,proposal,inputs=dict(inventory=state,health=health,capital=capital))
            reference=self.reference.get(frame['id'])
            if reference is not None:record_master_comparison(con,key,retained,proposal,reference)
            self.events[frame['id']]=key
            reason=';'.join(proposal['reasons'])
        snapshot.update(frame_id=frame['id'],decision_at_ms=at,available_source_frame_sha256=p4._hash(frame),
            admission_known=healthy,financial_entry_allowed=capital['financial_entry_allowed'],
            replay_scope='isolated_conditional_PAPER_not_active_book')
        self.snapshots[frame['id']]=deepcopy(snapshot)
        return dict(decision=dict(enter=enter,reason=reason,model=model,score=base.score if base else None),
            inventory_context=context,force_exit_reason=force,position_lamports=budget,snapshot=snapshot)

    def after_step(self,con,frame,at,api,message):
        from bot.master_audit import complete_master_reference
        key=self.events.get(frame['id'])
        if key is not None:
            complete_master_reference(con,key,dict(proposal_applied=False,
                proposal_applied_to_active_book=False,isolated_conditional_paper_replay=True,
                arm='master',outcome_role='isolated_master_replay',
                replay_result=message,observed_at_ms=at,execution_verified=False))

    def report(self,con):
        from bot.master_audit import master_report
        return master_report(con)


def _position_result(run,mint):
    item=next((p for p in run['positions'] if p['mint']==mint),None)
    if item is None:return dict(entered=False,remaining_atomic='0',conditional_net_lamports='0',
        basis='no_entry_cashflow_not_a_token_outcome')
    complete=item['remaining_atomic']=='0' and item['entry_cost_known']
    return dict(entered=True,remaining_atomic=item['remaining_atomic'],
        conditional_net_lamports=item['realized_pnl_lamports'] if complete else None,
        basis='full_native_quote_replay' if complete else 'unliquidated_or_unknown_costs')


def evaluate_comparison(corpus,plan):
    """Replay common observations; never use outcome deltas to choose a policy."""
    keys=('registered_at_ms','development_end_ms','holdout_end_ms','exit_horizon_ms','sensitivity')
    if type(plan) is not dict or plan!=make_plan(**{k:plan.get(k) for k in keys}):
        raise ValueError('Exact registered comparison design required')
    if type(corpus) is not dict or type(corpus.get('frames')) is not list or len(corpus['frames'])>plan['maximum_frames']:
        raise ValueError('Explicit bounded corpus required')
    raw_assignments=p4._validate(corpus,{k:plan[k] for k in ('registered_at_ms','development_end_ms')}|
        {'policy_sha256':plan['base_policy_sha256']})
    bounded=deepcopy(corpus);bounded['frames']=[f for f in corpus['frames'] if f['available_at_ms']<plan['holdout_end_ms']]
    # Split on when an identity first became available, not a backdated detection
    # carried by a later frame. Out-of-window identities cannot quarantine a past
    # validation candidate or become a zero-return investment opportunity.
    first={}
    for frame in bounded['frames']:first.setdefault(frame['mint'],frame)
    dev_creators={f['creator'] for f in first.values() if f['available_at_ms']<plan['development_end_ms']}
    assignments={mint:('excluded_outside_window' if mint not in first else
        'development' if first[mint]['available_at_ms']<plan['development_end_ms'] else
        'excluded_creator_overlap' if first[mint]['creator'] in dev_creators else 'validation')
        for mint in raw_assignments}
    kind='market_observation' if corpus['data_kind'].startswith('market_observation') else 'synthetic'
    api=p4._api();pairs=[]
    for fee in plan['fee_multipliers']:
        for delay in plan['decision_delays_ms']:
            for split in ('development','validation'):
                partition=deepcopy(bounded)
                partition['frames']=[_scenario_frame(f,fee) for f in partition['frames'] if f['available_at_ms']+delay<plan['holdout_end_ms']]
                reference=_Adapter('reference',kind)
                # Scenario extras are already present during both decisions.
                common=dict(fee_multiplier=1,decision_delay_ms=delay,
                    development_end_ms=plan['development_end_ms'],api=api,research_overrides={},
                    research_exit_horizon_ms=plan['exit_horizon_ms'])
                a=p4._run_arm(partition,assignments,'early_sniping',split,decision_adapter=reference,**common)
                master=_Adapter('master',kind,reference.snapshots)
                b=p4._run_arm(partition,assignments,'early_sniping',split,decision_adapter=master,**common)
                opportunities=[]
                for mint,group in assignments.items():
                    if group!=split:continue
                    left,right=_position_result(a,mint),_position_result(b,mint)
                    known=left['conditional_net_lamports'] is not None and right['conditional_net_lamports'] is not None
                    opportunities.append(dict(mint=mint,reference=left,master=right,
                        conditional_delta_lamports=str(int(right['conditional_net_lamports'])-int(left['conditional_net_lamports'])) if known else None))
                disagreements=[]
                for frame_id,bs in master.snapshots.items():
                    av=reference.snapshots[frame_id];ba='BUY' if bs['action']=='ENTER' else bs['action']
                    disagreements.append(dict(frame_id=frame_id,reference_action=av['action'],master_action=ba,
                        action_disagrees=av['action']!=ba,master_reasons=bs['reasons'],
                        reference_snapshot_sha256=p4._hash(av),master_snapshot_sha256=p4._hash(bs)))
                a['arm']='reference';b['arm']='master'
                a['strategy']='reference_current';b['strategy']='master_adaptive_orchestrator'
                pairs.append(dict(split=split,fee_multiplier=fee,decision_delay_ms=delay,
                    reference=a,master=b,opportunities=opportunities,decisions=disagreements,
                    known_opportunity_deltas=sum(o['conditional_delta_lamports'] is not None for o in opportunities),
                    unknown_opportunity_deltas=sum(o['conditional_delta_lamports'] is None for o in opportunities)))
    return dict(schema='rugger-master-reference-comparison-v1',data_kind=kind,
        plan=deepcopy(plan),plan_sha256=p4._hash(plan),corpus_sha256=p4._hash(corpus),assignments=assignments,
        pairs=pairs,input_frames=len(corpus['frames']),observed_frames=len(bounded['frames']),
        retained_frames=len(bounded['frames']),
        split_basis='first_identity_availability; future_identities_do_not_change_past_assignments',
        excluded_outside_window=sum(x=='excluded_outside_window' for x in assignments.values()),
        excluded_creator_overlap=sum(x=='excluded_creator_overlap' for x in assignments.values()),
        same_observation_tape=True,same_financial_implementation=True,initial_capital_each_lamports='10000000000',
        policy_selection_performed=False,ranking=None,promotion_allowed=False,active_policy_changed=False,
        independent_market_edge_verified=False,strict_market_economic_cycles=0,new_market_observations=0,
        network_requests=0,execution_verified=False,
        limitation='retrospective conditional quote replay; no certified fills or causal own-entry market impact')


def evaluate_acquired_comparison(acquisition,plan):
    """Preserve the captured universe and unknowns across the P3/A-B boundary."""
    if (type(acquisition) is not dict or acquisition.get('schema')!='p3-master-comparison-acquisition-v1'
            or type(acquisition.get('denominator')) is not list
            or acquisition.get('universe_size')!=len(acquisition['denominator'])
            or acquisition.get('qualified_economic_cycles')!=0
            or acquisition.get('execution_verified') is not False
            or type(acquisition.get('candidates')) is not list):
        raise ValueError('Retained P3 acquisition envelope and complete universe required')
    result=evaluate_comparison(acquisition['corpus'],plan)
    result['acquisition_universe']=deepcopy({key:acquisition.get(key) for key in (
        'denominator','universe_size','selected_count','candidates','unknown_candidate_count',
        'refused_quote_observation_ids','future_observations_excluded','retained_tail','integrity','as_of_ms')})
    result['acquisition_universe']['discovery_universe_known']=acquisition.get('discovery_universe_known')
    result['acquisition_sha256']=p4._hash(acquisition)
    result['acquisition_authentication_verified']=False
    return result


def freeze_bank_research_decisions(selection, *, decision_at_ms):
    """Run the existing two engines BEFORE S2, retaining missing USD features.

    Native bank arithmetic cannot be supplied as a clocked executable quote or
    USD feature. These are comparable admission decisions, not a performance
    experiment. Every book is in-memory and initialized independently to 10 SOL.
    The complete discovery denominator remains in the frozen input envelope.
    """
    if (type(selection) is not dict
            or selection.get('schema')!='p3-asof-flow-research-selection-v1'
            or selection.get('selected_using_future_quotes_or_S2') is not False
            or selection.get('original_strict_selection_unchanged') is not True
            or selection.get('trade_allowed') is not False
            or type(decision_at_ms) is not int
            or selection.get('decision_at_ms')!=decision_at_ms):
        raise ValueError('Frozen pre-S2 research selection required')
    records=selection.get('original_strict_selection',{}).get('records')
    assessments=selection.get('assessments')
    if (type(records) is not list or type(assessments) is not list
            or len(assessments)!=selection.get('universe_size')
            or len(records)!=len(assessments) or not 0<len(records)<=100):
        raise ValueError('Full frozen discovery denominator required')
    frames=[];excluded=[];seen=set()
    for record,assessment in zip(records,assessments):
        row=record.get('source_row',{})
        bank=row.get('snapshot');available=row.get('snapshot_available_at_ms')
        index=record.get('universe_index')
        if index!=assessment.get('universe_index'):
            raise ValueError('Discovery record index mismatch')
        if (assessment.get('reason') in ('outside_fixed_twelve_prefix',
                'invalid_or_outside_native_SOL_scope','duplicate_mint_or_pool')
                or type(bank) is not dict):
            excluded.append(dict(universe_index=index,reason=assessment.get('reason')))
            continue
        if (type(available) is not int or not 0<=available<=decision_at_ms
                or bank.get('mint')!=row.get('mint')
                or bank.get('pool_address')!=row.get('pool')
                or row['mint'] in seen):
            raise ValueError('Future or inconsistent predecision bank')
        seen.add(row['mint'])
        frame=dict(id='bank012-'+p4._hash(dict(index=index,row=row,at=decision_at_ms)),
            mint=row['mint'],pool=row['pool'],creator=row.get('creator_claim'),
            available_at_ms=decision_at_ms,detected_at_ms=available,
            detection_clock_basis='first_S1_receipt_in_this_frame_not_launch_creation',
            source_slot=bank.get('context_slot'),slot_available_at_ms=available,
            features=None,features_available_at_ms=None,health=None,
            independent_buyers=None,observed_native_bank=deepcopy(bank),
            native_bank_available_at_ms=available,
            unknowns=['SOL_USD_asof','USD_strategy_features','independent_buyers',
                'own_applicable_costs','clocked_executable_quotes','operational_health'])
        frames.append(frame)
    if len(frames)>12:
        raise ValueError('Fixed twelve-prefix bank frame limit exceeded')
    corpus=dict(data_kind='market_observation',frames=frames)
    assignments={f['mint']:'development' for f in frames}
    api=p4._api()
    common=dict(fee_multiplier=1,decision_delay_ms=0,
        development_end_ms=decision_at_ms+1,api=api)
    left=_Adapter('reference','market_observation')
    a=p4._run_arm(corpus,assignments,'early_sniping','development',decision_adapter=left,**common)
    right=_Adapter('master','market_observation',left.snapshots)
    b=p4._run_arm(corpus,assignments,'early_sniping','development',decision_adapter=right,**common)
    # Missing features must remain a hard refusal through the actual adapters.
    if a['entered_positions'] or b['entered_positions']:
        raise ValueError('Bank-only input unexpectedly admitted to execution')
    pairs=[dict(frame_id=f['id'],mint=f['mint'],
        reference=deepcopy(left.snapshots[f['id']]),
        master=deepcopy(right.snapshots[f['id']]),
        decision_at_ms=decision_at_ms) for f in frames]
    return dict(schema='p3-bank-master-reference-frozen-v1',decision_at_ms=decision_at_ms,
        selection_sha256=p4._hash(selection),frames_sha256=p4._hash(frames),
        universe_size=len(records),paired_admission_decisions=len(pairs),pairs=pairs,
        excluded=excluded,initial_capital_each_lamports='10000000000',
        final_cash_each_lamports='10000000000',isolated_books=True,
        reference_entries=0,master_entries=0,strict_economic_cycles=0,
        frozen_before_S2=True,net_market_pnl_lamports=None,
        executable_quote_comparison=False,strategy_performance_comparable=False,
        execution_verified=False,independent_market_edge_verified=False,
        promotion_allowed=False,active_policy_changed=False)


def main(argv=None):
    os.environ['RUGGER_NO_DOTENV']='1'
    from bot.__main__ import _offline_policy
    sys.addaudithook(_offline_policy)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if (args.input.is_symlink() or args.input.name.startswith('.env') or args.input.suffix!='.json'
            or args.input.stat().st_size>16777216 or args.output.exists() or args.output.is_symlink()
            or args.output.suffix!='.json' or args.input.resolve()==args.output.resolve()):
        parser.error('Retained JSON input and new separate output required')
    data=json.loads(args.input.read_text())
    if ('corpus' in data)==('acquisition' in data):parser.error('Exactly one corpus or retained P3 acquisition envelope required')
    result=(evaluate_acquired_comparison(data['acquisition'],data['plan']) if 'acquisition' in data else
        evaluate_comparison(data['corpus'],data['plan']))
    from bot.analyser.artifacts import atomic_write_json
    atomic_write_json(args.output,result,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps(dict(report=str(args.output),promotion_allowed=False,network_requests=0)))


if __name__=='__main__':main()
