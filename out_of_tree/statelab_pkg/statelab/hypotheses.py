"""The five pre-registered W1 hypotheses (sheet N v0.2): causal triggers, positions, counts and verdicts.

  python -B -m statelab.hypotheses p0     <visible_pack> --expect-manifest-sha <sha256> --out <rows.json>
                                          [--confirm-validation HW1] [--latency-slots 4]
  python -B -m statelab.hypotheses export <export_dir> --expect-manifest-sha <sha256> --out <rows.json>
                                          [--evaluation-min <slot> --evaluation-max <slot>]
                                          [--official-verdict-sha256 <sha256>] [--latency-slots 4]
  python -B -m statelab.hypotheses verdicts <rows.json> --declared-m <m> [--census <census.json>]
                                          [--latency10 <rows_lat10.json>] [--markdown <file>]

``p0`` / ``export`` print SAMPLE SIZES ONLY (positions, clusters, share of migrated positions, distinct
payers): the freeze of RUGGER 02 comes after these counts and before any value. ``verdicts`` reads the
values: it adds one trial per hypothesis to N.

ONE position per pool and hypothesis: the FIRST whole event of the pool's life that satisfies the
trigger, decided from the history up to that event only. If that first occurrence falls outside the
evaluation range (W1: warm-up) or too late for its exit to land inside the collected window, the
pool gives no position for that hypothesis (counted), never a later occurrence.

Triggers (definitions F-4: spot = effective quote reserve / effective base reserve; "at least 10 s
old" = block_time <= t - 10; real SOL = real_quote; tokens in circulation = real_base):
  HW1-1 REPLI          the event is a SELL; real_quote after it >= 5 SOL; spot after it <= 90 % of the spot
                       left by the last event at least 10 s old (launch spot when there is none); exit 25 s
  HW1-2 PURGE          the event is a BUY; pool age >= 30 s; the past maximum of real_quote reached 2 SOL;
                       real_base just BEFORE this buy <= 25 % of its past maximum; exit 60 s
  HW1-3 FIN DE COURBE  label progress:650000 of statelab.points; exit 60 s
  HW1-4 SURVIVANT      label age:600 of statelab.points; exit 120 s
  HW1-5 NON SIGNE      label age:0 of a pool whose creator, declared by the LaunchLab creation instruction,
                       is NOT a signer of the creation transaction (frozen reason
                       'creator_not_a_transaction_signer'; Ed25519 verification plays no part; unreadable
                       creator: pool excluded and counted); exit 10 s; EXPLORATORY, FROM P0
Positions are the probes of ``statelab.study`` (0.1 SOL, frozen latency, frozen clock exit, v4sim M-P).
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from bot.market.collector import summarize
from bot.p4 import historical_research_replay as hrr

from v3lab import plan
from v3lab.evaluate import _interval, cluster_bootstrap_means, holm
from v3lab.pack import Pack

from v4sim.io import actors_from_archive

from statelab.points import PLACEBO_CELL, decision_points, whole
from statelab.study import DISCOVERY_SEGMENTS, cluster_key, probe, window_cutoff
from statelab.table import probe_return

SCHEMA = 'statelab-hypothesis-rows-v1'
SOL = 1_000_000_000
DIP_MIN_REAL_QUOTE = 5 * SOL
DIP_WINDOW_S = 10
DIP_RATIO = (9, 10)                       # spot after the sale <= 9/10 of the reference spot
PURGE_MIN_AGE_S = 30
PURGE_MIN_PEAK_REAL_QUOTE = 2 * SOL
PURGE_BASE_RATIO = (1, 4)                 # real_base before the buy <= 1/4 of its past maximum
HYPOTHESES = (
    dict(id='HW1-1', name='REPLI', horizon=25),
    dict(id='HW1-2', name='PURGE', horizon=60),
    dict(id='HW1-3', name='FIN DE COURBE', horizon=60, label=['progress', 650_000]),
    dict(id='HW1-4', name='SURVIVANT', horizon=120, label=['age', 600]),
    dict(id='HW1-5', name='NON SIGNE', horizon=10, label=['age', 0], exploratory=True),
)
PLACEBO = 'PLACEBO'
MIN_POSITIONS, MIN_CLUSTERS, MAX_MIGRATED_SHARE = 30, 20, 0.10
R1_CLOSED, R1_CREATORS = 200, 100
MIN_PAYERS = 20
N_BOOT = 10_000
SEED = 20261113
NOT_SIGNER = 'creator_not_a_transaction_signer'


def dip_trigger(events):
    """HW1-1: first whole SELL leaving >= 5 SOL real whose spot is <= 90 % of the spot of 10 s earlier."""
    launch, old = events[0].state_before(), -1
    for k, event in enumerate(events):
        while old + 1 < k and events[old + 1].block_time <= event.block_time - DIP_WINDOW_S:
            old += 1
        if not whole(events, k) or event.side != 'sell' or event.real_quote_after < DIP_MIN_REAL_QUOTE:
            continue
        reference = events[old].state_after() if old >= 0 else launch
        now = event.state_after()
        if (now.quote_reserve * reference.base_reserve * DIP_RATIO[1]
                <= DIP_RATIO[0] * reference.quote_reserve * now.base_reserve):
            return k
    return None


def purge_trigger(events, created_block_time):
    """HW1-2: first whole BUY, pool aged >= 30 s, after real_quote once reached 2 SOL and real_base fell to a quarter."""
    peak_quote, peak_base = events[0].real_quote_before, events[0].real_base_before
    for k, event in enumerate(events):
        if (whole(events, k) and event.side == 'buy' and event.block_time - created_block_time >= PURGE_MIN_AGE_S
                and peak_quote >= PURGE_MIN_PEAK_REAL_QUOTE
                and event.real_base_before * PURGE_BASE_RATIO[1] <= PURGE_BASE_RATIO[0] * peak_base):
            return k
        peak_quote, peak_base = max(peak_quote, event.real_quote_after), max(peak_base, event.real_base_after)
    return None


def creator_not_signer(facts):
    """True / False from the creation transaction alone; None when no creator can be read."""
    if not facts.get('creator'):
        return None
    return NOT_SIGNER in str(facts.get('signed_creator_reason', '')).split(';')


def creation_payer(archive, facts):
    first = archive.transactions[facts['creation_signature']]['transaction']['message']['accountKeys'][0]
    return first['pubkey'] if isinstance(first, dict) else first


def triggers(events, facts, pool):
    """{hypothesis id or PLACEBO: decision index or None}; reads the history up to each returned event only."""
    labels = {}
    for k, items in decision_points(events, facts['creation_block_time'], pool):
        for kind, level in items:
            labels.setdefault(f'{kind}:{level}', k)
    out = {PLACEBO: labels.get(PLACEBO_CELL)}
    for hypothesis in HYPOTHESES:
        if 'label' in hypothesis:
            out[hypothesis['id']] = labels.get('%s:%d' % tuple(hypothesis['label']))
    out['HW1-1'] = dip_trigger(events) if events else None
    out['HW1-2'] = purge_trigger(events, facts['creation_block_time']) if events else None
    return out


def pool_rows(archive, entry, segment, params, cutoff_slot, evaluation=None):
    """Positions of one pool (one per hypothesis at most) and the reasons why some are missing."""
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded:
        return [], {'pool_not_replayable': 1}
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    events = timeline.events
    if not events:
        return [], {'pool_without_trade': 1}
    actors, _stats = actors_from_archive(archive, events)
    model = params.execution_model()
    unsigned = creator_not_signer(facts)
    rows, missing, probes = [], {}, {}

    def miss(key, reason):
        missing[f'{key}:{reason}'] = missing.get(f'{key}:{reason}', 0) + 1

    for key, k in triggers(events, facts, archive.pool).items():
        if key == 'HW1-5' and unsigned is None:
            miss(key, 'creator_unreadable')
            continue
        if key == 'HW1-5' and unsigned is False:
            continue                                         # a signed creation is simply not in this hypothesis
        if k is None:
            continue
        slot = events[k].slot
        if evaluation is not None and not evaluation[0] <= slot < evaluation[1]:
            miss(key, 'outside_evaluation_range')
            continue
        if cutoff_slot is not None and slot > cutoff_slot:
            miss(key, 'exit_would_leave_the_window')
            continue
        if k not in probes:
            probes[k] = probe(timeline, k, actors, model)
        position = probes[k]
        if not position['entered']:
            miss(key, 'buy_refused')
            continue
        if evaluation is not None and not evaluation[0] <= position['entry_slot'] < evaluation[1]:
            miss(key, 'landing_outside_evaluation_range')
            continue
        rows.append(dict(position, hypothesis=key, pool=archive.pool, creator=cluster_key(archive, facts),
                         payer=creation_payer(archive, facts), creator_signed=bool(facts['signed_creator_verified']),
                         creator_not_signer=unsigned, segment=segment, decision_slot=slot))
    return rows, missing


def _document(rows, missing, pools, *, source, latency_slots, extra):
    document = dict(schema=SCHEMA, status='EXPLORATORY', hypotheses=[dict(h) for h in HYPOTHESES],
                    hypotheses_sha256=fingerprint(), latency_slots=latency_slots, source=source, pools_read=pools,
                    missing=dict(sorted(missing.items())), counts=counts(rows), rows=rows,
                    flags=dict(holdout_read=False, promotion_allowed=False, financial_order_submitted=False), **extra)
    document['rows_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return document


def run_p0(pack_dir, expect_manifest_sha256, *, segments=DISCOVERY_SEGMENTS, confirm_validation=None,
           latency_slots=plan.REPLAY['latency_slots']):
    segments = tuple(segments)
    if set(segments) - set(plan.SEGMENTS):
        raise ValueError('unknown_segment')
    if 'validation' in segments and confirm_validation != 'HW1':
        raise ValueError('validation_is_read_once_for_the_frozen_family_HW1')
    params = hrr.ReplayParams(latency_slots=latency_slots)
    pack = Pack(pack_dir, expect_manifest_sha256)
    rows, missing, pools = [], {}, 0
    for entry, archive, segment in pack.pools():
        if segment not in segments:
            continue
        pools += 1
        found, reasons = pool_rows(archive, entry, segment, params, window_cutoff(entry, pack.manifest, params))
        rows.extend(found)
        for key, count in reasons.items():
            missing[key] = missing.get(key, 0) + count
    return _document(rows, missing, pools, source='p0_visible', latency_slots=latency_slots,
                     extra=dict(pack_manifest_sha256=pack.manifest_sha256, segments=list(segments),
                                confirm_validation=confirm_validation, w1_data_read=False))


def run_export(directory, expect_manifest_sha256, *, evaluation=None, official_verdict_sha256=None,
               latency_slots=plan.REPLAY['latency_slots']):
    """Positions from a pool export (the format of P0 and of W1). A window reaching W1 needs the anchored verdict."""
    manifest_sha256, _digests, pools, manifest = hrr.load_fixtures(directory)
    if type(expect_manifest_sha256) is not str or manifest_sha256 != expect_manifest_sha256:
        raise ValueError('export_manifest_sha256_is_not_the_expected_one')
    end = manifest.get('window_slot_max')
    reaches_w1 = (type(end) is int and end >= plan.S0_W1) or any(
        tx.get('slot', 0) >= plan.S0_W1 for _entry, archive in pools for tx in archive.transactions.values())
    if reaches_w1:
        if (type(official_verdict_sha256) is not str or len(official_verdict_sha256) != 64
                or any(c not in '0123456789abcdef' for c in official_verdict_sha256)):
            raise ValueError('w1_data_need_the_sha256_of_the_anchored_official_verdict')
        if evaluation is None:
            raise ValueError('w1_data_need_the_evaluation_range')
    if evaluation is not None and not (type(evaluation[0]) is int and type(evaluation[1]) is int
                                       and evaluation[0] < evaluation[1]):
        raise ValueError('invalid_evaluation_range')
    params = hrr.ReplayParams(latency_slots=latency_slots)
    rows, missing = [], {}
    for entry, archive in pools:
        found, reasons = pool_rows(archive, entry, 'export', params, window_cutoff(entry, manifest, params), evaluation)
        rows.extend(found)
        for key, count in reasons.items():
            missing[key] = missing.get(key, 0) + count
    return _document(rows, missing, len(pools), source='export', latency_slots=latency_slots,
                     extra=dict(pack_manifest_sha256=manifest_sha256, segments=['export'],
                                evaluation=list(evaluation) if evaluation else None,
                                official_verdict_sha256=official_verdict_sha256, w1_data_read=bool(reaches_w1),
                                skipped_by_the_export=len(manifest.get('skipped') or {})))


def counts(rows):
    """Sample sizes per hypothesis: nothing here is a value (the migrated share is a coverage count)."""
    out = {}
    for hypothesis in HYPOTHESES + (dict(id=PLACEBO, horizon=None),):
        items = [r for r in rows if r['hypothesis'] == hypothesis['id']]
        block = dict(positions=len(items), clusters=len({r['creator'] for r in items}),
                     distinct_payers=len({r['payer'] for r in items}))
        if hypothesis['horizon'] is not None:
            migrated = sum(r['horizons'][str(hypothesis['horizon'])]['migrated'] for r in items)
            block.update(migrated=migrated, migrated_share=migrated / len(items) if items else None,
                         evaluable=bool(len(items) >= MIN_POSITIONS and block['clusters'] >= MIN_CLUSTERS
                                        and migrated <= MAX_MIGRATED_SHARE * len(items)))
        out[hypothesis['id']] = block
    out['m'] = sum(block.get('evaluable', False) for block in out.values())
    return out


def fingerprint():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ('hypotheses.py', 'points.py', 'study.py', 'table.py'):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes())
    return digest.hexdigest()


def _boot(values, groups, n_boot):
    if not values or not n_boot:
        return None, None
    means = cluster_bootstrap_means(values, groups, n_boot=n_boot, seed=SEED)
    return _interval(means, 0.05), (sum(m <= 0 for m in means) + 1) / (n_boot + 1)


def _mean(values):
    return statistics.fmean(values) if values else None


def robustness(items, returns, rents, latency10_rows):
    """Mandatory conditions of the exploratory hypothesis (R02 d70251db), each True / False / None (not computable)."""
    n = len(returns)
    order = sorted(range(n), key=lambda i: returns[i])
    cut = n * 5 // 100
    trimmed = [returns[i] for i in order[cut:n - cut]]
    without_top5 = [returns[i] for i in order[:max(0, n - 5)]]
    by_cluster = {}
    for row, value in zip(items, returns):
        by_cluster.setdefault(row['creator'], []).append(value)
    largest = max(by_cluster, key=lambda key: (len(by_cluster[key]), key)) if by_cluster else None
    without_cluster = [v for row, v in zip(items, returns) if row['creator'] != largest]
    chronological = [v for _slot, _pool, v in sorted((row['decision_slot'], row['pool'], v) for row, v in zip(items, returns))]
    third = n // 3
    thirds = [chronological[:third], chronological[third:n - third], chronological[n - third:]] if third else []
    gains = [v for v in returns if v > 0]
    at25 = [probe_return(row, '25', rents) for row in items]
    slow = None
    if latency10_rows is not None:
        slow = _mean([probe_return(row, '10', rents) for row in latency10_rows if row['hypothesis'] == 'HW1-5'])
    values = dict(
        mean_at_25s=_mean(at25), trimmed_mean_5pct=_mean(trimmed), mean_without_5_best_pools=_mean(without_top5),
        mean_without_largest_cluster=_mean(without_cluster), largest_cluster_positions=len(by_cluster.get(largest, [])),
        thirds_means=[_mean(part) for part in thirds],
        largest_pool_share_of_gains=(max(gains) / sum(gains)) if gains else None,
        median=statistics.median(returns) if returns else None, mean_at_latency_10_slots=slow)
    positive = lambda value: None if value is None else value > 0                 # noqa: E731
    conditions = dict(
        i_mean_at_25s_positive=positive(values['mean_at_25s']),
        ii_trimmed_mean_positive=positive(values['trimmed_mean_5pct']),
        iii_positive_without_5_best_pools=positive(values['mean_without_5_best_pools']),
        iii_positive_without_largest_cluster=positive(values['mean_without_largest_cluster']),
        iv_two_thirds_of_three_positive=(sum(m > 0 for m in values['thirds_means']) >= 2) if thirds else None,
        v_no_pool_above_25pct_of_gains=None if values['largest_pool_share_of_gains'] is None
        else values['largest_pool_share_of_gains'] <= 0.25,
        vi_positive_at_latency_10_slots=positive(slow))
    return values, conditions


def verdicts(document, census=None, *, declared_m, latency10=None, n_boot=N_BOOT):
    if document.get('schema') != SCHEMA:
        raise ValueError('not_a_hypothesis_rows_document')
    if latency10 is not None and (latency10.get('schema') != SCHEMA or latency10.get('latency_slots') != 10
                                  or latency10.get('pack_manifest_sha256') != document['pack_manifest_sha256']):
        raise ValueError('latency10_rows_are_not_the_10_slot_run_of_the_same_data')
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    sizes = counts(document['rows'])
    if type(declared_m) is not int or declared_m != sizes['m']:
        raise ValueError('declared_m_is_not_the_number_of_evaluable_hypotheses:%d' % sizes['m'])
    placebo = {r['pool']: r for r in document['rows'] if r['hypothesis'] == PLACEBO}
    out, family = {}, []
    for hypothesis in HYPOTHESES:
        key, horizon = hypothesis['id'], str(hypothesis['horizon'])
        items = [r for r in document['rows'] if r['hypothesis'] == key]
        block = dict(name=hypothesis['name'], horizon_s=hypothesis['horizon'], exploratory_from_p0=bool(hypothesis.get('exploratory')),
                     **sizes[key])
        out[key] = block
        if not block['evaluable']:
            block['verdict'] = 'NON ÉVALUABLE'
            continue
        returns = [probe_return(r, horizon, rents) for r in items]
        if any(v is None for v in returns):
            raise ValueError('token_class_unknown_for_a_position')
        groups = [r['creator'] for r in items]
        interval, p = _boot(returns, groups, n_boot)
        pairs = [(a, placebo[a['pool']]) for a in items if a['pool'] in placebo]
        diffs = [probe_return(a, horizon, rents) - probe_return(b, horizon, rents) for a, b in pairs]
        diff_interval, _p = _boot(diffs, [a['creator'] for a, _b in pairs], n_boot)
        wins, losses = [v for v in returns if v > 0], [v for v in returns if v <= 0]
        closed = block['positions'] - block['migrated']
        block.update(mean_r=_mean(returns), mean_r_ci95=interval, p_one_sided=p, median_r=statistics.median(returns),
                     win_rate=len(wins) / len(returns), mean_gain=_mean(wins), mean_loss=_mean(losses),
                     vs_placebo=dict(pairs=len(pairs), mean=_mean(diffs), ci95=diff_interval),
                     r1_met=bool(closed >= R1_CLOSED and block['clusters'] >= R1_CREATORS))
        family.append(key)
        if hypothesis.get('exploratory'):
            latency10_rows = None if latency10 is None else latency10['rows']
            block['robustness'], block['conditions'] = robustness(items, returns, rents, latency10_rows)
            payer_interval, _p = _boot(returns, [r['payer'] for r in items], n_boot)
            block['payer_cluster_sensitivity'] = dict(
                distinct_payers=block['distinct_payers'], evaluable=block['distinct_payers'] >= MIN_PAYERS,
                mean_r_ci95=payer_interval)
    adjusted = holm([out[key]['p_one_sided'] for key in family])
    for key, p in zip(family, adjusted):
        block = out[key]
        block['p_holm'] = p
        low = (block['mean_r_ci95'] or [None])[0]
        block['primary_passed'] = bool(low is not None and low > 0 and p is not None and p < 0.05)
        if not block['primary_passed']:
            block['verdict'] = 'REJETÉE'
        elif block['exploratory_from_p0']:
            sensitivity = block['payer_cluster_sensitivity']
            contradicted = sensitivity['evaluable'] and (sensitivity['mean_r_ci95'] or [0])[0] <= 0
            if contradicted:
                block['verdict'] = 'NON CONCLUANT'
            elif all(value is True for value in block['conditions'].values()):
                block['verdict'] = 'CRITÈRE PRINCIPAL ET CONDITIONS ATTEINTS — CRITÈRES V1 À APPLIQUER'
            else:
                block['verdict'] = 'EXPLORATOIRE NON CONFIRMÉE'
        else:
            block['verdict'] = 'CRITÈRE PRINCIPAL ATTEINT — CRITÈRES V1 À APPLIQUER'
    return dict(schema='statelab-hypothesis-verdicts-v1', status='EXPLORATORY', rows_sha256=document['rows_sha256'],
                pack_manifest_sha256=document['pack_manifest_sha256'], source=document['source'],
                segments=document['segments'], w1_data_read=document['w1_data_read'],
                hypotheses_sha256=document['hypotheses_sha256'], m=sizes['m'], holm_family=family,
                trials_added_to_n=len(HYPOTHESES), rent_basis='token class of the census' if rents is not None
                else 'ASSUMED: SPL Token rent for every pool', hypotheses=out,
                notes=['rules, horizons, criteria and verdict words frozen before any value was read',
                       'the word "rentable" needs the economic criteria v1 of RUGGER 02 (R-1, R-2, P-1 to P-6), not computed here',
                       'r includes every cost and the rent lost by today\'s chain; a migrated position counts -1',
                       'HW1-5 is exploratory, born from P0: success unlikely'])


def _pct(value, digits=2):
    return '—' if value is None else f'{100 * value:.{digits}f} %'


def markdown(document):
    lines = ['> ' + note for note in document['notes']] + [
        f"> source {document['source']} ; famille de Holm : {', '.join(document['holm_family']) or 'vide'} (m = {document['m']}) ; "
        f"loyer : {document['rent_basis']}", '',
        '| Hypothèse | Sortie (s) | Positions | Grappes | Migrées | Rendement net moyen | IC 95 % | p (Holm) | Médiane '
        '| Part de gagnants | Gain moyen | Perte moyenne | Écart au placebo | R-1 | Verdict |', '|' + '---|' * 15]
    for key, b in document['hypotheses'].items():
        ci, d = b.get('mean_r_ci95'), b.get('vs_placebo') or {}
        lines.append(
            f"| {key} {b['name']} | {b['horizon_s']} | {b['positions']} | {b['clusters']} | {b['migrated']} | {_pct(b.get('mean_r'))} | "
            f"{'—' if ci is None else f'[{100 * ci[0]:.2f} ; {100 * ci[1]:.2f}]'} | "
            f"{'—' if b.get('p_holm') is None else '%.4f' % b['p_holm']} | {_pct(b.get('median_r'))} | "
            f"{_pct(b.get('win_rate'), 1)} | {_pct(b.get('mean_gain'))} | {_pct(b.get('mean_loss'))} | {_pct(d.get('mean'))} | "
            f"{'—' if 'r1_met' not in b else ('oui' if b['r1_met'] else 'non')} | {b['verdict']} |")
    block = document['hypotheses'].get('HW1-5', {})
    if 'conditions' in block:
        lines += ['', '| Condition obligatoire de HW1-5 | Valeur | Remplie |', '|---|---|---|']
        v, c = block['robustness'], block['conditions']
        mark = lambda value: '—' if value is None else ('oui' if value else 'NON')      # noqa: E731
        lines += [
            f"| (i) moyenne à 25 s > 0 | {_pct(v['mean_at_25s'])} | {mark(c['i_mean_at_25s_positive'])} |",
            f"| (ii) moyenne tronquée à 5 % > 0 | {_pct(v['trimmed_mean_5pct'])} | {mark(c['ii_trimmed_mean_positive'])} |",
            f"| (iii) sans les 5 meilleurs pools > 0 | {_pct(v['mean_without_5_best_pools'])} | {mark(c['iii_positive_without_5_best_pools'])} |",
            f"| (iii) sans la plus grosse grappe > 0 | {_pct(v['mean_without_largest_cluster'])} | {mark(c['iii_positive_without_largest_cluster'])} |",
            f"| (iv) deux tiers chronologiques sur trois positifs | {' / '.join(_pct(m) for m in v['thirds_means'])} | {mark(c['iv_two_thirds_of_three_positive'])} |",
            f"| (v) aucun pool > 25 % des gains | {_pct(v['largest_pool_share_of_gains'], 1)} | {mark(c['v_no_pool_above_25pct_of_gains'])} |",
            f"| (vi) moyenne > 0 à 10 slots de latence | {_pct(v['mean_at_latency_10_slots'])} | {mark(c['vi_positive_at_latency_10_slots'])} |",
            f"| (vii) médiane (publiée) | {_pct(v['median'])} | — |"]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='pre-registered W1 hypotheses: positions, counts, verdicts')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('p0')
    p.add_argument('pack', type=Path)
    p.add_argument('--confirm-validation')
    e = sub.add_parser('export')
    e.add_argument('directory', type=Path)
    e.add_argument('--evaluation-min', type=int)
    e.add_argument('--evaluation-max', type=int)
    e.add_argument('--official-verdict-sha256')
    for item in (p, e):
        item.add_argument('--expect-manifest-sha', required=True)
        item.add_argument('--out', type=Path, required=True)
        item.add_argument('--latency-slots', type=int, default=plan.REPLAY['latency_slots'])
    v = sub.add_parser('verdicts')
    v.add_argument('rows', type=Path)
    v.add_argument('--declared-m', type=int, required=True)
    v.add_argument('--census', type=Path)
    v.add_argument('--latency10', type=Path)
    v.add_argument('--markdown', type=Path)
    a = parser.parse_args(argv)
    if a.command == 'verdicts':
        raw = a.rows.read_bytes()
        census = json.loads(a.census.read_bytes()) if a.census else None
        slow = json.loads(a.latency10.read_bytes()) if a.latency10 else None
        document = verdicts(json.loads(raw), census, declared_m=a.declared_m, latency10=slow)
        document['rows_file_sha256'] = hashlib.sha256(raw).hexdigest()
        if a.markdown:
            a.markdown.write_text(markdown(document), encoding='utf-8')
        print(json.dumps(document, indent=1, sort_keys=True, allow_nan=False))
        return 0
    if a.out.exists():
        raise SystemExit('output_exists')
    if a.command == 'p0':
        segments = ('validation',) if a.confirm_validation else DISCOVERY_SEGMENTS
        document = run_p0(a.pack, a.expect_manifest_sha, segments=segments, confirm_validation=a.confirm_validation,
                          latency_slots=a.latency_slots)
    else:
        evaluation = None if a.evaluation_min is None and a.evaluation_max is None else (a.evaluation_min, a.evaluation_max)
        document = run_export(a.directory, a.expect_manifest_sha, evaluation=evaluation,
                              official_verdict_sha256=a.official_verdict_sha256, latency_slots=a.latency_slots)
    a.out.write_text(json.dumps(document, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    # Sample sizes only: no value is shown at run time.
    print(json.dumps(dict(pools_read=document['pools_read'], counts=document['counts'], missing=document['missing'],
                          rows_sha256=document['rows_sha256'], hypotheses_sha256=document['hypotheses_sha256']),
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
