"""statelab: causal points, exact forward values against an independent recomputation, segment guards."""
from dataclasses import replace
import json

import pytest

from bot.market.collector import summarize
from bot.market.launchlab_curve import buy_exact_in
from bot.market.replay import causal_fee_rate
from bot.master_v2 import policies as v2
from bot.master_v2.harness import ExitRule
from bot.p4 import historical_research_replay as hrr
from v3lab import plan, runner
from v3lab.tests.test_v3lab import archives, visible            # noqa: F401  (fixtures)
from v4sim.engine import landing_index
from v4sim.io import actors_from_archive
from v4sim.ledger import Others
from v4sim.valuation import liquidation

from statelab import points, study, table

PARAMS = hrr.ReplayParams(**plan.REPLAY)
MODEL = PARAMS.execution_model()


def _pool(archive):
    summary, timeline = summarize(archive)
    timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    return timeline, facts, actors_from_archive(archive, timeline.events)[0]


def test_the_grid_is_causal_whole_transaction_and_first_crossing(archives):                      # noqa: F811
    seen = 0
    for _entry, archive in archives:
        timeline, facts, _actors = _pool(archive)
        events, created = timeline.events, facts['creation_block_time']
        full = points.decision_points(events, created)
        for k, labels in full:
            assert points.whole(events, k)
            for kind, level in labels:
                age, progress = events[k].block_time - created, events[k].state_after().progress_ppm
                if kind == 'age':
                    assert level <= age <= level + points.MAX_LATENESS_S
                    assert not any(points.whole(events, j) and events[j].block_time - created >= level for j in range(k))
                else:
                    assert progress >= level
                    assert all(events[j].state_after().progress_ppm < level for j in range(k) if points.whole(events, j))
        flat = [(kind, level) for _k, labels in full for kind, level in labels]
        assert len(flat) == len(set(flat))                                    # each label at most once per pool
        # the labels of an event never depend on what comes after it
        for cut in [k for k in range(len(events)) if points.whole(events, k)]:
            assert points.decision_points(events[:cut + 1], created) == [p for p in full if p[0] <= cut]
        seen += len(full)
    assert seen >= 6


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
    for _entry, archive in archives:
        timeline, facts, actors = _pool(archive)
        for k, _labels in points.decision_points(timeline.events, facts['creation_block_time']):
            row = study.probe(timeline, k, actors, MODEL)
            if not row['entered'] or row['outcome'] == 'migrated_unpriced':
                continue
            immediate, path, tokens, land = _by_hand(timeline, k, actors)
            assert (row['immediate'], row['tokens'], row['land_index']) == (immediate, tokens, land)
            assert row['cost'] == study.STAKE_LAMPORTS + 2 * MODEL.tx_cost
            for h in study.HORIZONS_S:
                seen = [mark for age, mark in path if age <= h]
                late = [mark for age, mark in path if age <= h + 1]
                got = row['horizons'][str(h)]
                assert got['value'] == (seen[-1] if seen else immediate) and got['events'] == len(seen)
                assert got['value_late'] == (late[-1] if late else immediate)
                assert got['best'] == max([immediate] + seen) and got['worst'] == min([immediate] + seen)
                assert got['worst'] <= got['value'] <= got['best'] and got['migrated'] is False
            checked += 1
    assert checked >= 6


def test_nothing_after_the_longest_horizon_is_read(archives):                                     # noqa: F811
    """Removing every event later than the longest horizon (plus the sale allowance) changes no value."""
    horizons, done = (2, 5), 0
    for _entry, archive in archives:
        timeline, facts, actors = _pool(archive)
        events = timeline.events
        for k, _labels in points.decision_points(events, facts['creation_block_time']):
            row = study.probe(timeline, k, actors, MODEL, horizons=horizons)
            if not row['entered']:
                continue
            limit = row['entry_block_time'] + max(horizons) + study.SALE_LATENCY_ALLOWANCE_S
            keep = tuple(e for e in events if e.block_time <= limit)
            if len(keep) == len(events) or len(keep) <= row['land_index'] + 1:
                continue
            again = study.probe(replace(timeline, events=keep), k, actors, MODEL, horizons=horizons)
            assert again['horizons'] == row['horizons'] and again['immediate'] == row['immediate']
            assert any(row['horizons'][str(h)]['events'] for h in horizons)
            done += 1
    assert done >= 2


def test_the_5s_point_is_the_entry_of_the_reference_policy(archives):                             # noqa: F811
    """Same decision, same fill and same instant round trip as V3-01 (fixed 5 s delay) on the frozen engine."""
    matched = 0
    for entry, archive in archives:
        reference = runner.run_pool(archive, v2.FixedDelay(delay_s=5), ExitRule(max_hold_s=25, clock_exit=True),
                                    PARAMS, quote_mint=entry['quote_mint'])
        if reference['trade']['entry_index'] is None:
            continue
        timeline, facts, actors = _pool(archive)
        at5 = [k for k, labels in points.decision_points(timeline.events, facts['creation_block_time'])
               if ['age', 5] in labels]
        assert at5 == [reference['trade']['decision_index']]
        row = study.probe(timeline, at5[0], actors, MODEL)
        assert (row['land_index'], row['tokens']) == (reference['trade']['entry_index'], reference['trade']['tokens'])
        assert row['cost'] == reference['v3']['cost_lamports']
        assert row['immediate'] == reference['v3']['immediate_mark']
        matched += 1
    assert matched >= 2


def test_the_study_reads_discovery_segments_only_and_validation_once_per_hypothesis(visible):     # noqa: F811
    directory, sha = visible
    document = study.study(directory, sha)
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
    assert confirmation['confirm_validation'] == 'H-x'
    with pytest.raises(Exception):
        study.study(directory, '0' * 64)                                                    # not the anchored pack
    json.dumps(document, allow_nan=False)
    row = next(r for r in document['rows'] if r['entered'])
    assert {'age_s', 'progress_ppm', 'net_flow_10s_lamports', 'fee_rate_ppm_causal', 'top1_token_share'} <= set(row['features'])


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
        assert len(some) + dropped == len(rows) and len(some) == sum(slot == slots[0] for slot in slots)
        assert some == rows[:len(some)]
        tested += 1
    assert tested >= 2
    window = study.window_cutoff(dict(entry_cutoff_slot=1_000_000, window_slot_max=1_001_000), {}, PARAMS)
    assert window < 1_000_000                                    # 1,000 slots cannot hold a 301 s horizon
    assert study.window_cutoff({}, {}, PARAMS) is None
    with pytest.raises(ValueError, match='invalid_collection_window'):
        study.window_cutoff(dict(entry_cutoff_slot=5, window_slot_max=5), {}, PARAMS)


def _row(pool, creator, labels, values, *, cost=100_210_000, immediate=96_000_000, entered=True, migrated=()):
    horizons = {str(h): dict(value=None if h in migrated else v, value_late=None if h in migrated else v - 1_000,
                             events=1, best=max(v, immediate), best_age_s=1, worst=min(v, immediate),
                             migrated=h in migrated) for h, v in zip(study.HORIZONS_S, values)}
    return dict(pool=pool, creator=creator, segment='train', labels=labels, entered=entered, cost=cost,
                immediate=immediate, horizons=horizons)


def test_the_table_is_exact_on_hand_made_rows():
    rows = [_row('a', 'c1', [['age', 5], ['progress', 50_000]], [110_210_000] * 5),
            _row('b', 'c2', [['age', 5]], [90_210_000] * 5),
            _row('c', 'c2', [['age', 5]], [100_210_000] * 5, migrated=(300,)),
            _row('d', 'c3', [['age', 5]], [0] * 5, entered=False)]
    document = dict(schema='statelab-rows-v1', rows=rows, rows_sha256='x', pack_manifest_sha256='m',
                    segments=['train'], constants=dict(horizons_s=list(study.HORIZONS_S)))
    out = table.table(document, n_boot=0)
    assert list(out['cells']) == ['age:5', 'progress:50000'] and 'ASSUMED' in out['rent_basis']
    c = out['cells']['age:5']['25']
    assert (c['rows'], c['entered'], c['priced'], c['migrated'], c['creators']) == (4, 3, 3, 0, 2)
    assert c['mean_r'] == pytest.approx((10_000_000 - 10_000_000 + 0) / 3 / 100_210_000)
    assert c['mean_cost0'] == pytest.approx(-4_210_000 / 100_210_000)
    assert c['mean_drift'] == pytest.approx(c['mean_r'] - c['mean_cost0'])
    assert c['share_r_positive'] == pytest.approx(1 / 3) and c['small_sample'] is True
    rent = table.SPL_RENT_LAMPORTS
    assert c['mean_r_with_rent'] == pytest.approx(sum((v - 100_210_000 - rent) / (100_210_000 + rent)
                                                    for v in (110_210_000, 90_210_000, 100_210_000)) / 3)
    assert c['mean_sale_latency_effect'] == pytest.approx(-1_000 / 100_210_000)
    assert c['hindsight_best_mean'] == pytest.approx((10_000_000 - 4_210_000 + 0) / 3 / 100_210_000)
    late = out['cells']['age:5']['300']
    assert (late['priced'], late['migrated']) == (2, 1)
    assert late['mean_r'] == pytest.approx(0.0) and late['mean_r_migrated_lost'] == pytest.approx(-1 / 3)
    assert out['cells']['progress:50000']['10']['priced'] == 1
    assert '| age:5 * | 25 | 3 | 2 |' in table.markdown(out)
    with pytest.raises(ValueError):
        table.table(dict(document, schema='other'))


# --- a synthetic pool that completes its curve after our entry (no real data) -------------------

def _synthetic(steps, rate=12_500):
    """PoolTimeline from ``[(seconds, side, amount, actor)]`` on the frozen curve (start of a real-shaped curve)."""
    from bot.market.launchlab_curve import CurveState, sell_exact_in
    from bot.market.launchlab_events import TradeEvent
    from bot.market.pool_timeline import PoolTimeline
    from v4sim.io import EVENT_FIELDS
    state = CurveState(1_073_025_605_596_382, 30_000_852_951, 0, 0, 793_100_000_000_000)
    events, slot, time = [], 400_000_000, 1_790_000_000
    for index, step in enumerate(steps):
        seconds, side, amount, actor = step[:4]
        slot, time = slot + 5 * max(seconds, 1), time + seconds
        if amount == 'ALMOST_ALL':                          # a buy that leaves 10^9 atomic tokens on the curve
            out = state.remaining_base - 10 ** 9
            net = -(-out * state.quote_reserve // (state.base_reserve - out))
            amount = -(-net * 1_000_000 // (1_000_000 - rate)) + 2
            while buy_exact_in(state, amount, rate).amount_out > state.remaining_base - 10 ** 6:
                amount -= 1_000
        fill = buy_exact_in(state, amount, rate) if side == 'buy' else sell_exact_in(state, amount, rate)
        row = dict(signature=step[4] if len(step) > 4 else 'sig%04d' % index, slot=slot, block_time=time, event_index=0, fee_payer=actor, pool='POOL',
                   side=side, exact_in=True, pool_status=0, total_base_sell=state.total_base_sell,
                   virtual_base=state.virtual_base, virtual_quote=state.virtual_quote,
                   real_base_before=state.real_base, real_quote_before=state.real_quote,
                   real_base_after=fill.after.real_base, real_quote_after=fill.after.real_quote,
                   amount_in=fill.amount_in, amount_out=fill.amount_out, protocol_fee=fill.fee, platform_fee=0,
                   creator_fee=0, share_fee=0)
        events.append(TradeEvent(**{name: row[name] for name in EVENT_FIELDS}))
        state = fill.after
    return PoolTimeline('POOL', tuple(events), ())


def test_a_curve_completed_within_the_horizon_is_not_credited():
    timeline = _synthetic([(0, 'buy', 500_000_000, 'a'), (5, 'buy', 300_000_000, 'b'), (8, 'buy', 200_000_000, 'c'),
                           (40, 'buy', 'ALMOST_ALL', 'whale'), (10, 'sell', 10 ** 9, 'a')])
    row = study.probe(timeline, 1, {}, MODEL)
    assert row['entered'] and row['outcome'] == 'migrated_unpriced'
    assert row['last_curve_value'] == row['horizons']['25']['value']      # the value BEFORE the completing buy
    assert row['migrated_age_s'] == 48                      # entry lands behind event 1; the whale buys 48 s later
    for h, migrated in ((10, False), (25, False), (60, True), (120, True), (300, True)):
        got = row['horizons'][str(h)]
        assert got['migrated'] is migrated and (got['value'] is None) is migrated
    assert row['horizons']['25']['events'] == 1 and row['horizons']['25']['value'] > row['immediate']
    assert row['horizons']['10']['value_late'] == row['horizons']['10']['value']
    document = dict(schema='statelab-rows-v1', rows_sha256='x', pack_manifest_sha256='m', segments=['train'],
                    constants=dict(horizons_s=list(study.HORIZONS_S)),
                    rows=[dict(row, pool='POOL', creator='c', segment='train', labels=[['age', 5]])])
    cells = table.table(document, n_boot=0)['cells']['age:5']
    assert cells['60']['migrated'] == 1 and cells['60']['mean_r'] is None and cells['60']['mean_r_migrated_lost'] == -1.0
    assert cells['25']['priced'] == 1 and cells['25']['mean_r'] == pytest.approx((row['last_curve_value'] - row['cost']) / row['cost'])


def test_a_buy_that_would_cross_the_boundary_is_refused_not_valued():
    timeline = _synthetic([(0, 'buy', 500_000_000, 'a'), (5, 'buy', 'ALMOST_ALL', 'whale'), (3, 'sell', 10 ** 9, 'a')])
    row = study.probe(timeline, 1, {}, MODEL)
    assert row['entered'] is False and any('entry_refused' in note for note in row['notes'])
    assert 'horizons' not in row and 'immediate' not in row


def test_a_decision_waits_for_the_whole_transaction_and_a_silent_pool_gives_no_late_point():
    timeline = _synthetic([(0, 'buy', 500_000_000, 'a', 'tx1'), (0, 'buy', 300_000_000, 'a', 'tx1'),
                           (2, 'buy', 200_000_000, 'b'), (98, 'buy', 100_000_000, 'c'), (30, 'sell', 10 ** 9, 'a')])
    events = timeline.events
    created = events[0].block_time
    got = dict(points.decision_points(events, created))
    assert 0 not in got and got[1] == [['age', 0]]              # event 0 is mid-transaction: never a decision
    assert 2 not in got and 3 not in got                         # age 100: more than 30 s late for 5, 15, 30 and 60
    assert got[4] == [['age', 120]]                              # age 130: within 30 s of the 120 s target
    assert sorted(got) == [1, 4]


def test_a_pool_whose_creator_is_not_signed_gives_no_row(archives, monkeypatch):                  # noqa: F811
    entry, archive = archives[0]
    real = hrr.creation_facts
    monkeypatch.setattr(hrr, 'creation_facts', lambda a: dict(real(a), signed_creator_verified=False))
    assert study.pool_rows(archive, entry, 'train', PARAMS, None) == (None, ['creator_not_signed'])
