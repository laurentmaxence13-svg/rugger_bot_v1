"""No-network tests for pinned LaunchLab root forensic diagnosis (not an entry)."""
import pytest
from bot.live.helius_pinned_root_diagnostic import (
    inspect_pinned_root, PINNED_POOL, PINNED_MINT, SOURCE_SLOT)
from bot.live.readonly_plan import MAINNET_GENESIS


class FakeRpc:
    def __init__(self,root=None,genesis=MAINNET_GENESIS):
        self.root=root;self.genesis=genesis;self.calls=[]
    def __call__(self,method,args):
        self.calls.append((method,args))
        if method=="getGenesisHash":
            assert args==[]
            return self.genesis
        assert method=="getMultipleAccounts"
        assert args==[[PINNED_POOL],dict(
            encoding="base64",commitment="confirmed",minContextSlot=SOURCE_SLOT)]
        return dict(context=dict(slot=SOURCE_SLOT+300),value=[self.root])


def test_missing_historical_pool_stays_unqualified():
    rpc=FakeRpc(root=None)
    report=inspect_pinned_root(rpc,clock=lambda:"fixed-test-clock")
    assert len(rpc.calls)==2
    assert report["status"]=="POOL_ACCOUNT_UNAVAILABLE"
    assert report["source_to_current_slot_gap"]==300
    assert report["historical_asof_entry_state_verified"] is False
    assert report["qualified_market_economic_cycles"]==0
    assert report["financial_order_submitted"] is False
    assert report["live_ready_to_arm"] is False
    assert report["master_net_pnl_lamports"] is None


def test_wrong_owner_or_bad_layout_reports_current_root_reason_not_entry():
    rpc=FakeRpc(root=dict(owner="WrongOwner123",executable=False,
                          data=["AA==","base64"],lamports=1))
    report=inspect_pinned_root(rpc)
    assert report["pool_account_present"]
    assert report["pool_data_length_bytes"]==1
    assert report["root_decode_error"]=="pool_owner_or_executable_invalid"
    assert report["status"]=="CURRENT_ROOT_REFUSED_NOT_PROSPECTIVE"
    assert report["provider_executable_buy_sell_quote_observed"] is False


def test_invalid_genesis_must_not_read_pool():
    rpc=FakeRpc(genesis="different-mainnet")
    with pytest.raises(ValueError,match="mainnet_genesis"):
        inspect_pinned_root(rpc)
    assert len(rpc.calls)==1


def test_tampered_root_envelope_refused():
    class Rpc:
        def __init__(self):self.count=0
        def __call__(self,method,args):
            self.count+=1
            if self.count==1:return MAINNET_GENESIS
            return dict(context=dict(slot=SOURCE_SLOT-1),value=[None])
    with pytest.raises(ValueError,match="bank_context_or_cardinality"):
        inspect_pinned_root(Rpc())


def test_declares_no_historical_asof_even_when_pool_decompressed():
    rpc=FakeRpc(root=dict(owner="WrongOwner123",executable=False,
                          data=["AA==","base64"],lamports=1))
    report=inspect_pinned_root(rpc)
    assert report["historical_asof_entry_state_verified"] is False
    assert report["financial_order_submitted"] is False
    assert report["reference_net_pnl_lamports"] is None
