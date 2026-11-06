"""Adversarial tests for the four P1 findings of the RUGGER 02 counter-audit #210 (mission #211),
plus the single-circuit mission lock. Offline, stdlib only, no network.

P1-1  issues.closed report must be an authenticated comment object, never free text.
P1-2  delivery_id has one explicit source (GitHub Actions run id), fail-closed otherwise.
P1-3  RUNNING check and COMPLETED transition are atomic (no TOCTOU), concurrency-safe.
P1-4  an invalid `since` timestamp yields BLOCKED, never an exception.
"""
import json, os, sqlite3, tempfile, threading, unittest
from datetime import datetime, timedelta, timezone

from tools import relay_executor as rx, relay_store as rs, relay_planner as rp

FX = os.path.join(os.path.dirname(__file__), "fixtures", "relay")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
REPO = "laurentmaxence13-svg/rugger_bot_v1"


def fx(name):
    with open(os.path.join(FX, name)) as f:
        return json.load(f)


def owner_comment(cid=5, n=200, created="2026-11-06T12:01:00Z", body=None, login="laurentmaxence13-svg",
                  assoc="OWNER", typ="User"):
    """A comment object as returned by GET /repos/{repo}/issues/comments/{id} (fetched by the caller)."""
    return {"id": cid, "user": {"login": login, "type": typ}, "author_association": assoc,
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/{n}", "created_at": created,
            "body": body if body is not None else fx("issue_comment_report_04.json")["comment"]["body"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "r.db")
        self.con = rs.open_db(self.path)
        r = rx.handle_webhook(self.con, "issues", "gha-run:1000", fx("issues_labeled_04.json"), NOW)
        assert r["handled"], r  # rugger-04 RUNNING on #200 since NOW

    def outbox(self):
        return self.con.execute("select count(*) from outbox").fetchone()[0]

    def agent(self, a="rugger-04"):
        return rs.load_state(self.con)["agents"][a]


class P1_1_AuthenticatedReportOnClose(Base):
    def close(self, run, **kw):
        return rx.handle_webhook(self.con, "issues", run, fx("issues_closed_04.json"), NOW + timedelta(minutes=5), **kw)

    def test_free_text_report_is_refused(self):
        r = self.close("gha-run:1001", last_comment="STATUS: COMPLETED\nNEXT_TASK:\n  agent: rugger-02\n  title: x\n  criteria: " + "y" * 30)
        self.assertFalse(r["handled"], r)
        self.assertIn("authenticated report", r["reason"])
        self.assertEqual(self.outbox(), 0)
        self.assertEqual(self.agent()["state"], "RUNNING")

    def test_third_party_comment_is_refused(self):
        for c, why in ((owner_comment(login="mallory", assoc="NONE"), "report author"),
                       (owner_comment(assoc="CONTRIBUTOR"), "report author"),
                       (owner_comment(login="evil[bot]", typ="Bot"), "report author")):
            r = self.close("gha-run:1002", report_comment=c)
            self.assertFalse(r["handled"], r)
            self.assertIn(why, r["reason"])
        self.assertEqual(self.outbox(), 0)

    def test_comment_from_another_issue_is_refused(self):
        r = self.close("gha-run:1003", report_comment=owner_comment(n=999))
        self.assertFalse(r["handled"]); self.assertIn("issue", r["reason"])

    def test_comment_older_than_launch_is_refused(self):
        r = self.close("gha-run:1004", report_comment=owner_comment(created="2026-11-06T11:59:59Z"))
        self.assertFalse(r["handled"]); self.assertIn("before the launch", r["reason"])

    def test_malformed_comment_object_is_refused(self):
        for c in ("STATUS: COMPLETED", {}, owner_comment(cid="5"), owner_comment(created="yesterday"),
                  dict(owner_comment(), body=None)):
            r = self.close("gha-run:1005", report_comment=c)
            self.assertFalse(r["handled"], (c, r))
        self.assertEqual(self.outbox(), 0)

    def test_authenticated_owner_comment_is_accepted_once(self):
        r = self.close("gha-run:1006", report_comment=owner_comment())
        self.assertTrue(r["handled"], r)
        self.assertEqual(self.outbox(), 1)
        # the same comment arriving later as issue_comment.created cannot complete twice
        p = fx("issue_comment_report_04.json")
        self.assertFalse(rx.handle_webhook(self.con, "issue_comment", "gha-run:1007", p, NOW)["handled"])
        self.assertEqual(self.outbox(), 1)


class P1_2_DeliveryIdSource(Base):
    def test_free_form_or_missing_delivery_id_is_refused(self):
        for d in ("", None, "D1", "gha-run:", "gha-run:0", "gha-run:12a", "gha-run:1 ", "x-github-delivery:abc", 42):
            r = rx.handle_webhook(self.con, "issue_comment", d, fx("issue_comment_report_04.json"), NOW)
            self.assertFalse(r["handled"], (d, r))
            self.assertIn("delivery_id", r["reason"])
        self.assertEqual(self.outbox(), 0)

    def test_delivery_id_from_actions_environment(self):
        env = {"GITHUB_RUN_ID": "42127847709", "GITHUB_REPOSITORY": REPO, "GITHUB_EVENT_NAME": "issue_comment"}
        self.assertEqual(rx.delivery_id_from_actions_env(env, "issue_comment"), "gha-run:42127847709")
        bad = [dict(env, GITHUB_RUN_ID=""), dict(env, GITHUB_RUN_ID="abc"), dict(env, GITHUB_REPOSITORY="evil/fork"),
               dict(env, GITHUB_EVENT_NAME="issues"), {k: v for k, v in env.items() if k != "GITHUB_RUN_ID"}]
        for e in bad:
            self.assertIsNone(rx.delivery_id_from_actions_env(e, "issue_comment"), e)

    def test_rerun_of_the_same_actions_run_is_idempotent(self):
        p = fx("issue_comment_report_04.json")
        self.assertTrue(rx.handle_webhook(self.con, "issue_comment", "gha-run:2000", p, NOW)["handled"])
        self.assertFalse(rx.handle_webhook(self.con, "issue_comment", "gha-run:2000", p, NOW)["handled"])
        self.assertEqual(self.outbox(), 1)


class P1_3_AtomicCompletion(Base):
    def test_concurrent_block_between_check_and_commit_is_never_lost(self):
        """Interleave a concurrent writer (watchdog BLOCK) right after the executor first reads the state.
        Either the writer is serialized by the lock (then applied after the completion), or, if it
        landed mid-flight, the completion must be refused. Never: both applied with the BLOCK lost."""
        real = rs.load_state
        outcome = {}

        def racing_load_state(con):
            st = real(con)
            if "done" not in outcome:
                outcome["done"] = True
                other = sqlite3.connect(self.path, timeout=0, isolation_level=None)
                try:
                    other.execute("UPDATE agents SET state='BLOCKED', since=NULL WHERE agent='rugger-04'")
                    outcome["mid_flight"] = True
                except sqlite3.OperationalError:
                    outcome["mid_flight"] = False  # serialized by BEGIN IMMEDIATE
                finally:
                    other.close()
            return st

        rs.load_state = racing_load_state
        try:
            r = rx.handle_webhook(self.con, "issue_comment", "gha-run:3000", fx("issue_comment_report_04.json"), NOW)
        finally:
            rs.load_state = real
        if outcome.get("mid_flight"):
            self.assertFalse(r["handled"], "completion applied although the agent was BLOCKED concurrently")
            self.assertEqual(self.outbox(), 0)
            self.assertEqual(self.agent()["state"], "BLOCKED")
        else:
            self.assertTrue(r["handled"], r)
            self.con.execute("UPDATE agents SET state='BLOCKED', since=NULL WHERE agent='rugger-04'")
            self.assertEqual(self.agent()["state"], "BLOCKED")

    def test_parallel_deliveries_create_exactly_one_successor(self):
        results, errors = [], []

        def worker(i):
            try:
                c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
                p = fx("issue_comment_report_04.json")
                results.append(rx.handle_webhook(c, "issue_comment", f"gha-run:{4000 + i}", p, NOW)["handled"])
                c.close()
            except Exception as e:  # pragma: no cover - reported below
                errors.append(repr(e))

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(errors, [])
        self.assertEqual(results.count(True), 1, results)
        self.assertEqual(self.outbox(), 1)

    def test_label_on_other_issue_while_running_is_decided_inside_the_lock(self):
        p = fx("issues_labeled_04.json"); p["issue"]["number"] = 300
        r = rx.handle_webhook(self.con, "issues", "gha-run:5000", p, NOW)
        self.assertTrue(r["handled"])
        self.assertEqual(self.agent()["issue"], 200)
        self.assertEqual(self.con.execute("select count(*) from escalations").fetchone()[0], 1)


class P1_4_InvalidSince(unittest.TestCase):
    def test_decide_with_corrupted_since_blocks_without_exception(self):
        st = rp._empty_state()
        st["agents"]["rugger-03"] = {"state": "RUNNING", "issue": 7, "since": "not-a-date", "queue": []}
        dec = rp.decide({"id": "x", "action": "opened", "issue": {"number": 1, "labels": []}}, st, NOW)
        esc = [a for a in dec["actions"] if a["type"] == "ESCALATE_OWNER"]
        self.assertEqual(len(esc), 1)
        self.assertEqual(esc[0]["set_state"], {"rugger-03": "BLOCKED"})

    def test_decide_with_naive_or_missing_since_blocks(self):
        for since in ("2026-11-06T10:00:00", None, 12, ""):
            st = rp._empty_state()
            st["agents"]["rugger-01"] = {"state": "RUNNING", "issue": 9, "since": since, "queue": []}
            dec = rp.decide({"id": "x", "action": "opened", "issue": {"number": 1, "labels": []}}, st, NOW)
            self.assertTrue(any(a.get("set_state") == {"rugger-01": "BLOCKED"} for a in dec["actions"]), (since, dec))

    def test_executor_survives_corrupted_db_timestamp(self):
        con = rs.open_db(os.path.join(tempfile.mkdtemp(), "c.db"))
        rx.handle_webhook(con, "issues", "gha-run:6000", fx("issues_labeled_04.json"), NOW)
        con.execute("UPDATE agents SET since='garbage' WHERE agent='rugger-04'")
        r = rx.handle_webhook(con, "issue_comment", "gha-run:6001", fx("issue_comment_report_04.json"), NOW)
        self.assertFalse(r["handled"], r)
        self.assertEqual(rs.load_state(con)["agents"]["rugger-04"]["state"], "BLOCKED")
        self.assertEqual(con.execute("select count(*) from outbox").fetchone()[0], 0)


class SingleCircuitMissionLock(unittest.TestCase):
    """One mission -> one responsible session (the #213 / #214 duplicate must be impossible)."""
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "m.db")
        self.con = rs.open_db(self.path)

    def test_second_session_cannot_claim_a_held_mission(self):
        a = rs.claim_mission(self.con, "T-0039", "session:interactive-r03", NOW)
        b = rs.claim_mission(self.con, "T-0039", "routine:rugger-03", NOW + timedelta(minutes=1))
        self.assertTrue(a["granted"]); self.assertFalse(b["granted"])
        self.assertEqual(b["holder"], "session:interactive-r03")

    def test_parallel_claims_grant_exactly_one(self):
        out = []

        def w(i):
            c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            out.append(rs.claim_mission(c, "T-0040", f"session:{i}", NOW)["granted"]); c.close()

        ts = [threading.Thread(target=w, args=(i,)) for i in range(10)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(out.count(True), 1)

    def test_start_proof_and_terminal_state(self):
        rs.claim_mission(self.con, "T-1", "s1", NOW)
        self.assertFalse(rs.start_mission(self.con, "T-1", "s2", "commit abc", NOW)["ok"])
        self.assertFalse(rs.start_mission(self.con, "T-1", "s1", "", NOW)["ok"])  # proof required
        self.assertTrue(rs.start_mission(self.con, "T-1", "s1", "comment 123", NOW)["ok"])
        self.assertFalse(rs.finish_mission(self.con, "T-1", "s2", "COMPLETED", NOW)["ok"])
        self.assertTrue(rs.finish_mission(self.con, "T-1", "s1", "COMPLETED", NOW)["ok"])
        r = rs.claim_mission(self.con, "T-1", "s3", NOW + timedelta(days=2))
        self.assertFalse(r["granted"]); self.assertIn("terminal", r["reason"])

    def test_bounded_retry_after_lease_expiry_then_owner_escalation(self):
        lease = timedelta(minutes=rs.MISSION_LEASE_MIN)
        t = NOW
        self.assertTrue(rs.claim_mission(self.con, "T-2", "s0", t)["granted"])
        for i in range(1, rs.MISSION_MAX_ATTEMPTS):
            self.assertFalse(rs.claim_mission(self.con, "T-2", f"s{i}", t + lease - timedelta(seconds=1))["granted"])
            t = t + lease + timedelta(seconds=1)
            self.assertTrue(rs.claim_mission(self.con, "T-2", f"s{i}", t)["granted"], i)
        r = rs.claim_mission(self.con, "T-2", "late", t + lease + timedelta(seconds=1))
        self.assertFalse(r["granted"]); self.assertIn("escalate", r["reason"])
        self.assertEqual(rs.mission(self.con, "T-2")["state"], "BLOCKED")
        self.assertGreaterEqual(self.con.execute("select count(*) from escalations").fetchone()[0], 1)

    def test_heartbeat_extends_lease_only_for_holder(self):
        rs.claim_mission(self.con, "T-3", "s1", NOW)
        rs.start_mission(self.con, "T-3", "s1", "comment 1", NOW)
        self.assertFalse(rs.heartbeat_mission(self.con, "T-3", "s2", NOW)["ok"])
        later = NOW + timedelta(minutes=rs.MISSION_LEASE_MIN - 1)
        self.assertTrue(rs.heartbeat_mission(self.con, "T-3", "s1", later)["ok"])
        self.assertFalse(rs.claim_mission(self.con, "T-3", "s2", later + timedelta(minutes=2))["granted"])

    def test_invalid_inputs_refused(self):
        for mid, holder in (("", "s"), ("T-9", ""), (None, "s"), ("T-9", None), ("x" * 200, "s")):
            self.assertFalse(rs.claim_mission(self.con, mid, holder, NOW)["granted"])
        naive = datetime(2026, 11, 6, 12, 0)
        self.assertFalse(rs.claim_mission(self.con, "T-9", "s", naive)["granted"])


if __name__ == "__main__":
    unittest.main()
