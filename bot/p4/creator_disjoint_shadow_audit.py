"""Creator-disjoint, complete-denominator PAPER audit of frozen Master/reference.

This audit accepts frozen pre-outcome decisions, not reconstructed hindsight.
Unknown fees, absent followups, failed exits and still-open inventory cannot be
discarded to inflate a winner's average. An observed quote is not a fill.

Protocol registration must be externally anchored to a Git commit before the
first eligible decision. This offline function checks clocks and SHA chains,
but cannot independently establish Git commit timing or market authenticity.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bot.p4.paired_research_ledger import SCHEMA, score_pair, _sha

REPORT_SCHEMA="rugger-creator-disjoint-shadow-audit-v1"
PROTOCOL_SCHEMA="rugger-creator-disjoint-prospective-protocol-v1"
MIN_HOLDOUT_CREATORS=50
MIN_QUALIFIED_CYCLES=50


def _int(value,name,minimum=0):
    if type(value) is not int or value<minimum or value>10**15:
        raise ValueError(name+"_invalid")
    return value


def _hex(value):
    return type(value) is str and len(value)==64 and all(c in "0123456789abcdef" for c in value)


def _validate_protocol(protocol):
    if (type(protocol) is not dict or set(protocol)!={
        "schema","registered_at_ms","split_salt_sha256",
        "holdout_modulus","holdout_buckets","minimum_holdout_creators",
        "minimum_qualified_cycles","position_horizon_ms","financial_orders_allowed"}
            or protocol["schema"]!=PROTOCOL_SCHEMA
            or not _hex(protocol["split_salt_sha256"])
            or protocol["holdout_modulus"]!=10
            or protocol["holdout_buckets"]!=[0,1,2,3,4,5,6]
            or protocol["minimum_holdout_creators"]<MIN_HOLDOUT_CREATORS
            or protocol["minimum_qualified_cycles"]<MIN_QUALIFIED_CYCLES
            or protocol["financial_orders_allowed"] is not False):
        raise ValueError("complete_frozen_safe_holdout_protocol_required")
    _int(protocol["registered_at_ms"],"registration_clock",1)
    horizon=_int(protocol["position_horizon_ms"],"position_horizon",1)
    if not 1000<=horizon<=600000:
        raise ValueError("bounded_horizon_required")


def _split(creator,protocol):
    h=hashlib.sha256((protocol["split_salt_sha256"]+":"+creator).encode()).digest()
    bucket=int.from_bytes(h[:8],"big")%protocol["holdout_modulus"]
    return "holdout" if bucket in protocol["holdout_buckets"] else "development"


def _frozen_ok(frozen,protocol):
    if (type(frozen) is not dict or frozen.get("schema")!=SCHEMA
            or frozen.get("phase")!="FROZEN_PRE_OUTCOME"
            or frozen.get("financial_order_submitted") is not False
            or frozen.get("future_prices_consumed") is not False
            or type(frozen.get("research_case")) is not dict):
        raise ValueError("immutable_preoutcome_shadow_record_required")
    sha=frozen.get("freeze_sha256")
    if not _hex(sha) or sha!=_sha({k:v for k,v in frozen.items() if k!="freeze_sha256"}):
        raise ValueError("frozen_decision_digest_mismatch")
    case=frozen["research_case"]
    if _int(case.get("asof_ms"),"decision_clock",1)<=protocol["registered_at_ms"]:
        raise ValueError("decision_predates_registered_holdout_protocol")
    if case.get("master_action") not in ("ENTER","WAIT","REJECT") or case.get("reference_action") not in ("ENTER","WAIT","REJECT"):
        raise ValueError("unregistered_decision_action")
    if type(case.get("signed_creator_verified")) is not bool or type(case.get("source_clock_verified")) is not bool:
        raise ValueError("source_proof_flags_required")
    for key in ("creator","mint","pool"):
        if type(case.get(key)) is not str or not case[key]:
            raise ValueError("identity_required")
    return case


def audit_creator_disjoint_shadow(records,protocol):
    """No filtering of unprofitable, missing or unverified cohort members."""
    _validate_protocol(protocol)
    if type(records) is not list or len(records)>5000:
        raise ValueError("bounded_complete_cohort_required")
    seen=set()
    per_creator={}
    last_clock=protocol["registered_at_ms"]
    rows=[]
    for idx,record in enumerate(records):
        if type(record) is not dict or set(record)!={"frozen_pair","followup","engine_trace"}:
            raise ValueError("complete_shadow_cohort_record_required")
        frozen=record["frozen_pair"]
        case=_frozen_ok(frozen,protocol)
        at=case["asof_ms"]
        if at<last_clock:
            raise ValueError("cohort_must_be_chronologically_complete")
        last_clock=at
        identity=(case["mint"],case["pool"])
        if identity in seen:
            raise ValueError("repeated_token_pool_in_independent_cohort")
        seen.add(identity)
        creator=case["creator"]
        group=_split(creator,protocol)
        if creator in per_creator and per_creator[creator]!=group:
            raise ValueError("creator_must_never_cross_holdout_boundary")
        per_creator[creator]=group
        trace=record["engine_trace"]
        if trace is not None:
            if (type(trace) is not dict or trace.get("schema")!="rugger-real-engines-frozen-shadow-intents-v1"
                    or trace.get("actual_engines_called_before_outcome") is not True
                    or trace.get("frozen_pair")!=frozen
                    or trace.get("financial_order_submitted") is not False):
                raise ValueError("engine_trace_must_match_frozen_pair")
        followup=record["followup"]
        scored=score_pair(frozen,followup) if followup is not None else None
        if followup is not None:
            if followup["available_at_ms"]-at>protocol["position_horizon_ms"]:
                raise ValueError("followup_outside_preregistered_horizon")
        actions={arm:case[arm+"_action"] for arm in ("master","reference")}
        values={}
        for arm,action in actions.items():
            if action!="ENTER":
                values[arm]=0
            elif scored is None:
                values[arm]=None
            else:
                values[arm]=scored["master_and_reference"][arm][
                    "conditional_net_if_all_costs_provided_lamports"]
        edge=(values["master"]-values["reference"]
              if values["master"] is not None and values["reference"] is not None
              else None)
        censor=("MISSING_FOLLOWUP" if followup is None else followup["exit_kind"])
        # Preserve the hypothetical entry capital tied up by each arm, even
        # if there is no exit, an exit fails, or costs remain unknown.
        # These are *model* notionals, never wallet debits or actual exposure.
        size=case["hypothetical_buy_lamports"]
        model_notional={arm:size if actions[arm]=="ENTER" else 0
                        for arm in ("master","reference")}
        censored_notional={arm:model_notional[arm] if values[arm] is None else 0
                           for arm in ("master","reference")}
        missing_costs=(followup is not None and censor=="FULL_QUOTE" and
                       (followup["extra_costs_lamports"] is None or
                        followup["failure_costs_lamports"] is None))
        qualified_clock=(case["source_clock_verified"] and case["signed_creator_verified"]
                         and scored is not None and scored["source_quote_time_validated"])
        rows.append(dict(index=idx,creator=creator,mint=case["mint"],pool=case["pool"],
            split=group,decision_at_ms=at,freeze_sha256=frozen["freeze_sha256"],
            master_action=actions["master"],reference_action=actions["reference"],
            engine_adapter_trace_present=trace is not None,
            signed_creator_verified=case["signed_creator_verified"],
            decision_source_clock_self_attested=case["source_clock_verified"],
            quote_source_clock_self_attested=(
                scored["source_quote_time_validated"] if scored else False),
            all_required_clocks_self_attested=bool(qualified_clock),
            followup_class=censor,
            master_hypothetical_entry_notional_lamports=model_notional["master"],
            reference_hypothetical_entry_notional_lamports=model_notional["reference"],
            master_censored_entry_notional_lamports=censored_notional["master"],
            reference_censored_entry_notional_lamports=censored_notional["reference"],
            complete_exit_quote_but_missing_costs=missing_costs,
            conditional_model_master_lamports=values["master"],
            conditional_model_reference_lamports=values["reference"],
            conditional_model_master_minus_reference_lamports=edge,
            independently_authenticated_provider_clock=False,
            actual_fill_verified=False))
    summaries={}
    for split in ("development","holdout"):
        subset=[r for r in rows if r["split"]==split]
        groups={r["creator"] for r in subset}
        complete=[r for r in subset if r["conditional_model_master_minus_reference_lamports"] is not None]
        unknown=[r for r in subset if r not in complete]
        signed={r["creator"] for r in subset if r["signed_creator_verified"]}
        # Complete-case sums are selection-biased if missing followups exist.
        # Never use these sums to certify a winner.
        conditional_complete_case_sum=sum(r["conditional_model_master_minus_reference_lamports"] for r in complete)
        summaries[split]=dict(
            creator_groups_claimed=len(groups),
            # A Boolean in the supplied case is NOT an independently
            # revalidated Ed25519 receipt. Preserve the legacy field for
            # compatibility, but do not use it for the verified threshold.
            creator_groups_signed_verified=len(signed),
            creator_groups_signed_self_attested=len(signed),
            creator_groups_independently_verified=0,
            distinct_pool_pairs=len(subset),frozen_engine_traces=sum(r["engine_adapter_trace_present"] for r in subset),
            cases_with_complete_conditional_model_edge=len(complete),
            cases_with_unknown_model_edge=len(unknown),
            missing_followup=sum(r["followup_class"]=="MISSING_FOLLOWUP" for r in subset),
            failed_exit=sum(r["followup_class"]=="FAILED_EXIT" for r in subset),
            open_unpriced=sum(r["followup_class"]=="OPEN_UNPRICED" for r in subset),
            migrated_no_quote=sum(r["followup_class"]=="MIGRATED_NO_QUOTE" for r in subset),
            complete_exit_quote_but_missing_costs=sum(r["complete_exit_quote_but_missing_costs"] for r in subset),
            master_modelled_entry_notional_lamports=sum(r["master_hypothetical_entry_notional_lamports"] for r in subset),
            reference_modelled_entry_notional_lamports=sum(r["reference_hypothetical_entry_notional_lamports"] for r in subset),
            master_censored_entry_notional_lamports=sum(r["master_censored_entry_notional_lamports"] for r in subset),
            reference_censored_entry_notional_lamports=sum(r["reference_censored_entry_notional_lamports"] for r in subset),
            signed_and_source_clocks_self_attested=sum(r["all_required_clocks_self_attested"] for r in subset),
            conditional_complete_case_only_edge_sum_lamports=conditional_complete_case_sum if complete else None,
            all_cases_conditional_edge_sum_lamports=conditional_complete_case_sum if len(complete)==len(subset) and subset else None,
            all_cases_conditional_edge_mean_lamports=(conditional_complete_case_sum//len(subset)
                if len(complete)==len(subset) and subset else None),
            independently_verified_executed_economic_cycles=0)
    holdout=summaries["holdout"]
    return dict(schema=REPORT_SCHEMA,
        protocol_sha256=_sha(protocol),
        source_records_sha256=_sha(records),
        source_protocol_registration_externally_verified=False,
        complete_creation_denominator_externally_verified=False,
        creator_signature_proofs_independently_revalidated=False,
        creator_split_deterministic_and_disjoint=True,
        total_cases_including_missing=len(rows),
        unique_claimed_creators=len(per_creator),
        unique_token_pool_pairs=len(seen),
        splits=summaries,rows=rows,
        holdout_minimum_claimed_creator_groups_reached=(
            holdout["creator_groups_claimed"]>=protocol["minimum_holdout_creators"]),
        holdout_minimum_signed_self_attested_creator_groups_reached=(
            holdout["creator_groups_signed_self_attested"]>=protocol["minimum_holdout_creators"]),
        holdout_minimum_verified_creator_groups_reached=False,
        independently_verified_executed_economic_cycles=0,
        qualified_holdout_economic_cycles_requirement_reached=False,
        empirical_net_master_advantage_verified=False,
        actual_master_minus_reference_net_pnl_lamports=None,
        financial_order_submitted=False,live_ready_to_arm=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol",type=Path,required=True)
    p.add_argument("--records",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    paths=[x.resolve() for x in (args.protocol,args.records,args.output)]
    if len(set(paths))!=3 or args.output.exists() or args.output.is_symlink():
        p.error("immutable_distinct_inputs_and_new_output_required")
    protocol=json.loads(args.protocol.read_text(encoding="utf8"))
    records=json.loads(args.records.read_text(encoding="utf8"))
    result=audit_creator_disjoint_shadow(records,protocol)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf8") as out:
        json.dump(result,out,indent=2,sort_keys=True,allow_nan=False)
        out.write("\n")
    print(json.dumps(dict(cases=result["total_cases_including_missing"],
        claimed_creators=result["unique_claimed_creators"],
        holdout_signed_creators=result["splits"]["holdout"]["creator_groups_signed_verified"],
        actual_master_edge_lamports=None,live_ready_to_arm=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
