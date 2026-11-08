"""L1 P0 fixes: migration handling, causal fee estimate, optional exits, arm equivalence.

Everything here is offline and synthetic or uses the committed fixtures. Recorded
bundle fingerprints (validation/historical_replay_l1/RESULTS.json) must be
reproduced exactly: the fixes change no pre-registered parameter or past result.
"""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
import gzip
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from bot.market import replay as replay_module
from bot.market.collector import PoolArchive, summarize
from bot.market.launchlab_curve import FEE_DENOMINATOR, buy_exact_in, fee_for
from bot.market.launchlab_events import WSOL_MINT, TradeEvent, check_trade, implied_fee_rate_ppm
from bot.market.pool_timeline import Gap, PoolTimeline, build_timeline
from bot.market.replay import (ExecutionModel, Position, Strategy, causal_fee_rate, fee_rate_interval,
                               replay)
from bot.master_positions import choose_frozen_position_action
from bot.p4 import historical_research_replay as hrr
from test_launchlab_market_events import FRESH, POOL, _event_from_fill

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
RESULTS_PATH = ROOT / 'validation' / 'historical_replay_l1' / 'RESULTS.json'   # absent offline
DECLARED_150 = dict(sol_usd=150.0, sol_usd_provenance='ASSUMED_DECLARED')
# Recorded L1 bundles (RESULTS.json at fe8eb51): (variant, params, bundle, file, params sha256).
RECORDED = (
    ('a_default', {}, 'fa86f314f015277fc7a84f0124e5a04c4beaef00ab7caec05f91e3d255985270',
     '102f290119e382d5a59d7d93a9a5f0dba6f392f1bb4d593c1e68e4c9de941bae',
     '925ddc86ff32818d5f4bc81864418db4cd31481ad58b2d3da0d987540b6142f3'),
    ('b_sol150', DECLARED_150, '8f61ad57595e17fb64515d72aa94e4d6a8766a96619781199ed6409a1dc9da0c',
     'f19423a577cc5c48236c23b07489e4aa29fe7a4912eec5ece35238ce915cc7c1',
     '5af62f6f8277cd294cde6ff7cc3df6b124f2d611639019d531f9b9850107c631'),
    ('c_sol150_novault', dict(exclude_launchlab_vault=True, **DECLARED_150),
     '8643698219b48dafcca669896def4007238ae2ee565fbf8b308b1c128cc48133',
     '6ea453cfc400cbe3e3ec04ec83d08aea509e9f74628118944143b233ce0e7524',
     '18df15654fad39f4e9abbd4b00d6dab56cc7a147a17261996ec124e18172647b'),
    ('d_sol250_novault', dict(sol_usd=250.0, sol_usd_provenance='ASSUMED_DECLARED', exclude_launchlab_vault=True),
     '400d003c8feee4bac6448f106a66affbb876bec39f185175353bfc18c3982880',
     '1fb6a8c93c000787bd50eaa8e5ff537fe85ae2a500c928ecd61ac73dfc19287d',
     '5cc35994d0ef79371d7920a7b8a3c026e008ea74a7c2211e6d79b7fca4cd4c68'),
)
# The recorded hashes were produced on Python >= 3.12. Python 3.11 (the CI version)
# sums floats without compensation, so ``top_holder_share`` differs in its last bit and
# only the per-decision ``features_sha256`` changes (scores, intents, totals identical).
# Structural hash = bundle without bundle_sha256 and features_sha256, equal on 3.11-3.13.
STRUCTURAL = {
    'a_default': '2182efa81044f99542c6efdb553b1f719310e534d28a03abe155fbca7ef32f42',
    'b_sol150': '8b47a5f27a4bc8ff882c640e97767c987ef8475717d06a3c824632f020bdaccd',
    'c_sol150_novault': '985ebafb383d84c23c09759ac3af8d25d07a65e8e2707b55e19efa1bc3e6c367',
    'd_sol250_novault': '97870ccad34fca173669de496297f8eb1efb063adc168384e6bfefc472377bcc',
}
PY311 = {   # (bundle, file) on Python 3.11, identical at fe8eb51 and after these fixes
    'a_default': ('fa86f314f015277fc7a84f0124e5a04c4beaef00ab7caec05f91e3d255985270',
                  '102f290119e382d5a59d7d93a9a5f0dba6f392f1bb4d593c1e68e4c9de941bae'),
    'b_sol150': ('505766585932a18cf7d4d54281e18a4b85409c8ff533ff844f69e8fafaa6af42',
                 '064549b5e33abca4f76dd4ec9c65b670d9bca9ec5a1a3bc71a0bdc1ee877d86f'),
    'c_sol150_novault': ('b11140c9b73fa949b1da2d3e23ae856def4769354b80401126f717927ef513fc',
                         '31322ba63003df7cc346337e5a621401add5fc153bf63ee24756b3b4385f2b3f'),
    'd_sol250_novault': ('3419a399d44513915b185deb62cbc7b1b4b25a4ec2b56d0ac52ad1aeda1a9e0d',
                         '60b12fba0c04f0ea6fe2eaa528543cd97d284aead2cc8cf3386af4d529077c28'),
}
C7F9 = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'
P5PZ = '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2'
DVP = 'DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r'
DECLARED = dict(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')
PLAN = dict(tp_pct=10.0, sl_pct=8.0, trailing_stop_pct=5.0, hold_seconds=1800, cost_bps=200)
ZERO_COST = ExecutionModel(latency_slots=0, priority_fee_lamports=0, base_fee_lamports=0)


def archives():
    return {archive.pool: archive for _entry, archive in hrr.load_fixtures(PACK)[2]}


@lru_cache(maxsize=None)
def _bundle(**kwargs):
    return hrr.run_replay(PACK, hrr.ReplayParams(**kwargs))


class _Forced(hrr._PoolObserver):
    """Real observer, with an ENTER forced at ``enter_index`` (scorer plan PLAN)."""
    enter_index = 10

    def _evaluate(self, history):
        result = super()._evaluate(history)
        if len(history) - 1 == self.enter_index:
            result = dict(result, exit_conditions={k: PLAN[k] for k in ('tp_pct', 'sl_pct')},
                          scorer_exit_plan=dict(PLAN), decisions={
                              arm: dict(intent='ENTER', blocking_reasons=[]) for arm in hrr.ARMS})
        return result


def _forced_trade(pool, enter_index, options=None, params=None, timeline=None):
    params = params or hrr.ReplayParams(**DECLARED)
    archive = archives()[pool]
    timeline = timeline or summarize(archive)[1]
    observer = type('F', (_Forced,), dict(enter_index=enter_index))(
        archive, timeline, hrr.creation_facts(archive), params)
    arm = hrr.ResearchArm('master', observer, params, None, options)
    result = replay(timeline, arm, params.execution_model(), quote_mint=WSOL_MINT)
    return hrr._trade(result, timeline.events, arm, params), arm


# --- 1. migration boundary and pool exclusions --------------------------------------

def _crossing(previous, signature, rate=12_500):
    """The real capped buy that fills the curve (on chain the program refunds the rest)."""
    state = previous.state_after()
    amount_in = 10 ** 14
    fee = fee_for(amount_in, rate)
    values = {name: getattr(previous, name) for name in (
        'slot', 'block_time', 'fee_payer', 'pool', 'pool_status', 'total_base_sell',
        'virtual_base', 'virtual_quote')}
    values.update(signature=signature, event_index=0, side='buy', exact_in=True,
                  real_base_before=state.real_base, real_quote_before=state.real_quote,
                  real_base_after=state.total_base_sell, real_quote_after=state.real_quote + amount_in - fee,
                  amount_in=amount_in, amount_out=state.total_base_sell - state.real_base,
                  protocol_fee=fee, platform_fee=0, creator_fee=0, share_fee=0)
    return TradeEvent(violations=check_trade(values), **values)


def _migrating(boundary, pool=C7F9):
    """summarize() for ``pool`` as if its event ``boundary`` were the migrating buy."""
    real = summarize

    def fake(archive):
        summary, timeline = real(archive)
        if archive.pool != pool:
            return summary, timeline
        kept = list(timeline.events[:boundary])
        signature = timeline.events[boundary].signature
        cut = hrr._tx_key(archive.transactions[signature])
        archive.transactions = {s: tx for s, tx in archive.transactions.items()
                                if hrr._tx_key(tx) <= cut}
        archive.signatures = [r for r in archive.signatures
                              if r['signature'] in archive.transactions or r.get('err') is not None]
        migrated = build_timeline(pool, kept + [_crossing(kept[-1], signature)])
        return dict(summary, complete=False, trades=len(migrated.events), rejected=1,
                    max_progress_ppm=max(e.state_after().progress_ppm for e in kept)), migrated
    return fake


def _unit(events_at, rejected=(), gaps=(), **summary):
    """Archive/summary/timeline triple for usable_timeline unit tests."""
    transactions = {sig: dict(slot=slot, transactionIndex=index, blockTime=1) for sig, slot, index in events_at}
    events = tuple(SimpleNamespace(signature=sig) for sig, _s, _i in events_at
                   if sig not in {key[0] for key, _reason in rejected})
    base = dict(complete=not rejected and not gaps, signatures_complete=True, transactions_missing=0,
                undecodable=0, max_progress_ppm=700_000)
    base.update(summary)
    return (SimpleNamespace(transactions=transactions), base,
            PoolTimeline('pool', events, tuple(gaps), tuple(rejected)))


def test_capped_crossing_buy_is_rejected_with_the_migration_violation():
    _summary, timeline = summarize(archives()[C7F9])
    crossing = _crossing(timeline.events[12], timeline.events[13].signature)
    assert crossing.violations == ('curve_refused:buy_crosses_migration_boundary',)
    migrated = build_timeline(C7F9, list(timeline.events[:13]) + [crossing])
    assert migrated.rejected == ((crossing.key, hrr.MIGRATION_VIOLATION),)
    with pytest.raises(ValueError, match='timeline_incomplete'):     # the defect fixed here
        replay(migrated, SimpleNamespace(), quote_mint=WSOL_MINT)


def test_complete_history_is_used_as_is():
    archive, summary, timeline = _unit([('a', 10, 0), ('b', 11, 0)])
    assert hrr.usable_timeline(archive, summary, timeline) == (timeline, None)


def test_history_ending_at_the_migrating_buy_is_replayable():
    rejected = ((('c', 0), hrr.MIGRATION_VIOLATION),)
    archive, summary, timeline = _unit([('a', 10, 0), ('b', 11, 3), ('c', 11, 7)], rejected)
    usable, migration = hrr.usable_timeline(archive, summary, timeline)
    assert usable.complete and usable.events == timeline.events
    assert migration == dict(rule=hrr.MIGRATION_RULE, boundary_signatures=['c'], boundary_slot=11,
                             boundary_transaction_index=7, max_progress_ppm=700_000)


@pytest.mark.parametrize('after', [('d', 12, 0), ('d', 11, 9), ('c', 11, 7)])
def test_any_valid_event_at_or_after_the_boundary_excludes_the_pool(after):
    rejected = ((('c', 0), hrr.MIGRATION_VIOLATION),)
    archive, summary, timeline = _unit([('a', 10, 0), ('c', 11, 7), ('d', after[1], after[2])], rejected)
    if after[0] == 'c':           # a valid event inside the migrating transaction itself
        timeline = PoolTimeline('pool', timeline.events[:1] + (SimpleNamespace(signature='c'),), (), rejected)
    with pytest.raises(hrr.PoolExcluded) as excinfo:
        hrr.usable_timeline(archive, summary, timeline)
    assert excinfo.value.reasons == ['events_after_migration_boundary']


def test_every_other_defect_excludes_the_pool_with_all_its_reasons():
    rejected = ((('c', 0), hrr.MIGRATION_VIOLATION), (('b', 0), 'violations:buy_quote_delta_mismatch'))
    gaps = (Gap(None, ('a', 0), 10, 10, 'history_starts_mid_curve'),)
    archive, summary, timeline = _unit([('a', 10, 0), ('b', 11, 0), ('c', 12, 0)], rejected, gaps,
                                       signatures_complete=False, transactions_missing=2, undecodable=1)
    with pytest.raises(hrr.PoolExcluded) as excinfo:
        hrr.usable_timeline(archive, summary, timeline)
    assert excinfo.value.reasons == [
        'signatures_incomplete', 'transactions_missing:2', 'undecodable_transactions:1',
        'timeline_gaps:history_starts_mid_curve', 'rejected_events:violations:buy_quote_delta_mismatch']
    for defect, reason in ((dict(complete=False, transactions_missing=1), 'transactions_missing:1'),
                           (dict(complete=False), 'history_incomplete')):
        archive, summary, timeline = _unit([('a', 10, 0)], **defect)
        with pytest.raises(hrr.PoolExcluded) as excinfo:
            hrr.usable_timeline(archive, summary, timeline)
        assert excinfo.value.reasons == [reason]


def test_position_open_at_the_migration_is_unpriced_and_never_a_cycle(monkeypatch):
    params = hrr.ReplayParams(**DECLARED)
    monkeypatch.setattr(hrr, 'summarize', _migrating(18))
    monkeypatch.setattr(hrr, '_PoolObserver', _Forced)
    record = hrr.replay_pool(archives()[C7F9], params, quote_mint=WSOL_MINT)
    _summary, real = summarize(archives()[C7F9])
    boundary = real.events[18]
    # 18 curve events before the migrating buy; decisions stop at the forced entry (10).
    assert record['trades'] == 18 and max(row['index'] for row in record['journal']) == 10
    assert record['migration']['boundary_signatures'] == [boundary.signature]
    assert record['migration']['boundary_slot'] == boundary.slot
    for row in record['arms'].values():
        assert row['outcome'] == 'migrated_unpriced' and row['entry_index'] is not None
        assert row['pnl_lamports'] is None and row['net_return'] is None
        assert row['mark_pnl_lamports'] == (row['received'] - row['spent'] - row['tx_costs']
                                            - row['failed_attempt_costs'])
    totals = hrr._totals([record])
    assert all(totals[arm]['pnl_lamports'] is None and totals[arm]['closed_cycles'] == 0
               and totals[arm]['outcomes'] == {'migrated_unpriced': 1} for arm in hrr.ARMS)


def test_cycle_closed_before_the_migration_stays_closed(monkeypatch):
    free, _arm = _forced_trade(P5PZ, 2)          # stop loss at event 9 of 11
    assert free['outcome'] == 'closed' and free['exit_index'] == 9
    monkeypatch.setattr(hrr, '_PoolObserver', type('F', (_Forced,), dict(enter_index=2)))
    monkeypatch.setattr(hrr, 'summarize', _migrating(10, pool=P5PZ))
    record = hrr.replay_pool(archives()[P5PZ], hrr.ReplayParams(**DECLARED), quote_mint=WSOL_MINT)
    assert record['migration']['boundary_slot'] == summarize(archives()[P5PZ])[1].events[10].slot
    for row in record['arms'].values():
        assert row['outcome'] == 'closed' and row['exit_index'] == 9
        assert row['pnl_lamports'] == free['pnl_lamports'] < 0


def test_bundle_lists_migration_rule_and_keeps_marks_out_of_totals(monkeypatch):
    monkeypatch.setattr(hrr, 'summarize', _migrating(18))
    monkeypatch.setattr(hrr, '_PoolObserver', _Forced)
    doc = hrr.run_replay(PACK, hrr.ReplayParams(**DECLARED))
    migrated = [row for row in doc['pools'] if 'migration' in row]
    assert [row['pool'] for row in migrated] == [C7F9]
    assert doc['flags']['migration_rule'] == hrr.MIGRATION_RULE and 'excluded_pools' not in doc
    for arm in hrr.ARMS:
        priced = [p['arms'][arm]['pnl_lamports'] for p in doc['pools']
                  if p['arms'][arm]['pnl_lamports'] is not None]
        assert doc['totals'][arm]['pnl_lamports'] == (sum(priced) if priced else None)
        assert doc['totals'][arm]['outcomes'].get('migrated_unpriced') == 1


def _pack_without_last_trade(tmp_path, pool):
    pack = tmp_path / 'pack'
    shutil.copytree(PACK, pack)
    path = pack / f'{pool}.json.gz'
    data = json.loads(gzip.decompress(path.read_bytes()))
    archive = PoolArchive.from_json(data)
    _summary, timeline = summarize(archive)
    del data['transactions'][timeline.events[-1].signature]
    raw = gzip.compress(json.dumps(data).encode(), mtime=0)
    path.write_bytes(raw)
    manifest = json.loads((pack / 'MANIFEST.json').read_text('utf-8'))
    for entry in manifest['pools']:
        if entry['pool'] == pool:
            entry['sha256'] = hashlib.sha256(raw).hexdigest()
    (pack / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    return pack


def test_excluded_pool_is_listed_and_the_rest_is_still_replayed(tmp_path):
    doc = hrr.run_replay(_pack_without_last_trade(tmp_path, DVP), hrr.ReplayParams(**DECLARED))
    assert doc['excluded_pools'] == [dict(pool=DVP, file=f'{DVP}.json.gz', reasons=['transactions_missing:1'])]
    assert doc['flags']['pool_exclusion_rule'] == hrr.EXCLUSION_RULE
    assert sorted(row['pool'] for row in doc['pools']) == sorted([C7F9, P5PZ])
    assert len(doc['pools']) + len(doc['excluded_pools']) == len(doc['fixtures']['files']) == 3
    assert 'migration_rule' not in doc['flags']


# --- 2. causal fee estimate ------------------------------------------------------------

def test_fee_interval_is_exactly_the_set_of_rates_reproducing_the_rounded_fee():
    for basis in (1, 7, 80, 999, 10**6, 3 * 10**9 + 17):
        for rate in (1, 99, 10_000, 12_500, 17_500, 25_000):
            fee = fee_for(basis, rate)
            event = SimpleNamespace(side='buy', amount_in=basis, amount_out=1, protocol_fee=fee,
                                    platform_fee=0, creator_fee=0, share_fee=0)
            low, high = fee_rate_interval(event)
            assert low <= rate <= high
            assert all(fee_for(basis, r) == fee for r in (low, high))
            assert low == 1 or fee_for(basis, low - 1) != fee
            assert high == FEE_DENOMINATOR - 1 or fee_for(basis, high + 1) != fee
    assert fee_rate_interval(SimpleNamespace(side='buy', amount_in=10, amount_out=1, protocol_fee=0,
                                             platform_fee=0, creator_fee=0, share_fee=0)) is None


def _chain(trades, state=FRESH):
    """trades: [(quote_in, rate_ppm)]; real buys with exact rounded fees."""
    events = []
    for i, (quote_in, rate) in enumerate(trades):
        fill = buy_exact_in(state, quote_in, rate)
        events.append(_event_from_fill(fill, slot=100 + i, sig=f's{i:03d}'))
        state = fill.after
    assert all(e.violations == () for e in events)
    return events


class _EnterAt(Strategy):
    def __init__(self, index, spend=10**8):
        self.index, self.spend = index, spend

    def entry(self, history):
        return self.spend if len(history) - 1 == self.index else None

    def exit(self, history, position, mark):
        return False


def test_tiny_decision_event_no_longer_sets_an_implausible_rate():
    events = _chain([(10**9, 12_500)] * 4 + [(80, 12_500)])
    tiny = events[-1]
    assert tiny.total_fee == 1 and _values_rate(tiny) == 1          # old estimate: 1 ppm
    timeline = build_timeline(POOL, events)
    old = replay(timeline, _EnterAt(4), ZERO_COST, quote_mint=WSOL_MINT)
    assert (old.fee_rate_ppm, old.fee_rate_source) == (1, 'pool_event_at_decision')
    causal = ExecutionModel(latency_slots=0, priority_fee_lamports=0, base_fee_lamports=0,
                            fee_rate_estimator='causal_interval')
    new = replay(timeline, _EnterAt(4), causal, quote_mint=WSOL_MINT)
    assert (new.fee_rate_ppm, new.fee_rate_source) == (12_500, 'pool_events_causal_interval')
    assert new.fee_rate_evidence == dict(
        rule='largest_rate_compatible_with_the_longest_consistent_run_up_to_the_decision',
        interval_ppm=[12_500, 12_500], events_used=5, events_skipped=0)
    assert new.tokens < old.tokens                                   # the 1 ppm fill was too cheap


def _values_rate(event):
    return implied_fee_rate_ppm(dict(side=event.side, amount_in=event.amount_in, amount_out=event.amount_out,
                                     protocol_fee=event.protocol_fee, platform_fee=event.platform_fee,
                                     creator_fee=event.creator_fee, share_fee=event.share_fee))


def test_rate_change_uses_the_longest_consistent_run_ending_at_the_decision():
    events = _chain([(10**9, 10_000)] * 3 + [(10**9, 12_500)] * 2)
    rate, evidence = causal_fee_rate(events)
    assert rate == 12_500 and evidence['events_used'] == 2 and evidence['interval_ppm'] == [12_500, 12_500]
    rate, evidence = causal_fee_rate(events[:3])
    assert rate == 10_000 and evidence['events_used'] == 3


def test_run_stops_at_the_first_incompatible_event_and_never_skips_over_it():
    # Rate change 12 500 -> 10 000 -> 12 500: only the contiguous run ending at the
    # decision counts, even if an older epoch would narrow the interval again.
    events = _chain([(10**9, 12_500), (10**9, 10_000), (999, 12_500)])
    rate, evidence = causal_fee_rate(events)
    assert (rate, evidence['interval_ppm'], evidence['events_used']) == (13_013, [12_013, 13_013], 1)


def test_upper_bound_of_the_compatible_interval_is_used():
    events = _chain([(80, 12_500), (999, 12_500)])
    assert [fee_rate_interval(e) for e in events] == [(1, 12_500), (12_013, 13_013)]
    assert _values_rate(events[-1]) == 12_013                        # old estimate, below the true rate
    rate, evidence = causal_fee_rate(events)
    assert (rate, evidence['interval_ppm'], evidence['events_used']) == (12_500, [12_013, 12_500], 2)


def test_without_any_fee_bearing_event_the_decision_event_rate_is_kept():
    events = _chain([(10**9, 0)] * 2)
    rate, evidence = causal_fee_rate(events)
    assert rate == _values_rate(events[-1]) == 0
    assert evidence == dict(rule='no_fee_bearing_event_decision_event_rate', interval_ppm=None,
                            events_used=0, events_skipped=2)


def test_fee_estimate_reads_only_events_up_to_the_decision(monkeypatch):
    events = _chain([(10**9, 12_500)] * 3 + [(10**9, 25_000)] * 3)
    seen = []
    real = replay_module.causal_fee_rate
    monkeypatch.setattr(replay_module, 'causal_fee_rate', lambda prefix: seen.append(len(prefix)) or real(prefix))
    causal = ExecutionModel(latency_slots=0, fee_rate_estimator='causal_interval')
    result = replay(build_timeline(POOL, events), _EnterAt(2), causal, quote_mint=WSOL_MINT)
    assert seen == [3] and result.fee_rate_ppm == 12_500          # later 25 000 ppm events unread


def test_estimator_is_validated_and_other_callers_keep_the_old_default():
    with pytest.raises(ValueError, match='unknown_fee_rate_estimator'):
        ExecutionModel(fee_rate_estimator='future_events')
    assert ExecutionModel().fee_rate_estimator == 'event_at_decision'
    model = hrr.ReplayParams().execution_model()
    assert model.fee_rate_estimator == 'causal_interval' and model.fee_rate_ppm is None
    explicit = ExecutionModel(latency_slots=0, fee_rate_ppm=10_000, fee_rate_estimator='causal_interval')
    result = replay(build_timeline(POOL, _chain([(10**9, 12_500)] * 2)), _EnterAt(1), explicit,
                    quote_mint=WSOL_MINT)
    assert (result.fee_rate_ppm, result.fee_rate_source, result.fee_rate_evidence) == (10_000, 'model', None)


def test_forced_cycle_fee_evidence_on_committed_fixture():
    trade, _arm = _forced_trade(P5PZ, 2)
    assert trade['fee_rate_source'] == 'pool_events_causal_interval'
    assert trade['fee_rate_ppm'] == 10_000 == trade['fee_rate_evidence']['interval_ppm'][1]
    assert trade['fee_rate_evidence']['events_used'] == trade['decision_index'] + 1


# --- 3. optional trailing stop and maximum hold ---------------------------------------

def test_exit_options_are_off_by_default_and_validated():
    assert hrr.ExitOptions() == hrr.ExitOptions(False, False) and not hrr.ExitOptions().enabled
    for bad in (dict(trailing_stop=1), dict(max_hold='yes')):
        with pytest.raises(ValueError, match='invalid_exit_options'):
            hrr.ExitOptions(**bad)
    with pytest.raises(ValueError, match='invalid_exit_options'):
        hrr.run_replay(PACK, exit_options=dict(trailing_stop=True))
    default = _bundle()
    assert 'exit_options' not in default
    both = hrr.run_replay(PACK, exit_options=hrr.ExitOptions(True, True))
    assert both['exit_options'] == dict(trailing_stop=True, max_hold=True)
    assert both['bundle_sha256'] != default['bundle_sha256']
    without = {k: v for k, v in both.items() if k not in ('exit_options', 'bundle_sha256')}
    assert hrr._sha(without) == default['bundle_sha256']            # nothing else changes here


def test_only_enabled_exits_are_copied_from_the_scorer_plan():
    for options, extra in ((None, {}), (hrr.ExitOptions(trailing_stop=True), dict(trailing_stop_pct=5.0)),
                           (hrr.ExitOptions(max_hold=True), dict(hold_seconds=1800)),
                           (hrr.ExitOptions(True, True), dict(trailing_stop_pct=5.0, hold_seconds=1800))):
        trade, arm = _forced_trade(C7F9, 10, options)
        assert arm.exit_plan == dict(tp_pct=10.0, sl_pct=8.0, **extra) == trade['exit_conditions']


def _point(block_time, price):
    return SimpleNamespace(block_time=block_time,
                           state_after=lambda: SimpleNamespace(quote_reserve=price, base_reserve=1))


def _arm(plan, horizon_ms=3_600_000):
    arm = hrr.ResearchArm('master', None, SimpleNamespace(exit_horizon_ms=horizon_ms))
    arm.exit_plan = dict(plan)
    return arm


POSITION = Position(0, 1, 100, 1_000, 5)


def _walk(arm, prices, mark=1_000, last_time=101):
    history, trigger = [_point(100, prices[0])], None
    for step, price in enumerate(prices[1:], start=1):
        history.append(_point(last_time if step == len(prices) - 1 else 100, price))
        if arm.exit(list(history), POSITION, mark if step == len(prices) - 1 else 1_000):
            trigger = arm.exit_trigger['reason']
    return trigger


def test_trailing_stop_arms_above_entry_and_fires_on_the_drawdown():
    plan = dict(tp_pct=10.0, sl_pct=8.0, trailing_stop_pct=5.0)
    assert _walk(_arm(plan), [100, 94]) is None                      # peak never above entry
    assert _walk(_arm(plan), [100, 120, 115]) is None                # 115 > 120 * 0.95
    assert _walk(_arm(plan), [100, 120, 114]) == 'trailing_stop'     # 114 <= 114
    assert _walk(_arm(dict(tp_pct=10.0, sl_pct=8.0)), [100, 120, 50]) is None   # disabled


def test_trailing_entry_price_is_the_spot_behind_which_our_buy_lands():
    trade, arm = _forced_trade(P5PZ, 0, hrr.ExitOptions(trailing_stop=True))
    _summary, timeline = summarize(archives()[P5PZ])
    assert arm.entry_price == hrr._spot(timeline.events[trade['entry_index']])
    assert arm.peak_price == max(hrr._spot(e) for e in timeline.events[trade['entry_index']:trade['exit_index'] + 1])
    assert trade['exit_trigger']['reason'] == 'trailing_stop' and trade['outcome'] == 'closed'
    spot = hrr._spot(timeline.events[trade['exit_trigger']['index']])
    assert spot <= arm.peak_price * (1 - Fraction(5, 100))
    peak = arm.entry_price
    for event in timeline.events[trade['entry_index'] + 1:trade['exit_trigger']['index']]:
        peak = max(peak, hrr._spot(event))      # no earlier event met the armed drawdown
        assert not (peak > arm.entry_price and hrr._spot(event) <= peak * Fraction(95, 100))
    off, _ = _forced_trade(P5PZ, 0)
    assert off['exit_trigger'] is None and off['outcome'] == 'open_at_end'


def test_maximum_hold_fires_only_when_enabled_and_after_hold_seconds():
    plan = dict(tp_pct=10.0, sl_pct=8.0, hold_seconds=900)
    assert _walk(_arm(plan), [100, 100], last_time=100 + 899) is None
    assert _walk(_arm(plan), [100, 100], last_time=100 + 900) == 'max_hold'
    assert _walk(_arm(dict(tp_pct=10.0, sl_pct=8.0)), [100, 100], last_time=100 + 900) is None
    # With the pre-registered 30 s horizon, the horizon is reached long before hold_seconds.
    assert _walk(_arm(plan, horizon_ms=30_000), [100, 100], last_time=100 + 30) == 'exit_horizon'


OPERATIONAL = {'frozen_stop_loss_reached': 'stop_loss', 'frozen_trailing_stop_reached': 'trailing_stop',
               'frozen_maximum_hold_reached': 'max_hold',
               'frozen_price_target_SOL_profit_unproven': 'take_profit',
               'entry_thesis_not_invalidated_by_available_observations': None}


@pytest.mark.parametrize('stop,trail,hold,take', [
    case for case in itertools.product((False, True), repeat=4) if not (case[0] and case[3])])
def test_trigger_precedence_matches_the_operational_rule(stop, trail, hold, take):
    mark = 900 if stop else 1_100 if take else 1_000
    prices = [100, 120, 110 if trail else 118]
    elapsed = 1_800 if hold else 10
    ours = _walk(_arm(dict(tp_pct=10.0, sl_pct=8.0, trailing_stop_pct=5.0, hold_seconds=1_800)),
                 prices, mark=mark, last_time=100 + elapsed)
    _action, reasons, _chosen = choose_frozen_position_action(
        emergency=False, creator_risk=False, ratio=Fraction(mark, 1_000) - 1,
        trailing_drawdown_ratio=Fraction(prices[-1], 120), trailing_armed=True, age_ms=elapsed * 1000,
        model=dict(tp_pct=10.0, sl_pct=8.0, trailing_stop_pct=5.0, hold_seconds=1_800), features=None,
        full=None, partial=None, observations_complete=True)
    assert ours == OPERATIONAL[reasons[0]]


def test_cli_flags_and_exclusion_report(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location('hrr_cli', ROOT / 'tools' / 'historical_research_replay.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    cli.main(['--fixtures', str(PACK)])
    assert f'bundle_sha256 {RECORDED[0][2]}' in capsys.readouterr().out
    out = tmp_path / 'b.json'
    cli.main(['--fixtures', str(_pack_without_last_trade(tmp_path, DVP)), '--trailing-stop', '--max-hold',
              '--out', str(out)])
    text = capsys.readouterr().out
    assert f'EXCLUDED {DVP[:8]} ({DVP}.json.gz): transactions_missing:1' in text
    assert json.loads(out.read_text('utf-8'))['exit_options'] == dict(trailing_stop=True, max_hold=True)


# --- 4. recorded fingerprints and arm equivalence -------------------------------------

@pytest.mark.parametrize('variant,params,bundle_sha,file_sha,params_sha', RECORDED, ids=[r[0] for r in RECORDED])
def test_recorded_bundles_are_reproduced_exactly(variant, params, bundle_sha, file_sha, params_sha):
    doc = _bundle(**params)
    structural = deepcopy(doc)
    structural.pop('bundle_sha256')
    for row in (row for pool in structural['pools'] for row in pool['journal']):
        row.pop('features_sha256')
    assert hrr._sha(structural) == STRUCTURAL[variant] and doc['params_sha256'] == params_sha
    if sys.version_info < (3, 12):
        bundle_sha, file_sha = PY311[variant]
    assert doc['bundle_sha256'] == bundle_sha
    text = json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n'
    assert hashlib.sha256(text.encode()).hexdigest() == file_sha
    assert 'excluded_pools' not in doc and 'exit_options' not in doc
    assert not {'migration_rule', 'pool_exclusion_rule'} & set(doc['flags'])
    if RESULTS_PATH.exists():          # in a checkout: the pins are the recorded results
        results = json.loads(RESULTS_PATH.read_text('utf-8'))
        recorded = next(v for v in results['variants'] if v['variant'] == variant)
        pinned = next(r for r in RECORDED if r[0] == variant)
        assert (recorded['bundle_sha256'], recorded['file_sha256'], recorded['params_sha256']) == pinned[2:]
        assert recorded['params'] == doc['params'] and recorded['totals'] == doc['totals']
        if variant == results['committed_bundle']['variant']:
            assert (ROOT / results['committed_bundle']['path']).read_text('utf-8') == text


@pytest.mark.parametrize('kwargs', [r[1] for r in RECORDED[1:]], ids=[r[0] for r in RECORDED[1:]])
def test_master_union_of_intents_equals_early_sniping_at_every_decision(kwargs):
    """Mission 4 finding: no operational rule makes the master arm differ offline."""
    doc = _bundle(**kwargs)
    scored = 0
    for pool in doc['pools']:
        by_index = {}
        for row in pool['journal']:
            by_index.setdefault(row['index'], {})[row['arm']] = row
            if row['strategy_intents'] is not None:
                intents = row['strategy_intents']
                union = any(v['entry_intent'] is True for v in intents.values())
                assert union is (intents[hrr.REFERENCE_STRATEGY]['entry_intent'] is True)
                scored += 1
        for rows in by_index.values():
            assert rows['master']['intent'] == rows['reference']['intent']
        assert pool['arms']['master'] == pool['arms']['reference']
    assert scored > 0
    assert doc['flags']['master_operational_trade'] is False
    assert doc['flags']['counted_in_master_gate'] is False
    # Default: no optional exit at all; the bundle record keeps the two historical keys (R1 adds
    # clock_horizon, recorded only when on).
    assert hrr.ExitOptions().record() == dict(trailing_stop=False, max_hold=False)
    assert not hrr.ExitOptions().enabled and not hrr.ExitOptions().clock_horizon
