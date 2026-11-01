"""Audit the whole public prospective creator campaign funnel offline.

Verify each source window against the publisher's SHA-256, rather than
summing untrusted console counters; never infer profitable or executed trades.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from bot.live.helius_prospective_campaign import SCHEMA, CAPTURE_SCHEMA, _canonical


def funnel(summary, source_windows):
    if (type(summary) is not dict or summary.get("schema")!=SCHEMA
            or type(summary.get("windows")) is not list
            or len(summary["windows"])!=summary.get("windows_requested")
            or len(source_windows)!=len(summary["windows"])
            or summary.get("financial_order_submitted") is not False
            or summary.get("master_net_pnl_lamports") is not None
            or summary.get("live_ready_to_arm") is not False):
        raise ValueError("incomplete_or_unsafe_campaign_summary")
    counts=Counter()
    creator_ids=set()
    seen=set()
    inspected_unique=set()
    signed_signatures=set()
    reasons=Counter()
    windows=[]
    clocked=summary.get("local_capture_clock_is_not_external_git_or_provider_proof")
    if clocked not in (None,True):
        raise ValueError("invalid_local_capture_clock_disclaimer")
    previous_capture_completed_ms=None
    for index,(meta,source) in enumerate(zip(summary["windows"],source_windows)):
        if (type(meta) is not dict or meta.get("window")!=index+1
                or type(source) is not dict or set(source)!={"events","report"}):
            raise ValueError("window_sequence_or_envelope_invalid")
        if clocked is True:
            start=meta.get("capture_started_local_ms")
            end=meta.get("capture_completed_local_ms")
            if (type(start) is not int or type(end) is not int
                    or not 0<start<=end
                    or (previous_capture_completed_ms is not None
                        and start<previous_capture_completed_ms)
                    or meta.get("capture_clock_authentication")!="local_wall_clock_unverified"):
                raise ValueError("local_capture_clock_order_or_provenance_invalid")
            previous_capture_completed_ms=end
        elif any(k in meta for k in ("capture_started_local_ms",
                                     "capture_completed_local_ms",
                                     "capture_clock_authentication")):
            raise ValueError("unregistered_partial_local_capture_clock")
        digest=hashlib.sha256(_canonical(source).encode("utf-8")).hexdigest()
        if digest!=meta.get("source_sha256"):
            raise ValueError("tampered_window_or_wrong_artifact")
        report=source["report"];events=source["events"]
        if (type(report) is not dict or report.get("schema")!=CAPTURE_SCHEMA
            or type(events) is not list or type(report.get("attempts")) is not list
            or report.get("financial_order_submitted") is not False
            or report.get("live_ready_to_arm") is not False
            or report.get("master_net_pnl_lamports") is not None
            or report.get("reference_net_pnl_lamports") is not None):
            raise ValueError("non_readonly_capture_refused")
        window_status=Counter()
        repeats=0
        window_event_ids=set()
        for event in events:
            if type(event) is not dict or type(event.get("signature")) is not str:
                raise ValueError("event_identity_missing")
            if not event["signature"]:
                raise ValueError("empty_event_signature")
            if event["signature"] in window_event_ids:
                raise ValueError("duplicated_event_signature_within_window")
            window_event_ids.add(event["signature"])
            if event["signature"] in seen:
                repeats+=1
            seen.add(event["signature"])
        if len(events)!=meta.get("observed_events") or repeats!=meta.get("repeated_signatures_across_windows"):
            raise ValueError("inconsistent_signature_denominator")
        new_creators=0
        model_count=0
        signed_count=0
        frozen_count=0
        window_inspected=set()
        for attempt in report["attempts"]:
            if type(attempt) is not dict:
                raise ValueError("invalid_attempt")
            signature=attempt.get("signature")
            if type(signature) is not str or not signature:
                raise ValueError("inspected_signature_required")
            if signature not in window_event_ids:
                raise ValueError("inspected_signature_not_in_observed_window")
            if signature in window_inspected:
                raise ValueError("duplicated_inspection_within_window")
            window_inspected.add(signature)
            inspected_unique.add(signature)
            status=attempt.get("status") or "NO_STATUS_RECORDED"
            if type(status) is not str:
                raise ValueError("invalid_status")
            window_status[status]+=1
            launches=attempt.get("signed_outer_creations")
            if launches:
                if type(launches) is not list:
                    raise ValueError("invalid_signed_launch_list")
                signed_count+=len(launches)
                signed_signatures.add(signature)
                for item in launches:
                    if type(item) is not dict or type(item.get("creator")) is not str:
                        raise ValueError("invalid_creator_claim")
                    if item["creator"] not in creator_ids:
                        creator_ids.add(item["creator"]);new_creators+=1
            if type(attempt.get("frozen_pre_S2")) is dict:
                frozen_count+=1
            if "s1_s2_conditional_markout_lamports" in attempt:
                model_count+=1
            for key in ("root_refusal","s2_refusal","finality_refusal","refusal_class"):
                if type(attempt.get(key)) is str:
                    reasons[key+":"+attempt[key]]+=1
        if (len(report["attempts"])!=meta.get("inspected_attempts")
                or signed_count!=meta.get("verified_signed_launch_candidates")
                or frozen_count!=meta.get("frozen_S1_decisions")
                or model_count!=meta.get("conditional_model_markouts")
                or new_creators!=meta.get("newly_observed_creator_claims")):
            raise ValueError("attempt_counters_do_not_reconcile")
        counts.update(window_status)
        windows.append(dict(window=index+1,received=len(events),
            inspected=len(report["attempts"]),
            unique_uninspected_signatures=len(window_event_ids-window_inspected),
            status_counts=dict(sorted(window_status.items())),
            signed_creations=signed_count,frozen_S1=frozen_count,
            conditional_model_markouts=model_count))
    if summary.get("observed_events")!=sum(w["received"] for w in windows):
        raise ValueError("total_events_not_reconciled")
    if summary.get("observed_distinct_creator_claims")!=len(creator_ids):
        raise ValueError("creator_ids_not_reconciled")
    return dict(schema="rugger-prospective-campaign-funnel-v1",
        campaign_sha256=hashlib.sha256(_canonical(summary).encode("utf-8")).hexdigest(),
        local_capture_clock_provided=clocked is True,
        local_capture_clock_independently_authenticated=False,
        windows=windows,
        observed_events=sum(w["received"] for w in windows),
        unique_event_signatures=len(seen),
        unique_inspected_event_signatures=len(inspected_unique),
        uninspected_unique_event_signatures=len(seen-inspected_unique),
        uninspected_events_are_unknown_not_negative=True,
        unique_signed_creation_signature_claims=len(signed_signatures),
        signed_creator_claims_not_independent_crypto_reverification=True,
        verified_signed_creator_claims=len(creator_ids),
        status_counts=dict(sorted(counts.items())),
        refusal_reasons=dict(sorted(reasons.items())),
        source_authentication="integrity_hash_checked_not_independent_rpc_reverified",
        qualified_executable_buy_sell_cycles=0,
        master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
        market_profitability_verified=False,financial_order_submitted=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args(argv)
    if args.summary.resolve()==args.output.resolve():
        parser.error("summary_and_output_must_differ")
    summary=json.loads(args.summary.read_text(encoding="utf-8"))
    prefix=args.summary.name.removesuffix("_summary.json")
    if prefix==args.summary.name:
        parser.error("campaign_summary_file_name_expected")
    windows=[json.loads((args.summary.parent/f"{prefix}_window_{i:02d}.json").read_text(encoding="utf-8"))
             for i in range(1,summary.get("windows_requested",0)+1)]
    report=funnel(summary,windows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(dict(status="PAPER_FUNNEL_AUDITED",observed_events=report["observed_events"],
        verified_signed_creator_claims=report["verified_signed_creator_claims"],
        qualified_economic_cycles=0,financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
