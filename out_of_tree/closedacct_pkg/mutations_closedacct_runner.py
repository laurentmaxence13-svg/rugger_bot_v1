import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'closedacct' / 'model.py').read_text()
MUT = [
 ("CLEANUP_FEE_LAMPORTS = 105_000", "CLEANUP_FEE_LAMPORTS = 5_000", 'fee_live_default_as_main'),
 ("    return (outcome['value'] - outcome['cost'] - fees) / outcome['cost']", "    return (outcome['value'] - outcome['cost']) / outcome['cost']", 'cleanup_fee_free'),
 ("    fees = (failed_attempts + 1) * cleanup_fee", "    fees = cleanup_fee", 'failed_attempts_free'),
 ("    if failed_attempts == MAX_CLEANUP_ATTEMPTS:", "    if False:", 'never_left_open'),
 ("    if outcome['migrated']:\n        return -1.0\n    if outcome.get('value')", "    if outcome['migrated']:\n        return 0.0\n    if outcome.get('value')", 'migrated_zero'),
 ("        raise ClosedAccountError('closed_mode_requires_a_total_sale')", "        return 0.0", 'incomplete_sale_accepted'),
 ("    return (outcome['value'] - outcome['cost'] - rent) / (outcome['cost'] + rent)\n\n\ndef net_return_closed", "    return (outcome['value'] - outcome['cost']) / outcome['cost']\n\n\ndef net_return_closed", 'open_mode_rent_recovered'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'closedacct', work / 'closedacct')
    (work / 'closedacct' / 'model.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'closedacct' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
