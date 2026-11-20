"""latelab 0.1 — LATE entries on W1 (development data), a grid FIXED here before any data is read (plan v0.2 of
RUGGER 01; conditions of RUGGER 02 53ae2cae). EXPLORATORY: a cell kept here is an hypothesis, confirmed on W2 only.

  python -B -m latelab.study discover --pools <W1 export> --manifest-sha256 <anchored> --out <OUT>
  python -B -m latelab.study screen   --pools <W1 export> --manifest-sha256 <anchored> --cells L1,L3 \
         --discovery <ANCHORED discovery json> --discovery-sha256 <sha> --out <OUT>

REUSED UNCHANGED: ``statelab.points.decision_points`` (labels ``age:A``: first whole event of age >= A, at most
30 s late), ``statelab.exits.run_rule`` (v4sim mode M-P, buy of 0.1 SOL landing after the frozen order latency,
causal sale rule, frozen clock exit, a position whose curve completes before the sale counts -1),
``bot.market.replay.causal_fee_rate`` (the fee tier KNOWN at the decision), ``statelab.study.cluster_key``,
``hrr.usable_timeline`` / ``creation_facts``, ``w1aux.lazy`` (one archive in memory).

POPULATION: exported W1 pools CREATED in [EVAL_MIN, EVAL_MAX), replayable. Halves by creation slot: discovery
< CUT_SLOT <= screen (R02 condition 2).

FIREWALL HW1 (R02 53ae2cae, tested): only the labels ``age:120`` and ``age:300`` are used (< 600 s); no progress
label, no trigger on a sale, no reserve level, no ratio to a past price or maximum, no signer status. The ONLY
selection variable of 0.1 is the causal fee tier. Overlap of the exit window with HW1-4 is declared.

GRID (fixed; N + 4 at discovery, N + 2 at the screen):
  L1 age:120, every tier          L2 age:120, tier <= 2 500 ppm
  L3 age:300, every tier          L4 age:300, tier <= 2 500 ppm
EXIT (R02 condition 3): take profit +7 %, stop loss -5 % (of the cost), else the clock at EXIT_CLOCK_S.
RETURN: r = (received - cost - rent) / (cost + rent), rent LOST (SPL rent of the frozen chain); -1 if migrated.
A ``rent recovered`` mean is published apart. Comparator: the statelab placebo label (random age <= 120 s) under the
same exit, reported per half, never a cell.
PER CELL: n, clusters, mean, median, win rate, 95 % interval of the mean by creator-cluster bootstrap (seed
20261120, 2 000 draws), share of the 5 best pools in the positive P&L, migrated share; n < 30 or < 20 clusters =
« non interprétable ». DISCOVERY ranks the interpretable cells by the lower bound of the interval and names the top
2 (R02 condition 4); SCREEN recomputes those 2 only (an anchored discovery is required) and passes a cell if its mean
is > 0 with n >= 30. Output: counts and returns only, no pool or creator (tested). Nothing is printed.
"""
import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from bot.market.collector import summarize
from bot.market.replay import causal_fee_rate
from bot.p4 import historical_research_replay as hrr
from statelab.exits import SPL_RENT_LAMPORTS, run_rule
from statelab.points import decision_points
from statelab.study import cluster_key
from v3lab import plan
from w1aux.lazy import clear_cache, load_fixtures_lazy

SCHEMA = 'latelab-v0.1'
EVAL_MIN, EVAL_MAX, CUT_SLOT = 467_678_545, 469_291_345, 468_484_945
LOW_TIER_PPM = 2_500
EXIT_CLOCK_S = 30                      # the status quo's frozen horizon (to be confirmed by R02)
RULE = dict(id='TP7_SL5', take_profit=0.07, stop_loss=0.05, clock_s=EXIT_CLOCK_S)
CELLS = dict(L1=dict(age=120, low_tier=False), L2=dict(age=120, low_tier=True),
             L3=dict(age=300, low_tier=False), L4=dict(age=300, low_tier=True))
AGES = (120, 300)
PLACEBO = ['placebo', 0]
SEED, DRAWS, MIN_N, MIN_CLUSTERS = 20261120, 2_000, 30, 20


class LateLabError(RuntimeError):
    pass


def quantile(values, q):
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1] if ordered else None


def bootstrap(clusters, *, draws=DRAWS, seed=SEED):
    groups = [clusters[key] for key in sorted(clusters)]
    if not groups:
        return dict(low=None, high=None, draws=draws, seed=seed, clusters=0)
    rng, means = random.Random(seed), []
    for _ in range(draws):
        picked = [groups[rng.randrange(len(groups))] for _g in groups]
        means.append(sum(map(sum, picked)) / sum(map(len, picked)))
    return dict(low=quantile(means, 0.025), high=quantile(means, 0.975), draws=draws, seed=seed, clusters=len(groups))


def half_of(creation_slot):
    if not EVAL_MIN <= creation_slot < EVAL_MAX:
        return None
    return 'discovery' if creation_slot < CUT_SLOT else 'screen'


def pool_points(archive, params):
    """(half, cluster, [(label, fee tier ppm, outcome)]) of one pool; None when outside or not replayable."""
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    half = half_of(facts['creation_slot'])
    if half is None:
        return None
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded:
        return None
    events = timeline.events
    from v4sim.io import actors_from_archive                  # imported here: heavy, and only when a pool is kept
    actors, _stats = actors_from_archive(archive, events)
    model = params.execution_model()
    points = []
    for k, labels in decision_points(events, facts['creation_block_time'], archive.pool):
        kept = [label for label in labels if label == PLACEBO or (label[0] == 'age' and label[1] in AGES)]
        if not kept:
            continue
        tier, _evidence = causal_fee_rate(events[:k + 1])
        outcome = run_rule(timeline, k, actors, model, RULE)
        if outcome is None:
            continue                                         # the buy itself is refused: no position
        for label in kept:
            points.append((f'{label[0]}:{label[1]}', tier, outcome))
    return half, cluster_key(archive, facts), points


def net_return(outcome, *, rent=SPL_RENT_LAMPORTS):
    if outcome['migrated']:
        return -1.0
    return (outcome['value'] - outcome['cost'] - rent) / (outcome['cost'] + rent)


def summary(items):
    """items: [(cluster, outcome)]."""
    returns = [net_return(o) for _c, o in items]
    recovered = [net_return(o, rent=0) for _c, o in items]
    clusters = {}
    for (cluster, _o), r in zip(items, returns):
        clusters.setdefault(cluster, []).append(r)
    by_pool = sorted((r for r in returns if r > 0), reverse=True)
    interval = bootstrap(clusters)
    interpretable = len(returns) >= MIN_N and len(clusters) >= MIN_CLUSTERS
    return dict(n=len(returns), clusters=len(clusters), mean_net_return=statistics.fmean(returns) if returns else None,
                median_net_return=statistics.median(returns) if returns else None,
                win_rate=(sum(r > 0 for r in returns) / len(returns)) if returns else None,
                mean_net_return_rent_recovered=statistics.fmean(recovered) if recovered else None,
                interval_95=interval, interpretable=interpretable,
                share_of_the_5_best_in_positive=(sum(by_pool[:5]) / sum(by_pool)) if by_pool else None,
                migrated_share=(sum(o['migrated'] for _c, o in items) / len(items)) if items else None,
                exit_reasons=dict(sorted({r: sum(1 for _c, o in items if o['reason'] == r)
                                          for r in {o['reason'] for _c, o in items}}.items(), key=lambda kv: str(kv[0]))))


def cell_items(pools, half, cell):
    spec = CELLS[cell]
    return [(cluster, outcome) for h, cluster, points in pools if h == half
            for label, tier, outcome in points
            if label == f"age:{spec['age']}" and (not spec['low_tier'] or tier <= LOW_TIER_PPM)]


def placebo_items(pools, half):
    return [(cluster, outcome) for h, cluster, points in pools if h == half
            for label, _tier, outcome in points if label == 'placebo:0']


def collect(pools_dir, manifest_sha256, params):
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise LateLabError('manifest_is_not_the_anchored_one')
    pools = []
    try:
        for _entry, archive in entries:
            got = pool_points(archive, params)
            if got is not None:
                pools.append(got)
    finally:
        clear_cache()
    return pools


def discover(pools):
    cells = {cell: summary(cell_items(pools, 'discovery', cell)) for cell in CELLS}
    ranked = sorted((c for c in cells if cells[c]['interpretable'] and cells[c]['interval_95']['low'] is not None),
                    key=lambda c: (-cells[c]['interval_95']['low'], c))
    return dict(half='discovery', cells=cells, placebo=summary(placebo_items(pools, 'discovery')),
                ranking_rule='interpretable cells by the lower bound of the 95 % interval', top2=ranked[:2],
                trials_added=len(CELLS))


def screen(pools, cells):
    out = {cell: summary(cell_items(pools, 'screen', cell)) for cell in cells}
    for s in out.values():
        s['passes'] = s['n'] >= MIN_N and s['mean_net_return'] is not None and s['mean_net_return'] > 0
    return dict(half='screen', cells=out, placebo=summary(placebo_items(pools, 'screen')),
                pass_rule='mean > 0 and n >= 30; never a proof', trials_added=len(cells))


def _write(out_dir, doc):
    out = Path(out_dir)
    if out.exists():
        raise LateLabError('output_exists')
    out.mkdir(parents=True)
    path = out / 'LATELAB.json'
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base(params, manifest_sha256):
    return dict(schema=SCHEMA, category='EXPLORATORY_W1_DEVELOPMENT', rule=RULE, cells_grid=CELLS,
                cut_slot=CUT_SLOT, evaluation=[EVAL_MIN, EVAL_MAX], latency_slots=params.latency_slots,
                rent='lost (SPL rent of the frozen chain), recovered published apart',
                firewall=dict(labels=['age:120', 'age:300', 'placebo:0'], selection=['causal fee tier'],
                              hw1_overlap_declared='exit window may overlap the HW1-4 survivor age (600 s)'),
                input=dict(manifest_sha256=manifest_sha256))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='latelab.study')
    parser.add_argument('mode', choices=('discover', 'screen'))
    parser.add_argument('--pools', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--cells', default=None)
    parser.add_argument('--discovery', type=Path, default=None)
    parser.add_argument('--discovery-sha256', default=None)
    parser.add_argument('--latency-slots', type=int, default=None)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    params = hrr.ReplayParams(latency_slots=plan.REPLAY['latency_slots'] if a.latency_slots is None else a.latency_slots)
    if a.mode == 'screen':
        if a.discovery is None or a.discovery_sha256 is None:
            raise LateLabError('anchored_discovery_required')
        raw = a.discovery.read_bytes()
        if hashlib.sha256(raw).hexdigest() != a.discovery_sha256:
            raise LateLabError('discovery_is_not_the_anchored_one')
        top2 = json.loads(raw)['top2']
        cells = [] if a.cells is None else a.cells.split(',')
        if cells != top2 or not cells:
            raise LateLabError('screen_cells_must_be_the_anchored_top2')
    if a.out.exists():
        raise LateLabError('output_exists')
    pools = collect(a.pools, a.manifest_sha256, params)
    doc = dict(_base(params, a.manifest_sha256), **(discover(pools) if a.mode == 'discover' else screen(pools, cells)))
    if a.mode == 'screen':
        doc['input']['discovery_sha256'] = a.discovery_sha256
    _write(a.out, doc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
