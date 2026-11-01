"""No-network genuine IDL-trade source discovery: full denominators and caps."""
from copy import deepcopy

import pytest

from bot.live import helius_recent_signed_trade_pools as mod
from bot.p3.certification import PROGRAM,_encode
from bot.p3.quotes import SOL_MINT
from bot.live.readonly_plan import MAINNET_GENESIS

NOW=1_780_000_000_000
BASE="fixture-launchlab-token-base-mint"
POOL="fixture-launchlab-pool"


def trade(sig,*,pool=POOL,base=BASE,quote=SOL_MINT,
          direction="BUY_EXACT_IN",slot=410,signer=True,program=PROGRAM):
    names=list(mod.IDL_TRADE_DISCRIMINATORS)
    named={v:k for k,v in mod.IDL_TRADE_DISCRIMINATORS.items()}
    keys=[dict(pubkey="key-"+str(i),signer=False,writable=False)
          for i in range(17)]
    keys[0]=dict(pubkey="fixture-signed-buyer",signer=signer,writable=True)
    keys[4]=dict(pubkey=pool,signer=False,writable=True)
    keys[9]=dict(pubkey=base,signer=False,writable=False)
    keys[10]=dict(pubkey=quote,signer=False,writable=False)
    keys[16]=dict(pubkey=program,signer=False,writable=False)
    return dict(version="legacy",slot=slot,meta=dict(err=None),
        transaction=dict(signatures=[sig],message=dict(
            accountKeys=keys,instructions=[dict(programIdIndex=16,
                accounts=list(range(15)),data=_encode(named[direction]))])))


def verified(monkeypatch):
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",
        lambda *a:dict(cryptographic_signatures_verified=True,
            exact_message_sha256="d"*64))


def test_exact_official_idl_buy_sell_discriminators_and_account_positions(monkeypatch):
    verified(monkeypatch)
    sig=_encode(bytes([11])*64)
    for direction in ("BUY_EXACT_IN","BUY_EXACT_OUT","SELL_EXACT_IN","SELL_EXACT_OUT"):
        rows=mod.pinned_signed_launchlab_swaps(trade(sig,direction=direction))
        assert len(rows)==1
        assert rows[0]["side"]==direction
        assert rows[0]["pool"]==POOL
        assert rows[0]["mint"]==BASE
        assert rows[0]["direct_outer_idl_trade_instruction"] is True
        assert rows[0]["original_creation_signer_verified"] is False


def test_wrong_quote_buyer_signer_program_and_unknown_ix_never_become_real_sol_trade(monkeypatch):
    verified(monkeypatch)
    sig=_encode(bytes([12])*64)
    for changes in (dict(quote="other-quote-mint"),
                    dict(signer=False),
                    dict(program="fake-program")):
        assert mod.pinned_signed_launchlab_swaps(trade(sig,**changes))==[]
    bad=trade(sig)
    bad["transaction"]["message"]["instructions"][0]["data"]=_encode(b"not-buy!")
    assert mod.pinned_signed_launchlab_swaps(bad)==[]
    bad=trade(sig)
    bad["transaction"]["message"]["instructions"][0]["accounts"][4]=99
    with pytest.raises(ValueError,match="signed_trade_account_index_out_of_bounds"):
        mod.pinned_signed_launchlab_swaps(bad)


def test_latest_finalized_signatures_produce_bounded_active_pool_candidates(monkeypatch):
    verified(monkeypatch)
    signatures=[_encode(bytes([n+50])*64) for n in range(12)]
    class Rpc:
        def __init__(self):self.count=0
        def __call__(self,method,params):
            self.count+=1
            assert self.count<=10
            if method=="getGenesisHash":
                assert params==[]
                return MAINNET_GENESIS
            if method=="getSignaturesForAddress":
                assert params==[PROGRAM,dict(limit=20,commitment="finalized")]
                return [dict(signature=sig,slot=400+n,err=None,
                    blockTime=NOW//1000-2) for n,sig in enumerate(signatures)]
            if method=="getTransaction":
                sig=params[0]
                idx=signatures.index(sig)
                assert params[1]==mod.RAW_OPTS
                return trade(sig,slot=400+idx,
                    pool=POOL+str(idx),base=BASE+str(idx))
            raise AssertionError(method)
    rpc=Rpc()
    res=mod.discover_recent_signed_sol_trade_pools(rpc,clock_ms=NOW)
    assert rpc.count==10
    assert res["source_signature_count"]==12
    assert res["receipt_lookup_attempts"]==8
    assert res["selected_recent_pool_count"]==3
    assert [x["pool"] for x in res["selected_signed_recent_trade_pools"]]==[
        POOL+"0",POOL+"1",POOL+"2"]
    assert sum(x["eligibility_reason"]=="NOT_INSPECTED_RPC_BUDGET"
               for x in res["original_signature_page_records"])==4
    assert res["recent_trade_selection_no_future_exit_used"] is True
    assert res["actual_master_decision"] is None
    assert res["full_roundtrip_proof"] is False
    assert res["master_net_pnl_lamports"] is None
    assert res["financial_order_submitted"] is False


def test_old_failed_and_unproven_receipts_keep_denominator_not_fake_source(monkeypatch):
    verified(monkeypatch)
    signatures=[_encode(bytes([n+80])*64) for n in range(11)]
    class Rpc:
        def __init__(self):self.count=0
        def __call__(self,method,params):
            self.count+=1
            if method=="getGenesisHash":return MAINNET_GENESIS
            if method=="getSignaturesForAddress":
                return [dict(signature=sig,slot=200+n,
                    blockTime=NOW//1000-3,
                    err={"failure":1} if n==0 else None)
                    for n,sig in enumerate(signatures)]
            if method=="getTransaction":
                idx=signatures.index(params[0])
                return trade(params[0],slot=200+idx,
                    quote="USDC-not-SOL" if idx<4 else SOL_MINT)
            raise AssertionError(method)
    rpc=Rpc()
    res=mod.discover_recent_signed_sol_trade_pools(rpc,clock_ms=NOW)
    assert rpc.count==10
    assert res["receipt_lookup_attempts"]==8
    assert res["original_signature_page_records"][0]["eligibility_reason"]==(
        "FAILED_SIGNED_PROGRAM_TRANSACTION")
    assert res["source_signature_count"]==11
    assert res["selected_recent_pool_count"]<=3
    assert res["live_pool_status_not_yet_queried"] is True


def test_unsigned_transaction_refuses_without_promoting_provider_meta(monkeypatch):
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",
        lambda *a:dict(cryptographic_signatures_verified=False))
    with pytest.raises(ValueError,match="launchlab_recent_trade_signature_unverified"):
        mod.pinned_signed_launchlab_swaps(trade(_encode(bytes([18])*64)))
