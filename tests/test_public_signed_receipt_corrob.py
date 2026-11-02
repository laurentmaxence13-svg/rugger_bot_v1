"""Pinned independent public RPC proof contract (100% offline tests)."""
import json
from io import BytesIO
from unittest.mock import Mock

import pytest

from bot.live import public_signed_receipt_corrob as p


def transaction():
    return {
        "slot": p.EXPECTED_SLOT, "meta": {"err": None},
        "transaction": {"signatures": [p.EXPECTED_SIGNATURE],
                        "message": {"header": {"numRequiredSignatures": 1},
                                    "accountKeys": [p.EXPECTED_PAYER]}},
    }


class FakeReply:
    status = 200
    def __init__(self, payload):
        self.buffer = BytesIO(json.dumps(payload).encode("utf-8"))
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self, count):
        assert count == p.MAX_RESPONSE_BYTES + 1
        return self.buffer.read(count)


def test_one_bounded_public_read_only_get_transaction():
    calls = []
    def opener(request, *, timeout):
        assert request.full_url == p.PUBLIC_RPC
        assert request.get_method() == "POST"  # JSON-RPC read, never sendTransaction
        assert timeout == 15
        body = json.loads(request.data)
        assert body["method"] == "getTransaction"
        assert body["params"][0] == p.EXPECTED_SIGNATURE
        assert body["params"][1]["commitment"] == "finalized"
        assert not any("secret" in key.lower() or "api_key" in key.lower()
                       for key in request.headers)
        calls.append(body)
        return FakeReply({"jsonrpc": "2.0", "id": 1, "result": transaction()})
    assert p.fetch_one_public_transaction(opener=opener) == transaction()
    assert len(calls) == 1


def test_original_ed25519_receipt_and_signed_launch_must_match(monkeypatch):
    crypto = Mock(return_value={"cryptographic_signatures_verified": True,
                                "exact_message_sha256": p.EXPECTED_MESSAGE_SHA256})
    decoder = Mock(return_value=[{"creator": p.EXPECTED_CREATOR,
                                  "mint": p.EXPECTED_MINT,
                                  "pool_state": p.EXPECTED_POOL,
                                  "payer": p.EXPECTED_PAYER}])
    monkeypatch.setattr(p, "verify_compiled_rpc_signatures", crypto)
    monkeypatch.setattr(p, "compiled_launchlab_creations", decoder)
    result = p.check_pinned_public_receipt(transaction())
    crypto.assert_called_once()
    decoder.assert_called_once()
    assert result["status"] == "INDEPENDENT_ED25519_RECEIPT_VERIFIED"
    assert result["same_exact_message_sha256_as_archived_helius"] is True
    assert result["sol_native_pool_graph_verified"] is False
    assert result["master_paper_buy_sell_verified"] is False
    assert result["master_net_pnl_lamports"] is None
    assert result["financial_order_submitted"] is False


@pytest.mark.parametrize("alteration", [
    {"slot": 12},
    {"meta": {"err": "InstructionError"}},
    {"transaction": {"signatures": ["fake"]}},
    {"transaction": {"signatures": []}},
])
def test_unexpected_receipt_never_reaches_crypto(monkeypatch, alteration):
    crypto = Mock(side_effect=AssertionError("must not verify mismatched source"))
    monkeypatch.setattr(p, "verify_compiled_rpc_signatures", crypto)
    tx = transaction()
    tx.update(alteration)
    with pytest.raises((ValueError, IndexError)):
        p.check_pinned_public_receipt(tx)
    crypto.assert_not_called()


def test_wrong_message_hash_fail_closed_before_launch_decoding(monkeypatch):
    monkeypatch.setattr(p, "verify_compiled_rpc_signatures",
        lambda tx: {"cryptographic_signatures_verified": True,
                    "exact_message_sha256": "0" * 64})
    decoder = Mock()
    monkeypatch.setattr(p, "compiled_launchlab_creations", decoder)
    with pytest.raises(ValueError, match="independent_signed_message_hash_mismatch"):
        p.check_pinned_public_receipt(transaction())
    decoder.assert_not_called()


def test_unrelated_outer_launch_identity_fails_closed(monkeypatch):
    monkeypatch.setattr(p, "verify_compiled_rpc_signatures",
        lambda tx: {"cryptographic_signatures_verified": True,
                    "exact_message_sha256": p.EXPECTED_MESSAGE_SHA256})
    monkeypatch.setattr(p, "compiled_launchlab_creations",
        lambda tx: [{"creator": "wrong_creator", "mint": p.EXPECTED_MINT,
                     "pool_state": p.EXPECTED_POOL, "payer": p.EXPECTED_PAYER}])
    with pytest.raises(ValueError, match="independent_signed_launch_creation_not_matched"):
        p.check_pinned_public_receipt(transaction())


def test_missing_response_and_wrong_envelope_fail_closed():
    with pytest.raises(ValueError, match="historical_receipt_unavailable"):
        p.fetch_one_public_transaction(opener=lambda request, timeout:
            FakeReply({"jsonrpc": "2.0", "id": 1, "result": None}))


def test_default_cli_never_performs_network(monkeypatch, capsys):
    fetcher = Mock()
    monkeypatch.setattr(p, "fetch_one_public_transaction", fetcher)
    assert p.main([]) == 2
    fetcher.assert_not_called()
    assert "EXPLICIT_NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_public_rpc_error_redacted_without_private_information(monkeypatch, capsys):
    marker = "SECRET_API_KEY_SYNTHETIC_MUST_NOT_PRINT"
    monkeypatch.setattr(p, "fetch_one_public_transaction",
        lambda: (_ for _ in ()).throw(RuntimeError(marker)))
    assert p.main(["--network"]) == 2
    output = capsys.readouterr().out
    assert marker not in output
    assert '"status": "REFUSED"' in output


def test_signed_outer_creation_requires_same_payer_from_compiled_signers(monkeypatch):
    monkeypatch.setattr(p, "verify_compiled_rpc_signatures",
        lambda tx: {"cryptographic_signatures_verified": True,
                    "exact_message_sha256": p.EXPECTED_MESSAGE_SHA256})
    monkeypatch.setattr(p, "compiled_launchlab_creations",
        lambda tx: [{"creator": p.EXPECTED_CREATOR,
                     "mint": p.EXPECTED_MINT, "pool_state": p.EXPECTED_POOL,
                     "payer": p.EXPECTED_PAYER}])
    tx = transaction()
    tx["transaction"]["message"]["accountKeys"] = ["unrelated-signer"]
    with pytest.raises(ValueError, match="independent_signed_payer_not_present_in_message"):
        p.check_pinned_public_receipt(tx)


def test_inner_only_rpc_launch_does_not_pass_as_signed_creation(monkeypatch):
    monkeypatch.setattr(p, "verify_compiled_rpc_signatures",
        lambda tx: {"cryptographic_signatures_verified": True,
                    "exact_message_sha256": p.EXPECTED_MESSAGE_SHA256})
    def decoder(tx):
        if not tx["meta"].get("innerInstructions"):
            return []
        return [{"creator": p.EXPECTED_CREATOR,
                 "mint": p.EXPECTED_MINT, "pool_state": p.EXPECTED_POOL,
                 "payer": p.EXPECTED_PAYER}]
    monkeypatch.setattr(p, "compiled_launchlab_creations", decoder)
    tx = transaction()
    tx["meta"]["innerInstructions"] = [{"index": 0, "instructions": []}]
    with pytest.raises(ValueError, match="independent_signed_launch_creation_not_matched"):
        p.check_pinned_public_receipt(tx)
