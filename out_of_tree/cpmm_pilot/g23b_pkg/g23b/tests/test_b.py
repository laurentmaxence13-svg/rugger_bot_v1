"""g23b 0.1 on fixtures only (the rows of g23five's own tests, with a frozen-shaped decomposition)."""
import json
import random

import pytest

from cpmmcost import model as CC
from cpmmpilot import step1 as PILOT
from g23five import verdict as V
from g23five.tests.test_verdict import D, DRAWS, POOLS, SHEET, T0, run
from g23b import b as B

SEED = int(SHEET[:8], 16)


def entered(pool, day, gross, k=0, fees=-0.005, impact=-0.002):
    fixed = dict(transactions=-0.0021, wsol_close=-0.00105, cleanup=-0.00105, rent_lost=0.0)
    d = dict(price_move=gross, trade_and_creator_fees=fees, price_impact=impact, **fixed)
    net = sum(d.values())
    return dict(pool=pool, decision_index=day * 100 + k, decision_time=T0 + day * 86_400 + 60 * k, status='entered',
                entered=True, net_return=net, net_lamports=round(net * CC.STAKE_LAMPORTS),
                decomposition_share_of_stake=d)


def guard(pool, day, k=0):
    net = -2 * CC.TX_FEE_LAMPORTS
    return dict(pool=pool, decision_index=day * 100 + k, decision_time=T0 + day * 86_400 + 60 * k,
                status='guard_failed', entered=False, net_lamports=net, net_return=net / CC.STAKE_LAMPORTS)


def zero(pool, day, k=0):
    return PILOT.zero_sale(dict(pool=pool, decision_index=day * 100 + k, decision_time=T0 + day * 86_400 + 60 * k,
                                decision_slot=1, unpriced='lp_change_at_the_landing_point'))


def market(seed=1, per_day=2, pools=POOLS, days=range(D)):
    rng = random.Random(seed)
    return [entered(p, d, rng.uniform(-0.03, 0.04), k) for p in pools for d in days for k in range(per_day)]


def docs(rows, placebo=()):
    return dict(primary=rows, placebo=list(placebo)), dict(report=run(rows, placebo))


def direct_stratified(rows, value):
    """An independent rewrite of the frozen bootstrap on value(row)."""
    blocks = {}
    for r in rows:
        blocks.setdefault(r['pool'], {}).setdefault((r['decision_time'] - T0) // 86_400, []).append(value(r))
    rng, means = random.Random(SEED), []
    for _ in range(DRAWS):
        got = []
        for p in sorted(blocks):
            days = sorted(blocks[p])
            for _d in days:
                got += blocks[p][days[rng.randrange(len(days))]]
        means.append(sum(got) / len(got))
    k = int(0.05 * DRAWS) - 1
    return sorted(means)[k], sorted(means, reverse=True)[k]


def direct_common(rows, value):
    by_day = {}
    for r in rows:
        by_day.setdefault((r['decision_time'] - T0) // 86_400, []).append(value(r))
    days = sorted(by_day)
    rng, means = random.Random(SEED), []
    for _ in range(DRAWS):
        got = []
        for _d in days:
            got += by_day[days[rng.randrange(len(days))]]
        means.append(sum(got) / len(got))
    k = int(0.05 * DRAWS) - 1
    return sorted(means)[k], sorted(means, reverse=True)[k]


def test_the_verdict_is_reproduced_and_b_uses_the_same_bootstrap():
    rows = market()
    r, res = docs(rows)
    doc = B.compute(r, res, SHEET)
    assert doc['control'] == dict(lower_bound_95=res['report']['lower_bound_95'],
                                  upper_bound_95=res['report']['upper_bound_95'], reproduced=True)
    assert (doc['B']['lower_bound_95'], doc['B']['upper_bound_95']) == direct_stratified(
        rows, lambda x: x['decomposition_share_of_stake']['price_move'])
    assert doc['B']['mean'] == pytest.approx(sum(x['decomposition_share_of_stake']['price_move'] for x in rows)
                                             / len(rows))
    assert doc['seed'] == SEED == res['report']['seed'] and doc['draws'] == DRAWS
    assert doc['verdict'] is None and doc['counts_for_operational_master'] is False


def test_gross_is_zero_for_guard_and_zero_sale_and_counted():
    rows = market(per_day=1) + [guard('pA', 0, 5), zero('pB', 1, 5)]
    r, res = docs(rows)
    doc = B.compute(r, res, SHEET)
    assert doc['status_counts'] == {'entered': len(rows) - 2, 'guard_failed': 1, 'unpriced_zero_sale': 1}
    assert B.gross(guard('pA', 0)) == 0.0 and B.gross(zero('pA', 0)) == 0.0
    want = direct_stratified(rows, lambda x: x['decomposition_share_of_stake']['price_move']
                             if x['status'] == 'entered' else 0.0)
    assert (doc['B']['lower_bound_95'], doc['B']['upper_bound_95']) == want
    nets = [x['net_return'] for x in rows]
    grosses = [B.gross(x) for x in rows]
    assert doc['cost']['mean'] == pytest.approx(sum(g - n for g, n in zip(grosses, nets)) / len(rows))
    assert doc['cost']['entered'] == len(rows) - 2
    assert doc['cost']['entered_decomposition_mean']['trade_and_creator_fees'] == pytest.approx(0.005)
    assert doc['cost']['entered_decomposition_mean']['price_impact'] == pytest.approx(0.002)


def test_unknown_status_and_missing_decomposition_stop():
    with pytest.raises(B.BError, match='unknown_status'):
        B.gross(dict(status='closed'))
    with pytest.raises(B.BError, match='entered_row_without_decomposition'):
        B.gross(dict(status='entered'))
    with pytest.raises(B.BError, match='entered_row_without_decomposition'):
        B.gross(dict(status='entered', decomposition_share_of_stake=dict(price_impact=0.1)))


def test_the_inputs_must_be_the_verdicts():
    rows = market()
    r, res = docs(rows)
    with pytest.raises(B.BError, match='seed_differs_from_the_verdict'):
        B.compute(r, res, 'f' * 8 + SHEET[8:])
    with pytest.raises(B.BError, match='rows_differ_from_the_verdict'):
        B.compute(dict(r, primary=rows[:-1]), res, SHEET)
    bad = [dict(x) for x in rows]
    bad[0]['net_return'] += 0.5
    bad[0]['net_lamports'] = round(bad[0]['net_return'] * CC.STAKE_LAMPORTS)
    with pytest.raises(B.BError, match='verdict_not_reproduced'):
        B.compute(dict(r, primary=bad), res, SHEET)
    with pytest.raises(B.BError, match='verdict_stop_no_number'):
        B.compute(r, dict(report=dict(res['report'], decision='STOP')), SHEET)
    raw = [dict(x) for x in rows]
    del raw[0]['net_return']
    with pytest.raises(Exception, match='raw_unpriced_row'):
        B.compute(dict(r, primary=raw), res, SHEET)


def test_p4_common_day_bootstrap_resamples_days_jointly():
    rows = market(seed=3)
    r, res = docs(rows)
    doc = B.compute(r, res, SHEET)
    assert (doc['p4_common_day']['net']['lower_bound_95'], doc['p4_common_day']['net']['upper_bound_95']) == \
        direct_common(rows, lambda x: x['net_return'])
    assert (doc['p4_common_day']['B']['lower_bound_95'], doc['p4_common_day']['B']['upper_bound_95']) == \
        direct_common(rows, lambda x: x['decomposition_share_of_stake']['price_move'])
    assert doc['p4_common_day']['days'] == D
    # days moving together: every pool +4 % on even days, -3 % on odd days -> the joint draw keeps the whole day
    same = [entered(p, d, 0.04 if d % 2 == 0 else -0.03, k) for p in POOLS for d in range(D) for k in range(2)]
    lo, hi = B.common_day_bounds(same, T0, D, seed=SEED, draws=DRAWS)
    assert (lo, hi) == direct_common(same, lambda x: x['net_return'])
    one = [entered(p, 3, 0.01, k) for p in POOLS for k in range(2)]
    lo, hi = B.common_day_bounds(one, T0, D, seed=SEED, draws=DRAWS)
    assert lo == hi == pytest.approx(one[0]['net_return'])
    assert B.common_day_bounds([], T0, D, seed=SEED, draws=DRAWS) == (None, None)
    with pytest.raises(V.VerdictError, match='position_outside_the_window'):
        B.common_day_bounds([entered('pA', D, 0.01)], T0, D, seed=SEED, draws=DRAWS)


def test_the_tail_index_is_the_frozen_one():
    rows = [entered('pA', d, 0.001 * d) for d in range(D)]
    lo, hi = B.common_day_bounds(rows, T0, D, seed=SEED, draws=DRAWS)
    assert (lo, hi) == direct_common(rows, lambda x: x['net_return'])


def test_cli_writes_once_and_vocabulary(tmp_path, capsys):
    rows = market()
    r, res = docs(rows)
    (tmp_path / 'ROWS.json').write_text(json.dumps(r))
    (tmp_path / 'RESULT.json').write_text(json.dumps(res))
    args = ['--rows', str(tmp_path / 'ROWS.json'), '--result', str(tmp_path / 'RESULT.json'), '--sheet-sha', SHEET,
            '--out', str(tmp_path / 'B.json')]
    assert B.main(args) == 0
    got = json.loads((tmp_path / 'B.json').read_text())
    assert got['schema'] == 'g23b-v0.1' and got['control']['reproduced'] is True
    assert 'B.json' in capsys.readouterr().out
    with pytest.raises(B.BError, match='out_exists'):
        B.main(args)
    with pytest.raises(Exception, match='forbidden_word'):           # the document is checked (closed vocabulary)
        B.compute(r, dict(report=dict(res['report'], decision='rentable')), SHEET)


def test_rows_of_the_frozen_positions_end_to_end():
    from cpmmgen2.tests.test_gen2 import market as gen2_market
    from cpmmprereg import rule as R
    from cpmmprereg.tests.test_rule import CONFIG
    one = [(t, 'buy', 10 ** 8, False, 'Same') for t in range(0, 600, 60)]
    burst = [(t, 'buy', 10 ** 8, False, 'Q%d' % t) for t in range(600, 800, 50)]
    line, txs = gen2_market(one + burst + [(t, 'sell', 10 ** 11, False, 'S') for t in range(800, 2_600, 20)])
    primary = R.positions(line, CONFIG, V.decisions(line, txs, 1))
    assert primary and any(p['status'] == 'entered' for p in primary)
    report = V.report(primary, [], pools=[line.pool, 'x', 'y'], g0_passed=True, freeze_sheet_sha256=SHEET, t0=0,
                      d_days=D, draws=DRAWS)
    doc = B.compute(dict(primary=primary), dict(report=report), SHEET)
    assert doc['control']['reproduced'] is True
    ent = [p for p in primary if p['status'] == 'entered']
    assert doc['B']['mean'] == pytest.approx(sum(p['decomposition_share_of_stake']['price_move'] for p in ent)
                                             / len(primary))
    for p in ent:          # gross - every frozen cost part = the frozen net (cpmmcost identity, to the float)
        d = p['decomposition_share_of_stake']
        assert sum(d.values()) == pytest.approx(p['net_return'], abs=1e-12)
