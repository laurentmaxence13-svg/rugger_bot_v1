"""cdgate 0.2 (0.1 + the TIER of the causal rate, R02 B-1) -- NON-REFUTATION GATE of the FROZEN rule C-D on W1 (R02, register entry written before any run; the rule
is dossier A v1.6 section 10, branch « constant » = conjunction, fixed by Q3, R02 557648f4). EXPLORATORY: C-D was chosen
on W1, so the estimate is biased upwards; the gate can only KILL C-D, never confirm it.

  python -B -m cdgate.gate --pools <W1 export> --manifest-sha256 <anchored> --out <NEW DIR>

RULE (unchanged): for each W1 pool created in [EVAL_MIN, EVAL_MAX) (latelab 0.4 constants, the whole range) and
replayable, the decision is the FIRST WHOLE event of age >= 450 slots (event slot - creation slot); the pool is
ELIGIBLE iff the TIER of the frozen ``causal_fee_rate`` of the events up to that decision is <= 2 500 ppm; the tier is
the rate rounded to the nearest 500 ppm, exactly as feeage 0.2 ``tier_of`` (Q4); the raw rate stays the one of the costs. Buy 0.1 SOL, landing
after 4 slots, one position per pool, causal curve fees, 2 x (5 000 + 100 000) lamports, rent LOST, take profit +7 %
or stop loss -5 % of the cost, otherwise the clock at 30 s (L1_HORIZON_MS), sale after the frozen clock latency
(``statelab.exits.run_rule``, unchanged); a position whose curve completes before the sale counts -1.

FIREWALL HW1: an eligible decision at age >= 600 s is COUNTED, never replayed, its return is neither computed nor read.
GATE (R02): C-D stays a candidate iff n >= 30 AND the HIGH bound of the 95 % interval of the mean net >= 0 (creator-
cluster bootstrap, seed 20261120, 2 000 draws), over the entries < 600 s. Otherwise the slot stays EMPTY. N + 1.

DESCRIPTIVE (never in the gate): decomposition per position in % of the stake (curve fees: exact on the buy, ``fee_for``
of the gross sale on the sell; transaction costs; rent; gross = net before those costs); buy slippage = 1 - tokens
received / tokens of the same buy on the decision state; latency sensitivity at 10 slots (mean only); win rate, the
extremes, the share of the 5 best; c = eligible -> closed cycles; buys refused; comparator: the frozen statelab placebo
(random age <= 120 s) restricted to a causal rate <= 2 500 ppm, same exit. The MASTER W1 reference is the anchored
preliminary reading (ea152a32), quoted, not recomputed. Output: counts and returns only, no pool or creator (tested).
"""
import argparse
import hashlib
import json
import statistics
from dataclasses import replace
from pathlib import Path

from bot.market.collector import summarize
from bot.market.launchlab_curve import FEE_DENOMINATOR, buy_exact_in, fee_for
from bot.market.replay import causal_fee_rate
from bot.p4 import historical_research_replay as hrr
from latelab import study as LL
from statelab.exits import SPL_RENT_LAMPORTS, run_rule
from statelab.points import PLACEBO_CELL, decision_points, whole
from statelab.study import STAKE_LAMPORTS, cluster_key
from v3lab import plan
from w1aux.lazy import clear_cache, load_fixtures_lazy

SCHEMA = 'cdgate-v0.2'
TIER_STEP_PPM = 500                                          # feeage 0.2 tier_of (Q4, R02 B-1)
LATE_SLOTS, LOW_TIER_PPM, HW1_AGE_S = 450, 2_500, 600
RULE = dict(id='TP7_SL5_CLOCK30', take_profit=0.07, stop_loss=0.05, clock_s=30)
LATENCY_SENSITIVITY_SLOTS = 10
MASTER_REFERENCE = dict(source='W1 preliminary reading, anchored ea152a32 (quoted, not recomputed)',
                        mean_net_return=-0.0426)


class CdGateError(RuntimeError):
    pass


def decision_index(events, creation_slot):
    """First whole event of age >= 450 slots; None when the pool never gets there."""
    return next((k for k, e in enumerate(events) if e.slot - creation_slot >= LATE_SLOTS and whole(events, k)), None)


def tier(rate):
    return int(round(rate / TIER_STEP_PPM)) * TIER_STEP_PPM


def eligible(events, k):
    rate, _evidence = causal_fee_rate(events[:k + 1])
    return tier(rate) <= LOW_TIER_PPM, rate


def decompose(outcome, rate):
    """Per-position shares of the stake; the curve fees: exact on the buy, fee_for of the gross sale on the sell."""
    tx = outcome['cost'] - STAKE_LAMPORTS
    buy_fee = fee_for(STAKE_LAMPORTS, rate)
    if outcome['migrated']:
        return dict(curve_fees=buy_fee / STAKE_LAMPORTS, tx=tx / STAKE_LAMPORTS, rent=SPL_RENT_LAMPORTS / STAKE_LAMPORTS,
                    gross=None)
    received = outcome['value']
    gross_sale = (received * FEE_DENOMINATOR) // (FEE_DENOMINATOR - rate) if rate < FEE_DENOMINATOR else received
    sell_fee = fee_for(gross_sale, rate)
    curve = buy_fee + sell_fee
    return dict(curve_fees=curve / STAKE_LAMPORTS, tx=tx / STAKE_LAMPORTS, rent=SPL_RENT_LAMPORTS / STAKE_LAMPORTS,
                gross=(received + curve - STAKE_LAMPORTS) / STAKE_LAMPORTS)


def slippage(events, k, rate, outcome):
    """1 - tokens received / tokens the same buy would get on the decision state (descriptive execution cost)."""
    if not outcome.get('tokens'):
        return None
    expected = buy_exact_in(events[k].state_after(), STAKE_LAMPORTS, rate).amount_out
    return 1 - outcome['tokens'] / expected if expected else None


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def describe(rows):
    """rows: [dict(cluster, outcome, rate, slippage, latency10)]."""
    items = [(r['cluster'], r['outcome']) for r in rows]
    out = LL.summary(items)
    returns = [LL.net_return(o) for _c, o in items]
    parts = [decompose(r['outcome'], r['rate']) for r in rows]
    out.update(min_net_return=min(returns) if returns else None, max_net_return=max(returns) if returns else None,
               decomposition_mean_share_of_stake={k: _mean([p[k] for p in parts]) for k in ('gross', 'curve_fees', 'tx', 'rent')},
               buy_slippage_mean=_mean([r['slippage'] for r in rows]),
               mean_net_return_latency_10_slots=_mean([LL.net_return(r['latency10']) for r in rows if r['latency10']]),
               fee_rate_ppm_mean=_mean([r['rate'] for r in rows]))
    return out


def pool_rows(archive, params):
    """(kind, row) records of one pool: 'cd' / 'cd_at_or_after_600s' / 'cd_refused' / 'placebo'; None if outside."""
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    if LL.half_of(facts['creation_slot']) is None:
        return None
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded:
        return None
    events, records = timeline.events, []
    k = decision_index(events, facts['creation_slot'])
    placebo = next((k2 for k2, labels in decision_points(events, facts['creation_block_time'], archive.pool)
                    if PLACEBO_CELL in (f'{a}:{b}' for a, b in labels)), None)
    wanted = []
    if k is not None:
        ok, rate = eligible(events, k)
        if ok:
            if events[k].block_time - facts['creation_block_time'] >= HW1_AGE_S:
                records.append(('cd_at_or_after_600s', None))              # counted, never replayed (HW1 firewall)
            else:
                wanted.append(('cd', k, rate))
        records.append(('late_pool', None))
    if placebo is not None:
        ok, rate = eligible(events, placebo)
        if ok:
            wanted.append(('placebo', placebo, rate))
    if not wanted:
        return records
    from v4sim.io import actors_from_archive                  # heavy, and only when a position is replayed
    actors, _stats = actors_from_archive(archive, events)
    model = params.execution_model()
    cluster = cluster_key(archive, facts)
    for kind, index, rate in wanted:
        outcome = run_rule(timeline, index, actors, model, RULE)
        if outcome is None:
            records.append((kind + '_refused', None))
            continue
        latency10 = run_rule(timeline, index, actors, replace(model, latency_slots=LATENCY_SENSITIVITY_SLOTS), RULE) \
            if kind == 'cd' else None
        records.append((kind, dict(cluster=cluster, outcome=outcome, rate=rate, latency10=latency10,
                                   slippage=slippage(events, index, rate, outcome))))
    return records


def gate(rows):
    out = describe(rows)
    high = out['interval_95']['high']
    out['gate'] = dict(rule='C-D stays a candidate iff n >= 30 and the high bound of the 95 % interval >= 0',
                       n_ok=out['n'] >= LL.MIN_N, high_bound_ok=high is not None and high >= 0)
    out['gate']['c_d_stays_candidate'] = out['gate']['n_ok'] and out['gate']['high_bound_ok']
    return out


def run(pools_dir, manifest_sha256, params):
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise CdGateError('manifest_is_not_the_anchored_one')
    rows, counts = dict(cd=[], placebo=[]), dict(late_pool=0, cd_at_or_after_600s=0, cd_refused=0, placebo_refused=0)
    try:
        for _entry, archive in entries:
            for kind, row in pool_rows(archive, params) or []:
                if row is None:
                    counts[kind] += 1
                else:
                    rows[kind].append(row)
    finally:
        clear_cache()
    cd = gate(rows['cd'])
    eligible_total = len(rows['cd']) + counts['cd_refused'] + counts['cd_at_or_after_600s']
    cd['cycles'] = dict(late_pools=counts['late_pool'], eligible=eligible_total, eligible_at_tier_le_2500=eligible_total,
                        q4_reference='feeage Q4: 53 pools in the evaluation range at tier <= 2 500 ppm, before exclusions',
                        closed=len(rows['cd']),
                        refused_buys=counts['cd_refused'], at_or_after_600s_counted_not_read=counts['cd_at_or_after_600s'],
                        share_at_or_after_600s=(counts['cd_at_or_after_600s'] / eligible_total) if eligible_total else None,
                        share_refused=(counts['cd_refused'] / eligible_total) if eligible_total else None)
    placebo = describe(rows['placebo'])
    placebo['refused_buys'] = counts['placebo_refused']
    return dict(c_d=cd, placebo_low_tier_descriptive=placebo, master_reference=MASTER_REFERENCE, trials_added=1)


def _write(out_dir, doc):
    out = Path(out_dir)
    if out.exists():
        raise CdGateError('output_exists')
    out.mkdir(parents=True)
    path = out / 'CDGATE.json'
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cdgate.gate')
    parser.add_argument('--pools', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise CdGateError('output_exists')
    params = hrr.ReplayParams(latency_slots=plan.REPLAY['latency_slots'])
    body = run(a.pools, a.manifest_sha256, params)
    doc = dict(schema=SCHEMA, category='EXPLORATORY_W1_NON_REFUTATION_GATE', rule=RULE, late_slots=LATE_SLOTS,
               low_tier_ppm=LOW_TIER_PPM, hw1_age_s=HW1_AGE_S, evaluation=[LL.EVAL_MIN, LL.EVAL_MAX],
               latency_slots=params.latency_slots, rent='lost (SPL rent of the frozen chain)',
               input=dict(manifest_sha256=a.manifest_sha256), **body)
    _write(a.out, doc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
