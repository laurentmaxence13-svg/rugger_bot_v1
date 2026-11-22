import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'w1chain' / 'chain.py').read_text()
MUT = [
 ("    if n_before > TRIAL_CAP_OUTSIDE_HW1:", "    if False:", 'trial_cap_ignored'),
 ("n_with_hw1=n_before + HW1_TRIALS,", "n_with_hw1=n_before,", 'hw1_trials_not_added'),
 ("CB_ORDER = ('HW1-5', 'HW1-1', 'HW1-2', 'HW1-4', 'HW1-3')", "CB_ORDER = ('HW1-1', 'HW1-5', 'HW1-2', 'HW1-4', 'HW1-3')", 'order_changed'),
 ("CB_ORDER = ('HW1-5', 'HW1-1', 'HW1-2', 'HW1-4', 'HW1-3')", "CB_ORDER = ('HW1-5', 'HW1-1', 'HW1-2', 'HW1-3', 'HW1-4')", 'order_3_before_4'),
 ("        if positive_final and not positive_code:", "        if False:", 'r02_may_override_the_code'),
 ("        if positive_final and hypothesis == 'HW1-5':", "        if False:", 'hw1_5_conditions_skipped'),
 ("        if positive_final and chosen is None:", "        if positive_final:", 'last_positive_chosen'),
 ("    if final.get('schema') != SCHEMA_FINAL or final.get('hw1_verdicts_file_sha256') != hw1_sha256:", "    if final.get('schema') != SCHEMA_FINAL:", 'final_not_tied_to_verdicts'),
 ("    _read_anchored(official_verdict_path, official_verdict_sha256, 'official_verdict')", "    pass", 'official_verdict_unchecked'),
 ("    if list(doc.get('evaluation') or []) != list(the_plan['evaluation']):", "    if False:", 'evaluation_range_unchecked'),
 ("    if doc.get('official_verdict_sha256') != the_plan['official_verdict_sha256']:", "    if False:", 'rows_official_sha_unchecked'),
 ("    if doc.get('rows_sha256') != recomputed:", "    if False:", 'rows_sha_unchecked'),
 ("    if doc.get('pack_manifest_sha256') != the_plan['export_manifest_sha256']:", "    if False:", 'rows_manifest_unchecked'),
 ("    if doc.get('w1_data_read') is not True:", "    if False:", 'w1_flag_unchecked'),
 ("    if doc.get('counts') != H.counts(doc['rows']):", "    if False:", 'counts_unchecked'),
 ("            or W.N_MIN != DOSSIER_B['n_min']):", "            or False):", 'n_min_unchecked'),
 ("        if found[key] != value:", "        if False:", 'frozen_shas_unchecked'),
 ("    document['rows_file_sha256'] = _sha_bytes(lat4_raw)          # as the frozen CLI does", "    pass", 'not_the_cli_bytes'),
 ("latency10=lat10, n_boot=n_boot)", "latency10=None, n_boot=n_boot)", 'latency10_dropped'),
 ("    document = H.verdicts(lat4, json.loads(census_raw),", "    document = H.verdicts(lat4, None,", 'census_dropped'),
 ("    if selection['cb_hypothesis'] is None:", "    if False:", 'empty_cb_gets_commands'),
 ("    if w2_s0 < EVALUATION_W1[1] + wc.GAP_SLOTS:", "    if False:", 'w2_overlap_allowed'),
 ("        s0 = w2_s0 + i * W.WINDOW_SLOTS", "        s0 = w2_s0 + i * (W.WINDOW_SLOTS - 1)", 'windows_not_consecutive'),
 ("    return CODE_POSITIVE['exploratory' if hypothesis == 'HW1-5' else 'primary']", "    return CODE_POSITIVE['primary']", 'hw1_5_primary_word'),
 ("FINAL_POSITIVE = ('EXPLORATOIRE POSITIVE', 'CONFIRMÉE SUR W1')", "FINAL_POSITIVE = ('EXPLORATOIRE POSITIVE', 'CONFIRMÉE SUR W1', 'EXPLORATOIRE NON CONFIRMÉE')", 'unconfirmed_counts_as_positive'),
 ("    if docs[0]['pools_read'] != docs[1]['pools_read']:", "    if False:", 'lat_pools_unchecked'),
 ("        lat4 = _read_anchored(a.rows_lat4, a.rows_lat4_sha256, 'rows_lat4')", "        lat4 = Path(a.rows_lat4).read_bytes()", 'cli_rows_unanchored'),
 ("        census = _read_anchored(a.census, a.census_sha256, 'census')", "        census = Path(a.census).read_bytes()", 'cli_census_unanchored'),
 ("    if hw1.get('trials_added_to_n') != HW1_TRIALS:", "    if False:", 'select_trials_unchecked'),
 ("            if any(conditions[k] is not True for k in HW1_5_ADMISSION):", "            if any(conditions[k] is not True for k in HW1_5_CONDITIONS):", 'viii_blocking'),
 ("HW1_5_ADMISSION = ('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'payer_cluster_sensitivity_consistent')", "HW1_5_ADMISSION = ('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii')", 'payer_sensitivity_not_required'),
 ("            if sorted(conditions) != sorted(HW1_5_CONDITIONS) or any(type(v) is not bool for v in conditions.values()):", "            if sorted(conditions) != sorted(HW1_5_CONDITIONS):", 'conditions_not_boolean_allowed'),
 ("            recorded = {k: conditions[k] for k in HW1_5_RECORDED}", "            recorded = None", 'viii_not_recorded'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w1chain', work / 'w1chain')
    (work / 'w1chain' / 'chain.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'w1chain' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
