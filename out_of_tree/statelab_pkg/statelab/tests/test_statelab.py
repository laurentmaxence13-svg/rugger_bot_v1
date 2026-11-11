"""statelab 0.2: causal points, the clock-exit value against v4sim itself and an independent recomputation,
the placebo of the frozen RandomEntry, segment guards, and the declared table (floors, K, pairing, screening)."""
from dataclasses import replace
import json

import pytest

from bot.market.collector import summarize
from bot.market.launchlab_curve import CurveState, buy_exact_in, sell_exact_in
from bot.market.launchlab_events import WSOL_MINT, TradeEvent
from bot.market.pool_timeline import PoolTimeline
from bot.market.replay import Strategy, causal_fee_rate
from bot.master_v2 import policies as v2
from bot.master_v2.harness import ExitRule
from bot.p4 import historical_research_replay as hrr
from v3lab import plan, runner
from v3lab.tests.test_v3lab import archives, visible            # noqa: F401  (fixtures)
from v4sim import engine
from v4sim.engine import landing_index
from v4sim.io import EVENT_FIELDS, actors_from_archive
from v4sim.ledger import Others
from v4sim.valuation import liquidation

from statelab import points, study, table

PARAMS = hrr.ReplayParams(**plan.REPLAY)
MODEL = PARAMS.execution_model()
LATENCY_S = study.sale_latency_s(MODEL)


def _pool(archive):
    summary, timeline = summarize(archive)
    timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    return timeline, facts, actors_from_archive(archive, timeline.events)[0]


def _points(timeline, facts):
    return points.decision_points(timeline.events, facts['creation_block_time'], timeline.pool)


def _synthetic(steps, rate=12_500, pool='POOL'):
    """PoolTimeline from ``[(seconds, side, amount, actor[, signature])]`` on a real-shaped curve (no real data)."""
    state = CurveState(1_073_025_605_596_382, 30_000_852_951, 0, 0, 793_100_000_000_000)
    events, slot, time = [], 400_000_000, 1_790_000_000
    for index, step in enumerate(steps):
        seconds, side, amount, actor = step[:4]
        slot, time = slot + 5 * max(seconds, 1), time + seconds
        if amount == 'ALMOST_ALL':                          # a buy that leaves about 10^9 atomic tokens on the curve
            out = state.remaining_base - 10 ** 9
            net = -(-out * state.quote_reserve // (state.base_reserve - out))
            amount = -(-net * 1_000_000 // (1_000_000 - rate)) + 2
            while buy_exact_in(state, amount, rate).amount_out > state.remaining_base - 10 ** 6:
                amount -= 1_000
        fill = buy_exact_in(state, amount, rate) if side == 'buy' else sell_exact_in(state, amount, rate)
        row = dict(signature=step[4] if len(step) > 4 else 'sig%04d' % index, slot=slot, block_time=time, event_index=0,
                   fee_payer=actor, pool=pool, side=side, exact_in=True, pool_status=0,
                   total_base_sell=state.total_base_sell, virtual_base=state.virtual_base,
                   virtual_quote=state.virtual_quote, real_base_before=state.real_base,
                   real_quote_before=state.real_quote, real_base_after=fill.after.real_base,
                   real_quote_after=fill.after.real_quote, amount_in=fill.amount_in, amount_out=fill.amount_out,
                   protocol_fee=fill.fee, platform_fee=0, creator_fee=0, share_fee=0)
        events.append(TradeEvent(**{name: row[name] for name in EVENT_FIELDS}))
        state = fill.after
    return PoolTimeline(pool, tuple(events), ())


# --- the grid ------------------------------------------------------------------------------------

def test_the_grid_is_causal_whole_transaction_and_first_crossing(archives):                      # noqa: F811
    seen = 0
    for _entry, archive in archives:
        timeline, facts, _actors = _pool(archive)
        events, created = timeline.events, facts['creation_block_time']
        full = _points(timeline, facts)
        for k, labels in full:
            assert points.whole(events, k)
            for kind, level in labels:
                age, progress = events[k].block_time - created, events[k].state_after().progress_ppm
                earlier = [j for j in range(k) if points.whole(events, j)]
                if kind == 'age':
                    assert level <= age <= level + points.MAX_LATENESS_S
                    assert not any(events[j].block_time - created >= level for j in earlier)
                elif kind == 'progress':
                    assert progress >= level and all(events[j].state_after().progress_ppm < level for j in earlier)
                else:
                    target = points.placebo_target_age(timeline.pool)
                    assert (kind, level) == ('placebo', 0) and target <= age <= points.PLACEBO_MAX_AGE_S
                    assert not any(events[j].block_time - created >= target for j in earlier)
        flat = [(kind, level) for _k, labels in full for kind, level in labels]
        assert len(flat) == len(set(flat))                                    # each label at most once per pool
        for cut in [k for k in range(len(events)) if points.whole(events, k)]:   # nothing depends on what comes after
            assert points.decision_points(events[:cut + 1], created, timeline.pool) == [p for p in full if p[0] <= cut]
        seen += len(full)
    assert seen >= 6 and points.K_GRID == 90


def test_a_decision_waits_for_the_whole_transaction_and_a_silent_pool_gives_no_late_point():
    timeline = _synthetic([(0, 'buy', 500_000_000, 'a', 'tx1'), (0, 'buy', 300_000_000, 'a', 'tx1'),
                           (2, 'buy', 200_000_000, 'b'), (98, 'buy', 100_000_000, 'c'), (30, 'sell', 10 ** 9, 'a')])
    events = timeline.events
    got = {k: [label for label in labels if label[0] != 'placebo']
           for k, labels in points.decision_points(events, events[0].block_time, 'POOL')}
    assert 0 not in got and got[1] == [['age', 0]]              # event 0 is mid-transaction: never a decision
    assert not got.get(2) and not got.get(3)                    # age 100: more than 30 s late for 5, 15, 30 and 60
    assert got[4] == [['age', 120]]                             # age 130: within 30 s of the 120 s target


def test_the_placebo_is_the_frozen_random_entry_one_draw_per_pool(archives):                      # noqa: F811
    frozen = v2.RandomEntry(max_age_s=points.PLACEBO_MAX_AGE_S, salt=points.PLACEBO_SALT)
    matched = 0
    for entry, archive in archives:
        assert points.placebo_target_age(archive.pool) == frozen.target_age(archive.pool)
        reference = runner.run_pool(archive, frozen, ExitRule(max_hold_s=25, clock_exit=True), PARAMS,
                                    quote_mint=entry['quote_mint'])
        timeline, facts, _actors = _pool(archive)
        mine = [k for k, labels in _points(timeline, facts) if ['placebo', 0] in labels]
        if reference['trade']['decision_index'] is not None and reference['trade']['entry_index'] is not None:
            assert mine == [reference['trade']['decision_index']]
            matched += 1
    assert matched >= 1
    for name in ('POOL', 'POOL2', 'POOL3', 'POOL4'):
        target = points.placebo_target_age(name)
        assert 0 <= target <= points.PLACEBO_MAX_AGE_S
        # the first whole event at or after the target is beyond 120 s: the draw is lost, never moved to a later event
        late = _synthetic([(0, 'buy', 10 ** 8, 'a'), (121 + target, 'buy', 10 ** 8, 'b'), (1, 'buy', 10 ** 8, 'c')],
                          pool=name)
        labels = [label for _k, group in points.decision_points(late.events, late.events[0].block_time - 1, name)
                  for label in group]
        assert ['placebo', 0] not in labels or target <= 1
    assert len({points.placebo_target_age(name) for name in ('POOL', 'POOL2', 'POOL3', 'POOL4')}) > 1


# --- forward values ------------------------------------------------------------------------------

class _ClockExit(Strategy):
    """Buy at ``k``; sell by the clock ``hold`` seconds after the entry (the frozen clock-exit path of v4sim)."""

    def __init__(self, k, amount, hold):
        self.k, self.amount, self.hold = k, amount, hold

    def entry(self, history):
        return self.amount if len(history) - 1 == self.k else None

    def exit(self, history, position, mark):
        return False

    def exit_deadline(self, position):
        return position.entry_time + self.hold


def _all_points(archives, extra=()):                                                              # noqa: F811
    for _entry, archive in archives:
        timeline, facts, actors = _pool(archive)
        for k, _labels in _points(timeline, facts):
            yield timeline, k, actors
    for timeline, ks in extra:
        for k in ks:
            yield timeline, k, {}


SYNTHETIC = [(_synthetic([(0, 'buy', 500_000_000, 'a'), (3, 'buy', 300_000_000, 'b'), (4, 'sell', 4 * 10 ** 12, 'a'),
                          (5, 'buy', 900_000_000, 'c'), (2, 'sell', 10 ** 12, 'c'), (11, 'sell', 3 * 10 ** 12, 'b'),
                          (1, 'buy', 10 ** 8, 'd'), (35, 'buy', 2 * 10 ** 9, 'e'), (61, 'sell', 10 ** 12, 'c'),
                          (190, 'buy', 10 ** 9, 'f')]),          # seen from event 1: ages 4, 9, 11, 22, 23, 58, 119, 309
              (0, 1, 2, 3)),
             (_synthetic([(0, 'buy', 500_000_000, 'a'), (5, 'buy', 300_000_000, 'b'), (8, 'buy', 200_000_000, 'c'),
                          (40, 'buy', 'ALMOST_ALL', 'whale'), (10, 'sell', 10 ** 9, 'a')]), (0, 1, 2))]


def test_every_horizon_value_is_the_clock_exit_replayed_by_v4sim(archives):                       # noqa: F811
    """R02 C-S1: the value of horizon h equals, to the lamport, a clock exit of h seconds in v4sim mode M-P."""
    clock_model = replace(MODEL, clock_exit_latency_s=hrr.clock_exit_latency_s(MODEL.latency_slots))
    closed = migrated = five_at_25 = 0
    for timeline, k, actors in _all_points(archives, SYNTHETIC):
        row = study.probe(timeline, k, actors, MODEL)
        if not row['entered']:
            continue
        for h in points.HORIZONS_S:
            result = engine.replay(timeline, _ClockExit(k, study.STAKE_LAMPORTS, h), clock_model, quote_mint=WSOL_MINT,
                                   mode='M-P', actors=actors)
            got = row['horizons'][str(h)]
            assert (result.entry_index, result.tokens) == (row['land_index'], row['tokens'])
            if result.outcome == 'closed':
                assert 'clock_exit' in result.notes and got['migrated'] is False
                assert result.received == got['value']
                closed += 1
            else:
                assert result.outcome == 'migrated_unpriced' and got['migrated'] is True and got['value'] is None
                migrated += 1
    assert closed >= 40 and migrated >= 3
    # the 5 s point at the 25 s horizon is the reference V3-01 (entry 5 s, clock 25 s) valued by v4sim M-P
    for _entry, archive in archives:
        timeline, facts, actors = _pool(archive)
        for k, labels in _points(timeline, facts):
            if ['age', 5] in labels:
                row = study.probe(timeline, k, actors, MODEL)
                result = engine.replay(timeline, _ClockExit(k, study.STAKE_LAMPORTS, 25), clock_model,
                                       quote_mint=WSOL_MINT, mode='M-P', actors=actors)
                assert result.outcome == 'closed' and result.received == row['horizons']['25']['value']
                five_at_25 += 1
    assert five_at_25 >= 1


def _by_hand(timeline, k, actors):
    """Independent recomputation with the ledger API: (immediate, [(age, mark)], tokens, land)."""
    events = timeline.events
    rate, _evidence = causal_fee_rate(events[:k + 1])
    land = landing_index(events, k, events[k].slot + MODEL.latency_slots)
    fill = buy_exact_in(events[land].state_after(), study.STAKE_LAMPORTS, rate)
    others = Others('M-P', events, actors)
    for event in events[:land + 1]:
        others.observe(event)
    others.enter(fill.amount_out)
    state, path = fill.after, []
    for j in range(land + 1, len(events)):
        state = others.replay(state, events[j])
        path.append((events[j].block_time - events[land].block_time, liquidation(state, fill.amount_out, rate)[0]))
    return liquidation(fill.after, fill.amount_out, rate)[0], path, fill.amount_out, land


def test_forward_values_equal_an_independent_recomputation(archives):                              # noqa: F811
    checked = 0
    for timeline, k, actors in _all_points(archives, SYNTHETIC[:1]):
        row = study.probe(timeline, k, actors, MODEL)
        if not row['entered'] or row['outcome'] == 'migrated_unpriced':
            continue
        immediate, path, tokens, land = _by_hand(timeline, k, actors)
        assert (row['immediate'], row['tokens'], row['land_index']) == (immediate, tokens, land)
        assert row['cost'] == study.STAKE_LAMPORTS + 2 * MODEL.tx_cost
        for h in points.HORIZONS_S:
            landed = [mark for age, mark in path if age <= h + LATENCY_S]
            early = [mark for age, mark in path if age <= h]
            got = row['horizons'][str(h)]
            assert got['value'] == (landed[-1] if landed else immediate) and got['events'] == len(landed)
            assert got['value_no_latency'] == (early[-1] if early else immediate)
            assert got['best'] == max([immediate] + landed) and got['worst'] == min([immediate] + landed)
            assert got['worst'] <= got['value'] <= got['best'] and got['migrated'] is False
        checked += 1
    assert checked >= 8
    # the sale latency matters: an event of age 11 lands before a sale due at 10 s (latency 1 s) and moves its value
    row = study.probe(SYNTHETIC[0][0], 1, {}, MODEL)
    assert row['horizons']['10']['value'] != row['horizons']['10']['value_no_latency']
    assert row['horizons']['10']['events'] == 3 and row['horizons']['25']['value'] == row['horizons']['25']['value_no_latency']


def test_nothing_after_the_landing_of_the_longest_horizon_is_read(archives):                      # noqa: F811
    horizons, done = (2, 5), 0
    for timeline, k, actors in _all_points(archives, SYNTHETIC[:1]):
        events = timeline.events
        row = study.probe(timeline, k, actors, MODEL, horizons=horizons)
        if not row['entered']:
            continue
        limit = row['entry_block_time'] + max(horizons) + LATENCY_S
        keep = tuple(e for e in events if e.block_time <= limit)
        if len(keep) == len(events) or len(keep) <= row['land_index'] + 1:
            continue
        again = study.probe(replace(timeline, events=keep), k, actors, MODEL, horizons=horizons)
        assert again['horizons'] == row['horizons'] and again['immediate'] == row['immediate']
        done += 1
    assert done >= 3


def test_the_5s_point_is_the_entry_of_the_reference_policy(archives):                             # noqa: F811
    matched = 0
    for entry, archive in archives:
        reference = runner.run_pool(archive, v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=25, clock_exit=True),
                                    PARAMS, quote_mint=entry['quote_mint'])
        if reference['trade']['entry_index'] is None:
            continue
        timeline, facts, actors = _pool(archive)
        at5 = [k for k, labels in _points(timeline, facts) if ['age', 5] in labels]
        assert at5 == [reference['trade']['decision_index']]
        row = study.probe(timeline, at5[0], actors, MODEL)
        assert (row['land_index'], row['tokens']) == (reference['trade']['entry_index'], reference['trade']['tokens'])
        assert row['cost'] == reference['v3']['cost_lamports'] and row['immediate'] == reference['v3']['immediate_mark']
        matched += 1
    assert matched >= 2 and points.REFERENCE_CELL == 'age:5'


def test_a_curve_completed_before_the_sale_lands_is_not_credited():
    timeline = SYNTHETIC[1][0]
    row = study.probe(timeline, 1, {}, MODEL)
    assert row['entered'] and row['outcome'] == 'migrated_unpriced' and row['migrated_age_s'] == 48
    assert row['last_curve_value'] == row['horizons']['25']['value']      # the value BEFORE the completing buy
    for h, migrated in ((10, False), (25, False), (60, True), (120, True), (300, True)):
        got = row['horizons'][str(h)]
        assert got['migrated'] is migrated and (got['value'] is None) is migrated
    assert row['horizons']['60']['value_no_latency'] is None and row['horizons']['25']['events'] == 1
    assert table.probe_return(dict(row, pool='POOL'), '60') == -1.0
    assert table.probe_return(dict(row, pool='POOL'), '25') == pytest.approx(
        (row['horizons']['25']['value'] - row['cost'] - table.SPL_RENT_LAMPORTS) / (row['cost'] + table.SPL_RENT_LAMPORTS))
    # the landing counts: with a sale latency of 1 s a curve completed at h + 1 is not credited at h
    edge = _synthetic([(0, 'buy', 500_000_000, 'a'), (5, 'buy', 300_000_000, 'b'), (11, 'buy', 'ALMOST_ALL', 'w'),
                       (3, 'sell', 10 ** 9, 'a')])
    got = study.probe(edge, 1, {}, MODEL)
    assert got['migrated_age_s'] == 11 and got['horizons']['10']['migrated'] is True
    assert got['horizons']['10']['value_no_latency'] is not None


def test_a_buy_that_would_cross_the_boundary_is_refused_not_valued():
    timeline = _synthetic([(0, 'buy', 500_000_000, 'a'), (5, 'buy', 'ALMOST_ALL', 'whale'), (3, 'sell', 10 ** 9, 'a')])
    row = study.probe(timeline, 1, {}, MODEL)
    assert row['entered'] is False and any('entry_refused' in note for note in row['notes'])
    assert 'horizons' not in row and 'immediate' not in row


# --- the study: segments, window, population -----------------------------------------------------

def test_the_study_reads_discovery_segments_only_and_validation_once_per_hypothesis(visible):     # noqa: F811
    directory, sha = visible
    document = study.study(directory, sha)
    assert document['schema'] == 'statelab-rows-v2' and document['statelab_version'] == '0.2.1'
    assert document['segments'] == ['exploration', 'train'] and document['confirm_validation'] is None
    assert {row['segment'] for row in document['rows']} <= {'exploration', 'train'} and document['rows']
    assert document['flags'] == dict(strategy_evaluated=False, trial_registered=False, holdout_read=False,
                                     w1_data_read=False, promotion_allowed=False, financial_order_submitted=False)
    assert study.study(directory, sha)['rows_sha256'] == document['rows_sha256']           # deterministic
    for bad in (('validation',), ('exploration', 'validation')):
        with pytest.raises(ValueError, match='validation_is_read_once'):
            study.study(directory, sha, segments=bad)
    with pytest.raises(ValueError, match='reads_validation_only'):
        study.study(directory, sha, segments=('train', 'validation'), confirm_validation='H-x')
    with pytest.raises(ValueError, match='unknown_segment'):
        study.study(directory, sha, segments=('holdout',))
    confirmation = study.study(directory, sha, segments=('validation',), confirm_validation='H-x')
    assert {row['segment'] for row in confirmation['rows']} == {'validation'}
    with pytest.raises(Exception):
        study.study(directory, '0' * 64)                                                    # not the anchored pack
    json.dumps(document, allow_nan=False)
    row = next(r for r in document['rows'] if r['entered'])
    assert {'age_s', 'progress_ppm', 'net_flow_10s_lamports', 'fee_rate_ppm_causal', 'top1_token_share'} <= set(row['features'])
    constants, counts = document['constants'], document['counts']
    assert constants['sale_latency_s'] == 1 and constants['k_grid'] == 90 and constants['reference_cell'] == 'age:5'
    assert constants['placebo'] == dict(cell='placebo:0', max_age_s=120, salt='v1', rule='frozen RandomEntry.target_age')
    assert counts['k'] == 0 and counts['cells_meeting_floors'] == []      # a handful of probes: nothing may be computed
    assert all(set(item) == {'probes', 'creators', 'meets_floors'} for item in counts['labels'].values())
    slow = study.study(directory, sha, latency_slots=10)
    assert slow['constants']['sale_latency_s'] == 3 and slow['constants']['latency_slots'] == 10


def test_a_probe_whose_horizon_leaves_the_window_is_dropped(archives):                            # noqa: F811
    tested = 0
    for entry, archive in archives:
        rows, info = study.pool_rows(archive, entry, 'train', PARAMS, None)
        if rows is None:
            assert info and all(type(reason) is str for reason in info)      # excluded pools carry their reasons
            continue
        assert info == 0 and rows
        slots = sorted(row['decision_slot'] for row in rows)
        none, dropped = study.pool_rows(archive, entry, 'train', PARAMS, slots[0] - 1)
        assert none == [] and dropped == len(rows)
        some, dropped = study.pool_rows(archive, entry, 'train', PARAMS, slots[0])
        assert len(some) + dropped == len(rows) and some == rows[:len(some)]
        tested += 1
    assert tested >= 2
    assert study.window_cutoff(dict(entry_cutoff_slot=1_000_000, window_slot_max=1_001_000), {}, PARAMS) < 1_000_000
    assert study.window_cutoff({}, {}, PARAMS) is None
    with pytest.raises(ValueError, match='invalid_collection_window'):
        study.window_cutoff(dict(entry_cutoff_slot=5, window_slot_max=5), {}, PARAMS)


def test_a_pool_whose_creator_is_not_signed_gives_no_row(archives, monkeypatch):                  # noqa: F811
    entry, archive = archives[0]
    real = hrr.creation_facts
    monkeypatch.setattr(hrr, 'creation_facts', lambda a: dict(real(a), signed_creator_verified=False))
    assert study.pool_rows(archive, entry, 'train', PARAMS, None) == (None, ['creator_not_signed'])


# --- the declared table --------------------------------------------------------------------------

COST, RENT = 100_210_000, table.SPL_RENT_LAMPORTS


def _row(pool, labels, value, *, immediate=96_000_000, entered=True, migrated=False, no_latency=None):
    horizons = {str(h): dict(value=None if migrated else value, value_no_latency=value if no_latency is None else no_latency,
                             events=1, best=max(value, immediate), best_age_s=1, worst=min(value, immediate),
                             migrated=migrated) for h in points.HORIZONS_S}
    return dict(pool=pool, creator='c' + pool, segment='train', labels=labels, entered=entered, cost=COST,
                immediate=immediate, horizons=horizons)


def _document(rows):
    return dict(schema='statelab-rows-v2', rows=rows, rows_sha256='x', pack_manifest_sha256='m', segments=['train'],
                constants=dict(horizons_s=list(points.HORIZONS_S)))


def _population(good=40, flat=40):
    """``good`` pools where the age:5 probe wins (+20 %) and ``flat`` pools where it only pays its costs."""
    rows = []
    for i in range(good + flat):
        name = 'p%03d' % i
        rows.append(_row(name, [['age', 5]], round(COST * 1.20) if i < good else 96_000_000))
        rows.append(_row(name, [['placebo', 0]], 96_000_000))
        if i < 12:
            rows.append(_row(name, [['progress', 50_000]], COST * 3))             # 12 probes: below the floor
    return rows


def test_the_table_computes_only_cells_above_the_floors_and_needs_the_declared_k():
    document = _document(_population())
    with pytest.raises(ValueError, match='declared_k_is_not_the_number_of_cells_this_table_computes:5'):
        table.table(document, declared_k=90, n_boot=200)
    with pytest.raises(ValueError, match='declared_k'):
        table.table(document, declared_k=None, n_boot=200)
    out = table.table(document, declared_k=5, n_boot=2_000)
    assert list(out['cells']) == ['age:5'] and out['labels_not_computed'] == ['progress:50000']
    assert (out['k'], out['k_grid'], out['trials_added_to_n']) == (5, 90, 5) and 'ASSUMED' in out['rent_basis']
    c = out['cells']['age:5']['25']
    win, flat = (round(COST * 1.20) - COST - RENT) / (COST + RENT), (96_000_000 - COST - RENT) / (COST + RENT)
    assert (c['probes'], c['creators'], c['migrated']) == (80, 80, 0)
    assert c['mean_r'] == pytest.approx((win + flat) / 2) and c['share_r_positive'] == 0.5
    assert c['vs_placebo']['pairs'] == 80 and c['vs_placebo']['mean'] == pytest.approx((win - flat) / 2)
    assert c['vs_reference']['mean'] == 0.0                              # age:5 is the reference itself
    assert c['mean_instant_cost'] == pytest.approx((96_000_000 - COST) / COST)
    assert c['mean_drift'] == pytest.approx((round(COST * 1.20) - 96_000_000) / COST / 2)
    assert c['sensitivities']['mean_r_rent_recovered'] > c['mean_r']
    assert c['screening'] == dict(mean_r_positive=True, beats_placebo=True, bh_q10_of_90=True) and c['retained'] is True
    assert out['retained'] == [['age:5', str(h)] for h in points.HORIZONS_S]
    assert out['placebo_baseline']['25']['mean_r'] == pytest.approx(flat)
    assert '| age:5 | 25 | 80 | 80 |' in table.markdown(out) and 'OUI' in table.markdown(out)
    with pytest.raises(ValueError):
        table.table(dict(document, schema='statelab-rows-v1'), declared_k=5)


def test_a_cell_is_retained_only_if_every_declared_condition_holds():
    # positive against the placebo but not after costs and rent: not retained
    rows = []
    for i in range(60):
        name = 'q%03d' % i
        rows += [_row(name, [['age', 5]], 99_000_000), _row(name, [['placebo', 0]], 90_000_000)]
    c = table.table(_document(rows), declared_k=5, n_boot=500)['cells']['age:5']['25']
    assert c['screening'] == dict(mean_r_positive=False, beats_placebo=True, bh_q10_of_90=False) and c['retained'] is False
    # profitable but no better than the placebo (a market-wide move, no selection): not retained
    rows = []
    for i in range(60):
        name = 'r%03d' % i
        rows += [_row(name, [['age', 5]], 120_000_000), _row(name, [['placebo', 0]], 120_000_000)]
    c = table.table(_document(rows), declared_k=5, n_boot=500)['cells']['age:5']['25']
    assert c['screening']['mean_r_positive'] and not c['screening']['beats_placebo'] and c['retained'] is False
    # one huge winner among losers: the mean is positive but the bootstrap p-value fails the BH step
    rows = []
    for i in range(60):
        name = 's%03d' % i
        rows += [_row(name, [['age', 5]], COST * 40 if i == 0 else 80_000_000), _row(name, [['placebo', 0]], 70_000_000)]
    c = table.table(_document(rows), declared_k=5, n_boot=2_000)['cells']['age:5']['25']
    assert c['mean_r'] > 0 and c['screening']['bh_q10_of_90'] is False and c['retained'] is False
    # a migrated probe counts -1 and an unknown token class is refused, never guessed
    rows = [_row('m%03d' % i, [['age', 5]], 120_000_000, migrated=i < 30) for i in range(60)]
    c = table.table(_document(rows), declared_k=5, n_boot=0)['cells']['age:5']['25']
    assert c['migrated'] == 30 and c['mean_r'] == pytest.approx(((120_000_000 - COST - RENT) / (COST + RENT) - 1) / 2)
    assert c['vs_placebo'] == dict(pairs=0, mean=None, ci95=None) and c['retained'] is False
    census = dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[], rows=[])
    with pytest.raises(ValueError, match='token_class_unknown'):
        table.table(_document(rows), census, declared_k=5, n_boot=0)


def test_benjamini_hochberg_uses_the_whole_grid_as_the_family():
    p = {('a', '10'): 0.0005, ('b', '10'): 0.002, ('c', '10'): 0.004, ('d', '10'): 0.2, ('e', '10'): None}
    assert table.benjamini_hochberg(p, 90) == {('a', '10'), ('b', '10')}       # thresholds 0.0011, 0.0022, 0.0033
    assert table.benjamini_hochberg(p, 4) == {('a', '10'), ('b', '10'), ('c', '10')}
    assert table.benjamini_hochberg({('a', '10'): 0.0012}, 90) == set()
    assert table.benjamini_hochberg({}, 90) == set()


def test_the_placebo_is_drawn_once_even_when_many_events_follow_the_target():
    for name in ('POOL', 'POOL2', 'POOL3'):
        steps = [(0, 'buy', 10 ** 8, 'a')] + [(3, 'buy', 10 ** 8, 'b%d' % i) for i in range(45)]     # one event every 3 s
        timeline = _synthetic(steps, pool=name)
        target = points.placebo_target_age(name)
        got = [(k, timeline.events[k].block_time - timeline.events[0].block_time)
               for k, labels in points.decision_points(timeline.events, timeline.events[0].block_time, name)
               if ['placebo', 0] in labels]
        assert len(got) == 1 and target <= got[0][1] < target + 3


def test_pairs_are_made_by_pool_and_only_where_both_probes_exist():
    rows = [_row('p%03d' % i, [['age', 5]], 100_000_000 + 1_000_000 * i) for i in range(40)]
    rows += [_row('p%03d' % i, [['placebo', 0]], 90_000_000 + 3_000_000 * i) for i in reversed(range(10, 40))]
    c = table.table(_document(rows), declared_k=5, n_boot=0)['cells']['age:5']['25']
    expected = [(100_000_000 + 1_000_000 * i - (90_000_000 + 3_000_000 * i)) / (COST + RENT) for i in range(10, 40)]
    assert c['vs_placebo']['pairs'] == 30 and c['vs_placebo']['mean'] == pytest.approx(sum(expected) / 30)
    assert c['vs_reference']['pairs'] == 40 and c['probes'] == 40


def test_beating_the_placebo_needs_the_lower_bound_not_the_mean():
    rows = []
    for i in range(60):
        name = 't%03d' % i
        rows += [_row(name, [['age', 5]], COST * 40 if i == 0 else 120_000_000), _row(name, [['placebo', 0]], 120_000_000)]
    c = table.table(_document(rows), declared_k=5, n_boot=2_000)['cells']['age:5']['25']
    assert c['vs_placebo']['mean'] > 0 and c['vs_placebo']['ci95'][0] == 0.0       # one pool carries the whole difference
    assert c['screening']['mean_r_positive'] and c['screening']['beats_placebo'] is False and c['retained'] is False


def test_the_multiplicity_family_is_the_whole_grid_not_the_computed_cells():
    rows = []
    for i in range(60):                                         # 39 winners (+30 %) and 21 losers (-30 %) after costs
        name = 'u%03d' % i
        value = round((COST + RENT) * (1.30 if i % 20 < 13 else 0.70))
        rows += [_row(name, [['age', 5]], value), _row(name, [['placebo', 0]], round((COST + RENT) * 0.5))]
    c = table.table(_document(rows), declared_k=5, n_boot=10_000)['cells']['age:5']['25']
    assert c['mean_r'] == pytest.approx(0.09, abs=1e-6) and 0.0056 < c['p_one_sided'] < 0.02
    # with the 5 computed cells as the family this p-value would pass (0.10 x 5 / 5); with the 90 grid cells it fails
    assert c['screening'] == dict(mean_r_positive=True, beats_placebo=True, bh_q10_of_90=False) and c['retained'] is False


def test_a_placebo_under_the_floors_is_said_automatically():                                       # R02 E-S1
    rows = []
    for i in range(60):
        name = 'v%03d' % i
        rows.append(_row(name, [['age', 5]], 99_000_000))
        if i < 28:
            rows.append(_row(name, [['placebo', 0]], 90_000_000))                  # 28 probes: under the floor of 30
    thin = table.table(_document(rows), declared_k=5, n_boot=0)
    assert thin['placebo_below_floors'] is True and thin['placebo_sample'] == dict(probes=28, creators=28)
    assert any('PLACEBO BELOW THE SAMPLE FLOORS' in note and '28 probes' in note for note in thin['notes'])
    assert 'PLACEBO SOUS PLANCHER sur ce pack (28 sondes, 28 créateurs)' in table.markdown(thin)
    assert thin['cells']['age:5']['25']['vs_placebo']['pairs'] == 28               # still computed on what exists
    full = table.table(_document(_population()), declared_k=5, n_boot=0)
    assert full['placebo_below_floors'] is False and 'SOUS PLANCHER' not in table.markdown(full)
    assert not any('PLACEBO BELOW' in note for note in full['notes'])
