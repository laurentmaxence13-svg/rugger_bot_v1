"""Freeze the ACTUAL Master and frozen reference scorer over one causal prefix.

The reference scorer only returns a SCORE INTENT; it does not pass the
Master's full operational evidence/capital gates. Never interpret the two as
filled buy orders or an economic strategy comparison. Both engines run before
S2, using the same exact caller-retained feature-frame prefix.
"""
import hashlib
import json

from bot.master_decision import MasterDecisionOrchestrator
from bot.p4_experiment import decide_prefix, POLICY as REFERENCE_POLICY
from bot.p4.paired_research_ledger import freeze_pair


def _digest(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,allow_nan=False,
        separators=(",",":")).encode()).hexdigest()


def freeze_real_master_reference(frame,history=(),*,reference_strategy="early_sniping"):
    if (type(frame) is not dict or type(history) not in (list,tuple)
            or type(reference_strategy) is not str
            or reference_strategy not in REFERENCE_POLICY["strategies"]):
        raise ValueError("bounded_actual_scorer_input_required")
    history=list(history)
    at=frame.get("available_at_ms")
    slot=frame.get("source_slot")
    features_at=frame.get("features_available_at_ms")
    source_clock=frame.get("source_clock_verified")
    signed=frame.get("signed_creator_verified")
    if (type(at) is not int or at<=0 or type(slot) is not int or slot<=0
            or type(features_at) is not int or not 0<features_at<=at
            or type(source_clock) is not bool or type(signed) is not bool
            or type(frame.get("slot_available_at_ms")) is not int
            or frame["slot_available_at_ms"]>at
            or not all(type(frame.get(key)) is str and frame[key]
                       for key in ("id","mint","pool","creator"))
            or len(history)>32):
        raise ValueError("causal_scorer_features_and_identity_required")
    for prior in history:
        if (type(prior) is not dict or type(prior.get("available_at_ms")) is not int
                or prior["available_at_ms"]>=at):
            raise ValueError("future_or_unordered_history_refused")
    # Caller-observed original feature receipt hash is NOT a network signature.
    # No future oracle values may enter the shared frame.
    selected={k:v for k,v in frame.items() if k not in (
        "future_exit","future_S2_price","realized_pnl","postdecision_results")}
    if selected!=frame:
        raise ValueError("postoutcome_features_in_preoutcome_frame")
    master=MasterDecisionOrchestrator().evaluate(frame,history,
        inventory=None,health=None,capital=None)
    ref=decide_prefix(reference_strategy,frame,history,decision_at_ms=at)
    action=master.get("action")
    if action not in ("ENTER","WAIT","NO_TRADE"):
        raise ValueError("unexpected_actual_master_action")
    if type(ref) is not dict or type(ref.get("enter")) is not bool:
        raise ValueError("unqualified_reference_score_intent")
    frame_hash=_digest(dict(frame=frame,history=history))
    freeze=freeze_pair(dict(creator=frame["creator"],mint=frame["mint"],
        pool=frame["pool"],source_slot=slot,asof_ms=at,
        features_available_at_ms=features_at,
        feature_receipt_sha256=frame_hash,
        policy_sha256_master=master["policy_sha256"],
        policy_sha256_reference=_digest(REFERENCE_POLICY),
        master_action={"ENTER":"ENTER","WAIT":"WAIT","NO_TRADE":"REJECT"}[action],
        reference_action="ENTER" if ref["enter"] else "WAIT",
        hypothetical_buy_lamports=100_000_000,
        source_clock_verified=source_clock,signed_creator_verified=signed))
    return dict(schema="rugger-real-engines-frozen-shadow-intents-v1",
        frozen_pair=freeze,
        master_decision_sha256=_digest(master),
        reference_intent_sha256=_digest(ref),
        reference_strategy=reference_strategy,
        reference_decision_scope="scorer_intent_without_operational_admission",
        master_decision_scope="actual_master_shadow_full_evidence_and_capital_gate",
        original_master_action=action,
        original_reference_enter_intent=ref["enter"],
        common_feature_frame_hash=frame_hash,
        actual_engines_called_before_outcome=True,
        no_independent_executable_orders=True,
        source_signed_creator_verified=signed,
        source_provider_price_clock_verified=source_clock,
        prospective_strategy_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)
