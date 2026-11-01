"""Join independently archived finalized Raydium proofs to Helius prospective creators.

No fresh Ed25519 verification: upstream cryptographic proof and local window
hashes are separately archived, so distinguish source-attested from replayed.
No economic outcome, order, quote clock or Master edge is certified.
"""
import argparse
import hashlib
import json
from pathlib import Path


def _sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _hash64(value):
    return type(value) is str and len(value)==64 and all(c in "0123456789abcdef" for c in value)


def reconcile(pinned,prospective):
    if (type(pinned) is not dict or
            pinned.get("schema")!="rugger-pinned-index-creators-finalized-proof-v1"
            or pinned.get("financial_order_submitted") is not False
            or pinned.get("qualified_economic_cycles")!=0
            or type(pinned.get("records")) is not list
            or type(prospective) is not dict
            or prospective.get("schema")!="rugger-cross-campaign-signed-creator-audit-v1"
            or prospective.get("financial_order_submitted") is not False
            or prospective.get("qualified_master_reference_holdout_cycles")!=0
            or prospective.get("market_profitability_verified") is not False
            or type(prospective.get("creator_ids_public")) is not list):
        raise ValueError("strict_readonly_two_source_provenance_required")
    pinned_creators=set()
    signatures=set()
    messages=set()
    pools=set()
    pinned_by_signature={}
    pinned_by_pool={}
    for row in pinned["records"]:
        if row.get("status")!="EXACT_OUTER_SIGNED_CREATION_VERIFIED":
            continue
        match=row.get("signed_outer_creations")
        sig=row.get("signature");digest=row.get("verified_exact_message_sha256")
        creator=row.get("creator");mint=row.get("mint");pool=row.get("pool")
        if (type(match) is not list or len(match)!=1
                or any(match[0].get(k)!=row.get(k) for k in ("creator","mint","pool"))
                or not all(type(x) is str and x for x in (sig,creator,mint,pool))
                or not _hash64(digest)
                or sig in signatures or digest in messages or (mint,pool) in pools):
            raise ValueError("conflicted_pinned_finalized_signed_creation")
        signatures.add(sig);messages.add(digest);pools.add((mint,pool))
        pinned_by_signature[sig]=(creator,mint,pool)
        pinned_by_pool[(mint,pool)]=(creator,sig)
        pinned_creators.add(creator)
    claimed=prospective["creator_ids_public"]
    if (any(type(c) is not str or not c for c in claimed)
            or len(set(claimed))!=len(claimed)
            or len(claimed)!=prospective.get("unique_signed_creator_claims")):
        raise ValueError("prospective_creator_set_not_reconciled")
    new=set(claimed)
    overlap=pinned_creators&new
    # Backwards-compatible absence is explicitly unauditable. New campaign
    # archives MUST provide the source-hashed signature+mint+pool identities
    # for a stronger cross-provider join. These fields are not Ed25519 proof.
    raw_rows=prospective.get("source_signed_creation_rows")
    source_rows_present=raw_rows is not None
    source_by_signature={}
    source_by_pool={}
    if source_rows_present:
        if (type(raw_rows) is not list or len(raw_rows)>500
                or type(prospective.get("unique_signed_creation_signatures")) is not int
                or len(raw_rows)!=prospective["unique_signed_creation_signatures"]):
            raise ValueError("complete_source_signed_creation_identity_rows_required")
        for row in raw_rows:
            if type(row) is not dict or set(row)!={
                    "signature","creator","mint","pool","first_observed_run_id"}:
                raise ValueError("exact_signed_source_identity_required")
            sig=row["signature"];creator=row["creator"]
            mint=row["mint"];pool=row["pool"]
            if (not all(type(x) is str and x and len(x)<=256
                        for x in (sig,creator,mint,pool))
                    or type(row["first_observed_run_id"]) is not int
                    or row["first_observed_run_id"]<=0
                    or sig in source_by_signature):
                raise ValueError("duplicate_or_invalid_signed_source_identity")
            identity=(creator,mint,pool)
            if ((mint,pool) in source_by_pool and
                    source_by_pool[(mint,pool)]!=creator):
                raise ValueError("conflicting_source_creator_for_pool")
            source_by_signature[sig]=identity
            source_by_pool[(mint,pool)]=creator
        if (set(x[0] for x in source_by_signature.values())!=new
                or len(source_by_pool)!=prospective.get("unique_signed_mint_pool_pairs")):
            raise ValueError("signed_source_rows_do_not_reconcile_to_creator_cohort")
        for sig,identity in source_by_signature.items():
            if sig in pinned_by_signature and pinned_by_signature[sig]!=identity:
                raise ValueError("cross_source_signed_signature_identity_conflict")
        for pair,creator in source_by_pool.items():
            if pair in pinned_by_pool and pinned_by_pool[pair][0]!=creator:
                raise ValueError("cross_source_signed_pool_creator_conflict")
    common_signatures=signatures&set(source_by_signature)
    common_pools=pools&set(source_by_pool)
    return dict(schema="rugger-pinned-vs-prospective-creator-overlap-v1",
        pinned_finalized_proof_sha256=_sha(pinned),
        prospective_campaigns_audit_sha256=_sha(prospective),
        pinned_upstream_verified_signed_creator_count=len(pinned_creators),
        prospective_source_claimed_signed_creator_count=len(new),
        overlapping_creator_ids=len(overlap),
        cross_source_signed_creation_identity_rows_available=source_rows_present,
        overlapping_signed_creation_signatures=(len(common_signatures) if source_rows_present else None),
        overlapping_signed_mint_pool_pairs=(len(common_pools) if source_rows_present else None),
        conflicting_signed_creation_identities_refused=True,
        unique_creator_ids_across_two_sources=len(pinned_creators|new),
        pinned_unique_creator_ids=sorted(pinned_creators),
        prospective_unique_creator_ids=sorted(new),
        overlapping_creator_ids_public=sorted(overlap),
        cross_source_identity_matching_is_not_crypto_replay=True,
        independently_replayed_ed25519_proofs_in_this_join=0,
        executable_entry_exit_cycles_verified=0,
        master_minus_reference_net_pnl_lamports=None,
        independent_holdout_profitability_verified=False,
        market_profitability_verified=False,
        financial_order_submitted=False,
        live_ready_to_arm=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pinned",required=True,type=Path)
    p.add_argument("--prospective",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args(argv)
    if len({x.resolve() for x in (a.pinned,a.prospective,a.output)})!=3 or a.output.exists():
        p.error("distinct_input_and_fresh_output_required")
    out=reconcile(json.loads(a.pinned.read_text(encoding="utf8")),
                  json.loads(a.prospective.read_text(encoding="utf8")))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x",encoding="utf8") as file:
        json.dump(out,file,sort_keys=True,indent=2,allow_nan=False)
        file.write("\n")
    print(json.dumps(dict(status=out["schema"],
        pinned_signed_creators=out["pinned_upstream_verified_signed_creator_count"],
        prospective_signed_creator_claims=out["prospective_source_claimed_signed_creator_count"],
        cross_source_creator_overlap=out["overlapping_creator_ids"],
        signed_signature_overlap=out["overlapping_signed_creation_signatures"],
        signed_pool_overlap=out["overlapping_signed_mint_pool_pairs"],
        distinct_creator_claims=out["unique_creator_ids_across_two_sources"],
        independently_replayed_ed25519_proofs=0,
        qualified_master_reference_economic_cycles=0,
        market_profitability_verified=False,financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
