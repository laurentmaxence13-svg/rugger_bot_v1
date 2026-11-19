"""w1x.reading: the closed list of figures of the preliminary reading, on hand-made documents with known answers."""
import gzip
import hashlib
import json
import random

import pytest

from w1x import reading as R

START, END = 1_000, 2_000


def _cycle(pool, arm, pnl, *, cost=100_000_000, move=None, reason='exit_horizon_clock', outcome='closed',
           slippage=1.0, fees=(1_800_000, 1_700_000), tx=210_000, failed=0, verified=True):
    row = dict(trial='L1', arm=arm, pool=pool, outcome=outcome, verified=verified, mismatches=[],
               pnl_lamports=pnl if outcome == 'closed' else None,
               net_return=(pnl / cost) if outcome == 'closed' else None,
               sell=dict(trigger=None if reason is None else dict(reason=reason, index=1, mark=1)))
    if outcome == 'closed':
        move = pnl + slippage + sum(fees) + tx + failed if move is None else move      # the exact identity by default
        row['decomposition'] = dict(market_move=move, slippage=slippage, launchlab_buy_fee=fees[0],
                                    launchlab_sell_fee=fees[1], tx_costs=tx, failed_attempt_costs=failed, pnl=pnl)
    return row


def _pool(name, slot, creator, outcome='no_entry', entered=None):
    entered = outcome != 'no_entry' if entered is None else entered
    return dict(pool=name, creation_slot=slot, creator=creator,
                arms=dict(master=dict(outcome=outcome, entry_index=3 if entered else None)))


def _documents(tmp_path, pools, entries, *, report=None, verdict='PASS', mismatches=(), excluded=()):
    bundle = dict(pools=pools, excluded_pools=list(excluded))
    path = tmp_path / 'L1.json.gz'
    path.write_bytes(gzip.compress(json.dumps(bundle).encode(), mtime=0))
    ledger = dict(verdict=verdict, mismatches=list(mismatches), w1_report=report, entries=entries,
                  pools_manifest_sha256='m' * 64, bundles_sha256=dict(L1=hashlib.sha256(path.read_bytes()).hexdigest()))
    (tmp_path / 'ledger.json').write_text(json.dumps(ledger))
    return tmp_path / 'ledger.json', path


# ten closed master cycles in six clusters (creator A holds four, B two, the pools without creator one each)
PNL = dict(p01=5_000_000, p02=-4_000_000, p03=-3_000_000, p04=20_000_000, p05=-6_000_000, p06=1_000_000,
           p07=-2_000_000, p08=-1_000_000, p09=3_000_000, p10=-8_000_000)
CREATOR = dict(p01='A', p02='A', p03='A', p04='A', p05='B', p06='B', p07=None, p08=None, p09='C', p10=None)
REASON = dict(p01='take_profit', p02='stop_loss', p03='stop_loss', p04='trailing_stop', p05='max_hold', p06='exit_horizon',
              p07='exit_horizon_clock', p08='something_new', p09=None, p10='stop_loss')


def _case(tmp_path, **kwargs):
    pools = [_pool(name, START + i, CREATOR[name], 'closed') for i, name in enumerate(sorted(PNL))]
    pools += [_pool('q_open', START + 50, 'A', 'open_at_end'), _pool('q_window', START + 51, None, 'open_at_window_end'),
              _pool('q_migrated', START + 52, 'D', 'migrated_unpriced'),
              _pool('q_migrated_before_entry', START + 53, 'D', 'migrated_unpriced', entered=False),
              _pool('q_diverged', START + 54, None, 'counterfactual_divergence'),
              _pool('q_none1', START + 60, 'E'), _pool('q_none2', END - 1, None),
              # outside the evaluation range: counted only, even with a closed cycle
              _pool('w_before', START - 1, 'A', 'closed'), _pool('w_after', END, None, 'closed'), _pool('w_none', START - 5, 'Z')]
    entries = [_cycle(name, 'master', PNL[name], reason=REASON[name]) for name in sorted(PNL)]
    entries += [_cycle('q_open', 'master', 0, outcome='open_at_end'), _cycle('q_window', 'master', 0, outcome='open_at_window_end'),
                _cycle('q_migrated', 'master', 0, outcome='migrated_unpriced'),
                _cycle('q_diverged', 'master', 0, outcome='counterfactual_divergence'),
                _cycle('w_before', 'master', 999_000_000), _cycle('w_after', 'master', -999_000_000),
                _cycle('p01', 'reference', -2_000_000), _cycle('p02', 'reference', -4_000_000),
                _cycle('q_none1', 'reference', 0, outcome='open_at_end'), _cycle('w_before', 'reference', 777_000_000),
                _cycle('p03', 'placebo_random', 6_000_000, cost=50_000_000),
                dict(_cycle('p01', 'master', 123), trial='L1_event_horizon'), dict(_cycle('p01', 'S1', 456), trial='S1', arm='immediate-snipe')]
    return _documents(tmp_path, pools, entries, excluded=[dict(pool='x1'), dict(pool='x2')], **kwargs)


def test_quantile_is_the_value_of_rank_ceil_q_n():
    values = [50, 10, 40, 20, 30, 60, 90, 70, 80, 100]
    assert [R.quantile(values, q) for q in (0.1, 0.5, 0.9, 0.025, 0.975, 1.0)] == [10, 50, 90, 10, 100, 100]
    assert R.quantile([3, 1, 2], 0.5) == 2 and R.quantile([4, 1, 3, 2], 0.5) == 2      # even count: the lower middle
    assert R.quantile([7], 0.1) == 7 and R.quantile([], 0.5) is None
    assert R.quantile(list(range(1, 2001)), 0.025) == 50 and R.quantile(list(range(1, 2001)), 0.975) == 1950


def test_the_master_reading_has_the_known_answers(tmp_path, capsys):
    ledger, bundle = _case(tmp_path)
    sums = R.run(ledger, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    assert capsys.readouterr() == ('', '')                                             # nothing is printed
    doc = json.loads((tmp_path / 'out' / 'LECTURE_PRELIMINAIRE.json').read_text(encoding='utf-8'))
    assert sums == {n: hashlib.sha256((tmp_path / 'out' / n).read_bytes()).hexdigest() for n in sums} and len(sums) == 2
    assert doc['stamp'] == 'PRÉLIMINAIRE — PAS LE VERDICT OFFICIEL W1' == R.STAMP
    assert (tmp_path / 'out' / 'LECTURE_PRELIMINAIRE.md').read_text(encoding='utf-8').startswith('# ' + R.STAMP)
    m = doc['master']
    assert m['Q1_positions'] == dict(eligible_manifest_pools=22, excluded_pools=2, replayed_pools=20, evaluation_pools=17,
                                     pools_outside_the_evaluation_range=3, opened=15, cycles_with_entry=14, closed=10,
                                     not_closed=dict(counterfactual_divergence=1, migrated_unpriced=2, open_at_end=1,
                                                     open_at_window_end=1), no_entry=2)
    q2 = m['Q2_result_lamports']
    assert (q2['net_sum'], q2['net_mean'], q2['net_median']) == (5_000_000, 500_000.0, -2_000_000)
    assert q2['win_rate'] == 0.4 and q2['profit_factor'] == 29_000_000 / 24_000_000
    assert q2['net_return_mean'] == pytest.approx(0.005) and q2['net_return_median'] == -0.02
    costs = 10 * (1.0 + 3_500_000 + 210_000)
    assert q2['gross_sum'] == pytest.approx(5_000_000 + costs) and q2['gross_mean'] == pytest.approx((5_000_000 + costs) / 10)
    assert m['Q3_distribution_lamports'] == dict(p10=-8_000_000, p50=-2_000_000, p90=5_000_000, maximum=20_000_000,
                                                 minimum=-8_000_000, share_of_the_5_best=1.0)
    parts = m['Q4_failure_factors']['decomposition_lamports']
    assert (parts['net'], parts['slippage'], parts['launchlab_fees'], parts['tx_costs'], parts['failed_attempt_costs']) == (
        5_000_000, 10.0, 35_000_000, 2_100_000, 0)
    assert parts['identity_residual'] == pytest.approx(0, abs=1e-6)
    assert m['Q4_failure_factors']['exit_reasons'] == dict(autre=2, exit_horizon=1, exit_horizon_clock=1, max_hold=1,
                                                         stop_loss=3, take_profit=1, trailing_stop=1)
    assert m['Q5_creators']['distinct_clusters'] == 6 and m['Q5_creators']['share_of_the_5_largest'] == 0.9
    assert m['Q7_unit']['net_sum_sol'] == 0.005 and m['Q7_unit']['net_mean_sol'] == 0.0005 and 'usd' in m['Q7_unit']
    assert doc['flags'] == dict(official_w1_verdict=False, w1_decision_computed=False, frozen_hypotheses_evaluated=False,
                                master_operational_trade=False, counted_in_master_gate=False,
                                financial_order_submitted=False, profitability_demonstrated=False)
    text = json.dumps(doc)
    assert '999000000' not in text and '777000000' not in text and '"S1"' not in text and 'event_horizon"' not in text
    assert 'usd' not in json.dumps({k: v for k, v in doc.items() if k != 'master'}).lower()


def test_the_interval_is_the_cluster_bootstrap_written_in_the_method(tmp_path):
    ledger, bundle = _case(tmp_path)
    R.run(ledger, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    got = json.loads((tmp_path / 'out' / 'LECTURE_PRELIMINAIRE.json').read_text())['master']['Q6_interval_95_of_the_mean_net_return']
    # the method, written again independently: clusters in sorted key order, 2 000 draws of as many clusters
    clusters = {}
    for name, pnl in PNL.items():
        clusters.setdefault(CREATOR[name] or name, []).append(pnl / 100_000_000)
    groups = [clusters[key] for key in sorted(clusters)]
    rng, means = random.Random(20261115), []
    for _ in range(2_000):
        picked = [groups[rng.randrange(len(groups))] for _ in groups]
        means.append(sum(sum(g) for g in picked) / sum(len(g) for g in picked))
    means.sort()
    # equal up to the last bits only: the order of the float additions is not part of the method
    assert (got['low'], got['high']) == (pytest.approx(means[49], abs=1e-12), pytest.approx(means[1949], abs=1e-12))
    assert (got['draws'], got['seed'], got['clusters']) == (2_000, 20261115, 6)
    assert got['low'] < 0.005 < got['high']
    one = R.bootstrap(dict(a=[0.1, -0.3]))
    assert (one['low'], one['high'], one['clusters']) == (pytest.approx(-0.1), pytest.approx(-0.1), 1)
    assert R.bootstrap({}) == dict(low=None, high=None, draws=2_000, seed=20261115, clusters=0)
    # clusters matter: the same ten values in ten clusters give another interval
    alone = R.bootstrap({name: [pnl / 100_000_000] for name, pnl in PNL.items()})
    assert (alone['low'], alone['high']) != (got['low'], got['high'])


def test_reference_and_placebo_are_totals_only(tmp_path):
    ledger, bundle = _case(tmp_path)
    R.run(ledger, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    others = json.loads((tmp_path / 'out' / 'LECTURE_PRELIMINAIRE.json').read_text())['others']
    assert set(others) == {'reference', 'placebo_random'}
    ref, placebo = others['reference'], others['placebo_random']
    assert set(ref) == {'cycles_with_entry', 'closed_cycles', 'mean_net_pnl_lamports', 'mean_net_return', 'decomposition_lamports'}
    assert (ref['cycles_with_entry'], ref['closed_cycles'], ref['mean_net_pnl_lamports'], ref['mean_net_return']) == (
        3, 2, -3_000_000.0, pytest.approx(-0.03))
    assert ref['decomposition_lamports']['net'] == -6_000_000 and ref['decomposition_lamports']['launchlab_fees'] == 7_000_000
    assert (placebo['closed_cycles'], placebo['mean_net_pnl_lamports'], placebo['mean_net_return']) == (1, 6_000_000.0, 0.12)


def test_no_closed_cycle_gives_none_everywhere(tmp_path):
    ledger, bundle = _documents(tmp_path, [_pool('a', START, 'A'), _pool('b', START + 1, None, 'open_at_end')],
                                [_cycle('b', 'master', 0, outcome='open_at_end')])
    R.run(ledger, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    doc = json.loads((tmp_path / 'out' / 'LECTURE_PRELIMINAIRE.json').read_text())
    m = doc['master']
    assert m['Q1_positions']['opened'] == 1 and m['Q1_positions']['closed'] == 0
    assert set(m['Q2_result_lamports'].values()) == {None} and set(m['Q3_distribution_lamports'].values()) == {None}
    assert m['Q4_failure_factors'] == dict(decomposition_lamports=None, exit_reasons={})
    assert m['Q5_creators']['share_of_the_5_largest'] is None and m['Q6_interval_95_of_the_mean_net_return']['low'] is None
    assert doc['others']['reference']['mean_net_return'] is None


def test_a_decomposition_that_does_not_add_up_is_reported_not_filled(tmp_path):
    pools = [_pool('a', START, 'A', 'closed'), _pool('b', START + 1, 'B', 'closed')]
    entries = [_cycle('a', 'master', -5_000_000), _cycle('b', 'master', -1_000_000, move=1_000.0)]     # b: 2 709 001 missing
    ledger, bundle = _documents(tmp_path, pools, entries)
    R.run(ledger, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    doc = json.loads((tmp_path / 'out' / 'LECTURE_PRELIMINAIRE.json').read_text())
    parts = doc['master']['Q4_failure_factors']['decomposition_lamports']
    assert parts['net'] == -6_000_000 and parts['identity_residual'] == pytest.approx(-1_000_000 - (1_000.0 - 1.0 - 3_500_000 - 210_000))
    assert doc['master']['Q2_result_lamports']['gross_sum'] == pytest.approx(parts['market_move'])


@pytest.mark.parametrize('change,error', [
    (dict(report=dict(decision='NO_GO')), 'ledger_quotes_a_w1_report'),
    (dict(verdict='FAIL'), 'ledger_verdict_is_not_pass'),
    (dict(mismatches=[dict(pool='p01')]), 'ledger_verdict_is_not_pass')])
def test_the_ledger_must_be_a_pass_without_report(tmp_path, change, error):
    ledger, bundle = _case(tmp_path, **change)
    with pytest.raises(R.ReadingError, match=error):
        R.run(ledger, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    assert not (tmp_path / 'out').exists()


def test_inputs_must_agree(tmp_path):
    ledger, bundle = _case(tmp_path)
    with pytest.raises(R.ReadingError, match='invalid_evaluation_range'):
        R.run(ledger, bundle, tmp_path / 'o1', evaluation_min=END, evaluation_max=START)
    (tmp_path / 'out').mkdir()
    with pytest.raises(R.ReadingError, match='output_exists'):
        R.run(ledger, bundle, tmp_path / 'out', evaluation_min=START, evaluation_max=END)
    doc = json.loads(ledger.read_text())
    for change, error in ((lambda d: d['entries'].pop(0), 'ledger_and_bundle_disagree_on_the_master_positions'),
                          (lambda d: d['entries'][0].update(outcome='open_at_end'), 'ledger_and_bundle_disagree'),
                          (lambda d: d['entries'].append(_cycle('q_none1', 'master', 1)), 'ledger_and_bundle_disagree'),
                          (lambda d: d['entries'].append(_cycle('ghost', 'reference', 1)), 'ledger_row_for_a_pool_absent'),
                          (lambda d: d['entries'][0].update(verified=None), 'closed_cycle_not_verified_by_the_ledger'),
                          (lambda d: d['entries'][0].pop('decomposition'), 'closed_cycle_without_its_figures'),
                          (lambda d: d['bundles_sha256'].update(L1='0' * 64), 'bundle_is_not_the_one_the_ledger_read')):
        changed = json.loads(json.dumps(doc))
        change(changed)
        ledger.write_text(json.dumps(changed))
        with pytest.raises(R.ReadingError, match=error):
            R.run(ledger, bundle, tmp_path / 'o2', evaluation_min=START, evaluation_max=END)
        assert not (tmp_path / 'o2').exists()
    ledger.write_text(json.dumps(doc))
    bundle.write_bytes(bundle.read_bytes() + b'\0')                                     # the bundle file changed
    with pytest.raises(R.ReadingError, match='bundle_is_not_the_one_the_ledger_read'):
        R.run(ledger, bundle, tmp_path / 'o3', evaluation_min=START, evaluation_max=END)


def test_main_prints_nothing_and_the_module_reads_only_its_two_inputs(tmp_path, capsys):
    ledger, bundle = _case(tmp_path)
    assert R.main(['--ledger', str(ledger), '--l1-bundle', str(bundle), '--evaluation-min', str(START),
                   '--evaluation-max', str(END), '--out', str(tmp_path / 'out')]) == 0
    assert capsys.readouterr() == ('', '')
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(R))
    imported = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported == {'argparse', 'gzip', 'hashlib', 'json', 'math', 'random', 'pathlib'}       # standard library only
    assert 'print(' not in inspect.getsource(R) and 'sys.stdout' not in inspect.getsource(R)


def test_edge_definitions_zero_result_no_loss_no_gain_more_than_five_gains(tmp_path):
    def reading(pnls, tag):
        pools = [_pool(f'p{i}', START + i, None, 'closed') for i in range(len(pnls))]
        entries = [_cycle(f'p{i}', 'master', pnl) for i, pnl in enumerate(pnls)]
        (tmp_path / tag).mkdir()
        ledger, bundle = _documents(tmp_path / tag, pools, entries)
        R.run(ledger, bundle, tmp_path / tag / 'out', evaluation_min=START, evaluation_max=END)
        return json.loads((tmp_path / tag / 'out' / 'LECTURE_PRELIMINAIRE.json').read_text())['master']
    zero = reading([0, 0, 5, -5], 'zero')                 # a zero result is neither a win nor a loss
    assert zero['Q2_result_lamports']['win_rate'] == 0.25 and zero['Q2_result_lamports']['profit_factor'] == 1.0
    wins = reading([1, 2, 3], 'wins')                     # no loss: no profit factor
    assert wins['Q2_result_lamports']['profit_factor'] is None and wins['Q2_result_lamports']['win_rate'] == 1.0
    losses = reading([-1, -2], 'losses')                  # no gain: no share of the best, profit factor 0
    assert losses['Q3_distribution_lamports']['share_of_the_5_best'] is None
    assert losses['Q2_result_lamports']['profit_factor'] == 0.0 and losses['Q2_result_lamports']['win_rate'] == 0.0
    seven = reading([70, 60, 50, 40, 30, 20, 10, -100], 'seven')
    assert seven['Q3_distribution_lamports']['share_of_the_5_best'] == 250 / 280
    assert seven['Q5_creators'] == dict(distinct_clusters=8, share_of_the_5_largest=5 / 8,
                                        cluster='creator address recorded by the bundle, else the pool')
