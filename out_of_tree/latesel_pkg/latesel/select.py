"""latesel 0.1 -- ONE causal filter on a late latelab entry, threshold = a POPULATION quantile of W1 half 1 (no
return read), one trial per hypothesis on W1 half 2 (R02 note audit of 20/11 on NOTE_PISTES_TARDIVES_CPMM v0.1).

  python -B -m latesel.select quantiles --pools <W1 export> --manifest-sha256 <anchored> --out <OUT>
  python -B -m latesel.select screen    --pools <W1 export> --manifest-sha256 <anchored> \
         --quantiles <ANCHORED QUANTILES json> --quantiles-sha256 <sha> --out <OUT>

HYPOTHESES, frozen here before any latelab output (R02 condition 1; T2 withdrawn, condition 2):
  T1   entry ``age:120``, kept when unique_buyers >= the upper tercile (q = 2/3) of half 1
  T3p  entry ``age:300``, kept when top5_holder_share <= the median (q = 1/2) of half 1
EXIT, RETURN, HALVES, INTERVAL, FLOORS: those of latelab 0.4 (imported unchanged): clock 60 s, 0.1 SOL, latency 4
slots, rent lost, migrated = -1, creator-cluster bootstrap (seed 20261120, 2 000 draws), n >= 30 and >= 20 clusters.

FILTERS (R02 condition a), computed HERE from the trade events up to and including the decision event only, from
their side, fee payer and amounts (never a curve state, a reserve, a progress level, a price or a signer status):
  unique_buyers        number of distinct buyer fee payers, the creator excluded
  top5_holder_share    sum of the 5 largest positive token positions / sum of all positive positions, the creator
                       excluded; a position = tokens bought (amount_out of a buy) - tokens sold (amount_in of a sell)

QUANTILES (condition 3): over every ``age:A`` decision point of half 1 (no replay, no outcome); the output holds the
two thresholds and counts only, to be anchored by R02 BEFORE the screen. SCREEN (condition 4): both hypotheses on half
2 (N + 2); a hypothesis passes when mean > 0 with n >= 30 and >= 20 clusters; never a proof. The L slot selection among
the passing candidates (condition 5) is R02's dossier B rule, not computed here. Output: counts and returns only.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bot.market.collector import summarize
from bot.p4 import historical_research_replay as hrr
from latelab import study as LL
from statelab.exits import run_rule
from statelab.points import decision_points
from statelab.study import cluster_key
from v3lab import plan
from w1aux.lazy import clear_cache, load_fixtures_lazy

SCHEMA = 'latesel-v0.1'
HYPOTHESES = dict(
    T1=dict(age=120, feature='unique_buyers', q=2 / 3, keep='>='),
    T3p=dict(age=300, feature='top5_holder_share', q=1 / 2, keep='<='),
)


class LateSelError(RuntimeError):
    pass


def unique_buyers(history, creator):
    return len({e.fee_payer for e in history if e.side == 'buy'} - {creator})


def top5_holder_share(history, creator):
    positions = {}
    for e in history:
        if e.side == 'buy':
            positions[e.fee_payer] = positions.get(e.fee_payer, 0) + e.amount_out
        else:
            positions[e.fee_payer] = positions.get(e.fee_payer, 0) - e.amount_in
    held = sorted((amount for payer, amount in positions.items() if payer != creator and amount > 0), reverse=True)
    total = sum(held)
    return sum(held[:5]) / total if total else None


FEATURES = dict(unique_buyers=unique_buyers, top5_holder_share=top5_holder_share)


def keeps(spec, value, threshold):
    if value is None or threshold is None:
        return False
    return value >= threshold if spec['keep'] == '>=' else value <= threshold


def _timeline(archive):
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    half = LL.half_of(facts['creation_slot'])
    if half is None:
        return None
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded:
        return None
    return facts, half, timeline


def feature_points(events, facts, pool):
    """[(hypothesis, k, value)] at the hypotheses' age labels; reads events[:k + 1] only."""
    wanted = {('age', spec['age']): name for name, spec in HYPOTHESES.items()}
    out = []
    for k, labels in decision_points(events, facts['creation_block_time'], pool):
        for label in labels:
            name = wanted.get(tuple(label))
            if name is not None:
                spec = HYPOTHESES[name]
                out.append((name, k, FEATURES[spec['feature']](events[:k + 1], facts.get('creator'))))
    return out


def _pools(pools_dir, manifest_sha256):
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise LateSelError('manifest_is_not_the_anchored_one')
    return entries


def quantiles(pools_dir, manifest_sha256):
    values = {name: [] for name in HYPOTHESES}
    try:
        for _entry, archive in _pools(pools_dir, manifest_sha256):
            got = _timeline(archive)
            if got is None or got[1] != 'discovery':
                continue
            facts, _half, timeline = got
            for name, _k, value in feature_points(timeline.events, facts, archive.pool):
                if value is not None:
                    values[name].append(value)
    finally:
        clear_cache()
    return dict(half='discovery', trials_added=0, thresholds={
        name: dict(spec, n_points=len(values[name]), threshold=LL.quantile(values[name], spec['q']))
        for name, spec in HYPOTHESES.items()})


def screen(pools_dir, manifest_sha256, thresholds, params):
    from v4sim.io import actors_from_archive               # heavy, and only when a pool is kept
    items = {name: [] for name in HYPOTHESES}
    model = params.execution_model()
    try:
        for _entry, archive in _pools(pools_dir, manifest_sha256):
            got = _timeline(archive)
            if got is None or got[1] != 'screen':
                continue
            facts, _half, timeline = got
            chosen = [(name, k) for name, k, value in feature_points(timeline.events, facts, archive.pool)
                      if keeps(HYPOTHESES[name], value, thresholds[name])]
            if not chosen:
                continue
            actors, _stats = actors_from_archive(archive, timeline.events)
            cluster = cluster_key(archive, facts)
            for name, k in chosen:
                outcome = run_rule(timeline, k, actors, model, LL.RULE)
                if outcome is not None:
                    items[name].append((cluster, outcome))
    finally:
        clear_cache()
    return dict(half='screen', cells={name: verdict(items[name]) for name in HYPOTHESES}, trials_added=len(HYPOTHESES),
                pass_rule='mean > 0 with n >= 30 and >= 20 clusters; never a proof')


def verdict(items):
    out = LL.summary(items)
    out['passes'] = out['interpretable'] and out['mean_net_return'] is not None and out['mean_net_return'] > 0
    return out


def _write(out_dir, doc):
    out = Path(out_dir)
    if out.exists():
        raise LateSelError('output_exists')
    out.mkdir(parents=True)
    path = out / 'LATESEL.json'
    path.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base(params, manifest_sha256):
    return dict(schema=SCHEMA, category='EXPLORATORY_W1_DEVELOPMENT', hypotheses=HYPOTHESES, rule=LL.RULE,
                cut_slot=LL.CUT_SLOT, evaluation=[LL.EVAL_MIN, LL.EVAL_MAX], latency_slots=params.latency_slots,
                rent='lost (SPL rent of the frozen chain)', input=dict(manifest_sha256=manifest_sha256),
                firewall='filters from trade side, fee payer and amounts only; ages 120/300 s; no HW1 variable')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='latesel.select')
    parser.add_argument('mode', choices=('quantiles', 'screen'))
    parser.add_argument('--pools', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--quantiles', type=Path, default=None)
    parser.add_argument('--quantiles-sha256', default=None)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    params = hrr.ReplayParams(latency_slots=plan.REPLAY['latency_slots'])
    thresholds = None
    if a.mode == 'screen':
        if a.quantiles is None or a.quantiles_sha256 is None:
            raise LateSelError('anchored_quantiles_required')
        raw = a.quantiles.read_bytes()
        if hashlib.sha256(raw).hexdigest() != a.quantiles_sha256:
            raise LateSelError('quantiles_are_not_the_anchored_ones')
        doc = json.loads(raw)
        if doc.get('schema') != SCHEMA or doc.get('hypotheses') != json.loads(json.dumps(HYPOTHESES)):
            raise LateSelError('quantiles_of_other_hypotheses')
        thresholds = {name: doc['thresholds'][name]['threshold'] for name in HYPOTHESES}
    if a.out.exists():
        raise LateSelError('output_exists')
    body = (quantiles(a.pools, a.manifest_sha256) if a.mode == 'quantiles'
            else screen(a.pools, a.manifest_sha256, thresholds, params))
    doc = dict(_base(params, a.manifest_sha256), **body)
    if a.mode == 'screen':
        doc['input']['quantiles_sha256'] = a.quantiles_sha256
    _write(a.out, doc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
