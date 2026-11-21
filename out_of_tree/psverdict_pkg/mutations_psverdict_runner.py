import json, re, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'psverdict' / 'verdict.py').read_text()
names = ['printed_sha', 'rc', 'schema', 'network', 'trials_added', 'not_a_trial', 'memory_override', 'firewall',
         'manifest', 'series', 'expected_file', 'expected_json', 'expected_field', 'identity_file', 'identity_json',
         'identity_field', 'journal', 'master_closed', 'labels', 'cycles_sum', 'field_consistent']
MUT = []
for n in names:
    m = re.search(r"    c\['%s'\] = [^\n]*(?:\n {8,}[^\n]*)*" % n, src)
    assert m and src.count(m.group(0)) == 1, n
    MUT.append((m.group(0), "    c['%s'] = True" % n, n + '_always_true'))
MUT.append(("        verdict = 'INVALID_RUN'", "        verdict = 'IDENTITY_FAILED'", 'invalid_reported_as_failed'))
MUT.append(("                if type(item) is not int:", "                if False:", 'reason_values_unchecked'))
MUT.append(("        reasons = bool(path) and path[-1] == 'blocking_reasons'", "        reasons = False", 'reason_keys_not_exempt'))
MUT.append(("            bad.extend(firewall(item, path + (k,)))", "            pass", 'firewall_not_recursive'))
MUT.append(("    c['journal'] = (type(doc.get('reconciled_cycles')) is int and doc['reconciled_cycles'] > 0", "    c['journal'] = (type(doc.get('reconciled_cycles')) is int", 'zero_cycles_accepted'))
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
