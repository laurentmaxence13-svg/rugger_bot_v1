"""statelab.exits: each rule against a by-hand computation on synthetic pools, the clock reference against
statelab.study, causality, and the declared table."""
from dataclasses import replace
import json

import pytest

from bot.p4 import historical_research_replay as hrr
from v3lab import plan
from v3lab.tests.test_v3lab import archives, visible            # noqa: F401  (fixtures)

from statelab import exits, points, study
from statelab.tests.test_statelab import _by_hand, _pool, _points, _synthetic

PARAMS = hrr.ReplayParams(**plan.REPLAY)
MODEL = PARAMS.execution_model()
LATENCY_S = study.sale_latency_s(MODEL)
COST = study.STAKE_LAMPORTS + 2 * MODEL.tx_cost
RULE = {rule['id']: rule for rule in exits.RULES}

# decision at event 1 (lands at once: the builder spaces events by at least 5 slots, more than the 4-slot latency)
PUMP = _synthetic([(0, 'buy', 500_000_000, 'a'), (3, 'buy', 300_000_000, 'b'), (2, 'buy', 4_000_000_000, 'c'),
                   (3, 'buy', 2_000_000_000, 'd'), (4, 'sell', 60 * 10 ** 12, 'c'), (6, 'sell', 30 * 10 ** 12, 'd'),
                   (20, 'sell', 10 * 10 ** 12, 'a'), (200, 'buy', 10 ** 8, 'e')])
DUMP = _synthetic([(0, 'buy', 3_000_000_000, 'a'), (3, 'buy', 300_000_000, 'b'), (2, 'buy', 50_000_000, 'c'),
                   (3, 'sell', 40 * 10 ** 12, 'a'), (4, 'sell', 30 * 10 ** 12, 'a'), (30, 'buy', 10 ** 8, 'e'),
                   (200, 'buy', 10 ** 8, 'f')])
# a small sale first (the position is 3 to 9 % under its cost), then a large one (more than 10 % under)
SLIDE = _synthetic([(0, 'buy', 3_000_000_000, 'a'), (3, 'buy', 1_000_000_000, 'b'), (3, 'sell', 16 * 10 ** 12, 'a'),
                    (4, 'sell', 50 * 10 ** 12, 'a'), (30, 'buy', 10 ** 8, 'e'), (200, 'buy', 10 ** 8, 'f')])
QUIET = _synthetic([(0, 'buy', 500_000_000, 'a'), (3, 'buy', 300_000_000, 'b'), (400, 'buy', 10 ** 8, 'e')])


def _expected(timeline, k, rule):
    """By hand: walk the real events after the landing; the sale lands right after the trigger event."""
    immediate, path, _tokens, land = _by_hand(timeline, k, {})
    events = timeline.events
    peak, last = None, immediate
    for offset, (age, mark) in enumerate(path):
        event = events[land + 1 + offset]
        if age > rule['clock_s'] + LATENCY_S:
            break
        peak = mark if peak is None else max(peak, mark)
        fired = None
        if 'stop_loss' in rule and mark <= COST * (1 - rule['stop_loss']):
            fired = 'stop_loss'
        elif 'take_profit' in rule and mark >= COST * (1 + rule['take_profit']):
            fired = 'take_profit'
        elif 'trailing' in rule and peak > COST and mark <= peak * (1 - rule['trailing']):
            fired = 'trailing'
        elif rule.get('first_sale') and event.side == 'sell':
            fired = 'first_sale'
        elif 'flow_window_s' in rule:
            old = [e for e in events[land:land + 1 + offset] if e.block_time <= event.block_time - rule['flow_window_s']]
            reference = (old[-1] if old else events[land]).real_quote_after
            if event.real_quote_after < reference:
                fired = 'flow_reversal'
        if fired:
            return mark, fired
        last = mark
    return last, 'clock'


@pytest.mark.parametrize('name, timeline', [('pump', PUMP), ('dump', DUMP), ('slide', SLIDE), ('quiet', QUIET)])
def test_every_rule_matches_the_by_hand_result(name, timeline):
    seen = set()
    for rule in exits.RULES:
        got = exits.run_rule(timeline, 1, {}, MODEL, rule)
        value, reason = _expected(timeline, 1, rule)
        assert (got['value'], got['reason'], got['migrated']) == (value, reason, False), (name, rule['id'])
        assert got['cost'] == COST and got['land_index'] == 1
        seen.add(reason)
    if name == 'pump':
        assert seen >= {'take_profit', 'trailing', 'first_sale', 'flow_reversal', 'clock'}
        assert exits.run_rule(timeline, 1, {}, MODEL, RULE['X1'])['value'] > exits.run_rule(timeline, 1, {}, MODEL, RULE['X0'])['value']
    if name == 'dump':
        assert seen >= {'stop_loss', 'first_sale', 'flow_reversal'}
        assert exits.run_rule(timeline, 1, {}, MODEL, RULE['X2'])['trigger_age_s'] == 5
    if name == 'slide':
        _immediate, path, _tokens, _land = _by_hand(timeline, 1, {})
        assert 0.90 * COST < path[0][1] < 0.95 * COST and path[1][1] < 0.90 * COST      # the stop waits for the second sale
        assert exits.run_rule(timeline, 1, {}, MODEL, RULE['X2'])['trigger_age_s'] == 7
        # the first sale leaves the curve under its level at our landing but above its level at event 0
        events = timeline.events
        assert events[0].real_quote_after < events[2].real_quote_after < events[1].real_quote_after
        flow = exits.run_rule(timeline, 1, {}, MODEL, RULE['X6'])
        assert (flow['reason'], flow['trigger_age_s']) == ('flow_reversal', 3)
    if name == 'quiet':
        assert seen == {'clock'}                                 # nothing happens: every rule ends on its clock


def test_the_clock_reference_is_the_value_of_the_state_study(archives):                            # noqa: F811
    checked = 0
    for _entry, archive in archives:
        timeline, facts, actors = _pool(archive)
        for k, labels in _points(timeline, facts):
            row = study.probe(timeline, k, actors, MODEL)
            if not row['entered']:
                continue
            got = exits.run_rule(timeline, k, actors, MODEL, RULE['X0'])
            assert got['value'] == row['horizons']['25']['value'] and got['migrated'] == row['horizons']['25']['migrated']
            quiet = exits.run_rule(timeline, k, actors, MODEL, dict(id='T', label='t', take_profit=50.0, clock_s=60))
            assert quiet['value'] == row['horizons']['60']['value'] and quiet['reason'] in ('clock', None)
            checked += 1
    assert checked >= 6


def test_a_rule_reads_nothing_after_its_own_sale():
    for timeline in (PUMP, DUMP):
        for rule in exits.RULES:
            got = exits.run_rule(timeline, 1, {}, MODEL, rule)
            if got['reason'] == 'clock':
                limit = timeline.events[1].block_time + rule['clock_s'] + LATENCY_S
            else:
                limit = timeline.events[1].block_time + got['trigger_age_s'] + LATENCY_S
            kept = tuple(e for e in timeline.events if e.block_time <= limit)
            assert exits.run_rule(replace(timeline, events=kept), 1, {}, MODEL, rule) == got


def test_a_completed_curve_counts_minus_one_and_a_refused_buy_gives_nothing():
    done = _synthetic([(0, 'buy', 500_000_000, 'a'), (5, 'buy', 300_000_000, 'b'), (8, 'buy', 200_000_000, 'c'),
                       (4, 'buy', 'ALMOST_ALL', 'whale'), (10, 'sell', 10 ** 9, 'a')])
    got = exits.run_rule(done, 1, {}, MODEL, RULE['X0'])
    assert got['migrated'] is True and got['value'] is None and got['reason'] is None
    row = dict(pool='p', creator='c', cost=COST, rules={'X0': got})
    assert exits._return(row, 'X0', None) == -1.0
    refused = _synthetic([(0, 'buy', 500_000_000, 'a'), (5, 'buy', 'ALMOST_ALL', 'whale'), (3, 'sell', 10 ** 9, 'a')])
    assert exits.run_rule(refused, 1, {}, MODEL, RULE['X0']) is None


def test_the_run_reads_discovery_only_and_every_rule_shares_the_entry(visible, archives, monkeypatch):   # noqa: F811
    directory, sha = visible
    document = exits.run(directory, sha)
    assert document['segments'] == ['exploration', 'train'] and document['k'] == 6 and document['entries'] == 'age:5'
    assert document['entered'] == len(document['rows']) and exits.run(directory, sha)['rows_sha256'] == document['rows_sha256']
    assert all(set(row['rules']) == set(RULE) for row in document['rows'])
    assert document['entered'] + sum(document['pools_without_entry'].values()) == 2
    json.dumps(document, allow_nan=False)
    seen, real = [], exits.pool_row

    def spy(archive, entry, segment, *rest):
        seen.append(segment)
        return real(archive, entry, segment, *rest)
    monkeypatch.setattr(exits, 'pool_row', spy)
    exits.run(directory, sha)
    assert sorted(seen) == ['exploration', 'train']
    entered = 0
    for entry, archive in archives:
        row, reason = real(archive, entry, 'train', PARAMS, None)
        if row is None:
            assert reason in ('no_reference_entry', 'entry_refused') or reason.startswith('not_replayable')
            continue
        timeline, facts, actors = _pool(archive)
        probe = study.probe(timeline, row['decision_index'], actors, MODEL)
        assert row['rules']['X0']['value'] == probe['horizons']['25']['value'] and row['cost'] == probe['cost']
        assert real(archive, entry, 'train', PARAMS, timeline.events[row['decision_index']].slot - 1) == (None, 'after_cutoff')
        entered += 1
    assert entered >= 2


def _rows(n=40, *, better=6_000_000, clock=96_000_000):
    rent = exits.SPL_RENT_LAMPORTS
    rows = []
    for i in range(n):
        rules = {rule['id']: dict(migrated=False, value=clock, reason='clock', trigger_age_s=None) for rule in exits.RULES}
        rules['X1'] = dict(migrated=False, value=clock + better + 1_000 * i, reason='take_profit', trigger_age_s=3)
        rules['X2'] = dict(migrated=False, value=clock - 2_000_000 if i % 2 else clock + 2_000_000, reason='stop_loss',
                           trigger_age_s=4)
        rules['X5'] = dict(migrated=i == 0, value=None if i == 0 else clock, reason=None if i == 0 else 'first_sale',
                           trigger_age_s=None if i == 0 else 2)
        rules['X4'] = dict(migrated=False, value=clock + (30_000_000 if i == 0 else 0), reason='trailing', trigger_age_s=9)
        rows.append(dict(pool='p%02d' % i, creator='c%02d' % i, cost=COST, rules=rules))
    return dict(schema=exits.SCHEMA, rows=rows, rows_sha256='x', pack_manifest_sha256='m', segments=['train'],
                population='all', entries='age:5', entered=n, creators=n), rent


def test_the_table_is_exact_and_separates_improving_from_profitable():
    document, rent = _rows()
    for bad in (5, None, '6'):
        with pytest.raises(ValueError, match='declared_k_is_not_the_number_of_exit_rules:6'):
            exits.table(document, declared_k=bad)
    out = exits.table(document, declared_k=6, n_boot=2_000)
    base = (96_000_000 - COST - rent) / (COST + rent)
    x0, x1, x2, x5 = (out['rules'][k] for k in ('X0', 'X1', 'X2', 'X5'))
    assert (out['k'], out['trials_added_to_n']) == (6, 6) and x0['vs_clock_25'] is None
    assert x0['mean_r'] == pytest.approx(base) and x0['exits'] == {'clock': 40} and x0['win_rate'] == 0.0
    gain = sum(6_000_000 + 1_000 * i for i in range(40)) / 40 / (COST + rent)
    assert x1['vs_clock_25']['mean'] == pytest.approx(gain) and x1['vs_clock_25']['ci95'][0] > 0
    assert x1['improves_the_exit'] is True and x1['profitable'] is False        # better than the clock, still a loss
    assert x1['mean_r'] < 0 and x1['exits'] == {'take_profit': 40}
    assert x2['vs_clock_25']['mean'] == pytest.approx(0.0) and x2['improves_the_exit'] is False
    x4 = out['rules']['X4']                                      # one pool carries the whole gain: not an improvement
    assert x4['vs_clock_25']['mean'] > 0 and x4['vs_clock_25']['ci95'][0] == 0.0 and x4['improves_the_exit'] is False
    assert x5['exits'] == {'first_sale': 39, 'migrated': 1}
    assert x5['mean_r'] == pytest.approx((39 * base - 1) / 40) and x5['improves_the_exit'] is False
    rich, _rent = _rows(better=20_000_000)
    assert exits.table(rich, declared_k=6, n_boot=2_000)['rules']['X1']['profitable'] is True
    text = exits.markdown(out)
    assert '| X1 | take profit +10 %, clock 60 s |' in text and 'référence' in text and 'OUI' in text
    census = dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[], rows=[])
    with pytest.raises(ValueError, match='token_class_unknown'):
        exits.table(document, census, declared_k=6, n_boot=0)
    with pytest.raises(ValueError, match='not_an_exit_rows_document'):
        exits.table(dict(document, schema='x'), declared_k=6)
