"""RUGGER relay planner — PURE decision logic, NOT ACTIVATED (issue #187).

No network, no GitHub call, no file write, no subprocess. Input: a simulated
GitHub event + a state dict. Output: a list of *intended* actions. A future
workflow may execute those actions only after explicit owner approval.
States: WAITING / READY / RUNNING / COMPLETED / BLOCKED.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

AGENTS = ("rugger-01", "rugger-02", "rugger-03", "rugger-04")
TRIGGER_LABEL = "{agent}-run"
STATES = ("WAITING", "READY", "RUNNING", "COMPLETED", "BLOCKED")
LIMITS = {"per_agent_hour": 2, "per_agent_day": 6, "global_day": 16, "running_timeout_h": 6}
# Anything touching these domains is never auto-chained: escalate to owner.
FORBIDDEN = re.compile(
    r"\b(live|mainnet|trade|trading|order|ordre|paiement|payment|abonnement|subscription|"
    r"secret|private[_ -]?key|seed|merge|fusion|main|protection|permission|d[ée]ploi\w*|deploy\w*)\b",
    re.I,
)
NEXT_RE = re.compile(r"^NEXT_TASK:\s*\n((?:[ \t]+\S.*\n?)+)", re.M)


def _parse_next(body: str):
    m = NEXT_RE.search(body or "")
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.strip().split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _final_status(body: str):
    """Strict contract only: exactly one distinct `STATUS:` value, else None."""
    vals = set(re.findall(r"^STATUS:[ \t]*(COMPLETED|BLOCKED)[ \t]*$", body or "", re.M))
    return vals.pop() if len(vals) == 1 else None


# Legacy (pre-contract) report headers seen in #185 / #190 / #181. They are
# NEVER trusted as COMPLETED; they can only make the outcome *more* cautious.
_LEGACY_BLOCKED = re.compile(r"(VERDICT\s*:\s*\**\s*BLOCKED|[EÉ]tat final\s*:\s*\**\s*BLOCKED|statut\s*:\s*\**\s*BLOCKED)", re.I)


def normalize_report(body: str) -> dict:
    """-> {"status": COMPLETED|BLOCKED, "reliable": bool, "source": str}.
    Unreliable formats collapse to BLOCKED (fail-closed): no successor is created."""
    st = _final_status(body)
    if st:
        return {"status": st, "reliable": True, "source": "contract"}
    if re.search(r"^STATUS:", body or "", re.M):
        return {"status": "BLOCKED", "reliable": False, "source": "ambiguous_status"}
    if _LEGACY_BLOCKED.search(body or ""):
        return {"status": "BLOCKED", "reliable": False, "source": "legacy_blocked"}
    return {"status": "BLOCKED", "reliable": False, "source": "no_marker"}


def label_names(labels) -> list:
    """GitHub webhook labels are objects [{"name":..}]; simulated events use str."""
    out = []
    for l in labels or []:
        n = l.get("name") if isinstance(l, dict) else l
        if isinstance(n, str):
            out.append(n)
    return out


def parse_since(value):
    """A RUNNING start time as an aware datetime, or None if missing, malformed or naive (fail-closed)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None and dt.utcoffset() is not None else None


def _empty_state():
    return {"agents": {a: {"state": "WAITING", "issue": None, "since": None} for a in AGENTS},
            "processed": [], "launches": [], "version": 2}


def decide(event: dict, state: dict | None, now: datetime) -> dict:
    """event: {"id","action","issue":{"number","state","labels":[..],"last_comment"}}"""
    st = state or _empty_state()
    esc = lambda why: {"actions": [{"type": "ESCALATE_OWNER", "reason": why}], "reason": why}
    noop = lambda why: {"actions": [], "reason": why}
    issue = event.get("issue") or {}
    labels = label_names(issue.get("labels"))
    agent = next((a for a in AGENTS if TRIGGER_LABEL.format(agent=a) in labels), None)

    # Watchdog first: independent of the event. Same fail-closed rule as watchdog():
    # a RUNNING agent with a missing/invalid/naive start time is BLOCKED, never an exception (#210 P1-4).
    wd = watchdog(st, now)["actions"]

    if event.get("action") != "closed" or issue.get("state") != "closed" or not agent:
        r = noop("not a closed rugger-0N-run issue")
        r["actions"] = wd
        return r
    key = f"{event.get('id')}:{issue.get('number')}"
    if key in st["processed"]:
        return noop("idempotent: event already processed")

    body = issue.get("last_comment") or ""
    rep = normalize_report(body)
    status = rep["status"] if rep["reliable"] else None
    base = [{"type": "MARK_PROCESSED", "key": key}, {"type": "SET_STATE", "agent": agent, "state": status or "BLOCKED"}]
    if status is None:
        r = esc(f"unreliable report format ({rep['source']}): no valid single STATUS marker"); r["actions"] = base + r["actions"] + wd; return r
    if status == "BLOCKED":
        r = esc("report BLOCKED: owner action required"); r["actions"] = base + r["actions"] + wd; return r
    nxt = _parse_next(body)
    if not nxt:
        return {"actions": base + wd, "reason": "COMPLETED without NEXT_TASK: no auto-created mission"}
    tgt, title, crit = nxt.get("agent", ""), nxt.get("title", ""), nxt.get("criteria", "")
    if tgt not in AGENTS or not title or len(crit) < 20:
        r = esc("NEXT_TASK invalid or without precise criteria"); r["actions"] = base + r["actions"] + wd; return r
    if FORBIDDEN.search(title + " " + crit + " " + nxt.get("scope", "")):
        r = esc("NEXT_TASK touches forbidden domain (live/trade/payment/secret/merge/protection)")
        r["actions"] = base + r["actions"] + wd; return r
    if st["agents"][tgt]["state"] == "RUNNING":
        return {"actions": base + [{"type": "ENQUEUE", "agent": tgt, "task": {"title": title, "criteria": crit}}] + wd,
                "reason": f"max 1 run/agent: {tgt} RUNNING, successor queued (agent state unchanged)"}
    if _quota_exceeded(st, tgt, now):
        r = esc("quota exceeded"); r["actions"] = base + r["actions"] + wd; return r
    dedupe = hashlib.sha256(f"{tgt}|{title}|{crit}".encode()).hexdigest()[:12]
    if any(t.get("dedupe") == dedupe for t in st["launches"]):
        return {"actions": base + wd, "reason": "identical successor already created"}
    return {"actions": base + wd + [
        {"type": "CREATE_ISSUE", "agent": tgt, "title": title, "criteria": crit, "dedupe": dedupe},
        {"type": "ADD_LABEL", "label": TRIGGER_LABEL.format(agent=tgt)},
        {"type": "SET_STATE", "agent": tgt, "state": "RUNNING"}], "reason": "successor authorised"}



def _quota_exceeded(st: dict, tgt: str, now: datetime) -> bool:
    try:
        hour = [t for t in st["launches"] if t["agent"] == tgt and now - datetime.fromisoformat(t["at"]) < timedelta(hours=1)]
        day = [t for t in st["launches"] if now - datetime.fromisoformat(t["at"]) < timedelta(days=1)]
    except (KeyError, TypeError, ValueError):
        return True  # corrupted ledger => fail closed
    return (len(hour) >= LIMITS["per_agent_hour"]
            or len([t for t in day if t["agent"] == tgt]) >= LIMITS["per_agent_day"]
            or len(day) >= LIMITS["global_day"])


def promote(state: dict | None, now: datetime) -> dict:
    """WAITING -> READY promotion: a WAITING agent holding a queued task becomes
    READY (and a CREATE_ISSUE is planned) only if no agent run is active for it,
    quotas allow it, and the queued task is not a duplicate. Else it stays WAITING."""
    st = state or _empty_state()
    actions = []
    for a, s in st["agents"].items():
        q = s.get("queue")
        if s.get("state") not in ("WAITING", "COMPLETED") or not q:
            continue
        if _quota_exceeded(st, a, now):
            continue  # stays WAITING; no escalation spam
        title, crit = q[0].get("title", ""), q[0].get("criteria", "")
        if len(crit) < 20 or FORBIDDEN.search(title + " " + crit):
            actions.append({"type": "ESCALATE_OWNER", "reason": f"queued task for {a} invalid/forbidden", "drop_queue": a})
            continue
        dedupe = hashlib.sha256(f"{a}|{title}|{crit}".encode()).hexdigest()[:12]
        if any(t.get("dedupe") == dedupe for t in st["launches"]):
            actions.append({"type": "DROP_QUEUED", "agent": a, "dedupe": dedupe})
            continue
        actions += [{"type": "SET_STATE", "agent": a, "state": "READY"},
                    {"type": "CREATE_ISSUE", "agent": a, "title": title, "criteria": crit, "dedupe": dedupe},
                    {"type": "ADD_LABEL", "label": TRIGGER_LABEL.format(agent=a)},
                    {"type": "SET_STATE", "agent": a, "state": "RUNNING"}]
    return {"actions": actions, "reason": "promotion pass"}


def watchdog(state: dict | None, now: datetime) -> dict:
    """Event-independent check, meant to be invoked by a scheduler (NOT enabled).
    Escalates RUNNING agents past timeout and agents with unparsable timestamps."""
    st = state or _empty_state()
    actions = []
    for a, s in st["agents"].items():
        if s.get("state") != "RUNNING":
            continue
        since = parse_since(s.get("since"))
        late = since is None or now - since > timedelta(hours=LIMITS["running_timeout_h"])  # unknown start => fail closed
        if late:
            actions.append({"type": "ESCALATE_OWNER", "reason": f"watchdog: {a} RUNNING > {LIMITS['running_timeout_h']}h or no valid start time",
                            "set_state": {a: "BLOCKED"}})
    return {"actions": actions, "reason": "watchdog pass"}
