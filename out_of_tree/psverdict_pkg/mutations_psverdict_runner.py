import json, re, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'psverdict' / 'verdict.py').read_text()
names = ['printed_sha', 'rc', 'schema', 'network', 'trials_added', 'not_a_trial', 'memory_override', 'firewall',
         'manifest', 'series', 'expected_file', 'expected_json', 'expected_field', 'identity_file', 'identity_json',
         'identity_field', 'journal', 'master_closed']
MUT = []
for n in names:
    m = re.search(r"    c\['%s'\] = .*?(?=\n    c\[|\n    master|\n    index_path)" % n, src, re.S)
    assert m and src.count(m.group(0)) == 1, n
    MUT.append((m.group(0), "    c['%s'] = True" % n, n + '_always_true'))
MUT.append(("        verdict = 'INVALID_RUN'", "        verdict = 'IDENTITY_FAILED'", 'invalid_reported_as_failed'))
MUT.append(("                           and index.get('context', {}).get('mode') == 'stream')", ")", 'checkpoint_mode_unchecked'))
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'psverdict', work / 'psverdict')
    (work / 'psverdict' / 'verdict.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'psverdict' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
