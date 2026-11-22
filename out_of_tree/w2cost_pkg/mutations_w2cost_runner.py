import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'w2cost' / 'proposal.py').read_text()
MUT = [
 ("    cycles = max(n_min(sigma, effect, **kwargs), N_MIN_DOSSIER_B)", "    cycles = n_min(sigma, effect, **kwargs)", 'floor_removed'),
 ("    z = NormalDist().inv_cdf(1 - alpha) + NormalDist().inv_cdf(power)", "    z = NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)", 'two_sided_alpha'),
 ("    return dict(cycles=cycles, decisions=math.ceil(cycles / entry_share), effect=effect)", "    return dict(cycles=cycles, decisions=cycles, effect=effect)", 'entry_share_ignored'),
 ("    effect = delta - extra_cost", "    effect = delta", 'cost_not_subtracted'),
 ("    if effect <= 0:\n        return None", "    if False:\n        return None", 'eaten_effect_not_detected'),
 ("    return record['status'] == RT.COMPLETE, record", "    return True, record", 'gapped_pool_admitted'),
 ("            if c['status'] == 'guard_failed':", "            if False:", 'guard_refusals_not_counted'),
 ("            f_mode = _net(frozen, PARAMETERS['primary']['account_mode'])", "            f_mode = _net(frozen, 'frozen_assumption')", 'engine_only_mixes_rent'),
 ("    adopted=False,", "    adopted=True,", 'marked_adopted'),
 ("    primary=dict(buy_guard_ppm=G.BUY_GUARD_PPM, sell_guard_ppm=None, h1=True,", "    primary=dict(buy_guard_ppm=G.BUY_GUARD_PPM, sell_guard_ppm=None, h1=False,", 'h1_off_in_primary'),
]
base = subprocess.run([V, '-B', '-m', 'pytest', str(D / 'w2cost' / 'tests'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                      cwd=W, env={'PYTHONPATH': f'{PP}:{D}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'},
                      capture_output=True, text=True, timeout=600)
if base.returncode != 0:
    print(base.stdout[-2000:], base.stderr[-2000:])
    raise SystemExit('baseline_does_not_pass: no mutant is run')
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w2cost', work / 'w2cost')
    (work / 'w2cost' / 'proposal.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'w2cost' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True, timeout=600)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
