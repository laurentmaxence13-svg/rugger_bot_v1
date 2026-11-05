"""Causal, completeness-checked trade timeline of one LaunchLab pool.

Each ``TradeEvent`` carries the curve state immediately before and after the
trade. Chaining ``before == previous.after`` therefore orders trades inside a
slot (RPC signature listings do not expose intra-slot order) and *proves* that
no trade is missing between two consecutive events. Any break is reported as
a gap; downstream research must treat a gapped interval as unknown.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Gap:
    after_key: object       # (signature, event_index) of the last event before the gap, or None
    before_key: object      # first event after the gap
    slot_from: int
    slot_to: int
    reason: str


@dataclass(frozen=True)
class PoolTimeline:
    pool: str
    events: tuple
    gaps: tuple
    rejected: tuple = field(default=())     # (key, reason)

    @property
    def complete(self):
        return not self.gaps and not self.rejected

    def complete_from(self, start_index=0):
        """True when the chain is unbroken from ``events[start_index]`` to the end."""
        # A gap whose ``before_key`` sits at index j breaks the chain between
        # j-1 and j; only breaks strictly after ``start_index`` matter.
        indices = {e.key: i for i, e in enumerate(self.events)}
        return not self.rejected and all(
            indices[g.before_key] <= start_index for g in self.gaps)


def _state(event, which):
    if which == 'before':
        return event.real_base_before, event.real_quote_before
    return event.real_base_after, event.real_quote_after


def build_timeline(pool, events):
    """Order, deduplicate and chain-check every event of ``pool``.

    Events carrying arithmetic violations, or belonging to another pool, are
    rejected rather than used. Within a slot, events are ordered by following
    the reserve chain; if the chain cannot be followed the slot's remaining
    events keep (signature, event_index) order and a gap is recorded.
    """
    rejected, seen, valid = [], set(), []
    for event in events:
        if event.pool != pool:
            rejected.append((event.key, 'other_pool'))
        elif event.key in seen:
            continue
        elif event.violations:
            seen.add(event.key)
            rejected.append((event.key, 'violations:' + ','.join(event.violations)))
        else:
            seen.add(event.key)
            valid.append(event)
    curves = {(e.virtual_base, e.virtual_quote, e.total_base_sell) for e in valid}
    if len(curves) > 1:
        raise ValueError('inconsistent_curve_parameters_for_pool')

    by_slot = {}
    for event in valid:
        by_slot.setdefault(event.slot, []).append(event)
    ordered, gaps, previous = [], [], None
    for slot in sorted(by_slot):
        pending = sorted(by_slot[slot], key=lambda e: e.key)
        while pending:
            pick = None
            if previous is not None:
                tail = _state(previous, 'after')
                matches = [e for e in pending if _state(e, 'before') == tail]
                if len(matches) == 1:
                    pick = matches[0]
            if pick is None:
                # No unique continuation: choose an event that no other pending
                # event leads into (chain head), otherwise the first by key.
                afters = {_state(e, 'after') for e in pending}
                heads = [e for e in pending if _state(e, 'before') not in afters]
                pick = heads[0] if heads else pending[0]
                if previous is None:
                    if pick.real_base_before != 0 or pick.real_quote_before != 0:
                        gaps.append(Gap(None, pick.key, slot, slot, 'history_starts_mid_curve'))
                elif _state(pick, 'before') != _state(previous, 'after'):
                    gaps.append(Gap(previous.key, pick.key, previous.slot, slot,
                                    'reserve_chain_break'))
            pending.remove(pick)
            ordered.append(pick)
            previous = pick
    return PoolTimeline(pool, tuple(ordered), tuple(gaps), tuple(rejected))
