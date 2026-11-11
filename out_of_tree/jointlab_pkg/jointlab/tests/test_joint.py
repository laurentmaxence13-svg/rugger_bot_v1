"""jointlab.joint: the grid and its plans, selection without outcomes, rows tied to the audited probes and
triggers, exact recovery of known effects, the W1 guard and the counting of trials."""
import json

import pytest

from bot.p4 import historical_research_replay as hrr
from v3lab import plan
from v3lab.evaluate import cluster_bootstrap_means
from v3lab.tests.test_v3lab import archives                                 # noqa: F401  (fixture)

from statelab import exits, hypotheses as hyp, points, study
from statelab.tests.test_hypotheses import DIP, PURGE, _export
from statelab.tests.test_statelab import _pool

from jointlab import joint

PARAMS = hrr.ReplayParams(**plan.REPLAY)
COST, RENT = 100_210_000, joint.SPL_RENT_LAMPORTS
FROZEN_HYPOTHESES = '1e5fb31a8b8f1870204ba27ec413f893cc358557fa36a0dbfd4194b9385e3798'
FROZEN_EXITS = 'aba5d265e95c16a4f1843dd0977d525ff24340d2a9d907c9b3fb5f2e30484336'


def _value(r, rent=RENT):
    return round(r * (COST + rent) + COST + rent)


def _row(pool, entry, returns, *, flag=False, features=None, creator=None, slot=None, migrated=()):
    outs = {v: dict(migrated=v in migrated, value=None if v in migrated else _value(returns.get(v, returns['V0'])),
                    reason='clock') for v in joint._ids(joint.EXITS)}
    return dict(pool=pool, creator=creator or 'c' + pool, segment='export', entry=entry, decision_index=1,
                decision_slot=slot if slot is not None else int(pool[1:]), decision_block_time=0, entry_slot=0, cost=COST,
                features=dict({name: None for name in joint.SELECTION_FEATURES}, **(features or {})),
                creator_not_signer=flag, exits=outs)


def _document(rows):
    return dict(schema=joint.SCHEMA, rows=rows, rows_sha256='rows', slot_range=[0, 1])


def _additive(n=60, interaction=0.0):
    """r = -5 % + 2 % if selected + 3 % at entry A5 + 1 % with exit V1 (+ interaction when all three)."""
    rows = []
    for i in range(n):
        flag = i % 2 == 0
        for entry, bonus in (('PLACEBO', 0.0), ('A5', 0.03)):
            base = -0.05 + 0.02 * flag + bonus
            both = interaction if flag and entry == 'A5' else 0.0
            rows.append(_row('p%03d' % i, entry, dict(V0=base, V1=base + 0.01 + both, V2=base, V3=base), flag=flag))
    return _document(rows)


def test_the_frozen_code_is_the_one_measured_and_the_grid_is_fixed():
    assert hyp.fingerprint() == FROZEN_HYPOTHESES and exits.fingerprint() == FROZEN_EXITS
    assert (len(joint.SELECTORS), len(joint.ENTRIES), len(joint.EXITS)) == (5, 7, 4)
    for items in (joint.SELECTORS, joint.ENTRIES, joint.EXITS):
        assert len(set(joint._ids(items))) == len(items)
    assert joint.BASE == ('S0', 'PLACEBO', 'V0') and joint.EXITS[0] == dict(id='V0', label='clock 25 s', clock_s=25)
    assert [e['point'] for e in joint.ENTRIES if 'point' in e] == [points.PLACEBO_CELL, 'age:0', 'age:5', 'progress:650000', 'age:600']
    by_id = {r['id']: r for r in exits.RULES}
    assert {k: v for k, v in joint.EXITS[2].items() if k not in ('id', 'label')} == {k: v for k, v in by_id['X5'].items() if k not in ('id', 'label')}
    assert {k: v for k, v in joint.EXITS[3].items() if k not in ('id', 'label')} == {k: v for k, v in by_id['X6'].items() if k not in ('id', 'label')}


def test_plans_list_their_cells():
    star = joint.plan_cells('star')
    assert len(star) == 14 == len(set(star)) and star[0] == joint.BASE
    assert all(sum(x != y for x, y in zip(c, joint.BASE)) == 1 for c in star[1:])
    assert len(joint.plan_cells('full')) == 140 == len(set(joint.plan_cells('full')))
    assert joint.plan_cells('combined', ('S4', 'A0', 'V2')) == [
        joint.BASE, ('S4', 'PLACEBO', 'V0'), ('S0', 'A0', 'V0'), ('S0', 'PLACEBO', 'V2'), ('S4', 'A0', 'V2')]
    assert joint.plan_cells('combined', ('S0', 'A5', 'V1')) == [
        joint.BASE, ('S0', 'A5', 'V0'), ('S0', 'PLACEBO', 'V1'), ('S0', 'A5', 'V1')]
    assert joint.SECONDARY == ('S0', 'A5', 'V0') and joint.SECONDARY in star
    for bad in (None, ('S4', 'PLACEBO', 'V0'), ('S9', 'A0', 'V1'), ('S4', 'A0'), joint.BASE):
        with pytest.raises(ValueError, match='the_combined_plan_needs_one_cell'):
            joint.plan_cells('combined', bad)
    with pytest.raises(ValueError, match='unknown_plan'):
        joint.plan_cells('best')


def test_thirds_are_cut_on_the_reference_file_without_reading_any_outcome():
    rows = [_row('p%03d' % i, 'A5', dict(V0=0.0), features=dict(progress_ppm=10 * i, early_slot_payers=i % 4,
                                                                 fee_rate_ppm_causal=None)) for i in range(9)]
    document = _document(rows)
    cuts = joint.cutoffs(document)
    assert cuts['cutoffs']['A5'] == dict(progress_ppm=[20, 60], early_slot_payers=[0, 2])
    assert cuts['cutoffs']['PLACEBO'] == {} and cuts['reference_rows_sha256'] == 'rows'
    stripped = _document([{k: v for k, v in r.items() if k not in ('exits', 'cost')} for r in rows])
    assert joint.cutoffs(stripped) == cuts                                   # outcomes are not needed at all
    low, high, fee, flag = joint.SELECTORS[2], joint.SELECTORS[3], joint.SELECTORS[1], joint.SELECTORS[4]
    assert [joint.selected(r, low, cuts) for r in rows] == [True] * 3 + [False] * 6
    assert [joint.selected(r, high, cuts) for r in rows] == [i % 4 >= 2 for i in range(9)]
    assert not any(joint.selected(r, fee, cuts) for r in rows)               # unreadable value: never selected
    assert not any(joint.selected(r, flag, cuts) for r in rows) and all(joint.selected(r, joint.SELECTORS[0], cuts) for r in rows)
    assert joint.selected(dict(rows[0], creator_not_signer=True), flag, cuts)
    assert not joint.selected(dict(rows[0], creator_not_signer=None), flag, cuts)
    # the cutoffs of the reference file are applied unchanged to another file
    other = _row('p900', 'A5', dict(V0=0.0), features=dict(progress_ppm=25))
    assert not joint.selected(other, low, cuts) and joint.selected(dict(other, features=dict(progress_ppm=20)), low, cuts)
    with pytest.raises(ValueError, match='not_a_jointlab_rows_document'):
        joint.cutoffs(dict(schema='x', rows=[]))


def test_counts_show_sizes_only_and_decide_what_is_evaluable():
    document = _additive()
    cuts = joint.cutoffs(document)
    sizes = joint.counts(document, cuts, 'star')
    assert set(sizes) == {'plan', 'cells', 'evaluable_cells'} and len(sizes['cells']) == 14
    assert all(set(block) == {'positions', 'clusters', 'migrated', 'evaluable'} for block in sizes['cells'].values())
    assert sizes['cells']['S0,PLACEBO,V0'] == dict(positions=60, clusters=60, migrated=0, evaluable=True)
    assert sizes['cells']['S4,PLACEBO,V0'] == dict(positions=30, clusters=30, migrated=0, evaluable=True)
    assert sizes['cells']['S1,PLACEBO,V0']['positions'] == 0 and sizes['cells']['S0,DIP,V0']['evaluable'] is False
    assert sizes['evaluable_cells'] == 6                                     # base, S4, A5, V1, V2, V3
    few = _additive(n=58)                                                    # 29 selected pools: under the floor of 30
    assert joint.counts(few, cuts, 'star')['cells']['S4,PLACEBO,V0']['evaluable'] is False
    one_creator = _document([dict(r, creator='same') for r in document['rows']])
    assert joint.counts(one_creator, cuts, 'star')['evaluable_cells'] == 0   # 60 positions but one cluster


def test_the_star_plan_recovers_each_separate_effect():
    document = _additive()
    cuts = joint.cutoffs(document)
    with pytest.raises(ValueError, match='declared_cells_is_not_the_number_of_evaluable_cells:6'):
        joint.analysis(document, cuts, plan='star', declared_cells=14, n_boot=50)
    result = joint.analysis(document, cuts, plan='star', declared_cells=6, n_boot=400)
    cells = result['cells']
    assert set(cells) == {'S0,PLACEBO,V0', 'S4,PLACEBO,V0', 'S0,A5,V0', 'S0,PLACEBO,V1', 'S0,PLACEBO,V2', 'S0,PLACEBO,V3'}
    assert result['trials_added_to_n'] == 6 and 'interaction' not in result and result['cutoffs_from_the_same_rows']
    assert cells['S0,PLACEBO,V0']['mean_r'] == pytest.approx(-0.04, abs=1e-8) and 'effect_vs_base' not in cells['S0,PLACEBO,V0']
    assert cells['S4,PLACEBO,V0']['mean_r'] == pytest.approx(-0.03, abs=1e-8)
    # a selection is compared with the pools it does NOT select (R02): the full 2 % advantage, not a diluted half
    assert 'effect_vs_base' not in cells['S4,PLACEBO,V0']
    selection = cells['S4,PLACEBO,V0']['effect_vs_unselected']
    assert selection['mean'] == pytest.approx(0.02, abs=1e-8) and selection['compared_positions'] == 30
    assert selection['ci95'][0] == pytest.approx(0.02, abs=1e-8) and selection['positive_after_holm']
    # the MASTER reference entry (age 5 s) is published as a secondary, descriptive difference
    assert cells['S0,PLACEBO,V0']['diff_vs_age5']['mean'] == pytest.approx(-0.03, abs=1e-8)
    assert cells['S0,PLACEBO,V0']['diff_vs_age5']['ci95'] == pytest.approx([-0.03, -0.03], abs=1e-8)
    assert 'diff_vs_age5' not in cells['S0,A5,V0'] and 'p_holm' not in cells['S0,PLACEBO,V0']['diff_vs_age5']
    assert cells['S0,A5,V0']['effect_vs_base']['mean'] == pytest.approx(0.03, abs=1e-8)
    assert cells['S0,PLACEBO,V1']['effect_vs_base']['mean'] == pytest.approx(0.01, abs=1e-8)
    assert cells['S0,PLACEBO,V2']['effect_vs_base']['mean'] == pytest.approx(0.0, abs=1e-8)
    # the entry and exit effects are the same on every pool: their interval is a point and Holm keeps them
    assert cells['S0,A5,V0']['effect_vs_base']['positive_after_holm'] and cells['S0,PLACEBO,V1']['effect_vs_base']['positive_after_holm']
    assert not cells['S0,PLACEBO,V2']['effect_vs_base']['positive_after_holm']
    # ... and none of it is a positive net result: every cell loses money
    assert not any(block['net_positive_after_holm'] for block in cells.values())
    assert all(block['win_rate'] == 0 and block['mean_gain'] is None for block in cells.values())
    text = joint.markdown(result)
    assert text.count('NOT EVALUABLE') == 8 and 'profitable' not in text.lower()


def test_the_combined_plan_measures_the_interaction():
    for extra in (0.0, 0.04):
        document = _additive(interaction=extra)
        cuts = joint.cutoffs(document)
        result = joint.analysis(document, cuts, plan='combined', cell=('S4', 'A5', 'V1'), declared_cells=5, n_boot=400)
        assert result['cells']['S4,A5,V1']['mean_r'] == pytest.approx(0.01 + extra, abs=1e-8)
        assert result['interaction']['mean'] == pytest.approx(extra, abs=1e-8)
        low, high = result['interaction']['ci95']
        assert low == pytest.approx(extra, abs=1e-8) and high == pytest.approx(extra, abs=1e-8)
        assert result['trials_added_to_n'] == 5 and result['combined_cell'] == ['S4', 'A5', 'V1']
    two = joint.analysis(document, cuts, plan='combined', cell=('S0', 'A5', 'V1'), declared_cells=4, n_boot=200)
    assert two['interaction']['mean'] == pytest.approx(0.02, abs=1e-8)        # half of the pools carry the 4 % extra
    # a combined cell under the floors: no interaction is computed
    small = _additive(n=58)
    result = joint.analysis(small, joint.cutoffs(small), plan='combined', cell=('S4', 'A5', 'V1'), declared_cells=3, n_boot=50)
    assert 'interaction' not in result and 'S4,A5,V1' not in result['cells']


def test_holm_and_the_interval_decide_and_migrated_positions_count_minus_one():
    def noisy(shift, migrated=()):
        rows = []
        for i in range(300):
            noise = ((i * 37) % 21 - 10) / 100                               # -10 % ... +10 %, mean 0
            rows.append(_row('p%03d' % i, 'PLACEBO', dict(V0=shift + noise, V1=shift + noise + 0.001, V2=shift - noise, V3=shift),
                             migrated=('V3',) if i in migrated else ()))
        return _document(rows)

    document = noisy(0.004)
    result = joint.analysis(document, joint.cutoffs(document), plan='star', declared_cells=4, n_boot=1000)
    base = result['cells']['S0,PLACEBO,V0']
    assert base['mean_r'] > 0 and not base['net_positive_after_holm']         # a positive mean is not enough
    strong = noisy(0.05)
    result = joint.analysis(strong, joint.cutoffs(strong), plan='star', declared_cells=4, n_boot=1000)
    assert result['cells']['S0,PLACEBO,V0']['net_positive_after_holm'] and result['cells']['S0,PLACEBO,V0']['p_holm'] < 0.05
    assert result['cells']['S0,PLACEBO,V0']['win_rate'] == pytest.approx(sum(0.05 + ((i * 37) % 21 - 10) / 100 > 0 for i in range(300)) / 300)
    lost = noisy(0.05, migrated=range(0, 300, 10))
    sizes = joint.counts(lost, joint.cutoffs(lost), 'star')
    assert sizes['cells']['S0,PLACEBO,V3']['migrated'] == 30
    result = joint.analysis(lost, joint.cutoffs(lost), plan='star', declared_cells=4, n_boot=200)
    assert result['cells']['S0,PLACEBO,V3']['mean_r'] == pytest.approx((270 * 0.05 - 30) / 300, abs=1e-8)


def test_the_joint_bootstrap_is_the_audited_cluster_bootstrap_for_one_cell():
    values = [((i * 13) % 17 - 8) / 50 for i in range(40)]
    groups = ['g%02d' % (i // 2) for i in range(40)]                          # 20 clusters of two, already sorted
    draws = joint.joint_bootstrap({'x': [(1.0, list(zip(values, groups)))]}, n_boot=300, seed=7)['x']
    reference = cluster_bootstrap_means(values, groups, n_boot=300, seed=7)
    assert draws == pytest.approx(reference, abs=1e-12)
    # a difference between two cells that share their clusters keeps the pairing: a constant shift has no spread
    shifted = [(v + 0.01, g) for v, g in zip(values, groups)]
    diff = joint.joint_bootstrap({'d': [(1.0, shifted), (-1.0, list(zip(values, groups)))]}, n_boot=200)['d']
    assert diff[0] == pytest.approx(0.01, abs=1e-12) and diff[-1] == pytest.approx(0.01, abs=1e-12)
    # a draw that empties one cell is dropped for that statistic only
    partial = joint.joint_bootstrap({'a': [(1.0, [(1.0, 'g00')]), (-1.0, [(0.0, 'g01')])], 'b': [(1.0, [(1.0, 'g00'), (1.0, 'g01')])]},
                                    n_boot=200)
    assert len(partial['b']) == 200 and 0 < len(partial['a']) < 200 and set(partial['a']) == {1.0}
    assert joint.joint_bootstrap({'x': [(1.0, [])]}, n_boot=10) == {'x': []}


def test_drawdown_rent_and_unknown_token_class():
    assert joint.max_drawdown([0.1, -0.2, -0.1, 0.5, -0.05]) == pytest.approx(0.3)
    assert joint.max_drawdown([]) == 0 and joint.max_drawdown([0.1, 0.2]) == 0
    row = _row('p001', 'A5', dict(V0=0.0))
    assert joint.position_return(row, 'V0', None) == pytest.approx(0.0, abs=1e-9)
    t22 = 2_074_080
    census = {'p001': ('token-2022', t22)}
    assert joint.position_return(row, 'V0', census) == pytest.approx((_value(0.0) - COST - t22) / (COST + t22))
    with pytest.raises(ValueError, match='token_class_unknown_for_a_pool'):
        joint.position_return(row, 'V0', {})
    assert joint.position_return(_row('p002', 'A5', dict(V0=0.3), migrated=('V0',)), 'V0', None) == -1.0


def test_rows_are_the_audited_probes_triggers_and_features(archives):                                   # noqa: F811
    seen = set()
    for entry, archive in archives:
        rows, missing = joint.pool_rows(archive, entry, 'export', PARAMS, None)
        timeline, facts, actors = _pool(archive)
        events, model = timeline.events, PARAMS.execution_model()
        labels = {}
        for k, items in points.decision_points(events, facts['creation_block_time'], archive.pool):
            for kind, level in items:
                labels.setdefault(f'{kind}:{level}', k)
        expected = dict(PLACEBO=labels.get(points.PLACEBO_CELL), A0=labels.get('age:0'), A5=labels.get('age:5'),
                        DIP=hyp.dip_trigger(events), PURGE=hyp.purge_trigger(events, facts['creation_block_time']),
                        LATE=labels.get('progress:650000'), SURV=labels.get('age:600'))
        assert joint.entry_indexes(events, facts, archive.pool) == expected
        assert len({r['entry'] for r in rows}) == len(rows)                   # one position per pool and entry
        audited = {r['decision_index']: r for r in study.pool_rows(archive, entry, 'export', PARAMS, None)[0]}
        for row in rows:
            seen.add(row['entry'])
            k = row['decision_index']
            assert k == expected[row['entry']]
            probe = study.probe(timeline, k, actors, model)
            assert row['cost'] == probe['cost'] and row['entry_slot'] == probe['entry_slot']
            clock25 = probe['horizons']['25']
            assert row['exits']['V0']['migrated'] == clock25['migrated'] and row['exits']['V0']['value'] == clock25['value']
            clock60 = probe['horizons']['60']
            assert row['exits']['V1']['migrated'] == clock60['migrated'] and row['exits']['V1']['value'] == clock60['value']
            for rule in joint.EXITS:
                assert exits.run_rule(timeline, k, actors, model, rule)['value'] == row['exits'][rule['id']]['value']
            if k in audited:                                                  # a grid point: the same causal features
                assert row['features'] == {name: audited[k]['features'][name] for name in joint.SELECTION_FEATURES}
            assert row['creator'] == study.cluster_key(archive, facts) and row['creator_not_signer'] == hyp.creator_not_signer(facts)
        # a pool belongs to the part of its CREATION slot, with all its entries, whenever they are decided
        created = facts['creation_slot']
        assert rows and all(r['creation_slot'] == created for r in rows) and max(r['decision_slot'] for r in rows) > created
        assert joint.pool_rows(archive, entry, 'export', PARAMS, None, (created, created + 1)) == (rows, missing)
        for outside in ((created + 1, 10 ** 12), (0, created)):
            assert joint.pool_rows(archive, entry, 'export', PARAMS, None, outside) == ([], {'pool_created_outside_slot_range': 1})
        assert not any(key.endswith('buy_refused') for key in missing)
    assert {'PLACEBO', 'A0', 'A5'} <= seen


def test_the_decision_never_depends_on_the_future(archives):                                            # noqa: F811
    for _entry, archive in archives:
        timeline, facts, _actors = _pool(archive)
        events = timeline.events
        full = joint.entry_indexes(events, facts, archive.pool)
        for key, k in full.items():
            if k is None or key in ('PLACEBO', 'A0', 'A5', 'LATE', 'SURV'):   # grid labels: causality audited in statelab
                continue
            assert joint.entry_indexes(events[:k + 1], facts, archive.pool)[key] == k
            assert joint.entry_indexes(events[:k], facts, archive.pool)[key] is None


def test_w1_needs_both_anchored_verdicts_and_there_is_no_p0_reader(tmp_path):
    assert not hasattr(joint, 'run_p0')
    out, manifest_sha = _export(tmp_path)
    plain = joint.run_export(out, manifest_sha, slot_range=(0, 10 ** 12))
    assert plain['w1_data_read'] is False and plain['rows'] and plain['hypotheses_sha256'] == FROZEN_HYPOTHESES
    assert plain['exits_sha256'] == FROZEN_EXITS and plain['flags']['financial_order_submitted'] is False
    with pytest.raises(ValueError, match='export_manifest_sha256_is_not_the_expected_one'):
        joint.run_export(out, '0' * 64, slot_range=(0, 10 ** 12))
    with pytest.raises(ValueError, match='invalid_slot_range'):
        joint.run_export(out, manifest_sha, slot_range=(5, 5))
    assert joint.W1_PARTS == dict(discovery=(467_678_545, 468_484_945), screen=(468_484_945, 469_291_345))
    assert joint.W1_CUT_SLOT == (467_678_545 + 469_291_345) // 2 and joint.W1_EVALUATION[0] > plan.S0_W1
    discovery, screen = joint.W1_PARTS['discovery'], joint.W1_PARTS['screen']
    first_created = min(r['creation_slot'] for r in plain['rows'])
    shift = discovery[0] + 10 - first_created                               # the earliest pool is created in the discovery part
    w1, w1_sha = _export(tmp_path, shift=shift)
    for kwargs in ({}, dict(official_verdict_sha256='a' * 64), dict(hypotheses_verdict_sha256='b' * 64),
                   dict(official_verdict_sha256='a' * 64, hypotheses_verdict_sha256='B' * 64),
                   dict(official_verdict_sha256='a' * 64, hypotheses_verdict_sha256='b' * 63)):
        with pytest.raises(ValueError, match='w1_data_need_the_official_verdict_and_the_frozen_hypotheses_verdict'):
            joint.run_export(w1, w1_sha, slot_range=discovery, **kwargs)
    with pytest.raises(ValueError, match='the_two_verdicts_are_two_different_documents'):
        joint.run_export(w1, w1_sha, slot_range=discovery, official_verdict_sha256='a' * 64, hypotheses_verdict_sha256='a' * 64)
    both = dict(official_verdict_sha256='a' * 64, hypotheses_verdict_sha256='b' * 64)
    for free in ((0, 10 ** 12), (discovery[0], screen[1]), (discovery[0], discovery[1] - 1), (discovery[0] + 1, discovery[1])):
        with pytest.raises(ValueError, match='w1_parts_are_fixed_in_the_code'):
            joint.run_export(w1, w1_sha, slot_range=free, **both)                # on W1 only the two parts of the code exist
    document = joint.run_export(w1, w1_sha, slot_range=discovery, **both)
    later = joint.run_export(w1, w1_sha, slot_range=screen, **both)
    assert document['w1_data_read'] is True and document['part'] == 'discovery' and later['part'] == 'screen' and plain['part'] is None
    assert document['rows'] and all(discovery[0] <= r['creation_slot'] < discovery[1] for r in document['rows'])
    assert all(screen[0] <= r['creation_slot'] < screen[1] for r in later['rows'])
    assert not {r['pool'] for r in document['rows']} & {r['pool'] for r in later['rows']}
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ('decision_slot', 'entry_slot', 'creation_slot')} for r in rows]   # noqa: E731
    kept = {r['pool'] for r in document['rows']}
    assert strip(document['rows']) == strip([r for r in plain['rows'] if r['pool'] in kept])
    # the thirds are cut on the discovery part only, and the screen part is analysed with those cutoffs only
    cuts = joint.cutoffs(document)
    assert cuts['reference_w1'] is True and tuple(cuts['reference_slot_range']) == discovery
    with pytest.raises(ValueError, match='thirds_are_cut_on_the_discovery_part_only'):
        joint.cutoffs(later)
    foreign = joint.cutoffs(plain)
    for bad in (foreign, dict(cuts, reference_slot_range=list(screen)), dict(cuts, reference_w1=False)):
        with pytest.raises(ValueError, match='w1_needs_cutoffs_from_its_discovery_part'):
            joint.analysis(later, bad, plan='star', declared_cells=0, n_boot=10)
    assert joint.analysis(later, cuts, plan='star', declared_cells=0, n_boot=10)['cells'] == {}
    # two ranges of creation slots split the POOLS: every pool, with all its rows, is in exactly one part
    created = sorted({r['creation_slot'] for r in plain['rows']})
    assert len(created) == 3
    first = joint.run_export(out, manifest_sha, slot_range=(0, created[1]))
    second = joint.run_export(out, manifest_sha, slot_range=(created[1], 10 ** 12))
    assert first['rows'] and second['rows'] and not {r['pool'] for r in first['rows']} & {r['pool'] for r in second['rows']}
    key = lambda r: (r['pool'], r['entry'])                                                             # noqa: E731
    assert sorted(first['rows'] + second['rows'], key=key) == sorted(plain['rows'], key=key)
    assert first['missing'].get('pool_created_outside_slot_range') == 2 and second['missing'].get('pool_created_outside_slot_range') == 1


def test_the_command_line_prints_sizes_then_values_and_never_overwrites(tmp_path, capsys):
    out, manifest_sha = _export(tmp_path)
    rows, cuts, md = tmp_path / 'rows.json', tmp_path / 'cuts.json', tmp_path / 'a.md'
    joint.main(['rows', str(out), '--expect-manifest-sha', manifest_sha, '--out', str(rows), '--slot-min', '0', '--slot-max', str(10 ** 12)])
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {'rows_sha256', 'pools_read', 'entries', 'missing'} and printed['pools_read'] == 3
    with pytest.raises(SystemExit, match='output_exists'):
        joint.main(['rows', str(out), '--expect-manifest-sha', manifest_sha, '--out', str(rows), '--slot-min', '0', '--slot-max', '9'])
    joint.main(['cutoffs', str(rows), '--out', str(cuts)])
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {'reference_rows_sha256', 'features'}
    joint.main(['counts', str(rows), '--cutoffs', str(cuts), '--plan', 'star'])
    sizes = json.loads(capsys.readouterr().out)
    assert sizes['evaluable_cells'] == 0 and 'mean_r' not in json.dumps(sizes)   # three public pools: nothing to evaluate
    with pytest.raises(ValueError, match='declared_cells_is_not_the_number_of_evaluable_cells:0'):
        joint.main(['analysis', str(rows), '--cutoffs', str(cuts), '--plan', 'star', '--declared-cells', '14'])
    joint.main(['analysis', str(rows), '--cutoffs', str(cuts), '--plan', 'star', '--declared-cells', '0', '--markdown', str(md)])
    result = json.loads(capsys.readouterr().out)
    assert result['cells'] == {} and result['trials_added_to_n'] == 0 and md.read_text().count('NOT EVALUABLE') == 14


def test_holm_can_reject_a_cell_that_a_single_test_would_pass():
    rows = []
    for i in range(300):
        noise = ((i * 37) % 21 - 10) / 100
        rows.append(_row('p%03d' % i, 'PLACEBO', dict(V0=0.0078 + noise, V1=-0.05, V2=-0.05, V3=-0.05)))
    document = _document(rows)
    block = joint.analysis(document, joint.cutoffs(document), plan='star', declared_cells=4, n_boot=2000)['cells']['S0,PLACEBO,V0']
    assert block['mean_r'] > 0 and block['mean_r_ci95'][0] > 0 and block['p_one_sided'] < 0.05
    assert block['p_holm'] == pytest.approx(4 * block['p_one_sided']) and block['p_holm'] >= 0.05
    assert block['net_positive_after_holm'] is False


def test_the_two_causal_triggers_are_the_frozen_ones_and_are_not_confused():
    for timeline in (DIP, PURGE):
        events = timeline.events
        facts = dict(creation_block_time=events[0].block_time)
        found = joint.entry_indexes(events, facts, 'POOL')
        assert found['DIP'] == hyp.dip_trigger(events) and found['PURGE'] == hyp.purge_trigger(events, events[0].block_time)
    dip = joint.entry_indexes(DIP.events, dict(creation_block_time=DIP.events[0].block_time), 'POOL')
    purge = joint.entry_indexes(PURGE.events, dict(creation_block_time=PURGE.events[0].block_time), 'POOL')
    assert dip['DIP'] == 4 and dip['PURGE'] != 4 and purge['PURGE'] is not None and purge['DIP'] != purge['PURGE']


def _noise(i):
    return ((i * 37) % 21 - 10) / 100


def test_holm_can_reject_an_effect_that_a_single_test_would_pass():
    rows = [_row('p%03d' % i, 'PLACEBO', dict(V0=-0.03, V1=-0.03 + 0.0078 + _noise(i), V2=-0.08, V3=-0.08)) for i in range(300)]
    document = _document(rows)
    cells = joint.analysis(document, joint.cutoffs(document), plan='star', declared_cells=4, n_boot=2000)['cells']
    effect = cells['S0,PLACEBO,V1']['effect_vs_base']
    expected = 0.0078 + sum(_noise(i) for i in range(300)) / 300
    assert effect['mean'] == pytest.approx(expected, abs=1e-8) and effect['ci95'][0] > 0 and effect['p_one_sided'] < 0.05
    assert effect['p_holm'] == pytest.approx(3 * effect['p_one_sided']) and effect['p_holm'] >= 0.05
    assert effect['positive_after_holm'] is False
    assert cells['S0,PLACEBO,V2']['effect_vs_base']['positive_after_holm'] is False


def test_a_cell_needs_its_interval_above_zero_even_when_holm_passes():
    rows = [_row('p%03d' % i, 'PLACEBO', dict(V0=0.0070 + _noise(i), V1=0.05 + _noise(i), V2=0.05 + _noise(i), V3=0.05 + _noise(i)))
            for i in range(300)]
    document = _document(rows)
    cells = joint.analysis(document, joint.cutoffs(document), plan='star', declared_cells=4, n_boot=2000)['cells']
    base = cells['S0,PLACEBO,V0']
    assert base['mean_r'] > 0 and base['p_holm'] < 0.05 and base['mean_r_ci95'][0] <= 0
    assert base['net_positive_after_holm'] is False and cells['S0,PLACEBO,V1']['net_positive_after_holm'] is True


def test_an_effect_needs_its_interval_above_zero_even_when_holm_passes():
    rows = [_row('p%03d' % i, 'PLACEBO', dict(V0=-0.03, V1=-0.03 + 0.0070 + _noise(i), V2=0.02 + _noise(i), V3=0.02 + _noise(i)))
            for i in range(300)]
    document = _document(rows)
    cells = joint.analysis(document, joint.cutoffs(document), plan='star', declared_cells=4, n_boot=2000)['cells']
    effect = cells['S0,PLACEBO,V1']['effect_vs_base']
    assert effect['mean'] > 0 and effect['p_holm'] < 0.05 and effect['ci95'][0] <= 0 and effect['positive_after_holm'] is False
    assert cells['S0,PLACEBO,V2']['effect_vs_base']['positive_after_holm'] is True


def test_a_selection_effect_needs_enough_unselected_pools():
    rows = [_row('p%03d' % i, 'PLACEBO', dict(V0=-0.02 if i % 4 else -0.06), flag=bool(i % 4)) for i in range(80)]
    document = _document(rows)                                              # 60 selected, 20 unselected: under the floor of 30
    cells = joint.analysis(document, joint.cutoffs(document), plan='star', declared_cells=5, n_boot=100)['cells']
    block = cells['S4,PLACEBO,V0']
    assert block['positions'] == 60 and 'effect_vs_unselected' not in block and 'effect_vs_base' not in block
    more = _document(rows + [_row('q%03d' % i, 'PLACEBO', dict(V0=-0.06)) for i in range(10)])    # 30 unselected
    block = joint.analysis(more, joint.cutoffs(more), plan='star', declared_cells=5, n_boot=100)['cells']['S4,PLACEBO,V0']
    assert block['effect_vs_unselected']['mean'] == pytest.approx(0.04, abs=1e-8) and block['effect_vs_unselected']['compared_positions'] == 30
