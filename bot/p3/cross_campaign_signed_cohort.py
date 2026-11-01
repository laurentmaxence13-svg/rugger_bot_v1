"""Cross-run Helius LaunchLab cohort audit from immutable PAPER campaign archives.

No RPC, no wallet, no order. Every window is rehashed via the existing funnel.
Creator-level train/holdout assignment uses no outcomes but is applied
RETROSPECTIVELY to these archived runs. It is not a time-anchored precommit.
Only independently replayed finalized receipts can satisfy a verified holdout. A self-asserted flag is never enough.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from bot.p3.prospective_campaign_funnel import funnel


SCHEMA="rugger-cross-campaign-signed-creator-audit-v1"
HOLDOUT_MODULUS=5
HOLDOUT_BUCKET=0


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _text(value,name):
    if type(value) is not str or not value or len(value)>256:
        raise ValueError(name+"_invalid")
    return value


def audit_campaigns(campaigns):
    """Input: ordered (run_id, summary, list_of_window_artifacts) tuples."""
    if type(campaigns) is not list or not 1<=len(campaigns)<=12:
        raise ValueError("bounded_campaign_archive_set_required")
    runs=set()
    signatures={}
    creators={}
    mint_pool={}
    message_hashes={}
    counts=Counter()
    reports=[]
    for run_id,summary,windows in campaigns:
        if type(run_id) is not int or run_id<=0 or run_id in runs:
            raise ValueError("duplicate_or_invalid_campaign_run")
        runs.add(run_id)
        source=funnel(summary,windows)  # verifies every source window SHA
        run_sigs=set()
        run_creator_ids=set()
        run_finalized=set()
        run_provisional=set()
        new_signatures=0
        for w,window in enumerate(windows):
            events=window["events"]
            report=window["report"]
            event_ids={e["signature"] for e in events}
            if len(event_ids)!=len(events):
                raise ValueError("duplicate_signature_within_window")
            for event in events:
                sig=_text(event["signature"],"event_signature")
                if sig in run_sigs:
                    # Existing funnel permits repeats between windows but a
                    # repeated event is NOT a new creation opportunity.
                    counts["within_run_repeated_event"]+=1
                run_sigs.add(sig)
                if sig not in signatures:
                    signatures[sig]=run_id
                    new_signatures+=1
                elif signatures[sig]!=run_id:
                    counts["cross_run_repeated_event"]+=1
            for attempt in report["attempts"]:
                sig=_text(attempt.get("signature"),"attempt_signature")
                if sig not in event_ids:
                    raise ValueError("inspected_signature_not_in_captured_window")
                launches=attempt.get("signed_outer_creations")
                if not launches:
                    continue
                if type(launches) is not list or len(launches)!=1:
                    raise ValueError("ambiguous_signed_launch_not_cohort")
                launch=launches[0]
                if type(launch) is not dict:
                    raise ValueError("signed_launch_not_object")
                creator=_text(launch.get("creator"),"creator")
                mint=_text(launch.get("mint"),"mint")
                pool=_text(launch.get("pool"),"pool")
                if (attempt.get("creator") not in (None,creator)
                        or attempt.get("mint") not in (None,mint)
                        or attempt.get("pool") not in (None,pool)):
                    raise ValueError("attempt_and_signed_identity_disagree")
                if sig in mint_pool and mint_pool[sig]!=(creator,mint,pool):
                    raise ValueError("contradictory_signed_creation_signature")
                mint_pool[sig]=(creator,mint,pool)
                if (mint,pool) in message_hashes and message_hashes[(mint,pool)]!=creator:
                    raise ValueError("contradictory_pool_creator_across_runs")
                message_hashes[(mint,pool)]=creator
                if creator not in creators:
                    # No outcome, quote, future S2 or strategy decision enters
                    # the deterministic split; retrospective != preregistered.
                    bucket=int(hashlib.sha256(creator.encode()).hexdigest(),16)%HOLDOUT_MODULUS
                    creators[creator]=dict(split=("HOLDOUT" if bucket==HOLDOUT_BUCKET
                                                   else "DEVELOPMENT"),
                                           first_seen_run_id=run_id)
                run_creator_ids.add(creator)
                counts["signed_outer_creation_claim_observations"]+=1
                if attempt.get("finality_verified") is True:
                    # This is an upstream assertion tied to the archive, NOT
                    # independent replay of the Ed25519 signed message here.
                    run_finalized.add(creator)
                else:
                    run_provisional.add(creator)
        reports.append(dict(run_id=run_id,source_campaign_sha256=source["campaign_sha256"],
            windows=len(windows),events=source["observed_events"],
            unique_event_signatures=len(run_sigs),
            newly_seen_signatures_across_runs=new_signatures,
            creator_claims=len(run_creator_ids),
            upstream_finality_asserted_creators=len(run_finalized),
            confirmed_only_or_unproven_finality_creators=len(run_provisional),
            inspected_attempts=sum(x["inspected"] for x in source["windows"]),
            frozen_S1=sum(x["frozen_S1"] for x in source["windows"]),
            conditional_model_markouts=sum(x["conditional_model_markouts"] for x in source["windows"])))
    return dict(schema=SCHEMA,source_runs=sorted(runs),
        source_reports=reports,
        total_observed_event_rows=sum(x["events"] for x in reports),
        unique_observed_event_signatures=len(signatures),
        cross_run_repeated_event_observations=counts["cross_run_repeated_event"],
        unique_signed_creator_claims=len(creators),
        unique_signed_mint_pool_pairs=len(message_hashes),
        # Public, source-hashed identities are retained so the independent
        # finalized proof archive can detect a reused signature or pool with
        # a conflicting identity. These are upstream assertions, not a fresh
        # Ed25519 replay and not independently verified wallet ownership.
        unique_signed_creation_signatures=len(mint_pool),
        source_signed_creation_rows=[
            dict(signature=sig,creator=identity[0],mint=identity[1],pool=identity[2],
                 first_observed_run_id=signatures[sig])
            for sig,identity in sorted(mint_pool.items())
        ],
        signed_outer_creation_claim_observations=counts["signed_outer_creation_claim_observations"],
        creator_level_holdout_rule="sha256(creator_pubkey) mod 5 == 0",
        holdout_rule_registered_before_source_observations=False,
        creator_split_counts=dict(sorted(Counter(x["split"] for x in creators.values()).items())),
        creator_split_assignments_sha256=_digest(dict(sorted(creators.items()))),
        creator_ids_public=sorted(creators),
        independently_reverified_finalized_signed_creator_count=0,
        independently_reverified_creator_holdout_count=0,
        qualified_master_reference_holdout_cycles=0,
        holdout_independence_and_coverage_verified=False,
        price_source_clock_verified=False,
        actual_master_net_pnl_lamports=None,
        actual_reference_net_pnl_lamports=None,
        master_minus_reference_net_pnl_lamports=None,
        market_profitability_verified=False,
        financial_order_submitted=False,
        live_ready_to_arm=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--campaign",action="append",required=True,
                   help="RUN_ID:PATH_TO_SUMMARY (windows must be adjacent)")
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args(argv)
    campaigns=[]
    for value in a.campaign:
        try:
            run,filename=value.split(":",1)
            run_id=int(run)
        except (ValueError,TypeError):
            p.error("campaign_must_be_RUN_ID:SUMMARY")
        path=Path(filename)
        summary=json.loads(path.read_text(encoding="utf-8"))
        prefix=path.name.removesuffix("_summary.json")
        if prefix==path.name:
            p.error("campaign_summary_filename_required")
        windows=[json.loads((path.parent/f"{prefix}_window_{i:02d}.json").read_text(encoding="utf-8"))
                 for i in range(1,summary["windows_requested"]+1)]
        campaigns.append((run_id,summary,windows))
    out=audit_campaigns(campaigns)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x",encoding="utf-8") as file:
        json.dump(out,file,sort_keys=True,indent=2,allow_nan=False)
        file.write("\n")
    print(json.dumps(dict(status="CROSS_CAMPAIGN_PAPER_AUDITED",
        source_runs=out["source_runs"],
        unique_event_signatures=out["unique_observed_event_signatures"],
        creator_claims=out["unique_signed_creator_claims"],
        independently_reverified_creators=0,
        qualified_master_reference_holdout_cycles=0,
        market_profitability_verified=False,
        financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
