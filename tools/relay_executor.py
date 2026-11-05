"""Bounded relay executor (issue #200). NOT ACTIVATED: no network, no secret, dry-run sender only.

Entry point `handle_webhook(con, event_name, delivery_id, payload, now, ...)` turns a REAL GitHub
webhook payload (issues / issue_comment / workflow_run) into planner decisions, persists them
atomically (relay_store) and returns the outbox rows to send after commit.
All timestamps are timezone-aware UTC; naive datetimes are refused.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tools import relay_planner as rp, relay_store as rs, relay_payload as rpl

HANDLED = ("issues", "issue_comment", "workflow_run")
ALLOWED_REPO = "laurentmaxence13-svg/rugger_bot_v1"
# Explicit allowlists (no wildcard). Humans: owner only. Bots: none until the owner names one
# (the real identity of the Claude Code Cloud / GitHub App actor is UNKNOWN, not guessed).
ALLOWED_USERS = frozenset({"laurentmaxence13-svg"})
ALLOWED_BOTS = frozenset()
ALLOWED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER"})


def _login_ok(user) -> bool:
    if not isinstance(user, dict) or not isinstance(user.get("login"), str):
        return False
    if user.get("type") == "Bot":
        return user["login"] in ALLOWED_BOTS
    return user["login"] in ALLOWED_USERS


def authorize(event_name: str, payload: dict) -> str | None:
    """None if authorised, else the refusal reason. Missing data => refusal (fail-closed)."""
    repo = payload.get("repository")
    if not isinstance(repo, dict) or repo.get("full_name") != ALLOWED_REPO:
        return "refused: repository is not exactly " + ALLOWED_REPO
    if not _login_ok(payload.get("sender")):
        return "refused: sender missing or not allowlisted"
    if event_name == "issue_comment":
        c = payload.get("comment")
        if not isinstance(c, dict) or not _login_ok(c.get("user")):
            return "refused: comment author missing or not allowlisted"
        if c["user"]["login"] != payload["sender"]["login"]:
            return "refused: comment author differs from sender"
        if c.get("author_association") not in ALLOWED_ASSOCIATIONS:
            return "refused: author_association not OWNER/MEMBER"
        if not isinstance(c.get("id"), int):
            return "refused: comment id missing"
    return None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _agent_of(labels):
    return next((a for a in rp.AGENTS if rp.TRIGGER_LABEL.format(agent=a) in labels), None)


def _escalate(con, reason, now):
    rs.apply_decision(con, {"actions": [{"type": "ESCALATE_OWNER", "reason": reason}]}, now, None)


def handle_webhook(con, event_name: str, delivery_id: str, payload: dict, now: datetime, last_comment: str = "") -> dict:
    """Returns {"handled": bool, "reason": str, "decision": dict|None}. Never raises on bad input (fail-closed)."""
    if now.tzinfo is None or now.utcoffset().total_seconds() != 0:
        return {"handled": False, "reason": "refused: now must be UTC-aware", "decision": None}
    if rs.kill_switch_on(con):
        return {"handled": False, "reason": "kill switch ON: no action", "decision": None}
    if event_name not in HANDLED or not delivery_id or not isinstance(payload, dict):
        return {"handled": False, "reason": "unsupported/malformed event", "decision": None}
    bad = authorize(event_name, payload)
    if bad:
        return {"handled": False, "reason": bad, "decision": None}
    act = payload.get("action")

    if event_name == "workflow_run":
        wr = payload.get("workflow_run") or {}
        if act != "completed" or wr.get("conclusion") in (None, "success", "skipped", "cancelled"):
            return {"handled": False, "reason": "workflow_run not a failure", "decision": None}
        dec = {"actions": [{"type": "ESCALATE_OWNER", "reason": f"workflow_run {wr.get('id')} concluded {wr.get('conclusion')}"}]}
        ok = rs.apply_decision(con, dec, now, f"{delivery_id}:wf")
        return {"handled": ok, "reason": "workflow failure escalated" if ok else "duplicate delivery", "decision": dec if ok else None}

    issue = payload.get("issue")
    if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
        return {"handled": False, "reason": "malformed issue payload", "decision": None}
    n = issue["number"]
    labels = rp.label_names(issue.get("labels"))
    agent = _agent_of(labels)
    if not agent:
        return {"handled": False, "reason": "no rugger-0N-run label", "decision": None}
    if "pull_request" in issue:
        return {"handled": False, "reason": "pull request, ignored", "decision": None}

    if event_name == "issues" and act == "labeled":
        lab = (payload.get("label") or {}).get("name")
        if lab != rp.TRIGGER_LABEL.format(agent=agent):
            return {"handled": False, "reason": "other label", "decision": None}
        cur = rs.load_state(con)["agents"][agent]
        if cur["state"] == "RUNNING" and cur["issue"] not in (None, n):
            dec = {"actions": [{"type": "ESCALATE_OWNER", "reason": f"{agent} already RUNNING on #{cur['issue']}; #{n} labeled (max 1 run/agent)"}]}
        else:
            dec = {"actions": [{"type": "SET_STATE", "agent": agent, "state": "RUNNING", "issue": n}]}
        ok = rs.apply_decision(con, dec, now, f"{delivery_id}:label")
        return {"handled": ok, "reason": "labeled" if ok else "duplicate delivery", "decision": dec if ok else None}

    # Completion: issue closed (report = last_comment) OR a report comment carrying the STATUS contract.
    if event_name == "issue_comment" and act == "created":
        body = (payload.get("comment") or {}).get("body") or ""
        if not rp._final_status(body):
            return {"handled": False, "reason": "comment without STATUS contract", "decision": None}
    elif event_name == "issues" and act == "closed":
        body = last_comment
    else:
        return {"handled": False, "reason": "event not a completion", "decision": None}

    # Proven prior launch: the agent must be RUNNING on exactly this issue (WAITING/READY/COMPLETED/BLOCKED refused).
    cur = rs.load_state(con)["agents"][agent]
    if cur["state"] != "RUNNING" or cur["issue"] != n:
        return {"handled": False, "reason": f"refused: {agent} not RUNNING on #{n} (state={cur['state']}, issue={cur['issue']})", "decision": None}
    if con.execute("SELECT 1 FROM processed WHERE key=?", (f"issue-done:{n}",)).fetchone():
        return {"handled": False, "reason": f"issue #{n} completion already processed", "decision": None}
    # Dedup keys (comment id, delivery id, issue completion) are claimed in the SAME transaction as the effects.
    keys = [f"delivery:{delivery_id}", f"issue-done:{n}"]
    if event_name == "issue_comment":
        keys.append(f"comment:{payload['comment']['id']}")
    ev = {"id": delivery_id, "action": "closed",
          "issue": {"number": n, "state": "closed", "labels": labels, "last_comment": body}}
    dec = rs.process_event(con, ev, now, tuple(keys))
    if not dec["actions"] and "idempotent" in dec.get("reason", ""):
        return {"handled": False, "reason": dec["reason"], "decision": None}
    return {"handled": True, "reason": dec.get("reason", ""), "decision": dec}


def drain_outbox(con, send, now: datetime) -> list:
    """Send PENDING issue creations (after commit). Honours the kill switch."""
    if rs.kill_switch_on(con):
        return []
    return rs.run_outbox(con, send)


def catchup(con, now: datetime) -> dict:
    """Scheduled safety net: watchdog + promotion of queued tasks, persisted atomically."""
    if rs.kill_switch_on(con):
        return {"actions": [], "reason": "kill switch ON"}
    st = rs.load_state(con)
    dec = {"actions": rp.watchdog(st, now)["actions"] + rp.promote(st, now)["actions"], "reason": "catch-up"}
    rs.apply_decision(con, dec, now, None)
    return dec


def dry_run_send(payload: dict) -> None:
    """Default sender: prints intent only. A real sender needs owner-approved credentials (not provided)."""
    print("DRY-RUN create issue:", payload.get("title"), "labels=", payload.get("labels"), "dedupe=", payload["dedupe"])
