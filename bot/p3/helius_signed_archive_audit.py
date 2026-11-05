"""Offline audit of archived genuine Helius signed-source PAPER evidence.

This validates the exact archived bytes, canonical manifest hashes and observed
NO-TRADE state. It does NOT independently re-run on-chain Ed25519 verification:
that would require original compiled transaction messages and source receipts.
Never substitute archived DexScreener candidates or claim executable fills.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import PurePosixPath
import stat
from zipfile import ZipFile

SCHEMA = "rugger-archived-signed-source-evidence-audit-v1"
MANIFEST_SCHEMA = "rugger-continuous-helius-signed-source-paper-v1"
SUMMARY_SCHEMA = "rugger-helius-signed-master-paper-integration-v1"
MAX_ARCHIVE_ENTRIES = 500
MAX_ENTRY_BYTES = 2_000_000
MAX_TOTAL_BYTES = 30_000_000
MAX_WINDOWS = 400


def _digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _fail(reason):
    raise ValueError(reason)


def _integer(value, *, maximum=1_000_000):
    if type(value) is not int or not 0 <= value <= maximum:
        _fail("untrusted_archive_counter")
    return value


def _document(archive, name):
    if name not in archive.namelist():
        _fail("missing_signed_archive_document")
    data = archive.read(name)
    if len(data) > MAX_ENTRY_BYTES:
        _fail("oversized_signed_archive_document")
    try:
        document = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        _fail("invalid_signed_archive_json")
    if type(document) is not dict:
        _fail("invalid_signed_archive_document")
    return document, data


def audit_signed_archive(archive_path):
    """Read GitHub Actions ZIP evidence only, with no network or key access."""
    with ZipFile(archive_path, "r") as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= MAX_ARCHIVE_ENTRIES:
            _fail("unbounded_signed_archive")
        seen_paths = set()
        aggregate = 0
        for info in entries:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                    or info.filename in seen_paths or info.file_size > MAX_ENTRY_BYTES
                    or info.compress_size > MAX_ENTRY_BYTES
                    or stat.S_ISLNK(info.external_attr >> 16)):
                _fail("unsafe_signed_archive_entry")
            aggregate += info.file_size
            if aggregate > MAX_TOTAL_BYTES:
                _fail("unbounded_signed_archive")
            seen_paths.add(info.filename)
        manifest, manifest_bytes = _document(archive, "manifest.json")
        if (manifest.get("schema") != MANIFEST_SCHEMA or
                type(manifest.get("windows")) is not list or
                not 1 <= len(manifest["windows"]) <= MAX_WINDOWS or
                manifest.get("financial_order_submitted") is not False or
                manifest.get("live_ready_to_arm") is not False or
                manifest.get("exact_master_net_profitability_verified") is not False or
                manifest.get("complete_event_tape_verified") is not False):
            _fail("invalid_signed_session_manifest")
        if manifest.get("status") not in (
                "COMPLETED_NO_KNOWN_GAP_NOT_PROOF_OF_COMPLETE_TAPE",
                "COMPLETED_WITH_GAPS"):
            _fail("incomplete_signed_session")
        _integer(manifest.get("max_rpc_calls"), maximum=30_000)
        total_events = total_selected = total_signed = total_graphs = total_s1 = 0
        total_rpc = total_reserved = total_non_sol = 0
        seen_signatures = set()
        findings = []
        for index, window in enumerate(manifest["windows"]):
            if (type(window) is not dict or window.get("index") != index
                    or window.get("state") != "VERIFIED"):
                _fail("unverified_signed_archive_window")
            base = f"chunks/{index:06d}"
            received, received_bytes = _document(archive, base + "/received.json")
            summary, _ = _document(archive, base + "/verified/summary.json")
            proof, proof_bytes = _document(archive, base + "/verified/finalized_creation_proof.json")
            paired, paired_bytes = _document(archive, base + "/verified/paired_signed_master_paper.json")
            portfolio, portfolio_bytes = _document(archive, base + "/verified/paired_paper_portfolio.json")
            signed_log, signed_log_bytes = _document(archive, base + "/verified/signed_log_capture.json")
            if (hashlib.sha256(received_bytes).hexdigest() != window.get("source_sha256")
                    or _digest(summary) != window.get("verified_summary_sha256")
                    or received_bytes != signed_log_bytes):
                _fail("signed_source_manifest_hash_mismatch")
            if summary.get("schema") != SUMMARY_SCHEMA:
                _fail("unexpected_signed_summary_schema")
            for key, raw in (("finalized_creation_proof", proof_bytes),
                             ("paired_signed_master_paper", paired_bytes),
                             ("paired_paper_portfolio", portfolio_bytes),
                             ("signed_log_capture", signed_log_bytes)):
                if (type(summary.get("sha256")) is not dict or
                        summary["sha256"].get(key) != hashlib.sha256(raw).hexdigest()):
                    _fail("signed_component_hash_mismatch")
            events = received.get("events")
            if (type(events) is not list or
                    len(events) != _integer(window.get("source_event_count"), maximum=100) or
                    len(events) != _integer(summary.get("log_events_retained"), maximum=100)):
                _fail("signed_event_count_mismatch")
            for event in events:
                if (type(event) is not dict or
                        type(event.get("signature")) is not str or
                        not event["signature"] or event["signature"] in seen_signatures):
                    _fail("replayed_or_invalid_signed_source_event")
                seen_signatures.add(event["signature"])
            if (type(received.get("report")) is not dict or
                    proof.get("source_log_chain_sha256") !=
                        received["report"].get("signature_ledger_sha256") or
                    proof.get("status") != "CAPTURE_VERIFIED_AND_RPC_INSPECTED" or
                    proof.get("financial_order_submitted") is not False or
                    paired.get("financial_order_submitted") is not False or
                    paired.get("live_ready_to_arm") is not False):
                _fail("signed_proof_origin_unqualified")
            signed = _integer(summary.get("crypto_signed_creation_transactions"), maximum=100)
            selected = _integer(summary.get("selected_independent_signed_creators"), maximum=3)
            frozen = _integer(summary.get("frozen_S1_decisions"), maximum=3)
            if (signed != _integer(proof.get("signed_creation_candidate_transactions"), maximum=100)
                    or selected != _integer(paired.get("signed_creation_candidates_selected"), maximum=3)
                    or frozen != _integer(portfolio.get("frozen_decisions"), maximum=3)
                    or frozen > selected):
                _fail("signed_evidence_decision_count_mismatch")
            if (summary.get("trade_fills_simulated") != 0 or
                    type(summary.get("trade_fills_simulated")) is not int or
                    summary.get("qualified_economic_cycles") != 0 or
                    summary.get("execution_verified") is not False or
                    summary.get("financial_order_submitted") is not False or
                    summary.get("master_net_pnl_lamports") is not None or
                    summary.get("reference_net_pnl_lamports") is not None or
                    portfolio.get("actual_financial_orders_submitted") != 0):
                _fail("financial_trade_not_qualified_by_archive_auditor")
            accounts = portfolio.get("accounts")
            if (type(accounts) is not dict or set(accounts) != {"master", "reference"}
                    or any(type(accounts[arm]) is not dict or
                       accounts[arm].get("open_positions") != 0 or
                       accounts[arm].get("closed_paper_cycles") != 0
                       for arm in ("master", "reference"))):
                _fail("unqualified_archive_position_state")
            verified_rpc = _integer(summary.get("actual_verification_rpc_calls_used"), maximum=10)
            bank_rpc = _integer(summary.get("actual_bank_rpc_calls_used"), maximum=5)
            reserved = _integer(window.get("rpc_calls_reserved"), maximum=15)
            if reserved != verified_rpc + bank_rpc:
                _fail("unreconciled_signed_rpc_budget")
            observations = paired.get("observations")
            if type(observations) is not list:
                _fail("missing_signed_pool_observations")
            native_graphs = sum(type(row) is dict and type(row.get("graph")) is dict
                                for row in observations)
            if ("supported_native_SOL_graphs" in summary and
                    summary["supported_native_SOL_graphs"] != native_graphs):
                _fail("native_sol_graph_count_mismatch")
            non_sol = sum(type(row) is dict and
                          row.get("root_refusal") == "non_native_SOL_quote_mint"
                          for row in observations)
            total_events += len(events)
            total_signed += signed
            total_selected += selected
            total_s1 += frozen
            total_graphs += native_graphs
            total_non_sol += non_sol
            total_rpc += verified_rpc + bank_rpc
            total_reserved += reserved
            findings.append(dict(window=index,events=len(events),
                signed_creation_transactions=signed,independent_creators_selected=selected,
                native_sol_graphs=native_graphs,frozen_master_S1=frozen,
                refused_non_sol_pool_graphs=non_sol,rpc_calls=reserved))
        reported = manifest.get("summary")
        if (type(reported) is not dict or
                reported.get("unique_log_events") != total_events or
                reported.get("verified_creations") != total_selected or
                reported.get("frozen_s1_decisions") != total_s1 or
                reported.get("verification_rpc_calls") != total_rpc or
                manifest.get("events_retained") != total_events or
                manifest.get("rpc_used_or_reserved_upper_bound") != total_reserved or
                total_reserved > manifest["max_rpc_calls"] or
                reported.get("actual_paper_buys") != 0 or
                reported.get("financial_order_submitted") is not False):
            _fail("signed_session_totals_mismatch")
        return dict(schema=SCHEMA,status="ARCHIVED_SOURCE_BYTES_INTEGRITY_VERIFIED",
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            windows=len(findings),events=total_events,
            signed_creation_transactions=total_signed,
            selected_independent_signed_creators=total_selected,
            native_sol_graphs=total_graphs,frozen_S1_decisions=total_s1,
            refused_non_sol_pool_graphs=total_non_sol,
            verified_rpc_calls=total_rpc,
            complete_market_tape_verified=False,
            original_ed25519_signature_reverified_by_this_audit=False,
            independent_rpc_provider_corroboration=False,
            genuine_master_paper_buy_sell_verified=False,
            qualified_economic_cycles=0,master_net_pnl_sol=None,
            financial_order_submitted=False,live_trading_enabled=False,
            windows_detail=findings)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="Existing signed Helius GitHub Actions ZIP archive")
    args = parser.parse_args(argv)
    try:
        report = audit_signed_archive(args.archive)
    except Exception as error:
        # No untrusted exception content or secrets in stdout.
        print(json.dumps({"schema": SCHEMA,"status": "REFUSED",
                          "safe_error_class": type(error).__name__,
                          "financial_order_submitted": False}))
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
