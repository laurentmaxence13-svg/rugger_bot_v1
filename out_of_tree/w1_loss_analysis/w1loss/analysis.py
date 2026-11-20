"""w1loss 0.2 — DESCRIPTIVE breakdown of the W1 ledger positions already computed (phase « rentabilité », owner
directive of 2026-11-20). EXPLORATORY: it changes no W1 figure, computes no verdict and evaluates no hypothesis.

The list of tables is CLOSED and written before any W1 data is read; a table that cannot be computed is None.
Standard library only, no network. Nothing is printed: two stamped files are written, ``VENTILATION_W1.json`` and
``VENTILATION_W1.md``.

INPUTS (nothing else is opened)
* ``ledger.json`` of the anchored W1 ledger (verdict PASS, no mismatch, ``w1_report`` null), whose sha256 must be
  the one given (anchored by RUGGER 02);
* the L1 bundle, whose file sha256 must be the one the ledger recorded; only the pool facts (pool, creation slot)
  and the arms' ``exit_conditions`` are read in it.

POPULATION: as the preliminary reading (w1x.reading): ledger rows of trial ``L1``, arms ``master``,
``reference``, ``placebo_random``, pools created in [evaluation_min, evaluation_max), outcome ``closed``,
verified by the ledger. FIREWALL: no row of any other trial or arm is read; no frozen hypothesis (HW1-1 to HW1-5)
trigger is computed; the entry-age classes stop at ``>= 450`` slots.

PER POSITION (from the ledger only): spent = buy.spent_lamports; cost = spent + tx + failed (the frozen net-return
denominator); gross = decomposition.market_move; fees = launchlab buy + sell fee; rate = buy.fee_rate_ppm;
age = buy.slot - creation_slot; hold = sell.block_time - buy.block_time (s); reason = sell.trigger.reason.
Returns are fractions of ``spent`` (gross, fees, tx) or of ``cost`` (net, the frozen definition).

TABLES (R02 877da7b6: a closed list of 7 breakdowns, E = 7, counted apart from N), for the arms ``master``
(identical to ``reference`` by construction of the frozen code: one column, the identity is checked and stated)
and ``placebo_random``:
T0 totals (n, sums of net, gross, fees, tx, slippage, failed; must equal the preliminary reading) and the
   distribution of the gross return (p10 p25 p50 p75 p90, share > 0) - not a breakdown;
T1 by fee tier (exact causal ``fee_rate_ppm``): n, mean gross / fees / tx returns, mean and median net return,
   win rate;
T2 counterfactual fee rate r' = each tier OBSERVED in the arm below its highest one (causal tiers only),
   APPROXIMATION AU PREMIER ORDRE (sans effet sur le prix ni sur la décision d'entrée):
   pnl' = pnl + fees * (1 - r'/rate) when rate > r', else pnl; n, sum and mean net return, win rate;
T3 by exit reason: n, mean gross and net returns, mean and median hold;
T4 by entry age (slots) [0,5) [5,25) [25,50) [50,150) [150,450) >=450: n, mean gross and net returns;
T5 chronological thirds by entry slot: n, mean gross and net returns;
T6 paired master - placebo on the pools where both closed: n, mean and median differences of gross, fees and net
   returns;
T7 by scorer plan (tp_pct, sl_pct of the bundle row's ``exit_conditions``): n, mean gross and net returns.
Every class and T6 carry the 95 % interval of the mean net return (T6: of the mean difference) by cluster bootstrap
(cluster = creator recorded by the bundle, else the pool; clusters drawn with replacement, 2 000 draws,
``random.Random(20261120)``, percentiles 2.5 and 97.5 by rank) and ``interpretable`` = n >= 30; a class under 30
cycles is « non interprétable ». Quantile: value of rank ceil(q n) (as w1x.reading). No test, no selection.
OUTPUT WHITELIST: no pool, creator or signature appears in the output (tested).
FIREWALL (tested): the only row fields read are those of READ_FIELDS; no HW1 state variable (FORBIDDEN_NAMES) is
named in this module.
"""
import argparse
import gzip
import hashlib
import json
import math
import random
from pathlib import Path

STAMP = 'EXPLORATOIRE — VENTILATION DESCRIPTIVE — NE CHANGE AUCUN RÉSULTAT W1'
SCHEMA = 'rugger-w1-loss-breakdown-v0.2'
SEED, DRAWS, MIN_INTERPRETABLE = 20261120, 2_000, 30
CF_LABEL = 'approximation au premier ordre (sans effet sur le prix ni sur la décision d\'entrée)'
READ_FIELDS = dict(row=('trial', 'arm', 'pool', 'outcome', 'verified', 'pnl_lamports', 'net_return', 'decomposition',
                        'buy', 'sell'),
                   buy=('slot', 'block_time', 'spent_lamports', 'fee_rate_ppm'), sell=('block_time', 'trigger'),
                   decomposition=('market_move', 'slippage', 'launchlab_buy_fee', 'launchlab_sell_fee', 'tx_costs',
                                  'failed_attempt_costs'),
                   bundle_pool=('pool', 'creation_slot', 'creator', 'arms'), bundle_arm=('exit_conditions',),
                   exit_conditions=('tp_pct', 'sl_pct'))
TRIAL, ARMS, REFERENCE = 'L1', ('master', 'placebo_random'), 'reference'
AGE_EDGES = (0, 5, 25, 50, 150, 450)
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)


class BreakdownError(RuntimeError):
    pass


def quantile(values, q):
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1] if ordered else None


def _mean(values):
    return sum(values) / len(values) if values else None


def bootstrap(clusters, *, draws=DRAWS, seed=SEED):
    """95 % interval of the mean of the values, clusters drawn with replacement. ``clusters``: {key: [values]}."""
    groups = [clusters[key] for key in sorted(clusters)]
    if not groups:
        return dict(low=None, high=None, draws=draws, seed=seed, clusters=0)
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        total, count = 0.0, 0
        for _pick in range(len(groups)):
            group = groups[rng.randrange(len(groups))]
            total += sum(group)
            count += len(group)
        means.append(total / count)
    return dict(low=quantile(means, 0.025), high=quantile(means, 0.975), draws=draws, seed=seed, clusters=len(groups))


def _interval(positions, value=lambda p: p['net_return']):
    clusters = {}
    for p in positions:
        clusters.setdefault(p['cluster'], []).append(value(p))
    return dict(bootstrap(clusters), interpretable=len(positions) >= MIN_INTERPRETABLE)


def _position(row, pool, bundle_row):
    d = row['decomposition']
    spent = row['buy']['spent_lamports']
    cost = spent + d['tx_costs'] + d['failed_attempt_costs']
    fees = d['launchlab_buy_fee'] + d['launchlab_sell_fee']
    rate = row['buy']['fee_rate_ppm']
    if type(spent) is not int or spent <= 0 or type(rate) is not int or rate <= 0:
        raise BreakdownError('position_without_spent_or_rate:' + row['pool'])
    plan = (bundle_row or {}).get('exit_conditions') or {}
    buy_time, sell_time = row['buy'].get('block_time'), (row.get('sell') or {}).get('block_time')
    return dict(pool=row['pool'], cluster=pool.get('creator') or row['pool'], arm=row['arm'], pnl=row['pnl_lamports'], spent=spent, cost=cost,
                gross=d['market_move'], fees=fees, tx=d['tx_costs'], failed=d['failed_attempt_costs'],
                slippage=d['slippage'], rate=rate, net_return=row['net_return'],
                gross_return=d['market_move'] / spent, fee_return=fees / spent, tx_return=d['tx_costs'] / spent,
                slot=row['buy']['slot'], age=row['buy']['slot'] - pool['creation_slot'],
                hold=(sell_time - buy_time) if type(buy_time) is int and type(sell_time) is int else None,
                reason=(((row.get('sell') or {}).get('trigger') or {}).get('reason')) or 'aucun',
                plan=(plan.get('tp_pct'), plan.get('sl_pct')))


def _summary(positions):
    nets = [p['net_return'] for p in positions]
    return dict(n=len(positions), mean_gross_return=_mean([p['gross_return'] for p in positions]),
                mean_fee_return=_mean([p['fee_return'] for p in positions]),
                mean_tx_return=_mean([p['tx_return'] for p in positions]),
                mean_net_return=_mean(nets), median_net_return=quantile(nets, 0.5),
                win_rate=(sum(1 for p in positions if p['pnl'] > 0) / len(positions)) if positions else None,
                interval_95_mean_net_return=_interval(positions))


def _short(positions):
    return dict(n=len(positions), mean_gross_return=_mean([p['gross_return'] for p in positions]),
                mean_net_return=_mean([p['net_return'] for p in positions]),
                interval_95_mean_net_return=_interval(positions))


def _groups(positions, key):
    out = {}
    for p in positions:
        out.setdefault(key(p), []).append(p)
    return out


def _age_class(age):
    for low, high in zip(AGE_EDGES, AGE_EDGES[1:]):
        if low <= age < high:
            return f'[{low},{high})'
    return f'>={AGE_EDGES[-1]}' if age >= AGE_EDGES[-1] else 'negative'


def _counterfactual(positions, rate):
    pnl = [p['pnl'] + (p['fees'] * (1 - rate / p['rate']) if p['rate'] > rate else 0) for p in positions]
    returns = [v / p['cost'] for v, p in zip(pnl, positions)]
    shifted = [dict(p, net_return=r) for p, r in zip(positions, returns)]
    return dict(rate_ppm=rate, label=CF_LABEL, n=len(positions), net_sum_lamports=sum(pnl) if pnl else None,
                mean_net_return=_mean(returns), win_rate=(sum(1 for v in pnl if v > 0) / len(pnl)) if pnl else None,
                interval_95_mean_net_return=_interval(shifted))


def _thirds(positions):
    ordered = sorted(positions, key=lambda p: (p['slot'], p['pool']))
    n = len(ordered)
    cuts = [0, n // 3, 2 * n // 3, n]
    return [dict(_short(ordered[a:b]), first_slot=ordered[a]['slot'] if b > a else None,
                 last_slot=ordered[b - 1]['slot'] if b > a else None) for a, b in zip(cuts, cuts[1:])]


def _tables(positions):
    gross = [p['gross_return'] for p in positions]
    totals = dict(n=len(positions), **{f'{k}_sum_lamports': sum(p[k] for p in positions)
                                        for k in ('pnl', 'gross', 'fees', 'tx', 'slippage', 'failed')},
                  gross_return_distribution=dict({f'p{int(q * 100)}': quantile(gross, q) for q in QUANTILES},
                                                 share_positive=(sum(1 for g in gross if g > 0) / len(gross))
                                                 if gross else None))
    tiers = _groups(positions, lambda p: p['rate'])
    reasons = {}
    for reason, group in sorted(_groups(positions, lambda p: p['reason']).items()):
        holds = [p['hold'] for p in group if p['hold'] is not None]
        reasons[reason] = dict(_short(group), mean_hold_s=_mean(holds), median_hold_s=quantile(holds, 0.5))
    ages = _groups(positions, lambda p: _age_class(p['age']))
    order = [_age_class(edge) for edge in AGE_EDGES]
    plans = _groups(positions, lambda p: 'tp=%s;sl=%s' % p['plan'])
    return dict(
        T0_totals=totals,
        T1_fee_tiers={str(rate): _summary(group) for rate, group in sorted(tiers.items())},
        T2_counterfactual_fee_first_order=[_counterfactual(positions, r) for r in sorted(tiers)[:-1]],
        T3_exit_reasons=reasons,
        T4_entry_age_slots={name: _short(ages[name]) for name in order + ['negative'] if name in ages},
        T5_chronological_thirds=_thirds(positions) if positions else None,
        T7_scorer_plan={key: _short(group) for key, group in sorted(plans.items())})


def _paired(master, placebo):
    m, p = {x['pool']: x for x in master}, {x['pool']: x for x in placebo}
    common = sorted(set(m) & set(p))
    diff = {k: [m[x][k] - p[x][k] for x in common] for k in ('gross_return', 'fee_return', 'net_return')}
    pairs = [dict(cluster=m[x]['cluster'], net_return=d) for x, d in zip(common, diff['net_return'])]
    return dict(n=len(common), **{f'mean_diff_{k}': _mean(v) for k, v in diff.items()},
                **{f'median_diff_{k}': quantile(v, 0.5) for k, v in diff.items()},
                interval_95_mean_diff_net_return=_interval(pairs))


def breakdown(ledger, bundle, *, evaluation_min, evaluation_max):
    if ledger.get('verdict') != 'PASS' or ledger.get('mismatches') or ledger.get('w1_report') is not None:
        raise BreakdownError('ledger_is_not_a_pass_without_report')
    if type(evaluation_min) is not int or type(evaluation_max) is not int or not evaluation_min < evaluation_max:
        raise BreakdownError('invalid_evaluation_range')
    pools = {pool['pool']: pool for pool in bundle['pools']}
    inside = {name for name, pool in pools.items() if evaluation_min <= pool['creation_slot'] < evaluation_max}
    positions = {arm: [] for arm in ARMS + (REFERENCE,)}
    for row in ledger['entries']:
        if row.get('trial') != TRIAL or row.get('arm') not in positions or row.get('outcome') != 'closed':
            continue
        if row['pool'] not in pools:
            raise BreakdownError('ledger_row_for_a_pool_absent_from_the_bundle:' + row['pool'])
        if row['pool'] not in inside:
            continue
        if row.get('verified') is not True or 'decomposition' not in row or type(row.get('pnl_lamports')) is not int:
            raise BreakdownError('closed_cycle_not_verified_or_without_figures:' + row['pool'])
        pool = pools[row['pool']]
        positions[row['arm']].append(_position(row, pool, (pool.get('arms') or {}).get(row['arm'])))
    key = lambda p: (p['pool'], p['pnl'], p['gross'], p['fees'], p['rate'], p['slot'])   # noqa: E731
    identical = sorted(map(key, positions['master'])) == sorted(map(key, positions[REFERENCE]))
    return dict(schema=SCHEMA, stamp=STAMP, category='HISTORICAL_REPLAY',
                population=dict(evaluation_min=evaluation_min, evaluation_max=evaluation_max, trial=TRIAL,
                                rule='closed and verified ledger rows of pools created in the evaluation range'),
                arms={arm: _tables(positions[arm]) for arm in ARMS},
                reference_identical_to_master=identical,
                T6_paired_master_minus_placebo=_paired(positions['master'], positions['placebo_random']),
                reference_column='MASTER (≡ référence early_sniping par construction du code gelé)',
                firewall=dict(arms_read=list(ARMS + (REFERENCE,)), trial_read=TRIAL, frozen_hypotheses_evaluated=False,
                              age_classes_stop_at_slots=AGE_EDGES[-1], fields_read=READ_FIELDS),
                breakdowns=['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'],
                flags=dict(official_w1_verdict=False, w1_figure_changed=False, selection_made=False,
                           counterfactual='first order in the fee rate, tokens not recomputed',
                           profitability_demonstrated=False))


def _pct(value):
    return '—' if value is None else f'{value * 100:+.2f} %'.replace('.', ',')


def _ci(s):
    i = s['interval_95_mean_net_return']
    text = f"[{_pct(i['low'])} ; {_pct(i['high'])}]"
    return text if i['interpretable'] else text + ' non interprétable'


def markdown(doc):
    lines = [f'# {STAMP}', '', 'Colonne MASTER : ' + doc['reference_column'] + '.', '', f"Population : pools créés dans [{doc['population']['evaluation_min']} ; "
             f"{doc['population']['evaluation_max']}), cycles clôturés et vérifiés du ledger. Référence identique au "
             f"MASTER : {'oui' if doc['reference_identical_to_master'] else 'NON'}.", '']
    for arm, t in doc['arms'].items():
        lines += [f"## Bras {'MASTER (≡ référence)' if arm == 'master' else arm}", '', f"Positions : {t['T0_totals']['n']}", '',
                  '| Palier (ppm) | n | brut | frais | transaction | net moyen | IC 95 % | net médian | gagnantes |',
                  '|---|---|---|---|---|---|---|---|---|']
        for rate, s in t['T1_fee_tiers'].items():
            lines.append(f"| {rate} | {s['n']} | {_pct(s['mean_gross_return'])} | {_pct(s['mean_fee_return'])} | "
                         f"{_pct(s['mean_tx_return'])} | {_pct(s['mean_net_return'])} | {_ci(s)} | {_pct(s['median_net_return'])} | "
                         f"{_pct(s['win_rate'])} |")
        lines += ['', f'| Taux de frais contrefactuel (ppm ; {CF_LABEL}) | net moyen | IC 95 % | gagnantes |',
                  '|---|---|---|---|']
        lines += [f"| {c['rate_ppm']} | {_pct(c['mean_net_return'])} | {_ci(c)} | {_pct(c['win_rate'])} |"
                  for c in t['T2_counterfactual_fee_first_order']]
        lines += ['', '| Motif de sortie | n | brut | net | IC 95 % | détention moyenne (s) |', '|---|---|---|---|---|---|']
        lines += [f"| {r} | {s['n']} | {_pct(s['mean_gross_return'])} | {_pct(s['mean_net_return'])} | {_ci(s)} | "
                  f"{'—' if s['mean_hold_s'] is None else round(s['mean_hold_s'], 1)} |" for r, s in t['T3_exit_reasons'].items()]
        lines += ['', '| Âge à l\'entrée (slots) | n | brut | net | IC 95 % |', '|---|---|---|---|---|']
        lines += [f"| {a} | {s['n']} | {_pct(s['mean_gross_return'])} | {_pct(s['mean_net_return'])} | {_ci(s)} |"
                  for a, s in t['T4_entry_age_slots'].items()]
        lines += ['', '| Tiers chronologique | n | brut | net | IC 95 % |', '|---|---|---|---|---|']
        lines += [f"| {i + 1} | {s['n']} | {_pct(s['mean_gross_return'])} | {_pct(s['mean_net_return'])} | {_ci(s)} |"
                  for i, s in enumerate(t['T5_chronological_thirds'] or [])]
        g = t['T0_totals']['gross_return_distribution']
        lines += ['', 'Brut par position : ' + ', '.join(f"{k} {_pct(g[k])}" for k in ('p10', 'p25', 'p50', 'p75', 'p90'))
                  + f" ; part positive {_pct(g['share_positive'])}.", '',
                  '| Plan du scoreur | n | brut | net | IC 95 % |', '|---|---|---|---|---|']
        lines += [f"| {k} | {s['n']} | {_pct(s['mean_gross_return'])} | {_pct(s['mean_net_return'])} | {_ci(s)} |"
                  for k, s in t['T7_scorer_plan'].items()]
        lines.append('')
    p = doc['T6_paired_master_minus_placebo']
    lines += ['## MASTER − placebo, mêmes pools', '', f"Paires : {p['n']} ; écart moyen brut {_pct(p['mean_diff_gross_return'])}, "
              f"frais {_pct(p['mean_diff_fee_return'])}, net {_pct(p['mean_diff_net_return'])} "
              f"(IC 95 % {_ci(dict(interval_95_mean_net_return=p['interval_95_mean_diff_net_return']))}).", '',
              'Descriptif seulement : aucun intervalle, aucun test, aucune sélection. Toute piste qui en sort est une '
              'HYPOTHÈSE à préenregistrer et à tester sur W2.', '']
    return '\n'.join(lines)


def run(ledger_path, ledger_sha256, bundle_path, out_dir, *, evaluation_min, evaluation_max):
    raw = Path(ledger_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ledger_sha256:
        raise BreakdownError('ledger_is_not_the_anchored_one')
    ledger = json.loads(raw)
    bundle_raw = Path(bundle_path).read_bytes()
    if hashlib.sha256(bundle_raw).hexdigest() != (ledger.get('bundles_sha256') or {}).get(TRIAL):
        raise BreakdownError('bundle_is_not_the_one_the_ledger_recorded')
    out = Path(out_dir)
    if out.exists():
        raise BreakdownError('output_exists')
    doc = breakdown(ledger, json.loads(gzip.decompress(bundle_raw)), evaluation_min=evaluation_min,
                    evaluation_max=evaluation_max)
    doc['inputs'] = dict(ledger_sha256=ledger_sha256, bundle_sha256=hashlib.sha256(bundle_raw).hexdigest())
    out.mkdir(parents=True)
    (out / 'VENTILATION_W1.json').write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n',
                                             encoding='utf-8')
    (out / 'VENTILATION_W1.md').write_text(markdown(doc), encoding='utf-8')
    return {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
            for name in ('VENTILATION_W1.json', 'VENTILATION_W1.md')}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--ledger-sha256', required=True)
    parser.add_argument('--l1-bundle', type=Path, required=True)
    parser.add_argument('--evaluation-min', type=int, required=True)
    parser.add_argument('--evaluation-max', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    sums = run(a.ledger, a.ledger_sha256, a.l1_bundle, a.out, evaluation_min=a.evaluation_min,
               evaluation_max=a.evaluation_max)
    Path(a.out / 'SHA256SUMS.json').write_text(json.dumps(sums, sort_keys=True, indent=1) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
