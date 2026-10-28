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


# A separately hashed research supplement: never changes POLICY or active sizing.
CURVE_COST_POLICY = {
    'schema':'p4-causal-curve-cost-comparison-v2',
    'position_lamports':[50000000,100000000,250000000,1000000000],
    'hypothetical_additional_cost_lamports':[0,15000,1000000],
    'hypothetical_external_buy_lamports':[0,100000000,500000000,1000000000],
    'hypothetical_external_sell_fraction_bps':[5000,10000],
    'bank_max_availability_age_ms':5000,
    'selection':'NONE; descriptive same-state counterfactuals only',
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
        if frame.get('bank_state') is not None:
            bank=frame['bank_state']
            if type(bank) is not dict:raise ValueError('Explicit bank-state mapping required')
            if type(bank.get('available_at_ms')) is not int or bank['available_at_ms']>at:
                raise ValueError('Future or unknown bank availability in decision frame')
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


def _bank_for_costs(frame,at):
    bank=frame.get('bank_state')
    if bank is None:return None,'bank_state_unknown'
    if type(bank) is not dict:return None,'bank_state_invalid'
    available=bank.get('available_at_ms')
    if type(available) is not int or available<0 or available>at:
        raise ValueError('Bank was not available at this decision')
    if not 0<=at-available<=CURVE_COST_POLICY['bank_max_availability_age_ms']:
        return None,'bank_availability_stale_or_invalid'
    identity=bank.get('observation_id')
    if (bank.get('mint')!=frame.get('mint') or bank.get('pool')!=frame.get('pool')
            or type(bank.get('source_slot')) is not int or bank['source_slot']<=0
            or bank['source_slot']!=frame.get('source_slot')
            or bank.get('provenance') not in ('retained_rpc_snapshot','synthetic')
            or not ((type(identity) is int and identity>0) or (type(identity) is str and bool(identity)))
            or type(bank.get('pool_state')) is not dict):
        return None,'bank_identity_or_provenance_unqualified'
    pool=bank['pool_state']
    if pool.get('mint_a')!=frame['mint']:
        return None,'bank_pool_mint_mismatch'
    if type(pool.get('real_a')) is not int or not 0<=pool['real_a']<2**64:
        return None,'bank_circulation_amount_invalid'
    required=('fee_rates_ppm','base_vault_atomic','quote_vault_lamports','curve_type','share_fee_rate_ppm')
    if any(name not in bank for name in required):return None,'bank_cost_inputs_missing'
    for name in ('identity_qualified','creation_verified','supply_verified'):
        if bank.get(name) is not None and type(bank[name]) is not bool:
            return None,'bank_certification_state_invalid'
    try:json.dumps(bank,allow_nan=False)
    except (TypeError,ValueError):return None,'bank_nonfinite_or_non_json'
    return bank,None


def _asof_provider_quality(frame,size,at):
    """Keep exact indicative observations; no quote scaling or inferred fills."""
    from fractions import Fraction
    from bot.p3.exit_qualification import inventory_from_buy
    from bot.p3.replay import replay_quote_observation
    from bot.p3.quotes import SOL_MINT
    contexts=frame.get('size_contexts',{})
    context=contexts.get(str(size)) if type(contexts) is dict else None
    if context is None and type(frame.get('buy_context')) is dict:
        candidate=frame['buy_context'].get('buy_observation')
        if type(candidate) is dict and candidate.get('payload',{}).get('input_amount_atomic')==str(size):
            context=dict(buy_observation=candidate,sell_observations=[])
    result=dict(buy_observation_id=None,projected_quantity_atomic=None,
        full_sell_observation_ids=[],partial_sell_observation_ids=[],refusal_observation_ids=[],
        full_sell_quoted=False,max_quoted_inventory_fraction=None,
        source_times_unknown=0,source_slots_unknown=0,observations_used=0,
        buy_body_replayed=False,validation_reasons=[],
        economic_qualified=False,execution_verified=False,
        basis='exact_retained_quotes_available_at_decision; no scaling or fills')
    if type(context) is not dict:return result
    buy=context.get('buy_observation');p=buy.get('payload',{}) if type(buy) is dict else {}
    if (type(buy) is not dict or type(buy.get('available_at_ms')) is not int
            or buy['available_at_ms']>at or buy.get('mint')!=frame['mint']
            or buy.get('outcome')!='quoted' or p.get('input_mint')!=SOL_MINT
            or p.get('output_mint')!=frame['mint'] or p.get('input_amount_atomic')!=str(size)
            or type(p.get('output_amount_atomic')) is not str or not p['output_amount_atomic'].isdecimal()
            or int(p['output_amount_atomic'])<=0):return result
    retained=inventory_from_buy(buy,token_decimals=None,entry_decision_at_ms=at,max_source_age_ms=5000)
    result['validation_reasons']=retained['reasons']
    if not retained['accepted']:return result
    result['buy_body_replayed']=True
    quantity=int(p['output_amount_atomic']);accepted=[buy];coverage=None
    result.update(buy_observation_id=buy.get('id'),projected_quantity_atomic=str(quantity))
    seen=set()
    for sell in context.get('sell_observations',[]):
        if (type(sell) is not dict or type(sell.get('id')) not in (str,int)
                or sell.get('id') in seen):continue
        sp=sell.get('payload',{})
        if (type(sell.get('available_at_ms')) is not int or not buy['available_at_ms']<=sell['available_at_ms']<=at
                or sell.get('mint')!=frame['mint'] or sp.get('input_mint')!=frame['mint']
                or sp.get('output_mint')!=SOL_MINT or type(sp.get('input_amount_atomic')) is not str
                or not sp['input_amount_atomic'].isdecimal()):continue
        q=int(sp['input_amount_atomic'])
        if not 0<q<=quantity:continue
        try:
            checked=replay_quote_observation(sell)
            if checked['status']!='REPLAYED':continue
        except (ValueError,TypeError,KeyError):continue
        if sell.get('outcome')=='quoted' and sp.get('actual_input_amount_atomic')!=str(q):continue
        seen.add(sell.get('id'));accepted.append(sell)
        if sell.get('outcome')=='quoted':
            (result['full_sell_observation_ids'] if q==quantity else result['partial_sell_observation_ids']).append(sell.get('id'))
            fraction=Fraction(q,quantity);coverage=max(coverage or fraction,fraction)
        elif sell.get('outcome') in ('unavailable','error'):
            result['refusal_observation_ids'].append(sell.get('id'))
    result.update(full_sell_quoted=bool(result['full_sell_observation_ids']),
        max_quoted_inventory_fraction=str(coverage) if coverage is not None else None,
        observations_used=len(accepted),source_times_unknown=sum(e.get('source_time_ms') is None for e in accepted),
        source_slots_unknown=sum(e.get('source_slot') is None for e in accepted))
    return result


def assess_curve_costs(frame,history=(),*,decision_at_ms=None,api=None):
    """Compare fixed research sizes before outcomes, outside the PAPER ledger.

    The bank belongs to this decision's available prefix. Each size gets an
    independent integer buy/own-state sell, never a scaled external quotation.
    Extra-cost and external-flow scenarios are explicitly hypothetical; they do
    not certify freshness, executable liquidity, own costs or future outcomes.
    """
    from bot.p3.position_model import evaluate_position
    from bot.p3.launchlab import observed_sell_projection,SnapshotEvidenceError
    at=frame.get('available_at_ms') if decision_at_ms is None else decision_at_ms
    if type(at) is not int or type(frame.get('available_at_ms')) is not int or at<frame['available_at_ms']:
        raise ValueError('Decision precedes frame availability')
    bank,reason=_bank_for_costs(frame,at)
    decisions={}
    for strategy in POLICY['strategies']:
        if type(frame.get('features')) is not dict:
            decisions[strategy]={'enter_intent':None,'reason':'strategy_features_unknown'}
        else:
            decision=decide_prefix(strategy,frame,history,api=api,decision_at_ms=at)
            decisions[strategy]={'enter_intent':decision['enter'],'reason':decision['reason']}
    result=dict(schema=CURVE_COST_POLICY['schema'],policy_sha256=_hash(CURVE_COST_POLICY),
        frame_id=frame.get('id'),mint=frame.get('mint'),pool=frame.get('pool'),decision_at_ms=at,
        bank_available=bank is not None,bank_unavailable_reason=reason,strategy_decisions=decisions,
        sizes=[],ranking=None,active_size_changed=False,ledger_credited=False,
        strict_economic_cycles=0,economic_profitability_verified=False,execution_verified=False)
    if bank is None:return result
    result['source_bank']={key:bank.get(key) for key in ('observation_id','source_slot','available_at_ms',
        'provenance','identity_qualified','creation_verified','supply_verified','evidence_tail_hash')}
    result['source_bank']['availability_age_ms']=at-bank['available_at_ms']
    result['source_bank']['availability_does_not_certify_provider_quote_freshness']=True
    kwargs=dict(pool=bank['pool_state'],fee_rates_ppm=bank['fee_rates_ppm'],
        base_vault_atomic=bank['base_vault_atomic'],quote_vault_lamports=bank['quote_vault_lamports'],
        curve_type=bank['curve_type'],share_fee_rate_ppm=bank['share_fee_rate_ppm'])
    for size in CURVE_COST_POLICY['position_lamports']:
        model=evaluate_position(input_lamports=size,**kwargs)
        observed=None;refusal=None
        if model['admissible']:
            try:
                observed=observed_sell_projection(bank['pool_state'],
                    input_token_atomic=int(model['buy_output_atomic']),fee_rates_ppm=bank['fee_rates_ppm'],
                    quote_vault_lamports=bank['quote_vault_lamports'],curve_type=bank['curve_type'],
                    share_fee_rate_ppm=bank['share_fee_rate_ppm'])
            except SnapshotEvidenceError as error:refusal=str(error)
        costs=[dict(additional_costs_lamports=str(extra),cost_basis='explicit_hypothetical_total',
            model=evaluate_position(input_lamports=size,additional_costs_lamports=extra,**kwargs))
            for extra in CURVE_COST_POLICY['hypothetical_additional_cost_lamports']]
        reserve=[dict(external_buy_lamports=str(flow),
            flow_basis='hypothetical_external_buy_after_our_entry_not_observed_future',
            model=evaluate_position(input_lamports=size,external_buy_lamports=flow,**kwargs))
            for flow in CURVE_COST_POLICY['hypothetical_external_buy_lamports']]
        downside=[]
        for fraction in CURVE_COST_POLICY['hypothetical_external_sell_fraction_bps']:
            quantity=bank['pool_state']['real_a']*fraction//10000
            downside.append(dict(preexisting_circulation_fraction_bps=fraction,
                external_sell_token_atomic=str(quantity),
                scenario_state='no_preexisting_inventory_to_sell' if quantity==0 else 'conditional',
                model=None if quantity==0 else evaluate_position(input_lamports=size,
                    external_sell_token_atomic=quantity,**kwargs)))
        result['sizes'].append(dict(input_lamports=str(size),same_state_own_entry_model=model,
            observed_state_sell_estimate=observed,observed_state_sell_refusal=refusal,
            observed_state_does_not_contain_own_entry=True,hypothetical_additional_costs=costs,
            hypothetical_reserve_sensitivity=reserve,provider_quotes=_asof_provider_quality(frame,size,at)))
        result['sizes'][-1]['hypothetical_downside_sensitivity']=downside
    return result


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


def _run_arm(corpus,assignments,strategy,split,*,fee_multiplier,decision_delay_ms,development_end_ms,api,
             curve_assessments=None):
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
            if curve_assessments is not None and (frame['id'],at) in curve_assessments:
                trace[-1]['curve_cost_assessment_sha256']=_hash(curve_assessments[(frame['id'],at)])
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
    curve_assessments=None
    if any(frame.get('bank_state') is not None for frame in corpus['frames']):
        curve_assessments={}
        for delay in delays:
            histories={}
            for frame in corpus['frames']:
                history=histories.setdefault(frame['mint'],[])
                at=frame['available_at_ms']+delay
                if (frame.get('bank_state') is not None
                        and assignments[frame['mint']]!='excluded_creator_overlap'
                        and not (assignments[frame['mint']]=='development' and at>=protocol['development_end_ms'])):
                    curve_assessments[(frame['id'],at)]=assess_curve_costs(frame,history,decision_at_ms=at,api=api)
                history.append(frame)
    for multiplier in multipliers:
        for delay in delays:
            for split in ('development','validation'):
                for strategy in POLICY['strategies']:
                    result=_run_arm(corpus,assignments,strategy,split,fee_multiplier=multiplier,
                                    decision_delay_ms=delay,development_end_ms=protocol['development_end_ms'],api=api,
                                    curve_assessments=curve_assessments)
                    result.update(fee_multiplier=multiplier,decision_delay_ms=delay)
                    runs.append(result)
    report={'schema':'p4-native-experiment-report-v1','data_kind':corpus['data_kind'],
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
    if curve_assessments is not None:
        report['curve_cost_comparison']={'policy':deepcopy(CURVE_COST_POLICY),
            'policy_sha256':_hash(CURVE_COST_POLICY),'assessments':list(curve_assessments.values()),
            'basis':'causal_same_bank_model_supplement_not_ledger_cashflows',
            'active_book_position_lamports':POLICY['position_lamports'],'ranking':None,
            'strict_economic_cycles':0,'execution_verified':False}
    return report


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
