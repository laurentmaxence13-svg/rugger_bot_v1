"""statelab.cohorts: cohorts fixed at the decision, exact identity with the curve, discovery only."""
import json

import pytest

from bot.p4 import historical_research_replay as hrr
from v3lab import plan
from v3lab.tests.test_v3lab import archives, visible            # noqa: F401  (fixtures)

from statelab import cohorts, points
from statelab.tests.test_statelab import _pool, _points, _synthetic

PARAMS = hrr.ReplayParams(**plan.REPLAY)
ACTOR = lambda event: event.fee_payer                           # noqa: E731

# creator 'dev' and sniper 'snp' buy in the creation slot; 'bob' buys later; decision at event 2;
# afterwards the sniper and the creator sell, a newcomer buys.
TIMELINE = _synthetic([(0, 'buy', 500_000_000, 'dev', 'tx0'), (0, 'buy', 400_000_000, 'snp', 'tx1'),
                       (6, 'buy', 300_000_000, 'bob'), (4, 'sell', 5 * 10 ** 12, 'snp'), (3, 'buy', 200_000_000, 'new1'),
                       (20, 'sell', 8 * 10 ** 12, 'dev'), (100, 'sell', 10 ** 12, 'bob')])
EVENTS = TIMELINE.events
CREATION_SLOT = EVENTS[1].slot - 1                 # the builder spaces events by 5 slots: the sniper lands in 'creation + 1'
FACTS = dict(creator='dev', creation_slot=CREATION_SLOT, creation_block_time=EVENTS[0].block_time)


def test_cohorts_are_fixed_at_the_decision_from_the_past_only():
    who, held = cohorts.cohort_state(EVENTS, 2, 'dev', CREATION_SLOT, ACTOR)
    assert who == dict(dev='creator', snp='early', bob='before')
    assert held == dict(creator=EVENTS[0].amount_out, early=EVENTS[1].amount_out, before=EVENTS[2].amount_out)
    # nothing after the decision is read: the same answer on the truncated history
    assert cohorts.cohort_state(EVENTS[:3], 2, 'dev', CREATION_SLOT, ACTOR) == (who, held)
    # a buyer of the second slot is early, a later one is not; the creator stays the creator
    late = _synthetic([(0, 'buy', 10 ** 8, 'dev'), (1, 'buy', 10 ** 8, 'x'), (1, 'buy', 10 ** 8, 'dev')])
    who, _held = cohorts.cohort_state(late.events, 2, 'dev', late.events[0].slot, ACTOR)
    assert who == dict(dev='creator', x='before')               # slots advance by 5 per second in the builder


def test_flows_by_cohort_are_exact_on_a_hand_made_pool():
    row = cohorts.point_flows(EVENTS, 2, FACTS, {}, PARAMS.latency_slots)
    assert row['land_index'] == 2 and row['windows']['latency']['curve_change'] == 0
    circulating = EVENTS[2].state_after().real_base
    assert row['held_share']['early'] == EVENTS[1].amount_out / circulating
    assert sum(row['held_share'].values()) == pytest.approx(1.0)
    delta = lambda i: EVENTS[i].real_quote_after - EVENTS[i].real_quote_before     # noqa: E731
    w10 = row['windows']['10']                                   # ages 4 and 7: the sniper sells, a newcomer buys
    assert w10['cohorts']['early'] == dict(net=delta(3), bought=0, sold=-delta(3), trades=1)
    assert w10['cohorts']['new'] == dict(net=delta(4), bought=delta(4), sold=0, trades=1)
    assert w10['cohorts']['creator']['trades'] == 0 and w10['curve_change'] == delta(3) + delta(4)
    w60 = row['windows']['60']                                   # age 27: the creator sells
    assert w60['cohorts']['creator']['net'] == delta(5) < 0 and w60['curve_change'] == delta(3) + delta(4) + delta(5)
    assert row['windows']['120']['curve_change'] == w60['curve_change']            # bob sells at age 127
    assert row['windows']['300']['cohorts']['before']['net'] == delta(6)
    # the actor mapping of the simulator is honoured: the newcomer's trade is attributed to its token owner
    mapped = cohorts.point_flows(EVENTS, 2, FACTS, {EVENTS[4].key: 'snp'}, PARAMS.latency_slots)
    assert mapped['windows']['10']['cohorts']['early']['net'] == delta(3) + delta(4)
    assert mapped['windows']['10']['cohorts']['new']['trades'] == 0


def test_the_identity_holds_on_real_shaped_pools_and_windows_are_nested(archives):                # noqa: F811
    seen = 0
    for _entry, archive in archives:
        timeline, facts, actors = _pool(archive)
        for k, _labels in _points(timeline, facts):
            row = cohorts.point_flows(timeline.events, k, facts, actors, PARAMS.latency_slots)
            trades = [sum(c['trades'] for c in row['windows'][str(h)]['cohorts'].values()) for h in points.HORIZONS_S]
            assert trades == sorted(trades)
            for window in row['windows'].values():
                assert sum(c['net'] for c in window['cohorts'].values()) == window['curve_change']
                assert all(c['net'] == c['bought'] - c['sold'] for c in window['cohorts'].values())
            seen += 1
    assert seen >= 6


def test_a_broken_ledger_is_refused(monkeypatch):
    real = cohorts._window

    def lossy(events, start, stop, who, actor_of):
        flows = real(events, start, stop, who, actor_of)
        flows['new']['net'] += 1
        return flows
    monkeypatch.setattr(cohorts, '_window', lossy)
    with pytest.raises(ValueError, match='cohort_flows_do_not_add_up'):
        cohorts.point_flows(EVENTS, 2, FACTS, {}, PARAMS.latency_slots)


def test_the_study_reads_discovery_only_and_tabulates_labels_above_the_floors(visible):           # noqa: F811
    directory, sha = visible
    document = cohorts.study(directory, sha)
    assert document['segments'] == ['exploration', 'train'] and document['rows'] > 0 and document['table'] == {}
    assert document['flags'] == dict(strategy_evaluated=False, rule_pnl_computed=False, trial_registered=False,
                                     holdout_read=False, w1_data_read=False)
    assert cohorts.study(directory, sha)['rows_sha256'] == document['rows_sha256']
    json.dumps(document, allow_nan=False)
    rows = []
    for i in range(40):
        row = cohorts.point_flows(EVENTS, 2, FACTS, {}, PARAMS.latency_slots)
        rows.append(dict(row, pool='p%d' % i, creator='c%d' % i, segment='train', labels=[['age', 5], ['placebo', 0]]))
    rows.append(dict(rows[0], pool='q', labels=[['age', 15]]))
    out = cohorts.table(rows)
    assert list(out) == ['age:5']                                # the placebo and the thin label are not tabulated
    block = out['age:5']
    assert block['probes'] == 40 and block['mean_held_share']['early'] == pytest.approx(rows[0]['held_share']['early'])
    w = block['windows']['60']
    assert w['share_curve_down'] == 1.0 and w['share_no_trade'] == 0.0
    assert w['mean_net_sol']['new'] > 0 > w['mean_net_sol']['early'] and w['mean_net_sol']['creator'] < 0
    assert sum(w['share_of_gross_sales'].values()) == pytest.approx(1.0) and w['share_of_gross_sales']['new'] == 0
    assert w['share_of_gross_buys'] == dict(creator=0.0, early=0.0, before=0.0, new=1.0)
    assert block['windows']['latency']['share_no_trade'] == 1.0
    text = cohorts.markdown(dict(document, table=out))
    assert '| age:5 | 60 |' in text and 'Qui détient les tokens' in text


def test_validation_pools_are_never_opened_for_flows(visible, monkeypatch):                       # noqa: F811
    directory, sha = visible
    seen, real = [], cohorts.pool_rows

    def spy(archive, entry, segment, *rest):
        seen.append(segment)
        return real(archive, entry, segment, *rest)
    monkeypatch.setattr(cohorts, 'pool_rows', spy)
    cohorts.study(directory, sha)
    assert sorted(seen) == ['exploration', 'train']
