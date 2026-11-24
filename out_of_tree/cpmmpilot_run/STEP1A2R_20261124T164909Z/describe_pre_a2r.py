"""DESCRIPTIVE measures of the A2r pre pages (R02 erratum a74e2579 Q3, R04 17:29Z), OFFLINE, 0 credit, no call.
NO position, exit or return of R-CP1, B1 or G2 is computed. Swaps come from the frozen decoder (cpmmx timelines via
cpmmpilot.step1); the only new reading is the fee: priority_paid = meta.fee - 5 000 x number of signatures (exact,
any version), cross-checked on v1 against message.transactionConfig.priorityFee.
Usage: python -B describe_pre_a2r.py <run dir STEP1A_...> <U2.json> <out.json>"""
import hashlib
import json
import statistics
import sys
from pathlib import Path

from cpmmb1 import rule as B1  # noqa: F401  (not used: no rule outcome is computed here)
from cpmmprereg import rule as RCP1
from cpmmpilot import step1

BASE_FEE_PER_SIGNATURE = 5_000
FROZEN_TX_FEE = 105_000                      # cpmmcost.TX_FEE_LAMPORTS, for the comparison only
DAY, HOUR = 86_400, 3_600


def q(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(p * len(s)))]


run, u2, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
doc = json.loads(u2.read_bytes())
sel, t0 = doc['selected'], doc['t0_time']
start = t0 - 7 * DAY
cfg = step1.amm_config_for_rules(sel, doc['t0_slot'])
rows, all_prio, all_fee, all_fail, all_tx = {}, [], [], 0, 0
v1_checked = v1_mismatch = 0
for r in sel:
    pool = r['pool']
    txs = step1.transactions_of(run / 'step1', 'pre', pool)
    line = step1.timelines(run / 'step1', 'pre', [r])[0]
    fails = sum(1 for t in txs.values() if (t.get('meta') or {}).get('err') is not None)
    prio, fees = [], []
    for t in txs.values():
        meta = t.get('meta') or {}
        nsig = len(t['transaction']['signatures'])
        if type(meta.get('fee')) is int:
            fees.append(meta['fee'])
            prio.append(meta['fee'] - BASE_FEE_PER_SIGNATURE * nsig)
            tc = (t['transaction'].get('message') or {}).get('transactionConfig')
            if str(t.get('version')) == '1' and isinstance(tc, dict) and type(tc.get('priorityFee')) is int:
                v1_checked += 1
                v1_mismatch += tc['priorityFee'] != meta['fee'] - BASE_FEE_PER_SIGNATURE * nsig
    sizes = [(s.event.input_amount if s.side == 'buy' else s.event.output_amount) / 1e9 for s in line.swaps]
    hours = [0] * (7 * 24)
    for s in line.swaps:
        h = (s.block_time - start) // HOUR
        if 0 <= h < len(hours):
            hours[h] += 1
    trig = RCP1.trigger_count([line], cfg, t0)['triggers']
    trunc = sum(1 for _s, why in line.skipped if why == 'log_truncated')
    rows[pool] = dict(transactions=len(txs), fail_share=round(fails / len(txs), 4) if txs else None,
                      swaps=len(line.swaps), swaps_per_day=round(len(line.swaps) / 7, 1),
                      swaps_per_hour=dict(min=min(hours), median=statistics.median(hours), max=max(hours)),
                      swap_size_sol=dict(median=q(sizes, 0.5), p90=q(sizes, 0.9)),
                      priority_paid_lamports=dict(median=q(prio, 0.5), p90=q(prio, 0.9)),
                      fee_paid_lamports=dict(median=q(fees, 0.5), p90=q(fees, 0.9)),
                      truncated_share=round(trunc / len(txs), 4) if txs else None,
                      rcp1_triggers=trig, swaps_per_rcp1_trigger=round(len(line.swaps) / trig, 1) if trig else None)
    all_prio += prio
    all_fee += fees
    all_fail += fails
    all_tx += len(txs)
total = dict(transactions=all_tx, fail_share=round(all_fail / all_tx, 4) if all_tx else None,
             swaps=sum(v['swaps'] for v in rows.values()),
             priority_paid_lamports=dict(median=q(all_prio, 0.5), p90=q(all_prio, 0.9)),
             fee_paid_lamports=dict(median=q(all_fee, 0.5), p90=q(all_fee, 0.9)),
             share_fee_above_frozen_105000=round(sum(f > FROZEN_TX_FEE for f in all_fee) / len(all_fee), 4) if all_fee else None,
             rcp1_triggers=sum(v['rcp1_triggers'] for v in rows.values()),
             v1_priorityfee_crosscheck=dict(checked=v1_checked, mismatches=v1_mismatch))
res = dict(schema='a2r-describe-v1', stamp='DESCRIPTIF - aucun rendement', per_pool=rows, total=total,
           note='fee = all transactions touching the pool (any trader); frozen cost model charges 105 000 per tx')
out.write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
print(json.dumps(total))
print('out_sha256', hashlib.sha256(out.read_bytes()).hexdigest())
