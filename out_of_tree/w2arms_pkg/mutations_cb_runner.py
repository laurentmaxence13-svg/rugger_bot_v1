import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'w2arms' / 'cb.py').read_text()
MUT = [
 ("def net(row, horizon, rents, mode='open'):", "def net(row, horizon, rents, mode='closed'):", 'frozen_mode_closed'),
 ("        pairs = [(r, placebo[r['pool']]) for r in rows_ if r['pool'] in placebo]", "        pairs = [(r, p) for r in rows_ for p in placebo.values()][:len(rows_)]", 'placebo_not_same_pool'),
 ("            return str(h['horizon'])", "            return '25'", 'horizon_not_frozen'),
 ("    halves = [W._mean([net(r, horizon, rents) for r in cand if created[r['pool']] < middle]),", "    halves = [W._mean([net(r, horizon, rents) for r in cand if True]),", 'halves_not_by_creation'),
 ("        if doc.get('schema') != H.SCHEMA or doc.get('hypotheses_sha256') != FROZEN_HYPOTHESES_SHA256:", "        if doc.get('schema') != H.SCHEMA:", 'fingerprint_unchecked'),
 ("        if doc.get('latency_slots') != 4 or doc.get('source') != 'export':", "        if False:", 'latency_source_unchecked'),
 ("            if pool in created:\n                raise CbError('a_pool_in_two_windows')", "            if False:\n                raise CbError('a_pool_in_two_windows')", 'duplicates_allowed'),
 ("    if any(r['pool'] not in created for r in cand):", "    if False:", 'missing_creation_slot_allowed'),
 ("    elif all(conditions.values()):", "    elif conditions['c1_profitability']:", 'go_on_c1_only'),
 ("    if n < n_min:", "    if False:", 'n_min_ignored'),
 ("            if low <= slot < high:", "            if True:", 'creation_slots_outside_window'),
 ("        raise CbError(error)", "        pass", 'anchored_files_unchecked'),
 ("        c5 = slow is not None and slow > 0 and without_best5 is not None and without_best5 > 0", "        c5 = without_best5 is not None and without_best5 > 0", 'c5_without_latency10'),
 ("        c5 = slow is not None and slow > 0 and without_best5 is not None and without_best5 > 0", "        c5 = slow is not None and slow > 0", 'c5_without_best5_rule'),
 ("    without_best5 = W._mean(sorted(nets)[:-5]) if len(nets) > 5 else None", "    without_best5 = W._mean(sorted(nets)[5:]) if len(nets) > 5 else None", 'drops_the_5_worst'),
 ("    if hypothesis == 'HW1-5' and latency10_docs is None:", "    if False:", 'latency10_optional_for_hw1_5'),
 ("                d.get('latency_slots') != 10 or list(d.get('evaluation', [])) != list(x['evaluation'])", "                False or list(d.get('evaluation', [])) != list(x['evaluation'])", 'latency10_slots_unchecked'),
 ("    else:\n        c5 = True", "    else:\n        c5 = False", 'c5_fails_other_hypotheses'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w2arms', work / 'w2arms')
    (work / 'w2arms' / 'cb.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'w2arms' / 'tests' / 'test_cb.py'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
