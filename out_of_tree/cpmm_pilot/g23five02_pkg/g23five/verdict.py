"""g23five 0.2 -- verdict of the G2-3 pilot on POOLS NAMED BEFORE T0 (R02 notes 23f02580, 835d648e, D confirmed
c301e993; decision R04-1 of 24/11 20:38Z). The G2-3 rule is cpmmgen2.decisions_g23 (0.2, PASS R02), unchanged; order,
exits, costs and placebo are R-CP1's (cpmmprereg 0.2, cpmmcost 0.3); unpriced rows follow K01 (cpmmpilot.step1.zero_sale,
checked by g1ind.report.counted). Nothing here is modified upstream; nothing reads the window.

ESTIMAND: is the G2-3 rule net positive on THESE pools, named before T0, in a future window? No generalisation.
SELECTION (before T0): pools with >= 3 G2-3 triggers over [T0 - 7 d ; T0) (cpmmgen2.trigger_count with the pool's b3),
     the first 5 by count (ties by pool id); fewer than 3 -> NON EVALUABLE, no trial.
INFERENCE: one-sided 95 % bounds of the mean net by a block bootstrap of POOL-DAYS STRATIFIED BY POOL (each pool's days
     with a position are resampled with replacement within that pool), 10 000 draws, seed int(sheet sha[:8], 16).
FLOORS (else INCONCLUSIF): >= 30 pool-days with an entry; >= 3 pools with an entry; Kish N (sum n_p)^2 / sum n_p^2 >= 2.5
     on the entries; no pool above 50 % of the entries.
WORD: INCONCLUSIF before NO-GO (R-0.1). NO-GO if the upper bound < 0. GO_PILOTE only if the lower bound > 0 on all the
     pools AND without the pool with the most entries. Otherwise INCONCLUSIF. Results are published pool by pool.
0.1.1 (R02 audit of 0.1, PASS TECHNIQUE, choice (a)): the gap to the placebo is published with one-sided 95 % bounds
     at the SAME stratified bootstrap (primary and placebo each resampled by pool-day blocks, the distribution of the
     difference of the two means). DESCRIPTIVE ONLY: it never enters the word of the pilot; it is the base of c2 at
     the confirmation.
0.2 (decision R04-6, R02 21:18Z): parameter block_days (default 1). A block is block_days CONSECUTIVE days of one pool
     (days aligned on T0, block = day // block_days); D must be a multiple of block_days. block_days = 1 gives exactly
     0.1.1 (G2-3 keeps 0.1.1); N1 names block_days = 2.
"""
import hashlib
import random

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmprereg import rule as R
from g1ind import report as G1

SCHEMA = 'g23five-v0.2'
MIN_TRIGGERS, TOP_POOLS, MIN_SELECTED = 3, 5, 3
MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 3, 2.5, 0.5
ALPHA, DRAWS = 0.05, 10_000
MIN_D, MAX_D = 7, 30
DAY_S = 86_400
NM = 'NON MESURÉ'
SHEET_MEANING = ('GO_PILOTE autorise seulement à PROPOSER la confirmation sur les MÊMES pools dans une fenêtre NOUVELLE ; '
                 'il ne qualifie jamais la règle au-delà de ces pools')


class VerdictError(ValueError):
    pass


def _check_sheet(sha):
    if type(sha) is not str or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise VerdictError('freeze_sheet_sha256_required')


# -- selection before T0 ----------------------------------------------------------------------------------------------
def select(counts):
    """{pool: G2-3 triggers before T0} -> the named pools (>= 3 triggers, first 5 by count, ties by id)."""
    kept = sorted((p for p, c in counts.items() if c >= MIN_TRIGGERS), key=lambda p: (-counts[p], p))[:TOP_POOLS]
    evaluable = len(kept) >= MIN_SELECTED
    return dict(schema=SCHEMA, pools=kept, counts={p: counts[p] for p in kept}, evaluable=evaluable,
                conduct=None if evaluable else 'NON ÉVALUABLE : aucune fiche de gel, aucun essai consommé',
                list_sha256=hashlib.sha256('\n'.join(kept).encode()).hexdigest(), outcomes_computed=False)


def counts_before_t0(lines, txs_by_pool, t0):
    """G2-3 trigger counts over [T0 - 7 d ; T0) with each pool's own b3 (frozen cpmmgen2; data >= T0 refused)."""
    out = {}
    for line in lines:
        txs = txs_by_pool[line.pool]
        b3 = G2.baseline_b3(line, txs, t0)
        out[line.pool] = G2.trigger_count(lambda ln, txs=txs, b3=b3: G2.decisions_g23(ln, txs, b3), [line],
                                          t0)['triggers']
    return out


# -- pool-day blocks ---------------------------------------------------------------------------------------------------
def day_of(row, t0, d_days):
    """Day index aligned on T0; a row outside [T0 ; T0 + D d) is refused."""
    day = (row['decision_time'] - t0) // DAY_S
    if not 0 <= day < d_days:
        raise VerdictError('position_outside_the_window')
    return day


def blocks(rows, t0, d_days, block_days=1):
    if type(block_days) is not int or block_days < 1 or d_days % block_days:
        raise VerdictError('block_days_must_divide_d_days')
    out = {}
    for r in rows:
        out.setdefault(r['pool'], {}).setdefault(day_of(r, t0, d_days) // block_days, []).append(r)
    return out


def _mean(rows):
    return sum(r['net_return'] for r in rows) / len(rows) if rows else None


def stratified_bounds(block_map, *, seed, draws=DRAWS):
    """(lower, upper) one-sided 95 % bounds of the mean net: each pool's day-blocks resampled within that pool."""
    pools = sorted(block_map)
    if not pools:
        return None, None
    rng, means = random.Random(seed), []
    for _ in range(draws):
        rows = []
        for p in pools:
            days = sorted(block_map[p])
            for _k in days:
                rows += block_map[p][days[rng.randrange(len(days))]]
        means.append(_mean(rows))
    k = max(0, int(ALPHA * draws) - 1)
    return sorted(means)[k], sorted(means, reverse=True)[k]


def _resampled_mean(block_map, rng):
    rows = []
    for p in sorted(block_map):
        days = sorted(block_map[p])
        for _d in days:
            rows += block_map[p][days[rng.randrange(len(days))]]
    return _mean(rows)


def difference_bounds(primary_blocks, placebo_blocks, *, seed, draws=DRAWS):
    """DESCRIPTIVE (never decisional): one-sided 95 % bounds of mean(primary) - mean(placebo). In each draw the
    primary and then the placebo are EACH resampled by pool-day blocks stratified by pool (independent draws from one
    generator seeded by the sheet), and the difference of the two means is kept."""
    if not primary_blocks or not placebo_blocks:
        return None, None
    rng, diffs = random.Random(seed), []
    for _ in range(draws):
        diffs.append(_resampled_mean(primary_blocks, rng) - _resampled_mean(placebo_blocks, rng))
    tail = max(0, int(ALPHA * draws) - 1)
    return sorted(diffs)[tail], sorted(diffs, reverse=True)[tail]


# -- floors ------------------------------------------------------------------------------------------------------------
def entries(rows):
    """Entered positions (zero-sale rows included, K01); guard refusals are positions but not entries."""
    return [r for r in rows if r.get('entered', True) and r.get('status') != 'guard_failed']


def floors(rows, t0, d_days):
    ent = entries(rows)
    per_pool = {}
    for r in ent:
        per_pool[r['pool']] = per_pool.get(r['pool'], 0) + 1
    pool_days = len({(r['pool'], day_of(r, t0, d_days)) for r in ent})
    total = sum(per_pool.values())
    kish = total ** 2 / sum(n * n for n in per_pool.values()) if total else 0.0
    share = max(per_pool.values()) / total if total else 1.0
    checks = dict(pool_days=pool_days >= MIN_POOL_DAYS, pools=len(per_pool) >= MIN_POOLS, kish=kish >= MIN_KISH,
                  max_share=share <= MAX_SHARE)
    return dict(pool_days_with_entry=pool_days, pools_with_entry=len(per_pool), kish=kish, max_share=share,
                entries_per_pool=per_pool, checks=checks, passed=all(checks.values()))


def top_pool(rows):
    per_pool = {}
    for r in entries(rows):
        per_pool[r['pool']] = per_pool.get(r['pool'], 0) + 1
    return sorted(per_pool, key=lambda p: (-per_pool[p], p))[0] if per_pool else None


# -- verdict -----------------------------------------------------------------------------------------------------------
def report(primary, placebo, *, pools, g0_passed, freeze_sheet_sha256, t0, d_days, draws=DRAWS, block_days=1):
    _check_sheet(freeze_sheet_sha256)
    if type(d_days) is not int or not MIN_D <= d_days <= MAX_D:
        raise VerdictError('d_days_outside_7_30')
    if type(t0) is not int:
        raise VerdictError('t0_must_be_an_integer_block_time')
    if len(pools) < MIN_SELECTED:
        raise VerdictError('fewer_than_3_named_pools_non_evaluable')
    rows = G1.counted(primary)                                    # K01: raw unpriced refused, zero sale checked
    plac = G1.counted(placebo, 'placebo')
    if {r['pool'] for r in rows + plac} - set(pools):
        raise VerdictError('position_outside_the_named_pools')
    doc = dict(schema=SCHEMA, estimand='G2-3 sur les pools nommés avant T0 seulement', pools=list(pools), t0=t0,
               d_days=d_days, labels=list(CC.LABELS), counts_for_operational_master=False, meaning=SHEET_MEANING)
    if g0_passed is not True:
        return G1.check_vocabulary(dict(doc, decision='STOP', reason='g0_decoder_not_passed', published_numbers=False))
    seed = int(freeze_sheet_sha256[:8], 16)
    fl = floors(rows, t0, d_days)
    low, high = stratified_bounds(blocks(rows, t0, d_days, block_days), seed=seed, draws=draws)
    top = top_pool(rows)
    rest = [r for r in rows if r['pool'] != top]
    low_wo, high_wo = stratified_bounds(blocks(rest, t0, d_days, block_days), seed=seed, draws=draws)
    if not fl['passed']:
        decision = 'INCONCLUSIF'
    elif high is not None and high < 0:
        decision = 'NO-GO'
    elif low is not None and low > 0 and low_wo is not None and low_wo > 0:
        decision = 'GO_PILOTE'
    else:
        decision = 'INCONCLUSIF'
    per_pool = {}
    for p in pools:
        mine = [r for r in rows if r['pool'] == p]
        per_pool[p] = dict(positions=len(mine), entries=len(entries(mine)),
                           pool_days_with_entry=len({day_of(r, t0, d_days) for r in entries(mine)}),
                           mean_net_return=_mean(mine) if mine else NM)
    target = R.n_required()
    d_low, d_high = difference_bounds(blocks(rows, t0, d_days, block_days), blocks(plac, t0, d_days, block_days),
                                      seed=seed, draws=draws)
    doc.update(decision=decision, published_numbers=True, n=len(rows), n_entered=len(entries(rows)), floors=fl,
               mean_net_return=_mean(rows), lower_bound_95=low, upper_bound_95=high,
               without_top_pool=dict(pool=top, lower_bound_95=low_wo, upper_bound_95=high_wo),
               per_pool=per_pool, seed=seed, draws=draws, block_days=block_days,
               power=dict(n_entered=len(entries(rows)), n_required=target,
                          flag=G1.UNDER_TARGET if len(entries(rows)) < target else None),
               zero_sale=G1.zero_sale_reasons(rows),
               placebo=dict(positions=len(plac), mean_net_return=_mean(plac),
                            difference=(_mean(rows) - _mean(plac)) if rows and plac else NM,
                            difference_bounds_95=dict(lower=NM if d_low is None else d_low,
                                                      upper=NM if d_high is None else d_high,
                                                      role='descriptif, non décisionnel ; base de c2'),
                            verdict=None))
    return G1.check_vocabulary(doc)


# the G2-3 rule, positions and placebo, imported unchanged
decisions, positions, placebo = G2.decisions_g23, R.positions, R.placebo
