"""PRELIMINARY reading of the W1 ledger: a CLOSED list of figures, fixed by RUGGER 02 BEFORE any W1 data is read.

This is NOT the official W1 verdict: no decision is computed, ``evaluate_w1`` is never called, and the five frozen
hypotheses are neither read nor evaluated. Standard library only. Nothing is printed: the reading is written to
two stamped files, ``LECTURE_PRELIMINAIRE.json`` and ``LECTURE_PRELIMINAIRE.md``.

INPUTS (nothing else is opened)
* ``ledger.json`` of ``w1aux.ledger`` run WITHOUT a report (``w1_report`` must be null, verdict PASS, 0 mismatch);
* the L1 bundle (``bundles/L1.json.gz``), whose file sha256 must be the one the ledger recorded. Only the pool
  facts (pool, creation slot, creator) and the MASTER arm rows are read in it.

POPULATION: the pools of the bundle created in the evaluation range [evaluation_min, evaluation_max), i.e. the
population of the frozen W1 decision (``w1_eval.w1_split``: the warm-up range only feeds the creator history).
Pools created outside the range are only counted.

WHAT IS READ (R02 method 2ee87535, additif 3, and its answers of 2026-11-15)
MASTER arm (ledger rows trial ``L1``, arm ``master``):
* Q1 positions: eligible = pools of the MANIFEST (replayed + excluded); opened = outcome != ``no_entry``;
  closed = outcome ``closed``; not closed, by frozen outcome code (``open_at_end``, ``open_at_window_end``,
  ``migrated_unpriced``, ``counterfactual_divergence``; any other code under its own name); and the cycles with
  an executed entry (the rows of the ledger), which must be exactly the bundle's master rows with an entry.
* Q2 result of the closed cycles, in lamports: net (after every cost): sum, mean, median, win rate, profit
  factor; gross := the ledger's ``market_move`` component (P&L before slippage and before every fee); and the
  mean and median of the net return (pnl / (spent + tx costs + failed attempts), the frozen definition).
* Q3 distribution of the net P&L: p10, p50, p90, maximum, minimum, share of the 5 best positions.
* Q4 exact decomposition summed over the closed cycles: net = gross - slippage - LaunchLab fees - transaction
  costs - failed attempts; the residual of this identity is REPORTED, never filled. Exit reasons
  (``sell.trigger.reason``) among stop_loss, trailing_stop, max_hold, take_profit, exit_horizon,
  exit_horizon_clock; anything else, or no trigger, under ``autre``.
* Q5 creators: distinct clusters among the closed cycles and share of the closed cycles held by the 5 clusters
  with the most closed cycles. Cluster = creator address as the bundle records it, else the pool.
* Q6 95 % confidence interval of the MEAN NET RETURN of the closed cycles by cluster bootstrap: clusters drawn
  with replacement (as many as there are clusters), every cycle of a drawn cluster kept, 2 000 draws,
  ``random.Random(20261115)``, percentiles 2.5 and 97.5 by rank.
* Q7 unit: SOL only (lamports and SOL). No USD figure: no conversion rule was frozen.
REFERENCE and PLACEBO arms (ledger rows trial ``L1``, arms ``reference`` and ``placebo_random``): closed cycles,
mean net P&L and mean net return, total decomposition. Nothing else.
NOT READ: the V2 arms, the sensitivities, the hypotheses; no breakdown by creator, signal or state.

DEFINITIONS
* win rate = share of the closed cycles whose net P&L is > 0;
* profit factor = sum of the gains / |sum of the losses|, None when there is no loss;
* share of the 5 best = sum of the 5 largest positive net P&L / sum of the positive net P&L, None without a gain;
* quantile of level q of n sorted values (median, p10, p90, percentiles of the bootstrap): the value of rank
  ceil(q * n), i.e. index ceil(q * n) - 1 (lower rank, inverse of the empirical distribution function; the
  median of an even number of values is the lower middle one);
* a figure that cannot be computed is None.
"""
import argparse
import gzip
import hashlib
import json
import math
import random
from pathlib import Path

STAMP = 'PRÉLIMINAIRE — PAS LE VERDICT OFFICIEL W1'
SCHEMA = 'rugger-w1-preliminary-reading-v1'
LAMPORTS_PER_SOL = 1_000_000_000
SEED, DRAWS = 20261115, 2_000
TRIAL, MASTER, OTHER_ARMS = 'L1', 'master', ('reference', 'placebo_random')
NOT_CLOSED = ('open_at_end', 'open_at_window_end', 'migrated_unpriced', 'counterfactual_divergence')
EXIT_REASONS = ('stop_loss', 'trailing_stop', 'max_hold', 'take_profit', 'exit_horizon', 'exit_horizon_clock')
PARTS = ('market_move', 'slippage', 'launchlab_fees', 'tx_costs', 'failed_attempt_costs')


class ReadingError(RuntimeError):
    pass


def quantile(values, q):
    """Value of rank ceil(q * n) among the sorted values (lower rank); None for an empty list."""
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _mean(values):
    return sum(values) / len(values) if values else None


def _sol(lamports):
    return None if lamports is None else lamports / LAMPORTS_PER_SOL


def decomposition(cycles):
    """Totals of the ledger decomposition over closed cycles, and the residual of net = gross - costs."""
    total = {part: 0 for part in PARTS}
    for cycle in cycles:
        d = cycle['decomposition']
        total['market_move'] += d['market_move']
        total['slippage'] += d['slippage']
        total['launchlab_fees'] += d['launchlab_buy_fee'] + d['launchlab_sell_fee']
        total['tx_costs'] += d['tx_costs']
        total['failed_attempt_costs'] += d['failed_attempt_costs']
    net = sum(cycle['pnl_lamports'] for cycle in cycles)
    rebuilt = (total['market_move'] - total['slippage'] - total['launchlab_fees'] - total['tx_costs']
               - total['failed_attempt_costs'])
    return dict(total, net=net, identity_residual=net - rebuilt,
                identity='net = market_move - slippage - launchlab_fees - tx_costs - failed_attempt_costs')


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


def _closed(rows):
    closed = [row for row in rows if row['outcome'] == 'closed']
    for row in closed:
        if type(row.get('pnl_lamports')) is not int or row.get('net_return') is None or 'decomposition' not in row:
            raise ReadingError('closed_cycle_without_its_figures:' + row['pool'])
        if row.get('verified') is not True:
            raise ReadingError('closed_cycle_not_verified_by_the_ledger:' + row['pool'])
    return closed


def _aggregate(rows):
    closed = _closed(rows)
    return dict(cycles_with_entry=len(rows), closed_cycles=len(closed),
                mean_net_pnl_lamports=_mean([row['pnl_lamports'] for row in closed]),
                mean_net_return=_mean([row['net_return'] for row in closed]),
                decomposition_lamports=decomposition(closed))


def read(ledger, bundle, *, evaluation_min, evaluation_max):
    """The reading document (see the module docstring) from the two parsed inputs."""
    if type(evaluation_min) is not int or type(evaluation_max) is not int or not evaluation_min < evaluation_max:
        raise ReadingError('invalid_evaluation_range')
    pools = {pool['pool']: pool for pool in bundle['pools']}
    if len(pools) != len(bundle['pools']):
        raise ReadingError('duplicate_pool_in_bundle')
    inside = {name for name, pool in pools.items() if evaluation_min <= pool['creation_slot'] < evaluation_max}
    rows = {arm: [] for arm in (MASTER,) + OTHER_ARMS}
    for row in ledger['entries']:
        if row['trial'] == TRIAL and row['arm'] in rows:
            if row['pool'] not in pools:
                raise ReadingError('ledger_row_for_a_pool_absent_from_the_bundle:' + row['pool'])
            if row['pool'] in inside:
                rows[row['arm']].append(row)
    # Q1, from the bundle (every pool has a master row); the ledger must list exactly the opened ones
    outcomes = {}
    for name in sorted(inside):
        outcome = pools[name]['arms'][MASTER]['outcome']
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    opened = sum(n for code, n in outcomes.items() if code != 'no_entry')
    entered = {name: pools[name]['arms'][MASTER]['outcome'] for name in inside
               if pools[name]['arms'][MASTER]['entry_index'] is not None}
    if {row['pool']: row['outcome'] for row in rows[MASTER]} != entered or len(rows[MASTER]) != len(entered):
        raise ReadingError('ledger_and_bundle_disagree_on_the_master_positions')
    closed = _closed(rows[MASTER])
    pnl = [row['pnl_lamports'] for row in closed]
    returns = [row['net_return'] for row in closed]
    gains, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    parts = decomposition(closed)
    cluster_of = {name: pools[name].get('creator') or name for name in inside}
    clusters = {}
    for row in closed:
        clusters.setdefault(cluster_of[row['pool']], []).append(row['net_return'])
    sizes = sorted((len(v) for v in clusters.values()), reverse=True)
    reasons = {}
    for row in closed:
        reason = ((row.get('sell') or {}).get('trigger') or {}).get('reason')
        key = reason if reason in EXIT_REASONS else 'autre'
        reasons[key] = reasons.get(key, 0) + 1
    excluded = len(bundle.get('excluded_pools') or [])
    master = dict(
        Q1_positions=dict(eligible_manifest_pools=len(pools) + excluded, excluded_pools=excluded,
                          replayed_pools=len(pools), evaluation_pools=len(inside),
                          pools_outside_the_evaluation_range=len(pools) - len(inside),
                          opened=opened, cycles_with_entry=len(entered), closed=len(closed),
                          not_closed={code: n for code, n in sorted(outcomes.items())
                                      if code not in ('no_entry', 'closed')},
                          no_entry=outcomes.get('no_entry', 0)),
        Q2_result_lamports=dict(net_sum=sum(pnl) if pnl else None, net_mean=_mean(pnl), net_median=quantile(pnl, 0.5),
                                win_rate=(len(gains) / len(pnl)) if pnl else None,
                                profit_factor=(sum(gains) / abs(sum(losses))) if losses else None,
                                gross_sum=parts['market_move'] if closed else None,
                                gross_mean=(parts['market_move'] / len(closed)) if closed else None,
                                net_return_mean=_mean(returns), net_return_median=quantile(returns, 0.5)),
        Q3_distribution_lamports=dict(p10=quantile(pnl, 0.1), p50=quantile(pnl, 0.5), p90=quantile(pnl, 0.9),
                                      maximum=max(pnl) if pnl else None, minimum=min(pnl) if pnl else None,
                                      share_of_the_5_best=(sum(sorted(gains, reverse=True)[:5]) / sum(gains))
                                      if gains else None),
        Q4_failure_factors=dict(decomposition_lamports=parts if closed else None,
                                exit_reasons=dict(sorted(reasons.items()))),
        Q5_creators=dict(distinct_clusters=len(clusters),
                         share_of_the_5_largest=(sum(sizes[:5]) / len(closed)) if closed else None,
                         cluster='creator address recorded by the bundle, else the pool'),
        Q6_interval_95_of_the_mean_net_return=bootstrap(clusters),
        Q7_unit=dict(unit='SOL', net_sum_sol=_sol(sum(pnl)) if pnl else None, net_mean_sol=_sol(_mean(pnl)),
                     usd='not given: no conversion rule was frozen'))
    return dict(schema=SCHEMA, stamp=STAMP, category='HISTORICAL_REPLAY',
                population=dict(evaluation_min=evaluation_min, evaluation_max=evaluation_max,
                                rule='pools created in [evaluation_min, evaluation_max): the frozen decision population'),
                master=master, others={arm: _aggregate(rows[arm]) for arm in OTHER_ARMS},
                not_read=['V2 arms', 'sensitivities', 'frozen hypotheses', 'any breakdown by creator, signal or state'],
                flags=dict(official_w1_verdict=False, w1_decision_computed=False, frozen_hypotheses_evaluated=False,
                           master_operational_trade=False, counted_in_master_gate=False,
                           financial_order_submitted=False, profitability_demonstrated=False))


def _markdown(doc):
    lines = [f'# {STAMP}', '', 'Lecture préliminaire du registre W1 (bras gelés, simulation hors ligne). Aucune décision W1 '
             "n'est calculée ; les cinq hypothèses gelées ne sont ni lues ni évaluées.", '',
             f"Population : pools créés dans [{doc['population']['evaluation_min']} ; {doc['population']['evaluation_max']}).",
             '', '## MASTER', '']
    for question, values in doc['master'].items():
        lines += [f'### {question}', '', '```json', json.dumps(values, indent=1, sort_keys=True, ensure_ascii=False),
                  '```', '']
    lines += ['## RÉFÉRENCE et PLACEBO (totaux seulement)', '', '```json',
              json.dumps(doc['others'], indent=1, sort_keys=True, ensure_ascii=False), '```', '',
              'Non lus : ' + ' ; '.join(doc['not_read']) + '.', '', f'Entrées : {json.dumps(doc["inputs"], sort_keys=True)}', '']
    return '\n'.join(lines)


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(ledger_path, bundle_path, out_dir, *, evaluation_min, evaluation_max):
    """Check the inputs, write the two stamped files; return {file name: sha256}. Prints nothing."""
    ledger_path, bundle_path, out_dir = Path(ledger_path), Path(bundle_path), Path(out_dir)
    if out_dir.exists():
        raise ReadingError('output_exists')
    ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
    if ledger.get('verdict') != 'PASS' or ledger.get('mismatches'):
        raise ReadingError('ledger_verdict_is_not_pass')
    if ledger.get('w1_report') is not None:
        raise ReadingError('ledger_quotes_a_w1_report_this_reading_is_for_the_chain_without_evaluate')
    bundle_sha = _sha_file(bundle_path)
    if (ledger.get('bundles_sha256') or {}).get(TRIAL) != bundle_sha:
        raise ReadingError('bundle_is_not_the_one_the_ledger_read')
    raw = bundle_path.read_bytes()
    bundle = json.loads(gzip.decompress(raw) if bundle_path.name.endswith('.gz') else raw)
    doc = read(ledger, bundle, evaluation_min=evaluation_min, evaluation_max=evaluation_max)
    doc['inputs'] = dict(ledger_sha256=_sha_file(ledger_path), l1_bundle_sha256=bundle_sha,
                         pools_manifest_sha256=ledger.get('pools_manifest_sha256'))
    out_dir.mkdir(parents=True)
    (out_dir / 'LECTURE_PRELIMINAIRE.json').write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False),
                                                       encoding='utf-8')
    (out_dir / 'LECTURE_PRELIMINAIRE.md').write_text(_markdown(doc), encoding='utf-8')
    return {name: _sha_file(out_dir / name) for name in ('LECTURE_PRELIMINAIRE.json', 'LECTURE_PRELIMINAIRE.md')}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Preliminary reading of the W1 ledger (NOT the official verdict)')
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--l1-bundle', type=Path, required=True)
    parser.add_argument('--evaluation-min', type=int, required=True)
    parser.add_argument('--evaluation-max', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True, help='new directory for the two stamped files')
    args = parser.parse_args(argv)
    run(args.ledger, args.l1_bundle, args.out, evaluation_min=args.evaluation_min, evaluation_max=args.evaluation_max)
    return 0                                               # nothing is printed, on purpose


if __name__ == '__main__':                                 # pragma: no cover
    raise SystemExit(main())
