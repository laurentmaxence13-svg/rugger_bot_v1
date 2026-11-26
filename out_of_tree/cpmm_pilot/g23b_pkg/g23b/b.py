"""g23b 0.1 -- script B of the 06/12 recommendation rule (R02 note 9ed6de75, adopted by R04, state 23aedd3; declared to
R02 BEFORE any reading of the window). Short, offline, 0 credit; g23five 0.1.1 is imported, never modified.

B   = the mean of the GROSS price move (decomposition_share_of_stake['price_move'], before every cost) of the SAME rows
      as the verdict (g1ind.counted of ROWS.json 'primary'), with its one-sided 95 % bounds by the SAME function
      (g23five.verdict.stratified_bounds), the SAME pool-day blocks (verdict.blocks, t0 and d_days of RESULT.json), the
      SAME seed (int(sheet sha[:8], 16), checked equal to RESULT's) and the SAME draws. A row's gross is its price move
      when status = 'entered'; 0 for 'guard_failed' and 'unpriced_zero_sale' (the whole loss is cost, as
      livesim._costs); their count is published.
COST = mean(gross - net), with the mean frozen decomposition of the entered rows (pool fees, impact, fixed parts).
CONTROL: the same call on the rows' own net_return must give RESULT's lower / upper_bound_95 exactly, else STOP.
P4 (declared at the same time; DESCRIPTIVE, never the word): a bootstrap by COMMON CALENDAR DAY -- day =
      (decision_time - t0) // 86 400; the blocks are the days with at least one position, all pools together; each
      draw takes as many days, with replacement, and every row of every pool of those days; the same seed and draws,
      the bounds as stratified_bounds (k = int(0.05 x draws) - 1); for the net and for B.
Labels: never an operational Master trade, never counted for 50 / 20; no verdict of its own."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from g1ind import report as G1
from g23five import verdict as V

SCHEMA = 'g23b-v0.1'
ENTERED = 'entered'
NO_GROSS = ('guard_failed', 'unpriced_zero_sale')
PARTS = ('trade_and_creator_fees', 'price_impact', 'transactions', 'wsol_close', 'cleanup', 'rent_lost')
LABELS = ('MASTER_RESEARCH_PAPER', 'DESCRIPTIVE')


class BError(ValueError):
    pass


def gross(row):
    status = row.get('status')
    if status == ENTERED:
        d = row.get('decomposition_share_of_stake')
        if not d or 'price_move' not in d:
            raise BError('entered_row_without_decomposition')
        return d['price_move']
    if status in NO_GROSS:
        return 0.0
    raise BError('unknown_status:%s' % status)


def as_net(rows, value):
    """Copies whose net_return is value(row): what stratified_bounds averages."""
    return [dict(r, net_return=value(r)) for r in rows]


def common_day_bounds(rows, t0, d_days, *, seed, draws):
    """P4: one-sided 95 % bounds of the mean net_return, calendar days resampled jointly over the pools."""
    by_day = {}
    for r in rows:
        by_day.setdefault(V.day_of(r, t0, d_days), []).append(r)
    days = sorted(by_day)
    if not days:
        return None, None
    rng, means = random.Random(seed), []
    for _ in range(draws):
        got = []
        for _k in days:
            got += by_day[days[rng.randrange(len(days))]]
        means.append(sum(r['net_return'] for r in got) / len(got))
    k = max(0, int(V.ALPHA * draws) - 1)
    return sorted(means)[k], sorted(means, reverse=True)[k]


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def compute(rows_doc, result_doc, sheet_sha):
    report = result_doc['report']
    if report.get('decision') == 'STOP':
        raise BError('verdict_stop_no_number')
    V._check_sheet(sheet_sha)
    seed = int(sheet_sha[:8], 16)
    if report['seed'] != seed:
        raise BError('seed_differs_from_the_verdict')
    t0, d_days, draws = report['t0'], report['d_days'], report['draws']
    rows = G1.counted(rows_doc['primary'])
    if len(rows) != report['n']:
        raise BError('rows_differ_from_the_verdict')
    low, high = V.stratified_bounds(V.blocks(rows, t0, d_days), seed=seed, draws=draws)
    if (low, high) != (report['lower_bound_95'], report['upper_bound_95']):
        raise BError('verdict_not_reproduced')
    g_rows = as_net(rows, gross)
    b_low, b_high = V.stratified_bounds(V.blocks(g_rows, t0, d_days), seed=seed, draws=draws)
    entered = [r for r in rows if r.get('status') == ENTERED]
    status = {}
    for r in rows:
        status[r.get('status')] = status.get(r.get('status'), 0) + 1
    p4_net = common_day_bounds(rows, t0, d_days, seed=seed, draws=draws)
    p4_b = common_day_bounds(g_rows, t0, d_days, seed=seed, draws=draws)
    doc = dict(schema=SCHEMA, labels=list(LABELS), counts_for_operational_master=False, verdict=None,
               verdict_decision=report['decision'], seed=seed, draws=draws, t0=t0, d_days=d_days, n=len(rows),
               status_counts=status, gross_zero_for=list(NO_GROSS),
               control=dict(lower_bound_95=low, upper_bound_95=high, reproduced=True),
               B=dict(mean=_mean([r['net_return'] for r in g_rows]), lower_bound_95=b_low, upper_bound_95=b_high),
               net=dict(mean=_mean([r['net_return'] for r in rows]), lower_bound_95=low, upper_bound_95=high),
               cost=dict(mean=_mean([g['net_return'] - r['net_return'] for g, r in zip(g_rows, rows)]),
                         entered_decomposition_mean={k: _mean([-r['decomposition_share_of_stake'][k] for r in entered])
                                                     for k in PARTS},
                         entered=len(entered)),
               p4_common_day=dict(role='sensibilité P4, descriptive, non décisionnelle',
                                  days=len({V.day_of(r, t0, d_days) for r in rows}),
                                  net=dict(lower_bound_95=p4_net[0], upper_bound_95=p4_net[1]),
                                  B=dict(lower_bound_95=p4_b[0], upper_bound_95=p4_b[1])))
    return G1.check_vocabulary(doc)


def main(argv=None):
    p = argparse.ArgumentParser(prog='g23b.b')
    p.add_argument('--rows', type=Path, required=True)
    p.add_argument('--result', type=Path, required=True)
    p.add_argument('--sheet-sha', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    if a.out.exists():
        raise BError('out_exists')
    doc = compute(json.loads(a.rows.read_text()), json.loads(a.result.read_text()), a.sheet_sha)
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + '\n'
    a.out.write_text(text)
    print(a.out.name, hashlib.sha256(text.encode()).hexdigest())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
