"""rtgate 0.1 -- a fail-shut FRONT GATE between a live-like delivery of LaunchLab events and the audited streaming engine
(paperstream 0.4 ``StreamTrade``, imported unchanged). Task P3 of docs/ops/ETAT_RUGGER_MASTER.md (62c4525): obstacles
to a real-time streaming PAPER BUY/SELL, tested OFFLINE. HISTORICAL_REPLAY only: the only accepted source is a replay
of recorded events; a live source is refused (not wired, not authorized). Nothing is sent, signed or read from the
network.

WHY. The batch replay proves that no trade is missing: ``pool_timeline.build_timeline`` chains every event
(state before == state after of the previous one) and orders a slot by that chain. ``StreamTrade`` only checks time
order. A live delivery (websocket notifications, reconnects, retries) can DROP, DUPLICATE or REORDER events inside a
slot; ``StreamTrade`` would then decide and value on a wrong curve WITHOUT any error (shown by the tests). The gate puts
the batch proof back in front of the stream:
* duplicates (same (signature, event_index)) are dropped and counted (a reconnect re-delivers);
* events of the current slot are BUFFERED until an event of a later slot (or ``close()``) shows the slot is over, then
  ordered by the reserve chain exactly as ``build_timeline`` does; an ambiguous or broken chain is a GAP;
* the first event must start the curve (reserves 0 / 0): otherwise the history is incomplete (the Master's features and
  the causal fee rate need the pool from its launch);
* an event older than the slot already delivered is LATE: refused;
* a declared reconnect window (``declare_gap``) is healed only if the next event chains exactly onto the last one;
* any gap, late event, other pool or event with violations makes the pool INCOMPLETE: nothing more is pushed, an open
  position is flagged ``stream_gap_with_open_position`` and the record is NOT creditable (fail shut, never backfilled).
Cost of the buffering (declared): a decision on slot s is taken once slot s is known to be over; live, this needs a
slot-completion signal (an obstacle listed in the P3 note).
"""
import hashlib
from dataclasses import asdict
from pathlib import Path

from paperstream import engine as PS

SCHEMA = 'rtgate-v0.1'
SOURCES = ('HISTORICAL_REPLAY',)
COMPLETE, INCOMPLETE = 'COMPLETE', 'INCOMPLETE'


PAPERSTREAM_ENGINE_SHA256 = 'e86f66b009444c0ed97af11ae89a1e965e9437674a17f5f1c3aa0027bddc9f4a'   # paperstream 0.4, audited


class GateError(RuntimeError):
    pass


def frozen_check():
    found = hashlib.sha256(Path(PS.__file__).read_bytes()).hexdigest()
    if found != PAPERSTREAM_ENGINE_SHA256:
        raise GateError('paperstream_engine_is_not_the_audited_0_4')
    return found


def _before(e):
    return e.real_base_before, e.real_quote_before


def _after(e):
    return e.real_base_after, e.real_quote_after


class FrontGate:
    def __init__(self, pool, strategy, model, *, quote_mint, source):
        if source not in SOURCES:
            raise GateError('source_not_allowed:%s' % source)
        frozen_check()
        self.pool, self.source = pool, source
        self.trade = PS.StreamTrade(pool, strategy, model, quote_mint=quote_mint)
        self.seen, self.buffer, self.slot = set(), [], None
        self.last, self.delivered_slot = None, None
        self.status, self.reasons, self.duplicates = COMPLETE, [], 0
        self.declared_gap, self.closed = None, False

    # -- delivery ------------------------------------------------------------------------------------------------
    def deliver(self, event):
        if self.closed:
            raise GateError('delivery_after_close')
        if self.status == INCOMPLETE:
            return
        if event.key in self.seen:
            self.duplicates += 1
            return
        self.seen.add(event.key)
        if event.pool != self.pool:
            return self._fail('other_pool')
        if event.violations:
            return self._fail('event_with_violations')
        if self.delivered_slot is not None and event.slot <= self.delivered_slot:
            return self._fail('late_event:%d<=%d' % (event.slot, self.delivered_slot))
        if self.slot is not None and event.slot < self.slot:
            return self._fail('late_event:%d<%d' % (event.slot, self.slot))
        if self.slot is not None and event.slot > self.slot:
            self._flush()
            if self.status == INCOMPLETE:
                return
        self.slot = event.slot
        self.buffer.append(event)

    def declare_gap(self, slot_from, slot_to):
        """The observer lost its connection between these slots: unknown unless the next event chains exactly."""
        if self.status == COMPLETE:
            self._flush()
            self.declared_gap = (slot_from, slot_to)

    def close(self):
        if not self.closed:
            if self.status == COMPLETE:
                self._flush()
            self.closed = True
        return self.record()

    # -- slot ordering by the reserve chain (build_timeline's rule, strict) ----------------------------------------
    def _flush(self):
        pending = sorted(self.buffer, key=lambda e: e.key)
        self.buffer = []
        while pending and self.status == COMPLETE:
            if self.last is None:
                heads = [e for e in pending if _before(e) == (0, 0)]
                if len(heads) != 1:
                    return self._fail('history_starts_mid_curve' if not heads else 'ambiguous_curve_start')
                pick = heads[0]
            else:
                matches = [e for e in pending if _before(e) == _after(self.last)]
                if len(matches) != 1:
                    return self._fail(('reserve_chain_break' if not matches else 'ambiguous_chain')
                                      + ':slot:%d' % pending[0].slot)
                pick = matches[0]
            if self.declared_gap is not None:
                self.declared_gap = None                   # healed: the event chains exactly onto the last one
            pending.remove(pick)
            self._push(pick)
        if self.declared_gap is not None and self.status == COMPLETE and self.closed:
            self._fail('declared_gap_not_healed')

    def _push(self, event):
        if self.trade.phase != 'stopped':
            self.trade.push(event)
        self.last, self.delivered_slot = event, event.slot

    def _fail(self, reason):
        self.status = INCOMPLETE
        self.reasons.append(reason)
        self.buffer = []
        return None

    # -- record ---------------------------------------------------------------------------------------------------
    def record(self):
        if self.declared_gap is not None and self.status == COMPLETE and self.closed:
            self._fail('declared_gap_not_healed')
        flags = []
        result = None
        if self.status == COMPLETE and self.closed:
            result = asdict(self.trade.finish())
        elif self.trade.phase in ('landing', 'holding'):
            flags.append('stream_gap_with_open_position')
        return dict(schema=SCHEMA, pool=self.pool, source=self.source, label='HISTORICAL_REPLAY', status=self.status,
                    reasons=list(self.reasons), duplicates_dropped=self.duplicates, flags=flags, result=result,
                    journal=list(self.trade.journal), creditable=False, counts_for_operational_master=False)


def run(pool, deliveries, strategy, model, *, quote_mint, source='HISTORICAL_REPLAY'):
    """``deliveries``: events, or ('gap', slot_from, slot_to) markers, in the order they arrive."""
    gate = FrontGate(pool, strategy, model, quote_mint=quote_mint, source=source)
    for item in deliveries:
        if type(item) is tuple and item and item[0] == 'gap':
            gate.declare_gap(item[1], item[2])
        else:
            gate.deliver(item)
    return gate.close()
