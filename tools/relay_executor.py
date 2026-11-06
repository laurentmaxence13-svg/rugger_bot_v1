"""Bounded relay executor (issue #200). NOT ACTIVATED: no network, no secret, dry-run sender only.

Entry point `handle_webhook(con, event_name, delivery_id, payload, now, report_comment=None)` turns a
REAL GitHub event payload (issues / issue_comment / workflow_run) into planner decisions, persists them
atomically (relay_store) and returns the outbox rows to send after commit.
All timestamps are timezone-aware UTC; naive datetimes are refused.

Counter-audit #210 fixes (mission #211):
- P1-1 `issues.closed` never trusts free text: the report must be an authenticated comment OBJECT
  (author allowlisted, OWNER/MEMBER, on this issue, created after the launch), fetched by the caller.
- P1-2 `delivery_id` has ONE accepted source: the GitHub Actions run (`gha-run:<GITHUB_RUN_ID>`), built
  by `delivery_id_from_actions_env`. Anything else is refused (fail-closed). A re-run of the same run
  keeps the same id, hence is idempotent. There is no HTTP webhook receiver, so no
  `X-GitHub-Delivery` / signature path exists; adding one requires signature verification first.
- P1-3 every state check that guards an effect is made inside the same BEGIN IMMEDIATE transaction.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from tools import relay_planner as rp, relay_store as rs, relay_payload as rpl

HANDLED = ("issues", "issue_comment", "workflow_run")
ALLOWED_REPO = "laurentmaxence13-svg/rugger_bot_v1"
# Explicit allowlists (no wildcard). Humans: owner only. Bots: none until the owner names one
# (the real identity of the Claude Code Cloud / GitHub App actor is UNKNOWN, not guessed).
ALLOWED_USERS = frozenset({"laurentmaxence13-svg"})
ALLOWED_BOTS = frozenset()
ALLOWED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER"})
DELIVERY_RE = re.compile(r"\Agha-run:[1-9][0-9]{0,19}\Z")


def delivery_id_from_actions_env(env: dict, event_name: str) -> str | None:
    """The only accepted delivery id source: the GitHub Actions run handling this event.
    None (=> refuse) if the run id, repository or event name is missing or inconsistent."""
    if not isinstance(env, dict):
        return None
    run_id = env.get("GITHUB_RUN_ID")
    if env.get("GITHUB_REPOSITORY") != ALLOWED_REPO or env.get("GITHUB_EVENT_NAME") != event_name:
        return None
    did = f"gha-run:{run_id}" if isinstance(run_id, str) else ""
    return did if DELIVERY_RE.match(did) else None


def _delivery_ok(delivery_id) -> bool:
    return isinstance(delivery_id, str) and bool(DELIVERY_RE.match(delivery_id))


def _parse_gh_time(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def authenticate_report(comment, issue_number: int, since) -> str | None:
    """P1-1. None if `comment` is a trustworthy report for this issue, else the refusal reason.
    `comment` must be the comment OBJECT (GET /repos/{repo}/issues/comments/{id}), never free text."""
    if not isinstance(comment, dict):
        return "refused: authenticated report comment object required (free text is never trusted)"
    if not _login_ok(comment.get("user")) or comment.get("author_association") not in ALLOWED_ASSOCIATIONS:
        return "refused: report author not allowlisted or not OWNER/MEMBER"
    if not isinstance(comment.get("id"), int) or isinstance(comment.get("id"), bool):
        return "refused: report comment id missing"
    if not isinstance(comment.get("body"), str):
        return "refused: report comment body missing"
    # issue_url is mandatory: without it the comment cannot be bound to this issue (R02 audit #215, B2)
    if comment.get("issue_url") != f"https://api.github.com/repos/{ALLOWED_REPO}/issues/{issue_number}":
        return "refused: report comment issue_url missing or bound to another issue/repository"
    created = _parse_gh_time(comment.get("created_at"))
    start = rp.parse_since(since)
    if created is None or start is None:
        return "refused: report or launch time missing or invalid"
    if created < start:
        return "refused: report comment written before the launch of this run"
    return None


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


def handle_webhook(con, event_name: str, delivery_id: str, payload: dict, now: datetime,
                   report_comment: dict | None = None, last_comment: str | None = None) -> dict:
    """Returns {"handled": bool, "reason": str, "decision": dict|None}. Never raises on bad input (fail-closed).
    `last_comment` (free text) is accepted only for backward compatibility and is NEVER trusted (P1-1)."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset().total_seconds() != 0:
        return {"handled": False, "reason": "refused: now must be UTC-aware", "decision": None}
    if rs.kill_switch_on(con):
        return {"handled": False, "reason": "kill switch ON: no action", "decision": None}
    if not _delivery_ok(delivery_id):
        return {"handled": False, "reason": "refused: delivery_id must be gha-run:<GITHUB_RUN_ID> (fail-closed)", "decision": None}
    if event_name not in HANDLED or not isinstance(payload, dict):
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
        def build_label(c):  # decided under the write lock (P1-3)
            cur = rs.load_state(c)["agents"][agent]
            if cur["state"] == "RUNNING" and cur["issue"] not in (None, n):
                dec = {"actions": [{"type": "ESCALATE_OWNER", "reason": f"{agent} already RUNNING on #{cur['issue']}; #{n} labeled (max 1 run/agent)"}]}
            else:
                dec = {"actions": [{"type": "SET_STATE", "agent": agent, "state": "RUNNING", "issue": n}]}
            return {"apply": True, "decision": dec, "keys": (f"{delivery_id}:label",), "reason": "labeled"}
        r = rs.transact(con, now, build_label)
        return {"handled": r["applied"], "reason": r["reason"] if r["applied"] else "duplicate delivery", "decision": r["decision"]}

    # Completion: an authenticated report comment, delivered either as issue_comment.created or, on
    # issues.closed, as the comment object fetched by the caller (P1-1). Free text is never trusted.
    if event_name == "issue_comment" and act == "created":
        report = payload.get("comment")
        body = (report or {}).get("body") or ""
        if not rp._final_status(body):
            return {"handled": False, "reason": "comment without STATUS contract", "decision": None}
    elif event_name == "issues" and act == "closed":
        report = report_comment
        if not isinstance(report, dict):
            return {"handled": False, "reason": "refused: issues.closed needs an authenticated report comment object; free text is never trusted", "decision": None}
        body = report.get("body") if isinstance(report.get("body"), str) else ""
    else:
        return {"handled": False, "reason": "event not a completion", "decision": None}

    def build_completion(c):
        # Everything below runs under BEGIN IMMEDIATE: the RUNNING check, the report authentication
        # against the launch time, the dedup keys and the effects cannot interleave (P1-3).
        st = rs.load_state(c)
        cur = st["agents"][agent]
        if cur["state"] == "RUNNING" and rp.parse_since(cur.get("since")) is None:
            # corrupted launch time: fail closed (P1-4), BLOCK the agent and tell the owner
            dec = {"actions": [{"type": "ESCALATE_OWNER", "reason": f"{agent} RUNNING on #{cur['issue']} without a valid start time",
                                "set_state": {agent: "BLOCKED"}}]}
            return {"apply": True, "decision": dec, "keys": (), "reason": "refused: invalid launch time, agent BLOCKED", "blocked": True}
        if cur["state"] != "RUNNING" or cur["issue"] != n:
            return {"apply": False, "reason": f"refused: {agent} not RUNNING on #{n} (state={cur['state']}, issue={cur['issue']})"}
        bad = authenticate_report(report, n, cur.get("since"))
        if bad:
            return {"apply": False, "reason": bad}
        keys = (f"delivery:{delivery_id}", f"issue-done:{n}", f"comment:{report['id']}")
        if any(c.execute("SELECT 1 FROM processed WHERE key=?", (k,)).fetchone() for k in keys[1:]):
            return {"apply": False, "reason": f"issue #{n} completion already processed"}
        ev = {"id": delivery_id, "action": "closed",
              "issue": {"number": n, "state": "closed", "labels": labels, "last_comment": body}}
        dec = rp.decide(ev, st, now)
        if not any(a["type"] == "MARK_PROCESSED" for a in dec["actions"]):
            return {"apply": False, "reason": dec.get("reason", "not a completion")}
        dec["actions"] = [a for a in dec["actions"] if a["type"] != "MARK_PROCESSED"]
        return {"apply": True, "decision": dec, "keys": (f"{delivery_id}:{n}",) + keys, "reason": dec.get("reason", "")}

    r = rs.transact(con, now, build_completion)
    if r["applied"] and r["reason"].startswith("refused:"):
        return {"handled": False, "reason": r["reason"], "decision": r["decision"]}
    return {"handled": r["applied"], "reason": r["reason"], "decision": r["decision"]}


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
