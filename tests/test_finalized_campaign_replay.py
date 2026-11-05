"""Offline falsification of bounded historical finalized-creation replay.

The stubbed proof exercises the join only. Real Ed25519 signature verification
is delegated to the existing signed_receipt_proof in production.
"""
import json
import pytest

from bot.live.helius_prospective_campaign import campaign, CAPTURE_SCHEMA
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.finalized_campaign_replay import replay_finalized_campaign


def archive(tmp_path,*,same_creator=False):
    root=tmp_path
    p=root/"bot/live";p.mkdir(parents=True)
    (p/"helius_early_signed_s1s2.py").write_text("# fixture")
    n=[0]
    async def capture(*,seconds,max_events):
        n[0]+=1
        i=n[0]
        sig=f"sig{i}";creator="creator1" if same_creator else f"creator{i}"
        event=dict(signature=sig,slot=100+i)
        attempt=dict(signature=sig,source_slot=100+i,
            confirmed_message_sha256="a"*64,
            signed_outer_creations=[dict(creator=creator,mint=f"mint{i}",pool=f"pool{i}")])
        report=dict(schema=CAPTURE_SCHEMA,financial_order_submitted=False,
            live_ready_to_arm=False,qualified_economic_cycles=0,
            master_net_pnl_lamports=None,reference_net_pnl_lamports=None,
            forward_log_report=dict(events_received_unique=1),
            attempts=[attempt],selected=[dict(signature=sig)])
        return report,[event]
    summary=campaign(windows=2,seconds=10,max_events=20,
        capture=capture,workspace=root,session="signed")
    windows=[json.loads((root/"paper_artifacts"/f"prospective_signed_window_{i:02d}.json").read_text())
             for i in (1,2)]
    return summary,windows


def rpc(method,params):
    if method=="getGenesisHash":
        return MAINNET_GENESIS
    if method=="getTransaction":
        return dict(signature=params[0])
    raise AssertionError("unexpected RPC method")


def verified_proof(raw,sig,slot,call,*,commitment):
    assert commitment=="finalized"
    i=int(sig[-1])
    return dict(message_sha256="a"*64,launches=[dict(
        creator=f"creator{i}",mint=f"mint{i}",pool=f"pool{i}")])


def test_two_finalized_ed25519_proof_joins_do_not_certify_asof_pnl(tmp_path):
    summary,windows=archive(tmp_path)
    calls=[]
    def bounded(method,params):
        calls.append(method)
        return rpc(method,params)
    x=replay_finalized_campaign(summary,windows,bounded,proof=verified_proof)
    assert calls==["getGenesisHash","getTransaction","getTransaction"]
    assert x["source_total_observed_event_signatures"]==2
    assert x["independently_verified_finalized_creator_ids"]==2
    assert x["signed_creation_claim_signatures"]==2
    assert x["eligible_for_future_registered_holdout"] is False
    assert x["cryptographic_replay_does_not_prove_historical_decision_availability"] is True
    assert x["net_master_reference_advantage_lamports"] is None
    assert x["financial_order_submitted"] is False


def test_one_creator_two_tokens_is_one_authenticated_creator(tmp_path):
    summary,windows=archive(tmp_path,same_creator=True)
    def proof(raw,sig,slot,call,*,commitment):
        return dict(message_sha256="a"*64,launches=[dict(
            creator="creator1",mint="mint"+sig[-1],pool="pool"+sig[-1])])
    x=replay_finalized_campaign(summary,windows,rpc,proof=proof)
    assert x["signed_creation_claim_signatures"]==2
    assert x["independently_verified_finalized_creator_ids"]==1


def test_confirmed_finalized_message_mismatch_is_not_a_verified_creation(tmp_path):
    summary,windows=archive(tmp_path)
    def bad(raw,sig,slot,call,*,commitment):
        return dict(message_sha256="b"*64,launches=[dict(
            creator="creator"+sig[-1],mint="mint"+sig[-1],pool="pool"+sig[-1])])
    x=replay_finalized_campaign(summary,windows,rpc,proof=bad)
    assert x["independently_verified_finalized_creator_ids"]==0
    assert all(r["status"]=="CONFIRMED_FINALIZED_MESSAGE_MISMATCH" for r in x["records"])


def test_finalized_creator_mismatch_is_not_a_verified_creation(tmp_path):
    summary,windows=archive(tmp_path)
    def bad(raw,sig,slot,call,*,commitment):
        return dict(message_sha256="a"*64,launches=[dict(
            creator="attacker",mint="mint"+sig[-1],pool="pool"+sig[-1])])
    x=replay_finalized_campaign(summary,windows,rpc,proof=bad)
    assert x["independently_verified_finalized_creator_ids"]==0
    assert all(r["status"]=="FINALIZED_CREATOR_MINT_POOL_MISMATCH" for r in x["records"])


def test_budget_exclusions_remain_visible(tmp_path):
    summary,windows=archive(tmp_path)
    calls=[]
    def bounded(method,params):
        calls.append(method)
        return rpc(method,params)
    x=replay_finalized_campaign(summary,windows,bounded,max_replay=1,
                                proof=verified_proof)
    assert x["bounded_replay_attempts"]==1
    assert x["not_replayed_due_to_budget"]==1
    assert x["records"][1]["status"]=="NOT_REPLAYED_BUDGET"
    assert calls==["getGenesisHash","getTransaction"]


def test_capture_source_slot_mismatch_refused_even_if_source_hash_recomputed(tmp_path):
    import hashlib
    from bot.live.helius_prospective_campaign import _canonical
    summary,windows=archive(tmp_path)
    windows[0]["report"]["attempts"][0]["source_slot"]=999
    summary["windows"][0]["source_sha256"]=hashlib.sha256(
        _canonical(windows[0]).encode()).hexdigest()
    with pytest.raises(ValueError,match="source_slot_not_bound"):
        replay_finalized_campaign(summary,windows,rpc,proof=verified_proof)


def test_untrusted_genesis_cannot_be_accepted(tmp_path):
    summary,windows=archive(tmp_path)
    with pytest.raises(ValueError,match="explicit_mainnet"):
        replay_finalized_campaign(summary,windows,
            lambda method,params: "wrong-network",proof=verified_proof)


def test_ambiguous_signed_creation_claim_refused(tmp_path):
    import hashlib
    from bot.live.helius_prospective_campaign import _canonical
    summary,windows=archive(tmp_path)
    launches=windows[0]["report"]["attempts"][0]["signed_outer_creations"]
    launches.append(dict(launches[0]))
    summary["windows"][0]["verified_signed_launch_candidates"]=2
    summary["windows"][0]["source_sha256"]=hashlib.sha256(
        _canonical(windows[0]).encode()).hexdigest()
    with pytest.raises(ValueError,match="ambiguous_outer_creation_claim"):
        replay_finalized_campaign(summary,windows,rpc,proof=verified_proof)
