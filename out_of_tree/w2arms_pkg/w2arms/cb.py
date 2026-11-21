"""w2arms.cb 0.2 (0.1 + condition 5 of R02, dossier B v1.9) -- the W2 verdict of the arm C-B (one frozen HW1 hypothesis, chosen after the single HW1 reading by the
rule of dossier A section 11), section 5 of dossier B v1.8. The POSITIONS are those of the frozen
``statelab.hypotheses export`` (fingerprint 1e5fb31a, unchanged), one document per W2 window; nothing is replayed here.

  python -B -m w2arms.cb creation-slots --pools <export of ONE W2 window> --manifest-sha256 <anchored> --s0 <s0> --out <DIR>
  python -B -m w2arms.cb verdict --hypothesis HW1-5 --rows <statelab rows_1.json> ... --rows-sha256 <sha_1> ... \
         --creation-slots <slots_1.json> ... --creation-slots-sha256 <sha_1> ... --freeze-anchor-sha256 <sha> \
         [--latency10 <rows_lat10_1.json> ... --latency10-sha256 ...] [--census <census.json>] --out <NEW DIR>

* candidate = the rows of the chosen hypothesis; exit = its frozen horizon (statelab.hypotheses.HYPOTHESES);
* PAIRED PLACEBO = the frozen statelab rule: the PLACEBO row of the SAME pool (label placebo:0), valued at the SAME
  horizon (``statelab.table._paired``), the difference bootstrapped by creator cluster;
* FROZEN MODE of C-B (dossier B section 4): rent LOST; denominator = the STAKE; migrated (or no value at the horizon)
  = (- cost - rent) / stake; the rent is the frozen ``statelab.table._rent`` (token class of the census, SPL by
  default); the closed-account mode (closedacct 0.2) is published apart;
* conditions and decision: those of ``w2arms.ce.verdict`` (alpha 0.05 / 3 one-sided, 10 000 draws, seed = first 8 hex
  digits of the freeze anchor, halves by CREATION slot at EVAL_MIN_1 + k x 1 612 800 / 2, cost identity in lamports,
  INCONCLUSIVE if n < 414, DESCRIPTIVE never applies to C-B (no low-tier rule));
* CONDITION 5 (R02, dossier B v1.9): if the hypothesis is HW1-5, mean net > 0 at 10 slots (the --latency10 rows of the
  same windows, required) AND mean net > 0 without the 5 best pools; PASS for any other hypothesis;
* ``creation-slots``: the creation slot of each pool of a window, read from the export (no value, no return), anchored
  by R02 like the rows; the halves need it because the frozen rows carry the decision slot only.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bot.p4 import historical_research_replay as hrr
from closedacct import model as CA
from statelab import hypotheses as H
from statelab.study import STAKE_LAMPORTS
from statelab.table import _rent
from w1aux.lazy import clear_cache, load_fixtures_lazy
from w2arms import ce as W

SCHEMA_SLOTS, SCHEMA_VERDICT = 'w2arms-cb-creation-slots-v1', 'w2arms-cb-verdict-v1'
FROZEN_HYPOTHESES_SHA256 = '1e5fb31a8b8f1870204ba27ec413f893cc358557fa36a0dbfd4194b9385e3798'


class CbError(RuntimeError):
    pass


def creation_slots(pools_dir, manifest_sha256, s0):
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise CbError('manifest_is_not_the_anchored_one')
    low, high = W.evaluation_range(s0)
    slots = {}
    try:
        for _entry, archive in entries:
            slot = hrr.creation_facts(archive)['creation_slot']
            if low <= slot < high:
                slots[archive.pool] = slot
    finally:
        clear_cache()
    return dict(schema=SCHEMA_SLOTS, s0=s0, evaluation=[low, high], input=dict(manifest_sha256=manifest_sha256),
                slots=dict(sorted(slots.items())))


def _horizon(hypothesis):
    for h in H.HYPOTHESES:
        if h['id'] == hypothesis:
            return str(h['horizon'])
    raise CbError('unknown_hypothesis')


def outcome_of(row, horizon):
    """The probe row at the horizon, as a run_rule-like outcome (received, cost, tokens, migrated)."""
    cell = row['horizons'][horizon]
    migrated = bool(cell['migrated'] or cell['value'] is None)
    return dict(migrated=migrated, value=None if migrated else cell['value'], cost=row['cost'],
                tokens=None if migrated else row['tokens'], reason=None)


def net(row, horizon, rents, mode='open'):
    rent = _rent(row, rents)
    if rent is None:
        raise CbError('token_class_unknown_for_a_position')
    o = outcome_of(row, horizon)
    if mode == 'closed':
        return CA.net_return_closed(o, rent=rent)
    return CA.net_return_open(o, rent=rent)


def decomposition_lamports(row, horizon, rents):
    o = outcome_of(row, horizon)
    rent = _rent(row, rents)
    buy, sell = W.curve_fees(o, row['fee_rate_ppm'])
    received = 0 if o['migrated'] else o['value']
    gross = received + buy + sell - STAKE_LAMPORTS
    tx = o['cost'] - STAKE_LAMPORTS
    return gross, buy + sell, tx, rent, received - o['cost'] - rent


def verdict(hypothesis, docs, slot_docs, *, freeze_anchor_sha256, latency10_docs=None, census=None, n_min=W.N_MIN):
    horizon = _horizon(hypothesis)
    if (type(freeze_anchor_sha256) is not str or len(freeze_anchor_sha256) != 64
            or any(c not in '0123456789abcdef' for c in freeze_anchor_sha256)):
        raise CbError('freeze_anchor_sha256_required')
    if not docs or len(slot_docs) != len(docs):
        raise CbError('one_creation_slots_file_per_rows_file')
    for i, (doc, slots) in enumerate(zip(docs, slot_docs)):
        if doc.get('schema') != H.SCHEMA or doc.get('hypotheses_sha256') != FROZEN_HYPOTHESES_SHA256:
            raise CbError('rows_not_from_the_frozen_hypotheses')
        if doc.get('latency_slots') != 4 or doc.get('source') != 'export':
            raise CbError('rows_not_the_4_slot_export_run')
        if slots.get('schema') != SCHEMA_SLOTS or list(doc['evaluation']) != list(slots['evaluation']):
            raise CbError('creation_slots_of_another_window')
        if list(doc['evaluation']) != list(W.evaluation_range(slots['s0'])) \
                or slots['s0'] != slot_docs[0]['s0'] + i * W.WINDOW_SLOTS:
            raise CbError('windows_not_consecutive')
    rents = None
    if census is not None:
        from v3lab.scenarios import classes
        rents = classes(census)
    created = {}
    for slots in slot_docs:
        for pool, slot in slots['slots'].items():
            if pool in created:
                raise CbError('a_pool_in_two_windows')
            created[pool] = slot
    cand = [r for d in docs for r in d['rows'] if r['hypothesis'] == hypothesis]
    placebo = {r['pool']: r for d in docs for r in d['rows'] if r['hypothesis'] == H.PLACEBO}
    if any(r['pool'] not in created for r in cand):
        raise CbError('a_position_without_creation_slot')
    groups = {}
    for r in cand:
        groups.setdefault(r['creator'], []).append(r)
    seed = int(freeze_anchor_sha256[:8], 16)
    middle = slot_docs[0]['evaluation'][0] + len(docs) * W.WINDOW_SLOTS // 2

    def mean_c(rows_):
        return W._mean([net(r, horizon, rents) for r in rows_])

    def diff(rows_):
        pairs = [(r, placebo[r['pool']]) for r in rows_ if r['pool'] in placebo]
        return W._mean([net(a, horizon, rents) - net(b, horizon, rents) for a, b in pairs])
    n = len(cand)
    low_mean = W.lower_bound(groups, mean_c, seed=seed)
    low_diff = W.lower_bound(groups, diff, seed=seed)
    halves = [W._mean([net(r, horizon, rents) for r in cand if created[r['pool']] < middle]),
              W._mean([net(r, horizon, rents) for r in cand if created[r['pool']] >= middle])]
    residuals = []
    for r in cand:
        gross, curve, tx, rent, net_l = decomposition_lamports(r, horizon, rents)
        residuals.append(gross - curve - tx - rent - net_l)
        if abs(net_l / STAKE_LAMPORTS - net(r, horizon, rents)) > 1e-12:
            raise CbError('net_differs_from_closedacct')
    conditions = dict(c1_profitability=low_mean is not None and low_mean > 0,
                      c2_superiority_to_paired_placebo=low_diff is not None and low_diff > 0,
                      c3_both_halves_positive=all(h is not None and h > 0 for h in halves),
                      c4_cost_identity_zero_residual=bool(cand) and all(x == 0 for x in residuals),
                      c5_section_3=None)                    # set below, once the 10-slot rows are read
    parts = [decomposition_lamports(r, horizon, rents) for r in cand]
    share = (lambda i: W._mean([p[i] / STAKE_LAMPORTS for p in parts]))
    slow = None
    if hypothesis == 'HW1-5' and latency10_docs is None:
        raise CbError('hw1_5_needs_the_latency10_rows')
    if latency10_docs is not None:
        if len(latency10_docs) != len(docs) or any(
                d.get('latency_slots') != 10 or list(d.get('evaluation', [])) != list(x['evaluation'])
                or d.get('hypotheses_sha256') != FROZEN_HYPOTHESES_SHA256 for d, x in zip(latency10_docs, docs)):
            raise CbError('latency10_rows_are_not_the_10_slot_run_of_the_same_windows')
        rows10 = [r for d in latency10_docs for r in d['rows'] if r['hypothesis'] == hypothesis]
        slow = W._mean([net(r, horizon, rents) for r in rows10])
    nets = [net(r, horizon, rents) for r in cand]
    without_best5 = W._mean(sorted(nets)[:-5]) if len(nets) > 5 else None
    if hypothesis == 'HW1-5':
        c5 = slow is not None and slow > 0 and without_best5 is not None and without_best5 > 0
    else:
        c5 = True
    conditions['c5_section_3'] = c5
    if n < n_min:
        decision = 'INCONCLUSIVE'
    elif all(conditions.values()):
        decision = 'GO'
    else:
        decision = 'NO-GO'
    return dict(schema=SCHEMA_VERDICT, candidate='C-B', hypothesis=hypothesis, horizon_s=int(horizon), frozen_mode='rent_lost',
                windows=len(docs), n=n, n_min=n_min, clusters=len(groups), seed=seed, draws=W.DRAWS,
                alpha_one_sided=W.ALPHA_ONE_SIDED, mean_net_return=W._mean(nets), lower_bound_mean=low_mean,
                lower_bound_minus_paired_placebo=low_diff,
                paired_placebo=dict(pairs=sum(r['pool'] in placebo for r in cand)),
                halves=dict(cut_slot=middle, means=halves), conditions=conditions, decision=decision,
                decomposition_mean_share_of_stake=dict(gross=share(0), curve_fees=share(1), tx=share(2), rent=share(3),
                                                       net=share(4)),
                published_apart=dict(closed_account_mode=W._mean([net(r, horizon, rents, 'closed') for r in cand]),
                                     latency_10_slots=slow, without_best_5_pools=without_best5,
                                     win_rate=W._mean([v > 0 for v in nets]),
                                     min=min(nets, default=None), max=max(nets, default=None)),
                rent_basis='token class of the census' if rents is not None else 'ASSUMED: SPL Token rent for every pool',
                inputs=dict(freeze_anchor_sha256=freeze_anchor_sha256))


def _read_anchored(paths, shas, error):
    if len(paths) != len(shas):
        raise CbError('one_sha256_per_file')
    docs = []
    for path, sha in zip(paths, shas):
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise CbError(error)
        docs.append(json.loads(raw))
    return docs


def main(argv=None):
    parser = argparse.ArgumentParser(prog='w2arms.cb')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('creation-slots')
    s.add_argument('--pools', type=Path, required=True)
    s.add_argument('--manifest-sha256', required=True)
    s.add_argument('--s0', type=int, required=True)
    v = sub.add_parser('verdict')
    v.add_argument('--hypothesis', required=True, choices=[h['id'] for h in H.HYPOTHESES])
    v.add_argument('--rows', type=Path, nargs='+', required=True)
    v.add_argument('--rows-sha256', nargs='+', required=True)
    v.add_argument('--creation-slots', type=Path, nargs='+', required=True)
    v.add_argument('--creation-slots-sha256', nargs='+', required=True)
    v.add_argument('--latency10', type=Path, nargs='+')
    v.add_argument('--latency10-sha256', nargs='+')
    v.add_argument('--census', type=Path)
    v.add_argument('--freeze-anchor-sha256', required=True)
    for p in (s, v):
        p.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise CbError('output_exists')
    if a.command == 'creation-slots':
        doc = creation_slots(a.pools, a.manifest_sha256, a.s0)
        sha = W._write(a.out, 'W2_CB_CREATION_SLOTS.json', doc)
        print(json.dumps(dict(pools=len(doc['slots']), sha256=sha, s0=a.s0), sort_keys=True))
        return 0
    docs = _read_anchored(a.rows, a.rows_sha256, 'rows_are_not_the_anchored_ones')
    slots = _read_anchored(a.creation_slots, a.creation_slots_sha256, 'creation_slots_are_not_the_anchored_ones')
    slow = None
    if a.latency10 is not None:
        slow = _read_anchored(a.latency10, a.latency10_sha256 or [], 'latency10_rows_are_not_the_anchored_ones')
    census = json.loads(a.census.read_bytes()) if a.census else None
    doc = verdict(a.hypothesis, docs, slots, freeze_anchor_sha256=a.freeze_anchor_sha256, latency10_docs=slow,
                  census=census)
    doc['rows_sha256'], doc['creation_slots_sha256'] = list(a.rows_sha256), list(a.creation_slots_sha256)
    W._write(a.out, 'W2_CB_VERDICT.json', doc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
