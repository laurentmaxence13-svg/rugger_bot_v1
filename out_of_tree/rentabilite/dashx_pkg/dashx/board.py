"""dashx 0.1 -- R-3 of the owner's strategic directive (23/11): the EXTENDED DASHBOARD of every evaluated strategy,
computed ONLY on the ANCHORED outputs already produced (no replay, no new evaluation, no pool data). EXPLORATOIRE.
Run ONCE by RUGGER 03 after the R02 audit. Every input sha256 is checked before it is read.

INPUTS (each optional on the command line; a missing input makes its rows NON MESURÉ, never estimated)
* ``ledger.json`` of the anchored W1 ledger (sha given) and the L1 bundle (sha recorded by the ledger): the ONLY
  per-position source; rows MASTER W1 and placebo W1 (population of w1loss 0.3, imported unchanged);
* ``VENTILATION_W1.json`` of w1loss (anchored da1e5758): row C-A (MASTER at the 12 500 ppm tier, T1);
* ``LATELAB.json`` discovery (anchored 7351512d) and screen (anchored 20aba3f5): rows L1, L3, L1 screen and their
  descriptive placebos;
* ``LATESEL.json`` (anchored f3c6c9e3): rows T1 and T3';
* ``CDGATE.json`` (anchored 2b173f10): rows C-D and the low-tier placebo.
Rows C-B, C-C, C-E and CPMM R-CP1: no position, no figure.

COLUMNS (fixed now): positions; pools (distinct pools, or creator clusters for aggregate outputs: labelled); mean
gross; mean net [regime]; win rate; mean winning and mean losing net return; profit factor (sum of positive P&L /
|sum of negative P&L|); expectancy (mean net return per position); maximum drawdown of the cumulative net return
(positions ordered by their sale slot, then entry slot; in % of one stake); mean curve fees and mean tx in % of the
stake; latency (slots, from the document); failed attempts (modelled fee, else 0 = not measured); 95 % interval;
placebo comparison; robustness (chronological halves, mean without the 5 best, share of the 5 best in the positive
P&L, net at 10 slots when the document has it); status; verdict.
VERDICT (closed vocabulary, R-0.1 and the order of section 2.2, 2792655a): a placebo row gets none; n < 30 or a row
the document marks non-interpretable -> INCONCLUSIF; else the 95 % high bound < 0 -> NÉGATIF; else INCONCLUSIF. No
other word is ever produced (tested).
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from w1loss import analysis as A

SCHEMA = 'rugger-extended-dashboard-v0.1'
STAMP = 'EXPLORATOIRE — TABLEAU DE BORD SUR SORTIES ANCRÉES — AUCUNE NOUVELLE ÉVALUATION'
NM = 'NON MESURÉ'
VERDICTS = ('NÉGATIF', 'INCONCLUSIF')
NO_POSITION = ('C-B', 'C-C', 'C-E', 'CPMM R-CP1')
COLUMNS = ('positions', 'pools', 'mean_gross_return', 'mean_net_return', 'regime', 'win_rate', 'mean_winning_return',
           'mean_losing_return', 'profit_factor', 'expectancy', 'max_drawdown', 'mean_curve_fees', 'mean_tx',
           'latency_slots', 'failed_attempts', 'interval_95', 'placebo', 'robustness', 'status', 'verdict')


class DashError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load(path, sha256):
    if _sha(path) != sha256:
        raise DashError('input_is_not_the_anchored_one:' + Path(path).name)
    return json.loads(Path(path).read_bytes())


def verdict(n, high, interpretable=True, placebo=False):
    if placebo:
        return None
    if n is None or n < A.MIN_INTERPRETABLE or not interpretable:
        return 'INCONCLUSIF'
    if high is not None and high < 0:
        return 'NÉGATIF'
    return 'INCONCLUSIF'


def blank(name, **known):
    row = {c: NM for c in COLUMNS}
    row.update(strategy=name, **known)
    return row


# -- per-position rows (the ledger) ---------------------------------------------------------------------------------
def drawdown(positions):
    """Largest peak-to-trough fall of the cumulative net return, positions in sale order; in units of one stake."""
    cumulative, peak, worst = 0.0, 0.0, 0.0
    for p in sorted(positions, key=lambda q: (q['sell_slot'], q['slot'], q['pool'])):
        cumulative += p['net_return']
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return worst


def ledger_row(name, positions, *, placebo, latency, failed_fee, paired=None):
    n = len(positions)
    if not n:
        return blank(name, positions=0)
    nets = [p['net_return'] for p in positions]
    wins = [p['net_return'] for p in positions if p['pnl'] > 0]
    losses = [p['net_return'] for p in positions if p['pnl'] <= 0]
    gain, loss = sum(p['pnl'] for p in positions if p['pnl'] > 0), -sum(p['pnl'] for p in positions if p['pnl'] < 0)
    ordered = sorted(positions, key=lambda p: (p['slot'], p['pool']))
    half = n // 2
    best = sorted(nets, reverse=True)
    positive = sorted((p['pnl'] for p in positions if p['pnl'] > 0), reverse=True)
    interval = A._interval(positions)
    return dict(
        strategy=name, positions=n, pools=dict(distinct_pools=len({p['pool'] for p in positions})),
        mean_gross_return=A._mean([p['gross_return'] for p in positions]), mean_net_return=A._mean(nets),
        regime='SL (frozen engine, rent not modelled)', win_rate=len(wins) / n,
        mean_winning_return=A._mean(wins) if wins else NM, mean_losing_return=A._mean(losses) if losses else NM,
        profit_factor=(gain / loss) if loss else NM, expectancy=A._mean(nets), max_drawdown=drawdown(positions),
        mean_curve_fees=A._mean([p['fee_return'] for p in positions]), mean_tx=A._mean([p['tx_return'] for p in positions]),
        latency_slots=latency if latency is not None else NM,
        failed_attempts=dict(modelled_fee_lamports=failed_fee, measured=False),
        interval_95=interval, placebo=paired if paired is not None else NM,
        robustness=dict(first_half_mean=A._mean([p['net_return'] for p in ordered[:half]]),
                        second_half_mean=A._mean([p['net_return'] for p in ordered[half:]]),
                        mean_without_5_best=A._mean(best[5:]) if n > 5 else NM,
                        share_of_5_best_in_positive=(sum(positive[:5]) / sum(positive)) if positive else NM,
                        net_at_10_slots=NM),
        status='EXPLORATOIRE', verdict=verdict(n, interval['high'], interval['interpretable'], placebo))


def ledger_rows(ledger, bundle, *, evaluation_min, evaluation_max):
    doc = A.breakdown(ledger, bundle, evaluation_min=evaluation_min, evaluation_max=evaluation_max)   # checks + T6
    pools = {pool['pool']: pool for pool in bundle['pools']}
    sells = {}
    for row in ledger['entries']:
        if row.get('trial') == A.TRIAL and row.get('arm') in A.ARMS and row.get('outcome') == 'closed':
            sells[(row['arm'], row['pool'])] = (row.get('sell') or {}).get('slot')
    positions = {arm: [] for arm in A.ARMS}
    for row in ledger['entries']:
        if row.get('trial') != A.TRIAL or row.get('arm') not in positions or row.get('outcome') != 'closed':
            continue
        pool = pools[row['pool']]
        if not evaluation_min <= pool['creation_slot'] < evaluation_max:
            continue
        p = A._position(row, pool, (pool.get('arms') or {}).get(row['arm']))
        p['sell_slot'] = sells[(row['arm'], row['pool'])]
        if type(p['sell_slot']) is not int:
            raise DashError('closed_cycle_without_sell_slot')
        positions[row['arm']].append(p)
    params = bundle.get('params') or {}
    latency, failed = params.get('latency_slots'), params.get('failed_attempt_fee_lamports', 0)
    t6 = doc['T6_paired_master_minus_placebo']
    paired = dict(paired_pools=t6['n'], mean_diff_net_return=t6['mean_diff_net_return'],
                  interval_95=t6['interval_95_mean_diff_net_return'], label='descriptif (T6 de w1loss)')
    return [ledger_row('MASTER W1', positions['master'], placebo=False, latency=latency, failed_fee=failed,
                       paired=paired),
            ledger_row('Placebo W1', positions['placebo_random'], placebo=True, latency=latency, failed_fee=failed)]


# -- aggregate rows (latelab / latesel / cdgate / w1loss ventilation) -------------------------------------------------
def aggregate_row(name, s, *, placebo, latency, regime, comparator=NM, extra=None):
    """s: a summary of latelab.study.summary (or w1loss T1); only the fields it holds are filled."""
    interval = s.get('interval_95') or s.get('interval_95_mean_net_return') or {}
    interpretable = s.get('interpretable', interval.get('interpretable', True))
    row = blank(name, positions=s['n'], mean_net_return=s['mean_net_return'], regime=regime,
                win_rate=s.get('win_rate', NM), expectancy=s['mean_net_return'], latency_slots=latency,
                failed_attempts=dict(modelled_fee_lamports=0, measured=False),
                interval_95=dict(low=interval.get('low'), high=interval.get('high'), draws=interval.get('draws'),
                                 seed=interval.get('seed')),
                placebo=comparator, status='EXPLORATOIRE',
                verdict=verdict(s['n'], interval.get('high'), interpretable, placebo))
    if 'clusters' in s:
        row['pools'] = dict(creator_clusters=s['clusters'])
    if 'mean_gross_return' in s:
        row['mean_gross_return'] = s['mean_gross_return']
    if 'mean_fee_return' in s:
        row['mean_curve_fees'] = s['mean_fee_return']
    if 'mean_tx_return' in s:
        row['mean_tx'] = s['mean_tx_return']
    robustness = dict(share_of_5_best_in_positive=s.get('share_of_the_5_best_in_positive', NM),
                      mean_net_return_rent_recovered=s.get('mean_net_return_rent_recovered', NM),
                      net_at_10_slots=s.get('mean_net_return_latency_10_slots', NM))
    row['robustness'] = robustness
    if extra:
        row.update(extra)
    return row


def _cd_extra(s):
    d = s.get('decomposition_mean_share_of_stake') or {}
    return dict(mean_gross_return=d.get('gross', NM), mean_curve_fees=d.get('curve_fees', NM), mean_tx=d.get('tx', NM))


def board(*, ledger=None, bundle=None, ventilation=None, latelab_discovery=None, latelab_screen=None, latesel=None,
          cdgate=None, evaluation_min=None, evaluation_max=None):
    rows, done = [], set()
    if ledger is not None:
        rows += ledger_rows(ledger, bundle, evaluation_min=evaluation_min, evaluation_max=evaluation_max)
        done |= {'MASTER W1', 'Placebo W1'}
    if ventilation is not None:
        tier = ventilation['arms']['master']['T1_fee_tiers'].get('12500')
        if tier is not None:
            rows.append(aggregate_row('C-A (MASTER, palier 12 500 ppm)', tier, placebo=False, latency=NM,
                                      regime='SL (frozen engine, rent not modelled)'))
            done.add('C-A')
    if latelab_discovery is not None:
        lat = latelab_discovery.get('latency_slots', NM)
        place = latelab_discovery['placebo_descriptive']
        comp = dict(mean_net_return=place['mean_net_return'], n=place['n'], label='descriptif, non apparié')
        for cell, name in (('L1', 'latelab L1 (moitié 1)'), ('L3', 'latelab L3 (moitié 1)')):
            if cell in latelab_discovery['cells']:
                rows.append(aggregate_row(name, latelab_discovery['cells'][cell], placebo=False, latency=lat,
                                          regime='LP (rent lost)', comparator=comp))
                done.add(name)
        rows.append(aggregate_row('placebo latelab (moitié 1)', place, placebo=True, latency=lat, regime='LP (rent lost)'))
    if latelab_screen is not None:
        lat = latelab_screen.get('latency_slots', NM)
        place = latelab_screen['placebo_descriptive']
        comp = dict(mean_net_return=place['mean_net_return'], n=place['n'], label='descriptif, non apparié')
        for cell, s in latelab_screen['cells'].items():
            rows.append(aggregate_row(f'latelab {cell} crible (moitié 2)', s, placebo=False, latency=lat,
                                      regime='LP (rent lost)', comparator=comp))
        rows.append(aggregate_row('placebo latelab (moitié 2)', place, placebo=True, latency=lat, regime='LP (rent lost)'))
    if latesel is not None:
        for cell, name in (('T1', 'latesel T1'), ('T3p', "latesel T3'")):
            if cell in latesel['cells']:
                rows.append(aggregate_row(name, latesel['cells'][cell], placebo=False,
                                          latency=latesel.get('latency_slots', NM), regime='LP (rent lost)'))
                done.add(name)
    if cdgate is not None:
        lat = cdgate.get('latency_slots', NM)
        place = cdgate['placebo_low_tier_descriptive']
        comp = dict(mean_net_return=place['mean_net_return'], n=place['n'], label='descriptif, non apparié')
        rows.append(aggregate_row('C-D', cdgate['c_d'], placebo=False, latency=lat, regime='LP (rent lost)',
                                  comparator=comp, extra=_cd_extra(cdgate['c_d'])))
        rows.append(aggregate_row('placebo du palier bas', place, placebo=True, latency=lat, regime='LP (rent lost)',
                                  extra=_cd_extra(place)))
    for name in NO_POSITION:
        rows.append(blank(name, positions=0, status='aucune position', verdict=None))
    for row in rows:
        if row['verdict'] not in VERDICTS + (None,):
            raise DashError('verdict_outside_the_closed_vocabulary')
    return dict(schema=SCHEMA, stamp=STAMP, category='HISTORICAL_REPLAY', columns=list(COLUMNS), rows=rows,
                not_measured=NM, flags=dict(new_evaluation=False, rule_or_parameter_selected=False,
                                            profitability_demonstrated=False, counts_for_operational_master=False))


def _cell(value):
    if isinstance(value, float):
        return f'{value * 100:+.2f} %'.replace('.', ',')
    if value is None:
        return '—'
    if isinstance(value, dict):
        return '; '.join(f'{k}={_cell(v) if isinstance(v, float) else v}' for k, v in value.items())
    return str(value)


def markdown(doc):
    head = ('strategy',) + COLUMNS
    lines = [f'# Tableau de bord étendu — {doc["stamp"]}', '', '| ' + ' | '.join(head) + ' |',
             '|' + '---|' * len(head)]
    for row in doc['rows']:
        lines.append('| ' + ' | '.join(_cell(row.get(c)) for c in head) + ' |')
    return '\n'.join(lines) + '\n'


def run(out_dir, *, ledger=None, bundle=None, ventilation=None, latelab_discovery=None, latelab_screen=None,
        latesel=None, cdgate=None, evaluation_min=None, evaluation_max=None):
    """Each input is a (path, sha256) pair or None."""
    docs = {}
    if ledger is not None:
        docs['ledger'] = _load(*ledger)
        if bundle is None or _sha(bundle) != (docs['ledger'].get('bundles_sha256') or {}).get('L1'):
            raise DashError('bundle_is_not_the_one_the_ledger_recorded')
        docs['bundle'] = json.loads(gzip.decompress(Path(bundle).read_bytes()))
    for key, value in dict(ventilation=ventilation, latelab_discovery=latelab_discovery, latelab_screen=latelab_screen,
                           latesel=latesel, cdgate=cdgate).items():
        if value is not None:
            docs[key] = _load(*value)
    doc = board(**docs, evaluation_min=evaluation_min, evaluation_max=evaluation_max)
    out = Path(out_dir)
    if out.exists():
        raise DashError('output_exists')
    out.mkdir(parents=True)
    (out / 'TABLEAU_DE_BORD.json').write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False,
                                                         ensure_ascii=False) + '\n', encoding='utf-8')
    (out / 'TABLEAU_DE_BORD.md').write_text(markdown(doc), encoding='utf-8')
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(prog='dashx')
    parser.add_argument('--out', required=True)
    for name in ('ledger', 'ventilation', 'latelab-discovery', 'latelab-screen', 'latesel', 'cdgate'):
        parser.add_argument('--' + name, nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--bundle')
    parser.add_argument('--evaluation-min', type=int)
    parser.add_argument('--evaluation-max', type=int)
    a = parser.parse_args(argv)
    run(a.out, ledger=a.ledger, bundle=a.bundle, ventilation=a.ventilation, latelab_discovery=a.latelab_discovery,
        latelab_screen=a.latelab_screen, latesel=a.latesel, cdgate=a.cdgate, evaluation_min=a.evaluation_min,
        evaluation_max=a.evaluation_max)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
