"""Strict creator-cluster uncertainty and denominator audit for Rugger PAPER.

All P&L here is CONDITIONAL market-quote PAPER arithmetic, never a fill or
proof of a deployable edge. This module has no I/O, signing, trading, HTTP or
dependency on a wallet. It cannot authorize LIVE and does not promote a policy.

Input records must be a pre-registered, paired set of opportunity x scenario
records. No unobserved exit is imputed; an open position blocks a positive
claim even if its other opportunities profit. Bootstrap resamples *creators*,
not individual trades, to avoid pseudo-independent repeated launches.
"""
import hashlib
import json
import random

SCHEMA="rugger-creator-cluster-paper-evidence-v1"
SCENARIOS=((1,0),(2,0),(1,250),(2,250))
MAX_RECORDS=4000
MIN_CREATORS=50
BOOTSTRAP_DRAWS=2000

def _sha(value):
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,separators=(",",":"),
        ensure_ascii=True,allow_nan=False).encode("utf-8")).hexdigest()

def _digest(value):
    return (type(value) is str and len(value)==64
            and all(c in "0123456789abcdef" for c in value))

def _int(value):
    return type(value) is int and 0<=value<=2**63-1

def _arm(arm):
    if type(arm) is not dict or set(arm)!={
        "action","entry_spend_lamports","exit_receipts_lamports",
        "additional_cost_lamports","exit_status","quote_evidence_sha256"}:
        raise ValueError("explicit_paper_arm_schema_required")
    action=arm["action"];status=arm["exit_status"]
    values=[arm[k] for k in ("entry_spend_lamports",
                            "exit_receipts_lamports","additional_cost_lamports")]
    if any(not _int(v) for v in values):
        raise ValueError("unsigned_atomic_lamport_amounts_required")
    spend,receipts,costs=values
    if (action=="ABSTAIN" and (status!="NO_TRADE" or any(values)
                              or arm["quote_evidence_sha256"] is not None)):
        raise ValueError("abstention_cannot_have_cashflows")
    if action=="BUY" and (status not in ("CLOSED","OPEN") or spend==0
                          or not _digest(arm["quote_evidence_sha256"])):
        raise ValueError("buy_requires_cost_and_quote_provenance")
    if action not in ("ABSTAIN","BUY"):
        raise ValueError("unknown_paper_action")
    # "CLOSED" is only a recorded conditional complete-lot quote, never proof
    # that this strategy could actually obtain this fill.
    return dict(net_lamports=receipts-spend-costs,
                closed=(status in ("CLOSED","NO_TRADE")),
                open=(status=="OPEN"),
                invested_lamports=spend,
                paper_quote_not_actual_fill=action=="BUY")

def _record(value,registered_at_ms):
    fields={"opportunity_id","creator_id","signed_creation_sha256",
            "market_tape_sha256","fee_multiplier","decision_delay_ms",
            "first_seen_at_ms","decision_at_ms","outcome_at_ms",
            "reference","master"}
    if type(value) is not dict or set(value)!=fields:
        raise ValueError("complete_paired_evidence_row_required")
    for key in ("opportunity_id","creator_id"):
        if type(value[key]) is not str or not 1<=len(value[key])<=120:
            raise ValueError("invalid_paper_identity")
    for key in ("signed_creation_sha256","market_tape_sha256"):
        if not _digest(value[key]):
            raise ValueError("missing_signed_creation_or_market_tape_pin")
    fee,delay=value["fee_multiplier"],value["decision_delay_ms"]
    if type(fee) is not int or type(delay) is not int or (fee,delay) not in SCENARIOS:
        raise ValueError("unregistered_fee_delay_scenario")
    seen,decision,outcome=(value[k] for k in
                           ("first_seen_at_ms","decision_at_ms","outcome_at_ms"))
    if (any(not _int(t) for t in (seen,decision,outcome))
            or not registered_at_ms<seen<=decision<outcome
            or decision-seen>300_000):
        raise ValueError("future_leak_or_expired_decision_evidence")
    master,reference=_arm(value["master"]),_arm(value["reference"])
    return dict(opportunity_id=value["opportunity_id"],
                creator_id=value["creator_id"],
                signed_creation_sha256=value["signed_creation_sha256"],
                tape=value["market_tape_sha256"],
                scenario=(fee,delay),
                delta=master["net_lamports"]-reference["net_lamports"],
                master=master,reference=reference)

def _bootstrap_by_creator(groups,seed):
    """2.5th percentile of SUM of creator-level paired net deltas.

    Exact deterministic computation with seeded pseudo-random bootstrap;
    it is descriptive uncertainty for the supplied PAPER proxy, not a
    guarantee, a live execution model, or evidence of causal independence.
    """
    ids=sorted(groups)
    if len(ids)<MIN_CREATORS:return None
    values=[groups[key] for key in ids]
    n=len(values)
    rng=random.Random(seed)
    samples=[]
    for _ in range(BOOTSTRAP_DRAWS):
        samples.append(sum(values[rng.randrange(n)] for __ in range(n)))
    samples.sort()
    return samples[(BOOTSTRAP_DRAWS*25)//1000]

def audit_creator_paper_edge(evidence):
    if (type(evidence) is not dict or set(evidence)!={
            "schema","data_kind","registered_at_ms","registration_sha256",
            "development_creator_ids","full_creation_denominator_observed",
            "receipts_cryptographically_checked","decisions_frozen_before_outcome",
            "rows"} or evidence.get("schema")!=SCHEMA):
        raise ValueError("exact_frozen_paper_cohort_envelope_required")
    if evidence["data_kind"] not in ("synthetic","prospective_market_paper"):
        raise ValueError("data_kind_unrecognized")
    registered=evidence["registered_at_ms"]
    if not _int(registered) or registered==0 or not _digest(evidence["registration_sha256"]):
        raise ValueError("independent_registration_pin_required")
    developers=evidence["development_creator_ids"]
    if (type(developers) is not list or len(developers)>4000
            or any(type(x) is not str or not 1<=len(x)<=120 for x in developers)
            or len(set(developers))!=len(developers)):
        raise ValueError("invalid_development_creator_identity_set")
    if any(type(evidence[key]) is not bool for key in (
            "full_creation_denominator_observed","receipts_cryptographically_checked",
            "decisions_frozen_before_outcome")):
        raise ValueError("explicit_evidence_flags_required")
    rows=evidence["rows"]
    if type(rows) is not list or len(rows)>MAX_RECORDS:
        raise ValueError("bounded_paired_paper_rows_required")
    parsed=[_record(row,registered) for row in rows]
    by_opportunity={}
    by_scenario={s:{} for s in SCENARIOS}
    for row in parsed:
        key=row["opportunity_id"];scenario=row["scenario"]
        if scenario in by_opportunity.setdefault(key,{}):
            raise ValueError("duplicate_opportunity_scenario_falsifies_denominator")
        by_opportunity[key][scenario]=row
        by_scenario[scenario][key]=row
    creators=set()
    missing=0;inconsistent=0
    for items in by_opportunity.values():
        founders={x["creator_id"] for x in items.values()}
        signatures={x["signed_creation_sha256"] for x in items.values()}
        tapes={x["tape"] for x in items.values()}
        if len(founders)!=1 or len(signatures)!=1 or len(tapes)!=1:
            inconsistent+=1
        creators.update(founders)
        if len(items)!=len(SCENARIOS):missing+=1
    overlap=creators.intersection(developers)
    scenario_results={}
    seed_base=int(_sha(evidence),16)
    for index,scenario in enumerate(SCENARIOS):
        records=list(by_scenario[scenario].values())
        groups={}
        for row in records:
            key=row["creator_id"]
            groups[key]=groups.get(key,0)+row["delta"]
        opened=sum(x[arm]["open"] for x in records for arm in ("reference","master"))
        closed=sum(x[arm]["closed"] for x in records for arm in ("reference","master"))
        lower=_bootstrap_by_creator(groups,(seed_base+index) % (2**64))
        scenario_results[str(scenario[0])+"x_"+str(scenario[1])+"ms"]=dict(
            opportunities=len(records),distinct_creators=len(groups),
            total_conditional_delta_lamports=sum(groups.values()),
            clustered_bootstrap_p025_lower_lamports=lower,
            open_arm_positions=opened,closed_or_abstained_arm_positions=closed,
            complete_zero_open=opened==0)
    comparable=(bool(parsed) and len(creators)>=MIN_CREATORS and missing==0
                and inconsistent==0 and not overlap
                and evidence["full_creation_denominator_observed"]
                and evidence["receipts_cryptographically_checked"]
                and evidence["decisions_frozen_before_outcome"])
    positive=(comparable and all(
        x["clustered_bootstrap_p025_lower_lamports"] is not None
        and x["clustered_bootstrap_p025_lower_lamports"]>0
        and x["complete_zero_open"]
        for x in scenario_results.values()))
    # Even positive "prospective_market_paper" is still quote/market-tape
    # counterfactuals, with unknown actual ordering, fills and competition.
    return dict(schema="rugger-strict-creator-cluster-paper-audit-v1",
        status=("CONDITIONAL_PAPER_SIGNAL_FOR_INDEPENDENT_REVIEW"
                if positive and evidence["data_kind"]=="prospective_market_paper"
                else "NO_GO_REAL_PROFITABILITY_NOT_PROVEN"),
        input_provenance=evidence["data_kind"],
        evidence_sha256=_sha(evidence),
        registration_sha256=evidence["registration_sha256"],
        opportunities_in_denominator=len(by_opportunity),
        distinct_creator_claims=len(creators),
        holdout_creator_overlap_count=len(overlap),
        opportunities_missing_scenario=missing,
        opportunities_with_inconsistent_identity_or_tape=inconsistent,
        scenarios=scenario_results,
        conditional_positive_every_scenario=positive,
        independently_authenticated_source_proof=False,
        actual_bot_fills=0,
        has_actual_executable_lot_proof=False,
        statistically_credible_actual_profitability=False,
        requires_forward_execution_and_security_review=True,
        financial_order_submitted=False,
        live_ready_to_arm=False,
        economic_edge_validated=False,
        methodological_limitations=[
            "Creator IDs and signed receipt hashes are input claims, not independently authenticated by this module",
            "Bootstrap assumes observed creators represent the target population",
            "PAPER quote returns do not model actual transaction inclusion, adverse selection or other market participants",
            "Open positions block positive signal; no imputed liquidation proceeds",
            "At least 50 verified independent holdout creators are required for review, not sufficient for LIVE"],
        all_scenarios_registered=[list(s) for s in SCENARIOS])
