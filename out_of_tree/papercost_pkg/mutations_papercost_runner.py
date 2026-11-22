import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'papercost' / 'engine.py').read_text()
MUT = [
 ("        self.limit = self.events[k].slot + self.model.latency_slots * (1 + resent)", "        self.limit = self.events[k].slot + self.model.latency_slots", 'buy_failure_delay_ignored'),
 ("                candidates.append(before)", "                pass", 'buy_h1_ignored'),
 ("        if status == 'failed':\n            self.failed['buy'] += 1", "        if False:\n            self.failed['buy'] += 1", 'guard_failure_still_enters'),
 ("            self.failed['buy'] += 1\n            self.guard_failed = True", "            self.guard_failed = True", 'guard_failure_not_charged'),
 ("                self.pre_slot_state = self.state                    # before the real events of the sale slot", "                pass", 'sale_h1_ignored'),
 ("        if self.n3_sell_left > 0:", "        if False:", 'sale_failures_ignored'),
 ("        self.pending_exit_slot = base + self.model.latency_slots", "        self.pending_exit_slot = base", 'resend_not_delayed'),
 ("        if guard is not None and self.guard_sell_failures < G.SELL_MAX_FAILURES:", "        if False:", 'sale_guard_ignored'),
 ("    elif mode == 'rent_lost' or not sold:\n        account = RENT_LAMPORTS", "    elif mode == 'rent_lost' or not sold:\n        account = 0", 'rent_not_lost'),
 ("        account = (cleanup_failures + 1) * TX_FEE_LAMPORTS", "        account = 0", 'cleanup_free'),
 ("        account = RENT_LAMPORTS + cleanup_failures * TX_FEE_LAMPORTS", "        account = cleanup_failures * TX_FEE_LAMPORTS", 'left_open_rent_kept'),
 ("    wsol_cost = 0 if mode == 'frozen_assumption' else wsol * own_tx", "    wsol_cost = 0 if mode == 'frozen_assumption' else wsol", 'wsol_one_tx_only'),
 ("    received = row['received'] if priced else 0", "    received = row['received']", 'unpriced_not_at_zero'),
 ("    failed_fees = TX_FEE_LAMPORTS * (failed_buy + failed_sell) + row.get('failed_attempt_costs', 0)", "    failed_fees = row.get('failed_attempt_costs', 0)", 'failures_not_charged'),
 ("        return dict(status=status, counted=bool(failed_fees), net_lamports=-failed_fees,", "        return dict(status=status, counted=False, net_lamports=-failed_fees,", 'guard_failure_not_counted'),
 ("PRICED = ('closed', 'open_at_end', 'open_at_window_end')", "PRICED = ('closed',)", 'open_positions_excluded'),
 ("    if hashlib.sha256(Path(PS.__file__).read_bytes()).hexdigest() != PAPERSTREAM_ENGINE_SHA256:", "    if False:", 'engine_sha_unchecked'),
 ("            if c['counted']:\n                block['counted'] += 1", "            if c['status'] == 'closed':\n                block['counted'] += 1", 'summary_counts_closed_only'),
 ("            count += 1\n        return count", "            count += 1\n        return 0", 'probability_ignored'),
 ("    tx = row['tx_costs'] if priced else min(row['tx_costs'], TX_FEE_LAMPORTS)", "    tx = 0", 'transactions_forgotten'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'papercost', work / 'papercost')
    (work / 'papercost' / 'engine.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'papercost' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True, timeout=600)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
