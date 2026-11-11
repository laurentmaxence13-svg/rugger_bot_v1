"""Joint measure of the three engines: token selection (S), buy timing (A), sell timing (V).

  python -B -m jointlab.joint rows     <export_dir> --expect-manifest-sha <sha256> --out <rows.json>
                                       --slot-min <slot> --slot-max <slot>
                                       [--official-verdict-sha256 <sha256> --hypotheses-verdict-sha256 <sha256>]
                                       [--latency-slots 4]
  python -B -m jointlab.joint cutoffs  <rows.json> --out <cutoffs.json>
  python -B -m jointlab.joint counts   <rows.json> --cutoffs <cutoffs.json> --plan star|full|combined [--cell S,A,V]
  python -B -m jointlab.joint analysis <rows.json> --cutoffs <cutoffs.json> --plan ... [--cell S,A,V]
                                       --declared-cells <m> [--census <census.json>] [--markdown <file>]

The grid below is written BEFORE any reading. ``rows``, ``cutoffs`` and ``counts`` print SAMPLE SIZES ONLY;
``analysis`` reads the values and adds one trial per evaluable cell of its plan to the cumulative count N.

Factors
  S  a predicate on what is known AT THE DECISION (features of the history up to the deciding event, the
     creation transaction). Thirds are cut on the values of a REFERENCE rows file (the discovery part) and
     applied unchanged elsewhere: ``cutoffs`` never reads an outcome.
  A  the deciding event: placebo (frozen random age), fixed ages, the frozen causal triggers of
     ``statelab.hypotheses`` and labels of ``statelab.points``. ONE entry per pool and per A: its first occurrence.
  V  a causal exit rule of ``statelab.exits`` (the clock always sells in the end).
Every position is 0.1 SOL, valued by v4sim M-P with the frozen latency on the buy and on the sale;
r = (proceeds - cost - rent lost) / (cost + rent lost); a migrated position counts -1.

Plans
  star      the base cell and every cell that changes ONE factor (1 + 4 + 6 + 3 = 14): the separate
            contribution of each engine, as a difference to the base cell.
  combined  ONE cell (S, A, V) chosen beforehand, with the base cell and its three one-factor cells:
            interaction = r(S,A,V) - r(base) - effect(S) - effect(A) - effect(V).
  full      the whole grid (5 x 7 x 4 = 140), descriptive.
A cell is evaluable with at least 30 positions from 20 creator clusters. Claims use Holm over the evaluable
cells of the plan. The code never says "profitable".

``--slot-min`` / ``--slot-max`` bound the CREATION slot of the pools: a pool, with all its entries, belongs
to one part only (discovery or screen), fixed beforehand.

Reading W1 needs the sha256 of the anchored official verdict AND of the anchored verdict of the frozen
hypotheses (W1 becomes development data only after both). There is no reader for the P0 visible pack.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics

from bot.market.collector import summarize
from bot.master_v2.features import native_features
from bot.p4 import historical_research_replay as hrr

from v3lab import plan as v3plan
from v3lab.evaluate import _interval, holm
from v3lab.features import v3_extras

from v4sim.io import actors_from_archive

from statelab import exits, hypotheses as hyp
from statelab.points import PLACEBO_CELL, decision_points
from statelab.study import cluster_key, window_cutoff

SCHEMA = 'jointlab-rows-v1'
SELECTORS = (
    dict(id='S0', label='every pool'),
    dict(id='S1', label='lowest third of the causal fee rate', feature='fee_rate_ppm_causal', side='low'),
    dict(id='S2', label='lowest third of curve progress at the decision', feature='progress_ppm', side='low'),
    dict(id='S3', label='highest third of payers of the first two slots', feature='early_slot_payers', side='high'),
    dict(id='S4', label='declared creator not a signer of the creation', flag='creator_not_signer'),
)
ENTRIES = (
    dict(id='PLACEBO', label='frozen random age (0-120 s)', point=PLACEBO_CELL),
    dict(id='A0', label='first trade (age 0)', point='age:0'),
    dict(id='A5', label='age 5 s', point='age:5'),
    dict(id='DIP', label='sale that takes the spot 10 % under its 10 s reference, 5 SOL left', trigger='dip'),
    dict(id='PURGE', label='buy after three quarters of the tokens came back', trigger='purge'),
    dict(id='LATE', label='curve progress 65 %', point='progress:650000'),
    dict(id='SURV', label='age 600 s', point='age:600'),
)
EXITS = (
    dict(id='V0', label='clock 25 s', clock_s=25),
    dict(id='V1', label='clock 60 s', clock_s=60),
    dict(id='V2', label='first real sale after landing, clock 60 s', first_sale=True, clock_s=60),
    dict(id='V3', label='curve flow negative over 10 s, clock 60 s', flow_window_s=10, clock_s=60),
)
BASE = ('S0', 'PLACEBO', 'V0')
PLANS = ('star', 'combined', 'full')
SELECTION_FEATURES = tuple(s['feature'] for s in SELECTORS if 'feature' in s)
MIN_POSITIONS, MIN_CLUSTERS = 30, 20
N_BOOT = 5_000
SEED = 20261114
SPL_RENT_LAMPORTS = 2_039_280
_HEX = set('0123456789abcdef')


def fingerprint():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# --- rows: one per pool and entry, valued under every exit ----------------------------------------

def entry_indexes(events, facts, pool):
    """{entry id: deciding event index or None}; each one reads the history up to that event only."""
    labels = {}
    for k, items in decision_points(events, facts['creation_block_time'], pool):
        for kind, level in items:
            labels.setdefault(f'{kind}:{level}', k)
    out = {}
    for entry in ENTRIES:
        if 'point' in entry:
            out[entry['id']] = labels.get(entry['point'])
        elif entry['trigger'] == 'dip':
            out[entry['id']] = hyp.dip_trigger(events)
        else:
            out[entry['id']] = hyp.purge_trigger(events, facts['creation_block_time'])
    return out


def pool_rows(archive, entry, segment, params, cutoff_slot, slot_range=None):
    """Rows of one pool and the counted reasons why some entries give none."""
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded:
        return [], {'pool_not_replayable': 1}
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    if slot_range is not None and not slot_range[0] <= facts['creation_slot'] < slot_range[1]:
        return [], {'pool_created_outside_slot_range': 1}        # a pool belongs to ONE part: that of its creation
    events = timeline.events
    if not events:
        return [], {'pool_without_trade': 1}
    actors, _stats = actors_from_archive(archive, events)
    model = params.execution_model()
    rows, missing = [], {}

    def miss(key, reason):
        missing[f'{key}:{reason}'] = missing.get(f'{key}:{reason}', 0) + 1

    for key, k in entry_indexes(events, facts, archive.pool).items():
        if k is None:
            continue
        slot = events[k].slot
        if cutoff_slot is not None and slot > cutoff_slot:
            miss(key, 'exit_would_leave_the_window')
            continue
        outcomes = {rule['id']: exits.run_rule(timeline, k, actors, model, rule) for rule in EXITS}
        first = outcomes[EXITS[0]['id']]
        if first is None:
            miss(key, 'buy_refused')
            continue
        if any(o is None or (o['land_index'], o['tokens'], o['cost']) != (first['land_index'], first['tokens'], first['cost'])
               for o in outcomes.values()):
            raise ValueError('exits_do_not_share_the_same_entry')
        landing = events[first['land_index']].slot
        features = dict(native_features(events[:k + 1], facts), **v3_extras(events[:k + 1], facts))
        rows.append(dict(
            pool=archive.pool, creator=cluster_key(archive, facts), segment=segment, entry=key, decision_index=k,
            creation_slot=facts['creation_slot'],
            decision_slot=slot, decision_block_time=events[k].block_time, entry_slot=landing, cost=first['cost'],
            features={name: features.get(name) for name in SELECTION_FEATURES},
            creator_not_signer=hyp.creator_not_signer(facts),
            exits={rule: dict(migrated=o['migrated'], value=o['value'], reason=o['reason']) for rule, o in outcomes.items()}))
    return rows, missing


def run_export(directory, expect_manifest_sha256, *, slot_range, official_verdict_sha256=None,
               hypotheses_verdict_sha256=None, latency_slots=v3plan.REPLAY['latency_slots']):
    manifest_sha256, _digests, pools, manifest = hrr.load_fixtures(directory)
    if type(expect_manifest_sha256) is not str or manifest_sha256 != expect_manifest_sha256:
        raise ValueError('export_manifest_sha256_is_not_the_expected_one')
    if not (type(slot_range[0]) is int and type(slot_range[1]) is int and slot_range[0] < slot_range[1]):
        raise ValueError('invalid_slot_range')
    end = manifest.get('window_slot_max')
    reaches_w1 = (type(end) is int and end >= v3plan.S0_W1) or any(
        tx.get('slot', 0) >= v3plan.S0_W1 for _entry, archive in pools for tx in archive.transactions.values())
    if reaches_w1:
        for value in (official_verdict_sha256, hypotheses_verdict_sha256):
            if type(value) is not str or len(value) != 64 or set(value) - _HEX:
                raise ValueError('w1_data_need_the_official_verdict_and_the_frozen_hypotheses_verdict')
        if official_verdict_sha256 == hypotheses_verdict_sha256:
            raise ValueError('the_two_verdicts_are_two_different_documents')
    params = hrr.ReplayParams(latency_slots=latency_slots)
    rows, missing = [], {}
    for entry, archive in pools:
        found, reasons = pool_rows(archive, entry, 'export', params, window_cutoff(entry, manifest, params), slot_range)
        rows.extend(found)
        for key, count in reasons.items():
            missing[key] = missing.get(key, 0) + count
    document = dict(
        schema=SCHEMA, status='EXPLORATORY', jointlab_sha256=fingerprint(), hypotheses_sha256=hyp.fingerprint(),
        exits_sha256=exits.fingerprint(), pack_manifest_sha256=manifest_sha256, slot_range=list(slot_range),
        latency_slots=latency_slots, official_verdict_sha256=official_verdict_sha256,
        hypotheses_verdict_sha256=hypotheses_verdict_sha256, w1_data_read=bool(reaches_w1), pools_read=len(pools),
        missing=dict(sorted(missing.items())), entries={e['id']: sum(r['entry'] == e['id'] for r in rows) for e in ENTRIES},
        rows=rows, flags=dict(holdout_read=False, promotion_allowed=False, financial_order_submitted=False))
    document['rows_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return document


# --- selection: thirds cut on a reference file, applied unchanged ---------------------------------

def cutoffs(document):
    """{entry: {feature: [first third, second third]}} from the feature values alone (no outcome is read)."""
    if document.get('schema') != SCHEMA:
        raise ValueError('not_a_jointlab_rows_document')
    out = {}
    for entry in ENTRIES:
        block = {}
        for feature in SELECTION_FEATURES:
            values = sorted(r['features'][feature] for r in document['rows']
                            if r['entry'] == entry['id'] and r['features'].get(feature) is not None)
            if len(values) >= 3:
                block[feature] = [values[(len(values) - 1) // 3], values[(2 * (len(values) - 1) + 2) // 3]]
        out[entry['id']] = block
    return dict(schema='jointlab-cutoffs-v1', reference_rows_sha256=document['rows_sha256'], cutoffs=out)


def selected(row, selector, cuts):
    """True / False; a value that cannot be read is never selected."""
    if 'flag' in selector:
        return row.get(selector['flag']) is True
    if 'feature' not in selector:
        return True
    value = row['features'].get(selector['feature'])
    bounds = cuts['cutoffs'].get(row['entry'], {}).get(selector['feature'])
    if value is None or bounds is None:
        return False
    return value <= bounds[0] if selector['side'] == 'low' else value >= bounds[1]


# --- cells, plans and counts ----------------------------------------------------------------------

def _ids(items):
    return [item['id'] for item in items]


def plan_cells(plan, cell=None):
    if plan not in PLANS:
        raise ValueError('unknown_plan')
    if plan == 'full':
        return [(s, a, v) for s in _ids(SELECTORS) for a in _ids(ENTRIES) for v in _ids(EXITS)]
    if plan == 'star':
        return ([BASE] + [(s, BASE[1], BASE[2]) for s in _ids(SELECTORS) if s != BASE[0]]
                + [(BASE[0], a, BASE[2]) for a in _ids(ENTRIES) if a != BASE[1]]
                + [(BASE[0], BASE[1], v) for v in _ids(EXITS) if v != BASE[2]])
    if (cell is None or len(cell) != 3 or cell[0] not in _ids(SELECTORS) or cell[1] not in _ids(ENTRIES)
            or cell[2] not in _ids(EXITS) or sum(x != y for x, y in zip(cell, BASE)) < 2):
        raise ValueError('the_combined_plan_needs_one_cell_that_changes_at_least_two_factors')
    cell = tuple(cell)
    singles = [(cell[0], BASE[1], BASE[2]), (BASE[0], cell[1], BASE[2]), (BASE[0], BASE[1], cell[2])]
    return [BASE] + [c for c in singles if c != BASE] + [cell]


def members(document, cuts, cell):
    selector = next(s for s in SELECTORS if s['id'] == cell[0])
    return [r for r in document['rows'] if r['entry'] == cell[1] and selected(r, selector, cuts)]


def counts(document, cuts, plan, cell=None):
    """Sample sizes of every cell of the plan: nothing here is a value."""
    out = {}
    for c in plan_cells(plan, cell):
        rows = members(document, cuts, c)
        clusters = len({r['creator'] for r in rows})
        out[','.join(c)] = dict(positions=len(rows), clusters=clusters,
                                migrated=sum(r['exits'][c[2]]['migrated'] for r in rows),
                                evaluable=bool(len(rows) >= MIN_POSITIONS and clusters >= MIN_CLUSTERS))
    return dict(plan=plan, cells=out, evaluable_cells=sum(b['evaluable'] for b in out.values()))


# --- values ---------------------------------------------------------------------------------------

def position_return(row, exit_id, rents):
    outcome = row['exits'][exit_id]
    rent = SPL_RENT_LAMPORTS if rents is None else rents.get(row['pool'], (None, None))[1]
    if rent is None:
        raise ValueError('token_class_unknown_for_a_pool')
    if outcome['migrated']:
        return -1.0
    return (outcome['value'] - row['cost'] - rent) / (row['cost'] + rent)


def max_drawdown(returns):
    """Largest fall of the running sum (in stakes), positions in the given order."""
    total = peak = worst = 0.0
    for value in returns:
        total += value
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def joint_bootstrap(statistics_, *, n_boot, seed=SEED):
    """{name: sorted draws} for linear combinations of cell means, creator clusters resampled JOINTLY.

    ``statistics_``: {name: [(weight, [(value, cluster), ...]), ...]}. The same resampled clusters serve
    every statistic of a draw; a draw that empties one of the cells of a statistic is dropped for it.
    """
    clusters = sorted({g for parts in statistics_.values() for _w, items in parts for _v, g in items})
    index = {g: i for i, g in enumerate(clusters)}
    packed = {}
    for name, parts in statistics_.items():
        packed[name] = []
        for weight, items in parts:
            sums, sizes = {}, {}
            for value, group in items:
                i = index[group]
                sums[i], sizes[i] = sums.get(i, 0.0) + value, sizes.get(i, 0) + 1
            packed[name].append((weight, sums, sizes))
    rng = random.Random(seed)
    draws = {name: [] for name in statistics_}
    for _ in range(n_boot if clusters else 0):
        weights = [0] * len(clusters)
        for _k in range(len(clusters)):
            weights[rng.randrange(len(clusters))] += 1
        for name, parts in packed.items():
            total = 0.0
            for weight, sums, sizes in parts:
                size = sum(weights[i] * n for i, n in sizes.items())
                if not size:
                    total = None
                    break
                total += weight * sum(weights[i] * s for i, s in sums.items()) / size
            if total is not None:
                draws[name].append(total)
    return {name: sorted(values) for name, values in draws.items()}


def _summary(draws):
    if not draws:
        return None, None
    return _interval(draws, 0.05), (sum(d <= 0 for d in draws) + 1) / (len(draws) + 1)


def analysis(document, cuts, census=None, *, plan, declared_cells, cell=None, n_boot=N_BOOT):
    if document.get('schema') != SCHEMA or cuts.get('schema') != 'jointlab-cutoffs-v1':
        raise ValueError('not_jointlab_documents')
    sizes = counts(document, cuts, plan, cell)
    if type(declared_cells) is not int or declared_cells != sizes['evaluable_cells']:
        raise ValueError('declared_cells_is_not_the_number_of_evaluable_cells:%d' % sizes['evaluable_cells'])
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    cells = [c for c in plan_cells(plan, cell) if sizes['cells'][','.join(c)]['evaluable']]
    data = {}
    for c in cells:
        rows = sorted(members(document, cuts, c), key=lambda r: (r['decision_slot'], r['pool']))
        data[c] = [(position_return(r, c[2], rents), r['creator']) for r in rows]
    mean = {c: statistics.fmean(v for v, _g in items) for c, items in data.items()}
    stats = {('cell', c): [(1.0, items)] for c, items in data.items()}
    if BASE in data:
        for c in cells:
            if c != BASE:
                stats[('effect', c)] = [(1.0, data[c]), (-1.0, data[BASE])]
    interaction = None
    if plan == 'combined' and len(cells) == len(plan_cells(plan, cell)):
        singles = [c for c in cells if c not in (BASE, tuple(cell))]
        parts = [(1.0, data[tuple(cell)]), (float(len(singles) - 1), data[BASE])] + [(-1.0, data[c]) for c in singles]
        stats[('interaction', tuple(cell))] = parts
        interaction = sum(w * statistics.fmean(v for v, _g in items) for w, items in parts)
    draws = joint_bootstrap(stats, n_boot=n_boot)
    out, cell_p, effect_p = {}, [], []
    for c in cells:
        values = [v for v, _g in data[c]]
        wins, losses = [v for v in values if v > 0], [v for v in values if v <= 0]
        interval, p = _summary(draws[('cell', c)])
        top = sorted(wins, reverse=True)[:5]
        block = dict(
            positions=len(values), clusters=len({g for _v, g in data[c]}), mean_r=mean[c], mean_r_ci95=interval,
            p_one_sided=p, median_r=statistics.median(values), win_rate=len(wins) / len(values),
            mean_gain=statistics.fmean(wins) if wins else None, mean_loss=statistics.fmean(losses) if losses else None,
            max_drawdown_stakes=max_drawdown(values), top5_share_of_gains=sum(top) / sum(wins) if wins else None,
            migrated=sizes['cells'][','.join(c)]['migrated'])
        cell_p.append(p)
        if ('effect', c) in draws:
            e_interval, e_p = _summary(draws[('effect', c)])
            block['effect_vs_base'] = dict(mean=mean[c] - mean[BASE], ci95=e_interval, p_one_sided=e_p)
            effect_p.append(e_p)
        out[','.join(c)] = block
    for c, p in zip(cells, holm(cell_p)):
        block = out[','.join(c)]
        low = (block['mean_r_ci95'] or [None])[0]
        block['p_holm'] = p
        block['net_positive_after_holm'] = bool(block['mean_r'] > 0 and low is not None and low > 0
                                                and p is not None and p < 0.05)
    for c, p in zip([c for c in cells if 'effect_vs_base' in out[','.join(c)]], holm(effect_p)):
        effect = out[','.join(c)]['effect_vs_base']
        low = (effect['ci95'] or [None])[0]
        effect['p_holm'] = p
        effect['positive_after_holm'] = bool(low is not None and low > 0 and p is not None and p < 0.05)
    result = dict(
        schema='jointlab-analysis-v1', status='EXPLORATORY', plan=plan, combined_cell=list(cell) if cell else None,
        base=list(BASE), rows_sha256=document['rows_sha256'], cutoffs_reference_rows_sha256=cuts['reference_rows_sha256'],
        cutoffs_from_the_same_rows=cuts['reference_rows_sha256'] == document['rows_sha256'],
        jointlab_sha256=fingerprint(), slot_range=document.get('slot_range'),
        rent_basis='token class of the census' if rents is not None else 'ASSUMED: SPL Token rent for every pool',
        sizes=sizes['cells'], evaluable_cells=sizes['evaluable_cells'], trials_added_to_n=sizes['evaluable_cells'],
        cells=out, notes=[
            'every evaluable cell of the plan was computed and counts in N; cells under the floors have no value',
            'effects are differences of cell means to the base cell, creator clusters resampled jointly',
            'a positive effect is not a positive net result: read net_positive_after_holm of the cell itself',
            'r includes every cost and the rent lost; a migrated position counts -1'])
    if ('interaction', tuple(cell) if cell else None) in draws:
        i_interval, i_p = _summary(draws[('interaction', tuple(cell))])
        result['interaction'] = dict(mean=interaction, ci95=i_interval, p_one_sided=i_p)
    return result


def _pct(value, digits=2):
    return 'n/a' if value is None else f'{100 * value:+.{digits}f} %'


def markdown(result):
    lines = [f"# jointlab — plan {result['plan']} (exploratory, {result['trials_added_to_n']} trials added to N)", '',
             f"Base cell: {', '.join(result['base'])}. Rent: {result['rent_basis']}.", '',
             '| Cell (S, A, V) | Positions | Clusters | Mean net r | 95 % CI | Median | Winners | Drawdown (stakes) '
             '| Effect vs base | 95 % CI | Net positive after Holm |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for key, size in result['sizes'].items():
        block = result['cells'].get(key)
        if block is None:
            lines.append(f"| {key} | {size['positions']} | {size['clusters']} | NOT EVALUABLE | | | | | | | |")
            continue
        effect = block.get('effect_vs_base')
        ci = block['mean_r_ci95']
        lines.append('| %s | %d | %d | %s | [%s; %s] | %s | %s | %.1f | %s | %s | %s |' % (
            key, block['positions'], block['clusters'], _pct(block['mean_r']), _pct(ci[0]), _pct(ci[1]),
            _pct(block['median_r']), _pct(block['win_rate'], 0), block['max_drawdown_stakes'],
            _pct(effect['mean']) if effect else '', '[%s; %s]' % (_pct(effect['ci95'][0]), _pct(effect['ci95'][1])) if effect else '',
            'yes' if block['net_positive_after_holm'] else 'no'))
    if 'interaction' in result:
        i = result['interaction']
        lines += ['', 'Interaction (combined minus base minus the three separate effects): %s [%s; %s]' % (
            _pct(i['mean']), _pct(i['ci95'][0]), _pct(i['ci95'][1]))]
    return '\n'.join(lines + [''] + ['- ' + note for note in result['notes']]) + '\n'


def _write(path, payload):
    path = Path(path)
    if path.exists():
        raise SystemExit('output_exists')
    path.write_text(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='jointlab.joint')
    sub = parser.add_subparsers(dest='command', required=True)
    rows = sub.add_parser('rows')
    rows.add_argument('directory')
    rows.add_argument('--expect-manifest-sha', required=True)
    rows.add_argument('--out', required=True)
    rows.add_argument('--slot-min', type=int, required=True)
    rows.add_argument('--slot-max', type=int, required=True)
    rows.add_argument('--official-verdict-sha256')
    rows.add_argument('--hypotheses-verdict-sha256')
    rows.add_argument('--latency-slots', type=int, default=v3plan.REPLAY['latency_slots'])
    cut = sub.add_parser('cutoffs')
    cut.add_argument('rows')
    cut.add_argument('--out', required=True)
    for name in ('counts', 'analysis'):
        p = sub.add_parser(name)
        p.add_argument('rows')
        p.add_argument('--cutoffs', required=True)
        p.add_argument('--plan', required=True, choices=PLANS)
        p.add_argument('--cell')
        if name == 'analysis':
            p.add_argument('--declared-cells', type=int, required=True)
            p.add_argument('--census')
            p.add_argument('--markdown')
    args = parser.parse_args(argv)
    if args.command == 'rows':
        document = run_export(args.directory, args.expect_manifest_sha, slot_range=(args.slot_min, args.slot_max),
                              official_verdict_sha256=args.official_verdict_sha256,
                              hypotheses_verdict_sha256=args.hypotheses_verdict_sha256, latency_slots=args.latency_slots)
        _write(args.out, json.dumps(document, sort_keys=True))
        print(json.dumps(dict(rows_sha256=document['rows_sha256'], pools_read=document['pools_read'],
                              entries=document['entries'], missing=document['missing']), sort_keys=True))
        return
    document = json.loads(Path(args.rows).read_text())
    if args.command == 'cutoffs':
        cuts = cutoffs(document)
        _write(args.out, json.dumps(cuts, sort_keys=True))
        print(json.dumps(dict(reference_rows_sha256=cuts['reference_rows_sha256'],
                              features={k: sorted(v) for k, v in cuts['cutoffs'].items()}), sort_keys=True))
        return
    cuts = json.loads(Path(args.cutoffs).read_text())
    cell = tuple(args.cell.split(',')) if args.cell else None
    if args.command == 'counts':
        print(json.dumps(counts(document, cuts, args.plan, cell), sort_keys=True))
        return
    census = json.loads(Path(args.census).read_text()) if args.census else None
    result = analysis(document, cuts, census, plan=args.plan, declared_cells=args.declared_cells, cell=cell)
    if args.markdown:
        _write(args.markdown, markdown(result))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
