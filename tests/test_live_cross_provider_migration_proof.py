"""Cross-provider equality tests are pure and never request actual mainnet."""
from copy import deepcopy
import pytest
from bot.live import cross_provider_migration_proof as cross
from bot.live.readonly_plan import PUBLIC_MAINNET_RPC
from bot.live.public_program_observer import SECONDARY_RPC

class Provider:
    def __init__(self,endpoint):self.endpoint=endpoint

def fake_result():
    return dict(calls_used=5,results=[
        dict(signature=str(x),status="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED",
             slot=400+x,mint="mint",launchlab_pool="old",cpmm_pool="new",
             migration_abi="permissioned_cpmm_2026",signed_message_sha256="a"*64,
             structural_role_sha256="b"*64)
        for x in (1,2)])

def test_two_matching_public_providers_remain_nonfinancial(monkeypatch):
    monkeypatch.setattr(cross,"probe_pinned_migrations",lambda _rpc:fake_result())
    report=cross.compare_pinned_provider_migrations(
        Provider(PUBLIC_MAINNET_RPC),Provider(SECONDARY_RPC))
    assert len(report["verified_migrations"])==2
    assert report["signed_message_and_role_hashes_agree"] is True
    assert report["independent_rpc_consensus_verified"] is False
    assert report["cpmm_sell_simulation_verified"] is False
    assert report["financial_order_submitted"] is False
    assert report["live_ready_to_arm"] is False

@pytest.mark.parametrize("fault",["mismatch_hash","missing_second"])
def test_no_cross_provider_match_if_one_provider_disagrees(monkeypatch,fault):
    def probe(rpc):
        v=fake_result()
        if rpc.endpoint==SECONDARY_RPC:
            if fault=="mismatch_hash":
                v["results"][0]["signed_message_sha256"]="c"*64
            else:v["results"].pop()
        return v
    monkeypatch.setattr(cross,"probe_pinned_migrations",probe)
    with pytest.raises(ValueError):
        cross.compare_pinned_provider_migrations(
            Provider(PUBLIC_MAINNET_RPC),Provider(SECONDARY_RPC))

def test_mismatched_rpc_endpoints_refused_before_any_probe(monkeypatch):
    monkeypatch.setattr(cross,"probe_pinned_migrations",
                        lambda _: (_ for _ in ()).throw(AssertionError("Network forbidden")))
    with pytest.raises(ValueError,match="endpoints"):
        cross.compare_pinned_provider_migrations(
            Provider(SECONDARY_RPC),Provider(PUBLIC_MAINNET_RPC))
