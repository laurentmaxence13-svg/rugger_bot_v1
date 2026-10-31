"""Bounded no-network tests for the early confirmed LaunchLab PAPER sensor."""
import asyncio
from unittest.mock import patch
import pytest
from bot.live import helius_early_signed_s1s2 as m
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.certification import _encode
from bot.p3.quotes import SOL_MINT
from test_live_solana_v1_readonly import signed_receipt

SIG=_encode(bytes([7])*64)
CREATOR=_encode(bytes([9])*32)
MINT=_encode(bytes([10])*32)
POOL=_encode(bytes([11])*32)


def event(sig=SIG):
    return dict(signature=sig,slot=463809741,
        reception_utc_ns=1793475669300000000,
        on_chain_transaction_failed=False,
        untrusted_initialize_log_hint=True)


class FakeRpc:
    def __init__(self,*,present=True):
        self.count=0
        self.present=present
        self.calls=[]
    def __call__(self,method,args):
        self.count+=1
        self.calls.append((method,args))
        assert self.count<=m.MAX_RPC
        if method=="getGenesisHash":return MAINNET_GENESIS
        if method=="getTransaction":
            if not self.present:return None
            return dict(version=0,slot=463809741,meta=dict(err=None),
                transaction=dict(signatures=[SIG]))
        raise AssertionError(method)


def test_early_hint_without_confirmed_receipt_cannot_invent_price():
    rpc=FakeRpc(present=False)
    out=m.inspect_one_hint_early(event(),rpc,clock_ms=lambda:1793475669500,
        sleep=lambda _:None)
    assert out["status"]=="CONFIRMED_RECEIPT_NOT_YET_AVAILABLE"
    assert "s1_slot" not in out
    assert out["qualified_master_cycle"] is False
    assert out["master_net_pnl_lamports"] is None


def test_signed_creation_enforces_receipt_signature_and_slot():
    rpc=FakeRpc()
    with pytest.raises(ValueError,match="slot_signature"):
        m.signed_receipt_proof(
            dict(version=0,slot=463809742,meta=dict(err=None),
                 transaction=dict(signatures=[SIG])),
            SIG,463809741,rpc,commitment="confirmed")
    assert rpc.count==0


def test_v1_exact_ed25519_signed_creation_and_tampering():
    wire,sig=signed_receipt()
    rpc=FakeRpc()
    rpc.__call__=None  # __call__ on class is used; use a separate stub below.
    class V1:
        count=0
        def __call__(self,method,args):
            self.count+=1
            assert method=="getTransaction"
            assert args[1]["commitment"]=="confirmed"
            return wire
    proof=m.signed_receipt_proof(
        dict(version=1,slot=10101,meta=dict(err=None),
             transaction=dict(signatures=[sig])),
        sig,10101,V1(),commitment="confirmed")
    assert len(proof["launches"])==1
    assert proof["version"]==1
    bad,_=signed_receipt(tamper=True)
    class TamperV1:
        def __call__(self,method,args):return bad
    with pytest.raises(ValueError,match="v1_exact_ed25519_message_invalid"):
        m.signed_receipt_proof(
            dict(version=1,slot=10101,meta=dict(err=None),
                transaction=dict(signatures=[sig])),
            sig,10101,TamperV1(),commitment="confirmed")


def test_one_s1_frozen_before_s2_then_fully_verified_finality():
    rpc=FakeRpc()
    graph=dict(pool=POOL,mint_a=MINT,mint_b=SOL_MINT,
        vault_a=_encode(bytes([20])*32),vault_b=_encode(bytes([21])*32),
        config=_encode(bytes([22])*32),platform=_encode(bytes([23])*32))
    states=[]
    def bank(client,addresses,slot):
        states.append((addresses,slot))
        if len(states)==1:
            return 463809742,{POOL:dict(root=1)}
        if len(states)==2:
            assert slot==463809742
            return 463809743,{key:dict(state="S1") for key in addresses}
        assert len(states)==3
        assert slot==463809744
        return 463809744,{key:dict(state="S2") for key in addresses}
    def snapshot(accounts,**kwargs):
        if not kwargs.get("compute_projection",True):
            return dict(facts=dict(
                pool=dict(status=0),config=dict(trade_fee_rate_ppm=2500,curve_type=0),
                platform=dict(platform_fee_rate_ppm=0,creator_fee_rate_ppm=0),
                quote_vault=dict(amount_atomic="1000000000")),
                risk_flags=[],blocking_reasons=[])
        return dict(conditional_projection=dict(buy_output_atomic="200"),
                    blocking_reasons=[],risk_flags=[])
    def proof(raw,sig,slot,client,**kwargs):
        return dict(message_sha256="a"*64,version=0,
                    launches=[dict(creator=CREATOR,mint=MINT,pool=POOL)])
    freeze_at_s2=[]
    with (patch.object(m,"signed_receipt_proof",side_effect=proof),
          patch.object(m,"_bank",side_effect=bank),
          patch.object(m,"addresses_from_pool",return_value=graph),
          patch.object(m,"analyze_snapshot",side_effect=snapshot),
          patch.object(m,"observed_sell_projection",
                       return_value=dict(output_lamports="900000000"))):
        def check_delay(seconds):
            freeze_at_s2.append(seconds)
            assert seconds==5
            assert len(states)==2
        res=m.inspect_one_hint_early(event(),rpc,
            sleep=check_delay,clock_ms=lambda:1793475669500)
    assert freeze_at_s2==[5]
    assert res["status"]=="FROZEN_S1_BEFORE_S2_NO_TRADE"
    assert res["frozen_pre_S2"]["master_action"]!="ENTER"
    assert res["frozen_pre_S2"]["future_S2_consumed"] is False
    assert res["s1_slot"]==463809743
    assert res["creation_to_root_slot_gap"]==1
    assert res["s1_s2_conditional_markout_lamports"]=="-100000000"
    assert res["finality_verified"] is True
    assert res["master_net_pnl_lamports"] is None
    assert res["financial_order_submitted"] is False
    assert len(states)==3
    assert rpc.count==2


def test_missing_root_is_explicit_no_position_and_no_master_pnl():
    rpc=FakeRpc()
    with (patch.object(m,"signed_receipt_proof",
             return_value=dict(message_sha256="a"*64,version=0,
             launches=[dict(creator=CREATOR,mint=MINT,pool=POOL)])),
          patch.object(m,"_bank",return_value=(463809950,{POOL:None}))):
        res=m.inspect_one_hint_early(event(),rpc,
            sleep=lambda _: (_ for _ in ()).throw(AssertionError("not S2")))
    assert res["root_refusal"]=="pool_account_unavailable"
    assert res["creation_to_root_slot_gap"]==209
    assert "frozen_pre_S2" not in res
    assert res["master_net_pnl_lamports"] is None


def test_background_stream_records_preselected_hints_without_trading():
    rpc=FakeRpc(present=False)
    async def sensor(seconds,maximum,key,*,successful_only,on_retained):
        assert successful_only is True
        on_retained(event())
        on_retained(dict(event(SIG),signature=_encode(bytes([8])*64),slot=463809742))
        return (dict(events_received_unique=2,signature_ledger_sha256="b"*64),
                [event()])
    with patch.object(m,"observe",side_effect=sensor):
        result,events=asyncio.run(m.bounded_early_capture(
            seconds=10,max_events=100,rpc=rpc,key="test-only-key"))
    assert len(result["selected"])==2
    assert len(result["attempts"])==2
    assert result["qualified_economic_cycles"]==0
    assert result["master_net_pnl_lamports"] is None
    assert result["financial_order_submitted"] is False
    assert rpc.count==5  # genesis and two confirmed reads per observed hint



def test_nonhint_successful_logs_are_eligible_only_for_cryptographic_probe():
    rpc=FakeRpc(present=False)
    async def no_hints(seconds,maximum,key,*,successful_only,on_retained):
        for n in (7,8,9):
            row=dict(event(_encode(bytes([n])*64)),
                     untrusted_initialize_log_hint=False)
            on_retained(row)
        return dict(events_received_unique=3,
                    signature_ledger_sha256="a"*64),[]
    with patch.object(m,"observe",side_effect=no_hints):
        out,_=asyncio.run(m.bounded_early_capture(
            seconds=10,max_events=100,rpc=rpc,key="test-only"))
    assert len(out["selected"])==2
    assert len(out["attempts"])==2
    assert all(x["selection_reason"]=="first_successful_log_no_required_hint"
               for x in out["selected"])
    assert all(x["status"]=="CONFIRMED_RECEIPT_NOT_YET_AVAILABLE"
               for x in out["attempts"])
    assert out["qualified_economic_cycles"]==0
    assert out["master_net_pnl_lamports"] is None
    assert out["financial_order_submitted"] is False


def test_one_bounded_retry_does_not_turn_unavailable_receipt_into_profit():
    class RetryRpc:
        count=0
        def __call__(self,method,args):
            self.count+=1
            assert self.count<=2
            return None
    rpc=RetryRpc()
    pauses=[]
    row=dict(event(),untrusted_initialize_log_hint=False)
    result=m.inspect_one_hint_early(row,rpc,sleep=lambda s:pauses.append(s))
    assert pauses==[0.6]
    assert result["confirmed_receipt_retry_count"]==1
    assert result["status"]=="CONFIRMED_RECEIPT_NOT_YET_AVAILABLE"
    assert result["discovery_log_hint"] is False
    assert result["master_net_pnl_lamports"] is None
    assert rpc.count==2
