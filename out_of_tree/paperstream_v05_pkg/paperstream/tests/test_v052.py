"""paperstream 0.5.2 draft: as_of and _quote memoized; byte identity with a W1-size SOL/USD series (the 0.5/0.5.1
fixture benchmark used a ONE-point series, which hid the dominant term)."""
import hashlib
import json
import socket
from pathlib import Path

import pytest

import bot
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus
from paperstream import bigseries
from paperstream import engine as E
from paperstream import fast as F

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


def _series(tmp_path, n):
    path = bigseries.write(tmp_path / f'series_{n}.json', n)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen(series_path):
    return hrr.run_replay(PACK, w1_run.l1_params(), sus.load_series(series_path), w1_run.L1_EXIT,
                          hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(PACK)[2]], 'manifest'),
                          placebo_arm=True)


def _same(a, b):
    return a['bundle_sha256'] == b['bundle_sha256'] and E._canonical_strict(a) == E._canonical_strict(b)


def test_the_big_series_is_valid_and_used():
    import tempfile
    d = Path(tempfile.mkdtemp())
    s = sus.load_series(bigseries.write(d / 's.json', 300))
    assert s.label == 'COLLECTED' and len(s.points) == 300 and s.max_confidence_ppm == 1_000
    assert bigseries.W1_POINTS == 21_937
    with pytest.raises(ValueError):
        bigseries.write(d / 'x.json', 0)


@pytest.mark.parametrize('workers', [1, 2])
def test_byte_identity_with_a_realistic_series(tmp_path, workers):
    series = _series(tmp_path, 2_000)
    frozen = _frozen(series[0])
    assert frozen['totals']['master']['decisions'] > 0
    assert frozen['totals']['master']['blocking_reasons'].get('sol_usd_rate_unavailable', 0) == 0
    batch, _ = E.records(PACK, SHA, *series, streaming=False, workers=workers, fast_analyser=True)
    stream, journals = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'j', workers=workers,
                                 fast_analyser=True)
    slow, slow_j = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'k', workers=workers)
    assert _same(frozen, batch) and _same(frozen, stream) and _same(frozen, slow)
    assert E._canonical(journals) == E._canonical(slow_j)


def test_byte_identity_at_w1_size_and_the_gain(tmp_path):
    """W1 size (21 937 points): identity, and the measured ratio is published (no promise)."""
    import time
    series = _series(tmp_path, bigseries.W1_POINTS)
    t = time.perf_counter()
    frozen = _frozen(series[0])
    slow_s = time.perf_counter() - t
    t = time.perf_counter()
    fast_b, _ = E.records(PACK, SHA, *series, streaming=False, fast_analyser=True)
    fast_s = time.perf_counter() - t
    assert _same(frozen, fast_b)
    print(json.dumps(dict(points=bigseries.W1_POINTS, frozen_s=round(slow_s, 1), fast_s=round(fast_s, 1))))
    assert fast_s < slow_s                                                # direction only, no threshold promised


def test_verify_mode_with_the_realistic_series(tmp_path):
    series = _series(tmp_path, 1_000)
    before = F.STATS['hits']
    bundle, _j = E.records(PACK, SHA, *series, streaming=True, journal_dir=tmp_path / 'j', fast_analyser=True,
                           _verify_fast=True)
    assert F.STATS['hits'] > before and _same(bundle, _frozen(series[0]))


def test_as_of_memo_returns_the_series_own_point_and_restores(tmp_path):
    s = sus.load_series(bigseries.write(tmp_path / 's.json', 50))
    original_as_of, original_quote = sus.SolUsdSeries.as_of, hrr._PoolObserver._quote
    last = s.points[-1]
    args = dict(slot=last['slot'] + 10, transaction_index=0, decision_ms=(last['block_time'] + 5) * 1000)
    expected = s.as_of(**args)
    with F.memoized(verify=True):
        first, second = s.as_of(**args), s.as_of(**args)
        assert first == second == expected and first[0] is last and second[0] is last      # the same dict object
        refused = s.as_of(slot=1, transaction_index=0, decision_ms=1000)
        assert refused == (None, None, 'sol_usd_rate_unavailable')
        assert sus.SolUsdSeries.as_of is not original_as_of and hrr._PoolObserver._quote is not original_quote
        stale_args = dict(args, decision_ms=args['decision_ms'] + 10 * 120_000)        # same position, later decision
        stale = s.as_of(**stale_args)
        assert stale == original_as_of(s, **stale_args) and stale[2] == 'sol_usd_stale' and stale != first
    assert sus.SolUsdSeries.as_of is original_as_of and hrr._PoolObserver._quote is original_quote


def test_the_new_helpers_are_in_the_code_sha():
    import inspect
    src = inspect.getsource(F)
    assert "'as_of'" in src and "'quote'" in src
    assert E.streaming_code_sha256()                                       # covers fast.py (tested in test_v05)


def test_quote_memo_keys_on_the_event_and_the_rate(tmp_path):
    from fractions import Fraction
    from bot.market.collector import summarize
    entry, archive = [x for x in hrr.load_fixtures(PACK)[2] if x[1].pool.startswith('C7F9')][0]
    summary, timeline = summarize(archive)
    timeline, _m = hrr.usable_timeline(archive, summary, timeline)
    observer = hrr._PoolObserver(archive, timeline, hrr.creation_facts(archive), w1_run.l1_params(), None, 0)
    event = timeline.events[5]
    low, high = Fraction(100), Fraction(250)
    expected = (hrr._PoolObserver._quote(observer, event, low), hrr._PoolObserver._quote(observer, event, high))
    with F.memoized(verify=True):
        got = (observer._quote(event, low), observer._quote(event, high), observer._quote(event, low))
    assert got == (expected[0], expected[1], expected[0]) and expected[0] != expected[1]


def test_quote_entry_keeps_its_observer_and_refuses_a_reused_id():
    """R02 0.5.2.1: an entry is served only for the very observer it was computed for (forced id reuse)."""
    memo = F.Memo()
    event, old_observer, new_observer = object(), object(), object()
    key = ('quote', id(event), id(new_observer), (5,))
    memo.store[key] = (event, 'stale', old_observer)                # same ids in the key, another observer inside
    assert memo.get('quote', event, (5,), lambda: 'fresh', owner=new_observer) == 'fresh'
    assert memo.store[key][2] is new_observer                       # the entry now holds the right observer
    assert memo.get('quote', event, (5,), lambda: 'never', owner=new_observer) == 'fresh'
    import inspect
    assert 'owner=self' in inspect.getsource(F.memoized)
