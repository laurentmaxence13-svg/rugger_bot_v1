import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'ps0521verdict' / 'verdict.py').read_text()
MUT = [
 ("SCHEMA_EXPECTED = 'paperstream-v0.5.2.1'", "SCHEMA_EXPECTED = 'paperstream-v0.5.1'", 'old_schema_expected'),
 ("    c['I1_schema_and_flags'] = (doc.get('schema') == SCHEMA_EXPECTED and doc.get('fast_analyser') is True",
  "    c['I1_schema_and_flags'] = (doc.get('fast_analyser') is True", 'schema_unchecked'),
 ("    if type(unsampled_window) is not str or not re.match(WINDOW_FORMAT, unsampled_window):\n        raise VerdictError('bad_unsampled_window')",
  "    if False:\n        raise VerdictError('bad_unsampled_window')", 'window_unchecked'),
 ("        return 2, True, ('no unsampled window' if unsampled_window == 'none' else 'unsampled window ' + unsampled_window)",
  "        return 2, True, 'unsampled window 15:29:53-15:32:51Z'", 'old_window_note'),
 ("    if peaks['max_usage'] <= available:\n        return 1, True, None", "    if True:\n        return 1, True, None", 'rule_1_always'),
 ("    if peaks['sum_vmrss'] <= available and peaks['rss'] <= available:", "    if peaks['sum_vmrss'] <= available:", 'rule_2_without_rss'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'ps0521verdict', work / 'ps0521verdict')
    (work / 'ps0521verdict' / 'verdict.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'ps0521verdict' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
