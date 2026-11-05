"""Parse a GitHub `issues` webhook payload into the planner's event shape.
Pure: no network, no I/O. Labels are objects [{"name": ...}] in real payloads."""
from __future__ import annotations

from tools.relay_planner import label_names


def parse_issues_payload(payload: dict, last_comment: str = "", delivery_id: str = "") -> dict | None:
    """Return a planner event, or None if the payload is malformed (fail-closed)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("issue"), dict):
        return None
    issue = payload["issue"]
    if not isinstance(issue.get("number"), int) or not isinstance(payload.get("action"), str):
        return None
    ev_id = delivery_id or ""
    if not ev_id:
        return None  # no stable delivery id => cannot deduplicate => refuse
    lab = payload.get("label")
    return {
        "id": ev_id,
        "action": payload["action"],
        "label": (lab.get("name") if isinstance(lab, dict) else lab),
        "issue": {"number": issue["number"], "state": issue.get("state"),
                  "labels": label_names(issue.get("labels")), "last_comment": last_comment or ""},
    }
