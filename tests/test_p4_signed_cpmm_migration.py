"""LaunchLab->CPMM migration must be signed outer instruction, never index hint."""
from copy import deepcopy
import pytest

from bot.p3.certification import _encode,PROGRAM
from bot.p3.quotes import SOL_MINT
from bot.p4.signed_cpmm_migration import signed_cpswap_mapping,DISC
from bot.p4.cpmm_quote_adapter import CPMM_MAINNET

MINT="fixture-base-mint"
OLD="fixture-old-pool"
NEW="fixture-new-cpmm-pool"


def signed_fixture():
    keys=[dict(pubkey="placeholder-"+str(i),signer=False,writable=False)
          for i in range(30)]
    keys[0]=dict(pubkey="verified-payer",signer=True,writable=True)
    keys[1]["pubkey"]=MINT
    keys[2]["pubkey"]=SOL_MINT
    keys[4]["pubkey"]=CPMM_MAINNET
    keys[5]=dict(pubkey=NEW,signer=False,writable=True)
    keys[17]["pubkey"]=OLD
    keys[29]["pubkey"]=PROGRAM
    return dict(slot=400,meta=dict(err=None),
        transaction=dict(message=dict(accountKeys=keys,
            instructions=[dict(programIdIndex=29,
                accounts=list(range(28)),data=_encode(DISC))])))


def mocked_signature(monkeypatch):
    def validated(tx):
        assert tx["slot"]>0
        return dict(cryptographic_signatures_verified=True,
                    exact_message_sha256="a"*64)
    monkeypatch.setattr("bot.p4.signed_cpmm_migration.verify_compiled_rpc_signatures",
                        validated)


def certify(tx):
    return signed_cpswap_mapping(transaction=tx,
        expected_mint=MINT,expected_curve_pool=OLD,
        expected_cpmm_pool=NEW)


def test_canonical_migration_discriminator_and_outer_account_mapping(monkeypatch):
    mocked_signature(monkeypatch)
    assert list(DISC)==[136,92,200,103,28,218,144,140]
    result=certify(signed_fixture())
    p=result["proof"]
    assert p["from_pool"]==OLD and p["to_pool"]==NEW
    assert p["signed_transaction_verified"] is True
    assert p["transaction_sha256"]=="a"*64
    assert result["independently_verified_chain_inclusion"] is False
    assert result["economic_cpmm_exit_quote_not_yet_qualified"] is True
    assert result["financial_order_submitted"] is False


@pytest.mark.parametrize("idx,replacement",[
    (1,"wrong-mint"),(2,"wrong-quote"),(4,"wrong-cpmm-program"),
    (5,"wrong-cpmm-pool"),(17,"wrong-old-pool")])
def test_wrong_signed_account_identity_refused(monkeypatch,idx,replacement):
    mocked_signature(monkeypatch)
    tx=signed_fixture()
    tx["transaction"]["message"]["accountKeys"][idx]["pubkey"]=replacement
    with pytest.raises(ValueError,match="signed_migration_pool_identity_disagreement"):
        certify(tx)


def test_migration_hint_inner_or_failed_transaction_never_qualifies(monkeypatch):
    mocked_signature(monkeypatch)
    tx=signed_fixture()
    tx["meta"]["err"]={"InstructionError":[0,"custom"]}
    with pytest.raises(ValueError,match="successful_source_transaction"):
        certify(tx)
    tx=signed_fixture()
    tx["transaction"]["message"]["instructions"][0]["data"]=_encode(b"not-migra")
    with pytest.raises(ValueError,match="exactly_one_signed_outer"):
        certify(tx)
    tx=signed_fixture()
    tx["transaction"]["message"]["accountKeys"][0]["signer"]=False
    with pytest.raises(ValueError,match="signed_migration_pool_identity_disagreement"):
        certify(tx)


def test_no_proof_when_message_signature_verification_fails(monkeypatch):
    monkeypatch.setattr("bot.p4.signed_cpmm_migration.verify_compiled_rpc_signatures",
                        lambda *a:dict(cryptographic_signatures_verified=False))
    with pytest.raises(ValueError,match="signed_launchlab_migration_message"):
        certify(signed_fixture())
