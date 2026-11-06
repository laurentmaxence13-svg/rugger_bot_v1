"""Durable relay state + transactional idempotence (SQLite, stdlib only). NOT ACTIVATED.

Contract
- `processed(key)` PRIMARY KEY: an event is applied at most once.
- `outbox(dedupe)` PRIMARY KEY: an issue creation is *recorded* in the same
  transaction as the event mark; the external GitHub call happens AFTER commit via
  `run_outbox(send)`. A crash between commit and send leaves the row PENDING and
  it is retried; `send` must embed `dedupe` in the created issue body so a
  retry can first look for an existing issue (at-least-once + dedupe = effectively once).
- All writes of one event happen in one BEGIN IMMEDIATE transaction (rollback on error).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from tools import relay_planner as rp

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed(key TEXT PRIMARY KEY, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agents(agent TEXT PRIMARY KEY, state TEXT NOT NULL, issue INTEGER, since TEXT, queue TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS launches(dedupe TEXT PRIMARY KEY, agent TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(dedupe TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS escalations(id INTEGER PRIMARY KEY AUTOINCREMENT, reason TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS missions(mission TEXT PRIMARY KEY, holder TEXT, state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, lease_until TEXT, start_proof TEXT, updated_at TEXT NOT NULL);
"""
MAX_ATTEMPTS = 3
# Single-circuit mission lock (#211): one mission -> one responsible session at a time.
MISSION_LEASE_MIN = 90          # a claim without heartbeat expires after this many minutes
MISSION_MAX_ATTEMPTS = 3        # claims (initial + retries) before the owner must decide
MISSION_TERMINAL = ("COMPLETED", "BLOCKED", "CANCELLED")


def open_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None)
    con.executescript(SCHEMA)
    for a in rp.AGENTS:
        con.execute("INSERT OR IGNORE INTO agents(agent,state) VALUES(?, 'WAITING')", (a,))
    return con


def load_state(con) -> dict:
    st = rp._empty_state()
    for a, state, issue, since, queue in con.execute("SELECT agent,state,issue,since,queue FROM agents"):
        st["agents"][a] = {"state": state, "issue": issue, "since": since, "queue": json.loads(queue)}
    st["processed"] = [r[0] for r in con.execute("SELECT key FROM processed")]
    st["launches"] = [{"agent": a, "at": t, "dedupe": d} for d, a, t in con.execute("SELECT dedupe,agent,at FROM launches")]
    return st


def _claim_keys(con, keys, now) -> bool:
    """Inside an open transaction: claim every dedup key, False if one is already taken."""
    for k in keys:
        if con.execute("INSERT OR IGNORE INTO processed(key,at) VALUES(?,?)", (k, now.isoformat())).rowcount == 0:
            return False
    return True


def apply_decision(con, decision: dict, now: datetime, key: str | None = None, extra_keys: tuple = ()) -> bool:
    """Atomically persist a planner decision. Returns False if `key` was already processed."""
    con.execute("BEGIN IMMEDIATE")
    try:
        if kill_switch_on(con):  # same rule as transact(): the switch is honoured under the lock
            con.execute("ROLLBACK")
            return False
        if not _claim_keys(con, ((key,) if key is not None else ()) + tuple(extra_keys), now):
            con.execute("ROLLBACK")
            return False
        _apply_actions(con, decision, now)
        con.execute("COMMIT")
        return True
    except Exception:
        con.execute("ROLLBACK")
        raise


def transact(con, now: datetime, build) -> dict:
    """Run `build(con)` and its effects in ONE `BEGIN IMMEDIATE` transaction (#210 P1-3: no TOCTOU).

    `build(con)` reads the current state *under the write lock* and returns
    {"apply": bool, "reason": str, "decision": dict|None, "keys": tuple}. Keys are claimed and the
    decision applied only if `apply` is true; otherwise everything is rolled back (no side effect)."""
    con.execute("BEGIN IMMEDIATE")
    try:
        if kill_switch_on(con):  # re-read under the write lock (R02 audit #215, B1)
            con.execute("ROLLBACK")
            return {"applied": False, "reason": "kill switch ON: no action", "decision": None}
        out = build(con)
        if not out.get("apply"):
            con.execute("ROLLBACK")
            return {"applied": False, "reason": out.get("reason", ""), "decision": None}
        if not _claim_keys(con, tuple(out.get("keys") or ()), now):
            con.execute("ROLLBACK")
            return {"applied": False, "reason": "idempotent: event already processed", "decision": None}
        _apply_actions(con, out["decision"], now)
        con.execute("COMMIT")
        return {"applied": True, "reason": out.get("reason", ""), "decision": out["decision"]}
    except Exception:
        con.execute("ROLLBACK")
        raise


def _apply_actions(con, decision: dict, now: datetime) -> None:
    """Write the effects of a decision. Caller owns the transaction."""
    pending_label = next((x["label"] for x in decision.get("actions", []) if x["type"] == "ADD_LABEL"), None)
    for a in decision.get("actions", []):
        t = a["type"]
        if t == "ADD_LABEL":
            pass  # merged into the CREATE_ISSUE payload (one API call)
        elif t == "SET_STATE":
            since = now.isoformat() if a["state"] == "RUNNING" else None
            if "issue" in a:
                con.execute("UPDATE agents SET state=?, since=?, issue=? WHERE agent=?", (a["state"], since, a["issue"], a["agent"]))
            else:
                con.execute("UPDATE agents SET state=?, since=? WHERE agent=?", (a["state"], since, a["agent"]))
        elif t == "ENQUEUE":
            q = json.loads(con.execute("SELECT queue FROM agents WHERE agent=?", (a["agent"],)).fetchone()[0])
            if a["task"] not in q:
                q.append(a["task"])
            con.execute("UPDATE agents SET queue=? WHERE agent=?", (json.dumps(q), a["agent"]))
        elif t in ("DROP_QUEUED",) or a.get("drop_queue"):
            con.execute("UPDATE agents SET queue='[]' WHERE agent=?", (a.get("agent") or a["drop_queue"],))
        elif t == "CREATE_ISSUE":
            con.execute("INSERT INTO launches(dedupe,agent,at) VALUES(?,?,?)", (a["dedupe"], a["agent"], now.isoformat()))
            payload = dict(a, labels=[pending_label] if pending_label else [])
            con.execute("INSERT INTO outbox(dedupe,payload) VALUES(?,?)", (a["dedupe"], json.dumps(payload)))
            q = json.loads(con.execute("SELECT queue FROM agents WHERE agent=?", (a["agent"],)).fetchone()[0])
            q = [x for x in q if x.get("title") != a["title"]]
            con.execute("UPDATE agents SET queue=? WHERE agent=?", (json.dumps(q), a["agent"]))
        elif t == "ESCALATE_OWNER":
            con.execute("INSERT INTO escalations(reason,at) VALUES(?,?)", (a["reason"], now.isoformat()))
            for ag, stt in (a.get("set_state") or {}).items():
                con.execute("UPDATE agents SET state=?, since=NULL WHERE agent=?", (stt, ag))


def run_outbox(con, send) -> list:
    """Execute PENDING creations AFTER commit. `send(payload)->None` may raise.
    Failures increment attempts; after MAX_ATTEMPTS the row is FAILED (owner escalation)."""
    done = []
    for dedupe, payload, attempts in con.execute("SELECT dedupe,payload,attempts FROM outbox WHERE status='PENDING'").fetchall():
        try:
            send(json.loads(payload))
            con.execute("UPDATE outbox SET status='DONE' WHERE dedupe=?", (dedupe,))
            done.append(dedupe)
        except Exception:
            n = attempts + 1
            con.execute("UPDATE outbox SET attempts=?, status=? WHERE dedupe=?",
                        (n, "FAILED" if n >= MAX_ATTEMPTS else "PENDING", dedupe))
    return done


def process_event(con, event: dict, now: datetime, extra_keys: tuple = ()) -> dict:
    """decide -> persist atomically. Duplicate delivery of the same event is a no-op."""
    dec = rp.decide(event, load_state(con), now)
    key = f"{event.get('id')}:{(event.get('issue') or {}).get('number')}"
    if not any(a["type"] == "MARK_PROCESSED" for a in dec["actions"]):
        # not a relevant event: still persist watchdog actions, without consuming a key
        apply_decision(con, dec, now, None)
        return dec
    dec["actions"] = [a for a in dec["actions"] if a["type"] != "MARK_PROCESSED"]
    if not apply_decision(con, dec, now, key, extra_keys):
        return {"actions": [], "reason": "idempotent: event already processed"}
    return dec


def set_kill_switch(con, on: bool, now: datetime) -> None:
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('kill_switch',?)", (("ON " + now.isoformat()) if on else "OFF",))


def kill_switch_on(con) -> bool:
    r = con.execute("SELECT v FROM meta WHERE k='kill_switch'").fetchone()
    return bool(r) and r[0].startswith("ON")


def rollback_pending(con) -> int:
    """Rollback: cancel every outbox row not yet sent (and its launch ledger entry)."""
    con.execute("BEGIN IMMEDIATE")
    try:
        ids = [r[0] for r in con.execute("SELECT dedupe FROM outbox WHERE status IN ('PENDING','FAILED')")]
        for d in ids:
            con.execute("UPDATE outbox SET status='CANCELLED' WHERE dedupe=?", (d,))
            con.execute("DELETE FROM launches WHERE dedupe=?", (d,))
        con.execute("COMMIT")
        return len(ids)
    except Exception:
        con.execute("ROLLBACK")
        raise


# ----------------------------------------------------------------------------- mission lock (#211)
# One mission (a stable id such as a T-REG task "T-0039" or "issue:212") is held by ONE session at a
# time: an interactive Claude session, a label-triggered routine or a scheduled check, named by the
# caller ("session:<id>", "routine:rugger-03", ...). The holder must prove its start (comment/commit
# id) and renew the lease; an expired lease can be re-claimed a bounded number of times, then the
# mission is BLOCKED and escalated to the owner. A terminal mission is never claimed again.
# NOTE: this is the lock primitive only. It prevents duplicates (#213/#214) only for runners that
# call it; making routines and sessions call it is an owner decision (see docs/ops/RELAY_SINGLE_CIRCUIT.md).

def _aware(now) -> bool:
    return isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None \
        and now.utcoffset().total_seconds() == 0


def _ident_ok(x) -> bool:
    return isinstance(x, str) and 0 < len(x) <= 120 and x.strip() == x


def mission(con, mission_id: str) -> dict | None:
    r = con.execute("SELECT mission,holder,state,attempts,lease_until,start_proof,updated_at FROM missions WHERE mission=?",
                    (mission_id,)).fetchone()
    return None if r is None else dict(zip(("mission", "holder", "state", "attempts", "lease_until", "start_proof", "updated_at"), r))


def _lease(now):
    from datetime import timedelta
    return (now + timedelta(minutes=MISSION_LEASE_MIN)).isoformat()


def claim_mission(con, mission_id, holder, now) -> dict:
    """Atomic claim. -> {"granted": bool, "holder": str|None, "reason": str}."""
    if not (_ident_ok(mission_id) and _ident_ok(holder) and _aware(now)):
        return {"granted": False, "holder": None, "reason": "refused: invalid mission id, holder or naive time"}
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = mission(con, mission_id)
        if cur is None:
            con.execute("INSERT INTO missions(mission,holder,state,attempts,lease_until,updated_at) VALUES(?,?,?,?,?,?)",
                        (mission_id, holder, "CLAIMED", 1, _lease(now), now.isoformat()))
            con.execute("COMMIT")
            return {"granted": True, "holder": holder, "reason": "claimed"}
        if cur["state"] in MISSION_TERMINAL:
            con.execute("ROLLBACK")
            return {"granted": False, "holder": cur["holder"], "reason": f"refused: mission is terminal ({cur['state']})"}
        lease_ok = rp.parse_since(cur["lease_until"])
        if lease_ok is not None and now <= lease_ok:
            con.execute("ROLLBACK")
            return {"granted": False, "holder": cur["holder"], "reason": "refused: held by another session (lease valid)"}
        if cur["attempts"] >= MISSION_MAX_ATTEMPTS:
            con.execute("UPDATE missions SET state='BLOCKED', holder=NULL, lease_until=NULL, updated_at=? WHERE mission=?",
                        (now.isoformat(), mission_id))
            con.execute("INSERT INTO escalations(reason,at) VALUES(?,?)",
                        (f"mission {mission_id}: {cur['attempts']} expired claims, owner decision required", now.isoformat()))
            con.execute("COMMIT")
            return {"granted": False, "holder": None, "reason": "refused: retry budget spent, escalate to owner (mission BLOCKED)"}
        con.execute("UPDATE missions SET holder=?, state='CLAIMED', attempts=attempts+1, lease_until=?, start_proof=NULL, updated_at=? "
                    "WHERE mission=?", (holder, _lease(now), now.isoformat(), mission_id))
        con.execute("COMMIT")
        return {"granted": True, "holder": holder, "reason": f"re-claimed after expired lease of {cur['holder']}"}
    except Exception:
        con.execute("ROLLBACK")
        raise


def _holder_update(con, mission_id, holder, now, sql, params, allowed_states) -> dict:
    if not (_ident_ok(mission_id) and _ident_ok(holder) and _aware(now)):
        return {"ok": False, "reason": "refused: invalid input"}
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = mission(con, mission_id)
        if cur is None or cur["holder"] != holder or cur["state"] not in allowed_states:
            con.execute("ROLLBACK")
            return {"ok": False, "reason": "refused: not the current holder or wrong state"}
        lease = rp.parse_since(cur["lease_until"])
        if lease is None or now > lease:
            con.execute("ROLLBACK")
            return {"ok": False, "reason": "refused: lease expired, claim again"}
        con.execute(sql, params)
        con.execute("COMMIT")
        return {"ok": True, "reason": "ok"}
    except Exception:
        con.execute("ROLLBACK")
        raise


def start_mission(con, mission_id, holder, proof, now) -> dict:
    """Record the start proof (e.g. 'comment 6694201871' or 'commit 6fdd183'). Proof is mandatory."""
    if not _ident_ok(proof):
        return {"ok": False, "reason": "refused: start proof required"}
    return _holder_update(con, mission_id, holder, now,
                          "UPDATE missions SET state='STARTED', start_proof=?, lease_until=?, updated_at=? WHERE mission=?",
                          (proof, _lease(now) if _aware(now) else None, now.isoformat() if _aware(now) else "", mission_id),
                          ("CLAIMED",))


def heartbeat_mission(con, mission_id, holder, now) -> dict:
    return _holder_update(con, mission_id, holder, now,
                          "UPDATE missions SET lease_until=?, updated_at=? WHERE mission=?",
                          (_lease(now) if _aware(now) else None, now.isoformat() if _aware(now) else "", mission_id),
                          ("CLAIMED", "STARTED"))


def finish_mission(con, mission_id, holder, status, now) -> dict:
    if status not in MISSION_TERMINAL:
        return {"ok": False, "reason": "refused: status must be COMPLETED, BLOCKED or CANCELLED"}
    return _holder_update(con, mission_id, holder, now,
                          "UPDATE missions SET state=?, lease_until=NULL, updated_at=? WHERE mission=?",
                          (status, now.isoformat() if _aware(now) else "", mission_id),
                          ("STARTED",))
