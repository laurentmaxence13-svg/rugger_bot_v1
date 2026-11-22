import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cyclesplit' / 'split.py').read_text()
MUT = [
 ("        if slot < evaluation_min:", "        if slot <= evaluation_min:", 'min_inclusive_for_before'),
 ("        elif slot < evaluation_max:", "        elif slot <= evaluation_max:", 'max_inclusive_for_inside'),
 ("        if pool['arms']['master']['outcome'] != 'closed':", "        if pool['arms']['reference']['outcome'] != 'closed':", 'wrong_arm'),
 ("        if pool['arms']['master']['outcome'] != 'closed':", "        if False:", 'every_outcome_counted'),
 ("    if got != bundle_sha256:", "    if False:", 'sha_unchecked'),
 ("    if total != bundle['totals']['master']['closed_cycles']:", "    if False:", 'frozen_total_unchecked'),
 ("        if type(slot) is not int:", "        if slot is None and False:", 'missing_slot_accepted'),
 ("    evaluation_min, evaluation_max = w1_collection.bounds(s0)['evaluation']", "    evaluation_min, evaluation_max = s0, s0 + 2_015_600", 'bounds_not_the_frozen_ones'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cyclesplit', work / 'cyclesplit')
    (work / 'cyclesplit' / 'split.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cyclesplit' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
