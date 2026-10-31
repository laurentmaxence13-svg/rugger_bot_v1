"""Verify captured Helius WebSocket program logs with LATER finalized receipts.

This is an observation classifier, not a real-time trade decision engine.
All signatures originate in an immutable, hashed, bounded log capture; a
preexisting log hint selects at most eight events before seeing tx outcomes.
Exact compiled Solana Ed25519 bytes, not optional parsed RPC metadata,
qualify outer LaunchLab instructions; inner instructions remain RPC claims.
Only public data, read-only RPC. Missing receipts and failed tx remain counted.
"""
import json
import os
import sys
from pathlib import Path

from bot.p3.certification import PROGRAM
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_launchlab_cohort_probe import RAW_OPTS
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.live.solana_v1_readonly import verify_v1_base64_receipt
from bot.p3.platform_admin_history import _signature
from bot.live.helius_ws_forward_paper import _hash

MAX_INSPECTIONS = 8
MAX_EVENTS = 100


def _verify_capture(report, events):
    if (type(report) is not dict or type(events) is not list or
            report.get("schema") != "rugger-helius-program-log-forward-paper-v1" or
            report.get("source_program") != PROGRAM or
            report.get("source_commitment") != "confirmed" or
            report.get("status") not in ("LOGS_OBSERVED", "NO_LOGS_OBSERVED") or
            report.get("financial_order_submitted") is not False or
            report.get("live_ready_to_arm") is not False or
            type(report.get("events_received_unique")) is not int or
            report["events_received_unique"] != len(events) or
            len(events) > MAX_EVENTS):
        raise ValueError("invalid_forward_capture_header")
    digest = "0" * 64
    seen = set()
    for event in events:
        if (type(event) is not dict or
                type(event.get("slot")) is not int or event["slot"] <= 0 or
                type(event.get("on_chain_transaction_failed")) is not bool or
                type(event.get("untrusted_initialize_log_hint")) is not bool or
                type(event.get("reception_monotonic_ns")) is not int or
                type(event.get("reception_utc_ns")) is not int or
                event["reception_monotonic_ns"] <= 0 or
                event["reception_utc_ns"] <= 0 or
                event.get("filled") is not False):
            raise ValueError("invalid_forward_log_record")
        sig = _signature(event.get("signature"))
        if sig in seen:
            raise ValueError("duplicate_forward_signature")
        seen.add(sig)
        digest = _hash(dict(previous=digest, event=event))
    if digest != report.get("signature_ledger_sha256"):
        raise ValueError("forward_evidence_hash_chain_invalid")


def inspect_forward_creations(report, events, rpc):
    """Read only after the WebSocket window closes; NOT a causal as-of quote."""
    _verify_capture(report, events)
    if not callable(rpc) or rpc("getGenesisHash", []) != MAINNET_GENESIS:
        raise ValueError("verified_mainnet_genesis_required")
    # Selection depends exclusively on evidence captured before tx lookup,
    # not on future outcomes. Prefer explicit untrusted Initialize hints.
    candidates = [e for e in events if not e["on_chain_transaction_failed"]]
    candidates.sort(key=lambda e: 0 if e["untrusted_initialize_log_hint"] else 1)
    chosen = candidates[:MAX_INSPECTIONS]
    selected = {e["signature"] for e in chosen}
    records = []
    for e in events:
        records.append(dict(signature=e["signature"], slot=e["slot"],
            reception_utc_ns=e["reception_utc_ns"],
            untrusted_initialize_log_hint=e["untrusted_initialize_log_hint"],
            status=("FAILED_ON_CHAIN_IN_WS_NOTIFICATION"
                    if e["on_chain_transaction_failed"] else
                    "SELECTED_FOR_FINALIZED_RECEIPT"
                    if e["signature"] in selected else
                    "NOT_INSPECTED_RPC_BUDGET")))
    keyed = {item["signature"]: item for item in records}
    distinct_creators = set()
    inspected = 0
    for item in chosen:
        sig = item["signature"]
        receipt = keyed[sig]
        # Reserve capacity for a version-1 JSON+binary proof pair. RPC
        # calls after this point must never exceed the explicit call cap.
        # A missing call-count API is refused rather than silently unbounded.
        used = getattr(rpc, 'count', None)
        if type(used) is not int or used < 0:
            raise ValueError('verified_rpc_call_budget_missing')
        if used > 8:
            receipt['status'] = 'NOT_INSPECTED_RPC_BUDGET'
            continue
        inspected += 1
        try:
            raw = rpc("getTransaction", [sig, RAW_OPTS])
        except ValueError as exc:
            if (str(exc) == "helius_rpc_envelope_refused" and
                    getattr(rpc, "last_rpc_error_code", None) == -32015):
                receipt["status"] = "RAW_TX_VERSION_UNSUPPORTED"
                continue
            raise
        if raw is None:
            receipt["status"] = "FINALIZED_RECEIPT_UNAVAILABLE"
            continue
        if (type(raw) is not dict or
                raw.get("slot") != item["slot"] or
                type(raw.get("meta")) is not dict or
                raw["meta"].get("err") is not None or
                raw.get("transaction", {}).get("signatures", [None])[0] != sig):
            receipt["status"] = "FINALIZED_RECEIPT_MISMATCH"
            continue
        if type(raw.get("version")) is int and raw["version"] == 1:
            # v1 uses a different signed wire structure. Never force the
            # legacy/v0 reserializer onto v1 or treat a provider parser's
            # account claims as cryptographic proof.
            try:
                encoded = rpc("getTransaction", [sig, dict(
                    encoding="base64", commitment="finalized",
                    maxSupportedTransactionVersion=1)])
                v1 = verify_v1_base64_receipt(
                    encoded, expected_signature=sig,
                    expected_slot=item["slot"])
                receipt["exact_message_sha256"] = v1["exact_message_sha256"]
                receipt["cryptographic_signature_verified"] = True
                receipt["version"] = 1
                if v1["launched_candidates"]:
                    if any(x["payer"] not in v1["signer_public_keys"]
                           for x in v1["launched_candidates"]):
                        raise ValueError("v1_creation_payer_not_signer")
                    receipt["status"] = "SIGNED_OUTER_CREATION_CANDIDATE"
                    receipt["launches"] = v1["launched_candidates"]
                    distinct_creators.update(
                        x["creator"] for x in v1["launched_candidates"])
                else:
                    receipt["status"] = "VERIFIED_NON_CREATION"
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                code = str(exc)
                allowlisted = frozenset((
                    "v1_exact_ed25519_message_invalid",
                    "v1_signature_tail_length_invalid",
                    "v1_wire_prefix_or_length_invalid",
                    "v1_rpc_receipt_version_slot_or_status_invalid",
                    "v1_expected_first_signature_mismatch",
                    "v1_unknown_config_mask_bits",
                    "v1_creation_payer_not_signer",
                    "v1_instruction_or_address_count_invalid",
                    "v1_wire_truncated",
                    "v1_signer_header_invalid",
                    "v1_duplicate_static_addresses",
                    "v1_instruction_index_or_accounts_invalid",
                    "v1_instruction_account_reference_invalid",
                    "v1_transaction_base64_invalid"))
                receipt["status"] = "V1_BINARY_PROOF_REFUSED"
                receipt["refusal_phase"] = "v1_binary_ed25519"
                receipt["refusal_code"] = (code if type(exc) is ValueError
                    and code in allowlisted else "OTHER_" + type(exc).__name__)
            continue
        verification_phase = "ed25519_message"
        try:
            proof = verify_compiled_rpc_signatures(raw)
            if proof.get("cryptographic_signatures_verified") is not True:
                raise ValueError("cryptographic_signature_missing")
            verification_phase = "compiled_account_graph"
            normalized = normalized_compiled_transaction(raw)
            accounts = normalized["transaction"]["message"]["accountKeys"]
            keyset = {key["pubkey"] for key in accounts}
            signer_set = {key["pubkey"] for key in accounts if key["signer"]}
            verification_phase = "compiled_creation_instructions"
            raw_launches = compiled_launchlab_creations(raw)
            verification_phase = "outer_signed_creation_instructions"
            signed_outer_only = compiled_launchlab_creations(dict(
                raw, meta=dict(raw["meta"], innerInstructions=[])))
            key_fields = ("payer", "creator", "pool_state", "mint")
            def identities(rows):
                return {tuple(row[field] for field in key_fields)
                        for row in rows}
            verification_phase = "creation_payer_identity"
            for launch in raw_launches:
                if (not {launch["payer"], launch["creator"], launch["pool_state"],
                         launch["mint"], PROGRAM}.issubset(keyset) or
                        launch["payer"] not in signer_set):
                    raise ValueError("verified_compiled_creation_identity_mismatch")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            # Fixed categorical reason codes only, never raw RPC bodies,
            # exception representations, endpoint URLs or provider secrets.
            allowlisted = frozenset((
                "unsupported_transaction_message_or_header",
                "compiled_creation_inner_group_invalid",
                "compiled_creation_indices_invalid",
                "compiled_creation_outer_instructions_invalid",
                "raw_compiled_message_header_required",
                "unsupported_transaction_message_version",
                "compiled_creation_transaction_required",
                "compiled_creation_instruction_invalid",
                "parsed_vs_compiled_creation_disagreement",
                "verified_compiled_creation_identity_mismatch",
                "historical_transaction_Ed25519_signature_invalid",
                "serialized_Solana_message_packet_limit",
                "compiled_instruction_index_invalid",
                "compiled_account_key_not_base58_string"))
            code = str(error)
            receipt["status"] = "SIGNATURE_OR_CREATION_IDENTITY_REFUSED"
            receipt["refusal_phase"] = verification_phase
            receipt["refusal_code"] = (
                code if type(error) is ValueError and code in allowlisted
                else "OTHER_" + type(error).__name__)
            continue
        receipt["exact_message_sha256"] = proof["exact_message_sha256"]
        receipt["cryptographic_signature_verified"] = True
        if raw_launches:
            # Outer instructions are covered by the Ed25519-signed message.
            # Inner instructions exist only in provider-supplied RPC metadata.
            outer_keys = identities(signed_outer_only)
            receipt["status"] = (
                "SIGNED_OUTER_CREATION_CANDIDATE"
                if identities(raw_launches).issubset(outer_keys) else
                "INNER_RPC_ATTESTED_CREATION_CANDIDATE")
            receipt["launches"] = [
                dict(creator=v["creator"], payer=v["payer"],
                     pool=v["pool_state"], mint=v["mint"]) for v in raw_launches]
            if receipt["status"] == "SIGNED_OUTER_CREATION_CANDIDATE":
                distinct_creators.update(v["creator"] for v in raw_launches)
        else:
            receipt["status"] = "VERIFIED_NON_CREATION"
    counts = {}
    for row in records:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return dict(schema="rugger-mainnet-forward-captured-creation-check-v1",
        status="CAPTURE_VERIFIED_AND_RPC_INSPECTED",
        first_phase_captured_logs=len(events),
        selected_for_finalized_receipt=inspected,
        inspection_candidates_preselected=len(chosen),
        uninspected_due_to_rpc_budget=len(chosen)-inspected,
        selected_before_receipt_lookup=True,
        selection_rule="first_eight_unfailed_logs_initialize_hint_priority_then_arrival_budget_aware",
        source_log_chain_sha256=report["signature_ledger_sha256"],
        status_counts=counts, records=records,
        signed_creation_candidate_transactions=counts.get("SIGNED_OUTER_CREATION_CANDIDATE", 0),
        inner_rpc_only_candidate_transactions=counts.get("INNER_RPC_ATTESTED_CREATION_CANDIDATE", 0),
        distinct_creator_claims_from_signed_transactions=len(distinct_creators),
        independently_verified_economic_creators=0,
        real_buy_sell_trades=0, market_price_at_decision_verified=False,
        independent_rpc_provider_proof=False,
        provider_finalized_receipt_is_not_time_of_signal=True,
        classification_uses_only_cryptographically_checked_compiled_outer_messages=True,
        confirmed_websocket_event_is_not_finalized_at_arrival=True,
        economically_qualified_cycles=0,
        net_master_edge_estimate=None,
        financial_order_submitted=False, live_ready_to_arm=False,
        economic_edge_validated=False, execution_verified=False,
        rpc_calls_used=getattr(rpc, "count", None))


def main():
    try:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise ValueError("github_actions_capture_required")
        root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        target = root / "paper_artifacts" / "paper_helius_log_stream.json"
        if (not target.resolve().is_relative_to(root) or
                target.is_symlink() or target.stat().st_size > 300000):
            raise ValueError("untrusted_capture_file")
        contents = json.loads(target.read_text(encoding="utf-8"))
        if type(contents) is not dict:
            raise ValueError("capture_envelope_invalid")
        rpc = HeliusReadOnlyRpc.from_environment(max_calls=10)
        report = inspect_forward_creations(contents["report"], contents["events"], rpc)
        result = root / "paper_artifacts" / "paper_helius_verified_creations.json"
        result.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as error:
        # Error messages can contain user secrets; emit class only.
        print(json.dumps(dict(
            schema="rugger-mainnet-forward-captured-creation-check-v1",
            status="REFUSED", safe_error_class=type(error).__name__,
            financial_order_submitted=False, live_ready_to_arm=False,
            economic_edge_validated=False)))
        return 2


if __name__ == "__main__":
    sys.exit(main())
