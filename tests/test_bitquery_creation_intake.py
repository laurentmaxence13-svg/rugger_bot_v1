"""Bitquery discovery hints only: independent signature proof and causal boundaries."""
import copy
import pytest
from bot.p3 import bitquery_creation_intake as mod
from bot.p3.certification import PROGRAM
from bot.live.readonly_plan import MAINNET_GENESIS

CREATOR="26H5Js9rJRQvg9wWoPZHzs8tbk1XdwfQUrGZ2Rxsk9RY"
MINT="5AWBTmZzYZ3twtKQLe1eziWw9yMcUyUiR6iRnCpXPv7f"
POOL="EwZxoy5QpQBxo13AHp9fvh11f49CanyFJXXmpSjVtpbP"
SOL="So11111111111111111111111111111111111111112"
SIGNATURE="3"*88


def row(signature=SIGNATURE,slot=100,method="initialize_v2",pool=POOL):
    addresses=[SOL,CREATOR,SOL,SOL,SOL,pool,MINT]
    return dict(Block=dict(Time="2026-11-01T00:00:00Z",Slot=slot),
        Transaction=dict(Signature=signature,Signer=CREATOR),
        Instruction=dict(Index=0,Program=dict(
            Address=PROGRAM,Method=method,AccountNames=[]),
            Accounts=[{"Address":x} for x in addresses]))


def payload(*records):
    return dict(data=dict(Solana=dict(Instructions=list(records))))


def test_extraction_does_not_claim_executable_trades():
    r=mod.parse_bitquery_creation_response(payload(row()))
    assert r["candidates"]==1
    assert r["signed_creations_verified"]==0
    assert r["source_block_time_not_source_availability"] is True
    assert r["claims"][0]["reported_mint"]==MINT
    assert r["claims"][0]["reported_pool"]==POOL
    assert r["claims"][0]["reported_creator"]==CREATOR
    assert r["claims"][0]["provider_available_at_ms"] is None
    assert r["claims"][0]["asof_master_decision_possible"] is False
    assert r["master_net_pnl_lamports"] is None
    assert r["financial_order_submitted"] is False


@pytest.mark.parametrize("method",[
    "initialize_v2","initialize_with_token_2022","initialize_with_token2022"])
def test_all_documented_new_launch_methods_are_discovery_hints(method):
    r=mod.parse_bitquery_creation_response(payload(row(method=method)))
    assert r["candidates"]==1


def test_non_create_instruction_filtered_no_trades():
    r=mod.parse_bitquery_creation_response(payload(row(method="buy_exact_in")))
    assert r["candidates"]==0
    assert r["rows_discarded_or_duplicated"]==1


def test_duplicate_same_signature_reconciles_one():
    r=mod.parse_bitquery_creation_response(payload(row(),row()))
    assert r["candidates"]==1
    assert r["rows_discarded_or_duplicated"]==1


def test_conflicting_mint_or_pool_refuses():
    a=row();b=row(pool=SOL)
    with pytest.raises(ValueError,match="conflicting_creation"):
        mod.parse_bitquery_creation_response(payload(a,b))


@pytest.mark.parametrize("change",[
    lambda r:r["Block"].update(Slot=-1),
    lambda r:r["Block"].update(Time="2026-11-01 00:00"),
    lambda r:r["Instruction"].update(Accounts=[{"Address":SOL}]*6),
    lambda r:r["Transaction"].update(Signature="invalid!"),
    lambda r:r["Instruction"].update(Index=-1),
])
def test_malformed_rows_refused(change):
    a=row();change(a)
    with pytest.raises(ValueError):
        mod.parse_bitquery_creation_response(payload(a))


def test_provider_graphql_errors_are_not_empty_results():
    r=payload()
    r["errors"]=[{"message":"Rate limit exceeded"}]
    with pytest.raises(ValueError,match="graphql_errors"):
        mod.parse_bitquery_creation_response(r)


def test_exact_empty_response_stays_unknown_denominator():
    r=mod.parse_bitquery_creation_response(payload())
    assert r["candidates"]==0
    assert r["source_universe_completeness_verified"] is False


class Rpc:
    def __init__(self,raw=None,genesis=MAINNET_GENESIS):
        self.raw=raw;self.genesis=genesis;self.calls=[]
    def __call__(self,method,args):
        self.calls.append((method,args))
        if method=="getGenesisHash":
            assert args==[]
            return self.genesis
        assert method=="getTransaction"
        assert args[0]==SIGNATURE
        assert args[1]==dict(
            encoding="json",commitment="finalized",
            maxSupportedTransactionVersion=1)
        return self.raw


def test_verified_signed_exact_identity_cannot_claim_master_profit(monkeypatch):
    def proof(raw,sig,slot,rpc,*,commitment):
        assert commitment=="finalized"
        assert sig==SIGNATURE and slot==100
        return dict(message_sha256="a"*64,
            launches=[dict(mint=MINT,creator=CREATOR,pool=POOL)])
    monkeypatch.setattr(mod,"signed_receipt_proof",proof)
    r=mod.verify_bitquery_candidates(
        mod.parse_bitquery_creation_response(payload(row())),Rpc(raw={"faux":"receipt"}))
    assert r["verified_signed_creations"]==1
    assert r["independent_creator_ids"]==1
    assert r["asof_entry_quotes_available"] is False
    assert r["master_net_pnl_lamports"] is None
    assert r["qualified_economic_cycles"]==0
    assert r["financial_order_submitted"] is False


def test_discordant_signed_identity_refused(monkeypatch):
    monkeypatch.setattr(mod,"signed_receipt_proof",
        lambda *args,**kwargs:dict(message_sha256="a"*64,
            launches=[dict(mint=MINT,creator=CREATOR,pool=SOL)]))
    r=mod.verify_bitquery_candidates(
        mod.parse_bitquery_creation_response(payload(row())),Rpc(raw={}))
    assert r["records"][0]["status"]=="BITQUERY_SIGNED_IDENTITY_DISAGREEMENT"
    assert r["verified_signed_creations"]==0


def test_verified_noncreation_not_fabricated_as_creator(monkeypatch):
    monkeypatch.setattr(mod,"signed_receipt_proof",
        lambda *args,**kwargs:dict(message_sha256="a"*64,launches=[]))
    r=mod.verify_bitquery_candidates(
        mod.parse_bitquery_creation_response(payload(row())),Rpc(raw={}))
    assert r["records"][0]["status"]=="VERIFIED_NON_CREATION"
    assert r["verified_signed_creations"]==0


def test_missing_receipt_stays_unverified():
    rpc=Rpc()
    r=mod.verify_bitquery_candidates(mod.parse_bitquery_creation_response(
        payload(row())),rpc)
    assert r["records"][0]["status"]=="FINALIZED_RECEIPT_UNAVAILABLE"
    assert r["verified_signed_creations"]==0
    assert len(rpc.calls)==2


def test_invalid_genesis_rejected_without_transaction_lookup():
    rpc=Rpc(genesis="other")
    with pytest.raises(ValueError,match="mainnet_genesis"):
        mod.verify_bitquery_candidates(mod.parse_bitquery_creation_response(
            payload(row())),rpc)
    assert len(rpc.calls)==1


def test_unsigned_external_input_cannot_self_authorize_trading():
    intake=mod.parse_bitquery_creation_response(payload(row()))
    intake["claims"][0]["is_cryptographically_verified"]=True
    with pytest.raises(ValueError,match="self_verified"):
        mod.verify_bitquery_candidates(intake,Rpc())
