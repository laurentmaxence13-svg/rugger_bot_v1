"""Synthetic, offline test for cross-protocol swaps != migrations."""
import unittest
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "tools" / "bitquery_cross_protocol_audit.py"
spec = spec_from_file_location("rugger_cross_protocol_audit", source)
module = module_from_spec(spec)
spec.loader.exec_module(module)


def row(i, protocol, buy, sell, signature, slot=100):
    return {
        "event_id": "e" + str(i),
        "block_time_utc": "2026-10-31T18:30:00Z",
        "block_slot": str(slot),
        "signature": signature, "protocol": protocol,
        "program_address": module.PROGRAMS[protocol],
        "market_address": "pool-" + protocol,
        "buy_mint": buy, "sell_mint": sell,
        "wsol_trade": str((buy == module.WSOL) != (sell == module.WSOL)),
        "token_mint": sell if buy == module.WSOL else (buy if sell == module.WSOL else ""),
    }


class CrossProtocolEvidenceTests(unittest.TestCase):
    def test_cross_quote_same_signature_is_not_migration(self):
        events = [
            row(1, "raydium_launchpad", "token-A", "token-B", "route"),
            row(2, "raydium_cp_swap", "token-B", "token-C", "route"),
        ]
        report = module.audit(events)
        self.assertEqual(report["shared_mints_excluding_wsol"], 1)
        self.assertEqual(report["cross_protocol_same_signature_count"], 1)
        self.assertEqual(report["shared_mints_wsol_direct_only"], 0)
        self.assertEqual(report["verified_migrations"], 0)
        self.assertIsNone(report["net_pnl_sol"])
        self.assertEqual(report["same_signature_routes"][0]["common_leg_mints_excluding_wsol"], ["token-B"])

    def test_identical_mint_wsol_pairs_still_do_not_prove_graduation(self):
        events = [
            row(1, "raydium_launchpad", "token-A", module.WSOL, "one"),
            row(2, "raydium_cp_swap", "token-A", module.WSOL, "two"),
        ]
        report = module.audit(events)
        self.assertEqual(report["shared_mints_wsol_direct_only"], 1)
        self.assertEqual(report["verified_migrations"], 0)

    def test_wsol_only_overlap_is_excluded(self):
        events = [
            row(1, "raydium_launchpad", "token-A", module.WSOL, "one"),
            row(2, "raydium_cp_swap", "token-B", module.WSOL, "two"),
        ]
        report = module.audit(events)
        self.assertEqual(report["shared_mints_excluding_wsol"], 0)

    def test_no_shared_mint_in_multi_program_signature(self):
        events = [
            row(1, "raydium_launchpad", "token-A", "token-B", "one"),
            row(2, "raydium_cp_swap", "token-C", "token-D", "one"),
        ]
        report = module.audit(events)
        self.assertEqual(report["cross_protocol_same_signature_count"], 1)
        self.assertEqual(report["shared_mints_excluding_wsol"], 0)

    def test_bad_program_rejected(self):
        e = row(1, "raydium_launchpad", "token-A", "token-B", "s")
        e["program_address"] = "fake"
        with self.assertRaises(ValueError):
            module.audit([e])

    def test_duplicate_event_rejected(self):
        e = row(1, "raydium_launchpad", "token-A", "token-B", "s")
        with self.assertRaises(ValueError):
            module.audit([e, e])

    def test_wrong_wsol_side_rejected(self):
        e = row(1, "raydium_launchpad", "token-A", module.WSOL, "s")
        e["wsol_trade"] = "False"
        with self.assertRaises(ValueError):
            module.audit([e])

    def test_newer_cpmm_event_cannot_prove_migration(self):
        e = [
            row(1, "raydium_cp_swap", "token-A", "token-B", "s1", 101),
            row(2, "raydium_launchpad", "token-B", "token-C", "s2", 100),
        ]
        report = module.audit(e)
        self.assertEqual(report["shared_mints_excluding_wsol"], 1)
        self.assertEqual(report["verified_migrations"], 0)
        self.assertFalse(report["shared_mint_leads"][0]["migration_verified"])


if __name__ == "__main__":
    unittest.main()
