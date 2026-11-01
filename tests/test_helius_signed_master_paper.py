"""Offline integration tests for Helius log -> signed receipt -> Master shadow.

No public network, no API key persistence, no wallet, no synthetic profit.
The no-creation test uses the REAL receipt verifier and signed-bank selector.
"""
import json
from pathlib import Path

import pytest

from bot.live.helius_signed_master_paper import run_pipeline
from bot.live.helius_ws_forward_paper import ReadOnlyLogAudit
from bot.live.readonly_plan import MAINNET_GENESIS


SECRET="TestHeliusOnlyKey1234567890123456"


class FakeRpc:
    instances=[]
    def __init__(self,key,*,max_calls):
        assert key==SECRET
        assert max_calls in (5,10)
        self.count=0
        self.maximum=max_calls
        FakeRpc.instances.append(self)

    def __call__(self,method,params):
        assert method=="getGenesisHash" and params==[]
        self.count+=1
        assert self.count<=self.maximum
        return MAINNET_GENESIS


async def no_creation_observer(seconds,maximum,api_key,*,successful_only):
    assert api_key==SECRET
    assert seconds==15 and maximum==100
    assert successful_only is False
    return ReadOnlyLogAudit(7,4).report(duration_ms=15000,handshake_ms=5),[]


def test_real_verifier_and_real_signed_selector_no_creation_stays_no_trade(tmp_path):
    FakeRpc.instances=[]
    folder=tmp_path/"helius-round"
    summary=run_pipeline(seconds=15,output_dir=folder,api_key=SECRET,
                         observer=no_creation_observer,rpc_factory=FakeRpc)
    assert summary["log_events_retained"]==0
    assert summary["crypto_signed_creation_transactions"]==0
    assert summary["selected_independent_signed_creators"]==0
    assert summary["frozen_S1_decisions"]==0
    assert summary["capture_status"]=="NO_SIGNED_CREATIONS_IN_BOUNDED_CAPTURE"
    assert summary["actual_verification_rpc_calls_used"]==1
    assert summary["actual_bank_rpc_calls_used"]==0
    assert summary["provider_requests_used_upper_bound"]==15
    assert summary["exact_profitability_demonstrated"] is False
    assert summary["financial_order_submitted"] is False
    assert summary["master_net_pnl_lamports"] is None
    assert sorted(p.name for p in folder.iterdir())==[
        "finalized_creation_proof.json","paired_signed_master_paper.json",
        "signed_log_capture.json","summary.json"]
    assert all(SECRET not in path.read_text() for path in folder.iterdir())
    assert json.loads((folder/"summary.json").read_text())==summary
    with pytest.raises(ValueError,match="fresh_unoccupied"):
        run_pipeline(seconds=15,output_dir=folder,api_key=SECRET,
                     observer=no_creation_observer,rpc_factory=FakeRpc)


def test_unverified_creator_never_reaches_strategy(tmp_path):
    seen=[]
    def reject_verifier(*args):
        return dict(status="VERIFICATION_MISSING")
    def strategy(*args):
        seen.append(True)
        raise AssertionError("Must never freeze unsigned decisions")
    with pytest.raises(ValueError,match="invalid_signed_creator_proof"):
        run_pipeline(seconds=15,output_dir=tmp_path/"rejected",
                     api_key=SECRET,observer=no_creation_observer,
                     verifier=reject_verifier,strategy=strategy,rpc_factory=FakeRpc)
    assert seen==[]


def test_wrong_signed_proof_hash_refused_before_market_bank(tmp_path):
    def wrong_verifier(report,events,rpc):
        return dict(status="CAPTURE_VERIFIED_AND_RPC_INSPECTED",
                    source_log_chain_sha256="0"*63+"1",
                    financial_order_submitted=False)
    with pytest.raises(ValueError,match="invalid_signed_creator_proof"):
        run_pipeline(seconds=15,output_dir=tmp_path/"wrong-proof",
                     api_key=SECRET,observer=no_creation_observer,
                     verifier=wrong_verifier,rpc_factory=FakeRpc)


def test_frozen_master_and_reference_cannot_be_promoted_to_fake_profit(tmp_path):
    def verified(report,events,rpc):
        return dict(status="CAPTURE_VERIFIED_AND_RPC_INSPECTED",
                    source_log_chain_sha256=report["signature_ledger_sha256"],
                    financial_order_submitted=False,
                    signed_creation_candidate_transactions=0)
    def liar(*args):
        return dict(status="SIMULATED",observations=[],
                    financial_order_submitted=False,live_ready_to_arm=False,
                    execution_verified=False,
                    master_net_pnl_lamports=900,
                    reference_net_pnl_lamports=0,
                    comparative_master_edge_lamports=900)
    with pytest.raises(ValueError,match="unqualified_trading_or_economic_claim"):
        run_pipeline(seconds=15,output_dir=tmp_path/"liar",
                     api_key=SECRET,observer=no_creation_observer,
                     verifier=verified,strategy=liar,rpc_factory=FakeRpc)


@pytest.mark.parametrize("seconds,key",[(9,SECRET),(46,SECRET),
                                       (15,"COLLE_TA_CLE_ICI"),(15,None)])
def test_invalid_operator_inputs_never_call_provider(tmp_path,seconds,key):
    seen=[]
    async def observer(*args,**kwargs):
        seen.append(True)
        raise AssertionError("network must not be accessed")
    with pytest.raises(ValueError):
        run_pipeline(seconds=seconds,output_dir=tmp_path/"invalid",
                     api_key=key,observer=observer,rpc_factory=FakeRpc)
    assert not seen
