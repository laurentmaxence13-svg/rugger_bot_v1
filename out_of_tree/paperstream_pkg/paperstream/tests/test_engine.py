"""paperstream: streaming = frozen batch replay (byte for byte), no lookahead, offline, labels, thresholds, journal."""
import hashlib
import json
import socket
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

import bot
from bot.market import replay as R
from bot.p4 import historical_research_replay as hrr
from paperstream import engine as E
from w1aux.lazy import clear_cache, load_fixtures_lazy

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


def _timelines():
    out = []
    try:
        for _e, archive in load_fixtures_lazy(PACK)[2]:
            summary, timeline = hrr.summarize(archive) if hasattr(hrr, 'summarize') else (None, None)
            from bot.market.collector import summarize
            summary, timeline = summarize(archive)
            try:
                timeline, _m = hrr.usable_timeline(archive, summary, timeline)
            except hrr.PoolExcluded:
                continue
            out.append(timeline)
    finally:
        clear_cache()
    return out


class EnterAt(R.Strategy):
    """Test strategy: enter at the n-th event; exit once n_hold events have passed, or never."""

    def __init__(self, n, n_hold=None, clock_s=None):
        self.n, self.n_hold, self.clock_s, self.seen = n, n_hold, clock_s, []

    def entry(self, history):
        self.seen.append(len(history))
        return 100_000_000 if len(history) == self.n else None

    def exit(self, history, position, mark):
        self.seen.append(len(history))
        return self.n_hold is not None and len(history) - 1 - position.entry_index >= self.n_hold

    def exit_deadline(self, position):
        return None if self.clock_s is None else position.entry_time + self.clock_s


def _same(a, b):
    return asdict(a) == asdict(b)


@pytest.mark.parametrize('n,n_hold,clock_s,latency', [(1, 2, None, 4), (3, 1, None, 0), (2, None, None, 4),
                                                      (2, None, 5, 4), (5, 50, None, 2), (10_000, None, None, 4)])
def test_stream_trade_equals_the_frozen_replay(n, n_hold, clock_s, latency):
    model = R.ExecutionModel(latency_slots=latency, fee_rate_estimator='causal_interval',
                             clock_exit_latency_s=None if clock_s is None else 1)
    for timeline in _timelines():
        batch = R.replay(timeline, EnterAt(n, n_hold, clock_s), model, quote_mint=R.WSOL_MINT)
        streamed = E.stream_replay(timeline, EnterAt(n, n_hold, clock_s), model, quote_mint=R.WSOL_MINT)
        assert _same(batch, streamed), (n, n_hold, clock_s, latency)


def test_the_strategy_never_sees_beyond_the_pushed_events():
    timeline = _timelines()[0]
    model = R.ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')
    strategy = EnterAt(2, 3)
    trade = E.StreamTrade(timeline.pool, strategy, model, quote_mint=R.WSOL_MINT)
    for i, event in enumerate(timeline.events):
        trade.push(event)
        assert max(strategy.seen) <= i + 1                         # at most the events pushed so far
        if trade.phase == 'stopped':
            break
    trade.finish()
    with pytest.raises(E.StreamError, match='event_after_the_end'):
        trade.push(timeline.events[-1])


def test_an_event_from_the_past_is_refused():
    timeline = _timelines()[0]
    trade = E.StreamTrade(timeline.pool, EnterAt(10_000), R.ExecutionModel(), quote_mint=R.WSOL_MINT)
    late = timeline.events[-1]
    trade.push(late)
    early = replace(timeline.events[0], slot=late.slot - 1) if hasattr(timeline.events[0], '__dataclass_fields__') else None
    if early is None:
        pytest.skip('events are not dataclasses')
    with pytest.raises(E.StreamError, match='event_out_of_time_order'):
        trade.push(early)


def test_streaming_records_are_byte_identical_to_the_frozen_batch_records():
    batch, excluded_b, _ = E.records(PACK, SHA, streaming=False)
    streamed, excluded_s, journals = E.records(PACK, SHA, streaming=True)
    assert batch and E._canonical(batch) == E._canonical(streamed) and excluded_b == excluded_s
    assert hrr.replay is R.replay                                   # the frozen engine is restored
    assert journals and all(j['arm'] in ('master', hrr.PLACEBO_ARM) or j['arm'] in hrr.ARMS for j in journals)


def test_cli_reference_then_anchored_run(tmp_path, capsys):
    assert E.main(['reference', '--pools', str(PACK), '--manifest-sha256', SHA, '--out', str(tmp_path / 'ref')]) == 0
    ref_sha = capsys.readouterr().out.strip()
    ref = tmp_path / 'ref' / 'REFERENCE.json'
    assert ref_sha == hashlib.sha256(ref.read_bytes()).hexdigest()
    with pytest.raises(E.StreamError, match='reference_is_not_the_anchored_one'):
        E.main(['run', '--pools', str(PACK), '--manifest-sha256', SHA, '--reference', str(ref),
                '--reference-sha256', '0' * 64, '--out', str(tmp_path / 'x')])
    with pytest.raises(E.StreamError, match='manifest_is_not_the_anchored_one'):
        E.main(['reference', '--pools', str(PACK), '--manifest-sha256', '0' * 64, '--out', str(tmp_path / 'y')])
    assert E.main(['run', '--pools', str(PACK), '--manifest-sha256', SHA, '--reference', str(ref),
                   '--reference-sha256', ref_sha, '--out', str(tmp_path / 'run')]) == 0
    text = (tmp_path / 'run' / 'PAPERSTREAM.json').read_text()
    doc = json.loads(text)
    assert doc['identical_to_reference'] is True and doc['category'] == 'HISTORICAL_REPLAY'
    assert doc['network'] is False and doc['trials_added'] == 0
    for word in ('genuine', 'GENUINE', 'MASTER_CYCLE', 'operational_trade": true', 'LIVE'):
        assert word not in text, word
    with pytest.raises(E.StreamError, match='output_exists'):
        E.main(['reference', '--pools', str(PACK), '--manifest-sha256', SHA, '--out', str(tmp_path / 'ref')])


def test_thresholds_are_the_protected_ones_and_never_counted():
    t = E.thresholds()
    assert (t['min_qualified_cycles'], t['min_creator_groups']) == (50, 20)
    assert t['these_cycles_count_toward_them'] is False and t['operational_master_entry'] is False
    from bot.master_decision import POLICY, MasterDecisionOrchestrator
    with pytest.raises(ValueError):
        MasterDecisionOrchestrator(dict(POLICY, min_qualified_cycles=49))   # the frozen code refuses a lower gate


def test_journal_reconciles_and_a_tampered_journal_is_refused():
    recs, _x, journals = E.records(PACK, SHA, streaming=True)
    checked = sum(E.reconcile(r, journals) for r in recs)
    closed = sum(1 for r in recs for row in r['arms'].values() if row.get('pnl_lamports') is not None)
    assert checked == closed
    if closed:
        bad = json.loads(json.dumps(journals))
        for j in bad:
            for e in j['events']:
                if e['kind'] == 'SELL':
                    e['received'] += 1
        with pytest.raises(E.StreamError, match='journal_does_not_reconcile'):
            for r in recs:
                E.reconcile(r, bad)


def test_offline_no_sending_or_signing_module_is_imported():
    forbidden = ('bot.live.engine', 'bot.live.route', 'bot.live.route_dispatch', 'bot.live.cleanup', 'bot.live.safety',
                 'bot.live.journal', 'bot.live.cpmm_swap', 'bot.live.cpmm_exit', 'bot.live.helius_readonly_rpc')
    E.records(PACK, SHA, streaming=True)
    assert not [m for m in forbidden if m in sys.modules]
    import inspect
    code = inspect.getsource(E).split('"""', 2)[2]
    for word in ('requests', 'urllib', 'websocket', 'http', 'sign', 'keypair', 'private', 'send_transaction'):
        assert word not in code, word


@pytest.mark.parametrize('enter_at', [1, 3, 8])
def test_forced_master_cycles_are_identical_and_reconcile(monkeypatch, enter_at):
    """The frozen MASTER never enters on the 3 frozen pools (WAIT): force the observer to say ENTER, the SAME way for
    the batch and the streaming runs, so that the frozen ResearchArm exits (TP 7 / SL 5, clock 30 s), the trade rows,
    the clock-exit rows and the journal reconciliation are exercised on real timelines."""
    def forced(self, history):
        index = len(history) - 1
        go = index >= enter_at
        decision = dict(intent='ENTER' if go else 'WAIT', blocking_reasons=[] if go else ['forced_test_wait'])
        return dict(shared=dict(index=index, forced_test=True),
                    decisions={name: dict(decision) for name in hrr.ARMS},
                    exit_conditions=dict(tp_pct=7, sl_pct=5) if go else None, scorer_exit_plan={})
    monkeypatch.setattr(hrr._PoolObserver, 'observe', forced)
    batch, _x, _ = E.records(PACK, SHA, streaming=False)
    streamed, _y, journals = E.records(PACK, SHA, streaming=True)
    outcomes = [row['outcome'] for r in batch for row in r['arms'].values()]
    assert any(o in ('closed', 'migrated_unpriced', 'open_at_end') for o in outcomes), outcomes
    assert E._canonical(batch) == E._canonical(streamed)
    closed = sum(1 for r in streamed for row in r['arms'].values() if row.get('pnl_lamports') is not None)
    assert sum(E.reconcile(r, journals) for r in streamed) == closed
    kinds = [e['kind'] for j in journals for e in j['events']]
    assert 'BUY' in kinds and ('SELL' in kinds or 'MARK_AT_END' in kinds)
    bad = json.loads(json.dumps(journals))
    for j in bad:
        for e in j['events']:
            if e['kind'] == 'SELL':
                e['received'] += 1
    with pytest.raises(E.StreamError, match='journal_does_not_reconcile'):
        for r in streamed:
            E.reconcile(r, bad)
