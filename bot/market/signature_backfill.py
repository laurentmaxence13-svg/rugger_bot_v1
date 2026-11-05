"""Offline planner for paginated ``getSignaturesForAddress`` backfill.

No network: the caller injects ``fetch(address, before, until, limit)`` returning a
newest-first list of ``{'signature','slot','err',...}``. Properties:

* page size <= 1000 (RPC max); ``max_pages`` cap; resumable cursor (``before``).
* Gap detection: cap reached on a full page before touching ``until`` => ``complete=False``
  and ``gap`` is recorded; never reported as complete.
* Idempotent: signatures keyed in ``seen``; replaying pages adds nothing.
* Causality: output ordered by (slot, signature); within-slot order is NOT known from this
  RPC, so slots with several signatures are listed in ``ambiguous_slots``.
* Failed transactions (err not None) are kept apart; a non-monotonic page (slot increasing
  while paging backwards) aborts fail-closed.
"""
from dataclasses import dataclass, field

PAGE_MAX = 1000


class BackfillError(ValueError):
    pass


@dataclass
class BackfillState:
    address: str
    before: str = None          # cursor: oldest signature fetched so far
    until: str = None
    pages: int = 0
    complete: bool = False
    gap: str = ''
    seen: dict = field(default_factory=dict)   # signature -> slot
    failed: dict = field(default_factory=dict)
    last_slot: int = None

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

    def ordered(self):
        return sorted(self.seen.items(), key=lambda kv: (kv[1], kv[0]))

    def ambiguous_slots(self):
        counts = {}
        for s in self.seen.values():
            counts[s] = counts.get(s, 0) + 1
        return sorted(s for s, n in counts.items() if n > 1)


def run_backfill(state, fetch, page_size=PAGE_MAX, max_pages=10):
    if not 1 <= page_size <= PAGE_MAX or max_pages < 1:
        raise BackfillError('invalid_limits')
    if state.complete:
        return state
    for _ in range(max_pages):
        page = fetch(state.address, state.before, state.until, page_size)
        state.pages += 1
        if not page:
            state.complete, state.gap = True, ''
            return state
        for row in page:
            slot = row['slot']
            if state.last_slot is not None and slot > state.last_slot:
                raise BackfillError('non_monotonic_slot')
            state.last_slot = slot
            (state.failed if row.get('err') is not None else state.seen)[row['signature']] = slot
        state.before = page[-1]['signature']
        if len(page) < page_size:
            state.complete, state.gap = True, ''
            return state
    state.gap = 'page_cap_reached_before_until'   # full pages up to the cap: more history may remain
    return state
