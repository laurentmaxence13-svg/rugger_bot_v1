"""Offline regression tests for the optional crash-safe sender adapter."""
import unittest
from tools.relay_outbox_guard import ReconciliationError, guarded_send, marker


class GuardedSenderTests(unittest.TestCase):
    def test_existing_issue_never_created_twice(self):
        calls = []
        existing = {"number": 42}
        result = guarded_send({"dedupe": "task:42"}, lambda _: [existing],
                              lambda p: calls.append(p))
        self.assertEqual(result, existing)
        self.assertEqual(calls, [])

    def test_new_issue_has_exact_marker(self):
        calls = []
        result = guarded_send({"dedupe": "task:42", "body": "mission"},
                              lambda _: [], lambda p: calls.append(p) or {"number": 43})
        self.assertEqual(result["number"], 43)
        self.assertIn(marker("task:42"), calls[0]["body"])

    def test_timeout_with_existing_issue_reconciles(self):
        def fail(_):
            raise TimeoutError("response lost")
        lookups = iter([[], [{"number": 43}]])
        result = guarded_send({"dedupe": "task:42"}, lambda _: next(lookups), fail)
        self.assertEqual(result["number"], 43)

    def test_timeout_without_proof_blocks_retry(self):
        def fail(_):
            raise TimeoutError("response lost")
        with self.assertRaises(ReconciliationError):
            guarded_send({"dedupe": "task:42"}, lambda _: [], fail)

    def test_incomplete_lookup_blocks(self):
        with self.assertRaises(ReconciliationError):
            guarded_send({"dedupe": "task:42"}, lambda _: None, lambda _: None)

    def test_duplicate_remote_issues_blocks(self):
        with self.assertRaises(ReconciliationError):
            guarded_send({"dedupe": "task:42"}, lambda _: [1, 2], lambda _: None)

    def test_bad_marker_rejected(self):
        with self.assertRaises(ValueError):
            marker("x --> malicious")


if __name__ == "__main__":
    unittest.main()
