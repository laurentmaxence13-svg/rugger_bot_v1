"""E1 0.1 -- PLAFOND D'OPPORTUNITE on the anchored W1 LaunchLab export (R01, 28/11). EXPLORATOIRE W1.

CONDITION NECESSAIRE SEULEMENT, JAMAIS SUFFISANTE: E[|m|] - c is the volatility an oracle knowing the sign could
reach, never an edge. Method, segments and metrics: E1_DECLARATION.md (committed before any run; its sha256 is the
seed). Frozen code is imported, never changed: collector.summarize, historical_research_replay.usable_timeline /
creation_facts / ReplayParams, replay._event_rate, launchlab_curve.buy_exact_in / sell_exact_in.

python -B -m e1plafond.e1 --pools DIR --declaration E1_DECLARATION.md --out OUT [--coverage-end JSON] [--workers N]
The output holds no pool, creator or signature: counts and statistics only.
"""
import argparse
import bisect
import gzip
import hashlib
import json
import math
import random
import statistics
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

SCHEMA = 'rugger-e1-plafond-v0.1'
STAMP = 'EXPLORATOIRE W1 — CONDITION NÉCESSAIRE SEULEMENT, JAMAIS SUFFISANTE — AUCUNE STRATÉGIE VALIDÉE NI CHOISIE'
W1_MANIFEST = 'ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e'
HOLDOUT_PREFIX = '9f19ccac'
HORIZONS = (30, 120, 300, 900, 1800, 3600)
GRID = (0.005, 0.0095, 0.015)
BLOCK_S, DRAW_S, MAX_BLOCKS = 7200, 3600, 20
ACTIVITY_S = 600
STAKE = 100_000_000
RENT_LAMPORTS = 2_039_280                       # SPL_RENT_LAMPORTS (N-1), as w1decomp
MIN_POOLS = 30
OPEN_SHARE = 0.25
BOOT = 2000
ALPHA = 0.05
AGE = ((3600, '<1h'), (6 * 3600, '1-6h'), (86400, '6-24h'), (7 * 86400, '1-7j'), (None, '>7j'))
RESERVE_SOL = ((1, '<1'), (5, '1-5'), (20, '5-20'), (50, '20-50'), (None, '>=50'))
ACTIVITY = ((0, '0'), (2, '1-2'), (9, '3-9'), (None, '>=10'))
MIGR = ((3600, '<1h'), (6 * 3600, '1-6h'), (None, '>=6h'))
DIMENSIONS = ('tous', 'age', 'reserve', 'progression', 'palier', 'activite', 'migration')


class E1Error(RuntimeError):
    pass


def classify(value, edges):
    """First label whose upper bound (exclusive, None = open) exceeds value; ACTIVITY uses inclusive integer bounds."""
    for upper, label in edges:
        if upper is None or value < upper:
            return label
    raise AssertionError('unreachable')


def activity_class(n):
    for upper, label in ACTIVITY:
        if upper is None or n <= upper:
            return label
    raise AssertionError('unreachable')


def seed_of(declaration_bytes):
    return int(hashlib.sha256(declaration_bytes).hexdigest()[:8], 16)


def draw_entries(seed, pool, start, end):
    """Entry times: one uniform instant in the first DRAW_S of each BLOCK_S block from start, at most MAX_BLOCKS
    blocks (sampled if more), kept only if <= end. Consecutive entries are >= BLOCK_S - DRAW_S apart."""
    rng = random.Random('%d:%s' % (seed, pool))
    if end < start:
        return []
    blocks = list(range(int((end - start) // BLOCK_S) + 1))
    if len(blocks) > MAX_BLOCKS:
        blocks = sorted(rng.sample(blocks, MAX_BLOCKS))
    times = []
    for b in blocks:
        t = start + b * BLOCK_S + rng.random() * DRAW_S
        if t <= end:
            times.append(t)
    return times


class Path_:
    """Price path of one pool: events in timeline order with a non-decreasing block_time index."""

    def __init__(self, events):
        self.events = list(events)
        self.times, running = [], None
        for e in self.events:
            running = e.block_time if running is None else max(running, e.block_time)
            self.times.append(running)

    def index_at(self, tau):
        """Index of the last event with block_time <= tau, or -1."""
        return bisect.bisect_right(self.times, tau) - 1

    def state_at(self, tau):
        i = self.index_at(tau)
        return self.events[0].state_before() if i < 0 else self.events[i].state_after()

    @staticmethod
    def spot(state):
        return state.quote_reserve / state.base_reserve

    def price(self, tau):
        return self.spot(self.state_at(tau))

    def count_in(self, lo, hi):
        """Events with lo < block_time <= hi."""
        return bisect.bisect_right(self.times, hi) - bisect.bisect_right(self.times, lo)


def round_trip_cost(state, rate_ppm, tx_lamports, curve):
    """(c_eff with rent, c_eff without rent, convention) of a 0.1 SOL round trip at zero move, or None if refused."""
    try:
        buy = curve.buy_exact_in(state, STAKE, rate_ppm)
        after = curve.sell_exact_in(buy.after, buy.amount_out, rate_ppm).amount_out
    except curve.CurveError:
        return None
    try:
        without = curve.sell_exact_in(state, buy.amount_out, rate_ppm).amount_out
        out, convention = min(after, without), 'B'
    except curve.CurveError:
        out, convention = after, 'A'
    no_rent = (STAKE - out + tx_lamports) / STAKE
    return no_rent + RENT_LAMPORTS / STAKE, no_rent, convention


def pool_rows(pool, events, facts, migration_time, coverage_end, seed, rate_ppm, tx_lamports, curve):
    """Entry rows of one pool (no address inside). facts: creation_known, start."""
    path = Path_(events)
    last = path.times[-1]
    if coverage_end is not None:
        end, end_reason = coverage_end, 'fin_de_collecte'
    else:
        end, end_reason = last, 'dernier_evenement'
    if migration_time is not None and migration_time <= end:
        end, end_reason = migration_time, 'migration'
    tier = int(round(rate_ppm / 500.0)) * 500
    rows = []
    for t in draw_entries(seed, pool, facts['start'], end):
        state = path.state_at(t)
        p0 = path.spot(state)
        cost = round_trip_cost(state, rate_ppm, tx_lamports, curve)
        age = classify(t - facts['start'], AGE) if facts['creation_known'] else 'inconnu'
        migr = 'non_migre' if migration_time is None else classify(migration_time - t, MIGR)
        seg = dict(tous='tous', age=age, reserve=classify(state.real_quote / 1e9, RESERVE_SOL),
                   progression='%d-%d%%' % (min(state.progress_ppm // 100_000, 9) * 10,
                                            min(state.progress_ppm // 100_000, 9) * 10 + 10),
                   palier='%d_ppm' % tier, activite=activity_class(path.count_in(t - ACTIVITY_S, t)), migration=migr)
        moves = {}
        for h in HORIZONS:
            if t + h > end:
                moves[h] = dict(censored=end_reason)
                continue
            m = path.price(t + h) / p0 - 1
            i0, i1 = path.index_at(t), path.index_at(t + h)
            exc = abs(m)
            for e in path.events[i0 + 1:i1 + 1]:
                exc = max(exc, abs(path.spot(e.state_after()) / p0 - 1))
            moves[h] = dict(m=m, exc=exc, flat=i1 == i0)
        rows.append(dict(t=t, seg=seg, moves=moves, c_eff=None if cost is None else cost[0],
                         c_eff_no_rent=None if cost is None else cost[1],
                         convention=None if cost is None else cost[2]))
    return rows


# ---------------------------------------------------------------- statistics

def _q(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def cluster_mean(groups):
    """Ratio mean over pools: sum of values / number of values."""
    return sum(sum(g) for g in groups) / sum(len(g) for g in groups)


def cluster_se(groups):
    """Cluster-robust standard error of the ratio mean (pools = clusters)."""
    k = len(groups)
    n = sum(len(g) for g in groups)
    mean = cluster_mean(groups)
    if k < 2:
        return float('nan')
    resid = [sum(g) - mean * len(g) for g in groups]
    return math.sqrt(k / (k - 1) * sum(r * r for r in resid)) / n


def bootstrap_ci(groups, rng, draws=BOOT):
    """95 % percentile interval of the ratio mean, pools resampled with replacement (numpy rng)."""
    import numpy as np
    sums = np.array([sum(g) for g in groups], dtype=float)
    counts = np.array([len(g) for g in groups], dtype=float)
    idx = rng.integers(0, len(groups), size=(draws, len(groups)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return float(np.quantile(means, ALPHA / 2)), float(np.quantile(means, 1 - ALPHA / 2))


def kish(groups):
    sizes = [len(g) for g in groups]
    return sum(sizes) ** 2 / sum(s * s for s in sizes)


def cell_stats(by_pool, rng, z_simultaneous):
    """by_pool: list (one per pool) of lists of (m, exc, c_eff or None, c_eff_no_rent or None)."""
    flat = [x for g in by_pool for x in g]
    ms = [x[0] for x in flat]
    out = dict(n=len(flat), pools=len(by_pool), kish=kish(by_pool),
               p10=_q(ms, 0.1), p50=_q(ms, 0.5), p90=_q(ms, 0.9), share_up=sum(m > 0 for m in ms) / len(ms), grid={})
    for c in GRID:
        groups = [[abs(x[0]) - c for x in g] for g in by_pool]
        lo, hi = bootstrap_ci(groups, rng)
        out['grid']['%.4f' % c] = dict(share_abs=sum(abs(m) > c for m in ms) / len(ms),
                                       share_up=sum(m > c for m in ms) / len(ms),
                                       share_down=sum(m < -c for m in ms) / len(ms),
                                       mean_abs_minus_c=cluster_mean(groups), ci95=[lo, hi])
    costed = [[x for x in g if x[2] is not None] for g in by_pool]
    costed = [g for g in costed if g]
    n_c = sum(len(g) for g in costed)
    out['c_eff_unavailable'] = len(flat) - n_c
    if len(costed) < MIN_POOLS:
        out['real_cost'] = dict(status='n_insuffisant', pools=len(costed))
        return out
    for key, idx, col in (('real_cost', 0, 2), ('real_cost_no_rent', 0, 3), ('excursion_real_cost', 1, 2)):
        groups = [[abs(x[idx]) - x[col] for x in g] for g in costed]
        mean, se = cluster_mean(groups), cluster_se(groups)
        lo, hi = bootstrap_ci(groups, rng)
        share = sum(abs(x[idx]) > x[col] for g in costed for x in g) / n_c
        row = dict(n=n_c, pools=len(costed), mean_cost=sum(x[col] for g in costed for x in g) / n_c,
                   share_above=share, mean_minus_cost=mean, ci95=[lo, hi],
                   ci_simultaneous=[mean - z_simultaneous * se, mean + z_simultaneous * se])
        if key == 'real_cost':
            row['plafond'] = 'OUVERT' if row['ci_simultaneous'][0] > 0 and share >= OPEN_SHARE else 'FERMÉ'
        out[key] = row
    return out


def aggregate(pool_results, seed):
    """pool_results: list of (pool_index, rows). Cells by dimension, class and horizon."""
    import numpy as np
    cells, censored, flat_count, conventions = {}, Counter(), Counter(), Counter()
    for k, rows in pool_results:
        for r in rows:
            conventions[r['convention'] or 'indisponible'] += 1
            for h, mv in r['moves'].items():
                if 'censored' in mv:
                    censored[(h, mv['censored'])] += 1
                    continue
                flat_count[h] += mv['flat']
                for dim in DIMENSIONS:
                    key = (dim, r['seg'][dim], h)
                    cells.setdefault(key, {}).setdefault(k, []).append(
                        (mv['m'], mv['exc'], r['c_eff'], r['c_eff_no_rent']))
    eligible = [key for key, pools in cells.items()
                if sum(1 for g in pools.values() if any(x[2] is not None for x in g)) >= MIN_POOLS]
    big_k = len(eligible)
    z = statistics.NormalDist().inv_cdf(1 - ALPHA / (2 * max(big_k, 1)))
    rng = np.random.default_rng(seed)
    table = []
    for key in sorted(cells, key=lambda k: (DIMENSIONS.index(k[0]), k[2], k[1])):
        dim, label, h = key
        pools = [cells[key][p] for p in sorted(cells[key])]
        if len(pools) < MIN_POOLS:
            table.append(dict(dimension=dim, classe=label, horizon_s=h, status='n_insuffisant', pools=len(pools)))
            continue
        table.append(dict(dimension=dim, classe=label, horizon_s=h, status='rapporte', **cell_stats(pools, rng, z)))
    opened = [row for row in table if row.get('real_cost', {}).get('plafond') == 'OUVERT']
    return dict(cells=table, K_cells_real_cost=big_k, z_bonferroni=z, expected_false_open_uncorrected=0.025 * big_k,
                open_cells=len(opened),
                conclusion=('aucun segment n\'offre de plafond ouvert au coût réel W1 : l\'approche directionnelle à '
                            'court terme sur ces courbes est à revoir') if not opened else
                           ('%d cellule(s) au plafond ouvert : hypothèses seulement, à tester sur des données neuves '
                            '(condition nécessaire, jamais suffisante)' % len(opened)),
                censored={'%d:%s' % hk: n for hk, n in sorted(censored.items())},
                flat_no_trade={str(h): flat_count[h] for h in HORIZONS},
                sale_convention=dict(sorted(conventions.items())))


# ---------------------------------------------------------------- frozen W1 loading

def check_inputs(pools_dir, manifest_raw):
    sha = hashlib.sha256(manifest_raw).hexdigest()
    if HOLDOUT_PREFIX in str(pools_dir) or sha.startswith(HOLDOUT_PREFIX):
        raise E1Error('holdout_refused')
    if sha != W1_MANIFEST:
        raise E1Error('manifest_not_the_anchored_w1_export:%s' % sha)
    return sha


def load_pool(args):
    """Worker: one pool through the frozen chain; returns (pool, rows or None, reason)."""
    directory, entry, seed, coverage_end = args
    from bot.market import launchlab_curve as curve
    from bot.market.collector import PoolArchive, summarize
    from bot.market.replay import _event_rate
    from bot.p4 import historical_research_replay as hrr
    data = (Path(directory) / entry['file']).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise E1Error('fixture_sha256_mismatch')
    archive = PoolArchive.from_json(json.loads(gzip.decompress(data)))
    if archive.pool != entry['pool']:
        raise E1Error('fixture_pool_mismatch')
    summary, timeline = summarize(archive)
    try:
        timeline, migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded as exc:
        return entry['pool'], None, 'usable_timeline:' + ';'.join(r.split(':')[0] for r in exc.reasons)
    events = list(timeline.events)
    if not events:
        return entry['pool'], None, 'no_event'
    if any(type(e.block_time) is not int for e in events):
        return entry['pool'], None, 'block_time_missing'
    facts = hrr.creation_facts(archive)
    known = (facts.get('mint') is not None and facts['creation_block_time'] is not None)
    start = facts['creation_block_time'] if known else min(e.block_time for e in events)
    migration_time = None
    if migration is not None:
        migration_time = min(archive.transactions[s]['blockTime'] for s in migration['boundary_signatures'])
    rate = int(statistics.median_low([_event_rate(e) for e in events]))
    params = hrr.ReplayParams()
    tx = 2 * (params.base_fee_lamports + params.priority_fee_lamports)
    rows = pool_rows(entry['pool'], events, dict(creation_known=known, start=start), migration_time, coverage_end,
                     seed, rate, tx, curve)
    return entry['pool'], rows, 'retenu'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--pools', type=Path, required=True)
    ap.add_argument('--declaration', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--coverage-end', type=Path)
    ap.add_argument('--workers', type=int, default=1)
    a = ap.parse_args(argv)
    raw = (a.pools / 'MANIFEST.json').read_bytes()
    manifest_sha = check_inputs(a.pools, raw)
    declaration = a.declaration.read_bytes()
    seed = seed_of(declaration)
    coverage = json.loads(a.coverage_end.read_text()) if a.coverage_end else {}
    entries = sorted(json.loads(raw)['pools'], key=lambda e: e['pool'])
    jobs = [(str(a.pools), e, seed, coverage.get(e['pool'])) for e in entries]
    with ProcessPoolExecutor(a.workers) as ex:
        results = list(ex.map(load_pool, jobs, chunksize=8))
    reasons = Counter(r for _p, _rows, r in results)
    kept = [(k, rows) for k, (_p, rows, r) in enumerate(results) if rows is not None]
    retained = sorted(p for p, rows, _r in results if rows is not None)
    res = dict(schema=SCHEMA, stamp=STAMP, declaration_sha256=hashlib.sha256(declaration).hexdigest(), seed=seed,
               manifest_sha256=manifest_sha, pools_in_manifest=len(entries), pool_status=dict(sorted(reasons.items())),
               retained_pools_sha256=hashlib.sha256('\n'.join(retained).encode()).hexdigest(),
               coverage_end_source='inventaire_R03' if coverage else 'dernier_evenement',
               entries=sum(len(rows) for _k, rows in kept), horizons_s=list(HORIZONS), grid=list(GRID),
               stake_lamports=STAKE, rent_lamports=RENT_LAMPORTS, **aggregate(kept, seed))
    a.out.mkdir(parents=True, exist_ok=False)
    text = json.dumps(res, indent=1, sort_keys=True, ensure_ascii=False) + '\n'
    (a.out / 'E1_RESULT.json').write_text(text)
    print('E1_RESULT.json', hashlib.sha256(text.encode()).hexdigest())


if __name__ == '__main__':
    main()
