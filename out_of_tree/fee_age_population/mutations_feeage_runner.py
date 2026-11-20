import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
src = (D / 'feeage' / 'population.py').read_text()
MUT = [
 ("if fees < MIN_FEE_LAMPORTS:", "if fees <= MIN_FEE_LAMPORTS:", 'min_fee_inclusive'),
 ("return int(round(rate / TIER_STEP_PPM)) * TIER_STEP_PPM, True", "return rate, True", 'no_tier_rounding'),
 ("if all(b <= a for a, b in zip(tiers, tiers[1:])):", "if all(b < a for a, b in zip(tiers, tiers[1:])):", 'strict_decrease'),
 ("first_late = next((tier for age, tier in usable if age >= LATE_SLOTS), None)", "first_late = next((tier for age, tier in reversed(usable) if age >= LATE_SLOTS), None)", 'last_late_tier'),
 ("if age >= LATE_SLOTS), None)", "if age > LATE_SLOTS), None)", 'late_exclusive'),
 ("if len(tiers) >= 2:", "if len(tiers) >= 1:", 'single_event_counted'),
 ("if manifest_sha != manifest_sha256:", "if False:", 'manifest_ignored'),
 ("usable.append((event.slot - creation_slot, tier))", "usable.append((event.slot, tier))", 'age_not_relative'),
 ("days = span * SLOT_MS / 1000 / 86_400", "days = span * 400 / 1000 / 86_400", 'clock_400ms'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'feeage', work / 'feeage')
    (work / 'feeage' / 'population.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'feeage' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{W}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'},
                       capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1))
print(sum(o['detected'] for o in out), '/', len(out))
