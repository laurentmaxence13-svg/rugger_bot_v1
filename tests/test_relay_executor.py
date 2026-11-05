import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from tools import relay_executor as rx, relay_store as rs

FX = os.path.join(os.path.dirname(__file__), "fixtures", "relay")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def fx(name): return json.load(open(os.path.join(FX, name)))


class E2E(unittest.TestCase):
    def setUp(self):
        self.con = rs.open_db(os.path.join(tempfile.mkdtemp(), "r.db"))
        self.sent = []

    def count(self, table="outbox"): return self.con.execute(f"select count(*) from {table}").fetchone()[0]

    def test_full_chain_creates_exactly_one_labeled_task(self):
        r = rx.handle_webhook(self.con, "issues", "D1", fx("issues_labeled_04.json"), NOW)
        self.assertTrue(r["handled"])
        self.assertEqual(rs.load_state(self.con)["agents"]["rugger-04"]["issue"], 200)
        r = rx.handle_webhook(self.con, "issue_comment", "D2", fx("issue_comment_report_04.json"), NOW + timedelta(minutes=5))
        self.assertTrue(r["handled"])
        # redelivery of the same comment, and the later close event: no second task
        self.assertFalse(rx.handle_webhook(self.con, "issue_comment", "D2", fx("issue_comment_report_04.json"), NOW)["handled"])
        self.assertFalse(rx.handle_webhook(self.con, "issues", "D3", fx("issues_closed_04.json"), NOW, last_comment="STATUS: COMPLETED")["handled"])
        self.assertEqual(self.count(), 1)
        self.assertEqual(len(rx.drain_outbox(self.con, self.sent.append, NOW)), 1)
        self.assertEqual(rx.drain_outbox(self.con, self.sent.append, NOW), [])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["labels"], ["rugger-02-run"])  # issue + label in one call
        self.assertEqual(self.sent[0]["agent"], "rugger-02")
        self.assertEqual(rs.load_state(self.con)["agents"]["rugger-02"]["state"], "RUNNING")
        # successor issue labeled (GitHub App case): attaches issue number, no duplicate
        rx.handle_webhook(self.con, "issues", "D4", fx("issues_labeled_02_by_relay.json"), NOW)
        self.assertEqual(rs.load_state(self.con)["agents"]["rugger-02"]["issue"], 201)
        self.assertEqual(self.count(), 1)

    def test_blocked_escalates_without_task(self):
        p = fx("issue_comment_report_04.json"); p["comment"]["body"] = "STATUS: BLOCKED\nowner needed"
        self.assertTrue(rx.handle_webhook(self.con, "issue_comment", "B1", p, NOW)["handled"])
        self.assertEqual((self.count(), self.count("escalations")), (0, 1))

    def test_kill_switch_and_rollback(self):
        rx.handle_webhook(self.con, "issue_comment", "D2", fx("issue_comment_report_04.json"), NOW)
        rs.set_kill_switch(self.con, True, NOW)
        self.assertEqual(rx.drain_outbox(self.con, self.sent.append, NOW), [])
        self.assertFalse(rx.handle_webhook(self.con, "issues", "D1", fx("issues_labeled_04.json"), NOW)["handled"])
        self.assertEqual(rs.rollback_pending(self.con), 1)
        self.assertEqual(self.con.execute("select status from outbox").fetchone()[0], "CANCELLED")
        self.assertEqual(self.sent, [])

    def test_naive_time_and_concurrent_label_refused(self):
        self.assertFalse(rx.handle_webhook(self.con, "issues", "N", fx("issues_labeled_04.json"), datetime(2026, 11, 6))["handled"])
        rx.handle_webhook(self.con, "issues", "D1", fx("issues_labeled_04.json"), NOW)
        p = fx("issues_labeled_04.json"); p["issue"]["number"] = 300
        rx.handle_webhook(self.con, "issues", "D9", p, NOW)
        self.assertEqual(rs.load_state(self.con)["agents"]["rugger-04"]["issue"], 200)
        self.assertEqual(self.count("escalations"), 1)

    def test_quota_per_hour_blocks_creation(self):
        for i in range(2):
            self.con.execute("insert into launches values(?,?,?)", (f"x{i}", "rugger-02", (NOW - timedelta(minutes=10)).isoformat()))
        rx.handle_webhook(self.con, "issue_comment", "Q", fx("issue_comment_report_04.json"), NOW)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.count("escalations"), 1)

    def test_workflow_failure_and_catchup_watchdog(self):
        self.assertTrue(rx.handle_webhook(self.con, "workflow_run", "W1", fx("workflow_run_failed.json"), NOW)["handled"])
        self.assertFalse(rx.handle_webhook(self.con, "workflow_run", "W1", fx("workflow_run_failed.json"), NOW)["handled"])
        rx.handle_webhook(self.con, "issues", "D1", fx("issues_labeled_04.json"), NOW)
        rx.catchup(self.con, NOW + timedelta(hours=7))
        self.assertEqual(rs.load_state(self.con)["agents"]["rugger-04"]["state"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
