"""Driver of U-2 TIME 1 (cpmmpilot 0.2.1, commit b526440, PASS R02 746f7d94). One run only.
Usage: python -B u2_time1.py --pkg <cpmmpilot_pkg> --out <NEW DIR> --exclude <file of pool addresses, one per line>
Prints only shas and counts; never the endpoint, never a key."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, u2

ENDPOINT = 'https://beta.helius-rpc.com/'          # admitted by R02 (07:20Z); the key is injected by the proxy

p = argparse.ArgumentParser()
p.add_argument('--pkg', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--exclude', type=Path, required=True)
a = p.parse_args()
if a.out.exists():
    raise SystemExit('out_exists')
a.out.mkdir(parents=True)
excl_raw = a.exclude.read_bytes()
exclude = frozenset(x for x in excl_raw.decode().split() if x)
live = rpc.LiveRpc(ENDPOINT, authorization_file=a.pkg / 'AUTORISATION_B_C_v1_3.txt', timeout_s=120)
client = rpc.Client(live, B.PilotBudget(a.out / 'ledger_u2.json', stage='u2', max_credits=B.U2_CAP),
                    a.out / 'calls_u2.jsonl')
t0_time = int(time.time())
try:
    doc = u2.run_list(client, a.out / 'u2', t0_time=t0_time, exclude=exclude)
except Exception as exc:                                   # STOP, no fallback: type and tag only
    doc = dict(verdict='STOP', error=type(exc).__name__, tag=str(exc)[:120], budget=client.budget.snapshot())
doc = dict(doc, exclude_sha256=hashlib.sha256(excl_raw).hexdigest(), exclude_n=len(exclude),
           authorization_sha256=live.authorization_sha256)
(a.out / 'TIME1_RESULT.json').write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + '\n')
print(json.dumps({k: doc.get(k) for k in ('verdict', 'sha_l', 'list_l_file_sha256', 'counts', 'budget', 'error', 'tag',
                                          'exclude_sha256', 'exclude_n', 't0_slot', 't0_time')}, default=str))
