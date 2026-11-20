"""w1loss: a closed list of descriptive tables, on hand-made documents with known answers."""
import gzip
import hashlib
import json

import pytest

from w1loss import analysis as A

START, END = 1_000, 2_000
SPENT = 100_000_000


def _row(pool, arm, *, gross, rate, fees, slot, reason='exit_horizon_clock', tx=210_000, slippage=0, hold=30,
         outcome='closed', trial='L1', verified=True):
    pnl = gross - slippage - sum(fees) - tx
    cost = SPENT + tx
    row = dict(trial=trial, arm=arm, pool=pool, outcome=outcome, verified=verified, mismatches=[],
               pnl_lamports=pnl if outcome == 'closed' else None, net_return=pnl / cost if outcome == 'closed' else None,
               buy=dict(slot=slot, block_time=10_000, spent_lamports=SPENT, fee_rate_ppm=rate),
               sell=dict(block_time=10_000 + hold, trigger=dict(reason=reason, index=1, mark=1)))
    if outcome == 'closed':
        row['decomposition'] = dict(market_move=gross, slippage=slippage, launchlab_buy_fee=fees[0],
                                    launchlab_sell_fee=fees[1], tx_costs=tx, failed_attempt_costs=0, pnl=pnl)
    return row


def _pool(name, slot, plan=(10, 5)):
    arms = {arm: dict(exit_conditions=dict(tp_pct=plan[0], sl_pct=plan[1])) for arm in ('master', 'reference', 'placebo_random')}
    return dict(pool=name, creation_slot=slot, creator='C' + name, arms=arms)


# master: three tiers; a: 1.25 %, b and c: 1.75 %, d: 3.75 % (fees in lamports, both sides)
MASTER = dict(a=dict(gross=4_000_000, rate=12_500, fees=(1_250_000, 1_250_000), slot=1_002, reason='take_profit'),
              b=dict(gross=-6_000_000, rate=17_500, fees=(1_750_000, 1_650_000), slot=1_030, reason='stop_loss'),
              c=dict(gross=1_000_000, rate=17_500, fees=(1_750_000, 1_760_000), slot=1_200),
              d=dict(gross=-2_000_000, rate=37_500, fees=(3_750_000, 3_600_000), slot=1_600, reason='stop_loss', hold=12))
CREATED = dict(a=1_000, b=1_010, c=1_100, d=1_100, e=1_300)


def _documents(tmp_path, *, reference=None, extra=(), verdict='PASS'):
    pools = [_pool(n, CREATED[n]) for n in sorted(CREATED)] + [_pool('out', START - 1), _pool('late', END)]
    entries = [_row(n, 'master', **kw) for n, kw in MASTER.items()]
    entries += [_row(n, 'reference', **kw) for n, kw in (reference or MASTER).items()]
    entries += [_row('a', 'placebo_random', gross=-1_000_000, rate=12_500, fees=(1_250_000, 1_240_000), slot=1_020),
                _row('d', 'placebo_random', gross=3_000_000, rate=37_500, fees=(3_750_000, 3_760_000), slot=1_700),
                _row('e', 'placebo_random', gross=500_000, rate=17_500, fees=(1_750_000, 1_750_000), slot=1_324)]
    entries += [_row('out', 'master', gross=9 * SPENT, rate=12_500, fees=(1, 1), slot=1_500),     # outside the range
                _row('a', 'master', gross=9 * SPENT, rate=12_500, fees=(1, 1), slot=1_500, trial='L1_event_horizon'),
                _row('a', 'immediate-snipe', gross=9 * SPENT, rate=12_500, fees=(1, 1), slot=1_500),
                _row('e', 'master', gross=0, rate=12_500, fees=(1, 1), slot=1_500, outcome='open_at_end')]
    entries += list(extra)
    bundle = gzip.compress(json.dumps(dict(pools=pools)).encode(), mtime=0)
    (tmp_path / 'L1.json.gz').write_bytes(bundle)
    ledger = dict(verdict=verdict, mismatches=[], w1_report=None, entries=entries,
                  bundles_sha256=dict(L1=hashlib.sha256(bundle).hexdigest()))
    raw = json.dumps(ledger).encode()
    (tmp_path / 'ledger.json').write_bytes(raw)
    return tmp_path / 'ledger.json', hashlib.sha256(raw).hexdigest(), tmp_path / 'L1.json.gz'


PLACEBO = dict(a=dict(gross=-1_000_000, fees=(1_250_000, 1_240_000)), d=dict(gross=3_000_000, fees=(3_750_000, 3_760_000)),
               e=dict(gross=500_000, fees=(1_750_000, 1_750_000)))


def _parts(rows):
    fees = sum(sum(r['fees']) for r in rows)
    gross = sum(r['gross'] for r in rows)
    return dict(market_move=gross, slippage=0, launchlab_fees=fees, tx_costs=210_000 * len(rows), failed_attempt_costs=0,
                net=gross - fees - 210_000 * len(rows), identity_residual=0)


def _reading(directory, *, master_closed=4, net_shift=0, gross_shift=0.0, population=(START, END)):
    master = _parts(MASTER.values())
    master['net'] += net_shift
    master['market_move'] += gross_shift
    doc = dict(population=dict(evaluation_min=population[0], evaluation_max=population[1]),
               master=dict(Q1_positions=dict(closed=master_closed), Q4_failure_factors=dict(decomposition_lamports=master)),
               others=dict(placebo_random=dict(closed_cycles=3, decomposition_lamports=_parts(PLACEBO.values()))))
    raw = json.dumps(doc).encode()
    (directory / 'LECTURE_PRELIMINAIRE.json').write_bytes(raw)
    return directory / 'LECTURE_PRELIMINAIRE.json', hashlib.sha256(raw).hexdigest()


def _run(tmp_path, **kwargs):
    ledger, sha, bundle = _documents(tmp_path, **kwargs)
    reading, rsha = _reading(tmp_path)
    sums = A.run(ledger, sha, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END,
                 reading_path=reading, reading_sha256=rsha)
    return json.loads((tmp_path / 'out' / 'VENTILATION_W1.json').read_text(encoding='utf-8')), sums


def test_known_answers_for_the_master_arm(tmp_path, capsys):
    doc, sums = _run(tmp_path)
    assert capsys.readouterr() == ('', '')
    assert sums == {n: hashlib.sha256((tmp_path / 'out' / n).read_bytes()).hexdigest() for n in sums}
    assert (tmp_path / 'out' / 'VENTILATION_W1.md').read_text(encoding='utf-8').startswith('# ' + A.STAMP)
    m = doc['arms']['master']
    pnl = {n: kw['gross'] - sum(kw['fees']) - 210_000 for n, kw in MASTER.items()}
    assert m['T0_totals'] == dict(n=4, pnl_sum_lamports=sum(pnl.values()), gross_sum_lamports=-3_000_000,
                                  fees_sum_lamports=16_760_000, tx_sum_lamports=840_000, slippage_sum_lamports=0,
                                  failed_sum_lamports=0, gross_return_distribution=dict(
                                      p10=-0.06, p25=-0.06, p50=-0.02, p75=0.01, p90=0.04, share_positive=0.5))
    assert list(m['T1_fee_tiers']) == ['12500', '17500', '37500']
    tier = m['T1_fee_tiers']['17500']
    assert tier['n'] == 2 and tier['mean_gross_return'] == pytest.approx(-0.025)
    assert tier['mean_fee_return'] == pytest.approx((3_400_000 + 3_510_000) / 2 / SPENT)
    assert tier['mean_net_return'] == pytest.approx((pnl['b'] + pnl['c']) / 2 / (SPENT + 210_000))
    assert tier['median_net_return'] == pytest.approx(pnl['b'] / (SPENT + 210_000)) and tier['win_rate'] == 0.0
    assert m['T1_fee_tiers']['12500']['win_rate'] == 1.0
    cf = {c['rate_ppm']: c for c in m['T2_counterfactual_fee_first_order']}
    assert sorted(cf) == [12_500, 17_500]                       # observed causal tiers below the highest one only
    assert cf[12_500]['label'] == A.CF_LABEL == ("approximation au premier ordre (sans effet sur le prix ni sur la "
                                                  "décision d'entrée)")
    expected = sum(pnl[n] + sum(kw['fees']) * (1 - 17_500 / kw['rate']) * (kw['rate'] > 17_500) for n, kw in MASTER.items())
    assert cf[17_500]['net_sum_lamports'] == pytest.approx(expected)
    assert cf[17_500]['mean_net_return'] == pytest.approx(expected / 4 / (SPENT + 210_000))       # frozen denominator
    assert cf[17_500]['win_rate'] == 0.25
    assert cf[12_500]['net_sum_lamports'] == pytest.approx(  # the lowest tier is unchanged, the others are scaled down
        pnl['a'] + sum(pnl[n] + sum(MASTER[n]['fees']) * (1 - 12_500 / MASTER[n]['rate']) for n in 'bcd'))
    assert m['T3_exit_reasons']['stop_loss']['n'] == 2 and m['T3_exit_reasons']['stop_loss']['mean_hold_s'] == 21.0
    assert m['T3_exit_reasons']['stop_loss']['median_hold_s'] == 12
    ages = {k: (v['n'], v['mean_gross_return'], v['mean_net_return']) for k, v in m['T4_entry_age_slots'].items()}
    assert ages == {'[0,5)': (1, 0.04, pytest.approx(pnl['a'] / (SPENT + 210_000))),
                    '[5,25)': (1, -0.06, pytest.approx(pnl['b'] / (SPENT + 210_000))),
                    '[50,150)': (1, 0.01, pytest.approx(pnl['c'] / (SPENT + 210_000))),
                    '>=450': (1, -0.02, pytest.approx(pnl['d'] / (SPENT + 210_000)))}
    one = m['T4_entry_age_slots']['[0,5)']['interval_95_mean_net_return']
    assert one['low'] == one['high'] == pytest.approx(pnl['a'] / (SPENT + 210_000)) and one['clusters'] == 1
    assert one['interpretable'] is False and (one['seed'], one['draws']) == (20261120, 2000)
    thirds = m['T5_chronological_thirds']
    assert [t['n'] for t in thirds] == [1, 1, 2] and thirds[2]['first_slot'] == 1_200 and thirds[2]['last_slot'] == 1_600
    plan = m['T7_scorer_plan']['tp=10;sl=5']
    assert list(m['T7_scorer_plan']) == ['tp=10;sl=5'] and plan['n'] == 4 and plan['mean_gross_return'] == -0.0075
    assert plan['mean_net_return'] == pytest.approx(sum(pnl.values()) / 4 / (SPENT + 210_000))
    returns = sorted(v / (SPENT + 210_000) for v in pnl.values())
    ci = plan['interval_95_mean_net_return']                              # four creators: one cycle each
    assert returns[0] <= ci['low'] <= ci['high'] <= returns[-1] and ci['clusters'] == 4
    assert doc['breakdowns'] == ['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7']
    assert doc['reference_identical_to_master'] is True


def test_placebo_pairs_and_the_firewall(tmp_path):
    doc, _ = _run(tmp_path)
    p = doc['arms']['placebo_random']
    assert p['T0_totals']['n'] == 3                                          # the master-only rows are not read
    assert {k: v['n'] for k, v in p['T4_entry_age_slots'].items()} == {'[5,25)': 2, '>=450': 1}   # e: age 24 exactly
    assert [A._age_class(x) for x in (0, 4, 5, 24, 25, 449, 450, -1)] == [
        '[0,5)', '[0,5)', '[5,25)', '[5,25)', '[25,50)', '[150,450)', '>=450', 'negative']
    pair = doc['T6_paired_master_minus_placebo']
    assert pair['n'] == 2                                                    # pools a and d
    assert pair['mean_diff_gross_return'] == pytest.approx(((0.04 + 0.01) + (-0.02 - 0.03)) / 2)
    assert pair['interval_95_mean_diff_net_return']['clusters'] == 2
    assert pair['interval_95_mean_diff_net_return']['interpretable'] is False
    assert {k: v for k, v in doc['firewall'].items() if k != 'fields_read'} == dict(
        arms_read=['master', 'placebo_random', 'reference'], trial_read='L1', frozen_hypotheses_evaluated=False,
        age_classes_stop_at_slots=450)
    assert set(doc['arms']) == {'master', 'placebo_random'}
    assert doc['flags']['w1_figure_changed'] is False and doc['flags']['selection_made'] is False
    # 9 x the stake outside the range, in another trial or arm, or not closed: never read
    assert max(t['n'] for t in doc['arms']['master']['T1_fee_tiers'].values()) == 2


def test_a_reference_that_differs_from_the_master_is_flagged(tmp_path):
    reference = dict(MASTER, a=dict(MASTER['a'], gross=3_999_999))
    doc, _ = _run(tmp_path, reference=reference)
    assert doc['reference_identical_to_master'] is False
    assert 'Référence identique au MASTER : NON' in (tmp_path / 'out' / 'VENTILATION_W1.md').read_text(encoding='utf-8')


def test_guards(tmp_path):
    ledger, sha, bundle = _documents(tmp_path)
    with pytest.raises(A.BreakdownError, match='ledger_is_not_the_anchored_one'):
        A.run(ledger, '0' * 64, bundle, tmp_path / 'o1', evaluation_min=START, evaluation_max=END, **_rd(tmp_path))
    (tmp_path / 'other.json.gz').write_bytes(gzip.compress(b'{"pools": []}', mtime=0))
    with pytest.raises(A.BreakdownError, match='bundle_is_not_the_one_the_ledger_recorded'):
        A.run(ledger, sha, tmp_path / 'other.json.gz', tmp_path / 'o2', evaluation_min=START, evaluation_max=END,
              **_rd(tmp_path))
    (tmp_path / 'o3').mkdir()
    with pytest.raises(A.BreakdownError, match='output_exists'):
        A.run(ledger, sha, bundle, tmp_path / 'o3', evaluation_min=START, evaluation_max=END, **_rd(tmp_path))
    with pytest.raises(A.BreakdownError, match='invalid_evaluation_range'):
        A.run(ledger, sha, bundle, tmp_path / 'o4', evaluation_min=END, evaluation_max=START, **_rd(tmp_path))
    sub = tmp_path / 'fail'
    sub.mkdir()
    ledger, sha, bundle = _documents(sub, verdict='FAIL')
    with pytest.raises(A.BreakdownError, match='ledger_is_not_a_pass_without_report'):
        A.run(ledger, sha, bundle, sub / 'o', evaluation_min=START, evaluation_max=END, **_rd(sub))
    sub = tmp_path / 'unverified'
    sub.mkdir()
    bad = _row('c', 'placebo_random', gross=0, rate=17_500, fees=(1, 1), slot=1_150, verified=False)
    ledger, sha, bundle = _documents(sub, extra=[bad])
    with pytest.raises(A.BreakdownError, match='closed_cycle_not_verified_or_without_figures:c'):
        A.run(ledger, sha, bundle, sub / 'o', evaluation_min=START, evaluation_max=END, **_rd(sub))


def test_main_writes_the_two_files_and_their_sums(tmp_path):
    ledger, sha, bundle = _documents(tmp_path)
    reading, rsha = _reading(tmp_path)
    assert A.main(['--ledger', str(ledger), '--ledger-sha256', sha, '--l1-bundle', str(bundle), '--evaluation-min',
                   str(START), '--evaluation-max', str(END), '--reading', str(reading), '--reading-sha256', rsha,
                   '--out', str(tmp_path / 'out')]) == 0
    sums = json.loads((tmp_path / 'out' / 'SHA256SUMS.json').read_text())
    assert sorted(sums) == ['VENTILATION_W1.json', 'VENTILATION_W1.md']
    assert all(hashlib.sha256((tmp_path / 'out' / n).read_bytes()).hexdigest() == s for n, s in sums.items())


FORBIDDEN_NAMES = ('real_base', 'real_quote', 'progress', 'signer', 'signed', 'unsigned', 'age:600', 'age:0',
                   'creation_signature', 'vault', 'fee_payer', 'holder')


def test_firewall_no_hw1_state_variable_is_named_in_the_module():
    import inspect
    source = inspect.getsource(A)
    found = [name for name in FORBIDDEN_NAMES if name in source]
    assert found == [], found


class _Spy(dict):
    """A dict that records every key read."""

    def __init__(self, data, log, path):
        super().__init__({k: _spy(v, log, path + (k,)) for k, v in data.items()})
        self._log, self._path = log, path

    def __getitem__(self, key):
        self._log.add(self._path + (key,))
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._log.add(self._path + (key,))
        return super().get(key, default)

    def __contains__(self, key):
        self._log.add(self._path + (key,))
        return super().__contains__(key)


def _spy(value, log, path):
    if isinstance(value, dict):
        return _Spy(value, log, path)
    if isinstance(value, list):
        return [_spy(v, log, path + ('[]',)) for v in value]
    return value


def test_firewall_only_the_whitelisted_fields_are_read(tmp_path):
    ledger, _sha, bundle = _documents(tmp_path)
    log = set()
    led = _spy(json.loads(ledger.read_text()), log, ('ledger',))
    bun = _spy(json.loads(gzip.decompress(bundle.read_bytes())), log, ('bundle',))
    A.breakdown(led, bun, evaluation_min=START, evaluation_max=END)
    allowed = {('ledger', 'verdict'), ('ledger', 'mismatches'), ('ledger', 'w1_report'), ('ledger', 'entries'),
               ('bundle', 'pools')}
    F = A.READ_FIELDS
    allowed |= {('ledger', 'entries', '[]', k) for k in F['row']}
    allowed |= {('ledger', 'entries', '[]', 'buy', k) for k in F['buy']}
    allowed |= {('ledger', 'entries', '[]', 'sell', k) for k in F['sell']}
    allowed |= {('ledger', 'entries', '[]', 'sell', 'trigger', 'reason')}
    allowed |= {('ledger', 'entries', '[]', 'decomposition', k) for k in F['decomposition']}
    allowed |= {('bundle', 'pools', '[]', k) for k in F['bundle_pool']}
    allowed |= {('bundle', 'pools', '[]', 'arms', arm) for arm in ('master', 'reference', 'placebo_random')}
    allowed |= {('bundle', 'pools', '[]', 'arms', arm, k) for arm in ('master', 'reference', 'placebo_random')
                for k in F['bundle_arm']}
    allowed |= {('bundle', 'pools', '[]', 'arms', arm, 'exit_conditions', k)
                for arm in ('master', 'reference', 'placebo_random') for k in F['exit_conditions']}
    assert log - allowed == set(), sorted(log - allowed)
    assert ('ledger', 'entries', '[]', 'decomposition', 'market_move') in log          # the spy does see the reads


def test_output_whitelist_no_pool_creator_or_signature(tmp_path):
    doc, _ = _run(tmp_path)
    text = json.dumps(doc) + (tmp_path / 'out' / 'VENTILATION_W1.md').read_text(encoding='utf-8')
    for name in list(CREATED) + ['out', 'late']:
        assert f'"{name}"' not in text and 'C' + name not in text, name


def _rd(directory):
    reading, rsha = _reading(directory)
    return dict(reading_path=reading, reading_sha256=rsha)


def _manual_bootstrap(clusters):
    import random
    groups = [clusters[k] for k in sorted(clusters)]
    rng, means = random.Random(20261120), []
    for _ in range(2000):
        picked = [groups[rng.randrange(len(groups))] for _g in groups]
        means.append(sum(map(sum, picked)) / sum(map(len, picked)))
    means.sort()
    return means[49], means[1949]                       # ranks ceil(0.025 * 2000) and ceil(0.975 * 2000)


def test_interval_is_the_creator_cluster_bootstrap_and_the_counterfactual_one_is_shifted(tmp_path):
    shared = dict(CREATED)
    ledger, sha, bundle = _documents(tmp_path)
    data = json.loads(gzip.decompress(bundle.read_bytes()))
    for pool in data['pools']:
        if pool['pool'] in ('b', 'c'):
            pool['creator'] = 'SAME'                    # b and c: one creator, one cluster
    raw = gzip.compress(json.dumps(data).encode(), mtime=0)
    bundle.write_bytes(raw)
    led = json.loads(ledger.read_text())
    led['bundles_sha256']['L1'] = hashlib.sha256(raw).hexdigest()
    doc = A.breakdown(led, data, evaluation_min=START, evaluation_max=END)
    m = doc['arms']['master']
    pnl = {n: kw['gross'] - sum(kw['fees']) - 210_000 for n, kw in MASTER.items()}
    r = {n: v / (SPENT + 210_000) for n, v in pnl.items()}
    whole = m['T7_scorer_plan']['tp=10;sl=5']['interval_95_mean_net_return']
    assert whole['clusters'] == 3
    assert (whole['low'], whole['high']) == pytest.approx(_manual_bootstrap(dict(Ca=[r['a']], SAME=[r['b'], r['c']], Cd=[r['d']])))
    cf = {c['rate_ppm']: c for c in m['T2_counterfactual_fee_first_order']}[12_500]
    shifted = {n: (pnl[n] + sum(kw['fees']) * (1 - 12_500 / kw['rate'])) / (SPENT + 210_000) for n, kw in MASTER.items()}
    assert (cf['interval_95_mean_net_return']['low'], cf['interval_95_mean_net_return']['high']) == pytest.approx(
        _manual_bootstrap(dict(Ca=[shifted['a']], SAME=[shifted['b'], shifted['c']], Cd=[shifted['d']])))
    tier = m['T1_fee_tiers']['17500']['interval_95_mean_gross_return']      # b and c: one creator, one cluster
    assert tier['clusters'] == 1 and tier['low'] == tier['high'] == pytest.approx(-0.025)
    plan_gross = m['T7_scorer_plan']['tp=10;sl=5']['interval_95_mean_gross_return']
    g = {n: kw['gross'] / SPENT for n, kw in MASTER.items()}
    assert (plan_gross['low'], plan_gross['high']) == pytest.approx(_manual_bootstrap(dict(Ca=[g['a']], SAME=[g['b'], g['c']], Cd=[g['d']])))
    assert shared == CREATED


def test_a_position_without_a_rate_is_refused(tmp_path):
    bad = _row('c', 'placebo_random', gross=0, rate=0, fees=(1, 1), slot=1_150)
    ledger, sha, bundle = _documents(tmp_path, extra=[bad])
    with pytest.raises(A.BreakdownError, match='position_without_spent_or_rate:c'):
        A.run(ledger, sha, bundle, tmp_path / 'o', evaluation_min=START, evaluation_max=END, **_rd(tmp_path))


def test_bootstrap_takes_the_ranks_of_2_5_and_97_5_percent_not_the_extremes():
    clusters = {f'k{i:02d}': [float(i), float(i) / 2] for i in range(12)}
    out = A.bootstrap(clusters)
    assert (out['low'], out['high']) == pytest.approx(_manual_bootstrap(clusters))
    assert out['clusters'] == 12 and (out['seed'], out['draws']) == (20261120, 2000)
    assert A.bootstrap({}) == dict(low=None, high=None, draws=2000, seed=20261120, clusters=0)


def test_t0_must_equal_the_anchored_reading_to_the_lamport_or_nothing_is_written(tmp_path):
    cases = [('net', dict(net_shift=1), 'reading_sum_differs:master:net'),
             ('gross', dict(gross_shift=1.0), 'reading_sum_differs:master:gross'),
             ('count', dict(master_closed=5), 'reading_count_differs:master'),
             ('population', dict(population=(START, END + 1)), 'reading_population_differs')]
    for name, kwargs, error in cases:
        sub = tmp_path / name
        sub.mkdir()
        ledger, sha, bundle = _documents(sub)
        reading, rsha = _reading(sub, **kwargs)
        with pytest.raises(A.BreakdownError, match=error):
            A.run(ledger, sha, bundle, sub / 'out', evaluation_min=START, evaluation_max=END,
                  reading_path=reading, reading_sha256=rsha)
        assert not (sub / 'out').exists(), name
    sub = tmp_path / 'float'
    sub.mkdir()
    ledger, sha, bundle = _documents(sub)
    reading, rsha = _reading(sub, gross_shift=0.4)                       # rounding of float sums: under one lamport
    A.run(ledger, sha, bundle, sub / 'out', evaluation_min=START, evaluation_max=END, reading_path=reading,
          reading_sha256=rsha)
    doc = json.loads((sub / 'out' / 'VENTILATION_W1.json').read_text())
    assert doc['reading_check']['reading_checked'] is True and doc['inputs']['reading_sha256'] == rsha
    with pytest.raises(A.BreakdownError, match='reading_is_not_the_anchored_one'):
        A.run(ledger, sha, bundle, sub / 'o2', evaluation_min=START, evaluation_max=END, reading_path=reading,
              reading_sha256='0' * 64)
    with pytest.raises(A.BreakdownError, match='anchored_reading_required'):
        A.run(ledger, sha, bundle, sub / 'o3', evaluation_min=START, evaluation_max=END)


def test_intervals_are_reproducible_and_the_gross_interval_and_e_are_published(tmp_path):
    first = tmp_path / 'one'
    second = tmp_path / 'two'
    first.mkdir()
    second.mkdir()
    doc1, sums1 = _run(first)
    doc2, sums2 = _run(second)
    assert sums1 == sums2 and doc1 == doc2                                # same seed, same bytes
    tier = doc1['arms']['master']['T1_fee_tiers']['17500']
    assert tier['interval_95_mean_gross_return']['interpretable'] is False          # n = 2 < 30
    assert tier['interval_95_mean_net_return']['interpretable'] is False
    assert doc1['T6_paired_master_minus_placebo']['interval_95_mean_diff_gross_return']['clusters'] == 2
    assert doc1['E'] == 7
    text = (first / 'out' / 'VENTILATION_W1.md').read_text(encoding='utf-8')
    assert 'Intervalles descriptifs, aucun test, aucune sélection.' in text and 'aucun intervalle' not in text
    assert 'non interprétable' in text
