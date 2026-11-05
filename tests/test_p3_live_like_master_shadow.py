"""Actual Master and reference are frozen BEFORE S2 on the same S1 bank.

No signed creation, executable quote clock, or SignalFeatures is synthesized.
Synthetic test banks never establish executable economic cycles.
"""
import pytest

from bot.p3.live_like_master_shadow import (
    freeze_market_shadow,freeze_shadow_candidates)
from bot.p3.store import CaptureStore


def basic(tmp_path):
    path=tmp_path/"shadow.sqlite"
    store=CaptureStore(path,clock_ms=lambda:100000)
    def append(kind,**event):
        return store.append(kind,provenance="synthetic",**event)
    append("checkpoint",received_at_ms=1000,outcome="prospective_prefix_fixed",
           payload={"candidates":[dict(ordinal=0,mint="MINT-A",pool="POOL-A",
                                         creator_claim="PUBLIC-CREATOR-A")]})
    id=append("pool_snapshot",received_at_ms=1100,source_slot=300,mint="MINT-A",
           outcome="observed",payload={"period":"initial"})
    event=next(e for e in store.events() if e["id"]==id)
    row=dict(ordinal=0,mint="MINT-A",pool="POOL-A",creator_claim="PUBLIC-CREATOR-A")
    return store,append,event,row


def test_actual_scorers_run_but_wait_without_real_signal_features(tmp_path):
    store,append,snapshot,row=basic(tmp_path)
    try:
        receipt=freeze_market_shadow(
            row,snapshot,discovered_at_ms=1100,decision_at_ms=101000)
        assert receipt["pre_followup"] is True
        assert receipt["master_action"]!="ENTER"
        assert receipt["reference_action"]!="ENTER"
        actual=receipt["actual_master_reference"]
        assert actual["actual_engines_called_before_outcome"] is True
        assert actual["frozen_pair"]["phase"]=="FROZEN_PRE_OUTCOME"
        assert actual["frozen_pair"]["future_prices_consumed"] is False
        assert actual["financial_order_submitted"] is False
        assert actual["source_signed_creator_verified"] is False
        assert receipt["complete_signal_features_available"] is False
        assert receipt["master_minus_reference_net_lamports"] is None
        assert receipt["simulated_fills"] == 0
    finally:
        store.close()


def test_shadow_checkpoints_precede_followup_and_cannot_be_rewritten(tmp_path):
    store,append,snapshot,row=basic(tmp_path)
    try:
        snap=dict(snapshot,available_at_ms=100000)
        initial={row["mint"]:{"snapshot_observation_id":snapshot["id"]}}
        results=freeze_shadow_candidates(
            store,[row],initial,discovered_at_ms=1100,
            decision_at_ms=101000,append=append)
        assert len(results)==1
        frozen=[e for e in store.events() if e["outcome"]==
                "master_reference_frozen_pre_followup"]
        assert len(frozen)==1
        append("pool_snapshot",received_at_ms=102000,source_slot=301,
               mint=row["mint"],outcome="observed",
               payload={"period":"followup"})
        end=store.events()
        assert frozen[0]["id"]<end[-1]["id"]
        assert frozen[0]["available_at_ms"]<=end[-1]["available_at_ms"]
        assert results[0]["frozen_pair_sha256"]==frozen[0]["payload"]["frozen_pair_sha256"]
    finally:
        store.close()


def test_no_initial_bank_preserves_missing_candidate_in_denominator(tmp_path):
    store,append,snapshot,row=basic(tmp_path)
    try:
        rows=[row,dict(ordinal=1,mint="MINT-B",pool="POOL-B",
                       creator_claim="PUBLIC-CREATOR-B")]
        out=freeze_shadow_candidates(store,rows,{},discovered_at_ms=1100,
                                     decision_at_ms=101000,append=append)
        assert len(out)==2
        assert [x["reason"] for x in out]==[
            "initial_bank_not_available","initial_bank_not_available"]
        assert all(x["engines_called"] is False for x in out)
    finally:
        store.close()


def test_future_or_wrong_mint_bank_rejected(tmp_path):
    store,append,snapshot,row=basic(tmp_path)
    try:
        with pytest.raises(ValueError,match="retained_initial_bank"):
            freeze_market_shadow(row,dict(snapshot,mint="OTHER"),
                discovered_at_ms=1100,decision_at_ms=101000)
        with pytest.raises(ValueError,match="retained_initial_bank"):
            freeze_market_shadow(row,dict(snapshot,available_at_ms=102000),
                discovered_at_ms=1100,decision_at_ms=101000)
        with pytest.raises(ValueError,match="creator_claim_missing"):
            freeze_market_shadow(dict(row,creator_claim=None),snapshot,
                discovered_at_ms=1100,decision_at_ms=101000)
    finally:
        store.close()
