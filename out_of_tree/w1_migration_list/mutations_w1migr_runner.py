import json, shutil, subprocess, sys
from pathlib import Path
D, V, M = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
src = (D / 'w1migr' / 'migration_list.py').read_text()
MUT = [
 ("if slot_min <= slot < slot_max:", "if slot_min <= slot <= slot_max:", 'upper_bound_inclusive'),
 ("if slot_min <= slot < slot_max:", "if slot_min < slot < slot_max:", 'lower_bound_exclusive'),
 ("members.sort(key=lambda m: (m['boundary_slot'], m['boundary_transaction_index'], m['pool']))", "members.sort(key=lambda m: (m['boundary_slot'], m['pool']))", 'index_ignored_in_order'),
 ("pilot=[m['pool'] for m in members[:pilot_size]]", "pilot=[m['pool'] for m in members[-pilot_size:]]", 'pilot_last'),
 ("if AFTER_BOUNDARY in (p.get('reasons') or [])", "if p.get('reasons')", 'any_exclusion_counted'),
 ("if hashlib.sha256(raw).hexdigest() != bundle_sha256:", "if False:", 'sha_ignored'),
 ("            raise MigrationListError('duplicate_pool_in_bundle')", "            pass", 'duplicates_accepted'),
 ("if out.exists():", "if False:", 'overwrite_allowed'),
 ("        if type(slot) is not int or type(index) is not int:", "        if False:", 'slot_type_unchecked'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'w1migr', work / 'w1migr')
    (work / 'w1migr' / 'migration_list.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', 'w1migr/tests', '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=work, env={'PYTHONPATH': str(work), 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1))
print(sum(o['detected'] for o in out), '/', len(out))
