"""Bounded, preregistered policy research through the existing PAPER replay.

Selection uses development only. A frozen holdout is evaluated once per supplied
registry; neither this module nor its CLI can activate a production policy.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def candidates():
    from bot.p4_experiment import POLICY
    variations=[('baseline',{}),('tp7-sl5',{'tp_pct':7,'sl_pct':5}),
        ('tp7-sl8',{'tp_pct':7,'sl_pct':8}),('tp14-sl5',{'tp_pct':14,'sl_pct':5}),
        ('tp14-sl8',{'tp_pct':14,'sl_pct':8}),
        ('score-liquidity',{'min_score':60,'min_liquidity':3000}),
        ('confirmation-exit',{'confirmation_delay_ms':30000,'hold_seconds':900,'trailing_stop_pct':3.5}),
        ('size-0.10',{'position_lamports':100000000})]
    return [dict(id=strategy+':'+name,strategy=strategy,overrides=deepcopy(values))
        for strategy in POLICY['strategies'] for name,values in variations]


def make_plan(*,registered_at_ms,development_end_ms,holdout_end_ms,research_exit_horizon_ms=None,
              paired_validation=False):
    times=(registered_at_ms,development_end_ms,holdout_end_ms)
    if any(type(t) is not int or t<=0 for t in times) or not registered_at_ms<development_end_ms<holdout_end_ms:
        raise ValueError('Registration, development and holdout clocks must be ordered')
    if research_exit_horizon_ms is not None and (type(research_exit_horizon_ms) is not int
            or not 30000<=research_exit_horizon_ms<=3600000):
        raise ValueError('Research exit horizon must be an integer between30000 and3600000ms')
    if type(paired_validation) is not bool:
        raise ValueError('Paired validation must be an explicit Boolean registration')
    plan=dict(schema='rugger-policy-research-plan-v1',registered_at_ms=registered_at_ms,
        development_end_ms=development_end_ms,holdout_end_ms=holdout_end_ms,
        candidates=candidates(),maximum_candidates=24,maximum_frames=5000,
        objective={'tail_loss_weight':2,'drawdown_capital_weight':1},
        minimum_validation_creator_groups=50,selection='development_only_then_frozen_holdout',
        production_promotion='NEVER; separate independent evidence and authorization required')
    # Omission preserves the exact original30s plan and report fingerprints.
    if research_exit_horizon_ms is not None:plan['research_exit_horizon_ms']=research_exit_horizon_ms
    if paired_validation:
        plan['paired_validation']={
            'schema':'rugger-paired-policy-validation-design-v1',
            'unit':'creator_group_after_same_mint_pairing',
            'hypothesis_family_size':24,'familywise_alpha':{'numerator':1,'denominator':20},
            'per_hypothesis_alpha':{'numerator':1,'denominator':480},
            'multiplicity_method':'Bonferroni; registered allocation only, no inferential claim',
            'minimum_complete_creator_groups':50,
            'sensitivity_fee_multipliers':[1,2],'sensitivity_decision_delays_ms':[0,250],
            'selection':'descriptive_only_after_development_candidates_frozen',
            'inference':'BLOCKED until independent market evidence is separately audited'}
    return plan


def _validate_plan(plan):
    if type(plan) is not dict:raise ValueError('Explicit frozen plan required')
    expected=make_plan(**{key:plan.get(key) for key in (
        'registered_at_ms','development_end_ms','holdout_end_ms','research_exit_horizon_ms')},
        paired_validation='paired_validation' in plan)
    if plan!=expected:raise ValueError('Plan differs from the bounded frozen candidate design')
    return digest(plan)


def _objective(run):
    values=[int(p['realized_pnl_lamports'])/1e9 for p in run['positions']]
    complete=run['all_entered_positions_liquidated'] and run['full_extra_costs_lamports'] is not None
    if not complete:return dict(eligible=False,objective=None,dispersion_sol=None,tail_loss_sol=None)
    mean=sum(values)/len(values)
    variance=sum((v-mean)**2 for v in values)/len(values)
    worst=sorted(values)[:max(1,math.ceil(len(values)*.05))]
    tail=max(0,-sum(worst)/len(worst))
    score=mean-2*tail-10*abs(run['max_realized_drawdown'])
    return dict(eligible=True,objective=score,dispersion_sol=math.sqrt(variance),
        tail_loss_sol=tail,expectancy_sol=mean,position_count=len(values),
        scope='net_fixture_or_conditional_quote_outcomes; not certified market edge')


def _paired_outcome(run,mint):
    """A zero cashflow from abstention never proves zero opportunity cost."""
    positions=[row for row in run['positions'] if row['mint']==mint]
    traces=[row for row in run['trace'] if row['mint']==mint]
    refused=[row for row in traces if any(marker in (row.get('message') or '')
        for marker in ('REFUSED','_UNQUALIFIED'))]
    if len(positions)>1:raise ValueError('A paired opportunity must identify one native position')
    result=dict(entered=bool(positions),net_pnl_lamports=None,remaining_atomic=None,
        refusal_count=len(refused),entry_intentions=sum(row.get('enter_intent') is True for row in traces),
        decision_reasons=sorted({row['decision_reason'] for row in traces}),
        refusals=[dict(frame_id=row['frame_id'],decision_at_ms=row['decision_at_ms'],
            reason=row['message']) for row in refused],
        opportunity_cost_lamports=None)
    if not positions:
        result.update(state='NO_POSITION_CASHFLOW_ONLY',net_pnl_lamports='0',
            remaining_atomic='0',cost_scope='no_position_no_order_cashflow_in_this_PAPER_replay')
        return result
    position=positions[0];result['remaining_atomic']=position['remaining_atomic']
    known=(position['remaining_atomic']=='0' and position['entry_cost_known'] is True
        and run['full_extra_costs_lamports'] is not None)
    if known:
        result.update(state='COMPLETE_CONDITIONAL_PAPER_OUTCOME',
            net_pnl_lamports=str(int(position['realized_pnl_lamports'])),
            cost_scope='complete_retained_quotes_and_known_extra_costs')
    else:
        result.update(state='UNKNOWN_OR_REMAINING_POSITION',cost_scope='unliquidated_or_costs_unknown')
    return result


def _paired_holdout(candidate,reference,universe):
    """Pair all opportunities, then cluster mints sharing one creator.

    This describes conditional ledger differences. No p-value is inferred from
    fixture outcomes or from an input claiming that creators are independent.
    """
    pairs=[];creators={}
    for mint,creator in sorted(universe.items()):
        a=_paired_outcome(reference,mint);b=_paired_outcome(candidate,mint)
        known=a['net_pnl_lamports'] is not None and b['net_pnl_lamports'] is not None
        difference=int(b['net_pnl_lamports'])-int(a['net_pnl_lamports']) if known else None
        if known:
            if not a['entered'] and b['entered']:
                a['opportunity_cost_lamports']=str(max(0,int(b['net_pnl_lamports'])))
            if not b['entered'] and a['entered']:
                b['opportunity_cost_lamports']=str(max(0,int(a['net_pnl_lamports'])))
        row=dict(mint=mint,creator=creator,reference=a,candidate=b,
            conditional_delta_lamports=str(difference) if difference is not None else None,
            comparison_scope='conditional_same_opportunity_PAPER_cashflows; not realized market quality')
        pairs.append(row);creators.setdefault(creator,[]).append(row)
    groups=[]
    for creator,rows in sorted(creators.items()):
        complete=all(row['conditional_delta_lamports'] is not None for row in rows)
        delta=sum(int(row['conditional_delta_lamports']) for row in rows) if complete else None
        groups.append(dict(creator=creator,mints=len(rows),complete=complete,
            conditional_delta_lamports=str(delta) if delta is not None else None,
            unknown_opportunities=sum(row['conditional_delta_lamports'] is None for row in rows)))
    known=[int(row['conditional_delta_lamports']) for row in groups if row['complete']]
    complete=bool(groups) and len(known)==len(groups)
    return dict(opportunity_pairs=pairs,creator_groups=groups,complete_creator_groups=len(known),
        unknown_creator_groups=len(groups)-len(known),all_opportunities_complete=complete,
        total_conditional_delta_lamports=str(sum(known)) if complete else None,
        complete_subset_conditional_delta_lamports=str(sum(known)),
        mean_complete_creator_delta_lamports=(dict(numerator=str(sum(known)),denominator=str(len(known)))
            if known else None),
        complete_group_signs=dict(positive=sum(v>0 for v in known),
            negative=sum(v<0 for v in known),tied=sum(v==0 for v in known)),
        strict_qualified_market_pairs=0,p_value=None,confidence_interval=None,
        market_edge_demonstrated=False,scope='descriptive_creator_clustered_complete_subset_only')


def empty_registry():
    return {'schema':'rugger-shadow-policy-registry-v1','version':0,'current_shadow':None,
        'previous_shadows':[],'evaluated_holdouts':[],'evaluated_windows':[],
        'active_policy_changed':False}


def _registry(value,*,require_windows=True):
    """Validate persisted research state before replay or pointer mutation."""
    def hash_value(item):
        return type(item) is str and len(item)==64 and all(c in '0123456789abcdef' for c in item)
    def pointer(item):
        return item is None or (type(item) is dict
            and set(item)=={'candidate_id','plan_sha256','evaluation_key'}
            and type(item['candidate_id']) is str and bool(item['candidate_id'])
            and hash_value(item['plan_sha256']) and hash_value(item['evaluation_key']))
    if (type(value) is not dict or value.get('schema')!='rugger-shadow-policy-registry-v1'
            or value.get('active_policy_changed') is not False
            or type(value.get('version')) is not int or value['version']<0
            or type(value.get('previous_shadows')) is not list or len(value['previous_shadows'])>16
            or value['version']<len(value['previous_shadows'])
            or not all(pointer(p) for p in value['previous_shadows'])
            or 'current_shadow' not in value or not pointer(value['current_shadow'])
            or (value['version']==0 and (value['current_shadow'] is not None or value['previous_shadows']))
            or type(value.get('evaluated_holdouts')) is not list
            or len(value['evaluated_holdouts'])>128
            or not all(hash_value(h) for h in value['evaluated_holdouts'])
            or len(set(value['evaluated_holdouts']))!=len(value['evaluated_holdouts'])):
        raise ValueError('Explicit bounded shadow registry with monotone integer version required')
    state=deepcopy(value)
    hashes=state['evaluated_holdouts']
    for p in [state['current_shadow'],*state['previous_shadows']]:
        if p is not None and p['evaluation_key'] not in hashes:
            raise ValueError('Shadow pointer requires a retained holdout evaluation')
    if 'evaluated_windows' not in state:
        if hashes:
            if require_windows:raise ValueError('Legacy consumed holdout bounds are unknown; new replay refused')
            return state
        state['evaluated_windows']=[]
    windows=state['evaluated_windows']
    if type(windows) is not list or len(windows)!=len(hashes):
        raise ValueError('Explicit consumed holdout bounds required')
    previous=[]
    for index,window in enumerate(windows):
        if (type(window) is not dict or set(window)!={'development_end_ms','holdout_end_ms','evaluation_key'}
                or any(type(window[name]) is not int for name in ('development_end_ms','holdout_end_ms'))
                or not 0<window['development_end_ms']<window['holdout_end_ms']
                or window['evaluation_key']!=hashes[index]
                or digest({name:window[name] for name in ('development_end_ms','holdout_end_ms')})!=hashes[index]):
            raise ValueError('Invalid consumed holdout bounds or fingerprint')
        start,end=window['development_end_ms'],window['holdout_end_ms']
        if any(start<prior_end and prior_start<end for prior_start,prior_end in previous):
            raise ValueError('Overlapping consumed holdout bounds in registry')
        previous.append((start,end))
    return state


def evaluate_research(corpus,plan,*,registry=None):
    """Use one unchanged native ledger implementation per isolated candidate arm.

    Smaller budgets need their own retained quote contexts. No quote is scaled,
    absent/unliquidated positions stay incomplete, and historical prices crossing
    the development boundary cannot close a development trade.
    """
    from bot import p4_experiment as p4
    plan_hash=_validate_plan(plan)
    if type(corpus) is not dict or len(corpus.get('frames',[]))>plan['maximum_frames']:
        raise ValueError('Corpus exceeds the registered work budget')
    protocol={key:plan[key] for key in ('registered_at_ms','development_end_ms')}
    protocol['policy_sha256']=p4._hash(p4.POLICY)
    assignments=p4._validate(corpus,protocol)
    registry=_registry(empty_registry() if registry is None else registry)
    # Altering a future price must not unlock another look at the same window.
    key=digest({name:plan[name] for name in ('development_end_ms','holdout_end_ms')})
    if key in registry['evaluated_holdouts']:raise ValueError('This frozen holdout was already evaluated')
    if any(plan['development_end_ms']<window['holdout_end_ms']
            and window['development_end_ms']<plan['holdout_end_ms']
            for window in registry['evaluated_windows']):
        raise ValueError('This holdout overlaps a consumed evaluation window')
    if len(registry['evaluated_holdouts'])>=128:raise ValueError('Bounded research registry is full')
    bounded=deepcopy(corpus)
    bounded['frames']=[f for f in corpus['frames'] if f['available_at_ms']<plan['holdout_end_ms']]
    api=p4._api();development=[]
    def replay(candidate,split,*,fee_multiplier=1,decision_delay_ms=0):
        delayed=dict(bounded,frames=[f for f in bounded['frames']
            if f['available_at_ms']+decision_delay_ms<plan['holdout_end_ms']])
        run=p4._run_arm(delayed,assignments,candidate['strategy'],split,fee_multiplier=fee_multiplier,
            decision_delay_ms=decision_delay_ms,development_end_ms=plan['development_end_ms'],api=api,
            research_overrides=candidate['overrides'],
            research_exit_horizon_ms=plan.get('research_exit_horizon_ms'))
        return {'candidate':deepcopy(candidate),'run':run,'metrics':_objective(run)}
    for candidate in plan['candidates']:development.append(replay(candidate,'development'))
    selected=[]
    for strategy in p4.POLICY['strategies']:
        eligible=[r for r in development if r['candidate']['strategy']==strategy and r['metrics']['eligible']]
        if eligible:
            selected.append(sorted(eligible,key=lambda r:(-r['metrics']['objective'],r['candidate']['id']))[0]['candidate'])
    # Freeze these IDs before looking at any holdout outcome. Baselines are
    # retained for a reviewer even if a different candidate was selected.
    frozen_ids=[c['id'] for c in selected]
    comparison={c['id']:c for c in selected}
    comparison.update({c['id']:c for c in plan['candidates'] if c['id'].endswith(':baseline')})
    holdout=[replay(c,'validation') for c in comparison.values()]
    paired=None
    if 'paired_validation' in plan:
        design=plan['paired_validation'];universe={f['mint']:f['creator'] for f in bounded['frames']
            if assignments[f['mint']]=='validation'}
        base={row['candidate']['id']:row for row in holdout};scenarios=[];baseline_coverage=[]
        def summary(run):
            fields=('entered_positions','closed_positions','unentered_candidates',
                'known_modeled_extra_costs_lamports','full_extra_costs_lamports',
                'qualification_failures','exit_attempts','max_realized_drawdown',
                'portfolio_pnl_sol','all_entered_positions_liquidated')
            return {name:run[name] for name in fields}
        for fee in design['sensitivity_fee_multipliers']:
            for delay in design['sensitivity_decision_delays_ms']:
                arms=base if (fee,delay)==(1,0) else {
                    candidate['id']:replay(candidate,'validation',fee_multiplier=fee,decision_delay_ms=delay)
                    for candidate in comparison.values()}
                for identifier,arm in arms.items():
                    if identifier.endswith(':baseline'):
                        baseline_coverage.append(dict(reference_id=identifier,fee_multiplier=fee,
                            decision_delay_ms=delay,summary=summary(arm['run']),
                            coverage=_paired_holdout(arm['run'],arm['run'],universe),
                            scope='reference_coverage_only; self_delta_is_not_a_quality_comparison'))
                for candidate in selected:
                    reference_id=candidate['strategy']+':baseline'
                    a=arms[reference_id]['run'];b=arms[candidate['id']]['run']
                    measure=_paired_holdout(b,a,universe)
                    blockers=['independent_market_evidence_not_audited']
                    if corpus['data_kind']=='synthetic':blockers.append('synthetic_outcomes_only')
                    if measure['complete_creator_groups']<design['minimum_complete_creator_groups']:
                        blockers.append('insufficient_complete_creator_groups')
                    if not measure['all_opportunities_complete']:blockers.append('unknown_or_unliquidated_opportunities')
                    scenarios.append(dict(candidate_id=candidate['id'],reference_id=reference_id,
                        fee_multiplier=fee,decision_delay_ms=delay,initial_capital_lamports='10000000000',
                        identical_observation_universe=True,reference_summary=summary(a),
                        candidate_summary=summary(b),paired=measure,inference_blockers=blockers,
                        familywise_claim_allowed=False,promotion_allowed=False))
        paired=dict(schema='rugger-paired-policy-validation-v1',design=deepcopy(design),
            development_frozen_candidate_ids=list(frozen_ids),
            selection_uses_sensitivities=False,scenarios=scenarios,baseline_coverage=baseline_coverage,
            possible_hypotheses=24,actual_frozen_candidate_comparisons=len(selected),
            condition_scenarios=4,creator_independence_verified=False,
            multiple_testing_claim='registered Bonferroni allocation; inference blocked, no significance claim',
            market_winner=None,promotion_allowed=False)
    registry['evaluated_holdouts'].append(key)
    registry['evaluated_windows'].append(dict(development_end_ms=plan['development_end_ms'],
        holdout_end_ms=plan['holdout_end_ms'],evaluation_key=key))
    creators={f['creator'] for f in bounded['frames'] if assignments[f['mint']]=='validation'}
    unresolved=['independent_market_economic_cycles_not_verified','production_activation_not_authorized']
    if corpus['data_kind']=='synthetic':unresolved.append('synthetic_results_only')
    if len(creators)<plan['minimum_validation_creator_groups']:unresolved.append('insufficient_validation_creator_groups')
    if any(not r['metrics']['eligible'] for r in holdout):unresolved.append('holdout_missing_or_unliquidated_outcomes')
    report=dict(schema='rugger-policy-research-report-v1',plan_sha256=plan_hash,corpus_sha256=digest(corpus),
        data_kind=corpus['data_kind'],assignments=assignments,development=development,
        frozen_candidate_ids=frozen_ids,freeze_basis='development_only_before_holdout_replay',
        holdout=holdout,holdout_evaluation_key=key,registry=registry,
        validation_creator_groups=len(creators),creator_independence_verified=False,
        promotion_allowed=False,promotion_blockers=unresolved,active_policy_changed=False,
        market_winner=None,network_requests=0,execution_verified=False,
        scope='Structured exploratory optimization; no market-profitability claim')
    if 'research_exit_horizon_ms' in plan:report['research_exit_horizon_ms']=plan['research_exit_horizon_ms']
    if paired is not None:report['paired_validation']=paired
    return report


def choose_shadow(report,candidate_id,registry=None):
    """Versioned experimental pointer only; production state is unreachable."""
    if candidate_id not in report['frozen_candidate_ids']:
        raise ValueError('Candidate was not frozen before validation')
    state=_registry(report['registry'] if registry is None else registry,require_windows=False)
    if (len(state['previous_shadows'])>=16
            or report['holdout_evaluation_key'] not in state['evaluated_holdouts']):
        raise ValueError('A bounded shadow-only registry is required')
    state['previous_shadows'].append(state['current_shadow'])
    state['current_shadow']={'candidate_id':candidate_id,'plan_sha256':report['plan_sha256'],
        'evaluation_key':report['holdout_evaluation_key']}
    state['version']+=1
    return state


def rollback_shadow(registry):
    state=_registry(registry,require_windows=False)
    if not state['previous_shadows']:
        raise ValueError('A previous shadow version is required')
    state['current_shadow']=state['previous_shadows'].pop();state['version']+=1
    return state


def measure_drift(outcomes,*,as_of_ms,split_ms):
    """Past-only, position-level drift groups; unknown outcomes stay counted."""
    if (type(outcomes) is not list or len(outcomes)>5000
            or type(as_of_ms) is not int or type(split_ms) is not int
            or not 0<=split_ms<=as_of_ms):
        raise ValueError('Bounded outcomes and explicit chronological split required')
    seen=set();groups={};missing=0
    for row in outcomes:
        if type(row) is not dict:raise ValueError('Explicit position outcome records required')
        if type(row.get('available_at_ms')) is not int:raise ValueError('Outcome availability required')
        if row['available_at_ms']>as_of_ms:continue
        if row.get('position_id') in seen:raise ValueError('Repeated position would duplicate outcomes')
        seen.add(row.get('position_id'))
        if row.get('economic_qualified') is not True or type(row.get('net_pnl_lamports')) is not int:
            missing+=1;continue
        if not all(type(row.get(k)) is str and row[k] for k in ('position_id','creator','policy_id')):
            raise ValueError('Qualified position identity required')
        period='before' if row['available_at_ms']<split_ms else 'after'
        key=(row['policy_id'],row['creator'],period)
        groups.setdefault(key,[]).append(row['net_pnl_lamports'])
    return {'schema':'rugger-policy-drift-v1','as_of_ms':as_of_ms,'unknown_outcomes':missing,
        'groups':[{'policy_id':p,'creator':c,'period':t,'positions':len(v),
            'net_pnl_lamports':str(sum(v)),'expectancy_lamports':{'numerator':str(sum(v)),'denominator':str(len(v))}}
            for (p,c,t),v in sorted(groups.items())],
        'automatic_policy_change':False,'statistical_drift_proven':False}


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
        parser.error('Explicit retained JSON input and new separate output required')
    data=json.loads(args.input.read_text())
    result=evaluate_research(data['corpus'],data['plan'],registry=data.get('registry'))
    from bot.analyser.artifacts import atomic_write_json
    atomic_write_json(args.output,result,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps({'report':str(args.output),'promotion_allowed':False,'network_requests':0}))


if __name__=='__main__':main()
