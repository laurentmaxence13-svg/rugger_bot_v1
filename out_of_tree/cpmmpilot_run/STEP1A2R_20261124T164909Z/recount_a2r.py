"""R02 recount of A2r (24/11 17:18Z), OFFLINE, frozen functions, 0 credit, no call.
Usage: python -B recount_a2r.py <run dir STEP1A_...> <U2.json> <SHA256SUMS_PRE_PAGES.txt> <out.json>"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cpmmb1 import rule as B1
from cpmmprereg import rule as RCP1
from cpmmx.events import CPMM_PROGRAM
from cpmmpilot import step1

run, u2, sums, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
pre = run / 'step1' / 'collect' / 'pre'
check = subprocess.run(['sha256sum', '-c', str(sums.resolve())], cwd=pre, capture_output=True, text=True)
bad = [l for l in check.stdout.splitlines() if not l.endswith(': OK')]
doc = json.loads(u2.read_bytes())
sel, t0 = doc['selected'], doc['t0_time']
cfg = step1.amm_config_for_rules(sel, doc['t0_slot'])
per_pool, tot = {}, dict(swaps=0, lp_changes=0, rcp1=0, b1=0, skipped=0, truncated=0, truncated_cpmm_in_message=0,
                         truncated_cpmm_in_logs=0)
for r in sel:
    pool = r['pool']
    txs = step1.transactions_of(run / 'step1', 'pre', pool)
    line = step1.timelines(run / 'step1', 'pre', [r])[0]
    reasons = {}
    for sig, why in line.skipped:
        reasons[why] = reasons.get(why, 0) + 1
    trunc = [s for s, why in line.skipped if why == 'log_truncated']
    in_msg = sum(1 for s in trunc if CPMM_PROGRAM in json.dumps(txs[s].get('transaction'))
                 or CPMM_PROGRAM in json.dumps((txs[s].get('meta') or {}).get('loadedAddresses')))
    in_logs = sum(1 for s in trunc if any(CPMM_PROGRAM in l for l in ((txs[s].get('meta') or {}).get('logMessages') or [])))
    a = RCP1.trigger_count([line], cfg, t0)['triggers']
    b = B1.trigger_count([line], cfg, t0)['triggers']
    per_pool[pool] = dict(transactions=len(txs), swaps=len(line.swaps), lp_changes=len(line.lp_changes),
                          skipped_by_reason=reasons, rcp1=a, b1=b, truncated=len(trunc),
                          truncated_cpmm_in_message=in_msg, truncated_cpmm_in_logs=in_logs)
    for k, v in (('swaps', len(line.swaps)), ('lp_changes', len(line.lp_changes)), ('rcp1', a), ('b1', b),
                 ('skipped', len(line.skipped)), ('truncated', len(trunc)), ('truncated_cpmm_in_message', in_msg),
                 ('truncated_cpmm_in_logs', in_logs)):
        tot[k] += v
all_lines = step1.timelines(run / 'step1', 'pre', sel)
res = dict(schema='a2r-recount-v1', sha256sums_check=dict(rc=check.returncode, bad=len(bad)), per_pool=per_pool,
           total=tot, total_rules_on_all_lines=dict(rcp1=RCP1.trigger_count(all_lines, cfg, t0)['triggers'],
                                                    b1=B1.trigger_count(all_lines, cfg, t0)['triggers']))
out.write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
print(json.dumps(dict(total=tot, all_lines=res['total_rules_on_all_lines'], sums=res['sha256sums_check'])))
print('out_sha256', hashlib.sha256(out.read_bytes()).hexdigest())
