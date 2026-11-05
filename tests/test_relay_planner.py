import unittest
from datetime import datetime, timedelta
from tools import relay_planner as rp

NOW = datetime(2026, 11, 6, 12, 0, 0)
GOOD = ("STATUS: COMPLETED\nNEXT_TASK:\n  agent: rugger-02\n  title: Audit PR 184\n"
        "  criteria: verifier atomicite checkpoint et fail-closed du quota\n")


def ev(body, i="e1", labels=("rugger-01-run",), action="closed", state="closed"):
    return {"id": i, "action": action, "issue": {"number": 9, "state": state, "labels": list(labels), "last_comment": body}}


def types(r):
    return [a["type"] for a in r["actions"]]


class T(unittest.TestCase):
    def test_success_creates_successor(self):
        r = rp.decide(ev(GOOD), None, NOW)
        self.assertIn("CREATE_ISSUE", types(r)); self.assertIn("ADD_LABEL", types(r))

    def test_idempotent(self):
        st = rp._empty_state(); st["processed"].append("e1:9")
        self.assertEqual(rp.decide(ev(GOOD), st, NOW)["actions"], [])

    def test_no_next_task_no_creation(self):
        self.assertNotIn("CREATE_ISSUE", types(rp.decide(ev("STATUS: COMPLETED\n"), None, NOW)))

    def test_blocked_escalates(self):
        self.assertIn("ESCALATE_OWNER", types(rp.decide(ev("STATUS: BLOCKED\n"), None, NOW)))

    def test_missing_status_escalates(self):
        self.assertIn("ESCALATE_OWNER", types(rp.decide(ev("rapport libre"), None, NOW)))

    def test_vague_criteria_rejected(self):
        b = "STATUS: COMPLETED\nNEXT_TASK:\n  agent: rugger-02\n  title: Auditer\n  criteria: voir\n"
        r = rp.decide(ev(b), None, NOW); self.assertNotIn("CREATE_ISSUE", types(r)); self.assertIn("ESCALATE_OWNER", types(r))

    def test_forbidden_domains(self):
        for w in ("lancer un trade live", "fusion dans main", "modifier un secret", "activer un abonnement payant", "deploy en prod"):
            b = GOOD.replace("Audit PR 184", w)
            self.assertNotIn("CREATE_ISSUE", types(rp.decide(ev(b), None, NOW)), w)

    def test_max_one_run_per_agent(self):
        st = rp._empty_state(); st["agents"]["rugger-02"].update(state="RUNNING", since=NOW.isoformat())
        r = rp.decide(ev(GOOD), st, NOW); self.assertNotIn("CREATE_ISSUE", types(r))

    def test_hourly_quota(self):
        st = rp._empty_state()
        st["launches"] = [{"agent": "rugger-02", "at": (NOW - timedelta(minutes=5)).isoformat(), "dedupe": f"x{i}"} for i in range(2)]
        self.assertIn("ESCALATE_OWNER", types(rp.decide(ev(GOOD), st, NOW)))

    def test_global_day_quota(self):
        st = rp._empty_state()
        st["launches"] = [{"agent": "rugger-03", "at": (NOW - timedelta(hours=3)).isoformat(), "dedupe": f"x{i}"} for i in range(16)]
        self.assertNotIn("CREATE_ISSUE", types(rp.decide(ev(GOOD), st, NOW)))

    def test_duplicate_successor(self):
        r = rp.decide(ev(GOOD), None, NOW)
        d = next(a["dedupe"] for a in r["actions"] if a["type"] == "CREATE_ISSUE")
        st = rp._empty_state(); st["launches"] = [{"agent": "rugger-02", "at": (NOW - timedelta(hours=2)).isoformat(), "dedupe": d}]
        self.assertNotIn("CREATE_ISSUE", types(rp.decide(ev(GOOD, i="e2"), st, NOW)))

    def test_watchdog(self):
        st = rp._empty_state(); st["agents"]["rugger-03"].update(state="RUNNING", since=(NOW - timedelta(hours=7)).isoformat())
        r = rp.decide(ev("x", action="opened", state="open"), st, NOW)
        self.assertIn("ESCALATE_OWNER", types(r))

    def test_ignores_other_events(self):
        self.assertEqual(rp.decide(ev(GOOD, action="labeled", state="open"), None, NOW)["actions"], [])
        self.assertEqual(rp.decide(ev(GOOD, labels=("bug",)), None, NOW)["actions"], [])

    def test_module_is_pure(self):
        import ast, inspect
        tree = ast.parse(inspect.getsource(rp))
        mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(mods, {"__future__", "hashlib", "re", "datetime"})
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn("open", calls)


if __name__ == "__main__":
    unittest.main()
