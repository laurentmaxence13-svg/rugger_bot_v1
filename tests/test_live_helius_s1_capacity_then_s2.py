"""No-network tests for preregistered S1-capacity screening before S2."""
import pytest
from bot.live import helius_s1_capacity_then_s2 as mod
from bot.p3.certification import _encode
from bot.p3.quotes import SOL_MINT


def key(n):return _encode(bytes([n])*32)


def setup_pools(monkeypatch,count=4):
    pools=[key(i) for i in range(1,count+1)]
    raw={p:dict(creator=key(i+70),mint_a=key(i+80),mint_b=SOL_MINT,status=0)
         for i,p in enumerate(pools)}
    monkeypatch.setattr(mod,"discover_live_pool_account_page",
        lambda rpc:dict(scan_slot=1000,observed_universe_sha256="e"*64,
            initial_pools_before_price=pools))
    monkeypatch.setattr(mod,"_pool",lambda account:(account,bytes(429)))
    def graph(account,mint,pool):
        i=pools.index(pool)
        return dict(pool=pool,mint_a=mint,mint_b=SOL_MINT,
            config=key(100+i),platform=key(110+i),
            vault_a=key(120+i),vault_b=key(130+i))
    monkeypatch.setattr(mod,"addresses_from_pool",graph)
    return pools,raw


def test_only_s1_capacity_candidates_advance_to_future_bank(monkeypatch,capsys):
    pools,roots=setup_pools(monkeypatch,4)
    def analyze(accounts,*,pool_address,compute_projection=True,**kw):
        return dict(risk_flags=[],evidence_profile="published_metadata_v1",
            conditional_projection=(dict(buy_output_atomic="100")
                if compute_projection and pool_address!=pools[1] else None))
    monkeypatch.setattr(mod,"analyze_snapshot",analyze)
    monkeypatch.setattr(mod,"_followup_sell_from_snapshot",
                        lambda analysis,quantity:dict(output_lamports="9900000"))
    class Rpc:
        count=0
        def __init__(self):self.calls=0
        def __call__(self,method,params):
            self.calls+=1
            assert method=="getMultipleAccounts"
            if self.calls==1:
                assert params[0]==pools
                return dict(context=dict(slot=1001),
                    value=[roots[p] for p in pools])
            if self.calls in (2,3):
                if self.calls==2:
                    assert "FROZEN_POOL_PREFIX_BEFORE_S1" in capsys.readouterr().out
                return dict(context=dict(slot=1000+self.calls),
                    value=[dict(S1=True) for _ in params[0]])
            assert self.calls==4
            assert params[1]["minContextSlot"]==1004
            assert "S1_SCREENED_SELECTION_FROZEN_BEFORE_S2" in capsys.readouterr().out
            return dict(context=dict(slot=1004),
                value=[dict(S2=True) for _ in params[0]])
    out=mod.screened_s1_capacity_then_s2(Rpc(),
                          wait_seconds=1,sleep=lambda _:None)
    assert out["candidates_before_S1"]==4
    assert out["S1_screened_count"]==4
    assert out["S1_capacity_count"]==3
    assert out["selected_for_S2"]==3
    assert out["S2_conditional_sell_quotes"]==3
    assert out["real_buy_sell_trades"]==0
    assert out["strict_market_economic_cycles"]==0
    assert out["representative_creation_universe"] is False
    assert out["live_ready_to_arm"] is False


def test_no_S1_capable_source_stops_before_S2(monkeypatch):
    pools,roots=setup_pools(monkeypatch,2)
    monkeypatch.setattr(mod,"analyze_snapshot",lambda *args,**kw:dict(
        risk_flags=[],evidence_profile="published_metadata_v1",
        conditional_projection=None))
    class Rpc:
        count=0
        def __init__(self):self.calls=0
        def __call__(self,method,params):
            self.calls+=1
            assert method=="getMultipleAccounts"
            if self.calls==1:
                return dict(context=dict(slot=1001),
                    value=[roots[p] for p in params[0]])
            assert self.calls==2
            return dict(context=dict(slot=1002),
                        value=[dict(raw=True) for _ in params[0]])
    out=mod.screened_s1_capacity_then_s2(Rpc(),
                            wait_seconds=1,sleep=lambda _:None)
    assert out["S1_capacity_count"]==0
    assert out["S2_slot"] is None
    assert out["S2_conditional_sell_quotes"]==0
    assert out["live_ready_to_arm"] is False


def test_prohibited_wait_and_missing_rpc_refused():
    with pytest.raises(ValueError):
        mod.screened_s1_capacity_then_s2(None)
    with pytest.raises(ValueError):
        mod.screened_s1_capacity_then_s2(lambda *_:None,wait_seconds=1000)
