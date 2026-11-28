"""Driver of U-2 TIME 2 (cpmmpilot 0.2.2): permutation of L and creation transactions, ONLY with the sha of L anchored
by R02. Resumes the ledger of the time-1 run in the SAME --run directory (cumulative cap: U2_CAP - credits of the
stopped run of 24/11 09:23:16Z, read from its committed ledger, sha checked). One run only.
Usage: python -B u2_time2.py --pkg <pkg> --run <time-1 run dir> --anchored-sha-l <64 hex> --prior-ledger <ledger_u2.json>
Prints only shas, counts and pool addresses; never the endpoint, never a key."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, u2

ENDPOINT = 'https://beta.helius-rpc.com/'          # admitted by R02 (07:20Z); the key is injected by the proxy
PRIOR_LEDGER_SHA256 = '24535f41dac5b389fc2201fd9e6cfef029942812aae703ca9701996d522a4b96'   # stopped run, 287 credits

p = argparse.ArgumentParser()
p.add_argument('--pkg', type=Path, required=True)
p.add_argument('--run', type=Path, required=True)
p.add_argument('--anchored-sha-l', required=True)
p.add_argument('--prior-ledger', type=Path, required=True)
a = p.parse_args()
if (a.run / 'TIME2_RESULT.json').exists():                 # K-1 (R02): one run, even after a STOP
    raise SystemExit('time2_already_run')
if not re.fullmatch('[0-9a-f]{64}', a.anchored_sha_l):
    raise SystemExit('anchored_sha_l_must_be_64_hex')
prior_raw = a.prior_ledger.read_bytes()
if hashlib.sha256(prior_raw).hexdigest() != PRIOR_LEDGER_SHA256:
    raise SystemExit('prior_ledger_sha_mismatch')
cap = B.U2_CAP - json.loads(prior_raw)['credits']
if not (a.run / 'u2' / 'LIST_L.json').exists() or (a.run / 'u2' / 'U2.json').exists():
    raise SystemExit('time1_list_missing_or_time2_already_done')
live = rpc.LiveRpc(ENDPOINT, authorization_file=a.pkg / 'AUTORISATION_B_C_v1_3.txt', timeout_s=120)
client = rpc.Client(live, B.PilotBudget(a.run / 'ledger_u2.json', stage='u2', max_credits=cap), a.run / 'calls_u2.jsonl')
start_credits = client.budget.credits
try:
    doc = u2.run_qualify(client, a.run / 'u2', anchored_sha_l=a.anchored_sha_l)
    out = dict(verdict=doc['verdict'], sha_l=doc['sha_l'], tested=doc['tested'], creation_reasons=doc['creation_reasons'],
               selected=[r['pool'] for r in doc['selected']], u2_file_sha256=hashlib.sha256(
                   (a.run / 'u2' / 'U2.json').read_bytes()).hexdigest())
except Exception as exc:                                   # STOP, no fallback: type and tag only
    out = dict(verdict='STOP', error=type(exc).__name__, tag=str(exc)[:120])
out.update(budget=client.budget.snapshot(), credits_time1=start_credits, cap_this_run=cap)
(a.run / 'TIME2_RESULT.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
print(json.dumps(out, default=str))
