import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cpmmprereg' / 'rule.py').read_text()
MUT = [
 ("DROP = Fraction(-3, 100)", "DROP = Fraction(-1, 100)", 'drop_threshold_1pct'),
 ("        if recent < MIN_SWAPS_IN_LOOKBACK:", "        if False:", 'activity_ignored'),
 ("        if last_open is not None and t - last_open < COOLDOWN_S:", "        if False:", 'cooldown_ignored'),
 ("        if not refs:\n            continue", "        if not refs:\n            refs = [0]", 'no_reference_accepted'),
 ("        if spot_after(line, i, fees) / spot_after(line, refs[-1], fees) - 1 <= DROP:", "        if spot_after(line, i, fees) / spot_after(line, refs[0], fees) - 1 <= DROP:", 'oldest_reference'),
 ("        if ratio >= TP or ratio <= SL:", "        if ratio >= TP:", 'stop_loss_ignored'),
 ("        if ratio >= TP or ratio <= SL:", "        if ratio <= SL:", 'take_profit_ignored'),
 ("            return swap.slot + CC.LATENCY_SLOTS, None", "            return swap.slot, None", 'exit_latency_ignored'),
 ("    return None, deadline + CLOCK_LATENCY_S", "    return None, deadline", 'clock_latency_ignored'),
 ("        if all(abs(t - line.swaps[c].block_time) >= COOLDOWN_S for c in chosen):", "        if True:", 'placebo_cooldown_ignored'),
 ("    candidates = [i for i in range(len(line.swaps)) if has_reference(line, i)]", "    candidates = list(range(len(line.swaps)))", 'placebo_without_reference'),
 ("    if eligible_pools < MIN_ELIGIBLE_POOLS:", "    if eligible_pools < 10:", 'eligibility_floor_10'),
 ("    if expected_entries < 30:", "    if expected_entries < 10:", 'power_floor_10'),
 ("    if type(n_before) is not int or n_before + 1 > TRIAL_CAP:", "    if type(n_before) is not int or n_before > TRIAL_CAP:", 'trial_cap_off_by_one'),
 ("SIGMA_DECLARED = 0.025", "SIGMA_DECLARED = 0.02", 'sigma_changed'),
 ("        (first if line.swaps[p['decision_index']].block_time < cut_time else second).append(p['net_return'])", "        first.append(p['net_return'])", 'halves_not_split'),
]
base = subprocess.run([V, '-B', '-m', 'pytest', str(D / 'cpmmprereg' / 'tests'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                      cwd=W, env={'PYTHONPATH': f'{PP}:{D}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'},
                      capture_output=True, text=True, timeout=600)
if base.returncode != 0:
    print(base.stdout[-2000:], base.stderr[-2000:])
    raise SystemExit('baseline_does_not_pass: no mutant is run')
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cpmmprereg', work / 'cpmmprereg')
    (work / 'cpmmprereg' / 'rule.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cpmmprereg' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True, timeout=600)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
