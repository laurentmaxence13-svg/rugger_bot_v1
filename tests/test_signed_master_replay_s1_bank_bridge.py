"""Replay new authentic-S1-bank contract from PRE-S2 frozen inputs.

All observations here are SYNTHETIC fixtures and never real trades. The source
bank builder is mocked identically in the forward scorer and independent
replayer, so we test the hash/replay boundary without RPC, wallets or secrets.
Real on-chain source validation is performed by the separate bounded CI job.
"""
from copy import deepcopy
import json

import pytest

from test_signed_master_causal_replay import (
    signed_s1_campaign, write,
)
from bot.p4.signed_master_causal_replay import replay_public_signed_cohort, _hash
from test_p3_curve_size_grid import bank as fake_bank


def mock_verified_bank(*,analysis,mint,pool,creator,signature,
                       source_slot,received_at_ms,raw_bank_sha256,
                       signed_creation_verified):
    assert signed_creation_verified is True
    assert type(source_slot) is int and type(received_at_ms) is int
    assert len(raw_bank_sha256)==64
    fixture=deepcopy(fake_bank(source_slot,"initial")["payload"]["analysis"]["facts"])
    fixture["pool"]["mint_a"]=mint
    from bot.p3.curve_size_grid import _s1_inputs
    decoded=_s1_inputs(dict(facts=fixture,risk_flags=[]))
    return dict(
        observation_id="signed-s1-"+signature,
        mint=mint,pool=pool,creator=creator,source_slot=source_slot,
        available_at_ms=received_at_ms,
        provenance="retained_rpc_snapshot",
        identity_qualified=True,creation_verified=True,supply_verified=True,
        evidence_tail_hash=raw_bank_sha256,
        pool_state=decoded["pool"],
        fee_rates_ppm=list(decoded["fee_rates_ppm"]),
        base_vault_atomic=decoded["base_vault_atomic"],
        quote_vault_lamports=decoded["quote_vault_lamports"],
        curve_type=0,
        share_fee_rate_ppm=decoded["share_fee_rate_ppm"],
    ),None


def frozen_bank_campaign(tmp_path,monkeypatch):
    monkeypatch.setattr(
        "bot.p3.signed_creation_forward_bank.signed_s1_master_bank",
        mock_verified_bank)
    monkeypatch.setattr(
        "bot.p4.signed_master_causal_replay.signed_s1_master_bank",
        mock_verified_bank)
    folder=signed_s1_campaign(tmp_path,monkeypatch)
    return folder


def rehash_outer_documents(folder,paired):
    window=folder/"window_00"
    write(window/"paired_master_source_shadow.json",paired)
    summary=json.loads((window/"summary.json").read_text())
    summary["artifact_sha256"]["paired_master_source_shadow"]=_hash(paired)
    write(window/"summary.json",summary)
    campaign=json.loads((folder/"campaign_summary.json").read_text())
    campaign["windows"][0]["source_summary_sha256"]=_hash(summary)
    write(folder/"campaign_summary.json",campaign)


def test_new_source_bank_survives_independent_replay_and_real_master_wait(
        tmp_path,monkeypatch):
    folder=frozen_bank_campaign(tmp_path,monkeypatch)
    paired=json.loads((folder/"window_00"/
                       "paired_master_source_shadow.json").read_text())
    observation=paired["observations"][0]
    assert observation["s1_source_bank_bridge_status"] == (
        "SIGNED_CERTIFIED_S1_BANK_RETAINED_FOR_MASTER")
    source=observation["s1_preoutcome_frame"]["bank_state"]
    assert source["identity_qualified"] is True
    assert source["source_slot"]==observation["s1_slot"]
    assert source["evidence_tail_hash"]==observation["s1_raw_bank_sha256"]
    assert source["fee_rates_ppm"]==[2500,10000,5000]
    assert observation["s1_preoutcome_master_decision"]["action"]=="WAIT"
    assert "source_identity_supply_creation_unqualified" not in (
        observation["s1_preoutcome_master_decision"]["reasons"])
    result=replay_public_signed_cohort(folder)
    assert result["status"]=="GENUINE_MASTER_CAUSAL_WAIT_REPRODUCED"
    assert result["genuine_master_S1_decisions_recomputed"]==1
    assert result["master_paper_entries"]==0
    assert result["master_paper_exits"]==0
    assert result["master_net_pnl_lamports"] is None
    assert result["financial_order_submitted"] is False


def test_rehashed_forged_bank_fee_will_not_replay(tmp_path,monkeypatch):
    folder=frozen_bank_campaign(tmp_path,monkeypatch)
    paired=json.loads((folder/"window_00"/
                       "paired_master_source_shadow.json").read_text())
    item=paired["observations"][0]
    item["s1_preoutcome_frame"]["bank_state"]["fee_rates_ppm"]=[0,0,0]
    # Rehash both the frozen frame and outer artifacts to demonstrate that
    # self-signed JSON hashes alone cannot authorize altered financial data.
    item["frozen_decision_before_S2"]["frame_sha256"]=_hash(
        item["s1_preoutcome_frame"])
    rehash_outer_documents(folder,paired)
    with pytest.raises(ValueError,match="unreproducible_original_signed_S1_bank_bridge"):
        replay_public_signed_cohort(folder)


def test_rehashed_forged_identity_boolean_will_not_replay(tmp_path,monkeypatch):
    folder=frozen_bank_campaign(tmp_path,monkeypatch)
    paired=json.loads((folder/"window_00"/
                       "paired_master_source_shadow.json").read_text())
    item=paired["observations"][0]
    item["s1_preoutcome_frame"]["bank_state"]["identity_qualified"]=False
    item["frozen_decision_before_S2"]["frame_sha256"]=_hash(
        item["s1_preoutcome_frame"])
    rehash_outer_documents(folder,paired)
    with pytest.raises(ValueError,match="unreproducible_original_signed_S1_bank_bridge"):
        replay_public_signed_cohort(folder)
