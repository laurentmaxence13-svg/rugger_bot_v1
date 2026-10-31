"""Bounded, causal PAPER decision orchestration above the existing engine.

This module proposes shadow actions and explains evidence gaps. It does not
settle inventory, change an active strategy, authorize promotion or access I/O.
"""
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from fractions import Fraction
import hashlib
import json
import math

from bot.p4_experiment import POLICY as STRATEGIES, _api, _features, decide_prefix, assess_curve_costs


POLICY = dict(schema='rugger-master-shadow-v1',max_history=32,max_age_ms=5000,
    size_priority_lamports=[1000000000,250000000,100000000,50000000],
    min_qualified_cycles=50,min_creator_groups=20,max_open=3,max_entries_day=20,
    high_volatility_return=0.20,high_volatility_size_cap_lamports=250000000,
    priority_accelerating=['early_sniping','adaptive_hybrid','confirmed_momentum'],
    priority_confirmed=['confirmed_momentum','adaptive_hybrid','early_sniping'],
    priority_other=['adaptive_hybrid','confirmed_momentum','early_sniping'])

# Descriptive hypotheses have their own identity. They do not change the active
# scorer, shadow strategy priority or position execution authority.
CLASSIFICATION_POLICY = dict(schema='rugger-master-regimes-v1',early_max_age_ms=120000,
    overextension_momentum_60s=0.30,high_volatility_return=0.20,
    statuses=['OBSERVED','NOT_OBSERVED','UNKNOWN'],
    primary_priority=['POSSIBLE_MANIPULATION','INSUFFICIENT_LIQUIDITY',
        'OVEREXTENSION_RISK','HIGH_VOLATILITY','MOMENTUM_LOSS','ECONOMICALLY_UNFAVORABLE',
        'INSUFFICIENT_DATA','EARLY_GROWING_ACTIVITY','CONFIRMED_MOMENTUM'])


def _safe(value):
    if is_dataclass(value):return _safe(asdict(value))
    if type(value) is dict:return {str(k):_safe(v) for k,v in value.items()}
    if type(value) in (tuple,list):return [_safe(v) for v in value]
    if value is None or type(value) in (str,bool,int):return value
    if type(value) is float and math.isfinite(value):return value
    raise ValueError('Finite JSON-compatible observations required')


def policy_hash(policy):
    return hashlib.sha256(json.dumps(_safe(policy),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _integer(value):
    return value if type(value) is int and value>=0 else None


def _fees(frame):
    context=frame.get('inventory_context') or frame.get('buy_context')
    fees=context.get('fees') if type(context) is dict else None
    if type(fees) is not dict:return None
    if (fees.get('quote_amounts_net_of_pool_fees') is not True
            or fees.get('extra_fees_exclude_pool_fees') is not True
            or fees.get('provenance') not in ('observed','estimate','synthetic')):return None
    entry,exit=_integer(fees.get('entry_extra_lamports')),_integer(fees.get('exit_extra_lamports'))
    failed=fees.get('failed_attempt_lamports')
    if entry is None or exit is None or type(failed) is not list or any(_integer(n) is None for n in failed):return None
    return dict(total_lamports=entry+exit+sum(failed),provenance=fees['provenance'],
        observed=fees['provenance']=='observed',basis='extras_excluding_curve_fees_already_in_output')


def _evidence(frame,at,policy,sha):
    e=frame.get('research_evidence')
    if type(e) is not dict:return None
    if frame.get('data_kind') not in ('synthetic','market_observation'):return None
    available,ended=_integer(e.get('available_at_ms')),_integer(e.get('training_end_ms'))
    rate=e.get('gross_proceeds_return_lower_bound')
    if (available is None or ended is None or not ended<=available<=at
            or e.get('policy_sha256')!=sha
            or _integer(e.get('qualified_economic_cycles')) is None
            or e['qualified_economic_cycles']<policy['min_qualified_cycles']
            or _integer(e.get('independent_creator_groups')) is None
            or e['independent_creator_groups']<policy['min_creator_groups']
            or type(rate) not in (int,float) or not math.isfinite(rate) or not 0<rate<=10
            or e.get('provenance') not in ('qualified_historical','synthetic_fixture')
            or e.get('data_kind')!=frame.get('data_kind')
            or type(e.get('report_sha256')) is not str or len(e['report_sha256'])!=64
            or any(c not in '0123456789abcdef' for c in e['report_sha256'])):return None
    if e['provenance']=='synthetic_fixture' and frame.get('data_kind')!='synthetic':return None
    return deepcopy(e)


def _fresh_quotes(frame,size,at,max_age,quality):
    contexts=frame.get('size_contexts',{})
    context=contexts.get(str(size)) if type(contexts) is dict else None
    if type(context) is not dict:return False
    buy=context.get('buy_observation');sells=context.get('sell_observations',[])
    wanted=quality['full_sell_observation_ids']
    observations=[buy]+[s for s in sells if type(s) is dict and s.get('id') in wanted]
    if len(observations)<2:return False
    for event in observations:
        if type(event) is not dict:return False
        source=_integer(event.get('source_time_ms'));received=_integer(event.get('received_at_ms'))
        available=_integer(event.get('available_at_ms'));slot=_integer(event.get('source_slot'))
        if (source is None or received is None or available is None or slot is None or slot<=0
                or not source<=received<=available<=at or at-source>max_age):return False
    return True


def _regime_assessment(frame,past,features,base,assessment,size_rows,volatility,*,
                       capital_known,healthy,source_qualified,extras,evidence):
    """Describe available evidence, without claiming causation or a forecast.

    ``past`` has already passed strict identity and as-of feature validation.
    Observed means a documented condition was met, never that manipulation,
    reversal, future liquidity or profitability has been established.
    """
    at=frame['available_at_ms'];rows=[]
    prior=past[-1] if past else None
    prior_features=prior.get('features',{}) if prior else {}
    buyers=_integer(frame.get('independent_buyers')) if features else None
    previous_buyers=_integer(prior.get('independent_buyers')) if prior else None
    momentum=features.momentum_60s if features else None
    previous_momentum=prior_features.get('momentum_60s')
    flags=list(base.risk_flags) if base else []
    ids=[row['id'] for row in [*past,frame] if type(row.get('id')) is str]
    def add(key,condition,reason,metrics):
        rows.append(dict(key=key,status='UNKNOWN' if condition is None else
            'OBSERVED' if condition else 'NOT_OBSERVED',reason_codes=[reason],metrics=metrics,
            source_ids=ids,as_of_ms=at,certainty='descriptive_condition_only'))
    age=at-frame['detected_at_ms'] if type(frame.get('detected_at_ms')) is int else None
    growing=None
    if (features is not None and prior is not None and buyers is not None
            and previous_buyers is not None and type(momentum) in (int,float)
            and type(previous_momentum) in (int,float) and age is not None):
        growing=(0<=age<=CLASSIFICATION_POLICY['early_max_age_ms'] and buyers>=2
            and buyers>previous_buyers and momentum>0 and momentum>previous_momentum)
    add('EARLY_GROWING_ACTIVITY',growing,'early_independent_buyer_count_and_momentum_comparison',
        dict(age_ms=age,independent_buyers=buyers,previous_independent_buyers=previous_buyers,
            momentum_60s=momentum,previous_momentum_60s=previous_momentum))
    confirmed=assessment['strategy_decisions']['confirmed_momentum']
    slot_known=(type(frame.get('source_slot')) is int and frame['source_slot']>0
        and type(frame.get('slot_available_at_ms')) is int and 0<=frame['slot_available_at_ms']<=at)
    confirmation=(bool(confirmed['enter_intent']) if features and slot_known
        and buyers is not None and past else None)
    add('CONFIRMED_MOMENTUM',confirmation,'existing_confirmed_momentum_adapter',
        dict(adapter_reason=confirmed['reason'],independent_buyers=buyers,slot_available=slot_known))
    add('OVEREXTENSION_RISK',None if momentum is None else
        momentum>CLASSIFICATION_POLICY['overextension_momentum_60s'],
        'existing_excessive_60s_momentum_threshold',dict(momentum_60s=momentum,
            threshold=CLASSIFICATION_POLICY['overextension_momentum_60s'],reversal_observed=False))
    model_rows=[r for r in size_rows if r['model_admissible']]
    liquidity=(True if {'liquidite_insuffisante','funding_launchlab_absent'}.intersection(flags)
        else not bool(model_rows) if assessment['bank_available'] and features else None)
    add('INSUFFICIENT_LIQUIDITY',liquidity,'reference_liquidity_veto_or_exact_curve_capacity',
        dict(bank_available=assessment['bank_available'],admissible_model_sizes=len(model_rows),
            scope='conditional_curve_capacity; not_actual_full_exit_execution'))
    add('HIGH_VOLATILITY',None if features is None or volatility is None else
        volatility>CLASSIFICATION_POLICY['high_volatility_return'],'causal_adjacent_price_return_proxy',
        dict(max_absolute_adjacent_return=volatility if features else None,
            threshold=CLASSIFICATION_POLICY['high_volatility_return'],volatility_estimator=False))
    manipulation_flags=[flag for flag in flags if flag in (
        'activite_meme_slot','coordination_wallets_possible','multi_wallet_meme_slot',
        'liens_wallets_observes','concentration_extreme')]
    manipulation=(True if manipulation_flags else False if features and features.behavior_known
        and features.holder_data_known and features.wallet_graph_transactions>0 else None)
    add('POSSIBLE_MANIPULATION',manipulation,'observed_coordination_or_concentration_risk_indicators',
        dict(risk_flags=manipulation_flags,manipulation_confirmed=False,
            absence_of_flags_proves_independence=False))
    losing=None
    if momentum is not None:
        losing=momentum<0 or (type(previous_momentum) in (int,float)
            and previous_momentum>0 and momentum<previous_momentum)
    add('MOMENTUM_LOSS',losing,'negative_or_decelerating_observed_momentum',
        dict(momentum_60s=momentum,previous_momentum_60s=previous_momentum))
    costs_known=(model_rows and all(r['conditional_gain_lower_lamports'] is not None for r in model_rows))
    unfavorable=(all(int(r['conditional_gain_lower_lamports'])<=0 for r in model_rows)
        if costs_known else None)
    add('ECONOMICALLY_UNFAVORABLE',unfavorable,'past_declared_edge_versus_current_modeled_costs',
        dict(size_gain_lower_lamports=[dict(input_lamports=r['input_lamports'],
            value=r['conditional_gain_lower_lamports']) for r in model_rows],
            scope='conditional_inequality; neither_future_return_nor_causal_profit_estimate'))
    missing=[]
    for condition,name in ((features is not None,'features'),(capital_known,'capital'),
            (healthy,'fresh_healthy_operational_data'),(source_qualified,'source_identity_supply_creation'),
            (extras is not None,'additional_costs'),(evidence is not None,'qualified_past_edge')):
        if not condition:missing.append(name)
    if not any(r['exact_full_exit_indicative'] for r in size_rows):missing.append('exact_full_exit_evidence')
    add('INSUFFICIENT_DATA',bool(missing),'required_entry_evidence_completeness',dict(missing=missing))
    observed={r['key'] for r in rows if r['status']=='OBSERVED'}
    primary=next((key for key in CLASSIFICATION_POLICY['primary_priority'] if key in observed),'UNCERTAIN')
    return dict(schema='rugger-master-regime-assessment-v1',primary=primary,situations=rows,
        classification_policy_sha256=policy_hash(CLASSIFICATION_POLICY),
        classification_policy=deepcopy(CLASSIFICATION_POLICY),as_of_ms=at,
        history_frames_used=len(past),classification_controls_entry=False,
        market_regime_certified=False,scope='bounded_explanatory_hypotheses_not_future_outcomes')


class MasterDecisionOrchestrator:
    """Frozen shadow hypothesis; never an authority to bypass existing guards."""
    def __init__(self,policy=None):
        self._policy=deepcopy(POLICY if policy is None else policy)
        if set(self._policy)!=set(POLICY):raise ValueError('Complete frozen master policy required')
        p=self._policy
        if (type(p['max_history']) is not int or not 1<=p['max_history']<=32
                or type(p['max_age_ms']) is not int or not 1<=p['max_age_ms']<=5000
                or p['min_qualified_cycles']<50 or p['min_creator_groups']<20
                or p['max_open']>3 or p['max_entries_day']>20
                or type(p['size_priority_lamports']) is not list
                or not 1<=len(p['size_priority_lamports'])<=4
                or any(type(v) is not int or v not in POLICY['size_priority_lamports'] for v in p['size_priority_lamports'])
                or len(set(p['size_priority_lamports']))!=len(p['size_priority_lamports'])):
            raise ValueError('Bounded policies cannot relax protected evidence or capital limits')
        for name in ('priority_accelerating','priority_confirmed','priority_other'):
            if sorted(p[name])!=sorted(STRATEGIES['strategies']):raise ValueError('Three strategy adapters required')
        self.policy_sha256=policy_hash(p)

    @property
    def policy(self):
        return deepcopy(self._policy)

    def evaluate(self,frame,history=(),*,inventory=None,health=None,capital=None):
        frame=_safe(frame);history=_safe(history)
        health=_safe(health);capital=_safe(capital);inventory=_safe(inventory)
        if type(frame) is not dict or type(history) is not list or len(history)>self.policy['max_history']:
            raise ValueError('One frame and a bounded history prefix required')
        at=_integer(frame.get('available_at_ms'))
        if at is None:raise ValueError('Explicit frame availability required')
        past=[h for h in history if type(h) is dict and all(h.get(k)==frame.get(k)
              for k in ('mint','creator','pool','detected_at_ms'))
              and _integer(h.get('available_at_ms')) is not None and h['available_at_ms']<at]
        past.sort(key=lambda h:h['available_at_ms'])
        api=_api() if type(frame.get('features')) is dict else None
        # Historical feature values may only influence the regime after their
        # own availability and identity checks. A past envelope with future
        # feature availability must not steer today's strategy or size.
        past=[h for h in past if api and _features(h,api,h['available_at_ms'])[0] is not None]
        features,feature_reason=_features(frame,api,at) if api else (None,'features_unknown')
        base=api['decide'](features) if features else None
        assessment=assess_curve_costs(frame,past,api=api)
        extras=_fees(frame);evidence=_evidence(frame,at,self.policy,self.policy_sha256)
        htime=_integer(health.get('observed_at_ms')) if type(health) is dict else None
        healthy=(type(health) is dict and health.get('allow_new_entries') is True and htime is not None
                 and 0<=at-htime<=self.policy['max_age_ms'])
        ctime=_integer(capital.get('observed_at_ms')) if type(capital) is dict else None
        capital_known=(type(capital) is dict and ctime is not None
            and 0<=at-ctime<=self.policy['max_age_ms']
            and all(_integer(capital.get(k)) is not None for k in
            ('available_cash_lamports','open_positions','entries_today'))
            and type(capital.get('daily_loss_limit_reached')) is bool)
        capital_ok=capital_known and (not capital['daily_loss_limit_reached']
            and capital['open_positions']<self.policy['max_open']
            and capital['entries_today']<self.policy['max_entries_day']
            and capital.get('financial_entry_allowed',True) is True)
        blocked=[]
        if not features:blocked.append(feature_reason)
        if base and not base.enter:blocked.append('existing_risk_or_score_veto')
        if not healthy:blocked.append('operational_admission_unhealthy_or_unknown')
        if not capital_ok:blocked.append('capital_or_loss_limits_unavailable_or_reached')
        if extras is None:blocked.append('additional_costs_unknown')
        if evidence is None:blocked.append('qualified_past_edge_evidence_unavailable')
        supplied_bank=frame.get('bank_state')
        bank=supplied_bank if type(supplied_bank) is dict else {}
        source_qualified=assessment['bank_available'] and all(bank.get(k) is True for k in
            ('identity_qualified','supply_verified','creation_verified'))
        if not source_qualified:blocked.append('source_identity_supply_creation_unqualified')
        prices=[]
        for previous in [*past,*([frame] if features is not None else [])]:
            value=previous.get('features',{}).get('price_usd')
            if type(value) in (int,float) and math.isfinite(value) and value>0:prices.append(value)
        returns=[abs(Fraction(str(b))/Fraction(str(a))-1) for a,b in zip(prices,prices[1:])]
        largest=max(returns,default=None)
        # Saturating the report proxy keeps extreme finite observations finite;
        # the high-volatility branch still receives a conservative risk signal.
        volatility=(float(min(largest,Fraction(str(1e308)))) if largest is not None else None)
        buyers=frame.get('independent_buyers')
        independent=type(buyers) is int and buyers>=2
        prior_momentum=past[-1].get('features',{}).get('momentum_60s') if past else None
        momentum=features.momentum_60s if features else None
        accelerating=(independent and type(momentum) in (int,float) and type(prior_momentum) in (int,float)
            and momentum>0 and momentum>prior_momentum)
        if base and not base.enter:regime='RISK_REJECTED'
        elif volatility is not None and volatility>self.policy['high_volatility_return']:regime='HIGH_VOLATILITY'
        elif accelerating:regime='ACCELERATING_WITH_BUYERS'
        elif independent and momentum is not None and momentum>0:regime='OBSERVED_MOMENTUM'
        else:regime='UNCERTAIN'
        preference=self.policy['priority_accelerating' if accelerating else 'priority_confirmed'
            if regime=='OBSERVED_MOMENTUM' else 'priority_other']
        size_rows=[]
        for row in assessment['sizes']:
            model=row['same_state_own_entry_model'];size=int(row['input_lamports'])
            quality=row['provider_quotes']
            quote_known=(quality['full_sell_quoted'] and not quality['source_times_unknown']
                and not quality['source_slots_unknown']
                and _fresh_quotes(frame,size,at,self.policy['max_age_ms'],quality))
            # A copied quote amount is never scaled to a size. Its source clocks
            # still need the retained strict bridge in the execution adapter.
            amount_matches=(quality['projected_quantity_atomic']==model.get('buy_output_atomic'))
            reasons=[]
            if not model['admissible']:reasons.append(model['reason'])
            if not quote_known or not amount_matches:reasons.append('exact_full_exit_evidence_unavailable')
            total=None if extras is None or not model['admissible'] else int(model['round_trip_friction_lamports'])+extras['total_lamports']
            gain=None
            if evidence is not None and total is not None:
                gain=int(Fraction(str(evidence['gross_proceeds_return_lower_bound']))*size)-total
                if gain<=0:reasons.append('past_evidence_does_not_cover_current_costs')
            if capital_known and extras and size+extras['total_lamports']>capital['available_cash_lamports']:
                reasons.append('insufficient_available_cash')
            if regime=='HIGH_VOLATILITY' and size>self.policy['high_volatility_size_cap_lamports']:
                reasons.append('frozen_high_volatility_size_cap')
            size_rows.append(dict(input_lamports=str(size),quantity_atomic=model.get('buy_output_atomic'),
                model_admissible=model['admissible'],curve_friction_lamports=model.get('round_trip_friction_lamports'),
                additional_costs=extras,conditional_total_cost_lamports=None if total is None else str(total),
                conditional_gain_lower_lamports=None if gain is None else str(gain),
                plausible_total_loss_lamports=str(size+(extras['total_lamports'] if extras else 0)) if extras else None,
                loss_basis='total_position_loss_scenario_not_a_probabilistic_bound',
                exact_full_exit_indicative=quote_known and amount_matches,
                reasons=reasons,conditional_eligible=not blocked and not reasons))
        alternatives=[]
        for name in STRATEGIES['strategies']:
            variant=assessment['strategy_decisions'][name]
            alternatives.append(dict(strategy=name,entry_intent=variant['enter_intent'],reason=variant['reason'],
                eligible=variant['enter_intent'] is True and any(r['conditional_eligible'] for r in size_rows),
                uncertainty='unvalidated_shadow_hypothesis; independent_adoption_required'))
        alternatives.append(dict(strategy='NO_TRADE / WAIT',entry_intent=False,eligible=True,
            capital_consumed_lamports='0',reason='abstention_is_always_available'))
        selected=None;chosen=None
        for strategy in preference:
            alternative=next(r for r in alternatives if r['strategy']==strategy)
            if alternative['eligible']:
                for size in self.policy['size_priority_lamports']:
                    candidate=next((r for r in size_rows if int(r['input_lamports'])==size and r['conditional_eligible']),None)
                    if candidate is not None:selected=strategy;chosen=candidate;break
            if selected:break
        action='ENTER' if selected else 'NO_TRADE' if base and not base.enter or capital_known and not capital_ok else 'WAIT'
        if not selected and not blocked:blocked.append('no_strategy_with_admissible_size_and_exit')
        if selected:blocked=['selected_by_frozen_regime_priority','exact_size_cost_and_exit_checks_passed',
            'past_evidence_covers_modeled_current_costs']
        regime_assessment=_regime_assessment(frame,past,features,base,assessment,size_rows,volatility,
            capital_known=capital_known,healthy=healthy,source_qualified=source_qualified,
            extras=extras,evidence=evidence)
        questions=[]
        def question(number,name,status,metrics):
            questions.append(dict(number=number,key=name,status=status,metrics=metrics,
                source_ids=[frame.get('id'),bank.get('observation_id')]))
        question(1,'reliable_recent_data','YES' if features and healthy and source_qualified else 'UNKNOWN',
            dict(feature_reason=feature_reason,health_known=healthy,source_qualified=source_qualified))
        question(2,'eliminatory_risk','YES' if base and base.risk_flags else 'NO' if base else 'UNKNOWN',
            dict(risk_flags=list(base.risk_flags) if base else None,score=base.score if base else None))
        question(3,'independent_activity','YES' if independent else 'NO' if type(buyers) is int else 'UNKNOWN',dict(independent_buyers=buyers))
        question(4,'sustainable_or_manipulated','UNKNOWN',dict(regime=regime,
            causal_return_dispersion_proxy=volatility,descriptive_primary=regime_assessment['primary'],
            manipulation_confirmed=False))
        question(5,'complete_round_trip_cost','YES' if extras and size_rows else 'UNKNOWN',dict(size_costs=size_rows))
        question(6,'full_position_exit','YES' if chosen else 'UNKNOWN',dict(exact_full_exit_sizes=[r['input_lamports'] for r in size_rows if r['exact_full_exit_indicative']]))
        question(7,'break_even_movement','YES' if extras and size_rows else 'UNKNOWN',dict(required_extra_proceeds=[dict(input_lamports=r['input_lamports'],lamports=r['conditional_total_cost_lamports']) for r in size_rows]))
        question(8,'plausible_loss','YES' if extras else 'UNKNOWN',dict(loss_scenarios=[dict(input_lamports=r['input_lamports'],lamports=r['plausible_total_loss_lamports']) for r in size_rows]))
        question(9,'holding_horizon','YES' if base else 'UNKNOWN',dict(reference_hold_seconds=base.hold_seconds if base else None))
        question(10,'admissible_strategy','YES' if selected else 'UNKNOWN',dict(selected=selected,alternatives=alternatives))
        question(11,'early_advantage_over_wait','UNKNOWN',dict(past_evidence_available=evidence is not None,comparison_basis='frozen_regime_priority_not_a_causal_early_vs_wait_profit_proof'))
        question(12,'prefer_abstention','YES' if selected is None else 'NO',dict(reasons=blocked))
        position_plan=None
        if inventory is not None:
            from bot.master_positions import evaluate_position_plan
            position_plan=evaluate_position_plan(frame,inventory,policy=None,health=health)
            action=position_plan['action'];selected=None;chosen=None
        result=dict(schema='rugger-master-shadow-decision-v1',frame_id=frame.get('id'),mint=frame.get('mint'),
            decision_at_ms=at,source_slot=frame.get('source_slot'),policy_sha256=self.policy_sha256,
            policy_status='EXPERIMENTAL_SHADOW_NOT_PROMOTED',action=action,selected_strategy=selected,
            input_lamports=chosen['input_lamports'] if chosen else None,
            quantity_atomic=position_plan.get('proposed_quantity_atomic') if position_plan else chosen['quantity_atomic'] if chosen else None,
            regime=regime,reasons=position_plan['reasons'] if position_plan else blocked,
            regime_assessment=regime_assessment,
            decision_evidence=dict(score=base.score if base else None,
                risk_flags=list(base.risk_flags) if base else None,
                reference_score_intent=base.enter if base else None,
                reference_score_scope='current_scorer_intent_before_ledger_and_operational_admission',
                admissible_strategies=[r['strategy'] for r in alternatives
                    if r['entry_intent'] is True and r['eligible']],
                frozen_strategy_priority=preference,additional_costs=extras,
                additional_costs_unknown=extras is None,
                reference_exit_conditions=({key:getattr(base,key) for key in
                    ('tp_pct','sl_pct','trailing_stop_pct','hold_seconds','cost_bps')} if base else None),
                exit_condition_scope='scorer_plan; positions_use_their_separate_frozen_entry_plan',
                entry_admission_reasons=blocked,decision_action=action,
                position_trigger_reasons=position_plan['reasons'] if position_plan else None,
                features_available_at_ms=frame.get('features_available_at_ms') if features else None,
                as_of_ms=at,financial_execution_authorized=False),
            questions=questions,alternatives=alternatives,size_assessments=size_rows,position_plan=position_plan,
            evidence_basis='caller_retained_artifact_reference; validation_is_not_authentication',
            research_evidence_report_sha256=evidence.get('report_sha256') if evidence else None,
            history_frames_used=len(past),max_history=self.policy['max_history'],max_size_assessments=4,
            context_sha256=policy_hash(frame),promotion_allowed=False,active_policy_changed=False,
            execution_authorized=False,execution_verified=False,ledger_credited=False,strict_economic_cycles=0)
        return _safe(result)


def orchestrate(frame,history=(),*,inventory=None,health=None,capital=None,policy=None):
    return MasterDecisionOrchestrator(policy).evaluate(frame,history,inventory=inventory,health=health,capital=capital)
