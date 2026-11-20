import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'closedacct' / 'model.py').read_text()
MUT = [
 ("CLEANUP_FEE_LAMPORTS = 105_000", "CLEANUP_FEE_LAMPORTS = 5_000", 'fee_live_default_as_main'),
 ("    return (received - outcome['cost'] - (failed_attempts + 1) * cleanup_fee) / stake", "    return (received - outcome['cost'] - (failed_attempts + 1) * cleanup_fee) / outcome['cost']", 'closed_on_cost'),
 ("    return (_received(outcome) - outcome['cost'] - rent) / stake", "    return (_received(outcome) - outcome['cost'] - rent) / (outcome['cost'] + rent)", 'open_on_cost_plus_rent'),
 ("    return (received - outcome['cost'] - (failed_attempts + 1) * cleanup_fee) / stake", "    return (received - outcome['cost']) / stake", 'cleanup_fee_free'),
 ("(failed_attempts + 1) * cleanup_fee) / stake", "cleanup_fee) / stake", 'failed_attempts_free'),
 ("FROZEN_FAILED_ATTEMPTS = 0 ", "FROZEN_FAILED_ATTEMPTS = 1 ", 'frozen_attempts_1'),
 ("    if failed_attempts == MAX_CLEANUP_ATTEMPTS:", "    if False:", 'never_left_open'),
 ("        return net_return_open(outcome, rent=rent, stake=stake)", "        return -1.0", 'migrated_minus_one'),
 ("        raise ClosedAccountError('closed_mode_requires_a_total_sale')", "        return 0", 'incomplete_sale_accepted'),
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
