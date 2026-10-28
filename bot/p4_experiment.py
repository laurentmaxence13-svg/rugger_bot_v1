"""Offline, causal strategy comparison through the existing atomic PAPER book.

Research adapters are frozen hypotheses, never a replacement for the active
strategy. Input features/quotes must be retained, available observations. No
price interpolation, inventory scaling, HTTP, transaction or wallet is used.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys


POLICY = {
    'schema':'p4-frozen-native-comparison-v1',
    'strategies':['early_sniping','confirmed_momentum','adaptive_hybrid'],
    'confirmation_delay_ms':15000, 'confirmation_min_independent_buyers':2,
    'adaptive_min_prior_launches':2, 'adaptive_max_top_holder_share':0.2,
    'feature_max_age_ms':5000, 'exit_horizon_ms':30000,
    'position_lamports':1000000000, 'initial_capital_lamports':10000000000,
    'max_open':3, 'max_entries_day':20, 'max_daily_loss_pct':10.0,
    'minimum_independent_validation_creators':50,
    'sensitivity_fee_multipliers':[1,2], 'sensitivity_decision_delays_ms':[0,250],
}


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _api():
    previous=os.environ.get('RUGGER_NO_DOTENV');os.environ['RUGGER_NO_DOTENV']='1'
    try:
        from bot.analyser.final_decision_engine import SignalFeatures,decide
        from bot.analyser.paper_trader import (setup,ensure_paper_portfolio,record_quote,
            MarketQuote,paper_capital,_paper_realization_events,_paper_reconciled_capital)
        from bot.analyser.token_inventory import inventory_state,_lamports
        return locals()
    finally:
        if previous is None:os.environ.pop('RUGGER_NO_DOTENV',None)
        else:os.environ['RUGGER_NO_DOTENV']=previous


def _integer(value,name,positive=False):
    if type(value) is not int or value<(1 if positive else 0):
        raise ValueError('Invalid '+name)
    return value


def _validate(corpus,protocol):
    if (type(protocol) is not dict or set(protocol)!={'development_end_ms','registered_at_ms','policy_sha256'}
            or protocol.get('policy_sha256')!=_hash(POLICY)):
        raise ValueError('Exact frozen policy and chronological split required')
    cutoff=_integer(protocol['development_end_ms'],'development cutoff',True)
    registered=_integer(protocol['registered_at_ms'],'registration',True)
    if registered>=cutoff:raise ValueError('Protocol must predate validation')
    if (type(corpus) is not dict or set(corpus)!={'data_kind','frames'}
            or corpus['data_kind'] not in ('synthetic','market_observations')
            or type(corpus['frames']) is not list):
        raise ValueError('Explicit corpus provenance required')
    try:json.dumps(corpus,allow_nan=False)
    except (ValueError,TypeError):raise ValueError('Nonfinite or non-JSON corpus input') from None
    seen=set();previous=-1;identities={}
    for frame in corpus['frames']:
        if type(frame) is not dict or not all(frame.get(k) for k in ('id','mint','creator','pool')):
            raise ValueError('Frame identity missing')
        if frame['id'] in seen:raise ValueError('Duplicate frame identity')
        seen.add(frame['id'])
        at=_integer(frame.get('available_at_ms'),'availability',True)
        detected=_integer(frame.get('detected_at_ms'),'detection',True)
        if at<previous or detected>at:raise ValueError('Noncausal frame order')
        previous=at
        identity=(frame['creator'],frame['pool'],detected)
        if frame['mint'] in identities and identities[frame['mint']]!=identity:
            raise ValueError('Inconsistent candidate identity')
        identities[frame['mint']]=identity
        for name in ('features_available_at_ms','slot_available_at_ms'):
            value=frame.get(name)
            if value is not None and (_integer(value,name)>at):
                raise ValueError('Future information in decision frame')
        if frame.get('source_slot') is not None:_integer(frame['source_slot'],'source slot',True)
        if frame.get('independent_buyers') is not None:_integer(frame['independent_buyers'],'independent buyers')
    development_creators={creator for creator,_pool,detected in identities.values() if detected<cutoff}
    assignments={}
    for mint,(creator,_pool,detected) in identities.items():
        assignments[mint]=('development' if detected<cutoff else
            'excluded_creator_overlap' if creator in development_creators else 'validation')
    return assignments


def _features(frame,api,at):
    raw=frame.get('features');available=frame.get('features_available_at_ms')
    if type(raw) is not dict or type(available) is not int or not 0<=at-available<=POLICY['feature_max_age_ms']:
        return None,'features_unknown_or_stale'
    try:
        f=api['SignalFeatures'](**raw)
        if (f.mint!=frame['mint'] or f.creator!=frame['creator']
                or f.signal_time!=frame['detected_at_ms']//1000
                or type(f.observed_at) is not int or f.observed_at*1000>available
                or not 0<=at-f.observed_at*1000<=POLICY['feature_max_age_ms']):
            return None,'features_identity_or_asof_mismatch'
        for name in ('prior_launches','relevant_transactions','dev_sales','relay_transfers',
                     'bundle_transactions','bundle_wallets','quote_count','holder_count',
                     'linked_wallets','wallet_link_count','same_slot_wallets','wallet_graph_transactions'):
            _integer(getattr(f,name),name)
        for name in ('behavior_known','holder_data_known'):
            if type(getattr(f,name)) is not bool:raise ValueError(name)
        for name in ('liquidity_usd','price_usd'):
            if type(getattr(f,name)) not in (int,float) or not math.isfinite(getattr(f,name)) or getattr(f,name)<=0:
                raise ValueError(name)
        for name in ('momentum_60s','momentum_300s','volume_5m_usd','volume_24h_usd',
                     'price_change_5m_pct','price_change_1h_pct','market_cap_usd','fdv_usd',
                     'fee_bps','depth_usd','slippage_bps_est','top_holder_share','funding_usd'):
            value=getattr(f,name)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):
                raise ValueError(name)
        if f.top_holder_share is not None and not 0<=f.top_holder_share<=1:raise ValueError('concentration')
        return f,None
    except (TypeError,ValueError,OverflowError):return None,'features_invalid'


def decide_prefix(strategy,frame,history,*,api=None,decision_at_ms=None):
    """Return a decision using only this frame and the supplied past prefix."""
    if strategy not in POLICY['strategies']:raise ValueError('Unknown strategy')
    api=_api() if api is None else api
    at=frame['available_at_ms'] if decision_at_ms is None else decision_at_ms
    if type(at) is not int or at<frame['available_at_ms']:
        raise ValueError('Decision precedes frame availability')
    f,reason=_features(frame,api,at)
    if f is None:return {'enter':False,'reason':reason,'model':None,'score':None}
    base=api['decide'](f)
    if not base.enter:return {'enter':False,'reason':'active_risk_or_score_refusal','model':base.to_paper_model(),'score':base.score}
    slot=frame.get('source_slot')
    if (type(slot) is not int or slot<=0 or type(frame.get('slot_available_at_ms')) is not int
            or not 0<=frame['slot_available_at_ms']<=at):
        return {'enter':False,'reason':'source_slot_unknown','model':base.to_paper_model(),'score':base.score}
    known=[]
    for h in history:
        if (h['available_at_ms']>at or h['mint']!=frame['mint']
                or type(h.get('source_slot')) is not int or h['source_slot']<=0
                or type(h.get('slot_available_at_ms')) is not int
                or h['slot_available_at_ms']>h['available_at_ms']):continue
        prior,_=_features(h,api,h['available_at_ms'])
        if prior is not None and api['decide'](prior).enter:known.append(h)
    known.sort(key=lambda h:h['available_at_ms'])
    first=known[0] if known else frame
    first_price=first['features'].get('price_usd')
    confirmation=(at-first['available_at_ms']>=POLICY['confirmation_delay_ms']
        and slot>first['source_slot'] and type(first_price) in (int,float) and first_price>0
        and f.price_usd>first_price
        and type(frame.get('independent_buyers')) is int
        and frame['independent_buyers']>=POLICY['confirmation_min_independent_buyers'])
    quick=(f.behavior_known and f.prior_launches>=POLICY['adaptive_min_prior_launches']
           and f.holder_data_known and f.top_holder_share is not None
           and f.top_holder_share<=POLICY['adaptive_max_top_holder_share']
           and not f.bundle_transactions and not f.same_slot_wallets)
    enter=strategy=='early_sniping' or confirmation or (strategy=='adaptive_hybrid' and quick)
    return {'enter':enter,'reason':('early_qualified' if strategy=='early_sniping' else
        'known_creator_early' if strategy=='adaptive_hybrid' and quick else
        'confirmed_momentum' if confirmation else 'awaiting_observed_confirmation'),
        'model':base.to_paper_model(),'score':base.score}


def _scaled_context(context,multiplier):
    context=deepcopy(context) if type(context) is dict else {}
    fees=context.get('fees')
    if type(fees) is dict:
        if type(fees.get('entry_extra_lamports')) is int:fees['entry_extra_lamports']*=multiplier
        if type(fees.get('exit_extra_lamports')) is int:fees['exit_extra_lamports']*=multiplier
        if multiplier!=1 and fees.get('provenance')!='synthetic':fees['provenance']='estimate'
        if type(fees.get('failed_attempt_lamports')) in (list,tuple):
            fees['failed_attempt_lamports']=[n*multiplier for n in fees['failed_attempt_lamports']]
    return context


def _position_pct(api,capital):
    # The existing book takes a percentage; preserve the protocol's exact integer
    # budget through that float display API, refusing unsupported magnitudes.
    target=POLICY['position_lamports'];pct=(target/1e9)/capital*100
    for _ in range(32):
        actual=api['_lamports'](capital*pct/100)
        if actual==target:return pct
        pct=math.nextafter(pct,math.inf if actual<target else -math.inf)
    raise ValueError('Fixed research budget cannot be represented by existing sizing API')


def _run_arm(corpus,assignments,strategy,split,*,fee_multiplier,decision_delay_ms,development_end_ms,api):
    con=sqlite3.connect(':memory:',isolation_level=None)
    try:
        api['setup'](con);api['ensure_paper_portfolio'](con,10.0,0)
        histories={};models={};trace=[];candidate_mints={mint for mint,group in assignments.items() if group==split}
        for frame in corpus['frames']:
            mint=frame['mint']
            if mint not in candidate_mints:continue
            at=frame['available_at_ms']+decision_delay_ms
            if split=='development' and at>=development_end_ms:continue
            history=histories.setdefault(mint,[])
            decision=decide_prefix(strategy,frame,history,api=api,decision_at_ms=at)
            state=api['inventory_state'](con,mint)
            entry=state is None and decision['enter']
            f,_=_features(frame,api,at)
            message=None
            if f is not None:
                quote=api['MarketQuote'](f.liquidity_usd,f.price_usd,frame['pool'],quote_source='offline_retained_features')
                context=None
                if state is None:
                    context=_scaled_context(frame.get('buy_context'),fee_multiplier)
                else:
                    buy_id=json.loads(state['entry_observation_json']).get('id')
                    matching=[item for item in frame.get('sell_contexts',[]) if type(item) is dict
                              and item.get('inventory_buy_observation_id')==buy_id]
                    if len(matching)>1:raise ValueError('Ambiguous inventory-bound sell contexts')
                    context=_scaled_context(matching[0] if matching else None,fee_multiplier)
                    context['inventory_version']=state['version']
                context['decision_at_ms']=at
                model=models.get(mint,decision['model'])
                try:
                    capital=api['_paper_reconciled_capital'](con)
                    pct=_position_pct(api,capital) if capital>0 else 0
                    message=api['record_quote'](con,mint,frame['creator'],frame['detected_at_ms']//1000,
                        at//1000,quote,model,allow_entry=entry,strategy_mode='shadow_final',
                        force_exit_reason=('RESEARCH_HORIZON' if state and at-state['entry_decision_ms']>=POLICY['exit_horizon_ms'] else None),
                        initial_capital_sol=10.0,position_pct=pct,max_open=POLICY['max_open'],
                        max_entries_day=POLICY['max_entries_day'],max_daily_loss_pct=POLICY['max_daily_loss_pct'],
                        inventory_context=context,require_inventory=True)
                except (ValueError,TypeError) as error:
                    message='RESEARCH_REFUSED '+type(error).__name__+': '+str(error)
                if state is None and api['inventory_state'](con,mint) is not None:models[mint]=decision['model']
            trace.append({'frame_id':frame['id'],'mint':mint,'decision_at_ms':at,'enter_intent':entry,
                          'decision_reason':decision['reason'],'decision_score':decision['score'],'message':message})
            history.append(frame)
        states=[]
        for row in con.execute('SELECT mint,acquired_atomic,remaining_atomic,cost_basis_remaining_lamports,realized_pnl_lamports,entry_extra_lamports FROM paper_token_inventory ORDER BY mint'):
            mint,acquired,left,basis,pnl,entry_fee=row
            states.append({'mint':mint,'acquired_atomic':acquired,'remaining_atomic':left,
                'liquidated_fraction':(int(acquired)-int(left))/int(acquired),
                'remaining_cost_basis_lamports':basis,'realized_pnl_lamports':pnl,
                'entry_cost_known':entry_fee is not None})
        events=api['_paper_realization_events'](con)
        capital=api['_paper_reconciled_capital'](con)
        closed=[p for (p,) in con.execute("SELECT pnl_sol FROM paper_trades WHERE status='closed'")]
        complete=bool(states) and all(p['remaining_atomic']=='0' for p in states)
        gains=sum(p for p in closed if p>0);losses=-sum(p for p in closed if p<0)
        equity=peak=10.0;drawdown=0
        for event in events:
            equity+=event['pnl_sol'];peak=max(peak,equity);drawdown=min(drawdown,equity/peak-1)
        legs=[{'quantity_atomic':q,'proceeds_lamports':received,'extra_fee_lamports':fee,'pnl_lamports':pnl}
            for q,received,fee,pnl in con.execute('SELECT quantity_atomic,proceeds_lamports,extra_fee_lamports,pnl_lamports FROM paper_token_legs ORDER BY decision_ms,id')]
        return {'strategy':strategy,'split':split,'candidate_count':len(candidate_mints),
            'entered_positions':len(states),'closed_positions':len(closed),'unentered_candidates':len(candidate_mints)-len(states),
            'positions':states,'legs':legs,'trace':trace,'realized_capital_sol':capital,
            'realized_pnl_sol':sum(e['pnl_sol'] for e in events),
            'portfolio_pnl_sol':capital-10 if complete else None,
            'portfolio_return':(capital-10)/10 if complete else None,
            'net_expectancy_per_entered_position_sol':sum(closed)/len(states) if complete else None,
            'win_rate':sum(p>0 for p in closed)/len(closed) if complete else None,
            'average_win_sol':gains/sum(p>0 for p in closed) if complete and gains else None,
            'average_loss_sol':-losses/sum(p<0 for p in closed) if complete and losses else None,
            'profit_factor':gains/losses if complete and losses else None,
            'max_realized_drawdown':drawdown,'all_entered_positions_liquidated':complete,
            'exit_attempts':con.execute('SELECT COUNT(*) FROM paper_token_exit_attempts').fetchone()[0],
            'qualification_failures':con.execute('SELECT COUNT(*) FROM paper_token_exit_attempts WHERE qualification_json LIKE ?',('%"accepted":false%',)).fetchone()[0],
            'known_modeled_extra_costs_lamports':str(sum(int(leg['extra_fee_lamports']) for leg in legs)+sum(int(row[0]) for row in con.execute('SELECT entry_extra_lamports FROM paper_token_inventory') if row[0] is not None)),
            'full_extra_costs_lamports':(str(sum(int(leg['extra_fee_lamports']) for leg in legs)+sum(int(row[0]) for row in con.execute('SELECT entry_extra_lamports FROM paper_token_inventory'))) if complete else None),
            'economic_profitability_verified':False,'execution_verified':False}
    finally:con.close()


def evaluate_experiment(corpus,protocol,*,include_sensitivity=True):
    """All strategies use the same source prefix, bankroll and native ledger.

    Unknown/unliquidated positions prevent total-performance ranking. Development
    and validation use independent runs; creator overlap is quarantined before
    evaluating either partition. Frozen sensitivities are never model selection.
    """
    assignments=_validate(corpus,protocol);api=_api()
    runs=[]
    multipliers=POLICY['sensitivity_fee_multipliers'] if include_sensitivity else [1]
    delays=POLICY['sensitivity_decision_delays_ms'] if include_sensitivity else [0]
    for multiplier in multipliers:
        for delay in delays:
            for split in ('development','validation'):
                for strategy in POLICY['strategies']:
                    result=_run_arm(corpus,assignments,strategy,split,fee_multiplier=multiplier,
                                    decision_delay_ms=delay,development_end_ms=protocol['development_end_ms'],api=api)
                    result.update(fee_multiplier=multiplier,decision_delay_ms=delay)
                    runs.append(result)
    return {'schema':'p4-native-experiment-report-v1','data_kind':corpus['data_kind'],
        'policy':deepcopy(POLICY),'policy_sha256':_hash(POLICY),'protocol':deepcopy(protocol),
        'corpus_sha256':_hash(corpus),'assignments':assignments,'runs':runs,
        'validation_creator_groups':len({f['creator'] for f in corpus['frames'] if assignments[f['mint']]=='validation'}),
        'creator_group_basis':'input identity claims; independence not certified',
        'independent_validation_creators_verified':None,'protocol_registration_verified':False,
        'ranking':None,'selection':'NONE; frozen research hypotheses only',
        'statistical_edge_verified':False,'economic_profitability_verified':False,
        'uncertainty':'No market confidence claim; creator clustering and minimum sample still required',
        'network_requests':0,'acquisition_verified':False,'execution_verified':False,
        'model_eligible':False,'own_entry_impact_qualification':'No observed execution effect; independent quote scenarios only'}


def main(argv=None):
    os.environ['RUGGER_NO_DOTENV']='1'
    from bot.__main__ import _offline_policy
    sys.addaudithook(_offline_policy)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if (args.input.is_symlink() or args.input.name.startswith('.env') or args.input.suffix!='.json'
            or args.input.stat().st_size>16777216 or args.output.exists() or args.output.is_symlink()
            or args.output.suffix!='.json' or args.output.resolve()==args.input.resolve()):
        parser.error('Retained JSON corpus and a separate new JSON report required')
    payload=json.loads(args.input.read_text())
    report=evaluate_experiment(payload['corpus'],payload['protocol'])
    from bot.analyser.artifacts import atomic_write_json
    atomic_write_json(args.output,report,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps({'report':str(args.output),'ranking':None,'network_requests':0}))


if __name__=='__main__':main()
