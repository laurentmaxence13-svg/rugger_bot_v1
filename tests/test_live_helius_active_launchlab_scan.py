"""Offline tests for the current-active only Helius on-chain discovery."""
import pytest
from bot.live import helius_active_launchlab_scan as s
from bot.p3.certification import PROGRAM,_encode
from bot.p3.quotes import SOL_MINT
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from test_live_helius_readonly_rpc import KEY,Opener

def account(i):
    return dict(pubkey=_encode(bytes([i])*32),
        account=dict(owner=PROGRAM,executable=False,data=["","base64"]))

class Fake:
    def __init__(self,rows=None,chain=MAINNET_GENESIS):
        self.chain=chain;self.rows=rows if rows is not None else [account(x) for x in (1,2,3)]
        self.count=0
    def __call__(self,method,params):
        self.count+=1
        if method=="getGenesisHash":return self.chain
        assert method=="getProgramAccountsV2" and params==[PROGRAM,s.OPTIONS]
        return dict(context=dict(slot=463400000),value=dict(accounts=self.rows,paginationKey=None))

def test_never_promote_active_survivors_as_independent_creation_universe():
    out=s.discover_live_pool_account_page(Fake())
    assert out["status"]=="ACTIVE_SOL_POOLS_PAGE_RECORDED"
    assert out["observed_active_SOL_pools_in_one_page"]==3
    assert out["survivorship_bias_present"] is True
    assert out["is_creation_universe"] is False
    assert out["master_edge_validated"] is False
    assert out["buy_sell_trades"]==0
    assert out["financial_order_submitted"] is False
    assert out["live_ready_to_arm"] is False

def test_permutation_deterministic_under_reordered_provider_response():
    rows=[account(x) for x in range(1,22)]
    a=s.discover_live_pool_account_page(Fake(rows=rows))
    b=s.discover_live_pool_account_page(Fake(rows=list(reversed(rows))))
    assert a["observed_universe_sha256"]==b["observed_universe_sha256"]
    assert a["initial_pools_before_price"]==b["initial_pools_before_price"]
    assert len(a["initial_pools_before_price"])==12

def test_duplicate_or_inconsistent_account_list_fails_closed():
    for rows in ([account(1),account(1)],
                 [dict(account(1),account=dict(owner="untrusted",
                     executable=False,data=["","base64"]))]):
        with pytest.raises(ValueError):
            s.discover_live_pool_account_page(Fake(rows=rows))

def test_wrong_chain_and_unbounded_scan_disallowed():
    with pytest.raises(ValueError,match="genesis"):
        s.discover_live_pool_account_page(Fake(chain="wrong"))
    with pytest.raises(ValueError,match="cap"):
        s.discover_live_pool_account_page(Fake(rows=[account(1)]*(s.MAX_UNIVERSE+1)))

def test_helius_method_requires_exact_fixed_scan_and_optin():
    opener=Opener()
    rpc=HeliusReadOnlyRpc(KEY,opener=opener)
    with pytest.raises(ValueError,match="allowlisted"):
        rpc("getProgramAccountsV2",[PROGRAM,s.OPTIONS])
    opted=HeliusReadOnlyRpc(KEY,opener=opener,allow_active_pool_scan=True)
    for params in ([PROGRAM,dict(s.OPTIONS,filters=[])],
                   [PROGRAM,dict(s.OPTIONS,dataSlice=dict(offset=0,length=429))],
                   ["random-program",s.OPTIONS]):
        with pytest.raises(ValueError,match="page"):
            opted("getProgramAccountsV2",params)
    assert opener.calls==[]
