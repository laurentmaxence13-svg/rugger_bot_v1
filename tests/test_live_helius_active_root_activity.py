"""Retrospective survivor bias is explicit; capacity filter is S1-causal, never GO."""
import pytest
from bot.live import helius_active_launchlab_cohort as mod
from bot.p3.certification import _encode
from bot.p3.quotes import SOL_MINT


def pub(n):
    return _encode(bytes([n])*32)


def fixture(monkeypatch,*,active=True):
    pools=[pub(1),pub(2)]
    roots={
        pools[0]:dict(mint_a=pub(10),mint_b=SOL_MINT,status=0,
                      creator=pub(21),real_a=0,real_b=0),
        pools[1]:dict(mint_a=pub(11),mint_b=SOL_MINT,status=0,
                      creator=pub(22),real_a=100000000,real_b=1000000 if active else 0),
    }
    monkeypatch.setattr(mod,"discover_live_pool_account_page",lambda rpc:dict(
        scan_slot=1000,observed_universe_sha256="a"*64,
        observed_active_SOL_pools_in_one_page=2,
        further_pages_exist=False,initial_pools_before_price=pools))
    monkeypatch.setattr(mod,"_pool",lambda raw:(raw,bytes(429)))
    monkeypatch.setattr(mod,"addresses_from_pool",lambda raw,mint,pool:dict(
        pool=pool,config=pub(100),platform=pub(101),mint_a=mint,mint_b=SOL_MINT,
        vault_a=pub(102),vault_b=pub(103)))
    monkeypatch.setattr(mod,"analyze_snapshot",lambda *args,**kwargs:dict(
        schema="p3-launchlab-native-snapshot-v1",evidence_profile="published_metadata_v1",
        facts={},risk_flags=[],blocking_reasons=[],
        conditional_projection=dict(buy_output_atomic="1234") if
                              kwargs.get("compute_projection",True) else None))
    monkeypatch.setattr(mod,"_followup_sell_from_snapshot",lambda *args,**kwargs:dict(output_lamports="90000"))
    class Rpc:
        count=2
        def __init__(self):self.calls=0
        def __call__(self,method,args):
            assert method=="getMultipleAccounts"
            self.calls+=1
            if self.calls==1:
                return dict(context=dict(slot=1001),value=[roots[x] for x in args[0]])
            return dict(context=dict(slot=1001+self.calls),value=[dict(bank=self.calls) for _ in args[0]])
    return Rpc()


def test_root_activity_screen_freezes_one_pre_S1_and_retains_denominator(monkeypatch):
    rpc=fixture(monkeypatch)
    r=mod.observe_active_survivor_cohort(rpc,wait_seconds=1,
        sleep=lambda x:None,prefer_root_activity=True)
    assert r["root_activity_filter_enabled"] is True
    assert r["selected_count"]==1
    assert r["discovery_denominator"][0]["selection_reason"]=="no_observed_root_outstanding_tokens_and_SOL_reserve"
    assert r["discovery_denominator"][1]["selection_reason"]=="selected_before_S1"
    assert r["observations"][0]["mint"]==pub(11)
    assert r["strict_qualified_economic_cycles"]==0
    assert not r["financial_order_submitted"]
    assert not r["representative_creation_universe"]


def test_unknown_or_zero_root_activity_retains_zero_selected(monkeypatch):
    rpc=fixture(monkeypatch,active=False)
    r=mod.observe_active_survivor_cohort(rpc,wait_seconds=1,
        sleep=lambda x: (_ for _ in ()).throw(AssertionError("no S1 or S2 expected")),
        prefer_root_activity=True)
    assert r["selected_count"]==0
    assert len(r["discovery_denominator"])==2
    assert all(z["selection_reason"]=="no_observed_root_outstanding_tokens_and_SOL_reserve"
               for z in r["discovery_denominator"])
    assert rpc.calls==1


def test_activity_filter_requires_bool_before_rpc():
    calls=[]
    def fake(*args):
        calls.append(args)
    with pytest.raises(ValueError,match="active_readonly_cohort_bounds_required"):
        mod.observe_active_survivor_cohort(fake,prefer_root_activity=1)
    assert calls==[]
