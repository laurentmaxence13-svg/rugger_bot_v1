"""w1chain 0.1 -- the offline chain  W1 official verdict -> single HW1 reading -> choice of C-B -> W2 C-B verdict
(task P2-a of docs/ops/ETAT_RUGGER_MASTER.md 62c4525). It PLANS, CHECKS and calls the FROZEN functions only; it changes
no rule, threshold, horizon, population or criterion, and it never reads a W1 or W2 value before its anchor.

  python -B -m w1chain.chain plan       --official-verdict <file> --official-verdict-sha256 <R02> \
                                        --export-manifest-sha256 <R02> --n-before <R02 register> --out <plan.json>
  python -B -m w1chain.chain check-rows --plan <plan.json> --plan-sha256 <sha> --rows-lat4 <f> --rows-lat10 <f>
  python -B -m w1chain.chain verdicts   --plan ... --plan-sha256 ... --rows-lat4 <f> --rows-lat4-sha256 <R02> \
                                        --rows-lat10 <f> --rows-lat10-sha256 <R02> --census <f> --census-sha256 <R02> \
                                        --declared-m <R02> --out <NEW DIR>
  python -B -m w1chain.chain select     --plan ... --plan-sha256 ... --hw1-verdicts <f> --hw1-verdicts-sha256 <R02> \
                                        --r02-final <f> --r02-final-sha256 <R02> --out <selection.json>
  python -B -m w1chain.chain cb-plan    --selection <f> --selection-sha256 <sha> --w2-s0 <s0 of window 1> \
                                        --windows <k> --out <cb_plan.json>

Steps (runbook HW1 v2 74a74cf, steps 1a-7, updated by v3 2df1b92; nothing changed):
* ``plan``: the official W1 verdict file must have the anchored sha256 (its bytes are hashed, never parsed); the frozen
  code is checked (statelab/hypotheses.py 81f19725, fingerprint 1e5fb31a, w2arms cb 0.2 a293d3f7 and ce a161ad49, the
  dossier B v1.9 constants); the W1 evaluation range is recomputed from S0 = 467 275 745 by the frozen
  ``w1_collection.bounds`` and must be [467 678 545 ; 469 291 345); the trial counter needs N <= 170 OUTSIDE HW1 (the
  register of R02, 168 on 22/11); the plan lists the exact commands of steps 3 and 5 and the trial count N + 5.
* ``check-rows`` (step 4, for R02): both row files are the 4- and 10-slot export runs of THIS plan (schema, frozen
  fingerprint, anchored export manifest, W1 range, official verdict sha, rows_sha256 recomputed); it prints the file
  sha256 and the frozen SAMPLE SIZES only (``document['counts']``), never a value.
* ``verdicts`` (step 5): reads the ANCHORED rows, census and m, calls the frozen ``statelab.hypotheses.verdicts``
  exactly like its CLI (same bytes, ``rows_file_sha256`` added the same way) and writes the trial count.
* ``select`` (after step 6): the C-B rule of dossier A section 3 / section 11, frozen on 20/11: the FIRST of HW1-5,
  HW1-1, HW1-2, HW1-4, HW1-3 whose single W1 verdict is "EXPLORATOIRE POSITIVE" or "CONFIRMEE SUR W1" (the FINAL words
  of R02, step 6). A final word of R02 is positive only where the frozen code gave its positive word (rule 6 of R02,
  4e03d6a6: no variant makes positive what the code does not); for HW1-5 the conditions (i) to (viii) of R02 (d70251db)
  must all hold. No such hypothesis: C-B stays EMPTY ("VIDE"), without any second pass.
* ``cb-plan``: the W2 commands of the chosen hypothesis (statelab export per window with the W1 official verdict sha,
  ``w2arms.cb creation-slots``, then ONE ``w2arms.cb verdict``); with an EMPTY C-B it writes no command. The number of
  windows k is a W2 variable of the owner (dossier B v1.9): an input here.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bot.market import w1_collection as wc
from statelab import hypotheses as H
from w2arms import cb as CB
from w2arms import ce as W

SCHEMA_PLAN, SCHEMA_TRIALS = 'w1chain-plan-v1', 'w1chain-trials-v1'
SCHEMA_FINAL, SCHEMA_SELECTION, SCHEMA_CB_PLAN = 'w1chain-hw1-final-v1', 'w1chain-cb-selection-v1', 'w1chain-cb-plan-v1'

S0_W1 = 467_275_745
EVALUATION_W1 = (467_678_545, 469_291_345)
FROZEN = dict(hypotheses_py='81f197253f8d70f0e1fb8c7ed0187a40891574c0172a7a09d2c31e0c820cab8e',
              hypotheses_fingerprint='1e5fb31a8b8f1870204ba27ec413f893cc358557fa36a0dbfd4194b9385e3798',
              w2arms_cb_py='a293d3f76a1e362015a823e09ca5fb4a9fbde38d92cdc85bc2cc699f9d9eb1b9',
              w2arms_ce_py='a161ad492d5ec86adfce9c63b38466240b32e2142f99a856cb78e48ab04b0df1')
# dossier B v1.9 (frozen): K = 3 candidates, one-sided bound at alpha = 0.05 / 3 (98.33 %), 10 000 creator-cluster
# draws, n_min = 414, paired placebo of the same pool, both halves positive, cost identity with a zero residual.
DOSSIER_B = dict(k_candidates=3, alpha_one_sided=0.05 / 3, draws=10_000, n_min=414)
CONDITIONS_C_B = ('c1_profitability', 'c2_superiority_to_paired_placebo', 'c3_both_halves_positive',
                  'c4_cost_identity_zero_residual', 'c5_section_3')
CB_ORDER = ('HW1-5', 'HW1-1', 'HW1-2', 'HW1-4', 'HW1-3')
FINAL_POSITIVE = ('EXPLORATOIRE POSITIVE', 'CONFIRMÉE SUR W1')
FINAL_WORDS = FINAL_POSITIVE + ('NÉGATIVE', 'REJETÉE', 'NON ÉVALUABLE', 'NON CONCLUANT', 'EXPLORATOIRE NON CONFIRMÉE')
CODE_POSITIVE = dict(primary='CRITÈRE PRINCIPAL ATTEINT — CRITÈRES V1 À APPLIQUER',
                     exploratory='CRITÈRE PRINCIPAL ET CONDITIONS ATTEINTS — CRITÈRES V1 À APPLIQUER')
HW1_5_CONDITIONS = ('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii')
TRIAL_CAP_OUTSIDE_HW1 = 170
HW1_TRIALS = 5


class ChainError(RuntimeError):
    pass


def _sha_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _need_sha(value, name):
    if not _is_sha(value):
        raise ChainError('%s_must_be_a_sha256' % name)


def _read_anchored(path, sha, name):
    _need_sha(sha, name)
    raw = Path(path).read_bytes()
    if _sha_bytes(raw) != sha:
        raise ChainError('%s_is_not_the_anchored_file' % name)
    return raw


def frozen_check():
    """Every frozen piece the chain relies on, recomputed; any difference stops the chain."""
    found = dict(hypotheses_py=_sha_bytes(Path(H.__file__).read_bytes()), hypotheses_fingerprint=H.fingerprint(),
                 w2arms_cb_py=_sha_bytes(Path(CB.__file__).read_bytes()),
                 w2arms_ce_py=_sha_bytes(Path(W.__file__).read_bytes()))
    for key, value in FROZEN.items():
        if found[key] != value:
            raise ChainError('frozen_code_differs:%s' % key)
    if CB.FROZEN_HYPOTHESES_SHA256 != FROZEN['hypotheses_fingerprint']:
        raise ChainError('frozen_code_differs:cb_fingerprint')
    if (W.ALPHA_ONE_SIDED != DOSSIER_B['alpha_one_sided'] or W.DRAWS != DOSSIER_B['draws']
            or W.N_MIN != DOSSIER_B['n_min']):
        raise ChainError('dossier_b_constants_differ')
    if tuple(h['id'] for h in H.HYPOTHESES) != ('HW1-1', 'HW1-2', 'HW1-3', 'HW1-4', 'HW1-5') \
            or sorted(CB_ORDER) != sorted(h['id'] for h in H.HYPOTHESES):
        raise ChainError('frozen_hypotheses_differ')
    if tuple(wc.bounds(S0_W1)['evaluation']) != EVALUATION_W1:
        raise ChainError('w1_evaluation_range_differs')
    return found


def trials(n_before):
    if type(n_before) is not int or n_before < 0:
        raise ChainError('n_before_must_be_a_non_negative_integer')
    if n_before > TRIAL_CAP_OUTSIDE_HW1:
        raise ChainError('trial_cap_exceeded:%d>%d' % (n_before, TRIAL_CAP_OUTSIDE_HW1))
    return dict(schema=SCHEMA_TRIALS, n_outside_hw1=n_before, cap_outside_hw1=TRIAL_CAP_OUTSIDE_HW1,
                hw1_reading=HW1_TRIALS, n_with_hw1=n_before + HW1_TRIALS,
                note='the HW1 reading adds +5 and is published apart; the choice of C-B adds no trial (mechanical rule)')


def _dump(doc):
    return (json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n').encode()


def _write_new(path, raw):
    path = Path(path)
    if path.exists():
        raise ChainError('output_exists')
    path.write_bytes(raw)
    return _sha_bytes(raw)


def plan(official_verdict_path, official_verdict_sha256, export_manifest_sha256, n_before):
    _read_anchored(official_verdict_path, official_verdict_sha256, 'official_verdict')
    _need_sha(export_manifest_sha256, 'export_manifest_sha256')
    frozen = frozen_check()
    low, high = EVALUATION_W1
    export = ('python -B -m statelab.hypotheses export <dayj/pools W1> --expect-manifest-sha %s --evaluation-min %d '
              '--evaluation-max %d --official-verdict-sha256 %s' % (export_manifest_sha256, low, high,
                                                                    official_verdict_sha256))
    steps = [
        dict(step='1a-1b-2', who='R03 then R02', action='census of the token classes (runbook v2, unchanged); R02 anchors '
             'pools_trace_w1.json and census_w1.json'),
        dict(step='3', who='R03', commands=[export + ' --out hw1_rows_w1_lat4.json',
                                            export + ' --latency-slots 10 --out hw1_rows_w1_lat10.json']),
        dict(step='4', who='R02', action='anchor BOTH row files first, then read the sizes with w1chain check-rows; fix '
             'and anchor m'),
        dict(step='5', who='R03', commands=['python -B -m w1chain.chain verdicts --plan <plan.json> --plan-sha256 <sha> '
                                            '--rows-lat4 hw1_rows_w1_lat4.json --rows-lat4-sha256 <R02> '
                                            '--rows-lat10 hw1_rows_w1_lat10.json --rows-lat10-sha256 <R02> '
                                            '--census census_w1.json --census-sha256 <R02> --declared-m <R02> '
                                            '--out <NEW DIR>']),
        dict(step='6', who='R02', action='independent recomputation and final verdict (rules 4e03d6a6); writes the '
             'w1chain-hw1-final-v1 document and anchors it'),
        dict(step='7', who='R01', action='report to the owner after step 6, then w1chain select and w1chain cb-plan'),
    ]
    return dict(schema=SCHEMA_PLAN, official_verdict_sha256=official_verdict_sha256,
                export_manifest_sha256=export_manifest_sha256, s0_w1=S0_W1, evaluation=[low, high], frozen=frozen,
                dossier_b=dict(DOSSIER_B), cb_order=list(CB_ORDER), trials=trials(n_before), steps=steps,
                flags=dict(data_read=False, holdout_read=False, financial_order_submitted=False))


def load_plan(path, sha):
    doc = json.loads(_read_anchored(path, sha, 'plan'))
    if doc.get('schema') != SCHEMA_PLAN:
        raise ChainError('not_a_w1chain_plan')
    frozen_check()
    trials(doc['trials']['n_outside_hw1'])
    return doc


def check_rows_document(doc, the_plan, latency_slots):
    if doc.get('schema') != H.SCHEMA or doc.get('source') != 'export':
        raise ChainError('rows_not_a_statelab_export_document')
    if doc.get('hypotheses_sha256') != FROZEN['hypotheses_fingerprint']:
        raise ChainError('rows_not_from_the_frozen_hypotheses')
    if doc.get('latency_slots') != latency_slots:
        raise ChainError('rows_not_the_%d_slot_run' % latency_slots)
    if doc.get('pack_manifest_sha256') != the_plan['export_manifest_sha256']:
        raise ChainError('rows_not_from_the_anchored_export')
    if list(doc.get('evaluation') or []) != list(the_plan['evaluation']):
        raise ChainError('rows_not_on_the_w1_evaluation_range')
    if doc.get('official_verdict_sha256') != the_plan['official_verdict_sha256']:
        raise ChainError('rows_not_after_the_anchored_official_verdict')
    if doc.get('w1_data_read') is not True:
        raise ChainError('rows_do_not_come_from_w1')
    recomputed = _sha_bytes(json.dumps(doc['rows'], sort_keys=True, separators=(',', ':')).encode())
    if doc.get('rows_sha256') != recomputed:
        raise ChainError('rows_sha256_differs')
    if doc.get('counts') != H.counts(doc['rows']):
        raise ChainError('counts_differ')
    return doc


def check_rows(the_plan, lat4_path, lat10_path):
    out = {}
    docs = []
    for name, path, slots in (('lat4', lat4_path, 4), ('lat10', lat10_path, 10)):
        raw = Path(path).read_bytes()
        doc = check_rows_document(json.loads(raw), the_plan, slots)
        docs.append(doc)
        out[name] = dict(file_sha256=_sha_bytes(raw), rows_sha256=doc['rows_sha256'], pools_read=doc['pools_read'],
                         missing=doc['missing'], counts=doc['counts'])
    if docs[0]['pools_read'] != docs[1]['pools_read']:
        raise ChainError('lat4_and_lat10_did_not_read_the_same_pools')
    return out


def hw1_verdicts(the_plan, lat4_raw, lat10_raw, census_raw, declared_m, *, n_boot=H.N_BOOT):
    lat4 = check_rows_document(json.loads(lat4_raw), the_plan, 4)
    lat10 = check_rows_document(json.loads(lat10_raw), the_plan, 10)
    document = H.verdicts(lat4, json.loads(census_raw), declared_m=declared_m, latency10=lat10, n_boot=n_boot)
    document['rows_file_sha256'] = _sha_bytes(lat4_raw)          # as the frozen CLI does
    if document['trials_added_to_n'] != HW1_TRIALS:
        raise ChainError('hw1_trials_differ')
    return document


def frozen_cli_bytes(document):
    """The exact stdout of ``python -B -m statelab.hypotheses verdicts`` (print adds the newline)."""
    return (json.dumps(document, indent=1, sort_keys=True, allow_nan=False) + '\n').encode()


def _code_positive(hypothesis):
    return CODE_POSITIVE['exploratory' if hypothesis == 'HW1-5' else 'primary']


def select(the_plan, hw1, hw1_sha256, final):
    if hw1.get('schema') != 'statelab-hypothesis-verdicts-v1' or hw1.get('source') != 'export' \
            or hw1.get('w1_data_read') is not True:
        raise ChainError('not_the_hw1_verdicts_of_w1')
    if hw1.get('hypotheses_sha256') != FROZEN['hypotheses_fingerprint'] \
            or hw1.get('pack_manifest_sha256') != the_plan['export_manifest_sha256']:
        raise ChainError('hw1_verdicts_not_from_this_plan')
    if hw1.get('trials_added_to_n') != HW1_TRIALS:
        raise ChainError('hw1_trials_differ')
    if final.get('schema') != SCHEMA_FINAL or final.get('hw1_verdicts_file_sha256') != hw1_sha256:
        raise ChainError('r02_final_is_not_about_these_hw1_verdicts')
    words = final.get('final') or {}
    if sorted(words) != sorted(CB_ORDER) or any(words[k] not in FINAL_WORDS for k in words):
        raise ChainError('r02_final_words_incomplete_or_unknown')
    reasons, chosen = {}, None
    for hypothesis in CB_ORDER:
        code = hw1['hypotheses'][hypothesis]['verdict']
        positive_final = words[hypothesis] in FINAL_POSITIVE
        positive_code = code == _code_positive(hypothesis)
        if positive_final and not positive_code:
            raise ChainError('r02_positive_where_the_frozen_code_is_not:%s' % hypothesis)
        if positive_final and hypothesis == 'HW1-5':
            conditions = final.get('hw1_5_conditions_r02') or {}
            if sorted(conditions) != sorted(HW1_5_CONDITIONS) or any(v is not True for v in conditions.values()):
                raise ChainError('hw1_5_positive_without_the_conditions_i_to_viii')
        reasons[hypothesis] = dict(code_verdict=code, r02_final=words[hypothesis], positive=positive_final)
        if positive_final and chosen is None:
            chosen = hypothesis
    horizon = None
    if chosen is not None:
        horizon = next(h['horizon'] for h in H.HYPOTHESES if h['id'] == chosen)
    return dict(schema=SCHEMA_SELECTION, rule='dossier A section 3 / 11: first positive of HW1-5, 1, 2, 4, 3; else EMPTY',
                order=list(CB_ORDER), cb_hypothesis=chosen, status='RETENUE' if chosen else 'VIDE', horizon_s=horizon,
                per_hypothesis=reasons, inputs=dict(official_verdict_sha256=the_plan['official_verdict_sha256'],
                                                    hw1_verdicts_file_sha256=hw1_sha256,
                                                    export_manifest_sha256=the_plan['export_manifest_sha256']),
                trials=the_plan['trials'], dossier_b=dict(DOSSIER_B))


def cb_plan(selection, selection_sha256, w2_s0, windows):
    if selection.get('schema') != SCHEMA_SELECTION:
        raise ChainError('not_a_cb_selection')
    frozen_check()
    if type(w2_s0) is not int or w2_s0 <= S0_W1 or type(windows) is not int or windows < 1:
        raise ChainError('invalid_w2_windows')
    if w2_s0 < EVALUATION_W1[1] + wc.GAP_SLOTS:
        raise ChainError('w2_overlaps_w1')
    base = dict(schema=SCHEMA_CB_PLAN, selection_sha256=selection_sha256, status=selection['status'],
                cb_hypothesis=selection['cb_hypothesis'], windows=windows, dossier_b=dict(DOSSIER_B),
                conditions=list(CONDITIONS_C_B))
    if selection['cb_hypothesis'] is None:
        return dict(base, commands=[], note='C-B EMPTY: no W2 command, no second pass')
    official = selection['inputs']['official_verdict_sha256']
    commands = []
    for i in range(windows):
        s0 = w2_s0 + i * W.WINDOW_SLOTS
        low, high = W.evaluation_range(s0)
        export = ('python -B -m statelab.hypotheses export <W2 pools %d> --expect-manifest-sha <R02 manifest %d> '
                  '--evaluation-min %d --evaluation-max %d --official-verdict-sha256 %s' % (i + 1, i + 1, low, high,
                                                                                            official))
        commands.append(dict(window=i + 1, s0=s0, evaluation=[low, high], commands=[
            export + ' --out cb_rows_%d.json' % (i + 1),
            export + ' --latency-slots 10 --out cb_rows_lat10_%d.json' % (i + 1),
            'python -B -m w2arms.cb creation-slots --pools <W2 pools %d> --manifest-sha256 <R02 manifest %d> '
            '--s0 %d --out cb_slots_%d' % (i + 1, i + 1, s0, i + 1)]))
    k = range(1, windows + 1)
    verdict = ('python -B -m w2arms.cb verdict --hypothesis %s --rows %s --rows-sha256 %s --creation-slots %s '
               '--creation-slots-sha256 %s --latency10 %s --latency10-sha256 %s --census <W2 census> '
               '--freeze-anchor-sha256 <R02 freeze> --out <NEW DIR>' % (
                   selection['cb_hypothesis'], ' '.join('cb_rows_%d.json' % i for i in k),
                   ' '.join('<R02 rows %d>' % i for i in k),
                   ' '.join('cb_slots_%d/W2_CB_CREATION_SLOTS.json' % i for i in k),
                   ' '.join('<R02 slots %d>' % i for i in k), ' '.join('cb_rows_lat10_%d.json' % i for i in k),
                   ' '.join('<R02 rows lat10 %d>' % i for i in k)))
    return dict(base, horizon_s=selection['horizon_s'], per_window=commands, verdict_command=verdict)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='w1chain.chain')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--official-verdict', type=Path, required=True)
    p.add_argument('--official-verdict-sha256', required=True)
    p.add_argument('--export-manifest-sha256', required=True)
    p.add_argument('--n-before', type=int, required=True)
    p.add_argument('--out', type=Path, required=True)
    c = sub.add_parser('check-rows')
    v = sub.add_parser('verdicts')
    s = sub.add_parser('select')
    for item in (c, v, s):
        item.add_argument('--plan', type=Path, required=True)
        item.add_argument('--plan-sha256', required=True)
    for item in (c, v):
        item.add_argument('--rows-lat4', type=Path, required=True)
        item.add_argument('--rows-lat10', type=Path, required=True)
    v.add_argument('--rows-lat4-sha256', required=True)
    v.add_argument('--rows-lat10-sha256', required=True)
    v.add_argument('--census', type=Path, required=True)
    v.add_argument('--census-sha256', required=True)
    v.add_argument('--declared-m', type=int, required=True)
    v.add_argument('--out', type=Path, required=True)
    s.add_argument('--hw1-verdicts', type=Path, required=True)
    s.add_argument('--hw1-verdicts-sha256', required=True)
    s.add_argument('--r02-final', type=Path, required=True)
    s.add_argument('--r02-final-sha256', required=True)
    s.add_argument('--out', type=Path, required=True)
    b = sub.add_parser('cb-plan')
    b.add_argument('--selection', type=Path, required=True)
    b.add_argument('--selection-sha256', required=True)
    b.add_argument('--w2-s0', type=int, required=True)
    b.add_argument('--windows', type=int, required=True)
    b.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    if a.command == 'plan':
        doc = plan(a.official_verdict, a.official_verdict_sha256, a.export_manifest_sha256, a.n_before)
        sha = _write_new(a.out, _dump(doc))
        print(json.dumps(dict(plan_sha256=sha, trials=doc['trials']), sort_keys=True))
        return 0
    if a.command == 'cb-plan':
        selection = json.loads(_read_anchored(a.selection, a.selection_sha256, 'selection'))
        doc = cb_plan(selection, a.selection_sha256, a.w2_s0, a.windows)
        print(json.dumps(dict(cb_plan_sha256=_write_new(a.out, _dump(doc)), status=doc['status']), sort_keys=True))
        return 0
    the_plan = load_plan(a.plan, a.plan_sha256)
    if a.command == 'check-rows':
        # Sample sizes only: no value is shown.
        print(json.dumps(check_rows(the_plan, a.rows_lat4, a.rows_lat10), sort_keys=True, indent=1))
        return 0
    if a.command == 'verdicts':
        if a.out.exists():
            raise ChainError('output_exists')
        lat4 = _read_anchored(a.rows_lat4, a.rows_lat4_sha256, 'rows_lat4')
        lat10 = _read_anchored(a.rows_lat10, a.rows_lat10_sha256, 'rows_lat10')
        census = _read_anchored(a.census, a.census_sha256, 'census')
        document = hw1_verdicts(the_plan, lat4, lat10, census, a.declared_m)
        a.out.mkdir(parents=True)
        sha = _write_new(a.out / 'HW1_VERDICTS.json', frozen_cli_bytes(document))
        (a.out / 'HW1_VERDICTS.md').write_text(H.markdown(document), encoding='utf-8')
        record = dict(the_plan['trials'], hw1_verdicts_file_sha256=sha, rows_lat4_sha256=a.rows_lat4_sha256,
                      rows_lat10_sha256=a.rows_lat10_sha256, census_sha256=a.census_sha256, declared_m=a.declared_m)
        _write_new(a.out / 'TRIALS.json', _dump(record))
        print(json.dumps(dict(hw1_verdicts_file_sha256=sha, n_with_hw1=record['n_with_hw1']), sort_keys=True))
        return 0
    hw1_raw = _read_anchored(a.hw1_verdicts, a.hw1_verdicts_sha256, 'hw1_verdicts')
    final = json.loads(_read_anchored(a.r02_final, a.r02_final_sha256, 'r02_final'))
    doc = select(the_plan, json.loads(hw1_raw), a.hw1_verdicts_sha256, final)
    doc['inputs']['r02_final_sha256'] = a.r02_final_sha256
    print(json.dumps(dict(selection_sha256=_write_new(a.out, _dump(doc)), status=doc['status'],
                          cb_hypothesis=doc['cb_hypothesis']), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
