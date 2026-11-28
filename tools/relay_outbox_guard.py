"""Crash-safe GitHub issue sender adapter (NOT wired into production).

The lookup must query the authoritative repository by an exact, immutable marker.
A failed/incomplete lookup MUST raise, never be interpreted as 'no match'.
No credentials, network client, or production workflow are configured here.
"""
from __future__ import annotations

import re

MARKER_PREFIX = "<!-- rugger-relay-dedupe:"
MARKER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,119}$")


class ReconciliationError(RuntimeError):
    """Fail closed when exactly-once delivery cannot be established."""

    no_retry = True  # relay_store.run_outbox must NOT retry: the row goes FAILED and the owner is alerted


def marker(dedupe: str) -> str:
    if not isinstance(dedupe, str) or not MARKER_RE.fullmatch(dedupe):
        raise ValueError("invalid immutable dedupe key")
    return f"{MARKER_PREFIX}{dedupe} -->"


def guarded_send(payload: dict, lookup_exact, create_issue) -> object:
    """Reconcile before creation and after ambiguous failures.

    lookup_exact(marker) must return a COMPLETE list of matching issues from the
    target repository; it must raise on API errors, pagination gaps, or uncertainty.
    create_issue(payload) creates the issue with payload['body'] unchanged.
    The caller must use a durable, shared outbox and serialize sends per dedupe.
    """
    dedupe = payload.get("dedupe")
    tag = marker(dedupe)
    matches = lookup_exact(tag)
    if not isinstance(matches, list):
        raise ReconciliationError("lookup did not return a complete list")
    if len(matches) > 1:
        raise ReconciliationError("multiple issues with same dedupe marker")
    if matches:
        return matches[0]
    body = payload.get("body", "")
    if not isinstance(body, str):
        raise ValueError("body must be text")
    enriched = dict(payload, body=body + "\n\n" + tag)
    try:
        created = create_issue(enriched)
    except Exception:
        # Network timeout may mean the issue WAS created. Reconcile before retry.
        try:
            matches = lookup_exact(tag)
        except Exception as exc:  # fail closed: an unreadable remote state must never lead to a retry
            raise ReconciliationError("lookup failed after an ambiguous create; block automatic retry") from exc
        if not isinstance(matches, list) or len(matches) != 1:
            raise ReconciliationError("ambiguous create result; block automatic retry")
        return matches[0]
    if created is None:
        raise ReconciliationError("create returned no proof")
    return created
