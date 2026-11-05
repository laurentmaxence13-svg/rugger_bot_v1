"""Offline checks of the RUGGER 03 pre-registration (issue #158). No network, no DB, no secrets."""
import json, pathlib, socket, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P = ROOT / "benchmarks" / "rugger03_prereg_v1" / "protocol.json"


def helius_credits(requests, credits_per_request):
    """Pure budget arithmetic; credits_per_request must come from the provider's price sheet."""
    if requests < 0 or credits_per_request <= 0:
        raise ValueError("invalid budget input")
    return requests * credits_per_request


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.p = json.loads(P.read_text(encoding="utf-8"))

    def test_targets_and_paper_only(self):
        self.assertEqual(self.p["targets"]["min_independent_verified_creators"], 50)
        self.assertEqual(self.p["targets"]["min_complete_paper_cycles"], 20)
        self.assertTrue(self.p["paper_only"])
        self.assertEqual(self.p["stop_rules"]["max_budget_usd"], 0)
        self.assertFalse(self.p["stop_rules"]["live_trading"])
        self.assertFalse(self.p["stop_rules"]["secrets"])

    def test_denominator_keeps_failures(self):
        d = self.p["cohort_sampling"]["denominator_includes"]
        for k in ("failed", "unquoted", "never_migrated", "unsupported_state"):
            self.assertIn(k, d)

    def test_holdout_split_valid(self):
        s = self.p["cohort_sampling"]["split"]
        self.assertAlmostEqual(s["development_fraction"] + s["holdout_fraction"], 1.0)
        self.assertTrue(s["holdout_untouched_until_decisions_frozen"])

    def test_unknown_funding_not_independent(self):
        self.assertEqual(self.p["creator_independence"]["unknown_funding_counts_as"], "NOT_VERIFIED_INDEPENDENT")

    def test_profit_claim_gate_is_conservative(self):
        g = self.p["comparison"]["profitability_demonstrated_only_if"]
        for k in ("lower 95% bound > 0", "targets met", "20%"):
            self.assertIn(k, g)

    def test_budget_arithmetic(self):
        self.assertEqual(helius_credits(1000, 3), 3000)
        with self.assertRaises(ValueError):
            helius_credits(1, 0)

    def test_no_secret_values_in_protocol(self):
        txt = P.read_text(encoding="utf-8").lower()
        for bad in ("api-key=", "api_key=", "private", "seed phrase", "http://", "https://"):
            self.assertNotIn(bad, txt)

    def test_authoring_made_no_network(self):
        # this module opens no sockets; guard against accidental use
        orig = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
        try:
            json.loads(P.read_text(encoding="utf-8"))
        finally:
            socket.socket = orig


if __name__ == "__main__":
    unittest.main()
