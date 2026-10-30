"""Verify captured Helius WebSocket program logs with LATER finalized receipts.

This is an observation classifier, not a real-time trade decision engine.
All signatures originate in an immutable, hashed, bounded log capture; a
preexisting log hint selects at most four events before seeing tx outcomes.
Raw compiled Solana Ed25519 bytes and parsed instruction identity must agree.
Only public data, read-only RPC. Missing receipts and failed tx remain counted.
"""
import json
import os
import sys
from pathlib import Path

from bot.p3.certification import PROGRAM
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.helius_launchlab_cohort_probe import RAW_OPTS, PARSED_OPTS
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.scanner.transaction_parser import find_raydium_launches
from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.p3.platform_admin_history import _signature
from bot.live.helius_ws_forward_paper import _hash

MAX_INSPECTIONS = 4
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
    for item in chosen:
        sig = item["signature"]
        receipt = keyed[sig]
        try:
            raw = rpc("getTransaction", [sig, RAW_OPTS])
            parsed = rpc("getTransaction", [sig, PARSED_OPTS])
        except ValueError as exc:
            # A version or provider access problem must not be misread as a
            # rejected trade. Unexpected RPC errors abort the investigation.
            if (str(exc) == "helius_rpc_envelope_refused" and
                    getattr(rpc, "last_rpc_error_code", None) == -32015):
                receipt["status"] = "UNSUPPORTED_TX_VERSION"
                continue
            raise
        if raw is None or parsed is None:
            receipt["status"] = "FINALIZED_RECEIPT_UNAVAILABLE"
            continue
        if (type(raw) is not dict or type(parsed) is not dict or
                raw.get("slot") != item["slot"] or
                parsed.get("slot") != item["slot"] or
                type(raw.get("meta")) is not dict or
                type(parsed.get("meta")) is not dict or
                raw["meta"].get("err") is not None or
                parsed["meta"].get("err") is not None or
                raw.get("transaction", {}).get("signatures", [None])[0] != sig or
                parsed.get("transaction", {}).get("signatures", [None])[0] != sig):
            receipt["status"] = "FINALIZED_RECEIPT_MISMATCH"
            continue
        try:
            proof = verify_compiled_rpc_signatures(raw)
            if proof.get("cryptographic_signatures_verified") is not True:
                raise ValueError("cryptographic_signature_missing")
            normalized = normalized_compiled_transaction(raw)
            accounts = normalized["transaction"]["message"]["accountKeys"]
            keyset = {key["pubkey"] for key in accounts}
            signer_set = {key["pubkey"] for key in accounts if key["signer"]}
            launches = find_raydium_launches(parsed)
            raw_launches = compiled_launchlab_creations(raw)
            signed_outer_only = compiled_launchlab_creations(dict(
                raw, meta=dict(raw["meta"], innerInstructions=[])))
            key_fields = ("payer", "creator", "pool_state", "mint")
            def identities(rows):
                return {tuple(row[field] for field in key_fields)
                        for row in rows}
            if identities(launches) != identities(raw_launches):
                raise ValueError("parsed_vs_compiled_creation_disagreement")
            for launch in raw_launches:
                if (not {launch["payer"], launch["creator"], launch["pool_state"],
                         launch["mint"], PROGRAM}.issubset(keyset) or
                        launch["payer"] not in signer_set):
                    raise ValueError("verified_compiled_creation_identity_mismatch")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            receipt["status"] = "SIGNATURE_OR_CREATION_IDENTITY_REFUSED"
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
        selected_for_finalized_receipt=len(chosen),
        selected_before_receipt_lookup=True,
        selection_rule="first_four_unfailed_logs_initialize_hint_priority_then_arrival",
        source_log_chain_sha256=report["signature_ledger_sha256"],
        status_counts=counts, records=records,
        signed_creation_candidate_transactions=counts.get("SIGNED_OUTER_CREATION_CANDIDATE", 0),
        inner_rpc_only_candidate_transactions=counts.get("INNER_RPC_ATTESTED_CREATION_CANDIDATE", 0),
        distinct_creator_claims_from_signed_transactions=len(distinct_creators),
        independently_verified_economic_creators=0,
        real_buy_sell_trades=0, market_price_at_decision_verified=False,
        independent_rpc_provider_proof=False,
        provider_finalized_receipt_is_not_time_of_signal=True,
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
        rpc = HeliusReadOnlyRpc.from_environment(max_calls=9)
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
