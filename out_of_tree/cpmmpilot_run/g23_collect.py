"""Collection of the G2-3 pilot window (decision R04-1 of 24/11 20:38Z under the owner's delegation of 20:37:04Z; R02 text
835d648e), cpmmpilot 0.2.8 (stage 'g23'). ONE run, ONLY after the window is closed (now >= T0 + 12 d) and after R02 anchored the freeze
sheet and the audited verdict code (their sha are required arguments). Raw GTFA pages of the 4 named pools over
[T0 ; T0 + 12 d) by step1.collect (resumable STATE per pool); a truncated response may be re-read ONCE (charged, logged);
any other incident = STOP (pages already written are kept, their counts published). NO decision, position or return is
computed here: the verdict belongs to the audited code (R01 g23five) after this collection.
Usage: python -B g23_collect.py --pkg <pkg> --u2 <U2.json> --out <NEW DIR> --sheet-sha <hex> --verdict-code-sha <hex>
       --authorization <file>"""
import argparse
import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, step1

ENDPOINT = 'https://beta.helius-rpc.com/'
U2_SHA256 = '3ca0260aa187f8df99ab422fc74fbbb1da4404d6f6b175548270ade3e731a963'
POOLS = ('AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr',
         'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh', 'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')
POOLS_SHA256 = '812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80'   # sha256 of the 4 addresses joined by newlines (R02 835d648e)
T0 = 1795515686                                      # 24/11/2026 10:21:26Z (U-2 retry, never read)
D_DAYS = 12                                          # R02 835d648e / 4e08d2a2
CAP = 32_340                                         # 98 % of 33 000 (R04-1) = budget.G23_CAP (0.2.8)
RETRY_ON_TRUNCATED = 1                               # R04-1: one re-read of a truncated response
RESULT = 'G23_COLLECT_RESULT.json'
# The three texts anchored in 0.2.7 (B/C, T1/T2, T2 bis) do NOT cover this collection (T1/T2: "aucune nouvelle collecte
# importante"). The run needs an owner text for G2-3, written in the R03 session, anchored by R02, whose sha is set here
# AND added to rpc.AUTHORIZED_TEXT_SHA256 by an audited 0.2.8. None = no run possible (refused before any call).
G23_TEXT_SHA256 = '3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b'   # owner 24/11 22:29:08Z, R02 a5e8f770
NOT_COVERING = frozenset({'e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1',
                          'b75e657a60a0de335906e091936c93ba707b639a3b9ca5fc56c7623142a063f9',
                          'cae25a3c1f07c3daafef18131d6ace13c8604b6d847f00fbaed69fe451c0967d'})


def sha_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _retry_client():
    spec = importlib.util.spec_from_file_location('activity_l2', Path(__file__).resolve().parent / 'activity_l2.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RetryOnceClient                        # the audited wrapper (activity_l2 9b2c0487), reused, not copied


def main(argv=None, now=None):
    p = argparse.ArgumentParser()
    for k in ('--pkg', '--u2', '--out', '--authorization'):
        p.add_argument(k, type=Path, required=True)
    p.add_argument('--sheet-sha', required=True)
    p.add_argument('--verdict-code-sha', required=True)
    a = p.parse_args(argv)
    end = T0 + D_DAYS * step1.DAY
    now = int(time.time()) if now is None else now
    if B.G23_CAP != CAP:
        raise SystemExit('package_without_g23_stage')  # needs cpmmpilot 0.2.8 (stage 'g23', R02 20:42Z)
    if now < end:
        raise SystemExit('window_not_closed')         # never read the window before T0 + D
    for h in (a.sheet_sha, a.verdict_code_sha):
        if not re.fullmatch('[0-9a-f]{64}', h):
            raise SystemExit('anchor_sha_must_be_64_hex')
    auth = sha_of(a.authorization)
    if G23_TEXT_SHA256 is None or auth in NOT_COVERING or auth != G23_TEXT_SHA256:
        raise SystemExit('g23_owner_text_not_anchored')
    if a.out.exists():
        raise SystemExit('out_exists')
    if len(POOLS) != 4 or hashlib.sha256('\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:
        raise SystemExit('pools_or_t0_mismatch')
    if sha_of(a.u2) != U2_SHA256:
        raise SystemExit('u2_not_anchored')
    doc = json.loads(a.u2.read_bytes())
    sel = [r for r in doc['selected'] if r['pool'] in POOLS]
    if sorted(r['pool'] for r in sel) != sorted(POOLS) or doc['t0_time'] != T0:
        raise SystemExit('pools_or_t0_mismatch')
    a.out.mkdir(parents=True)
    live = rpc.LiveRpc(ENDPOINT, authorization_file=a.authorization, timeout_s=120)
    inner = rpc.Client(live, B.PilotBudget(a.out / 'ledger_g23.json', stage='g23', max_credits=CAP),
                       a.out / 'calls_g23.jsonl')
    client = _retry_client()(inner, RETRY_ON_TRUNCATED)
    res = dict(schema='g23-collect-v1', t0=T0, window=[T0, end], pools=list(POOLS), cap=CAP,
               sheet_sha256=a.sheet_sha, verdict_code_sha256=a.verdict_code_sha, driver_sha256=sha_of(__file__),
               authorization_sha256=live.authorization_sha256)
    try:
        step1.collect(client, a.out / 'window', list(POOLS), start_time=T0, end_time=end, phase='window')
        res.update(verdict_run='DONE', tx_format=step1.require_tx_format(a.out / 'window', 'window', sel))
    except Exception as exc:                          # STOP: no fallback; pages already written are kept
        res.update(verdict_run='STOP', error=type(exc).__name__, tag=str(exc)[:120],
                   error_text=getattr(exc, 'error_text', None))
    states = {}
    root = a.out / 'window' / 'collect' / 'window'
    for pool in POOLS:                                # every pool is published; one never reached reads 0 / not done
        st = root / pool / 'STATE.json'
        s = json.loads(st.read_text()) if st.exists() else dict(pages=0, transactions=0, done=False)
        states[pool] = dict(pages=s['pages'], transactions=s['transactions'], done=s['done'])
    res.update(states=states,
               budget=client.budget.snapshot(), retries=client.retries)
    (a.out / RESULT).write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: res.get(k) for k in ('verdict_run', 'states', 'budget', 'retries', 'error', 'tag')}))


if __name__ == '__main__':
    main()
