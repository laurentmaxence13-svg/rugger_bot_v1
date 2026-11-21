import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'w2arms' / 'orch.py').read_text()
MUT = [
 ("        s0 = s0_1 + i * WINDOW_SLOTS", "        s0 = s0_1 + i * (WINDOW_SLOTS + wc.GAP_SLOTS)", 'windows_not_consecutive'),
 ("            module = 'w1aux.dayj_c1p1' if step == 'ledger' else 'w1aux.dayj'", "            module = 'w1aux.dayj'", 'ledger_without_c1'),
 ("    return (CREDIT_CAP - PILOT_CREDITS) // sum(caps().values())", "    return CREDIT_CAP // sum(W1_CREDITS.values())", 'no_margin_no_pilot'),
 ("                            quota_month=i // per_month + 1,", "                            quota_month=1,", 'single_month'),
 ("            raise OrchError(f\"run_{w['index']}_is_not_the_planned_window\")", "            pass", 'run_window_unchecked'),
 ("            raise OrchError(f\"dayj_{w['index']}_has_another_s0\")", "            pass", 'dayj_s0_unchecked'),
 ("    if hashlib.sha256(raw).hexdigest() != a.plan_sha256:", "    if False:", 'plan_sha_ignored'),
 ("        if b['s0'] - a['s0'] != WINDOW_SLOTS or b['evaluation'][0] != a['evaluation'][1]:", "        if False:", 'consecutive_unchecked'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w2arms', work / 'w2arms')
    (work / 'w2arms' / 'orch.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'w2arms' / 'tests' / 'test_orch.py'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
