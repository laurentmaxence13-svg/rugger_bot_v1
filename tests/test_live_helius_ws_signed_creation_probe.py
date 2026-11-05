"""No-network tests: verified receipt classification never becomes a PAPER fill."""
from copy import deepcopy

import pytest

from bot.live import helius_ws_signed_creation_probe as mod
from bot.live.helius_ws_forward_paper import ReadOnlyLogAudit
from bot.p3.certification import _encode, PROGRAM
from bot.live.readonly_plan import MAINNET_GENESIS

SIGS = [_encode(bytes([n]) * 64) for n in (1, 2, 3, 4, 5, 6)]
KEYS = [_encode(bytes([n]) * 32) for n in range(10, 20)]


def capture():
    audit = ReadOnlyLogAudit(7, 20)
    for n, sig in enumerate(SIGS):
        is_hint = n in (1, 3)
        tx = dict(jsonrpc="2.0", method="logsNotification",
                  params=dict(subscription=7,
                      result=dict(context=dict(slot=1000 + n),
                          value=dict(signature=sig,
                              err={"InstructionError": [0]} if n == 2 else None,
                              logs=["Program log: Instruction: InitializeV2"]
                                  if is_hint else ["Program log: other"]))))
        audit.accept(tx, received_mono_ns=100000 + n,
                     received_utc_ns=10000000000 + n,
                     parsed_mono_ns=100001 + n)
    return audit.report(duration_ms=25100, handshake_ms=90), audit.events


def fake_tx(signature, slot):
    return dict(slot=slot, meta=dict(err=None),
                transaction=dict(signatures=[signature]))


class Rpc:
    count = 0
    def __init__(self, e):
        self.signatures = e
        self.calls = []
    def __call__(self, method, params):
        self.count += 1
        self.calls.append((method, params))
        if method == "getGenesisHash":
            return MAINNET_GENESIS
        assert method == "getTransaction"
        sig = params[0]
        item = next(r for r in self.signatures if r["signature"] == sig)
        return fake_tx(sig, item["slot"])


def fake_verified_crypto(_):
    return dict(cryptographic_signatures_verified=True,
                exact_message_sha256="d" * 64)


def fake_compiled(_):
    accounts = [
        dict(pubkey=KEYS[i], signer=i in (0, 1)) for i in range(5)]
    accounts.append(dict(pubkey=PROGRAM, signer=False))
    return dict(transaction=dict(message=dict(accountKeys=accounts)))


def fake_creations(_):
    return [dict(payer=KEYS[0], creator=KEYS[1],
                 pool_state=KEYS[2], mint=KEYS[3])]


def test_forward_classification_reports_signed_candidates_without_inventing_fills(monkeypatch):
    report, events = capture()
    monkeypatch.setattr(mod, "verify_compiled_rpc_signatures",
                        fake_verified_crypto)
    monkeypatch.setattr(mod, "normalized_compiled_transaction",
                        fake_compiled)
    monkeypatch.setattr(mod, "compiled_launchlab_creations", fake_creations)
    rpc = Rpc(events)
    result = mod.inspect_forward_creations(report, events, rpc)
    assert result["first_phase_captured_logs"] == 6
    assert result["selected_for_finalized_receipt"] == 5
    assert result["selected_before_receipt_lookup"] is True
    assert result["signed_creation_candidate_transactions"] == 5
    assert result["status_counts"]["FAILED_ON_CHAIN_IN_WS_NOTIFICATION"] == 1
    assert result["status_counts"].get("NOT_INSPECTED_RPC_BUDGET", 0) == 0
    assert [q[1][0] for q in rpc.calls if q[0] == "getTransaction"] == [
        SIGS[1], SIGS[3], SIGS[0], SIGS[4], SIGS[5]]
    assert result["market_price_at_decision_verified"] is False
    assert result["economically_qualified_cycles"] == 0
    assert result["financial_order_submitted"] is False
    assert result["live_ready_to_arm"] is False


def test_no_creation_is_factual_result_not_rpc_failure(monkeypatch):
    report, events = capture()
    monkeypatch.setattr(mod, "verify_compiled_rpc_signatures",
                        fake_verified_crypto)
    monkeypatch.setattr(mod, "normalized_compiled_transaction",
                        fake_compiled)
    monkeypatch.setattr(mod, "compiled_launchlab_creations", lambda _: [])
    result = mod.inspect_forward_creations(report, events, Rpc(events))
    assert result["signed_creation_candidate_transactions"] == 0
    assert result["status_counts"]["VERIFIED_NON_CREATION"] == 5
    assert result["economic_edge_validated"] is False


def test_mutation_of_captured_event_refused_before_rpc_lookup():
    report, events = capture()
    changes = deepcopy(events)
    changes[0]["slot"] = 2000
    rpc = Rpc(events)
    with pytest.raises(ValueError, match="hash_chain"):
        mod.inspect_forward_creations(report, changes, rpc)
    assert rpc.calls == []


def test_duplicate_untrusted_signature_refused():
    report, events = capture()
    changes = deepcopy(events)
    changes[0]["signature"] = changes[1]["signature"]
    with pytest.raises(ValueError, match="duplicate_forward_signature"):
        mod.inspect_forward_creations(report, changes, Rpc(events))


def test_bad_genesis_refused_after_capture_validation():
    report, events = capture()
    class Wrong:
        def __call__(self, method, params):
            assert method == "getGenesisHash"
            return KEYS[4]
    with pytest.raises(ValueError, match="verified_mainnet_genesis"):
        mod.inspect_forward_creations(report, events, Wrong())


def test_fee_payer_not_compiled_signer_rejected(monkeypatch):
    report, events = capture()
    monkeypatch.setattr(mod, "verify_compiled_rpc_signatures",
                        fake_verified_crypto)
    monkeypatch.setattr(mod, "normalized_compiled_transaction",
                        lambda _: dict(transaction=dict(message=dict(
                            accountKeys=[dict(pubkey=KEYS[i], signer=False)
                                         for i in range(5)] +
                                        [dict(pubkey=PROGRAM, signer=False)]))))
    monkeypatch.setattr(mod, "compiled_launchlab_creations", fake_creations)
    result = mod.inspect_forward_creations(report, events, Rpc(events))
    assert result["status_counts"]["SIGNATURE_OR_CREATION_IDENTITY_REFUSED"] == 5
    assert all(r["refusal_phase"] == "creation_payer_identity" and
               r["refusal_code"] == "verified_compiled_creation_identity_mismatch"
               for r in result["records"] if r["status"] ==
               "SIGNATURE_OR_CREATION_IDENTITY_REFUSED")
    assert result["signed_creation_candidate_transactions"] == 0


def test_no_initial_logs_no_rpc_transaction_lookup():
    audit = ReadOnlyLogAudit(3, 10)
    report = audit.report(duration_ms=10, handshake_ms=5)
    result = mod.inspect_forward_creations(report, [], Rpc([]))
    assert result["selected_for_finalized_receipt"] == 0
    assert result["signed_creation_candidate_transactions"] == 0
    assert result["status_counts"] == {}


def test_absent_compiled_creation_cannot_be_invented(monkeypatch):
    report, events = capture()
    monkeypatch.setattr(mod, "verify_compiled_rpc_signatures",
                        fake_verified_crypto)
    monkeypatch.setattr(mod, "normalized_compiled_transaction",
                        fake_compiled)
    monkeypatch.setattr(mod, "compiled_launchlab_creations", lambda _: [])
    result = mod.inspect_forward_creations(report, events, Rpc(events))
    assert result["signed_creation_candidate_transactions"] == 0
    assert result["status_counts"]["VERIFIED_NON_CREATION"] == 5
    assert result["economic_edge_validated"] is False


def test_v1_real_signed_wire_fallback_accepts_only_cryptographically_verified_outer(monkeypatch):
    from test_live_solana_v1_readonly import signed_receipt
    tx, sig = signed_receipt()
    audit = ReadOnlyLogAudit(7, 10)
    msg = dict(jsonrpc="2.0", method="logsNotification", params=dict(
        subscription=7, result=dict(context=dict(slot=10101),
            value=dict(signature=sig, err=None,
                       logs=["Program log: Instruction: InitializeV2"]))))
    assert audit.accept(msg, received_mono_ns=200000,
                        parsed_mono_ns=200010, received_utc_ns=100000000000)
    events = audit.events
    class V1Rpc:
        count = 0
        def __call__(self, method, params):
            self.count += 1
            if method == "getGenesisHash":
                return MAINNET_GENESIS
            assert method == "getTransaction" and params[0] == sig
            if params[1]["encoding"] == "base64":
                return tx
            assert params[1]["encoding"] == "json"
            return dict(fake_tx(sig, 10101), version=1)
    rpc = V1Rpc()
    result = mod.inspect_forward_creations(
        audit.report(duration_ms=1000, handshake_ms=30), events, rpc)
    assert result["signed_creation_candidate_transactions"] == 1
    assert result["status_counts"]["SIGNED_OUTER_CREATION_CANDIDATE"] == 1
    assert result["distinct_creator_claims_from_signed_transactions"] == 1
    assert rpc.count == 3
    assert result["economically_qualified_cycles"] == 0
    assert result["live_ready_to_arm"] is False


def test_eight_preselected_v1_double_receipts_respect_ten_call_budget(monkeypatch):
    report, events = capture()
    # All six are no-failure observations after dropping the single failed
    # websocket notification from the selection pool.
    class VersionOneRpc:
        def __init__(self):
            self.count=0
            self.last_rpc_error_code=None
        def __call__(self,method,params):
            self.count+=1
            assert self.count<=10
            if method=="getGenesisHash":return MAINNET_GENESIS
            assert method=="getTransaction"
            row=next(x for x in events if x["signature"]==params[0])
            if params[1]["encoding"]=="json":
                return dict(fake_tx(params[0],row["slot"]),version=1)
            return {"unused_mock_wire":True}
    monkeypatch.setattr(mod,"verify_v1_base64_receipt",lambda wire,**kwargs:
        dict(exact_message_sha256="d"*64,
             signer_public_keys=[KEYS[0]],
             launched_candidates=[]))
    rpc=VersionOneRpc()
    out=mod.inspect_forward_creations(report,events,rpc)
    assert out["selected_for_finalized_receipt"]==4
    assert out["inspection_candidates_preselected"]==5
    assert out["uninspected_due_to_rpc_budget"]==1
    assert out["status_counts"]["NOT_INSPECTED_RPC_BUDGET"]==1
    assert out["status_counts"]["VERIFIED_NON_CREATION"]==4
    assert rpc.count==9
    assert out["financial_order_submitted"] is False


def test_stratified_receipt_sample_uses_whole_websocket_window_not_first_eight(monkeypatch):
    audit=ReadOnlyLogAudit(7,100)
    for n in range(40):
        sig=_encode(bytes([n+20])*64)
        msg=dict(jsonrpc="2.0",method="logsNotification",
            params=dict(subscription=7,result=dict(
                context=dict(slot=3000+n),
                value=dict(signature=sig,err=None,logs=["Program log: no hint"]))))
        assert audit.accept(msg,received_mono_ns=1000000+n,
            received_utc_ns=200000000000+n,parsed_mono_ns=1000001+n)
    report=audit.report(duration_ms=30000,handshake_ms=10)
    events=audit.events
    monkeypatch.setattr(mod,"verify_compiled_rpc_signatures",fake_verified_crypto)
    monkeypatch.setattr(mod,"normalized_compiled_transaction",fake_compiled)
    monkeypatch.setattr(mod,"compiled_launchlab_creations",lambda _:[])
    result=mod.inspect_forward_creations(report,events,Rpc(events))
    selected={x["slot"] for x in result["records"]
              if x["status"]=="VERIFIED_NON_CREATION"}
    assert len(selected)==8
    assert min(selected)>3000
    assert max(selected)>3030
    assert result["status_counts"]["NOT_INSPECTED_RPC_BUDGET"]==32
    assert result["selection_rule"]=="initialize_hints_first_then_preoutcome_time_stratified_eight_finalized_receipts"
    assert result["financial_order_submitted"] is False
