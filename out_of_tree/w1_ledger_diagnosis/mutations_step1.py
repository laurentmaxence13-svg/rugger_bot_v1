"""Deliberate defects in w1diag/histogram.py: each must make the tests fail."""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).parent
MUT = [
 ('check_not_filtered', "    return prefix if _CHECK.fullmatch(prefix) else 'unrecognized_check_name'\n", "    return prefix\n"),
 ('name_not_filtered', "    return value if isinstance(value, str) and _NAME.fullmatch(value) else 'unrecognized'\n", "    return str(value)\n"),
 ('counted_per_string', "        for check in sorted({_check(x) for x in m.get('mismatches') or ()}):    # one count per entry and check\n",
  "        for check in [_check(x) for x in m.get('mismatches') or ()]:\n"),
 ('true_counted', "        if (e.get('checks') or {}).get('l1_exit_plan_re_derived') is False:\n", "        if (e.get('checks') or {}).get('l1_exit_plan_re_derived') is not True:\n"),
 ('sha_not_checked', "    if hashlib.sha256(data).hexdigest() != a.ledger_sha256:\n", "    if False:\n"),
 ('cycles_leaked', "                mismatch_entries=len(mismatches),\n", "                mismatch_entries=len(mismatches), cycles_with_entry=doc.get('cycles_with_entry'),\n"),
 ('pool_list_leaked', "                pools_touched_by_trial={t: len(p) for t, p in sorted(pools.items())},\n",
  "                pools_touched_by_trial={t: sorted(map(str, p)) for t, p in sorted(pools.items())},\n"),
 ('verdict_raw', "    return dict(verdict=verdict if verdict in ('PASS', 'FAIL') else 'unrecognized',\n", "    return dict(verdict=verdict,\n"),
]
out = []
for name, old, new in MUT:
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / 'pkg'
        shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns('__pycache__'))
        f = dst / 'w1diag' / 'histogram.py'
        t = f.read_text(); assert t.count(old) == 1, name; f.write_text(t.replace(old, new))
        r = subprocess.run([sys.executable, '-B', '-m', 'pytest', str(dst / 'w1diag/tests'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                           cwd=dst, capture_output=True, text=True, env={'PYTHONPATH': str(dst), 'PATH': '/usr/bin:/bin'})
        out.append(dict(mutant=name, detected=r.returncode != 0))
        print(json.dumps(out[-1]))
print(f"detected {sum(o['detected'] for o in out)}/{len(out)}")
