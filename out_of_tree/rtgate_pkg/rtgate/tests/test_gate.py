"""rtgate: live-like delivery faults on the public fixture pools. Without the gate the audited StreamTrade decides on a
wrong curve WITHOUT error; with the gate the same faults are refused or the pool is marked INCOMPLETE (fail shut)."""
from collections import Counter
from dataclasses import asdict, replace

import pytest

from bot.market import replay as R
from paperstream import engine as PS
from paperstream.tests.test_engine import EnterAt, _timelines
from rtgate import gate as G

MODEL = R.ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')


@pytest.fixture(scope='module')
def timelines():
    return _timelines()


@pytest.fixture(scope='module')
def busy(timelines):
    """The fixture pool with several events in one slot (24 such slots, up to 10 events)."""
    return max(timelines, key=lambda t: len(t.events))


def _reference(t, strategy):
    return asdict(R.replay(t, strategy, MODEL, quote_mint=R.WSOL_MINT))


def _gate(t, deliveries, strategy, **kw):
    return G.run(t.pool, deliveries, strategy, MODEL, quote_mint=R.WSOL_MINT, **kw)


def _raw(t, deliveries, strategy):
    trade = PS.StreamTrade(t.pool, strategy, MODEL, quote_mint=R.WSOL_MINT)
    for e in deliveries:
        if trade.phase == 'stopped':
            break
        trade.push(e)
    return asdict(trade.finish())


def _reversed_inside_slots(events):
    out, slot = [], []
    for e in events:
        if slot and e.slot != slot[-1].slot:
            out += slot[::-1]
            slot = []
        slot.append(e)
    return out + slot[::-1]


STRATEGIES = [(1, 2, None), (2, None, None), (3, 1, None), (5, 50, None), (10_000, None, None)]


@pytest.mark.parametrize('n,n_hold,clock', STRATEGIES)
def test_an_ordered_delivery_gives_exactly_the_frozen_replay(timelines, n, n_hold, clock):
    for t in timelines:
        out = _gate(t, list(t.events), EnterAt(n, n_hold, clock))
        assert out['status'] == G.COMPLETE and out['reasons'] == []
        assert out['result'] == _reference(t, EnterAt(n, n_hold, clock))
        assert out['label'] == 'HISTORICAL_REPLAY' and out['creditable'] is False
        assert out['counts_for_operational_master'] is False


@pytest.mark.parametrize('n,n_hold,clock', STRATEGIES)
def test_reordered_slots_and_duplicates_are_repaired_by_the_reserve_chain(busy, n, n_hold, clock):
    events = _reversed_inside_slots(list(busy.events))
    assert events != list(busy.events)
    noisy = []
    for i, e in enumerate(events):
        noisy.append(e)
        if i % 7 == 3:
            noisy.append(e)                                                     # a reconnect re-delivers
    out = _gate(busy, noisy, EnterAt(n, n_hold, clock))
    assert out['status'] == G.COMPLETE and out['duplicates_dropped'] == sum(1 for i in range(len(events)) if i % 7 == 3)
    assert out['result'] == _reference(busy, EnterAt(n, n_hold, clock))


def test_without_the_gate_the_same_faults_change_the_result_silently(busy):
    reference = _reference(busy, EnterAt(2, None, None))
    assert reference['outcome'] != 'no_entry'
    events = list(busy.events)
    dropped = events[:50] + events[51:]
    duplicated = events[:50] + [events[50]] + events[50:]
    reordered = _reversed_inside_slots(events)
    for faulty in (dropped, duplicated, reordered):
        raw = _raw(busy, faulty, EnterAt(2, None, None))                       # no error raised by StreamTrade
        assert raw != reference
    # the gate on the same three deliveries: two refused, the reordering repaired
    assert _gate(busy, dropped, EnterAt(2, None, None))['status'] == G.INCOMPLETE
    assert _gate(busy, duplicated, EnterAt(2, None, None))['result'] == reference
    assert _gate(busy, reordered, EnterAt(2, None, None))['result'] == reference


def test_a_missing_event_marks_the_pool_incomplete_and_flags_the_open_position(busy):
    events = list(busy.events)
    out = _gate(busy, events[:60] + events[61:], EnterAt(2, None, None))
    assert out['status'] == G.INCOMPLETE and out['reasons'][0].startswith('reserve_chain_break')
    assert out['result'] is None and out['flags'] == ['stream_gap_with_open_position']
    assert [j['kind'] for j in out['journal']][:2] == ['DECISION', 'BUY']
    # a missing event before any entry: incomplete, no position to flag
    late_entry = _gate(busy, events[:5] + events[6:], EnterAt(10_000, None, None))
    assert late_entry['status'] == G.INCOMPLETE and late_entry['flags'] == []


def test_the_history_must_start_at_the_launch(busy):
    out = _gate(busy, list(busy.events)[1:], EnterAt(2, None, None))
    assert out['status'] == G.INCOMPLETE and out['reasons'] == ['history_starts_mid_curve']


def test_a_late_event_is_refused(busy):
    events = list(busy.events)
    slots = sorted(Counter(e.slot for e in events))
    k = next(i for i, e in enumerate(events) if e.slot == slots[3])
    late = events[:k] + events[k + 1:k + 8] + [events[k]] + events[k + 8:]
    out = _gate(busy, late, EnterAt(2, None, None))
    assert out['status'] == G.INCOMPLETE
    assert any(r.startswith('late_event') or r.startswith('reserve_chain_break') for r in out['reasons'])
    # strictly older than what was delivered: always a late event
    old = events[:40] + [replace(events[0], signature='x')]                    # a new key, but an old slot
    out = _gate(busy, old, EnterAt(2, None, None))
    assert out['status'] == G.INCOMPLETE and out['reasons'][0].startswith('late_event')


def test_a_declared_reconnect_is_healed_only_by_an_exact_chain(busy):
    events = list(busy.events)
    slot_gap = ('gap', events[30].slot, events[31].slot)
    healed = _gate(busy, events[:31] + [slot_gap] + events[31:], EnterAt(2, None, None))
    assert healed['status'] == G.COMPLETE and healed['result'] == _reference(busy, EnterAt(2, None, None))
    lost = _gate(busy, events[:31] + [slot_gap] + events[33:], EnterAt(2, None, None))
    assert lost['status'] == G.INCOMPLETE
    at_end = _gate(busy, events + [('gap', events[-1].slot, events[-1].slot + 100)], EnterAt(2, None, None))
    assert at_end['status'] == G.INCOMPLETE and at_end['reasons'] == ['declared_gap_not_healed']


def test_foreign_or_broken_events_and_the_source_guard(busy):
    events = list(busy.events)
    other = _gate(busy, events[:10] + [replace(events[10], pool='another')] + events[11:], EnterAt(2, None, None))
    assert other['status'] == G.INCOMPLETE and other['reasons'] == ['other_pool']
    broken = _gate(busy, events[:10] + [replace(events[10], violations=('fee_mismatch',))] + events[11:],
                   EnterAt(2, None, None))
    assert broken['status'] == G.INCOMPLETE and broken['reasons'] == ['event_with_violations']
    for source in ('LIVE_PAPER', 'LIVE', 'MASTER', None):
        with pytest.raises(G.GateError, match='source_not_allowed'):
            _gate(busy, events, EnterAt(2, None, None), source=source)
    gate = G.FrontGate(busy.pool, EnterAt(2, None, None), MODEL, quote_mint=R.WSOL_MINT, source='HISTORICAL_REPLAY')
    gate.close()
    with pytest.raises(G.GateError, match='delivery_after_close'):
        gate.deliver(events[0])


def test_the_engine_behind_the_gate_is_the_audited_streamtrade():
    assert G.PS.StreamTrade is PS.StreamTrade
    assert G.frozen_check() == G.PAPERSTREAM_ENGINE_SHA256


def test_a_slot_is_pushed_as_soon_as_a_later_slot_arrives(busy):
    events = list(busy.events)
    gate = G.FrontGate(busy.pool, EnterAt(10_000, None, None), MODEL, quote_mint=R.WSOL_MINT, source='HISTORICAL_REPLAY')
    first_multi = next(e.slot for e in events if sum(x.slot == e.slot for x in events) > 1)
    k = max(i for i, e in enumerate(events) if e.slot == first_multi) + 1      # first event of the next slot
    for e in events[:k]:
        gate.deliver(e)
    assert len(gate.trade.events) < k                                         # the open slot is still buffered
    gate.deliver(events[k])
    assert len(gate.trade.events) == k                                        # the finished slot was pushed
    assert gate.close()['status'] == G.COMPLETE


def test_each_late_rule_alone(busy):
    events = list(busy.events)
    multi = [s for s, c in sorted(Counter(e.slot for e in events).items()) if c > 1]
    # same slot as the one just flushed by a declared reconnect: refused even though it is not older than the buffer
    s = multi[1]
    idx = [i for i, e in enumerate(events) if e.slot == s]
    head = events[:idx[0] + 1]
    out = _gate(busy, head + [('gap', s, s)] + events[idx[0] + 1:], EnterAt(10_000, None, None))
    assert out['status'] == G.INCOMPLETE and out['reasons'][0] == 'late_event:%d<=%d' % (s, s)
    # a slot between the last flushed one and the buffered one: refused (no cross-slot repair)
    slots = sorted({e.slot for e in events})
    s0, s1, s2 = slots[10], slots[11], slots[12]
    upto = [e for e in events if e.slot <= s0]
    mid = [e for e in events if e.slot == s1]
    nxt = [e for e in events if e.slot == s2]
    rest = [e for e in events if e.slot > s2]
    out = _gate(busy, upto + nxt[:1] + mid + nxt[1:] + rest, EnterAt(10_000, None, None))
    assert out['status'] == G.INCOMPLETE and out['reasons'][0] == 'late_event:%d<%d' % (s1, s2)


def test_nothing_is_counted_or_pushed_after_a_failure(busy):
    events = list(busy.events)
    gate = G.FrontGate(busy.pool, EnterAt(2, None, None), MODEL, quote_mint=R.WSOL_MINT, source='HISTORICAL_REPLAY')
    for e in events[:20]:
        gate.deliver(e)
    gate.deliver(replace(events[20], pool='another'))
    pushed = len(gate.trade.events)
    for e in events[:30] + [replace(events[25], pool='again')] + events[21:]:
        gate.deliver(e)
    out = gate.close()
    assert out['reasons'] == ['other_pool'] and out['duplicates_dropped'] == 0 and len(gate.trade.events) == pushed


def test_a_modified_engine_is_refused(monkeypatch, busy):
    monkeypatch.setattr(G, 'PAPERSTREAM_ENGINE_SHA256', '0' * 64)
    with pytest.raises(G.GateError, match='paperstream_engine_is_not_the_audited_0_4'):
        G.frozen_check()
    with pytest.raises(G.GateError, match='paperstream_engine_is_not_the_audited_0_4'):
        _gate(busy, list(busy.events), EnterAt(2, None, None))
