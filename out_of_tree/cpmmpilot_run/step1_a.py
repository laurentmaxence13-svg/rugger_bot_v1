"""Driver of STEP 1, part A (owner text C points (1) and (2) ONLY, R02 10:29Z), cpmmpilot 0.2.2. One run only.
(1) getSignaturesForAddress over the 24 h before T0 for the 24 pools of the ANCHORED U2.json -> R^;
(2) point-(2) rule: 24 x R^ x 8 x 0.10 + 400 > 32 900 -> STOP, no trial consumed, the owner is referred to;
then STOP in every case: R02 anchors R^ and the point-(2) result before (3) and (4) (driver A2).
Own ledger (stage 'step1', hard stop 49 000), resumed by the next drivers. Prints only shas and counts.
Usage: python -B step1_a.py --pkg <pkg> --u2 <U2.json> --anchored-u2-sha <hex> --out <NEW DIR>"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, step1

ENDPOINT = 'https://beta.helius-rpc.com/'          # admitted by R02 (07:20Z); the key is injected by the proxy

p = argparse.ArgumentParser()
p.add_argument('--pkg', type=Path, required=True)
p.add_argument('--u2', type=Path, required=True)
p.add_argument('--anchored-u2-sha', required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
if not re.fullmatch('[0-9a-f]{64}', a.anchored_u2_sha):
    raise SystemExit('anchored_u2_sha_must_be_64_hex')
raw = a.u2.read_bytes()
if hashlib.sha256(raw).hexdigest() != a.anchored_u2_sha:
    raise SystemExit('u2_not_anchored')
doc = json.loads(raw)
if doc.get('verdict') != 'U2_OK' or len(doc['selected']) != 24:
    raise SystemExit('u2_not_ok')
if a.out.exists():
    raise SystemExit('out_exists')
a.out.mkdir(parents=True)
selected, pools, t0 = doc['selected'], [r['pool'] for r in doc['selected']], doc['t0_time']
live = rpc.LiveRpc(ENDPOINT, authorization_file=a.pkg / 'AUTORISATION_B_C_v1_3.txt', timeout_s=120)
client = rpc.Client(live, B.PilotBudget(a.out / 'ledger_step1.json', stage='step1', max_credits=B.STEP1_HARD_STOP),
                    a.out / 'calls_step1.jsonl')
res = dict(u2_sha256=a.anchored_u2_sha, t0_time=t0, t0_slot=doc['t0_slot'])
try:
    cnt = step1.count_24h(client, pools, t0_time=t0)
    (a.out / 'COUNT_24H.json').write_text(json.dumps(cnt, indent=1, sort_keys=True) + '\n')
    res.update(r_hat=cnt['r_hat'], point2=cnt['point2'], d_max_days=cnt['d_max_days'])
    res.update(count_file_sha256=hashlib.sha256((a.out / 'COUNT_24H.json').read_bytes()).hexdigest(),
               verdict='STOP_POINT2_NO_TRIAL_OWNER_REFERRED' if cnt['point2']['stop'] else 'POINT2_PASSED_AWAIT_R02_ANCHOR')
except Exception as exc:                                   # STOP, no fallback: type and tag only
    res.update(verdict='STOP', error=type(exc).__name__, tag=str(exc)[:120])
res.update(budget=client.budget.snapshot())
(a.out / 'STEP1A_RESULT.json').write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + '\n')
print(json.dumps(res, default=str))
