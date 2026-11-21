import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'w2arms' / 'ce.py').read_text()
MUT = [
 ("    cand = [r for r in all_rows if r['low_tier']]", "    cand = list(all_rows)", 'tier_restriction_dropped'),
 ("        c, p = mean_c(rows_), _mean([net(r, mode) for r in rows_])", "        c, p = mean_c(rows_), _mean([net(r, mode) for r in rows_ if r['low_tier']])", 'placebo_restricted_to_low_tier'),
 ("    return values[max(0, int(alpha * len(values)) - 1)] if values else None", "    return values[max(0, int(0.05 * len(values)) - 1)] if values else None", 'alpha_not_bonferroni'),
 ("    seed = int(freeze_anchor_sha256[:8], 16)", "    seed = 20261120", 'seed_not_from_anchor'),
 ("    middle = eval_min_1 + len(docs) * WINDOW_SLOTS // 2", "    middle = eval_min_1 + WINDOW_SLOTS // 2", 'halves_cut_one_window'),
 ("def verdict(docs, *, freeze_anchor_sha256, section_6_4_fired, section_3_pass, mode='closed', n_min=N_MIN):", "def verdict(docs, *, freeze_anchor_sha256, section_6_4_fired, section_3_pass, mode='open', n_min=N_MIN):", 'frozen_mode_open'),
 ("    elif n < n_min:\n        decision = 'INCONCLUSIVE'", "    elif False:\n        decision = 'INCONCLUSIVE'", 'n_min_ignored'),
 ("    if section_6_4_fired:\n        decision = 'DESCRIPTIVE'", "    if False:\n        decision = 'DESCRIPTIVE'", 'rule_6_4_ignored'),
 ("        if doc['s0'] != base['s0'] + i * WINDOW_SLOTS:", "        if False:", 'windows_not_checked'),
 ("    if len(pools) != len(set(pools)):", "    if False:", 'duplicates_allowed'),
 ("        if hashlib.sha256(raw).hexdigest() != sha:", "        if False:", 'rows_sha_ignored'),
 ("    rent = CA.CLEANUP_FEE_LAMPORTS if mode == 'closed' and not o['migrated'] else SPL_RENT_LAMPORTS", "    rent = CA.CLEANUP_FEE_LAMPORTS if mode == 'closed' else SPL_RENT_LAMPORTS", 'migrated_closed'),
 ("    slow = run_rule(timeline, k, actors, replace(model, latency_slots=LATENCY_SENSITIVITY_SLOTS), CG.RULE)", "    slow = run_rule(timeline, k, actors, model, CG.RULE)", 'latency10_not_applied'),
 ("    if not low <= facts['creation_slot'] < high:", "    if False:", 'outside_window_read'),
 ("    c2_superiority_to_paired_placebo=low_diff is not None and low_diff > 0,", "    c2_superiority_to_paired_placebo=True,", 'c2_skipped'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w2arms', work / 'w2arms')
    (work / 'w2arms' / 'ce.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'w2arms' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
