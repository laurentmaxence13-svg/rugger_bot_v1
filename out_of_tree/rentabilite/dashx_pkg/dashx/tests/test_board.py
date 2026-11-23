"""dashx: the extended dashboard on hand-made anchored outputs with known answers; NON MESURÉ where absent."""
import gzip
import hashlib
import json

import pytest

from dashx import board as B

SPENT, TX = 100_000_000, 210_000
START, END = 1_000, 2_000


def _row(pool, arm, gross, buy_slot, sell_slot, fees=(1_000_000, 1_000_000), trial='L1'):
    pnl = gross - sum(fees) - TX
    return dict(trial=trial, arm=arm, pool=pool, outcome='closed', verified=True, pnl_lamports=pnl,
                net_return=pnl / (SPENT + TX),
                buy=dict(index=1, slot=buy_slot, block_time=10_000, spent_lamports=SPENT, fee_rate_ppm=10_000),
                sell=dict(index=2, slot=sell_slot, block_time=10_030, trigger=dict(reason='stop_loss')),
                decomposition=dict(market_move=gross, slippage=0, launchlab_buy_fee=fees[0], launchlab_sell_fee=fees[1],
                                   tx_costs=TX, failed_attempt_costs=0, pnl=pnl))


# net returns (pnl = gross - 2 210 000): +7.79 M, -12.21 M, +2.79 M, -5.21 M  in sale order 1100, 1200, 1300, 1400
MASTER = [('a', 10_000_000, 1_050, 1_100), ('b', -10_000_000, 1_060, 1_200), ('c', 5_000_000, 1_070, 1_300),
          ('d', -3_000_000, 1_080, 1_400)]


def _docs():
    entries = [_row(p, 'master', g, b, s) for p, g, b, s in MASTER]
    entries += [_row(p, 'reference', g, b, s) for p, g, b, s in MASTER]
    entries += [_row('a', 'placebo_random', -1_000_000, 1_055, 1_150), _row('b', 'placebo_random', 0, 1_065, 1_250)]
    pools = [dict(pool=n, creation_slot=1_010, creator='C' + n, arms={}) for n in 'abcd']
    bundle = dict(pools=pools, params=dict(latency_slots=4, failed_attempt_fee_lamports=0))
    ledger = dict(verdict='PASS', mismatches=[], w1_report=None, entries=entries)
    return ledger, bundle


def _summary(n=40, mean=-0.05, high=-0.01, clusters=35, **kw):
    return dict(dict(n=n, clusters=clusters, mean_net_return=mean, median_net_return=mean, win_rate=0.1,
                     mean_net_return_rent_recovered=mean + 0.02,
                     interval_95=dict(low=mean - 0.02, high=high, draws=2000, seed=20261120),
                     interpretable=n >= 30 and clusters >= 20, share_of_the_5_best_in_positive=0.5), **kw)


def _others():
    vent = dict(arms=dict(master=dict(T1_fee_tiers={'12500': dict(
        n=46, mean_gross_return=-0.01, mean_fee_return=0.025, mean_tx_return=0.0021, mean_net_return=-0.0545,
        median_net_return=-0.05, win_rate=0.3,
        interval_95_mean_net_return=dict(low=-0.1089, high=-0.0055, draws=2000, seed=20261120, interpretable=True))})))
    disc = dict(latency_slots=4, cells=dict(L1=_summary(178, -0.0514, -0.029), L3=_summary(82, -0.0781, -0.0476)),
                placebo_descriptive=_summary(270, -0.0567, -0.0375))
    screen = dict(latency_slots=4, cells=dict(L1=_summary(106, -0.1029, -0.0635)),
                  placebo_descriptive=_summary(200, -0.1041, -0.0736))
    sel = dict(latency_slots=4, cells=dict(T1=_summary(34, -0.0559, -0.0009, clusters=34),
                                           T3p=_summary(23, -0.1062, -0.0418, clusters=23)))
    cd = dict(latency_slots=4, c_d=_summary(46, -0.0459, -0.0242, clusters=41, mean_net_return_latency_10_slots=-0.047,
                                            decomposition_mean_share_of_stake=dict(gross=-0.0194, curve_fees=0.0049,
                                                                                   tx=0.0021, rent=0.0204)),
              placebo_low_tier_descriptive=_summary(35, -0.0182, -0.0033, clusters=34))
    return dict(ventilation=vent, latelab_discovery=disc, latelab_screen=screen, latesel=sel, cdgate=cd)


def _rows(doc):
    return {r['strategy']: r for r in doc['rows']}


def test_ledger_rows_full_metrics_with_known_answers():
    ledger, bundle = _docs()
    rows = _rows(B.board(ledger=ledger, bundle=bundle, evaluation_min=START, evaluation_max=END))
    m = rows['MASTER W1']
    pnl = [g - 2_210_000 for _p, g, _b, _s in MASTER]
    nets = [v / (SPENT + TX) for v in pnl]
    assert m['positions'] == 4 and m['pools'] == dict(distinct_pools=4) and m['win_rate'] == 0.5
    assert m['mean_net_return'] == pytest.approx(sum(nets) / 4) and m['expectancy'] == m['mean_net_return']
    assert m['mean_winning_return'] == pytest.approx((nets[0] + nets[2]) / 2)
    assert m['mean_losing_return'] == pytest.approx((nets[1] + nets[3]) / 2)
    assert m['profit_factor'] == pytest.approx((pnl[0] + pnl[2]) / -(pnl[1] + pnl[3]))
    # cumulative in sale order: n0, n0+n1 (fall n1), +n2, +n3: worst fall = max(-n1, -n1-n3 + ... )
    cum, peak, worst = 0, 0, 0
    for v in nets:
        cum += v
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    assert m['max_drawdown'] == pytest.approx(worst) and worst == pytest.approx(-(nets[1] + nets[2] + nets[3]))
    assert m['mean_curve_fees'] == pytest.approx(0.02) and m['mean_tx'] == pytest.approx(0.0021)
    assert m['latency_slots'] == 4 and m['failed_attempts'] == dict(modelled_fee_lamports=0, measured=False)
    assert m['robustness']['first_half_mean'] == pytest.approx((nets[0] + nets[1]) / 2)
    assert m['robustness']['mean_without_5_best'] == B.NM and m['robustness']['net_at_10_slots'] == B.NM
    assert m['placebo']['paired_pools'] == 2 and m['verdict'] == 'INCONCLUSIF'          # n = 4 < 30
    assert rows['Placebo W1']['verdict'] is None and rows['Placebo W1']['positions'] == 2


def test_drawdown_orders_positions_by_sale():
    ps = [dict(net_return=r, sell_slot=s, slot=0, pool=str(s)) for r, s in ((-0.5, 3), (1.0, 1), (-0.2, 2))]
    assert B.drawdown(ps) == pytest.approx(0.7)                 # +1.0, then -0.2, -0.5: fall of 0.7
    assert B.drawdown([dict(net_return=-0.1, sell_slot=1, slot=0, pool='x')]) == pytest.approx(0.1)


def test_aggregate_rows_keep_only_what_the_documents_hold():
    rows = _rows(B.board(**_others()))
    for name in ('latelab L1 (moitié 1)', 'latelab L3 (moitié 1)', 'latelab L1 crible (moitié 2)', 'latesel T1', 'C-D',
                 'C-A (MASTER, palier 12 500 ppm)'):
        r = rows[name]
        assert r['verdict'] == 'NÉGATIF' and r['status'] == 'EXPLORATOIRE'
        for col in ('mean_winning_return', 'mean_losing_return', 'profit_factor', 'max_drawdown'):
            assert r[col] == B.NM
    assert rows["latesel T3'"]['verdict'] == 'INCONCLUSIF'                       # n = 23 < 30
    assert rows['placebo du palier bas']['verdict'] is None and rows['placebo latelab (moitié 1)']['verdict'] is None
    assert rows['C-D']['mean_gross_return'] == -0.0194 and rows['C-D']['robustness']['net_at_10_slots'] == -0.047
    assert rows['C-D']['placebo']['mean_net_return'] == -0.0182
    assert rows['latelab L1 (moitié 1)']['mean_gross_return'] == B.NM and rows['latelab L1 (moitié 1)']['latency_slots'] == 4
    ca = rows['C-A (MASTER, palier 12 500 ppm)']
    assert ca['mean_curve_fees'] == 0.025 and ca['interval_95']['high'] == -0.0055 and ca['positions'] == 46
    for name in B.NO_POSITION:
        assert rows[name]['positions'] == 0 and rows[name]['verdict'] is None and rows[name]['mean_net_return'] == B.NM


def test_verdict_order_and_closed_vocabulary():
    assert B.verdict(29, -0.5) == 'INCONCLUSIF' and B.verdict(30, -0.01) == 'NÉGATIF'
    assert B.verdict(30, 0.0) == 'INCONCLUSIF' and B.verdict(100, -0.1, interpretable=False) == 'INCONCLUSIF'
    assert B.verdict(100, -0.1, placebo=True) is None and B.verdict(None, None) == 'INCONCLUSIF'
    doc = B.board(**_others())
    text = json.dumps(doc, ensure_ascii=False).lower()
    assert not any(w in text for w in ('rentable', 'profitable', 'gagnant', 'positif'))
    assert {r['verdict'] for r in doc['rows']} <= {'NÉGATIF', 'INCONCLUSIF', None}


def _write(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_run_checks_every_sha_and_hides_pools(tmp_path):
    ledger, bundle = _docs()
    raw_bundle = gzip.compress(json.dumps(bundle).encode(), mtime=0)
    (tmp_path / 'L1.json.gz').write_bytes(raw_bundle)
    ledger['bundles_sha256'] = dict(L1=hashlib.sha256(raw_bundle).hexdigest())
    lp = _write(tmp_path, 'ledger.json', ledger)
    others = {k: _write(tmp_path, k + '.json', v) for k, v in _others().items()}
    with pytest.raises(B.DashError, match='input_is_not_the_anchored_one'):
        B.run(tmp_path / 'o1', ledger=(lp[0], '0' * 64), bundle=tmp_path / 'L1.json.gz', evaluation_min=START,
              evaluation_max=END)
    with pytest.raises(B.DashError, match='input_is_not_the_anchored_one'):
        B.run(tmp_path / 'o1', cdgate=(others['cdgate'][0], '1' * 64))
    (tmp_path / 'x.gz').write_bytes(b'x')
    with pytest.raises(B.DashError, match='bundle_is_not_the_one'):
        B.run(tmp_path / 'o1', ledger=lp, bundle=tmp_path / 'x.gz', evaluation_min=START, evaluation_max=END)
    doc = B.run(tmp_path / 'out', ledger=lp, bundle=tmp_path / 'L1.json.gz', evaluation_min=START, evaluation_max=END,
                **others)
    assert len(doc['rows']) == 2 + 1 + 3 + 2 + 2 + 2 + 4
    text = (tmp_path / 'out' / 'TABLEAU_DE_BORD.json').read_text() + (tmp_path / 'out' / 'TABLEAU_DE_BORD.md').read_text()
    for name in ('"a"', 'Ca', 'Cb'):
        assert name not in text
    assert 'NON MESURÉ' in text and 'EXPLORATOIRE' in text
    with pytest.raises(B.DashError, match='output_exists'):
        B.run(tmp_path / 'out', cdgate=others['cdgate'])
    only = B.run(tmp_path / 'only', cdgate=others['cdgate'])
    assert {r['strategy'] for r in only['rows']} == {'C-D', 'placebo du palier bas'} | set(B.NO_POSITION)


def test_non_interpretable_aggregate_latency_from_the_document_and_vocabulary_guard(monkeypatch):
    few_clusters = B.aggregate_row('x', _summary(n=40, clusters=10, high=-0.2), placebo=False, latency=4, regime='LP')
    assert few_clusters['verdict'] == 'INCONCLUSIF'                  # n >= 30 but < 20 clusters: not interpretable
    ledger, bundle = _docs()
    rows = _rows(B.board(ledger=ledger, bundle=dict(bundle, params=dict(latency_slots=7)), evaluation_min=START,
                         evaluation_max=END))
    assert rows['MASTER W1']['latency_slots'] == 7
    assert rows['MASTER W1']['failed_attempts']['modelled_fee_lamports'] == 0
    rows = _rows(B.board(ledger=ledger, bundle=dict(bundle, params={}), evaluation_min=START, evaluation_max=END))
    assert rows['MASTER W1']['latency_slots'] == B.NM
    monkeypatch.setattr(B, 'verdict', lambda *a, **k: 'POSITIF')
    with pytest.raises(B.DashError, match='verdict_outside_the_closed_vocabulary'):
        B.board(**_others())
