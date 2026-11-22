"""rtgate 0.2: the 5 remaining tests of the P3 note (T-11 rollback, T-12 getTransaction decoding, T-13 work per event,
T-14 Rugger Wallet labelling, T-15 stale SOL/USD). Fixtures only, no network."""
import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from bot.market import launchlab_events as LE
from bot.market import replay as R
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from paperstream import engine as PS
from paperstream.tests.test_engine import PACK, EnterAt, _timelines
from rtgate import gate as G
from w1aux import dayj
from w1aux.lazy import clear_cache, load_fixtures_lazy

MODEL = R.ExecutionModel(latency_slots=4, fee_rate_estimator='causal_interval')
FIXTURES = Path(__file__).resolve().parent / 'fixtures'
RESEARCH_VIEW = FIXTURES / 'research_view_e3f78d0.py'
RESEARCH_VIEW_SHA256 = 'aade2d5a40972c1ac8294e912d9a36d4af257c2382f5b0d4aa78e0ccca16bf83'   # git blob 5ce35b04, e3f78d0


@pytest.fixture(scope='module')
def busy():
    return max(_timelines(), key=lambda t: len(t.events))


def _gate(t, deliveries, strategy):
    return G.run(t.pool, deliveries, strategy, MODEL, quote_mint=R.WSOL_MINT)


# T-11 ----------------------------------------------------------------------------------------------------------------
def test_t11_a_rolled_back_event_closes_the_pool_once_pushed_and_is_forgotten_before(busy):
    events = list(busy.events)
    reference = asdict(R.replay(busy, EnterAt(2, None, None), MODEL, quote_mint=R.WSOL_MINT))
    pushed = _gate(busy, events[:30] + [('retract', events[10].key)] + events[30:], EnterAt(2, None, None))
    assert pushed['status'] == G.INCOMPLETE and pushed['reasons'] == ['rollback_of_a_pushed_event']
    assert pushed['result'] is None and pushed['flags'] == ['stream_gap_with_open_position']
    # retracted while still buffered (its slot not over), and re-included later: the key is spent, the chain breaks
    k = 30
    same_slot = [i for i, e in enumerate(events) if e.slot == events[k].slot]
    last = same_slot[-1]
    buffered = _gate(busy, events[:last + 1] + [('retract', events[last].key)] + events[last + 1:], EnterAt(2, None, None))
    assert buffered['status'] == G.INCOMPLETE and buffered['reasons'][0].startswith('reserve_chain_break')
    # retracting an event that never arrived is itself a defect of the stream
    unknown = _gate(busy, events[:5] + [('retract', ('nope', 0))] + events[5:], EnterAt(2, None, None))
    assert unknown['status'] == G.INCOMPLETE and unknown['reasons'] == ['rollback_of_an_unknown_event']
    # no retraction at all: the frozen replay
    assert _gate(busy, events, EnterAt(2, None, None))['result'] == reference
    gate = G.FrontGate(busy.pool, EnterAt(2, None, None), MODEL, quote_mint=R.WSOL_MINT, source='HISTORICAL_REPLAY')
    gate.close()
    with pytest.raises(G.GateError, match='retract_after_close'):
        gate.retract(events[0].key)


# T-12 ----------------------------------------------------------------------------------------------------------------
def _archives():
    out = []
    try:
        for _entry, archive in load_fixtures_lazy(PACK)[2]:
            out.append(archive)
    finally:
        clear_cache()
    return out


def test_t12_events_come_from_get_transaction_inner_instructions_never_from_log_lines():
    timelines = {t.pool: t for t in _timelines()}
    checked = 0
    for archive in _archives():
        if archive.pool not in timelines:
            continue
        decoded = {}
        for tx in archive.transactions.values():
            for event in LE.extract_trade_events(tx):
                decoded[event.key] = event
        replayed = {e.key: e for e in timelines[archive.pool].events}
        assert set(replayed) <= set(decoded)
        for key, event in replayed.items():
            assert asdict(decoded[key]) == asdict(event)
            checked += 1
        # the same transactions with their inner instructions removed: the frozen decoder finds NOTHING, even though
        # the log lines (``Program data:`` among them) are still there
        for tx in archive.transactions.values():
            if not LE.extract_trade_events(tx):
                continue
            stripped = json.loads(json.dumps(tx))
            stripped['meta']['innerInstructions'] = []
            assert stripped['meta'].get('logMessages')
            assert LE.extract_trade_events(stripped) == []
    assert checked == sum(len(t.events) for t in timelines.values()) > 100


# T-13 ----------------------------------------------------------------------------------------------------------------
class Counting(R.Strategy):
    def __init__(self):
        self.lengths = []

    def entry(self, history):
        self.lengths.append(len(history))
        return None

    def exit(self, history, position, mark):
        return False


def test_t13_work_per_event_the_gate_is_bounded_by_the_slot_the_engine_passes_the_whole_history(busy):
    events = list(busy.events)
    strategy = Counting()
    out = _gate(busy, events, strategy)
    n = len(events)
    # the audited engine hands the WHOLE history to the strategy at every push: n(n+1)/2 elements in all (quadratic);
    # the frozen MASTER evaluates on it (O-9 of the note; the 0.5.2.1 memo removes the dominant term)
    assert strategy.lengths == list(range(1, n + 1)) and sum(strategy.lengths) == n * (n + 1) // 2
    # the gate compares each pending event of the open slot only: bounded by sum(size^2) over slots, never by n^2
    sizes = {}
    for e in events:
        sizes[e.slot] = sizes.get(e.slot, 0) + 1
    assert n <= out['chain_comparisons'] <= sum(s * (s + 1) // 2 for s in sizes.values())
    assert out['chain_comparisons'] < n * (n + 1) // 2 // 10


# T-14 ----------------------------------------------------------------------------------------------------------------
def _research_view():
    assert hashlib.sha256(RESEARCH_VIEW.read_bytes()).hexdigest() == RESEARCH_VIEW_SHA256
    spec = importlib.util.spec_from_file_location('research_view_e3f78d0', RESEARCH_VIEW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_t14_the_rugger_wallet_never_shows_a_gate_record_as_a_master_trade(busy):
    view = _research_view()
    record = _gate(busy, list(busy.events), EnterAt(2, None, None))
    raw = json.dumps(record, sort_keys=True).encode()
    with pytest.raises(view.BundleRefused, match='bundle_schema_not_supported'):
        view.verify_bundle(raw)
    # even disguised with the replay schema, a record claiming a Master trade, the gate or the ledger is refused
    for flag in ('master_operational_trade', 'counted_in_master_gate', 'admissible_in_paper_ledger',
                 'financial_order_submitted'):
        flags = {f: False for f in view.MUST_BE_FALSE}
        flags.update(category='HISTORICAL_REPLAY', research_evidence_status=view.REQUIRED_EVIDENCE_STATUS)
        flags[flag] = True
        doc = dict(schema=view.REPLAY_SCHEMA, category='HISTORICAL_REPLAY', flags=flags)
        doc['bundle_sha256'] = view.canonical_sha256(doc)
        with pytest.raises(view.BundleRefused, match='bundle_flag_must_be_false:' + flag):
            view.verify_bundle(json.dumps(doc).encode())
    assert view.LABELS == ('HISTORICAL_REPLAY', 'PROSPECTIVE_PAPER', 'SYNTHETIC', 'REAL')
    assert record['label'] == 'HISTORICAL_REPLAY' and record['counts_for_operational_master'] is False


# T-15 ----------------------------------------------------------------------------------------------------------------
def _stale_series(tmp_path):
    fresh = tmp_path / 'fresh.json'
    dayj._selfcheck_series(fresh)
    doc = json.loads(fresh.read_text())
    point = doc['points'][0]
    point['block_time'] -= 3_600
    point['publish_time'] -= 3_600
    stale = tmp_path / 'stale.json'
    stale.write_text(json.dumps(doc))
    return sus.load_series(fresh), sus.load_series(stale)


def _replay(series, *, streaming):
    archives = [a for _e, a in hrr.load_fixtures(PACK)[2]]
    args = (PACK, w1_run.l1_params(), series, w1_run.L1_EXIT, hrr.CreatorHistory.from_archives(archives, 'manifest'))
    if streaming:
        with PS.streaming_engine():
            return hrr.run_replay(*args, placebo_arm=True)
    return hrr.run_replay(*args, placebo_arm=True)


def test_t15_a_stale_sol_usd_point_gives_a_logged_wait_never_a_declared_rate(tmp_path):
    assert w1_run.l1_params().sol_usd is None                                     # no declared rate exists
    fresh, stale = _stale_series(tmp_path)
    for streaming in (False, True):
        ok = _replay(fresh, streaming=streaming)['totals']
        bad = _replay(stale, streaming=streaming)['totals']
        for arm, block in bad.items():
            assert block['decisions'] == ok[arm]['decisions'] > 0
            assert block['blocking_reasons'].get('sol_usd_stale', 0) == block['decisions'], (arm, streaming)
            assert block['entries'] == 0 and block['blocking_reasons'].get('sol_usd_rate_unavailable', 0) == 0
        assert ok[hrr.PLACEBO_ARM]['entries'] >= 1                                  # the fresh series lets one enter
