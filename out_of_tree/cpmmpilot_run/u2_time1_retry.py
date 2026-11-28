"""Driver of a NEW U-2 TIME 1 after the 429 STOP of 24/11 09:23:16Z (cpmmpilot 0.2.2). One run only, from scratch
(R02 note 41c20a16, D4: no page, T0 or parameter of the stopped run is reused). The cap is CUMULATIVE (D5): the
credits of the stopped run, read from its committed ledger (sha checked), are deducted from U2_CAP.
Usage: python -B u2_time1_retry.py --pkg <cpmmpilot_pkg> --out <NEW DIR> --exclude <file> --prior-ledger <ledger_u2.json>
Prints only shas and counts; never the endpoint, never a key."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, u2

ENDPOINT = 'https://beta.helius-rpc.com/'          # admitted by R02 (07:20Z); the key is injected by the proxy
PRIOR_LEDGER_SHA256 = '24535f41dac5b389fc2201fd9e6cfef029942812aae703ca9701996d522a4b96'   # stopped run, 287 credits

p = argparse.ArgumentParser()
p.add_argument('--pkg', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--exclude', type=Path, required=True)
p.add_argument('--prior-ledger', type=Path, required=True)
a = p.parse_args()
prior_raw = a.prior_ledger.read_bytes()
if hashlib.sha256(prior_raw).hexdigest() != PRIOR_LEDGER_SHA256:
    raise SystemExit('prior_ledger_sha_mismatch')
prior = json.loads(prior_raw)['credits']
cap = B.U2_CAP - prior
if a.out.exists():
    raise SystemExit('out_exists')
a.out.mkdir(parents=True)
excl_raw = a.exclude.read_bytes()
exclude = frozenset(x for x in excl_raw.decode().split() if x)
live = rpc.LiveRpc(ENDPOINT, authorization_file=a.pkg / 'AUTORISATION_B_C_v1_3.txt', timeout_s=120)
client = rpc.Client(live, B.PilotBudget(a.out / 'ledger_u2.json', stage='u2', max_credits=cap), a.out / 'calls_u2.jsonl')
t0_time = int(time.time())
try:
    doc = u2.run_list(client, a.out / 'u2', t0_time=t0_time, exclude=exclude)
except Exception as exc:                                   # STOP, no fallback: type and tag only
    doc = dict(verdict='STOP', error=type(exc).__name__, tag=str(exc)[:120], budget=client.budget.snapshot())
doc = dict(doc, exclude_sha256=hashlib.sha256(excl_raw).hexdigest(), exclude_n=len(exclude),
           authorization_sha256=live.authorization_sha256, prior_credits=prior, cap_this_run=cap,
           min_interval_s=rpc.MIN_INTERVAL_S)
(a.out / 'TIME1_RESULT.json').write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + '\n')
print(json.dumps({k: doc.get(k) for k in ('verdict', 'sha_l', 'list_l_file_sha256', 'counts', 'budget', 'error', 'tag',
                                          'prior_credits', 'cap_this_run', 'exclude_n', 't0_slot', 't0_time')}, default=str))
