"""Offline-only two-bank economic evidence; no fills, no profits, no trades."""
from copy import deepcopy
import pytest

from bot.live.cpmm_prospective_markout import (
    decode_bank, conditional_markouts, observe_prospective_two_banks,
    POOL, MINT, ENTRY_LAMPORTS)
from bot.live.cpmm_exit import _pool, _account, POOL_ACCOUNT_SIZE, POOL_DISCRIMINATOR
from bot.live.readonly_plan import MAINNET_GENESIS
from test_live_cpmm_exit import fixture_bank, mutate_raw, _token_state
from bot.p3.quotes import SOL_MINT


def fixture_accounts():
    d=fixture_bank(creator_enabled=False)["accounts"]
    old_pool=next(k for k,v in d.items() if v and v.get("owner")==
        "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
        and len(v["data"][0])>600)
    # The economic function is intentionally pinned to a real pool; synthetic
    # fixtures cannot impersonate a different signed migration pool identity.
    # Test the pure decoder with a patched module pin, not a fake mainnet fact.
    return d,old_pool


def test_bank_decoder_and_hypothetical_sizes(monkeypatch):
    from bot.live import cpmm_prospective_markout as mod
    p=fixture_bank(creator_enabled=False)
    monkeypatch.setattr(mod,"POOL",p["pool_address"])
    monkeypatch.setattr(mod,"MINT",p["mint"])
    raw=_pool(_account(p["accounts"][p["pool_address"]],name="pool",
                   size=POOL_ACCOUNT_SIZE,discriminator=POOL_DISCRIMINATOR))
    keys=[p["pool_address"],raw["amm_config"],raw["token_0_vault"],raw["token_1_vault"]]
    s1=decode_bank({k:p["accounts"][k] for k in keys})
    assert s1["base_reserve_atomic"]==1_000_000_000
    assert s1["sol_reserve_lamports"]==5_000_000_000
    s2=deepcopy(s1)
    s2["sol_reserve_lamports"]+=500_000_000
    output=conditional_markouts(s1,s2,first_slot=1234,second_slot=1235,
                                registered_before_s2=True)
    assert output["observed_pool_state_changed"] is True
    assert output["observed_independent_market_transition_count"]==1
    assert len(output["results"])==len(ENTRY_LAMPORTS)==3
    assert all(row["execution_verified"] is False for row in output["results"])
    assert output["completed_actual_buy_sell_cycles"]==0
    assert output["master_vs_baseline_economic_edge_validated"] is False
    assert output["financial_order_submitted"] is False
    assert output["live_ready_to_arm"] is False
    assert all(row["observed_S2_sell_quote_lamports"] is not None
               for row in output["results"])


@pytest.mark.parametrize("modification",["slot","registration","pool","config","mint"])
def test_never_use_future_or_unlinked_bank_as_qualified_result(monkeypatch,modification):
    from bot.live import cpmm_prospective_markout as mod
    p=fixture_bank(creator_enabled=False)
    monkeypatch.setattr(mod,"POOL",p["pool_address"])
    monkeypatch.setattr(mod,"MINT",p["mint"])
    pool=_pool(_account(p["accounts"][p["pool_address"]],name="pool",
                size=POOL_ACCOUNT_SIZE,discriminator=POOL_DISCRIMINATOR))
    keys=[p["pool_address"],pool["amm_config"],pool["token_0_vault"],pool["token_1_vault"]]
    first=decode_bank({k:p["accounts"][k] for k in keys})
    second=deepcopy(first)
    args=dict(first_slot=200,second_slot=201,registered_before_s2=True)
    if modification=="slot":args["second_slot"]=200
    elif modification=="registration":args["registered_before_s2"]=False
    elif modification=="pool":second["pool"]="not-pool"
    elif modification=="config":second["config"]["trade_fee_rate"]+=1
    elif modification=="mint":second["mint"]="not-mint"
    with pytest.raises(ValueError,match="noncausal"):
        conditional_markouts(first,second,**args)


def test_wrong_genesis_refuses_before_any_market_read():
    class Fake:
        def __init__(self):self.methods=[]
        def __call__(self,method,params):
            self.methods.append(method)
            return "not-mainnet"
    rpc=Fake()
    with pytest.raises(ValueError,match="genesis"):
        observe_prospective_two_banks(rpc,wait_seconds=1,sleep=lambda _:None)
    assert rpc.methods==["getGenesisHash"]


def test_malformed_budget_never_runs_rpc():
    with pytest.raises(ValueError):
        observe_prospective_two_banks(None)
    with pytest.raises(ValueError):
        observe_prospective_two_banks(lambda *_:None,wait_seconds=1000)


def test_s2_wait_is_registered_before_future_bank(monkeypatch,capsys):
    from bot.live import cpmm_prospective_markout as mod
    p=fixture_bank(creator_enabled=False)
    monkeypatch.setattr(mod,"POOL",p["pool_address"])
    monkeypatch.setattr(mod,"MINT",p["mint"])
    # Let pure RPC handler inspect order without real network or private keys.
    pool=_pool(_account(p["accounts"][p["pool_address"]],name="pool",
                size=POOL_ACCOUNT_SIZE,discriminator=POOL_DISCRIMINATOR))
    keys=[p["pool_address"],pool["amm_config"],pool["token_0_vault"],pool["token_1_vault"]]
    class Fake:
        def __init__(self):self.count=0;self.events=[]
        def __call__(self,method,params):
            self.count+=1;self.events.append(method)
            if method=="getGenesisHash":return MAINNET_GENESIS
            if self.count==2:
                return dict(context=dict(slot=300),value=[p["accounts"][p["pool_address"]]])
            if self.count==3:
                return dict(context=dict(slot=301),value=[p["accounts"][k] for k in keys])
            assert self.count==4 and params[1]["minContextSlot"]==302
            assert "REGISTERED_BEFORE_S2" in capsys.readouterr().out
            return dict(context=dict(slot=303),value=[p["accounts"][k] for k in keys])
    rpc=Fake()
    out=observe_prospective_two_banks(rpc,wait_seconds=1,sleep=lambda n:None)
    assert out["first_slot"]==301 and out["second_slot"]==303
    assert out["status"]=="UNCHANGED_BANK_FRICTION_ONLY"
    assert out["observed_pool_state_changed"] is False
    assert out["observed_independent_market_transition_count"]==0
    assert out["rpc_calls_used"]==4
    assert rpc.events==["getGenesisHash","getMultipleAccounts",
                         "getMultipleAccounts","getMultipleAccounts"]
    assert out["strict_economic_cycles_qualified"]==0
    assert out["actual_fill_or_executable_profit_verified"] is False
