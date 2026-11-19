"""Deliberate defects in w1diag/c1_table.py: each must make the tests fail."""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).parent
MUT = [
 ('other_trial_selected', "              if m.get('trial') == TRIAL and any(", "              if any("),
 ('other_check_selected', "str(x).split(':', 1)[0] == 'tx_costs' for x", "True for x"),
 ('multiple_not_integer_checked', "cost // unit if isinstance(cost, int) and unit and cost % unit == 0 else 'non_integer'", "cost // unit"),
 ('raw_outcome', "            outcome = row.get('outcome') if row.get('outcome') in OUTCOMES else 'other'\n", "            outcome = row.get('outcome')\n"),
 ('raw_arm', "    rows[(arm if isinstance(arm, str) and _NAME.fullmatch(arm) else 'unrecognized', outcome, multiple,", "    rows[(arm, outcome, multiple,"),
 ('mark_value_leaked', "                  'mark_pnl_lamports' in row and row['mark_pnl_lamports'] is not None,", "                  row.get('mark_pnl_lamports'),"),
 ('migration_note_ignored', "                  'exit_after_migration' in (row.get('notes') or ()), row.get('exit_index') is not None)] += 1",
  "                  False, row.get('exit_index') is not None)] += 1"),
 ('missing_rows_accepted', "        raise C1TableError('selected_entries_missing_from_the_bundle')\n", "        pass\n"),
 ('ledger_sha_not_checked', "    if hashlib.sha256(data).hexdigest() != sha:\n", "    if False:\n"),
 ('tx_value_leaked', "    return dict(entries=found, table=", "    return dict(entries=found, unit=unit, table="),
]
out = []
for name, old, new in MUT:
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / 'pkg'
        shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns('__pycache__'))
        f = dst / 'w1diag' / 'c1_table.py'
        t = f.read_text(); assert t.count(old) == 1, name; f.write_text(t.replace(old, new))
        r = subprocess.run([sys.executable, '-B', '-m', 'pytest', str(dst / 'w1diag/tests/test_c1_table.py'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                           cwd=dst, capture_output=True, text=True, env={'PYTHONPATH': str(dst), 'PATH': '/usr/bin:/bin'})
        out.append(dict(mutant=name, detected=r.returncode != 0)); print(json.dumps(out[-1]))
print(f"detected {sum(o['detected'] for o in out)}/{len(out)}")
