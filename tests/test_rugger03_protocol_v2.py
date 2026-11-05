"""Offline tests for the RUGGER 03 v2 candidate protocol (issue 164). Reads local evidence only."""
import json, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks" / "rugger03_prereg_v2"))
import checks as c  # noqa: E402

P = json.loads((ROOT / "benchmarks" / "rugger03_prereg_v2" / "protocol.json").read_text(encoding="utf-8"))
B = c.load_bundles()
F = c.flat(B)


class EvidenceTests(unittest.TestCase):
    def test_record_and_bundle_counts(self):
        self.assertEqual((len(F), len(B)), (397, 5))

    def test_transaction_count_81(self):
        tx = [r for r in F if r["kind"] == "transaction"]
        self.assertEqual(len(tx), P["req5_transactions"]["documented_count_in_local_evidence"])
        self.assertEqual(len({r["signature"] for r in tx}), P["req5_transactions"]["documented_distinct_signatures"])

    def test_kinds_closed_schema(self):
        kinds = {r["kind"] for r in F}
        self.assertTrue(kinds <= c.KNOWN_KINDS, kinds - c.KNOWN_KINDS)
        self.assertEqual(set(P["req7_non_vacuous_tests"]["schema_kinds"]), set(c.KNOWN_KINDS))

    def test_zero_cycles_is_non_vacuous(self):
        # fails if a cycle kind appears OR if the schema silently grew an unknown kind
        self.assertFalse({r["kind"] for r in F} & c.CYCLE_KINDS)
        self.assertTrue({r["kind"] for r in F} <= c.KNOWN_KINDS)
        buys = [r for r in F if r["kind"] == "quote_attempt" and (r.get("payload") or {}).get("executable_confirmed") is True]
        self.assertEqual(len(buys), 0)

    def test_no_migration_kind_in_evidence(self):
        self.assertFalse([r for r in F if "migrat" in str(r["kind"]).lower()])

    def test_mint_dedup_counts(self):
        self.assertEqual(sum(1 for r in F if r["kind"] == "candidate_decision"), 214)
        self.assertEqual(len(c.dedup_by_mint(F, "candidate_decision")), 135)
        self.assertEqual(len(c.dedup_by_mint(F)), 136)

    def test_cross_bundle_signature_duplicates(self):
        self.assertEqual(len(c.cross_bundle_duplicate_signatures(B)), 2)

    def test_source_time_unknown_counted(self):
        self.assertEqual(len(c.unknown_source_time(F)), 378)
        known = [r for r in F if r["source_time_ms"] is not None]
        self.assertEqual(sum(1 for r in known if r["kind"] == "launch"), 3)


class SyntheticTests(unittest.TestCase):
    """synthetic=True: negative cases, never mixed with provenance=live data."""
    def test_dedup_synthetic(self):
        recs = [{"kind": "candidate_decision", "mint": "A"}, {"kind": "candidate_decision", "mint": "A"}, {"kind": "candidate_decision", "mint": "B"}]
        self.assertEqual({m: len(v) for m, v in c.dedup_by_mint(recs).items()}, {"A": 2, "B": 1})
        bundles = {"x": [{"kind": "transaction", "signature": "s"}], "y": [{"kind": "transaction", "signature": "s"}]}
        self.assertEqual(c.cross_bundle_duplicate_signatures(bundles), {"s": {"x", "y"}})

    def test_causal_view_synthetic(self):
        recs = [{"available_at_ms": 10, "source_time_ms": 5}, {"available_at_ms": 20, "source_time_ms": 5},
                {"available_at_ms": 10, "source_time_ms": None}]
        self.assertEqual(len(c.causal_view(recs, 15)), 1)

    def test_net_pnl_lamports(self):
        self.assertEqual(c.net_pnl_lamports(1000, 1500, {"a": 100, "b": 50}), 350)
        self.assertIsNone(c.net_pnl_lamports(1000, 1500, {"a": 100, "b": None}))
        with self.assertRaises(TypeError):
            c.net_pnl_lamports(1000, 1500.0, {"a": 1})


class ProtocolTests(unittest.TestCase):
    def test_targets_and_freeze_declared(self):
        self.assertEqual(P["targets"], {"min_independent_verified_creators": 50, "min_complete_paper_cycles": 20})
        self.assertIn("NOT_FROZEN", P["status"])
        self.assertTrue(P["paper_only"] and not P["stop_rules"]["live_trading"] and not P["stop_rules"]["secrets"])

    def test_owner_values_left_null(self):
        self.assertIsNone(P["req1_preregistration"]["values_declared_by_owner"])

    def test_causal_criteria_declared(self):
        r = P["req4_causal_criteria"]
        for k in ("same_replayed_journal_for_both_arms", "same_costs_slippage_latency_for_both_arms",
                  "parameters_frozen_before_results", "no_threshold_change_after_results"):
            self.assertTrue(r[k])
        s = r["split"]
        self.assertAlmostEqual(s["development_fraction"] + s["holdout_fraction"], 1.0)

    def test_profit_gate(self):
        g = P["req8_costs_thresholds"]["profitability_demonstrated_only_if"]
        for k in ("lower 95% bound > 0", "both targets met", "20%"):
            self.assertIn(k, g)

    def test_insufficient_data_rule(self):
        self.assertIn("INSUFFICIENT_DATA", P["insufficient_data_rule"])

    def test_no_secrets_or_urls(self):
        t = (ROOT / "benchmarks" / "rugger03_prereg_v2" / "protocol.json").read_text(encoding="utf-8").lower()
        for bad in ("api-key=", "api_key=", "http://", "https://", "seed phrase"):
            self.assertNotIn(bad, t)


if __name__ == "__main__":
    unittest.main()
