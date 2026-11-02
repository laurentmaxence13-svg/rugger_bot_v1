import gzip
import json
import unittest
from pathlib import Path

from bot.market import timing
import bot.market.replay as replay

FIXTURES = Path(__file__).parent / "fixtures" / "launchlab_sol_pools"


def fixture_pairs():
    pairs = []
    for path in sorted(FIXTURES.glob("*.json.gz")):
        with gzip.open(path, "rt") as handle:
            data = json.load(handle)
        pairs.extend((s["slot"], s["blockTime"]) for s in data["signatures"])
    return pairs


class SyntheticTests(unittest.TestCase):
    def test_exact_rate(self):
        pairs = [(100 + i, 1000 + i * 0.4) for i in range(0, 101, 10)]
        result = timing.span_rate(pairs)
        self.assertAlmostEqual(result["seconds_per_slot"], 0.4)
        self.assertEqual(result["slots"], 100)

    def test_dedup_and_missing(self):
        pairs = [(5, 10), (5, 10), (None, 3), (7, None), (9, 12)]
        self.assertEqual(timing.unique_pairs(pairs), [(5, 10), (9, 12)])

    def test_conflict_raises(self):
        with self.assertRaises(ValueError):
            timing.unique_pairs([(5, 10), (5, 11)])

    def test_too_few(self):
        self.assertIsNone(timing.span_rate([(1, 1)]))
        self.assertEqual(timing.consecutive_rates([(1, 1)]), [])

    def test_bound_and_conversion(self):
        result = timing.span_rate([(0, 0), (50, 20)])
        self.assertAlmostEqual(result["quantisation_bound"], 0.02)
        self.assertAlmostEqual(timing.slots_to_seconds(2, 0.4), 0.8)


class FixtureTests(unittest.TestCase):
    def test_measured_rate_is_plausible(self):
        pairs = fixture_pairs()
        self.assertGreater(len(timing.unique_pairs(pairs)), 10)
        result = timing.span_rate(pairs)
        self.assertGreater(result["seconds_per_slot"], 0.2)
        self.assertLess(result["seconds_per_slot"], 1.0)

    def test_replay_default_unchanged(self):
        self.assertEqual(replay.ExecutionModel().latency_slots, 2)

    def test_each_pool_rate_in_measured_range(self):
        for path in sorted(FIXTURES.glob("*.json.gz")):
            with gzip.open(path, "rt") as handle:
                data = json.load(handle)
            result = timing.span_rate((s["slot"], s["blockTime"]) for s in data["signatures"])
            self.assertGreater(result["seconds_per_slot"], 0.2, path.name)
            self.assertLess(result["seconds_per_slot"], 0.25, path.name)


if __name__ == "__main__":
    unittest.main()
