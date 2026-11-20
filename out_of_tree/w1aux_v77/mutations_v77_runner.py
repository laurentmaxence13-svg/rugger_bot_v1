"""Deliberate defects in w1aux/ledger_c1.py: each must make test_ledger_c1.py fail."""
import json, shutil, subprocess
from pathlib import Path
S = Path('/tmp/claude-0/-home-user/e0619565-42dc-58dc-a353-d81a7198e975/scratchpad')
V = '/tmp/claude-0/-home-user-rugger-bot-v1/e0619565-42dc-58dc-a353-d81a7198e975/scratchpad/venv312/bin/python'
SRC = S / 'wt_tooling/out_of_tree/w1aux_v77'
MUT = [
 ('applied_to_every_outcome', "    if row.get('outcome') not in RELABELED or spec is None or 'tx_costs' not in checks:\n",
  "    if spec is None or 'tx_costs' not in checks:\n"),
 ('early_stop_ignored', " or spec is None or 'tx_costs' not in checks:\n", " or spec is None:\n"),
 ('always_two', "    own = 2 if priced else 1\n", "    own = 2\n"),
 ('always_one', "    own = 2 if priced else 1\n", "    own = 1\n"),
 ('old_cost_mismatches_kept', "    checks, bad = dict(checks), [b for b in bad if _reason(b) not in COST_CHECKS]\n", "    checks, bad = dict(checks), list(bad)\n"),
 ('failed_not_rechecked', "    check('failed_attempt_costs', params['failed_attempt_fee_lamports'] * own, row['failed_attempt_costs'])\n", ""),
 ('exit_index_not_checked', "        check('exit_index', hold['exit_index'], row['exit_index'])\n", ""),
 ('note_ignored', "        expected = (('closed',) if note else ('open_at_end',)) if row['outcome'] == 'migrated_unpriced' else PRICED\n",
  "        expected = PRICED\n"),
 ('consistency_not_checked', "        check('c1_relabel_consistent', hold['outcome'] in expected, True)\n", ""),
 ('unpriced_outcome_not_checked', "        check('outcome', hold['outcome'], row['outcome'])\n", "        pass\n"),
 ('priced_set_wrong', "PRICED = ('closed', 'open_at_end')\n", "PRICED = ('closed',)\n"),
 ('window_not_covered', "RELABELED = ('open_at_window_end', 'migrated_unpriced')\n", "RELABELED = ('migrated_unpriced',)\n"),
 ('rule_flag_missing', "    checks['c1_rule_applied'] = True\n", ""),
 ('not_restored', "        ledger.verify_cycle = _ORIGINAL['verify_cycle']\n        _ACTIVE['on'] = False\n", "        _ACTIVE['on'] = False\n"),
 ('not_reentrancy_guarded', "    if _ACTIVE['on']:\n        raise LedgerC1Error('c1_rule_is_not_reentrant')\n", ""),
 ('ledger_sha_not_checked', "    lp._check_ledger_module()                                       # ledger.py must be v7.4, unmodified\n", ""),
 ('double_wrap_accepted', "        raise LedgerC1Error('verify_cycle_is_already_replaced')\n", "        pass\n"),
 ('rule_not_declared', "        yield dict(RULE, module='w1aux/ledger_c1.py', sha256=module_sha256())\n", "        yield {}\n"),
]
out = []
for name, old, new in MUT:
    dst = S / 'mut_c1' / 'pkg'
    shutil.rmtree(dst, ignore_errors=True); shutil.copytree(SRC, dst)
    f = dst / 'w1aux' / 'ledger_c1.py'
    t = f.read_text(); assert t.count(old) == 1, name; f.write_text(t.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(dst / 'w1aux/tests/test_ledger_c1.py'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=S / 'wt_w1', capture_output=True, text=True, timeout=1500,
                       env={'PYTHONPATH': f"{S/'wt_w1'}:{dst}", 'RUGGER_NO_DOTENV': '1', 'PATH': '/usr/bin:/bin'})
    out.append(dict(mutant=name, detected=r.returncode != 0, last=(r.stdout.strip().splitlines() or [''])[-1]))
    print(json.dumps(out[-1]), flush=True)
print(f"detected {sum(o['detected'] for o in out)}/{len(out)}")
