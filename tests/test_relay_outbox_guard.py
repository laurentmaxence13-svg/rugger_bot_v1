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


class GuardWiredIntoOutbox(unittest.TestCase):
    """Integration on 6a8282e (R04): the adapter behind relay_store.run_outbox, still offline."""

    def setUp(self):
        import os, tempfile
        from datetime import datetime, timezone
        from tools import relay_store as rs
        self.rs = rs
        self.now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
        self.con = rs.open_db(os.path.join(tempfile.mkdtemp(), "r.db"))
        rs.apply_decision(self.con, {"actions": [{"type": "CREATE_ISSUE", "agent": "rugger-04", "title": "t",
                                                  "dedupe": "abc123def456"}]}, self.now, None)

    def status(self):
        return self.con.execute("SELECT status, attempts FROM outbox").fetchone()

    def test_planner_dedupe_keys_are_valid_markers(self):
        self.assertIn("abc123def456", marker("abc123def456"))

    def test_ambiguous_create_is_not_retried_and_alerts_owner(self):
        calls = []

        def create(p):
            calls.append(p); raise TimeoutError("response lost")

        send = lambda payload: guarded_send(payload, lambda _: [], create)
        for _ in range(3):  # three drains: a plain failure would be retried three times
            self.rs.run_outbox(self.con, send)
        self.assertEqual(len(calls), 1, "an ambiguous create must never be retried automatically")
        self.assertEqual(self.status(), ("FAILED", 1))
        alerts = [r[0] for r in self.con.execute("SELECT reason FROM escalations")]
        self.assertTrue(any("ReconciliationError" in a for a in alerts), alerts)

    def test_c1_alert_time_is_the_utc_time_passed_by_the_caller(self):
        def create(p):
            raise TimeoutError("response lost")
        self.rs.run_outbox(self.con, lambda payload: guarded_send(payload, lambda _: [], create), self.now)
        at = [r[0] for r in self.con.execute("SELECT at FROM escalations WHERE reason LIKE 'outbox %'")]
        self.assertEqual(at, [self.now.isoformat()])
        self.assertTrue(at[0].endswith("+00:00"))

    def test_c2_second_lookup_failure_fails_closed_in_one_attempt(self):
        calls, lookups = [], []

        def create(p):
            calls.append(p); raise TimeoutError("response lost")

        def lookup(tag):
            lookups.append(tag)
            if len(lookups) == 1:
                return []
            raise OSError("search API down")

        send = lambda payload: guarded_send(payload, lookup, create)
        for _ in range(3):
            self.rs.run_outbox(self.con, send, self.now)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.status(), ("FAILED", 1))
        self.assertTrue(any("ReconciliationError" in r[0] for r in self.con.execute("SELECT reason FROM escalations")))

    def test_crash_after_create_is_reconciled_on_the_next_drain(self):
        remote, calls = [], []

        def create(p):
            calls.append(p); remote.append({"number": 7}); raise TimeoutError("response lost")

        send = lambda payload: guarded_send(payload, lambda _: list(remote), create)
        done = self.rs.run_outbox(self.con, send)
        self.assertEqual(done, ["abc123def456"]); self.assertEqual(len(calls), 1)
        self.assertEqual(self.status()[0], "DONE")

    def test_plain_failure_keeps_the_bounded_retry(self):
        def send(payload):
            raise OSError("network down before any lookup")
        self.rs.run_outbox(self.con, send)
        self.assertEqual(self.status(), ("PENDING", 1))

    def test_kill_switch_still_stops_the_guarded_drain(self):
        self.rs.set_kill_switch(self.con, True, self.now)
        sent = []
        self.rs.run_outbox(self.con, lambda p: sent.append(p))
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
