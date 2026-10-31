"""Adversarial offline tests for read-only forward evidence, no market access."""
import copy
import unittest

from tools.master_prospective_gate import build_gate, _sha


def capture():
    event = {
        "signature": "2" * 88, "slot": 463789800,
        "reception_utc_ns": 1793471400000000000,
        "reception_monotonic_ns": 1234567,
        "untrusted_initialize_log_hint": True,
        "on_chain_transaction_failed": False, "filled": False,
    }
    sha = _sha({"previous": "0" * 64, "event": event})
    return {
        "report": {"schema": "rugger-helius-program-log-forward-paper-v1",
                   "events_received_unique": 1, "signature_ledger_sha256": sha,
                   "financial_order_submitted": False},
        "events": [event],
    }


def verification(c):
    return {"schema": "rugger-mainnet-forward-captured-creation-check-v1",
            "source_log_chain_sha256": c["report"]["signature_ledger_sha256"],
            "first_phase_captured_logs": 1,
            "status": "CAPTURE_VERIFIED_AND_RPC_INSPECTED",
            "signed_creation_candidate_transactions": 1,
            "distinct_creator_claims_from_signed_transactions": 1,
            "financial_order_submitted": False,
            "records": [{"signature": c["events"][0]["signature"],
                         "status": "SIGNED_OUTER_CREATION_CANDIDATE"}]}


def comparison():
    pairs = []
    for fee in (1, 2):
        for delay in (0, 250):
            for split in ("development", "validation"):
                pairs.append({"fee_multiplier": fee, "decision_delay_ms": delay,
                              "split": split, "opportunities": (
                                  [{"mint": "newmint", "conditional_delta_lamports": "-20000000"}]
                                  if split == "validation" else [])})
    return {"schema": "rugger-master-reference-comparison-v1",
            "data_kind": "market_observation",
            "same_observation_tape": True,
            "same_financial_implementation": True,
            "active_policy_changed": False, "promotion_allowed": False,
            "execution_verified": False,
            "assignments": {"newmint": "validation"}, "pairs": pairs}


class ForwardGateTests(unittest.TestCase):
    def test_no_input_is_no_go(self):
        result = build_gate()
        self.assertIsNone(result["actual_master_minus_reference_net_pnl_sol"])
        self.assertFalse(result["economic_edge_validated"])
        self.assertEqual(result["comparison"]["status"], "NO_PAIRED_DECISIONS")

    def test_signed_creation_does_not_imply_trade(self):
        c = capture()
        result = build_gate(c, verification(c))
        self.assertEqual(result["capture"]["signed_creation_candidates"], 1)
        self.assertEqual(result["observed_filled_entry_exit_cycles"], 0)

    def test_modified_capture_must_fail(self):
        c = capture()
        v = verification(c)
        c["events"][0]["slot"] += 1
        with self.assertRaisesRegex(ValueError, "hash_chain"):
            build_gate(c, v)

    def test_mismatched_finalized_receipt_link_fails(self):
        c = capture()
        v = verification(c)
        v["source_log_chain_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "not_linked"):
            build_gate(c, v)

    def test_real_market_conditional_delta_not_a_proven_fill(self):
        c = capture()
        result = build_gate(c, verification(c), comparison())
        self.assertEqual(result["comparison"]["scenarios"]["1x_0ms"]["conditional_delta_lamports"], "-20000000")
        self.assertFalse(result["economic_edge_validated"])
        self.assertIsNone(result["actual_master_minus_reference_net_pnl_sol"])

    def test_open_position_hides_complete_delta(self):
        cmp = comparison()
        for pair in cmp["pairs"]:
            if pair["split"] == "validation":
                pair["opportunities"][0]["conditional_delta_lamports"] = None
        result = build_gate(comparison=cmp)
        self.assertIsNone(result["comparison"]["scenarios"]["1x_250ms"]["conditional_delta_lamports"])
        self.assertEqual(result["comparison"]["scenarios"]["1x_250ms"]["unknown_or_open_pairs"], 1)

    def test_synthetic_comparison_refused(self):
        cmp = comparison()
        cmp["data_kind"] = "synthetic"
        with self.assertRaises(ValueError):
            build_gate(comparison=cmp)

    def test_missing_scenario_refused(self):
        cmp = comparison()
        cmp["pairs"].pop()
        with self.assertRaisesRegex(ValueError, "four_stress"):
            build_gate(comparison=cmp)

    def test_duplicate_holdout_position_refused(self):
        cmp = comparison()
        cmp["pairs"][1]["opportunities"].append(copy.deepcopy(cmp["pairs"][1]["opportunities"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_gate(comparison=cmp)


if __name__ == "__main__":
    unittest.main()
