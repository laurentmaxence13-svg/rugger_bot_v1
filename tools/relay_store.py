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
"""
MAX_ATTEMPTS = 3


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


def apply_decision(con, decision: dict, now: datetime, key: str | None = None, extra_keys: tuple = ()) -> bool:
    """Atomically persist a planner decision. Returns False if `key` was already processed."""
    con.execute("BEGIN IMMEDIATE")
    try:
        if key is not None:
            if con.execute("INSERT OR IGNORE INTO processed(key,at) VALUES(?,?)", (key, now.isoformat())).rowcount == 0:
                con.execute("ROLLBACK")
                return False
        for k in extra_keys:  # same transaction: all dedup keys claimed atomically with the effects
            if con.execute("INSERT OR IGNORE INTO processed(key,at) VALUES(?,?)", (k, now.isoformat())).rowcount == 0:
                con.execute("ROLLBACK")
                return False
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
        con.execute("COMMIT")
        return True
    except Exception:
        con.execute("ROLLBACK")
        raise


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
