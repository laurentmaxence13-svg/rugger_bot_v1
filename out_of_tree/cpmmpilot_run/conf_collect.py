"""Collection of the CONFIRMATION window (decision R04-8, 24/11 23:08Z), cpmmpilot 0.2.8.1. Written OFFLINE, NOT run.
Runs ONLY if at least one pilot (C-169 G2-3 or C-170 N1) returns GO_PILOTE on 06/12, ONLY after the confirmation window
is closed (now >= T1 + 12 d), and ONLY with an owner text for this collection anchored by R02 (CONF_TEXT_SHA256, None
until then; the G2-3 text 3d6999ec covers the pilot window only and is refused here).
Mode: c169 -> the 4 G2-3 pools; c170 -> the 3 N1 pools; both -> their union (the 4 G2-3 pools). Duration (R02 23:13Z):
12 days for C-170; D_c for C-169 (formula of sheet ccf6ac75, 12 <= D_c <= 30), passed as --d-days and published; with
'both' the 4 pools are collected over D_c, which covers C-170's 12 days (the verdict code trims). One cap for the whole
collection, whatever the mode: P credits at 98 % (stage 'g23' of 0.2.8, NEW ledger). P = the cap of the owner's
confirmation text, computed and anchored by R02 (erratum C-169: P = ceil(1.25 x c_j x D_c*), or 33 000 if kept), --cap. Raw GTFA pages over
[T1 ; T1 + D), T1 = end of the pilot window; a truncated response may be re-read ONCE; any other incident = STOP,
pages kept and counts published. No decision, position or return is computed here.
Usage: python -B conf_collect.py --mode c169|c170|both --d-days <D> --cap <P> --u2 <U2.json> --out <NEW DIR> --sheet-sha <hex> [--sheet-sha <hex>]
       --verdict-code-sha <hex> [--verdict-code-sha <hex>] --pilot-result <GO result json> [...] --authorization <file>"""
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
G23_POOLS = ('AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr',
             'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh', 'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')
N1_POOLS = ('AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh',
            'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')       # n1rot 6b9b02a9, list c72bd586
G23_POOLS_SHA256 = '812d311b152b7127eedd4146508fdbdb5fc305c15d412e2d4f95e0ab690aca80'
N1_LIST_SHA256 = 'c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da'   # = n1rot list_sha256 (6b9b02a9)
T0 = 1795515686                                      # 24/11/2026 10:21:26Z
D_DAYS = 12                                          # pilot window, and C-170's confirmation window
DC_MIN, DC_MAX = 12, 30                              # C-169's D_c bounds (R02 23:13Z, sheet ccf6ac75)
T1 = T0 + D_DAYS * 86_400                            # 06/12/2026 10:21:26Z, end of the pilot window
G23_CAP = 32_340                                     # 0.2.8 stage constant, checked as a package guard only
HARD_STOP_PCT = 98                                   # hard stop at 98 % of the owner's cap P (floor)
RETRY_ON_TRUNCATED = 1
RESULT = 'CONF_COLLECT_RESULT.json'
CONF_TEXT_SHA256 = None                              # owner text for the confirmation collection, anchored by R02
NOT_COVERING = frozenset({'e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1',
                          'b75e657a60a0de335906e091936c93ba707b639a3b9ca5fc56c7623142a063f9',
                          'cae25a3c1f07c3daafef18131d6ace13c8604b6d847f00fbaed69fe451c0967d',
                          '3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b'})
MODES = {'c169': G23_POOLS, 'c170': N1_POOLS, 'both': G23_POOLS}
PILOT_OF_MODE = {'c169': {'C-169'}, 'c170': {'C-170'}, 'both': {'C-169', 'C-170'}}


def _pool_sha(pools):
    return hashlib.sha256('\n'.join(pools).encode()).hexdigest()


def sha_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _retry_client():
    spec = importlib.util.spec_from_file_location('activity_l2', Path(__file__).resolve().parent / 'activity_l2.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RetryOnceClient


def go_pilots(paths):
    """The pilots whose audited verdict file says GO_PILOTE ({'pilot': 'C-169'|'C-170', 'verdict': ...})."""
    go = set()
    for path in paths:
        doc = json.loads(Path(path).read_bytes())
        if doc.get('pilot') not in ('C-169', 'C-170'):
            raise SystemExit('pilot_result_unknown_pilot')
        if doc.get('verdict') == 'GO_PILOTE':
            go.add(doc['pilot'])
    return go


def main(argv=None, now=None):
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=sorted(MODES), required=True)
    p.add_argument('--d-days', type=int, required=True)
    p.add_argument('--cap', type=int, required=True)    # P, the owner's cap in credits (anchored by R02)
    for k in ('--pkg', '--u2', '--out', '--authorization'):
        p.add_argument(k, type=Path, required=True)
    p.add_argument('--pilot-result', type=Path, action='append', required=True)
    p.add_argument('--sheet-sha', action='append', required=True)
    p.add_argument('--verdict-code-sha', action='append', required=True)
    a = p.parse_args(argv)
    if a.mode == 'c170' and a.d_days != D_DAYS:
        raise SystemExit('c170_window_is_12_days')
    if a.mode != 'c170' and not DC_MIN <= a.d_days <= DC_MAX:
        raise SystemExit('d_c_out_of_12_30')
    if not 1_000 <= a.cap <= 1_000_000:
        raise SystemExit('cap_out_of_range')
    cap = a.cap * HARD_STOP_PCT // 100
    end = T1 + a.d_days * step1.DAY
    now = int(time.time()) if now is None else now
    if B.G23_CAP != G23_CAP:
        raise SystemExit('package_without_g23_stage')
    if now < end:
        raise SystemExit('window_not_closed')         # never read the confirmation window before T1 + D
    for h in a.sheet_sha + a.verdict_code_sha:
        if not re.fullmatch('[0-9a-f]{64}', h):
            raise SystemExit('anchor_sha_must_be_64_hex')
    if PILOT_OF_MODE[a.mode] - go_pilots(a.pilot_result):
        raise SystemExit('mode_needs_a_go_pilote_for_each_confirmed_pilot')
    auth = sha_of(a.authorization)
    if CONF_TEXT_SHA256 is None or auth in NOT_COVERING or auth != CONF_TEXT_SHA256:
        raise SystemExit('conf_owner_text_not_anchored')
    pools = MODES[a.mode]
    if _pool_sha(G23_POOLS) != G23_POOLS_SHA256 or _pool_sha(N1_POOLS) != N1_LIST_SHA256 or \
            not set(N1_POOLS) <= set(G23_POOLS):
        raise SystemExit('pools_mismatch')
    if a.out.exists():
        raise SystemExit('out_exists')
    if sha_of(a.u2) != U2_SHA256:
        raise SystemExit('u2_not_anchored')
    doc = json.loads(a.u2.read_bytes())
    sel = [r for r in doc['selected'] if r['pool'] in pools]
    if sorted(r['pool'] for r in sel) != sorted(pools) or doc['t0_time'] != T0:
        raise SystemExit('pools_mismatch')
    a.out.mkdir(parents=True)
    live = rpc.LiveRpc(ENDPOINT, authorization_file=a.authorization, timeout_s=120)
    inner = rpc.Client(live, B.PilotBudget(a.out / 'ledger_conf.json', stage='g23', max_credits=cap),
                       a.out / 'calls_conf.jsonl')
    client = _retry_client()(inner, RETRY_ON_TRUNCATED)
    res = dict(schema='conf-collect-v1', mode=a.mode, d_days=a.d_days, t1=T1, window=[T1, end], pools=list(pools), owner_cap=a.cap, cap=cap,
               sheet_sha256=a.sheet_sha, verdict_code_sha256=a.verdict_code_sha, driver_sha256=sha_of(__file__),
               pilot_results_sha256=[sha_of(x) for x in a.pilot_result], authorization_sha256=live.authorization_sha256)
    try:
        step1.collect(client, a.out / 'window', list(pools), start_time=T1, end_time=end, phase='window')
        res.update(verdict_run='DONE', tx_format=step1.require_tx_format(a.out / 'window', 'window', sel))
    except Exception as exc:                          # STOP: no fallback; pages already written are kept
        res.update(verdict_run='STOP', error=type(exc).__name__, tag=str(exc)[:120],
                   error_text=getattr(exc, 'error_text', None))
    states = {}
    root = a.out / 'window' / 'collect' / 'window'
    for pool in pools:
        st = root / pool / 'STATE.json'
        s = json.loads(st.read_text()) if st.exists() else dict(pages=0, transactions=0, done=False)
        states[pool] = dict(pages=s['pages'], transactions=s['transactions'], done=s['done'])
    res.update(states=states, budget=client.budget.snapshot(), retries=client.retries)
    (a.out / RESULT).write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: res.get(k) for k in ('verdict_run', 'mode', 'states', 'budget', 'retries', 'error', 'tag')}))



if __name__ == '__main__':
    main()
