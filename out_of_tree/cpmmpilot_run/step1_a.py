"""Driver of STEP 1, part A (owner text C points (1)-(4) up to the freeze sheets), cpmmpilot 0.2.2. One run only.
(1) getSignaturesForAddress over the 24 h before T0 for the 24 pools of the ANCHORED U2.json -> R^;
(2) point-(2) rule: 24 x R^ x 8 x 0.10 + 400 > 32 900 -> STOP here, no trial consumed;
(3) pre-T0 collection [T0 - 7 d ; T0) (GTFA full) and trigger counts of R-CP1 and B1, no outcome;
(4) the two freeze sheets (D = min(--d-days fixed by R02, D_max)), then STOP: R02 anchors them before any window read.
Own ledger (stage 'step1', hard stop 49 000). Prints only shas and counts; never the endpoint, never a key.
Usage: python -B step1_a.py --pkg <pkg> --u2 <U2.json> --anchored-u2-sha <hex> --out <NEW DIR> --d-days <float>"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, step1
from cpmmpilot.rehearse import code_sha

ENDPOINT = 'https://beta.helius-rpc.com/'          # admitted by R02 (07:20Z); the key is injected by the proxy

p = argparse.ArgumentParser()
p.add_argument('--pkg', type=Path, required=True)
p.add_argument('--u2', type=Path, required=True)
p.add_argument('--anchored-u2-sha', required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--d-days', type=float, required=True)
a = p.parse_args()
if not re.fullmatch('[0-9a-f]{64}', a.anchored_u2_sha):
    raise SystemExit('anchored_u2_sha_must_be_64_hex')
raw = a.u2.read_bytes()
if hashlib.sha256(raw).hexdigest() != a.anchored_u2_sha:
    raise SystemExit('u2_not_anchored')
doc = json.loads(raw)
if doc.get('verdict') != 'U2_OK' or len(doc['selected']) != 24:
    raise SystemExit('u2_not_ok')
if not 0 < a.d_days <= 60:
    raise SystemExit('d_days_out_of_range')
if a.out.exists():
    raise SystemExit('out_exists')
a.out.mkdir(parents=True)
selected, pools, t0 = doc['selected'], [r['pool'] for r in doc['selected']], doc['t0_time']
live = rpc.LiveRpc(ENDPOINT, authorization_file=a.pkg / 'AUTORISATION_B_C_v1_3.txt', timeout_s=120)
client = rpc.Client(live, B.PilotBudget(a.out / 'ledger_step1.json', stage='step1', max_credits=B.STEP1_HARD_STOP),
                    a.out / 'calls_step1.jsonl')
res = dict(u2_sha256=a.anchored_u2_sha, t0_time=t0, t0_slot=doc['t0_slot'], d_days_requested=a.d_days)
try:
    cnt = step1.count_24h(client, pools, t0_time=t0)
    (a.out / 'COUNT_24H.json').write_text(json.dumps(cnt, indent=1, sort_keys=True) + '\n')
    res.update(r_hat=cnt['r_hat'], point2=cnt['point2'], d_max_days=cnt['d_max_days'])
    if cnt['point2']['stop']:
        res.update(verdict='STOP_POINT2_NO_TRIAL')
    else:
        step1.collect(client, a.out / 'step1', pools, start_time=t0 - 7 * step1.DAY, end_time=t0, phase='pre')
        trig = step1.trigger_counts(a.out / 'step1', selected, t0_time=t0, t0_slot=doc['t0_slot'])
        d_days = min(a.d_days, cnt['d_max_days'])
        sheets = step1.freeze_sheets(a.out / 'step1', u2_doc=doc, count_doc=cnt, triggers=trig, d_days=d_days,
                                     code_sha=code_sha())
        res.update(verdict='SHEETS_AWAIT_R02_ANCHOR', d_days=d_days, sheets=sheets,
                   triggers=dict(rcp1=trig['rcp1']['triggers'], b1=trig['b1']['triggers'],
                                 skipped=trig['skipped_transactions']))
except Exception as exc:                                   # STOP, no fallback: type and tag only
    res.update(verdict='STOP', error=type(exc).__name__, tag=str(exc)[:120])
res.update(budget=client.budget.snapshot())
(a.out / 'STEP1A_RESULT.json').write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + '\n')
print(json.dumps(res, default=str))
