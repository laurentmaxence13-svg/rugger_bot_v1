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


def make_plan(*,registered_at_ms,development_end_ms,holdout_end_ms):
    times=(registered_at_ms,development_end_ms,holdout_end_ms)
    if any(type(t) is not int or t<=0 for t in times) or not registered_at_ms<development_end_ms<holdout_end_ms:
        raise ValueError('Registration, development and holdout clocks must be ordered')
    return dict(schema='rugger-policy-research-plan-v1',registered_at_ms=registered_at_ms,
        development_end_ms=development_end_ms,holdout_end_ms=holdout_end_ms,
        candidates=candidates(),maximum_candidates=24,maximum_frames=5000,
        objective={'tail_loss_weight':2,'drawdown_capital_weight':1},
        minimum_validation_creator_groups=50,selection='development_only_then_frozen_holdout',
        production_promotion='NEVER; separate independent evidence and authorization required')


def _validate_plan(plan):
    if type(plan) is not dict:raise ValueError('Explicit frozen plan required')
    expected=make_plan(**{key:plan.get(key) for key in (
        'registered_at_ms','development_end_ms','holdout_end_ms')})
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


def empty_registry():
    return {'schema':'rugger-shadow-policy-registry-v1','version':0,'current_shadow':None,
        'previous_shadows':[],'evaluated_holdouts':[],'active_policy_changed':False}


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
    registry=deepcopy(empty_registry() if registry is None else registry)
    if (registry.get('schema')!='rugger-shadow-policy-registry-v1'
            or type(registry.get('evaluated_holdouts')) is not list
            or registry.get('active_policy_changed') is not False):
        raise ValueError('Explicit shadow registry required')
    # Altering a future price must not unlock another look at the same window.
    key=digest({name:plan[name] for name in ('development_end_ms','holdout_end_ms')})
    if key in registry['evaluated_holdouts']:raise ValueError('This frozen holdout was already evaluated')
    if len(registry['evaluated_holdouts'])>=128:raise ValueError('Bounded research registry is full')
    bounded=deepcopy(corpus)
    bounded['frames']=[f for f in corpus['frames'] if f['available_at_ms']<plan['holdout_end_ms']]
    api=p4._api();development=[]
    def replay(candidate,split):
        run=p4._run_arm(bounded,assignments,candidate['strategy'],split,fee_multiplier=1,
            decision_delay_ms=0,development_end_ms=plan['development_end_ms'],api=api,
            research_overrides=candidate['overrides'])
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
    registry['evaluated_holdouts'].append(key)
    creators={f['creator'] for f in bounded['frames'] if assignments[f['mint']]=='validation'}
    unresolved=['independent_market_economic_cycles_not_verified','production_activation_not_authorized']
    if corpus['data_kind']=='synthetic':unresolved.append('synthetic_results_only')
    if len(creators)<plan['minimum_validation_creator_groups']:unresolved.append('insufficient_validation_creator_groups')
    if any(not r['metrics']['eligible'] for r in holdout):unresolved.append('holdout_missing_or_unliquidated_outcomes')
    return dict(schema='rugger-policy-research-report-v1',plan_sha256=plan_hash,corpus_sha256=digest(corpus),
        data_kind=corpus['data_kind'],assignments=assignments,development=development,
        frozen_candidate_ids=frozen_ids,freeze_basis='development_only_before_holdout_replay',
        holdout=holdout,holdout_evaluation_key=key,registry=registry,
        validation_creator_groups=len(creators),creator_independence_verified=False,
        promotion_allowed=False,promotion_blockers=unresolved,active_policy_changed=False,
        market_winner=None,network_requests=0,execution_verified=False,
        scope='Structured exploratory optimization; no market-profitability claim')


def choose_shadow(report,candidate_id,registry=None):
    """Versioned experimental pointer only; production state is unreachable."""
    if candidate_id not in report['frozen_candidate_ids']:
        raise ValueError('Candidate was not frozen before validation')
    state=deepcopy(report['registry'] if registry is None else registry)
    if state.get('active_policy_changed') is not False or len(state.get('previous_shadows',[]))>=16:
        raise ValueError('A bounded shadow-only registry is required')
    state['previous_shadows'].append(state['current_shadow'])
    state['current_shadow']={'candidate_id':candidate_id,'plan_sha256':report['plan_sha256'],
        'evaluation_key':report['holdout_evaluation_key']}
    state['version']+=1
    return state


def rollback_shadow(registry):
    state=deepcopy(registry)
    if state.get('active_policy_changed') is not False or not state.get('previous_shadows'):
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
