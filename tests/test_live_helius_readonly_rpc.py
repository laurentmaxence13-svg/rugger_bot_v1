"""Offline security contract for secret-backed Helius public mainnet RPC."""
import json
import pytest

from bot.live.helius_readonly_rpc import (
    HeliusReadOnlyRpc, HELIUS_RPC_ID
)


KEY = "only-safe-test-HELIUS-token-0123456789"


class Response:
    status = 200
    def __init__(self, url, payload):
        self._url, self._payload = url, payload
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def geturl(self):
        return self._url
    def read(self, _):
        return self._payload


class Opener:
    def __init__(self, result=None):
        self.calls = []
        self.result = result
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        payload = json.loads(request.data)
        response = self.result if self.result is not None else dict(
            jsonrpc="2.0", id=payload["id"], result="test-genesis")
        return Response(request.full_url, json.dumps(response).encode())


def test_only_readonly_methods_allowed_before_http():
    opener = Opener()
    rpc = HeliusReadOnlyRpc(KEY, opener=opener, max_calls=2)
    for method in ("sendTransaction", "simulateTransaction",
                   "getSignaturesForAddress", "getPrivateKey"):
        with pytest.raises(ValueError, match="allowlisted"):
            rpc(method, [])
    assert rpc.count == 0
    assert opener.calls == []


def test_secret_is_never_in_repr_or_success_response():
    opener = Opener()
    rpc = HeliusReadOnlyRpc(KEY, opener=opener)
    assert rpc.endpoint == HELIUS_RPC_ID
    assert KEY not in repr(rpc)
    assert rpc("getGenesisHash", []) == "test-genesis"
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.full_url.startswith("https://mainnet.helius-rpc.com/?api-key=")
    assert timeout == 8
    assert request.get_method() == "POST"


@pytest.mark.parametrize("method", [
    "getTransaction", "getTokenLargestAccounts", "getMultipleAccounts"])
def test_other_read_only_methods_supported_without_wallet_secrets(method):
    opener = Opener()
    rpc = HeliusReadOnlyRpc(KEY, opener=opener)
    assert rpc(method, []) == "test-genesis"
    assert rpc.count == 1


def test_budget_blocks_extra_requests():
    opener = Opener()
    rpc = HeliusReadOnlyRpc(KEY, opener=opener, max_calls=1)
    assert rpc("getGenesisHash", []) == "test-genesis"
    with pytest.raises(ValueError, match="budget"):
        rpc("getGenesisHash", [])
    assert len(opener.calls) == 1


@pytest.mark.parametrize("key", ["", None, "COLLE_TA_CLE_ICI", "https://secret",
                                  "abc def", "bad?api-key=secret"])
def test_invalid_or_missing_helius_key_fails_before_request(key):
    with pytest.raises(ValueError, match="key"):
        HeliusReadOnlyRpc(key)


def test_invalid_rpc_reply_is_sanitized():
    opener = Opener(result=dict(jsonrpc="2.0", id=1,
                                error=dict(message="no-private-token")))
    rpc = HeliusReadOnlyRpc(KEY, opener=opener)
    with pytest.raises(ValueError, match="envelope") as exc:
        rpc("getGenesisHash", [])
    assert KEY not in str(exc.value)
    assert "no-private-token" not in str(exc.value)


def test_environment_reads_only_explicit_helius_secret(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", KEY)
    monkeypatch.setenv("PRIVATE_KEY", "must-never-use-wallet-private-key")
    rpc = HeliusReadOnlyRpc.from_environment()
    assert rpc.endpoint == HELIUS_RPC_ID
    assert KEY not in repr(rpc)


def test_unsigned_simulation_requires_explicit_opt_in():
    import base64
    wire=bytes([1])+bytes(64)+bytes([2])*70
    payload=[base64.b64encode(wire).decode(),dict(
        encoding="base64",sigVerify=False,replaceRecentBlockhash=False,
        commitment="confirmed",minContextSlot=100)]
    opener=Opener()
    rpc=HeliusReadOnlyRpc(KEY,opener=opener)
    with pytest.raises(ValueError,match="allowlisted"):
        rpc("simulateTransaction",payload)
    assert opener.calls==[]


def test_unsigned_simulation_rejects_nonzero_signatures_before_http():
    import base64
    wire=bytes([1])+bytes([42])*64+bytes([2])*70
    payload=[base64.b64encode(wire).decode(),dict(
        encoding="base64",sigVerify=False,replaceRecentBlockhash=False,
        commitment="confirmed",minContextSlot=100)]
    opener=Opener()
    rpc=HeliusReadOnlyRpc(KEY,opener=opener,allow_unsigned_preflight=True)
    with pytest.raises(ValueError,match="zero_signature"):
        rpc("simulateTransaction",payload)
    assert opener.calls==[]


def test_unsigned_simulation_never_allows_signature_verify_or_blockhash_replacement():
    import base64
    wire=bytes([1])+bytes(64)+bytes([2])*70
    args=[base64.b64encode(wire).decode(),dict(
        encoding="base64",sigVerify=False,replaceRecentBlockhash=False,
        commitment="confirmed",minContextSlot=100)]
    opener=Opener()
    rpc=HeliusReadOnlyRpc(KEY,opener=opener,allow_unsigned_preflight=True)
    for option,value in (("sigVerify",True),("replaceRecentBlockhash",True),
                         ("minContextSlot",0)):
        mutated=[args[0],dict(args[1])]
        mutated[1][option]=value
        with pytest.raises(ValueError,match="nonreplacing"):
            rpc("simulateTransaction",mutated)
    assert opener.calls==[]


def test_unsigned_simulation_with_zero_signatures_is_a_read_only_rpc():
    import base64
    wire=bytes([1])+bytes(64)+bytes([2])*70
    args=[base64.b64encode(wire).decode(),dict(
        encoding="base64",sigVerify=False,replaceRecentBlockhash=False,
        commitment="confirmed",minContextSlot=100)]
    opener=Opener()
    rpc=HeliusReadOnlyRpc(KEY,opener=opener,allow_unsigned_preflight=True)
    assert rpc("simulateTransaction",args)=="test-genesis"
    assert json.loads(opener.calls[0][0].data)["method"]=="simulateTransaction"
    assert KEY not in repr(rpc)


def test_helius_rpc_error_reports_only_numeric_code_and_method():
    opener=Opener(result=dict(jsonrpc="2.0",id=1,
                              error=dict(code=-32005,message="secret "+KEY)))
    rpc=HeliusReadOnlyRpc(KEY,opener=opener,allow_launch_discovery=True)
    with pytest.raises(ValueError,match="envelope") as raised:
        rpc("getSignaturesForAddress",[
            "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
            dict(limit=20,commitment="finalized")])
    assert rpc.last_method=="getSignaturesForAddress"
    assert rpc.last_rpc_error_code==-32005
    assert KEY not in repr(rpc)
    assert KEY not in str(raised.value)
