"""No-network PublicNode second-verifier proof and strict provenance contracts."""
import json
from io import BytesIO
from unittest.mock import Mock
import pytest

from bot.live import publicnode_signed_sol_creation as mod


class Reply:
    status=200
    def __init__(self,value):
        self.data=BytesIO(json.dumps(value).encode())
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return None
    def read(self,limit):
        assert limit==mod.MAX_RESPONSE+1
        return self.data.read(limit)


def rpc_tx():
    return dict(slot=mod.SLOT,
                meta=dict(err=None,innerInstructions=[{"index":0,"instructions":[]}]),
                transaction=dict(signatures=[mod.SIGNATURE],
                    message=dict(header=dict(numRequiredSignatures=1),
                        accountKeys=[mod.CREATOR])))


def test_second_provider_calls_only_two_known_public_read_methods():
    methods=[]
    def opener(req,*,timeout):
        assert req.full_url==mod.RPC and req.get_method()=="POST"
        assert timeout==12
        assert not any("key" in key.lower() for key in req.headers)
        body=json.loads(req.data)
        methods.append(body["method"])
        val="mainnet-genesis" if body["method"]=="getGenesisHash" else rpc_tx()
        return Reply(dict(jsonrpc="2.0",id=1,result=val))
    assert mod._rpc_once("getGenesisHash",[],opener=opener)=="mainnet-genesis"
    assert mod._rpc_once("getTransaction",[mod.SIGNATURE,dict(
        encoding="json",commitment="finalized",
        maxSupportedTransactionVersion=0)],opener=opener)==rpc_tx()
    assert methods==["getGenesisHash","getTransaction"]
    with pytest.raises(ValueError,match="second_provider_source_not_pinned"):
        mod._rpc_once("sendTransaction",["fake-wire"],opener=opener)
    assert len(methods)==2


def test_true_compiled_ed25519_verification_required(monkeypatch):
    crypto=Mock(return_value={"cryptographic_signatures_verified":True,
                              "exact_message_sha256":mod.MESSAGE_SHA256})
    parse=Mock(return_value=[dict(creator=mod.CREATOR,payer=mod.CREATOR,
        mint=mod.MINT,pool_state=mod.POOL)])
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",crypto)
    monkeypatch.setattr(mod,"compiled_launchlab_creations",parse)
    calls=[]
    def rpc(method,params):
        calls.append(method)
        if method=="getGenesisHash":
            return mod.MAINNET_GENESIS
        assert method=="getTransaction"
        return rpc_tx()
    result=mod.verify_second_provider(rpc=rpc)
    assert calls==["getGenesisHash","getTransaction"]
    assert crypto.call_count==1 and parse.call_count==1
    assert parse.call_args.args[0]["meta"]["innerInstructions"]==[]
    assert result["status"]=="PUBLICNODE_REVERIFIED_SAME_NATIVE_SOL_CREATION"
    assert result["financial_order_submitted"] is False
    assert result["genuine_Master_PAPER_buy_sell_verified"] is False
    assert result["master_net_pnl_lamports"] is None


def test_wrong_genesis_refused_before_looking_up_transaction():
    def rpc(method,params):
        assert method=="getGenesisHash"
        return "another-chain"
    with pytest.raises(ValueError,match="second_provider_genesis_invalid"):
        mod.verify_second_provider(rpc=rpc)


def test_hash_mismatch_never_reaches_outer_parser(monkeypatch):
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",
        lambda tx:dict(cryptographic_signatures_verified=True,
                       exact_message_sha256="0"*64))
    parser=Mock(side_effect=AssertionError("should not use launch"))
    monkeypatch.setattr(mod,"compiled_launchlab_creations",parser)
    def rpc(method,params):
        return mod.MAINNET_GENESIS if method=="getGenesisHash" else rpc_tx()
    with pytest.raises(ValueError,match="second_provider_compiled_message_not_equal"):
        mod.verify_second_provider(rpc=rpc)
    parser.assert_not_called()


def test_inner_only_provider_claim_cannot_pass_as_signed_outer_creation(monkeypatch):
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",
        lambda tx:dict(cryptographic_signatures_verified=True,
                       exact_message_sha256=mod.MESSAGE_SHA256))
    def parse(tx):
        return [] if not tx["meta"]["innerInstructions"] else [
            dict(creator=mod.CREATOR,payer=mod.CREATOR,mint=mod.MINT,pool_state=mod.POOL)]
    monkeypatch.setattr(mod,"compiled_launchlab_creations",parse)
    def rpc(method,params):
        return mod.MAINNET_GENESIS if method=="getGenesisHash" else rpc_tx()
    with pytest.raises(ValueError,match="second_provider_signed_creation_identity_mismatch"):
        mod.verify_second_provider(rpc=rpc)


def test_unsupported_payer_never_qualifies_even_with_signed_message(monkeypatch):
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",
        lambda tx:dict(cryptographic_signatures_verified=True,
                       exact_message_sha256=mod.MESSAGE_SHA256))
    monkeypatch.setattr(mod,"compiled_launchlab_creations",lambda tx:[
        dict(creator=mod.CREATOR,payer=mod.CREATOR,mint=mod.MINT,pool_state=mod.POOL)])
    def rpc(method,params):
        if method=="getGenesisHash":
            return mod.MAINNET_GENESIS
        tx=rpc_tx()
        tx["transaction"]["message"]["accountKeys"]=["not-the-payer"]
        return tx
    with pytest.raises(ValueError,match="second_provider_signed_creation_identity_mismatch"):
        mod.verify_second_provider(rpc=rpc)


def test_no_network_without_explicit_optin(monkeypatch,tmp_path,capsys):
    task=Mock()
    monkeypatch.setattr(mod,"verify_second_provider",task)
    assert mod.main(["--output-file",str(tmp_path/"proof.json")])==2
    task.assert_not_called()
    assert "EXPLICIT_NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_failure_redacts_untrusted_secret_string(monkeypatch,tmp_path,capsys):
    marker="untrusted-credential-DEMO_NOT_A_REAL_KEY"
    monkeypatch.setattr(mod,"verify_second_provider",
        lambda: (_ for _ in ()).throw(RuntimeError(marker)))
    assert mod.main(["--network","--output-file",str(tmp_path/"proof.json")])==2
    assert marker not in capsys.readouterr().out
    assert not (tmp_path/"proof.json").exists()
