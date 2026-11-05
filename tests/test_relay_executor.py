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
        rx.handle_webhook(self.con, "issues", "L0", fx("issues_labeled_04.json"), NOW)  # proven launch first (P0-3)
        self.assertTrue(rx.handle_webhook(self.con, "issue_comment", "B1", p, NOW)["handled"])
        self.assertEqual((self.count(), self.count("escalations")), (0, 1))

    def test_kill_switch_and_rollback(self):
        rx.handle_webhook(self.con, "issues", "L0", fx("issues_labeled_04.json"), NOW)  # proven launch first (P0-3)
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
        rx.handle_webhook(self.con, "issues", "L0", fx("issues_labeled_04.json"), NOW)  # proven launch first (P0-3)
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


class Adversarial(unittest.TestCase):
    """Audit #207 scenarios. Each must be refused with NO state/outbox/escalation side effect."""
    def setUp(self):
        self.con = rs.open_db(os.path.join(tempfile.mkdtemp(), "r.db"))
        rx.handle_webhook(self.con, "issues", "L", fx("issues_labeled_04.json"), NOW)  # agent RUNNING on #200

    def snap(self):
        c = self.con
        return [c.execute(f"select count(*) from {t}").fetchone()[0] for t in ("outbox", "escalations", "launches")] + \
            [rs.load_state(c)["agents"]["rugger-04"]["state"]]

    def refused(self, mutate, why):
        p = fx("issue_comment_report_04.json"); mutate(p)
        before = self.snap()
        r = rx.handle_webhook(self.con, "issue_comment", "A1", p, NOW)
        self.assertFalse(r["handled"], r)
        self.assertIn(why, r["reason"])
        self.assertEqual(self.snap(), before)

    def test_p0_1_unauthorised_sender(self):
        def m(p): p["sender"]["login"] = "mallory"; p["comment"]["user"]["login"] = "mallory"
        self.refused(m, "not allowlisted")

    def test_p0_1_comment_author_differs_from_sender(self):
        self.refused(lambda p: p["comment"]["user"].update(login="mallory"), "comment author")

    def test_p0_1_missing_sender_or_user(self):
        self.refused(lambda p: p.pop("sender"), "sender missing")
        self.refused(lambda p: p["comment"].pop("user"), "comment author")

    def test_p0_1_association_not_owner_member(self):
        for assoc in ("NONE", "CONTRIBUTOR", "COLLABORATOR", None):
            self.refused(lambda p, a=assoc: p["comment"].update(author_association=a), "author_association")

    def test_p0_1_bot_not_allowlisted(self):
        def m(p): p["sender"] = {"login": "evil[bot]", "type": "Bot"}; p["comment"]["user"] = dict(p["sender"])
        self.refused(m, "not allowlisted")

    def test_p0_1_spoofed_login_with_bot_type_of_owner_name_is_refused(self):
        def m(p): p["sender"]["type"] = "Bot"; p["comment"]["user"]["type"] = "Bot"
        self.refused(m, "not allowlisted")

    def test_p0_2_wrong_repository(self):
        for name in ("evil/rugger_bot_v1", "laurentmaxence13-svg/rugger_bot_v1-fork", "LAURENTMAXENCE13-SVG/rugger_bot_v1", None):
            self.refused(lambda p, n=name: p["repository"].update(full_name=n), "repository")
        self.refused(lambda p: p.pop("repository"), "repository")

    def test_p0_2_wrong_repository_on_issues_event(self):
        p = fx("issues_labeled_04.json"); p["repository"]["full_name"] = "evil/fork"
        self.assertFalse(rx.handle_webhook(self.con, "issues", "A2", p, NOW)["handled"])

    def test_p0_3_completion_of_never_launched_task(self):
        con = rs.open_db(os.path.join(tempfile.mkdtemp(), "w.db"))  # rugger-04 WAITING, never launched
        r = rx.handle_webhook(con, "issue_comment", "A3", fx("issue_comment_report_04.json"), NOW)
        self.assertFalse(r["handled"]); self.assertIn("not RUNNING", r["reason"])
        self.assertEqual(con.execute("select count(*) from outbox").fetchone()[0], 0)
        self.assertEqual(rs.load_state(con)["agents"]["rugger-04"]["state"], "WAITING")

    def test_p0_3_completion_on_other_issue_number(self):
        def m(p): p["issue"]["number"] = 999
        self.refused(m, "not RUNNING on #999")

    def test_p0_3_completed_agent_cannot_complete_again(self):
        self.assertTrue(rx.handle_webhook(self.con, "issue_comment", "OK", fx("issue_comment_report_04.json"), NOW)["handled"])
        p = fx("issue_comment_report_04.json"); p["comment"]["id"] = 6
        before = self.snap()
        self.assertFalse(rx.handle_webhook(self.con, "issue_comment", "A4", p, NOW)["handled"])
        self.assertEqual(self.snap(), before)

    def test_p1_4_double_comment_new_delivery_id(self):
        self.assertTrue(rx.handle_webhook(self.con, "issue_comment", "D-a", fx("issue_comment_report_04.json"), NOW)["handled"])
        before = self.snap()
        self.assertFalse(rx.handle_webhook(self.con, "issue_comment", "D-b", fx("issue_comment_report_04.json"), NOW)["handled"])
        self.assertEqual(self.snap(), before)
        self.assertEqual(before[0], 1)

    def test_p1_4_redelivery_same_delivery_id_different_comment(self):
        self.assertTrue(rx.handle_webhook(self.con, "issue_comment", "D-x", fx("issue_comment_report_04.json"), NOW)["handled"])
        p = fx("issue_comment_report_04.json"); p["comment"]["id"] = 77
        self.assertFalse(rx.handle_webhook(self.con, "issue_comment", "D-x", p, NOW)["handled"])
        self.assertEqual(self.snap()[0], 1)

    def test_workflow_run_requires_authorised_sender_and_repo(self):
        for mut in (lambda p: p.pop("sender"), lambda p: p["repository"].update(full_name="evil/fork")):
            p = fx("workflow_run_failed.json"); mut(p)
            self.assertFalse(rx.handle_webhook(self.con, "workflow_run", "WX", p, NOW)["handled"])
        self.assertEqual(self.snap()[1], 0)


if __name__ == "__main__":
    unittest.main()
