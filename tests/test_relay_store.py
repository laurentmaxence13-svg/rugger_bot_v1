import json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from tools import relay_planner as rp, relay_store as rs, relay_payload as rpl

NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)  # aware UTC: the relay refuses naive times (#210 P1-4)
GOOD = ("STATUS: COMPLETED\nNEXT_TASK:\n  agent: rugger-02\n  title: Audit PR 184\n"
        "  criteria: verifier atomicite checkpoint et fail-closed du quota\n")
OTHER = GOOD.replace("Audit PR 184", "Audit PR 191")


def ev(body, i="d1", n=9, labels=("rugger-01-run",)):
    return {"id": i, "action": "closed", "issue": {"number": n, "state": "closed", "labels": list(labels), "last_comment": body}}


def T(r): return [a["type"] for a in r["actions"]]


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.path = os.path.join(self.d, "r.db"); self.con = rs.open_db(self.path)
    def tearDown(self):
        self.con.close()


class Durable(Base):
    def test_state_survives_reopen_and_duplicate_delivery_is_noop(self):
        self.assertIn("CREATE_ISSUE", T(rs.process_event(self.con, ev(GOOD), NOW)))
        self.con.close(); self.con = rs.open_db(self.path)  # restart
        self.assertEqual(rs.process_event(self.con, ev(GOOD), NOW)["actions"], [])
        self.assertEqual(self.con.execute("select count(*) from outbox").fetchone()[0], 1)

    def test_same_successor_other_delivery_not_duplicated(self):
        rs.process_event(self.con, ev(GOOD, "d1"), NOW)
        rs.process_event(self.con, ev(GOOD, "d2", n=10), NOW + timedelta(minutes=1))
        self.assertEqual(self.con.execute("select count(*) from outbox").fetchone()[0], 1)

    def test_rollback_on_failure_leaves_no_partial_state(self):
        dec = rp.decide(ev(GOOD), rs.load_state(self.con), NOW)
        dec["actions"].append({"type": "CREATE_ISSUE", "agent": "rugger-02", "title": "x", "criteria": "y" * 20, "dedupe": "zz"})
        dec["actions"].append({"type": "CREATE_ISSUE", "agent": "rugger-02", "title": "x", "criteria": "y" * 20, "dedupe": "zz"})  # PK violation
        with self.assertRaises(Exception):
            rs.apply_decision(self.con, dec, NOW, "d1:9")
        self.assertEqual(self.con.execute("select count(*) from processed").fetchone()[0], 0)
        self.assertEqual(self.con.execute("select count(*) from outbox").fetchone()[0], 0)
        self.assertIn("CREATE_ISSUE", T(rs.process_event(self.con, ev(GOOD), NOW)))  # retry works

    def test_outbox_retry_then_fail(self):
        rs.process_event(self.con, ev(GOOD), NOW)
        def boom(p): raise RuntimeError("api down")
        for _ in range(rs.MAX_ATTEMPTS): rs.run_outbox(self.con, boom)
        self.assertEqual(self.con.execute("select status from outbox").fetchone()[0], "FAILED")

    def test_outbox_crash_before_send_is_resent_once(self):
        rs.process_event(self.con, ev(GOOD), NOW)
        sent = []
        self.assertEqual(len(rs.run_outbox(self.con, sent.append)), 1)
        self.assertEqual(rs.run_outbox(self.con, sent.append), [])
        self.assertEqual(len(sent), 1)


class Promotion(Base):
    def test_queue_then_promote_waiting_to_ready(self):
        self.con.execute("UPDATE agents SET state='RUNNING', since=? WHERE agent='rugger-02'", (NOW.isoformat(),))
        r = rs.process_event(self.con, ev(GOOD), NOW)
        self.assertIn("ENQUEUE", T(r)); self.assertNotIn("CREATE_ISSUE", T(r))
        self.assertEqual(rs.load_state(self.con)["agents"]["rugger-02"]["state"], "RUNNING")  # not clobbered
        self.assertEqual(rp.promote(rs.load_state(self.con), NOW)["actions"], [])  # still running
        rs.process_event(self.con, ev("STATUS: COMPLETED\n", "d2", 20, ("rugger-02-run",)), NOW + timedelta(hours=1))
        p = rp.promote(rs.load_state(self.con), NOW + timedelta(hours=1))
        self.assertEqual(T(p), ["SET_STATE", "CREATE_ISSUE", "ADD_LABEL", "SET_STATE"])
        self.assertEqual(p["actions"][0]["state"], "READY")
        rs.apply_decision(self.con, p, NOW + timedelta(hours=1))
        s = rs.load_state(self.con)["agents"]["rugger-02"]
        self.assertEqual((s["state"], s["queue"]), ("RUNNING", []))

    def test_promote_blocked_by_quota_stays_waiting(self):
        st = rp._empty_state(); st["agents"]["rugger-02"].update(queue=[{"title": "t", "criteria": "c" * 25}])
        st["launches"] = [{"agent": "rugger-02", "at": (NOW - timedelta(minutes=1)).isoformat(), "dedupe": f"q{i}"} for i in range(2)]
        self.assertEqual(rp.promote(st, NOW)["actions"], [])

    def test_promote_forbidden_queue_escalates(self):
        st = rp._empty_state(); st["agents"]["rugger-02"].update(queue=[{"title": "go live", "criteria": "c" * 25}])
        self.assertEqual(T(rp.promote(st, NOW)), ["ESCALATE_OWNER"])


class Payload(unittest.TestCase):
    def payload(self, labels):
        return {"action": "closed", "issue": {"number": 5, "state": "closed", "labels": labels}}

    def test_object_labels(self):
        e = rpl.parse_issues_payload(self.payload([{"name": "rugger-01-run", "id": 1}, {"name": "bug"}]), GOOD, "dlv-1")
        self.assertEqual(e["issue"]["labels"], ["rugger-01-run", "bug"])
        self.assertIn("CREATE_ISSUE", T(rp.decide(e, None, NOW)))

    def test_old_string_labels_and_garbage(self):
        self.assertEqual(rp.label_names(["a", {"name": "b"}, {"x": 1}, 3, None]), ["a", "b"])

    def test_malformed_or_no_delivery_id_refused(self):
        self.assertIsNone(rpl.parse_issues_payload({}, "", "d"))
        self.assertIsNone(rpl.parse_issues_payload(self.payload([]), "", ""))
        self.assertIsNone(rpl.parse_issues_payload({"action": "closed", "issue": {"number": "5"}}, "", "d"))


class Reports(unittest.TestCase):
    def test_real_legacy_formats_never_completed(self):
        cases = {
            "## RUGGER 02 — Audit\n**VERDICT : BLOCKED**\nbla": "legacy_blocked",       # #185
            "**État final : BLOCKED partiel** (B2 non clos)": "legacy_blocked",           # #190
            "**RUGGER 03 — statut : PRÉPARATION PARTIELLE (READY pour revue)**": "no_marker",  # #181
            "Tout est COMPLETED, merci": "no_marker",
            "STATUS: COMPLETED\nSTATUS: BLOCKED\n": "ambiguous_status",
            "STATUS: DONE\n": "ambiguous_status",
        }
        for body, src in cases.items():
            n = rp.normalize_report(body)
            self.assertEqual((n["status"], n["reliable"], n["source"]), ("BLOCKED", False, src), body)
            r = rp.decide(ev(body + "\n" + GOOD.split("\n", 1)[1]), None, NOW)  # even with a NEXT_TASK block
            self.assertNotIn("CREATE_ISSUE", T(r), body); self.assertIn("ESCALATE_OWNER", T(r))

    def test_contract_status_reliable(self):
        self.assertEqual(rp.normalize_report("x\nSTATUS: COMPLETED\n"), {"status": "COMPLETED", "reliable": True, "source": "contract"})


class Watchdog(Base):
    def test_watchdog_without_any_event(self):
        self.con.execute("UPDATE agents SET state='RUNNING', since=? WHERE agent='rugger-03'", ((NOW - timedelta(hours=7)).isoformat(),))
        w = rp.watchdog(rs.load_state(self.con), NOW)
        self.assertEqual(T(w), ["ESCALATE_OWNER"])
        rs.apply_decision(self.con, w, NOW)
        self.assertEqual(rs.load_state(self.con)["agents"]["rugger-03"]["state"], "BLOCKED")
        self.assertEqual(rp.watchdog(rs.load_state(self.con), NOW)["actions"], [])  # no repeat spam

    def test_watchdog_missing_start_fail_closed(self):
        st = rp._empty_state(); st["agents"]["rugger-01"].update(state="RUNNING", since=None)
        self.assertEqual(T(rp.watchdog(st, NOW)), ["ESCALATE_OWNER"])

    def test_corrupt_ledger_fails_closed(self):
        st = rp._empty_state(); st["launches"] = [{"agent": "rugger-02", "at": "garbage", "dedupe": "a"}]
        self.assertNotIn("CREATE_ISSUE", T(rp.decide(ev(GOOD), st, NOW)))


class Purity(unittest.TestCase):
    def test_planner_and_payload_have_no_io_imports(self):
        import ast, inspect
        for m in (rp, rpl):
            tree = ast.parse(inspect.getsource(m))
            mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
            mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertLessEqual(mods, {"__future__", "hashlib", "re", "datetime", "tools"})

    def test_store_has_no_network(self):
        import ast, inspect
        tree = ast.parse(inspect.getsource(rs))
        mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(mods, {"__future__", "json", "sqlite3", "datetime", "tools"})


if __name__ == "__main__":
    unittest.main()
