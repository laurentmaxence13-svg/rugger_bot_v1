"""No-network contract for SURVIVOR-only prospective launch cohort."""
import pytest
from bot.live import helius_active_launchlab_cohort as a
from bot.p3.quotes import SOL_MINT
from bot.p3.certification import _encode

def pub(i):return _encode(bytes([i])*32)

def test_three_creators_are_frozen_before_S1_and_S2(monkeypatch,capsys):
    pools=[pub(i) for i in (1,2,3,4)]
    root_addresses={p:dict(pool=p,creator=pub(i+50),mint_a=pub(i+70),
                          mint_b=SOL_MINT,status=0)
                    for i,p in enumerate(pools)}
    monkeypatch.setattr(a,"discover_live_pool_account_page",
        lambda rpc:dict(scan_slot=1000,observed_universe_sha256="a"*64,
              observed_active_SOL_pools_in_one_page=64,
              further_pages_exist=True,initial_pools_before_price=pools))
    monkeypatch.setattr(a,"_pool",
        lambda raw:(raw,bytes(429)))
    def graph(raw,mint,pool):
        i=pools.index(pool)
        return dict(pool=pool,config=pub(i+100),platform=pub(i+110),
            mint_a=mint,mint_b=SOL_MINT,vault_a=pub(i+120),vault_b=pub(i+130))
    monkeypatch.setattr(a,"addresses_from_pool",graph)
    def analyze(accounts,*,compute_projection=True,**kwargs):
        return dict(facts=dict(pool=dict(status=0),config=dict(
            trade_fee_rate_ppm=2500,curve_type=0),
            platform=dict(platform_fee_rate_ppm=0,creator_fee_rate_ppm=0),
            quote_vault=dict(amount_atomic="10000000")),
            risk_flags=[],blocking_reasons=[],conditional_projection=
            (dict(buy_output_atomic="500") if compute_projection else None))
    monkeypatch.setattr(a,"analyze_snapshot",analyze)
    monkeypatch.setattr(a,"observed_sell_projection",
        lambda pool,**kwargs:dict(output_lamports="9000000"))
    # Discover mock consumes two calls, but the contract still uses shared RPC
    # for roots, S1 and S2: exact bank slots are verified by the real helper.
    class Rpc:
        count=2
        def __init__(self):self.calls=0
        def __call__(self,method,params):
            self.calls+=1
            assert method=="getMultipleAccounts"
            if self.calls==1:
                return dict(context=dict(slot=1001),
                    value=[root_addresses[p] for p in params[0]])
            if self.calls==2:
                return dict(context=dict(slot=1002),
                    value=[dict(bank="S1") for _ in params[0]])
            assert self.calls==3 and params[1]["minContextSlot"]==1003
            out=capsys.readouterr().out
            assert "FROZEN_ACTIVE_SURVIVOR_SELECTION_BEFORE_S1" in out
            assert "S1_OBSERVED_BEFORE_S2" in out
            return dict(context=dict(slot=1003),
                value=[dict(bank="S2") for _ in params[0]])
    rpc=Rpc()
    out=a.observe_active_survivor_cohort(rpc,wait_seconds=1,
                                           sleep=lambda _:None)
    assert out["status"]=="ACTIVE_SURVIVOR_PROSPECTIVE_OBSERVATION_COMPLETE"
    assert out["selected_count"]==3
    assert len(out["observations"])==3
    assert out["discovery_denominator"][-1]["selection_reason"]=="outside_fixed_pre_S1_three_creator_sample"
    assert all(z["conditional_gross_markout_lamports"]==-1000000
               for z in out["observations"])
    assert out["strict_qualified_economic_cycles"]==0
    assert out["representative_creation_universe"] is False
    assert out["holdout_verified"] is False
    assert out["master_vs_reference_edge_demonstrated"] is False
    assert out["financial_order_submitted"] is False

def test_malformed_or_wrong_clock_no_trade(monkeypatch):
    pool=pub(1)
    monkeypatch.setattr(a,"discover_live_pool_account_page",
       lambda rpc:dict(scan_slot=1000,observed_universe_sha256="a"*64,
              observed_active_SOL_pools_in_one_page=1,
              further_pages_exist=False,initial_pools_before_price=[pool]))
    class Bad:
        def __call__(self,method,params):
            return dict(context=dict(slot=500),value=[None])
    with pytest.raises(ValueError,match="bank_context"):
        a.observe_active_survivor_cohort(Bad(),wait_seconds=1,
                                           sleep=lambda _:None)

def test_missing_rpc_and_unbounded_wait_refused_before_any_network():
    with pytest.raises(ValueError):
        a.observe_active_survivor_cohort(None)
    with pytest.raises(ValueError):
        a.observe_active_survivor_cohort(lambda *_:None,wait_seconds=400)
