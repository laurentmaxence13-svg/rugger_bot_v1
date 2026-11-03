"""Independent PAPER-only Master research intent separated from LIVE admission.

The actual MasterDecisionOrchestrator hard-gates ENTER on at least 50 prior
verified economic cycles and 20 independent creators. PAPER research must be
able to test that hypothesis *before* such history exists, without relaxing
ANY operational or LIVE guard. It therefore freezes the actual scorers'
prefrozen intent, NOT their execution authorization.

Input feature, identity and source clocks are subjected to the existing
freeze_real_master_reference causal checker, which does not independently
authenticate an RPC receipt: upstream on-chain proofs remain mandatory.
This module never submits transactions or claims a real fill.
"""
from bot.master_decision import MasterDecisionOrchestrator
from bot.p4.actual_master_reference_freeze import freeze_real_master_reference
from bot.p4.live_like_paper_ledger import freeze_decision,sha


ENTRY_PAPER_LAMPORTS=100_000_000


def freeze_master_research_paper(frame,history=(),*,reference_strategy="early_sniping"):
    prior=freeze_real_master_reference(frame,history,
        reference_strategy=reference_strategy)
    master=MasterDecisionOrchestrator().evaluate(frame,list(history),
        inventory=None,health=None,capital=None)
    if (master["policy_status"]!="EXPERIMENTAL_SHADOW_NOT_PROMOTED"
            or master["execution_authorized"] is not False
            or master["promotion_allowed"] is not False):
        raise ValueError("unexpected_operational_master_execution")
    candidate_by_strategy={v["strategy"]:v for v in master["alternatives"]}
    priorities=master["decision_evidence"]["frozen_strategy_priority"]
    eligible_intents=[name for name in priorities
        if candidate_by_strategy[name]["entry_intent"] is True]
    master_research_action="ENTER" if eligible_intents else "WAIT"
    ref_action="ENTER" if prior["original_reference_enter_intent"] else "WAIT"
    # In an unverified source frame no action may be treated even as a
    # research PAPER buy. Freeze explicit WAIT for both arms.
    signed=frame.get("signed_creator_verified") is True
    clocked=frame.get("source_clock_verified") is True
    features=type(frame.get("features")) is dict and (
        master["decision_evidence"]["reference_score_intent"] is not None)
    research_source_ready=signed and clocked and features
    if not research_source_ready:
        master_research_action="WAIT"
        ref_action="WAIT"
    case=dict(id="paper-research-"+frame["id"],
        mint=frame["mint"],creator=frame["creator"],pool=frame["pool"],
        source_slot=frame["source_slot"],available_at_ms=frame["available_at_ms"],
        entry_size_lamports=ENTRY_PAPER_LAMPORTS,
        decisions=dict(master=master_research_action,reference=ref_action),
        signed_creator_verified=signed,asof_features_verified=features,
        source_quote_clock_verified=clocked,
        policy_sha256=master["policy_sha256"])
    frozen=freeze_decision(case)
    return dict(schema="rugger-causal-master-research-paper-intents-v1",
        research_freeze=frozen,
        reference_strategy=reference_strategy,
        original_operational_master_action=master["action"],
        provisional_master_research_intent=master_research_action,
        provisional_reference_research_intent=ref_action,
        provisional_master_strategy=eligible_intents[0] if eligible_intents
            and master_research_action=="ENTER" else None,
        selected_paper_entry_budget_lamports=ENTRY_PAPER_LAMPORTS,
        actual_master_policy_sha256=master["policy_sha256"],
        original_master_economic_and_operational_gate_still_enforced=True,
        research_intent_is_not_master_live_approval=True,
        no_executable_price_or_fill_proven=True,
        original_full_master_comparison_receipt_sha256=sha(prior),
        both_intents_frozen_before_future_market_events=True,
        source_authentication_requires_upstream_chain_receipt=True,
        financial_order_submitted=False,
        execution_verified=False,live_ready_to_arm=False,
        master_strategy_profitability_verified=False)
