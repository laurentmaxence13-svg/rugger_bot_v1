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
    m = re.search(r"^STATUS:\s*(COMPLETED|BLOCKED)\s*$", body or "", re.M)
    return m.group(1) if m else None


def _empty_state():
    return {"agents": {a: {"state": "WAITING", "issue": None, "since": None} for a in AGENTS},
            "processed": [], "launches": []}


def decide(event: dict, state: dict | None, now: datetime) -> dict:
    """event: {"id","action","issue":{"number","state","labels":[..],"last_comment"}}"""
    st = state or _empty_state()
    esc = lambda why: {"actions": [{"type": "ESCALATE_OWNER", "reason": why}], "reason": why}
    noop = lambda why: {"actions": [], "reason": why}
    issue = event.get("issue") or {}
    labels = issue.get("labels") or []
    agent = next((a for a in AGENTS if TRIGGER_LABEL.format(agent=a) in labels), None)

    # Watchdog first: independent of the event.
    wd = []
    for a, s in st["agents"].items():
        if s["state"] == "RUNNING" and s["since"] and \
                now - datetime.fromisoformat(s["since"]) > timedelta(hours=LIMITS["running_timeout_h"]):
            wd.append({"type": "ESCALATE_OWNER", "reason": f"watchdog: {a} RUNNING > {LIMITS['running_timeout_h']}h",
                       "set_state": {a: "BLOCKED"}})

    if event.get("action") != "closed" or issue.get("state") != "closed" or not agent:
        r = noop("not a closed rugger-0N-run issue")
        r["actions"] = wd
        return r
    key = f"{event.get('id')}:{issue.get('number')}"
    if key in st["processed"]:
        return noop("idempotent: event already processed")

    body = issue.get("last_comment") or ""
    status = _final_status(body)
    base = [{"type": "MARK_PROCESSED", "key": key}, {"type": "SET_STATE", "agent": agent, "state": status or "BLOCKED"}]
    if status is None:
        r = esc("no final STATUS marker in last report"); r["actions"] = base + r["actions"] + wd; return r
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
        return {"actions": base + [{"type": "SET_STATE", "agent": tgt, "state": "WAITING", "queued": title}] + wd,
                "reason": f"max 1 run/agent: {tgt} RUNNING, successor queued as WAITING"}
    hour = [t for t in st["launches"] if t["agent"] == tgt and now - datetime.fromisoformat(t["at"]) < timedelta(hours=1)]
    day = [t for t in st["launches"] if now - datetime.fromisoformat(t["at"]) < timedelta(days=1)]
    if len(hour) >= LIMITS["per_agent_hour"] or len([t for t in day if t["agent"] == tgt]) >= LIMITS["per_agent_day"] \
            or len(day) >= LIMITS["global_day"]:
        r = esc("quota exceeded"); r["actions"] = base + r["actions"] + wd; return r
    dedupe = hashlib.sha256(f"{tgt}|{title}|{crit}".encode()).hexdigest()[:12]
    if any(t.get("dedupe") == dedupe for t in st["launches"]):
        return {"actions": base + wd, "reason": "identical successor already created"}
    return {"actions": base + wd + [
        {"type": "CREATE_ISSUE", "agent": tgt, "title": title, "criteria": crit, "dedupe": dedupe},
        {"type": "ADD_LABEL", "label": TRIGGER_LABEL.format(agent=tgt)},
        {"type": "SET_STATE", "agent": tgt, "state": "RUNNING"}], "reason": "successor authorised"}
