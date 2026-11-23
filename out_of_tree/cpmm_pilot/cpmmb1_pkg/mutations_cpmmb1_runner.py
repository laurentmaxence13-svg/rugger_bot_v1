import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cpmmb1' / 'rule.py').read_text()
MUT = [
 ("RISE = Fraction(3, 100)", "RISE = Fraction(2, 100)", 'rise_2pct'),
 ("        if R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 >= RISE:", "        if R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 > RISE:", 'rise_strict'),
 ("        if R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 >= RISE:", "        if R.spot_after(line, i, fees) / R.spot_after(line, refs[0], fees) - 1 >= RISE:", 'oldest_reference'),
 ("        if R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 >= RISE:", "        if R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 <= -RISE:", 'drop_instead_of_rise'),
 ("        if recent < R.MIN_SWAPS_IN_LOOKBACK:\n            continue", "        if False:\n            continue", 'activity_ignored'),
 ("        if last_open is not None and t - last_open < R.COOLDOWN_S:", "        if False:", 'cooldown_ignored'),
 ("        if not refs:\n            continue", "        if not refs:\n            refs = [0]", 'no_reference_accepted'),
 ("        per_pool[line.pool] = sum(1 for i in decisions(line, config) if line.swaps[i].block_time >= start)", "        per_pool[line.pool] = sum(1 for i in R.decisions(line, config) if line.swaps[i].block_time >= start)", 'count_uses_r_cp1'),
 ("        per_pool[line.pool] = sum(1 for i in decisions(line, config) if line.swaps[i].block_time >= start)", "        per_pool[line.pool] = len(decisions(line, config))", 'count_before_7_days'),
 ("        if any(s.block_time >= t0 for s in line.swaps):", "        if False:", 'data_after_t0_accepted'),
 ("        if line.pool in per_pool:", "        if False:", 'duplicate_pool_accepted'),
 ("        refs = [j for j in range(i) if line.swaps[j].block_time <= t - R.LOOKBACK_S]", "        refs = [j for j in range(i) if line.swaps[j].block_time < t - R.LOOKBACK_S]", 'ref_boundary_R02'),
 ("TRIALS_BEFORE = 169", "TRIALS_BEFORE = 168", 'trial_count_wrong'),
 ("    if type(n_before) is not int or n_before + 1 > R.TRIAL_CAP:", "    if type(n_before) is not int or n_before > R.TRIAL_CAP:", 'cap_off_by_one'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cpmmb1' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'cpmmb1', base / 'cpmmb1')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cpmmb1', work / 'cpmmb1')
    (work / 'cpmmb1' / 'rule.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
