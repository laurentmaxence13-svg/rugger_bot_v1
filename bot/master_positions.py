"""Bounded shadow position proposals over the existing atomic PAPER inventory.

This module never settles a leg or changes a frozen entry plan. Quote acceptance
is conditional evidence only: the existing ledger must still check cash,
deduplication, inventory version and atomic persistence before any PAPER credit.
"""
import hashlib
import json
import math
from fractions import Fraction

from bot.p3.accounting import SolFeeBreakdown, InsufficientAccountingData, _fees
from bot.p3.exit_qualification import qualify_inventory_exit
from bot.p3.quotes import _atomic


POLICY = {'schema':'master-position-proposals-v1','max_source_age_ms':5000,
          'deterioration':'negative_60s_momentum_and_observed_sells_exceed_buys',
          'partial_selection':'largest_qualified_exact_partial_quantity',
          'active_policy_changed':False}


class _EvidenceError(ValueError):
    pass


def _integer(value):
    return type(value) is int and value >= 0


def _amount(value, *, zero=True):
    return int(_atomic(value,zero=zero))


def _number(value, *, positive=False):
    try:
        return (type(value) in (int,float) and math.isfinite(value)
                and (not positive or value>0))
    except OverflowError:
        return False


def _frozen_model(frame, inventory):
    model=frame.get('entry_plan',inventory.get('position_model'))
    return model if type(model) is dict else {}


def _features(frame, at, max_age):
    features=frame.get('features');available=frame.get('features_available_at_ms')
    observed=features.get('observed_at') if type(features) is dict else None
    if (type(features) is not dict or not _integer(available) or available>at
            or not _integer(observed) or not 0<=at-observed*1000<=max_age
            or observed*1000>available or features.get('mint')!=frame.get('mint')):
        return None
    for key in ('price_usd','momentum_60s'):
        if features.get(key) is not None and not _number(features[key]):return None
    return features


def _inventory(inventory):
    if type(inventory) is not dict:raise ValueError('inventory_missing')
    acquired=_amount(inventory.get('acquired_atomic'),zero=False)
    remaining=_amount(inventory.get('remaining_atomic'))
    if remaining>acquired:raise ValueError('remaining_exceeds_acquired')
    version=inventory.get('version')
    entry=inventory.get('entry_decision_ms',inventory.get('entry_decision_at_ms'))
    if not _integer(version) or not _integer(entry):raise ValueError('inventory_version_or_entry_time_unknown')
    buy=inventory.get('buy_observation')
    if buy is None:
        encoded=inventory.get('entry_observation_json')
        if type(encoded) is not str or len(encoded)>524288:raise ValueError('entry_observation_missing')
        buy=json.loads(encoded)
    restored=dict(inventory,buy_observation=buy,entry_decision_at_ms=entry,
        basis=inventory.get('inventory_basis',inventory.get('basis')),
        provenance=inventory.get('source_provenance',inventory.get('provenance')))
    return restored,acquired,remaining,version,entry


def _contexts(frame):
    contexts=frame.get('sell_contexts',[])
    result=list(contexts[:8]) if type(contexts) is list else []
    if type(frame.get('sell_context')) is dict:result.insert(0,frame['sell_context'])
    if type(frame.get('inventory_context')) is dict:result.insert(0,frame['inventory_context'])
    return result[:8]


def _exit_value(inventory, context, at, max_age, acquired, remaining, version):
    """Reuse the strict bridge and exact cumulative cost allocation of the book."""
    result=dict(accepted=False,reasons=[],quote_id=None,quantity_atomic=None,
        proceeds_lamports=None,extra_fees_lamports=None,allocated_basis_lamports=None,
        conditional_net_lamports=None,conditional_total_position_net_lamports=None)
    if type(context) is not dict:
        result['reasons']=['exit_context_missing'];return result
    event=context.get('sell_observation')
    if type(event) is dict:result['quote_id']=event.get('id')
    try:
        quantity=_amount(context.get('requested_quantity_atomic'),zero=False)
        if context.get('inventory_version')!=version:
            raise _EvidenceError('inventory_version_changed_or_unknown')
        if quantity>remaining:raise _EvidenceError('requested_exit_exceeds_remaining_inventory')
        previous=inventory.get('last_settlement_ms')
        if previous is not None:
            requested=event.get('payload',{}).get('requested_at_ms') if type(event) is dict else None
            if not _integer(previous) or not _integer(requested) or requested<previous or at<previous:
                raise _EvidenceError('quote_precedes_remaining_inventory')
        verdict=qualify_inventory_exit(inventory,event,requested_quantity_atomic=str(quantity),
            exit_decision_at_ms=at,max_source_age_ms=max_age)
        if not verdict['accepted']:
            result['reasons']=verdict['reasons'];return result
        fee=context.get('fees')
        if type(fee) is dict:
            fee=dict(fee)
            if type(fee.get('failed_attempt_lamports')) is list:
                fee['failed_attempt_lamports']=tuple(fee['failed_attempt_lamports'])
            fee=SolFeeBreakdown(**fee)
        entry_extra,exit_extra,failed=_fees(fee)
        if inventory.get('entry_extra_lamports') is None or entry_extra!=_amount(inventory['entry_extra_lamports']):
            raise _EvidenceError('additional_fees_unknown_or_inconsistent')
        synthetic=inventory.get('provenance')=='synthetic'
        if synthetic != (fee.provenance=='synthetic'):
            raise _EvidenceError('fee_and_inventory_provenance_differ')
        total=_amount(inventory.get('cost_basis_total_lamports'),zero=False)
        if total!=_amount(inventory.get('entry_budget_lamports'),zero=False)+entry_extra:
            raise _EvidenceError('total_cost_basis_not_reconciled')
        old=_amount(inventory.get('cost_basis_remaining_lamports'))
        expected=total-total*(acquired-remaining)//acquired
        if old!=expected:raise _EvidenceError('remaining_cost_basis_not_reconciled')
        new=total-total*(acquired-remaining+quantity)//acquired
        allocated=old-new;extras=exit_extra+sum(failed)
        proceeds=int(verdict['proceeds_lamports']);net=proceeds-extras-allocated
        realized=int(inventory.get('realized_pnl_lamports','0'))
        result.update(accepted=True,quantity_atomic=str(quantity),proceeds_lamports=str(proceeds),
            extra_fees_lamports=str(extras),allocated_basis_lamports=str(allocated),
            conditional_net_lamports=str(net),fee_provenance=fee.provenance,
            conditional_total_position_net_lamports=str(realized+net) if quantity==remaining else None,
            remaining_after_atomic=str(remaining-quantity))
    except _EvidenceError as error:
        result['reasons']=[str(error)]
    except InsufficientAccountingData:
        result['reasons']=['additional_fees_unknown_or_inconsistent']
    except (ValueError,TypeError,KeyError,OverflowError):
        result['reasons']=['exit_cost_inventory_or_quote_evidence_unqualified']
    return result


def evaluate_position_plan(frame, inventory, *, policy=None, health=None):
    """Propose one action using only available facts and the frozen entry plan.

    Frame extends the P4 frame with sell_context(s). Each context must carry the
    persisted inventory version and exact quantity. Optional inventory fields
    position_model, entry_price_usd and peak_price_usd are frozen/read-only trade
    facts; absent price thresholds are never replaced by new defaults.
    """
    if policy is not None and policy!=POLICY:raise ValueError('Unsupported position policy')
    result=dict(schema='master-position-proposal-v1',action='WAIT_FOR_DATA',
        proposed_quantity_atomic=None,quote_quantity_atomic=None,quote_id=None,
        executable_quote_qualified=False,conditional_quote_qualified=False,
        conditional_net_lamports=None,conditional_total_position_net_lamports=None,
        estimated_proceeds_lamports=None,estimated_extra_fees_lamports=None,
        allocated_basis_lamports=None,fee_provenance=None,
        remaining_after_atomic=None,inventory_version=None,source_frame_id=None,
        decision_at_ms=None,reasons=[],quote_refusals=[],risk_metrics={},
        shadow_only=True,promotion_allowed=False,ledger_mutated=False,
        execution_verified=False,execution_guaranteed=False,
        existing_ledger_funding_and_dedup_checks_required=True,
        policy_sha256=hashlib.sha256(json.dumps(POLICY,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    if type(frame) is not dict:return dict(result,reasons=['frame_missing'])
    at=frame.get('available_at_ms');result.update(source_frame_id=frame.get('id'),decision_at_ms=at)
    if not _integer(at):return dict(result,reasons=['decision_time_unknown'])
    blocked=health.get('blocking_reasons',[]) if type(health) is dict else []
    emergency=(type(health) is dict and (health.get('emergency_stop') is True
        or health.get('emergency_stop_requested') is True
        or (type(blocked) in (list,tuple) and 'emergency_stop_or_invalid_stop_state' in blocked)))
    try:inv,acquired,remaining,version,entry=_inventory(inventory)
    except (ValueError,TypeError,KeyError,OverflowError):
        return dict(result,action='EMERGENCY_EXIT' if emergency else 'WAIT_FOR_DATA',reasons=['atomic_inventory_unqualified'])
    result['inventory_version']=version
    if entry>at:return dict(result,reasons=['entry_is_in_future'])
    if inv.get('mint')!=frame.get('mint'):return dict(result,reasons=['position_mint_mismatch'])
    if remaining==0:return dict(result,action='HOLD',proposed_quantity_atomic='0',remaining_after_atomic='0',reasons=['position_already_closed'])
    values=[_exit_value(inv,c,at,POLICY['max_source_age_ms'],acquired,remaining,version) for c in _contexts(frame)]
    result['quote_refusals']=[{'quote_id':v['quote_id'],'reasons':v['reasons']} for v in values if not v['accepted']]
    accepted=[v for v in values if v['accepted']]
    full=next((v for v in accepted if int(v['quantity_atomic'])==remaining),None)
    partial=max((v for v in accepted if int(v['quantity_atomic'])<remaining),
                key=lambda v:int(v['quantity_atomic']),default=None)
    f=_features(frame,at,POLICY['max_source_age_ms']);model=_frozen_model(frame,inv)
    price=f.get('price_usd') if f else None
    reference=frame.get('position_reference')
    reference=reference if type(reference) is dict else {}
    original=reference.get('entry_price',inv.get('entry_price_usd'))
    peak=reference.get('peak_price',inv.get('peak_price_usd'))
    ratio=(Fraction(str(price))/Fraction(str(original))-1
           if _number(price,positive=True) and _number(original,positive=True) else None)
    try:gain=float(ratio) if ratio is not None else None
    except OverflowError:gain=None
    if not _number(gain):gain=None
    result['risk_metrics']={'age_ms':at-entry,'price_return':gain,
        'liquidatable_full_net_lamports':full['conditional_total_position_net_lamports'] if full else None,
        'features_available':f is not None,'entry_policy_present':bool(model)}
    creator_risk=(f is not None and any(_integer(f.get(key)) and f[key]>0 for key in ('dev_sales','relay_transfers')))
    action='HOLD';reasons=['entry_thesis_not_invalidated_by_available_observations'];chosen=None
    if emergency or creator_risk:
        action='EMERGENCY_EXIT';reasons=['operational_emergency' if emergency else 'observed_creator_or_relay_sale_risk']
    elif ratio is not None and _number(model.get('sl_pct'),positive=True) and ratio<=-Fraction(str(model['sl_pct']))/100:
        action='EXIT';reasons=['frozen_stop_loss_reached']
    elif (_number(price,positive=True) and _number(original,positive=True) and _number(peak,positive=True)
          and peak>original and _number(model.get('trailing_stop_pct'),positive=True)
          and Fraction(str(price))<=Fraction(str(peak))*(1-Fraction(str(model['trailing_stop_pct']))/100)):
        action='EXIT';reasons=['frozen_trailing_stop_reached']
    elif _integer(model.get('hold_seconds')) and model['hold_seconds']>0 and at-entry>=model['hold_seconds']*1000:
        action='EXIT';reasons=['frozen_maximum_hold_reached']
    elif ratio is not None and _number(model.get('tp_pct'),positive=True) and ratio>=Fraction(str(model['tp_pct']))/100:
        positive=full is not None and int(full['conditional_total_position_net_lamports'])>0
        action='TAKE_PROFIT' if positive else 'EXIT'
        reasons=['frozen_price_target_and_positive_SOL_net' if positive else 'frozen_price_target_SOL_profit_unproven']
    elif (full is not None and _integer(model.get('net_take_profit_lamports'))
          and model['net_take_profit_lamports']>0
          and int(full['conditional_total_position_net_lamports'])>=model['net_take_profit_lamports']):
        action='TAKE_PROFIT';reasons=['frozen_net_profit_target_reached']
    elif (f is not None and _number(f.get('momentum_60s')) and f['momentum_60s']<0
          and _integer(f.get('tx_buys_5m')) and _integer(f.get('tx_sells_5m'))
          and f['tx_sells_5m']>f['tx_buys_5m']):
        action='REDUCE' if partial else 'EXIT' if full else 'WAIT_FOR_DATA'
        reasons=['observed_momentum_and_flow_deterioration'];chosen=partial if partial else full
    elif (f is None or not model or full is None
          or (type(health) is dict and health.get('allow_new_entries') is False)):
        action='WAIT_FOR_DATA';reasons=['position_observations_stale_missing_or_source_unhealthy']
    if action in ('EMERGENCY_EXIT','EXIT','TAKE_PROFIT'):chosen=full
    if action in ('EMERGENCY_EXIT','EXIT','TAKE_PROFIT'):
        result['proposed_quantity_atomic']=str(remaining)
    if chosen is not None and action in ('EMERGENCY_EXIT','EXIT','TAKE_PROFIT','REDUCE'):
        result.update(proposed_quantity_atomic=chosen['quantity_atomic'],quote_quantity_atomic=chosen['quantity_atomic'],
            quote_id=chosen['quote_id'],conditional_quote_qualified=True,executable_quote_qualified=True,
            conditional_net_lamports=chosen['conditional_net_lamports'],
            conditional_total_position_net_lamports=chosen['conditional_total_position_net_lamports'],
            estimated_proceeds_lamports=chosen['proceeds_lamports'],
            estimated_extra_fees_lamports=chosen['extra_fees_lamports'],
            allocated_basis_lamports=chosen['allocated_basis_lamports'],fee_provenance=chosen['fee_provenance'],
            remaining_after_atomic=chosen['remaining_after_atomic'])
    elif action in ('EMERGENCY_EXIT','EXIT','TAKE_PROFIT'):
        reasons.append('full_exit_quote_unqualified_or_unavailable')
    return dict(result,action=action,reasons=reasons)
