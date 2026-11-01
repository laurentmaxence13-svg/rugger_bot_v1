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
        pinned_creators.add(creator)
    claimed=prospective["creator_ids_public"]
    if (any(type(c) is not str or not c for c in claimed)
            or len(set(claimed))!=len(claimed)
            or len(claimed)!=prospective.get("unique_signed_creator_claims")):
        raise ValueError("prospective_creator_set_not_reconciled")
    new=set(claimed)
    overlap=pinned_creators&new
    return dict(schema="rugger-pinned-vs-prospective-creator-overlap-v1",
        pinned_finalized_proof_sha256=_sha(pinned),
        prospective_campaigns_audit_sha256=_sha(prospective),
        pinned_upstream_verified_signed_creator_count=len(pinned_creators),
        prospective_source_claimed_signed_creator_count=len(new),
        overlapping_creator_ids=len(overlap),
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
        distinct_creator_claims=out["unique_creator_ids_across_two_sources"],
        independently_replayed_ed25519_proofs=0,
        qualified_master_reference_economic_cycles=0,
        market_profitability_verified=False,financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
