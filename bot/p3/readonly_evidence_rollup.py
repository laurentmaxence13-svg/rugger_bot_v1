"""Deduplicate GitHub PAPER mainnet observations; never infer economic GO.

Consumes per-run public JSON artifacts and verifies each's canonical SHA-256.
Distinct snapshots of the same (pool, creator claim) count only once as a
*claim*, never as verified signed creator identities. A successful S2 quote
is NOT a realized BUY->SELL trade nor a pre-registered Master decision.
"""
import argparse
import hashlib
import json
from pathlib import Path


def _hash(value):
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,separators=(",",":"),
        ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def aggregate_evidence(archives):
    if type(archives) is not list or not 1<=len(archives)<=500:
        raise ValueError("bounded_nonempty_archive_list_required")
    accepted=[]
    seen_hashes=set()
    keyed={}
    cycles=0
    errors=0
    for item in archives:
        if (type(item) is not dict or
                item.get("schema")!="rugger-paper-observation-archive-v1" or
                type(item.get("observation")) is not dict or
                item.get("observation_sha256")!=_hash(item["observation"]) or
                item.get("financial_order_submitted") is not False or
                item.get("live_ready_to_arm") is not False):
            raise ValueError("paper_evidence_archive_integrity_refused")
        fingerprint=item["observation_sha256"]
        if fingerprint in seen_hashes:
            continue
        seen_hashes.add(fingerprint)
        report=item["observation"]
        kind=item.get("kind")
        if kind not in ("active_survivor_cohort","s1_capacity_s2",
                         "historical_launchlab_sample"):
            raise ValueError("unknown_paper_evidence_kind")
        if kind=="active_survivor_cohort":
            rows=report.get("observations",[])
        elif kind=="s1_capacity_s2":
            rows=report.get("results",[])
        else:
            rows=[]
        if type(rows) is not list or len(rows)>100:
            raise ValueError("paper_evidence_rows_unbounded")
        for row in rows:
            if type(row) is not dict:
                raise ValueError("paper_evidence_row_invalid")
            pool=row.get("pool")
            creator=row.get("creator_claim")
            if type(pool) is not str or len(pool)>64 or type(creator) is not str or len(creator)>64:
                raise ValueError("paper_evidence_public_identity_invalid")
            key=(pool,creator)
            x=keyed.setdefault(key,dict(
                pool=pool,creator_claim=creator,
                sample_observations=0,
                hypothetical_S2_sell_quote_observations=0,
                incomplete_or_refused_S2_observations=0,
                signed_creation_proven=False,
                economically_qualified=False))
            x["sample_observations"]+=1
            if ("conditional_sell_lamports" in row or
                    "S2_conditional_sell_lamports" in row):
                x["hypothetical_S2_sell_quote_observations"]+=1
            else:
                x["incomplete_or_refused_S2_observations"]+=1
            # Never treat caller's unverifiable 'passed' flag or test count
            # as real cycle. Signed creation claim requires independent proof.
        cycles+=int(report.get("real_buy_sell_trades",0)) if type(
            report.get("real_buy_sell_trades",0)) is int else 0
        errors+=int(report.get("S2_refusals",0)) if type(
            report.get("S2_refusals",0)) is int else 0
        accepted.append(dict(kind=kind,sha256=fingerprint,
                             github_run_id=item.get("run_id")))
    if cycles!=0:
        raise ValueError("unapproved_live_trades_in_paper_rollup")
    return dict(schema="rugger-unbiased-public-paper-observation-rollup-v1",
        status="EXPLORATORY_ACTIVE_SURVIVORS_NOT_CREATION_COHORT",
        archives_unique_by_hash=len(accepted),
        run_documents=accepted,
        distinct_active_pool_creator_claims=len(keyed),
        creator_signature_verified_count=0,
        independently_qualified_market_creators=0,
        modelled_S2_sell_observation_count=sum(
            r["hypothetical_S2_sell_quote_observations"] for r in keyed.values()),
        S2_refusal_count=sum(
            r["incomplete_or_refused_S2_observations"] for r in keyed.values()),
        results=sorted(keyed.values(),key=lambda r:r["pool"]),
        representative_creation_universe=False,
        realized_buy_sell_cycles=0,
        master_vs_baseline_oos_validated=False,
        economic_edge_validated=False,
        financial_order_submitted=False,
        live_ready_to_arm=False)


def main():
    parser=argparse.ArgumentParser(description="Roll up public read-only evidence JSONs")
    parser.add_argument("files",nargs="+",type=Path)
    paths=parser.parse_args().files
    if len(paths)>500:
        raise SystemExit("too many evidence archives")
    records=[json.loads(p.read_text(encoding="utf-8")) for p in paths]
    print(json.dumps(aggregate_evidence(records),sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
