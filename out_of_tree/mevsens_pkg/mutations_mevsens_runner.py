import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'mevsens' / 'model.py').read_text()
MUT = [
 ("        shifted = buy_exact_in(state, front, rate).after if front else state", "        shifted = state", 'buy_front_run_ignored'),
 ("    return low, fill_after_front_run(state, amount, rate, low)", "    return high, fill_after_front_run(state, amount, rate, high)", 'returns_the_failing_front_run'),
 ("    floor = 0 if guard_ppm is None else G.minimum(expected, guard_ppm)", "    floor = 0 if guard_ppm is None else expected", 'guard_band_ignored'),
 ("        if ok(middle):\n            low = middle", "        if not ok(middle):\n            low = middle", 'search_inverted'),
 ("        shifted = sell_exact_in(state, front_tokens, rate).after if front_tokens else state", "        shifted = state", 'sale_front_run_ignored'),
 ("    expected = sandwich_loss * scenario['probability_ppm'] // 1_000_000", "    expected = sandwich_loss", 'probability_ignored'),
 ("    tip = scenario['tip_lamports'] * own_transactions", "    tip = scenario['tip_lamports']", 'tip_once_only'),
 ("    if scenario['buy_front'] == 'guard_bound':", "    if False:", 'scenario_buy_front_ignored'),
 ("    if scenario not in SCENARIOS:", "    if False:", 'any_scenario_accepted'),
 ("    if scenario['sale_front_multiple']:", "    if False:", 'scenario_sale_front_ignored'),
]
# Baseline guard (R02, 21:34Z): the unmutated package must PASS with this PYTHONPATH, otherwise a collection error would
# make every mutant look detected.
base = subprocess.run([V, '-B', '-m', 'pytest', str(D / 'mevsens' / 'tests'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                      cwd=W, env={'PYTHONPATH': f'{PP}:{D}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'},
                      capture_output=True, text=True, timeout=600)
if base.returncode != 0:
    print(base.stdout[-2000:], base.stderr[-2000:])
    raise SystemExit('baseline_does_not_pass: no mutant is run')
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'mevsens', work / 'mevsens')
    (work / 'mevsens' / 'model.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'mevsens' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True, timeout=600)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
