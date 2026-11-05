"""Preregistered seven-size S1/S2 sensitivity; no real or synthetic fill claims."""
import pytest
from bot.live import helius_active_launchlab_cohort as mod
from bot.p3.certification import _encode
from bot.p3.quotes import SOL_MINT


def pub(i):
    return _encode(bytes([i])*32)


def test_size_ladder_frozen_pre_S2_and_refuses_one_sol_illiquid_exit(monkeypatch):
    pool=pub(1);mint=pub(2);creator=pub(3)
    graph=dict(pool=pool,config=pub(4),platform=pub(5),mint_a=mint,
        mint_b=SOL_MINT,vault_a=pub(6),vault_b=pub(7))
    root=dict(mint_a=mint,mint_b=SOL_MINT,creator=creator,status=0)
    monkeypatch.setattr(mod,"discover_live_pool_account_page",lambda rpc:dict(
        scan_slot=1000,observed_universe_sha256="b"*64,
        observed_active_SOL_pools_in_one_page=1,
        further_pages_exist=False,initial_pools_before_price=[pool]))
    monkeypatch.setattr(mod,"_pool",lambda value:(value,bytes(429)))
    monkeypatch.setattr(mod,"addresses_from_pool",lambda *args:graph)
    state=dict(s2=False,initial_models=[])
    def analyse(accounts,*,input_lamports,compute_projection=True,**kw):
        if compute_projection:
            assert state["s2"] is False
            state["initial_models"].append(input_lamports)
        elif state["s2"] is False:
            raise AssertionError("S2 analysis called before frozen S1")
        return dict(schema="p3-launchlab-native-snapshot-v1",
            evidence_profile="published_metadata_v1",
            risk_flags=[],blocking_reasons=["execution_not_verified"],
            facts=dict(pool=dict(status="0")),
            conditional_projection=(dict(buy_output_atomic=str(input_lamports))
                                    if compute_projection else None))
    monkeypatch.setattr(mod,"analyze_snapshot",analyse)
    def sell(analysis,exact_quantity):
        qty=int(exact_quantity)
        if qty>=250_000_000:
            raise ValueError("sell_exceeds_observed_outstanding_curve_tokens")
        return dict(output_lamports=str(qty-1000))
    monkeypatch.setattr(mod,"_followup_sell_from_snapshot",sell)
    class Rpc:
        count=2
        def __init__(self):self.calls=0
        def __call__(self,method,params):
            assert method=="getMultipleAccounts"
            self.calls+=1
            slot=(1001,1002,1003)[self.calls-1]
            if self.calls==1:
                rows=[root]
            else:
                rows=[dict(mock_bank="S1" if self.calls==2 else "S2")
                      for _ in params[0]]
            return dict(context=dict(slot=slot),value=rows)
    def before_second():
        assert state["s2"] is False
        assert state["initial_models"]==[
            mod.BUY_LAMPORTS,*mod.RESEARCH_LADDER_LAMPORTS]
        state["s2"]=True
    out=mod.observe_active_survivor_cohort(Rpc(),wait_seconds=1,
        sleep=lambda wait:before_second(),research_ladder=True)
    assert out["selected_count"]==1
    assert out["research_size_ladder_enabled"] is True
    assert out["research_sizes_are_not_independent_creators"] is True
    rows=out["observations"][0]["research_size_ladder"]
    assert [int(r["entry_lamports"]) for r in rows]==list(mod.RESEARCH_LADDER_LAMPORTS)
    assert len(rows)==7
    assert out["observations"][0]["s2_refusal"]=="insufficient_supported_real_S2_exit_evidence"
    for row in rows:
        amount=int(row["entry_lamports"])
        assert row["observed_execution"] is False
        if amount>=250_000_000:
            assert row["s2_conditional_sell_lamports"] is None
            assert row["s2_refusal"]=="exact_lot_S2_curve_or_capacity_refused"
        else:
            assert row["s2_conditional_gross_markout_lamports"]=="-1000"
            assert row["s2_conditional_sell_lamports"]==str(amount-1000)
            assert row["economic_cycle_qualified"] is False
    assert out["strict_qualified_economic_cycles"]==0
    assert out["master_vs_reference_edge_demonstrated"] is False
    assert out["financial_order_submitted"] is False


def test_research_ladder_rejects_nonboolean_selection_before_source_calls():
    calls=[]
    def rpc(*args):
        calls.append(args)
        raise AssertionError("must fail before source")
    with pytest.raises(ValueError,match="active_readonly_cohort_bounds_required"):
        mod.observe_active_survivor_cohort(rpc,research_ladder="yes")
    assert calls==[]
