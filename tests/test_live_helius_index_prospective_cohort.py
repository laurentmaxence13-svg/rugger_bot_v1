"""Strict no-network preregistered mainnet cohort tests."""
from copy import deepcopy
import json
import pytest
from bot.p3 import helius_index_prospective_cohort as c
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.quotes import SOL_MINT
from bot.p3.certification import _encode

def addr(n): return _encode(bytes([n])*32)
def row(n,creator):
    return dict(mint=addr(n),poolId=addr(n+30),
                creator=addr(creator),mintB=dict(address=SOL_MINT),
                createAt=1000)

def test_index_denominator_preserves_duplicates_and_invalid_candidates():
    rows=[row(1,90),row(2,90),row(3,91),row(4,92),row(5,93),
          dict(mint="untrusted"),row(3,94)]
    receipt=c.register_prebank_universe(rows)
    assert len(receipt["denominator"])==7
    assert [x["index"] for x in receipt["selected"]]==[0,2,3]
    assert receipt["denominator"][1]["selection_reason"]=="duplicate_mint_pool_or_creator_claim"
    assert receipt["denominator"][4]["selection_reason"]=="outside_first_three_distinct_creator_claims"
    assert receipt["denominator"][5]["selection_reason"]=="unsupported_or_unidentified_index_row"
    assert receipt["selection_precedes_all_RPC_account_prices"] is True
    assert receipt["claimed_creator_not_verified_by_signed_creation"] is True

def test_incomplete_and_wrong_genesis_never_count_as_pnl():
    class Wrong:
        def __init__(self):self.methods=[]
        def __call__(self,method,params):
            self.methods.append(method); return "wrong"
    rpc=Wrong()
    with pytest.raises(ValueError,match="wrong_chain"):
        c.prospective_index_cohort(rpc,[row(1,90)],sleep=lambda _:None,wait_seconds=1)
    assert rpc.methods==["getGenesisHash"]

def test_empty_index_is_explicit_gap_not_qualified_sample():
    class Rpc:
        def __call__(self,method,params):
            assert method=="getGenesisHash"
            return MAINNET_GENESIS
    out=c.prospective_index_cohort(Rpc(),[],sleep=lambda _:None,wait_seconds=1)
    assert out["status"]=="NO_QUALIFIED_INDEX_LEADS"
    assert out["economic_cycles"]==0
    assert out["live_ready_to_arm"] is False

def test_two_banks_keep_claimed_creator_unqualified(monkeypatch,capsys):
    addresses={k:addr(i+100) for i,k in enumerate(
        ("pool","config","platform","mint_a","mint_b","vault_a","vault_b"))}
    addresses["mint_b"]=SOL_MINT
    rows=[row(1,90)]
    def addresses_from_pool(account,mint,pool):
        assert account==dict(root=1)
        return dict(addresses,pool=pool)
    monkeypatch.setattr(c,"addresses_from_pool",addresses_from_pool)
    monkeypatch.setattr(c,"analyze_snapshot",lambda ac,**kw:dict(
        schema="synthetic",identity_status="identity_verified",
        evidence_profile="published_metadata_v1",blocking_reasons=[],
        conditional_projection=(None if kw.get("compute_projection") is False
            else dict(buy_output_atomic="200")),
        risk_flags=[],facts=dict(pool=dict(status=0),config=dict(
            trade_fee_rate_ppm=2500,curve_type=0),
            platform=dict(platform_fee_rate_ppm=0,creator_fee_rate_ppm=0),
            quote_vault=dict(amount_atomic="10000000"))))
    monkeypatch.setattr(c,"observed_sell_projection",lambda *_,**kw:
                         dict(output_lamports="9000000"))
    class Rpc:
        def __init__(self):self.count=0;self.events=[]
        def __call__(self,method,params):
            self.count+=1;self.events.append(method)
            if method=="getGenesisHash":return MAINNET_GENESIS
            if self.count==2:
                return dict(context=dict(slot=200),
                    value=[dict(root=1)])
            if self.count==3:
                return dict(context=dict(slot=201),
                    value=[dict(state="S1") for _ in params[0]])
            assert self.count==4
            assert params[1]["minContextSlot"]==202
            assert "COHORT_REGISTERED_BEFORE_FUTURE_BANK" in capsys.readouterr().out
            return dict(context=dict(slot=202),
                value=[dict(state="S2") for _ in params[0]])
    rpc=Rpc()
    result=c.prospective_index_cohort(rpc,rows,
        sleep=lambda _:None,wait_seconds=1)
    assert result["status"]=="INDEX_FIRST_PROSPECTIVE_CAPTURE_COMPLETE"
    assert result["observed"][0]["conditional_sell_lamports"]==9000000
    assert result["observed"][0]["conditional_gross_markout_lamports"]==-1000000
    assert result["claim_only_creator_count"]==1
    assert result["signed_creator_qualification_count"]==0
    assert result["independent_creators_economically_qualified"]==0
    assert result["master_vs_baseline_edge_validated"] is False
    assert result["actual_buy_sell_cycles"]==0
    assert result["financial_order_submitted"] is False
    assert result["rpc_calls_used"]==4

def test_corrupt_s2_bank_cannot_be_relabelled_economic_win(monkeypatch):
    monkeypatch.setattr(c,"addresses_from_pool",lambda *_:dict(
        pool=addr(31),config=addr(41),platform=addr(42),
        mint_a=addr(1),mint_b=SOL_MINT,vault_a=addr(43),vault_b=addr(44)))
    monkeypatch.setattr(c,"analyze_snapshot",lambda *_,**kw:dict(
        evidence_profile="published_metadata_v1",
        conditional_projection=dict(buy_output_atomic="200"),
        risk_flags=[],blocking_reasons=[],identity_status="unverified",
        facts={} if kw.get("compute_projection") is False else dict()))
    class Rpc:
        def __init__(self):self.count=0
        def __call__(self,method,params):
            self.count+=1
            if self.count==1:return MAINNET_GENESIS
            return dict(context=dict(slot=200+self.count),
                        value=[dict(placeholder=True) for _ in params[0]])
    result=c.prospective_index_cohort(Rpc(),[row(1,90)],
                                      sleep=lambda _:None,wait_seconds=1)
    assert result["observed"][0]["s2_refusal"]=="observed_s2_exit_unqualified"
    assert result["strict_economic_cycles"]==0
    assert result["live_ready_to_arm"] is False

def test_index_fetch_does_not_follow_redirect_or_enlarge_body():
    class Response:
        status=200
        def __init__(self,body):self._body=body
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def geturl(self):return c.INDEX_URL+"?sort=new"
        def read(self,_):return self._body
    class Opener:
        def __init__(self,body):self.body=body
        def open(self,request,timeout):
            assert timeout==8
            assert request.get_method()=="GET"
            return Response(self.body)
    raw=json.dumps(dict(success=True,data=dict(rows=[row(1,90)]))).encode()
    assert len(c.fetch_index(opener=Opener(raw)))==1
    with pytest.raises(ValueError,match="maximum"):
        c.fetch_index(opener=Opener(b"x"*1_000_001))
