"""Three-way archived signed-creator provenance join; no replayed crypto here.

Two pinned Raydium creators were authenticated by an earlier GitHub Actions
run. One Helius historical creator can now be independently replayed against
finalized Solana signed bytes. This join binds source digests and identities,
but does not itself redo Ed25519 verification or prove independent operators.
"""
import argparse
import json
from pathlib import Path

from bot.p3.cross_source_creator_overlap import reconcile, _sha, _hash64

SCHEMA="rugger-three-source-finalized-creator-join-v1"


def join_finalized_creator_proofs(pinned,prospective,replay):
    base=reconcile(pinned,prospective)
    if (type(replay) is not dict
            or replay.get("schema")!="rugger-finalized-campaign-ed25519-replay-v1"
            or replay.get("financial_order_submitted") is not False
            or replay.get("eligible_for_future_registered_holdout") is not False
            or replay.get("exact_lot_executable_buy_sell_cycles")!=0
            or replay.get("net_master_reference_advantage_lamports") is not None
            or type(replay.get("records")) is not list
            or type(prospective.get("source_reports")) is not list
            or type(prospective.get("source_signed_creation_rows")) is not list):
        raise ValueError("strict_archived_readonly_three_source_contract_required")
    source=[x for x in prospective["source_reports"]
            if x.get("source_campaign_sha256")==replay.get("source_campaign_sha256")]
    if len(source)!=1:
        raise ValueError("replayed_campaign_digest_not_in_cross_run_source_set")
    source_run=source[0]["run_id"]
    if (type(source_run) is not int or source_run<=0
            or type(replay.get("signed_creation_claim_signatures")) is not int
            or len(replay["records"])!=replay["signed_creation_claim_signatures"]):
        raise ValueError("replay_claim_denominator_incomplete")
    source_by_sig={x["signature"]:x for x in prospective["source_signed_creation_rows"]}
    verified=set()
    replayed_signatures=set()
    statuses={}
    for row in replay["records"]:
        sig=row.get("signature")
        if type(sig) is not str or sig in replayed_signatures:
            raise ValueError("replay_duplicate_or_invalid_signature")
        replayed_signatures.add(sig)
        origin=source_by_sig.get(sig)
        if (origin is None or origin.get("first_observed_run_id")!=source_run
                or any(origin.get(key)!=row.get(key)
                       for key in ("creator","mint","pool"))):
            raise ValueError("replayed_finalized_identity_not_bound_to_source_campaign")
        status=row.get("status")
        if type(status) is not str:
            raise ValueError("missing_replay_verification_status")
        statuses[status]=statuses.get(status,0)+1
        if status=="EXACT_FINALIZED_ED25519_CREATION_VERIFIED":
            if (not _hash64(row.get("source_confirmed_message_sha256"))
                    or row.get("source_confirmed_message_sha256")!=
                       row.get("independently_verified_finalized_message_sha256")):
                raise ValueError("finalized_signed_message_hash_mismatch")
            verified.add(row["creator"])
    if (len(verified)!=replay.get("independently_verified_finalized_creator_ids")
            or len(replayed_signatures)!=replay["signed_creation_claim_signatures"]):
        raise ValueError("replay_verified_creator_count_or_source_denominator_mismatch")
    pinned_keys=set(base["pinned_unique_creator_ids"])
    claimed=set(base["prospective_unique_creator_ids"])
    if not verified.issubset(claimed):
        raise ValueError("replayed_creator_outside_source_claims")
    overlap=pinned_keys&verified
    return dict(schema=SCHEMA,
        pinned_source_sha256=_sha(pinned),
        prospective_source_sha256=_sha(prospective),
        finalized_replay_source_sha256=_sha(replay),
        replayed_source_campaign_run_id=source_run,
        historical_pinned_upstream_ed25519_creator_keys=len(pinned_keys),
        historical_helius_replayed_ed25519_creator_keys=len(verified),
        replayed_helius_creator_overlap_with_pinned=len(overlap),
        distinct_historical_finalized_ed25519_public_creator_keys=len(pinned_keys|verified),
        public_verified_creator_keys=sorted(pinned_keys|verified),
        unverified_helius_creator_claims=len(claimed-verified),
        replay_status_counts=dict(sorted(statuses.items())),
        cross_artifact_join_replays_ed25519_itself=False,
        source_workflows_replay_ed25519_signatures=True,
        independent_economic_operators_verified=False,
        eligible_for_future_preregistered_holdout=False,
        verified_executable_economic_cycles=0,
        actual_master_reference_net_advantage_lamports=None,
        market_profitability_verified=False,
        financial_order_submitted=False,live_ready_to_arm=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("pinned","prospective","replay","output"):
        p.add_argument("--"+name,required=True,type=Path)
    a=p.parse_args(argv)
    paths=[x.resolve() for x in (a.pinned,a.prospective,a.replay,a.output)]
    if len(set(paths))!=4 or a.output.exists():
        p.error("distinct_immutable_inputs_and_new_output_required")
    out=join_finalized_creator_proofs(
        json.loads(a.pinned.read_text(encoding="utf8")),
        json.loads(a.prospective.read_text(encoding="utf8")),
        json.loads(a.replay.read_text(encoding="utf8")))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x",encoding="utf8") as f:
        json.dump(out,f,sort_keys=True,indent=2,allow_nan=False)
        f.write("\n")
    print(json.dumps(dict(status=SCHEMA,
        historical_ed25519_public_creator_keys=out[
            "distinct_historical_finalized_ed25519_public_creator_keys"],
        future_holdout_eligible=False,qualified_economic_cycles=0,
        financial_order_submitted=False)))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
