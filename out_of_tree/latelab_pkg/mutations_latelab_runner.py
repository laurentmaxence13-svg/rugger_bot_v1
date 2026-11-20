import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'latelab' / 'study.py').read_text()
MUT = [
 ("return 'discovery' if creation_slot < CUT_SLOT else 'screen'", "return 'discovery' if creation_slot <= CUT_SLOT else 'screen'", 'cut_inclusive'),
 ("if not EVAL_MIN <= creation_slot < EVAL_MAX:", "if not EVAL_MIN <= creation_slot <= EVAL_MAX:", 'eval_upper_inclusive'),
 ("        return -1.0", "        return 0.0", 'migrated_zero'),
 ("def net_return(outcome, *, rent=SPL_RENT_LAMPORTS):", "def net_return(outcome, *, rent=0):", 'rent_recovered_by_default'),
 ("key=lambda c: (-cells[c]['interval_95']['low'], c))", "key=lambda c: (-cells[c]['mean_net_return'], c))", 'rank_by_mean'),
 ("interpretable = len(returns) >= MIN_N and len(clusters) >= MIN_CLUSTERS", "interpretable = len(returns) >= MIN_N", 'cluster_floor_dropped'),
 ("label[0] == 'age' and label[1] in AGES)]", "label[0] in ('age', 'progress'))]", 'other_labels_kept'),
 ("if not top1 or a.cell != top1[0]:", "if not top1:", 'screen_any_cell'),
 ("if hashlib.sha256(raw).hexdigest() != a.discovery_sha256:", "if False:", 'discovery_sha_ignored'),
 ("out['passes'] = out['interpretable'] and out['mean_net_return'] is not None and out['mean_net_return'] > 0", "out['passes'] = out['mean_net_return'] is not None and out['mean_net_return'] > 0", 'pass_without_floor'),
 ("RULE = dict(id='CLOCK60', clock_s=EXIT_CLOCK_S)", "RULE = dict(id='CLOCK60', clock_s=30)", 'clock_changed'),
 ("ranking_rule='interpretable cells by the lower bound of the 95 % interval', top1=ranked[:1],", "ranking_rule='interpretable cells by the lower bound of the 95 % interval', top1=ranked[:2],", 'top2_instead_of_top1'),
 ("if hashlib.sha256(a.dossier_a.read_bytes()).hexdigest() != a.dossier_a_sha256:", "if False:", 'dossier_a_sha_ignored'),
 ("        if 'C-D FIGÉ' not in a.dossier_a.read_text(encoding='utf-8'):", "        if False:", 'dossier_a_content_ignored'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'latelab', work / 'latelab')
    (work / 'latelab' / 'study.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'latelab' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
