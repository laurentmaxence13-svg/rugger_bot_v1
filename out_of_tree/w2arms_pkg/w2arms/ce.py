"""w2arms 0.1 -- the W2 arm C-E and its paired placebo (P-4 plan accepted by R02; Dossier B v1.6 sections 4 to 7,
sha 7b867c0f, excerpt 7674243d). OPTION NOT RECOMMENDED by R01 and R02; written so that the slot can be filled.

  python -B -m w2arms.ce rows    --pools <export of ONE W2 window> --manifest-sha256 <anchored> --s0 <window s0> \
                                 --out <NEW DIR>
  python -B -m w2arms.ce verdict --rows <rows_1.json> ... --rows-sha256 <sha_1> ... --freeze-anchor-sha256 <sha> \
                                 --section-6-4 <anchored population json> --section-3 PASS|FAIL --out <NEW DIR>

RULES (unchanged, frozen in the C-E card v0.2, 6d00179d, and in dossier B v1.6):
* decision = the frozen statelab placebo event (label ``placebo:0``: first whole event of age >= the pseudo-random
  target age of the pool, 0 to 120 s, seed = the pool address); buy 0.1 SOL, latency 4 slots; take profit +7 % or stop
  loss -5 % of the cost, otherwise the clock at 30 s (``cdgate.gate.RULE`` through ``statelab.exits.run_rule``);
* C-E = the placebo positions whose TIER of the causal rate (``cdgate.gate.tier``) is <= 2 500 ppm;
  PAIRED PLACEBO (section 6.5) = the same placebo positions WITHOUT the tier restriction, same pools, same exit, same
  account mode;
* FROZEN MODE of C-E: token account CLOSED (``closedacct`` 0.2, failed attempts 0); the rent-lost mode, failed attempts
  = 1 and the 10-slot latency are published apart; denominator = the STAKE; migrated = (-cost - rent) / stake.

``rows``: one window (dayj s0; evaluation range = ``w1_run.plan(s0)['evaluation']``, EVALUATION_SLOTS frozen); one
row per placebo position of a pool created in that range: pool, cluster, creation slot, tier flag, the raw run_rule
outcome (received, cost, tokens, migrated, exit reason), the causal rate, the curve fees in lamports and the outcome at
10 slots. NO RETURN is computed or printed: only counts are printed; R02 anchors the file.
``verdict``: the anchored rows of the k CONSECUTIVE windows (s0_(i+1) = s0_i + 1 612 800), read once, at the end:
section 5 of dossier B (alpha = 0.05 / 3 one-sided, creator-cluster bootstrap 10 000 draws, seed = the first 8 hex
digits of the freeze anchor; halves cut by creation slot at EVAL_MIN_1 + k x 1 612 800 / 2; cost identity with a zero
residual in lamports; INCONCLUSIVE if n < n_min = 414; DESCRIPTIVE if the section 6.4 rule fired; NO-GO otherwise).
Condition 5 (section 3, specific to the candidate) and rule 6.4 are anchored inputs of R02, never computed here.
"""
import argparse
import hashlib
import json
import random
import statistics
from dataclasses import replace
from pathlib import Path

from bot.market.collector import summarize
from bot.market.launchlab_curve import FEE_DENOMINATOR, fee_for
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from cdgate import gate as CG
from closedacct import model as CA
from statelab.exits import SPL_RENT_LAMPORTS, run_rule
from statelab.points import PLACEBO_CELL, decision_points
from statelab.study import STAKE_LAMPORTS, cluster_key
from v3lab import plan
from w1aux.lazy import clear_cache, load_fixtures_lazy

SCHEMA_ROWS, SCHEMA_VERDICT = 'w2arms-ce-rows-v1', 'w2arms-ce-verdict-v1'
WINDOW_SLOTS = 1_612_800                  # EVALUATION_SLOTS of the frozen chain
N_MIN = 414                               # dossier B 6.1: delta +2 %, K = 3
ALPHA_ONE_SIDED = 0.05 / 3                # dossier B section 5
DRAWS = 10_000
LATENCY_SENSITIVITY_SLOTS = 10


class W2ArmsError(RuntimeError):
    pass


def evaluation_range(s0):
    low, high = w1_run.plan(s0)['evaluation']
    return low, high


def curve_fees(outcome, rate):
    """Exact buy fee (fee_for of the stake) and sell fee (fee_for of the gross sale), in lamports."""
    buy = fee_for(STAKE_LAMPORTS, rate)
    if outcome['migrated']:
        return buy, 0
    received = outcome['value']
    gross_sale = (received * FEE_DENOMINATOR) // (FEE_DENOMINATOR - rate)
    return buy, fee_for(gross_sale, rate)


def _outcome(o):
    return None if o is None else dict(migrated=o['migrated'], value=o['value'], cost=o['cost'], tokens=o['tokens'],
                                       reason=o['reason'])


def pool_rows(archive, params, low, high):
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    if not low <= facts['creation_slot'] < high:
        return []
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded:
        return []
    events = timeline.events
    k = next((k for k, labels in decision_points(events, facts['creation_block_time'], archive.pool)
              if PLACEBO_CELL in (f'{a}:{b}' for a, b in labels)), None)
    if k is None:
        return []
    low_tier, rate = CG.eligible(events, k)
    from v4sim.io import actors_from_archive                  # heavy, and only when a position is replayed
    actors, _stats = actors_from_archive(archive, events)
    model = params.execution_model()
    outcome = run_rule(timeline, k, actors, model, CG.RULE)
    if outcome is None:
        return [dict(pool=archive.pool, refused=True, low_tier=low_tier)]
    slow = run_rule(timeline, k, actors, replace(model, latency_slots=LATENCY_SENSITIVITY_SLOTS), CG.RULE)
    buy_fee, sell_fee = curve_fees(outcome, rate)
    return [dict(pool=archive.pool, refused=False, cluster=cluster_key(archive, facts),
                 creation_slot=facts['creation_slot'], low_tier=low_tier, rate=rate, outcome=_outcome(outcome),
                 buy_fee=buy_fee, sell_fee=sell_fee, outcome_latency10=_outcome(slow),
                 slippage=CG.slippage(events, k, rate, outcome))]


def rows(pools_dir, manifest_sha256, s0, params):
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise W2ArmsError('manifest_is_not_the_anchored_one')
    low, high = evaluation_range(s0)
    found = []
    try:
        for _entry, archive in entries:
            found.extend(pool_rows(archive, params, low, high))
    finally:
        clear_cache()
    return dict(schema=SCHEMA_ROWS, s0=s0, evaluation=[low, high], rule=CG.RULE, tier_ppm=CG.LOW_TIER_PPM,
                latency_slots=params.latency_slots, input=dict(manifest_sha256=manifest_sha256), rows=found)


def counts(doc):
    kept = [r for r in doc['rows'] if not r['refused']]
    return dict(placebo_positions=len(kept), c_e_positions=sum(r['low_tier'] for r in kept),
                refused=sum(r['refused'] for r in doc['rows']),
                clusters=len({r['cluster'] for r in kept}))


# ------------------------------------------------------------------ verdict

def net(row, mode, *, failed_attempts=CA.FROZEN_FAILED_ATTEMPTS, outcome_key='outcome'):
    o = row[outcome_key]
    if mode == 'closed':
        return CA.net_return_closed(o, failed_attempts=failed_attempts)
    return CA.net_return_open(o)


def decomposition_lamports(row, mode):
    """(gross, curve fees, tx, rent or cleanup fee, net) in lamports; gross - fees - tx - rent = net exactly."""
    o = row['outcome']
    received = 0 if o['migrated'] else o['value']
    curve = row['buy_fee'] + row['sell_fee']
    tx = o['cost'] - STAKE_LAMPORTS
    rent = CA.CLEANUP_FEE_LAMPORTS if mode == 'closed' and not o['migrated'] else SPL_RENT_LAMPORTS
    gross = received + curve - STAKE_LAMPORTS
    net_lamports = received - o['cost'] - rent
    return gross, curve, tx, rent, net_lamports


def lower_bound(groups, statistic, *, seed, draws=None, alpha=ALPHA_ONE_SIDED):
    """One-sided lower bound (quantile alpha) of a statistic over creator-cluster bootstrap resamples."""
    draws = DRAWS if draws is None else draws
    keys = sorted(groups)
    if not keys:
        return None
    rng, values = random.Random(seed), []
    for _ in range(draws):
        picked = [groups[keys[rng.randrange(len(keys))]] for _k in keys]
        value = statistic([row for group in picked for row in group])
        if value is not None:
            values.append(value)
    values.sort()
    return values[max(0, int(alpha * len(values)) - 1)] if values else None


def _mean(values):
    return statistics.fmean(values) if values else None


def verdict(docs, *, freeze_anchor_sha256, section_6_4_fired, section_3_pass, mode='closed', n_min=N_MIN):
    if (type(freeze_anchor_sha256) is not str or len(freeze_anchor_sha256) != 64
            or any(c not in '0123456789abcdef' for c in freeze_anchor_sha256)):
        raise W2ArmsError('freeze_anchor_sha256_required')
    if not docs:
        raise W2ArmsError('no_rows')
    base = docs[0]
    for i, doc in enumerate(docs):
        if doc.get('schema') != SCHEMA_ROWS or doc['rule'] != CG.RULE or doc['tier_ppm'] != CG.LOW_TIER_PPM \
                or doc['latency_slots'] != base['latency_slots']:
            raise W2ArmsError('rows_of_another_rule')
        if doc['s0'] != base['s0'] + i * WINDOW_SLOTS:
            raise W2ArmsError('windows_not_consecutive')
    all_rows = [r for doc in docs for r in doc['rows'] if not r['refused']]
    pools = [r['pool'] for doc in docs for r in doc['rows']]
    if len(pools) != len(set(pools)):
        raise W2ArmsError('a_pool_in_two_windows')
    seed = int(freeze_anchor_sha256[:8], 16)
    eval_min_1 = docs[0]['evaluation'][0]
    middle = eval_min_1 + len(docs) * WINDOW_SLOTS // 2
    cand = [r for r in all_rows if r['low_tier']]
    groups = {}
    for r in all_rows:
        groups.setdefault(r['cluster'], []).append(r)

    def mean_c(rows_):
        return _mean([net(r, mode) for r in rows_ if r['low_tier']])

    def diff(rows_):
        c, p = mean_c(rows_), _mean([net(r, mode) for r in rows_])
        return None if c is None or p is None else c - p
    n = len(cand)
    low_mean = lower_bound(groups, mean_c, seed=seed)
    low_diff = lower_bound(groups, diff, seed=seed)
    halves = [_mean([net(r, mode) for r in cand if r['creation_slot'] < middle]),
              _mean([net(r, mode) for r in cand if r['creation_slot'] >= middle])]
    residuals = []
    for r in cand:
        gross, curve, tx, rent, net_l = decomposition_lamports(r, mode)
        residuals.append(gross - curve - tx - rent - net_l)
        if net_l / STAKE_LAMPORTS != net(r, mode) and abs(net_l / STAKE_LAMPORTS - net(r, mode)) > 1e-12:
            raise W2ArmsError('net_differs_from_closedacct')
    conditions = dict(c1_profitability=low_mean is not None and low_mean > 0,
                      c2_superiority_to_paired_placebo=low_diff is not None and low_diff > 0,
                      c3_both_halves_positive=all(h is not None and h > 0 for h in halves),
                      c4_cost_identity_zero_residual=bool(cand) and all(x == 0 for x in residuals),
                      c5_section_3=section_3_pass is True)
    if section_6_4_fired:
        decision = 'DESCRIPTIVE'
    elif n < n_min:
        decision = 'INCONCLUSIVE'
    elif all(conditions.values()):
        decision = 'GO'
    else:
        decision = 'NO-GO'
    parts = [decomposition_lamports(r, mode) for r in cand]
    share = (lambda i: _mean([p[i] / STAKE_LAMPORTS for p in parts]))
    return dict(schema=SCHEMA_VERDICT, candidate='C-E', frozen_mode=mode, windows=len(docs), n=n, n_min=n_min,
                clusters=len({r['cluster'] for r in cand}), seed=seed, draws=DRAWS, alpha_one_sided=ALPHA_ONE_SIDED,
                mean_net_return=_mean([net(r, mode) for r in cand]),
                lower_bound_mean=low_mean, lower_bound_minus_paired_placebo=low_diff,
                paired_placebo=dict(n=len(all_rows), mean_net_return=_mean([net(r, mode) for r in all_rows])),
                halves=dict(cut_slot=middle, means=halves), conditions=conditions, decision=decision,
                decomposition_mean_share_of_stake=dict(gross=share(0), curve_fees=share(1), tx=share(2), rent_or_cleanup=share(3),
                                                       net=share(4)),
                published_apart=dict(
                    rent_lost_mode=_mean([net(r, 'open') for r in cand]),
                    failed_attempts_1=_mean([net(r, 'closed', failed_attempts=CA.SENSITIVITY_FAILED_ATTEMPTS) for r in cand])
                    if mode == 'closed' else None,
                    latency_10_slots=_mean([net(r, mode, outcome_key='outcome_latency10') for r in cand
                                            if r['outcome_latency10'] is not None]),
                    win_rate=_mean([net(r, mode) > 0 for r in cand]),
                    min=min((net(r, mode) for r in cand), default=None), max=max((net(r, mode) for r in cand), default=None)),
                inputs=dict(section_6_4_fired=section_6_4_fired, section_3_pass=section_3_pass,
                            freeze_anchor_sha256=freeze_anchor_sha256))


def _write(out_dir, name, doc):
    out = Path(out_dir)
    if out.exists():
        raise W2ArmsError('output_exists')
    out.mkdir(parents=True)
    path = out / name
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='w2arms.ce')
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('rows')
    r.add_argument('--pools', type=Path, required=True)
    r.add_argument('--manifest-sha256', required=True)
    r.add_argument('--s0', type=int, required=True)
    v = sub.add_parser('verdict')
    v.add_argument('--rows', type=Path, nargs='+', required=True)
    v.add_argument('--rows-sha256', nargs='+', required=True)
    v.add_argument('--freeze-anchor-sha256', required=True)
    v.add_argument('--section-6-4', type=Path, required=True)
    v.add_argument('--section-3', choices=('PASS', 'FAIL'), required=True)
    for p in (r, v):
        p.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise W2ArmsError('output_exists')
    if a.command == 'rows':
        doc = rows(a.pools, a.manifest_sha256, a.s0, hrr.ReplayParams(latency_slots=plan.REPLAY['latency_slots']))
        sha = _write(a.out, 'W2_CE_ROWS.json', doc)
        print(json.dumps(dict(counts=counts(doc), rows_sha256=sha, s0=a.s0), sort_keys=True))   # counts only
        return 0
    if len(a.rows) != len(a.rows_sha256):
        raise W2ArmsError('one_sha256_per_rows_file')
    docs = []
    for path, sha in zip(a.rows, a.rows_sha256):
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise W2ArmsError('rows_are_not_the_anchored_ones')
        docs.append(json.loads(raw))
    fired = json.loads(a.section_6_4.read_text())
    if type(fired.get('descriptive')) is not bool:
        raise W2ArmsError('section_6_4_input_must_state_descriptive')
    doc = verdict(docs, freeze_anchor_sha256=a.freeze_anchor_sha256, section_6_4_fired=fired['descriptive'],
                  section_3_pass=a.section_3 == 'PASS')
    doc['rows_sha256'] = list(a.rows_sha256)
    _write(a.out, 'W2_CE_VERDICT.json', doc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
