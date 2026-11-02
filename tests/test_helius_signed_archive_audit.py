"""Synthetic archive contract for the real-source integrity auditor.

Offline only: no network access, external data or wallet. Synthetic source
is deliberately NOT a cryptographically attested blockchain transaction.
"""
from copy import deepcopy
import hashlib
import json
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from bot.p3.helius_signed_archive_audit import audit_signed_archive, _digest


def encoded(x):
    return json.dumps(x, sort_keys=True, indent=2, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture(tmp_path, *, mutation=None):
    events = [{"signature": "synthetic-signature-1",
               "reception_utc_ns": 1700000000000000000, "slot": 12345}]
    source = {"report": {"signature_ledger_sha256": "f" * 64}, "events": events}
    proof = {"status": "CAPTURE_VERIFIED_AND_RPC_INSPECTED",
             "source_log_chain_sha256": "f" * 64,
             "financial_order_submitted": False,
             "signed_creation_candidate_transactions": 1}
    paired = {"financial_order_submitted": False, "live_ready_to_arm": False,
              "signed_creation_candidates_selected": 1,
              "observations": [{"root_refusal": "non_native_SOL_quote_mint"}]}
    portfolio = {"actual_financial_orders_submitted": 0,
                 "frozen_decisions": 0,
                 "accounts": {"master": {"open_positions": 0, "closed_paper_cycles": 0},
                              "reference": {"open_positions": 0, "closed_paper_cycles": 0}}}
    src_raw = encoded(source)
    files = {"received.json": src_raw, "verified/signed_log_capture.json": src_raw,
             "verified/finalized_creation_proof.json": encoded(proof),
             "verified/paired_signed_master_paper.json": encoded(paired),
             "verified/paired_paper_portfolio.json": encoded(portfolio)}
    summary = {
        "schema": "rugger-helius-signed-master-paper-integration-v1",
        "log_events_retained": 1,
        "crypto_signed_creation_transactions": 1,
        "selected_independent_signed_creators": 1,
        "frozen_S1_decisions": 0,
        "trade_fills_simulated": 0,
        "qualified_economic_cycles": 0,
        "execution_verified": False,
        "financial_order_submitted": False,
        "master_net_pnl_lamports": None,
        "reference_net_pnl_lamports": None,
        "actual_verification_rpc_calls_used": 1,
        "actual_bank_rpc_calls_used": 1,
        "sha256": {key: sha(files[filename]) for key, filename in (
            ("signed_log_capture", "verified/signed_log_capture.json"),
            ("finalized_creation_proof", "verified/finalized_creation_proof.json"),
            ("paired_signed_master_paper", "verified/paired_signed_master_paper.json"),
            ("paired_paper_portfolio", "verified/paired_paper_portfolio.json"))},
    }
    files["verified/summary.json"] = encoded(summary)
    manifest = {"schema": "rugger-continuous-helius-signed-source-paper-v1",
        "status": "COMPLETED_NO_KNOWN_GAP_NOT_PROOF_OF_COMPLETE_TAPE",
        "financial_order_submitted": False,
        "live_ready_to_arm": False,
        "complete_event_tape_verified": False,
        "exact_master_net_profitability_verified": False,
        "max_rpc_calls": 15, "rpc_used_or_reserved_upper_bound": 2,
        "events_retained": 1,
        "windows": [{"index": 0, "state": "VERIFIED", "source_sha256": sha(src_raw),
                     "source_event_count": 1, "rpc_calls_reserved": 2,
                     "verified_summary_sha256": _digest(summary),
                     "signed_creations": 1, "master_decisions": 0}],
        "summary": {"unique_log_events": 1, "verified_creations": 1,
                    "frozen_s1_decisions": 0, "verification_rpc_calls": 2,
                    "actual_paper_buys": 0, "financial_order_submitted": False}}
    docs = {"chunks/000000/" + name: raw for name, raw in files.items()}
    docs["manifest.json"] = encoded(manifest)
    if mutation:
        mutation(docs)
    path = tmp_path / "synthetic-signed.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as z:
        for key, raw in docs.items():
            z.writestr(key, raw)
    return path


def test_synthetic_integrity_audit_reports_zero_genuine_master_trades(tmp_path):
    result = audit_signed_archive(fixture(tmp_path))
    assert result["status"] == "ARCHIVED_SOURCE_BYTES_INTEGRITY_VERIFIED"
    assert result["windows"] == 1
    assert result["events"] == 1
    assert result["signed_creation_transactions"] == 1
    assert result["refused_non_sol_pool_graphs"] == 1
    assert result["native_sol_graphs"] == 0
    assert result["frozen_S1_decisions"] == 0
    assert result["genuine_master_paper_buy_sell_verified"] is False
    assert result["original_ed25519_signature_reverified_by_this_audit"] is False
    assert result["master_net_pnl_sol"] is None
    assert result["financial_order_submitted"] is False


def test_archive_mutated_raw_source_refused(tmp_path):
    def mutate(docs):
        name = "chunks/000000/received.json"
        docs[name] = docs[name].replace(b"synthetic-signature-1", b"synthetic-signature-2")
    with pytest.raises(ValueError, match="signed_source_manifest_hash_mismatch"):
        audit_signed_archive(fixture(tmp_path, mutation=mutate))


def test_summary_mutated_financial_claim_refused(tmp_path):
    def mutate(docs):
        name = "chunks/000000/verified/summary.json"
        docs[name] = docs[name].replace(b'"trade_fills_simulated": 0',
                                        b'"trade_fills_simulated": 1')
    with pytest.raises(ValueError, match="signed_source_manifest_hash_mismatch"):
        audit_signed_archive(fixture(tmp_path, mutation=mutate))


def test_component_tampering_not_excused_by_manifest_hash(tmp_path):
    def mutate(docs):
        name = "chunks/000000/verified/finalized_creation_proof.json"
        docs[name] = docs[name].replace(
            b"CAPTURE_VERIFIED_AND_RPC_INSPECTED",
            b"NOT_INDEPENDENTLY_VERIFIED")
    with pytest.raises(ValueError, match="signed_component_hash_mismatch"):
        audit_signed_archive(fixture(tmp_path, mutation=mutate))


def test_duplicate_archive_path_refused(tmp_path):
    path = fixture(tmp_path)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with ZipFile(path, "a") as z:
            z.writestr("manifest.json", b"{}")
    with pytest.raises(ValueError, match="unsafe_signed_archive_entry"):
        audit_signed_archive(path)


def test_path_traversal_refused(tmp_path):
    path = fixture(tmp_path)
    with ZipFile(path, "a") as z:
        z.writestr("../private.env", b"NEVER_READ")
    with pytest.raises(ValueError, match="unsafe_signed_archive_entry"):
        audit_signed_archive(path)


def test_missing_verification_artifact_refused(tmp_path):
    def mutate(docs):
        docs.pop("chunks/000000/verified/finalized_creation_proof.json")
    with pytest.raises(ValueError, match="missing_signed_archive_document"):
        audit_signed_archive(fixture(tmp_path, mutation=mutate))


def test_rpc_usage_cannot_be_retroactively_refunded(tmp_path):
    def mutate(docs):
        name = "manifest.json"
        manifest = json.loads(docs[name])
        manifest["rpc_used_or_reserved_upper_bound"] = 0
        docs[name] = encoded(manifest)
    with pytest.raises(ValueError, match="signed_session_totals_mismatch"):
        audit_signed_archive(fixture(tmp_path, mutation=mutate))
