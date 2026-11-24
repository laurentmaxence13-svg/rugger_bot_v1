"""T2 SECOND MEASURE (driver v2, cpmmpilot 0.2.7) after the STOP of 24/11 18:22:22Z (truncated HTTP response, 186 credits,
no count kept). REQUIRES a new owner clause (not yet given) and R02's PASS. Differences with the audited v1 (6b51b618):
counts written after EACH pool (PARTIAL_COUNTS.json) and published on a STOP; the cap is CUMULATIVE over the two
measures (T2_CAP - credits of the stopped run, read from its ledger, sha checked).
Original description (v1): T2 (owner 24/11 18:00:36Z, text b75e657a; R02 method 18:01Z): ONE measure of the 24 h activity of the 259 pools of the
anchored list L, cpmmpilot 0.2.6. getSignaturesForAddress only (step1.count_24h, limit 1 000): NO transaction is read
and NO signature is written, only counts per pool. Own NEW ledger (stage 't2', cap 1 470). First incident = STOP.
N50 = pools with >= 50 signatures over [T0' - 24 h ; T0'). Groups: 24 valid (U2), 20 known invalid (tested at the
creation, U-2 time 2), 215 untested. N_eff = active valid + floor(active untested x 24/44); low / high with the
Clopper-Pearson 95 % bounds 0.388 / 0.696. Verdict (R02): INFAISABLE if N_eff high < 80, U2BIS_A_PROPOSER if N_eff low
>= 80, ZONE_INCERTAINE otherwise.
Usage: python -B activity_l.py --pkg <pkg> --list-l <LIST_L.json> --u2 <U2.json> --gtfa-dir <dir of the 44 pages> --out <NEW>"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, step1, u2 as U2

ENDPOINT = 'https://beta.helius-rpc.com/'          # admitted by R02 (07:20Z); the key is injected by the proxy
LIST_L_SHA256 = 'c96353b9f3c0bdb25fd1b7c8af85cf0c4efd66e84480d7850252b85d8a7d8ff3'
SHA_L = '110dabe138a2bacc97e630db29ddc5c363f5e99a738172d73373af01fd076cbd'
U2_SHA256 = '3ca0260aa187f8df99ab422fc74fbbb1da4404d6f6b175548270ade3e731a963'
AUTH_FILE = 'AUTORISATION_T1_T2.txt'
RESULT = 'ACTIVITY_RESULT.json'
PARTIAL = 'PARTIAL_COUNTS.json'
PRIOR_RESULT_SHA256 = '1773d01f615792a8c485746b167e0c1db5c90a0da544e1fac1cb7171b7814635'    # v1 STOP of 18:22:22Z
PRIOR_LEDGER_SHA256 = '06533afb9023157342d6266bebda222719e6d3a047123aedbe3e13236ee027e8'    # 186 credits
N50_THRESHOLD = 50
P_POINT, P_LOW, P_HIGH = (24, 44), 0.388, 0.696
VERDICT_LIMIT = 80


def sha_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def partition(list_l, u2_doc, gtfa_names):
    """(valid, invalid, untested) of L. Tested = the first 44 of the frozen permutation of L, cross-checked with the 44
    creation pages; valid = the 24 of U2 (all tested); invalid = tested - valid."""
    order = U2.permutation(list_l, SHA_L)
    tested = order[:u2_doc['tested']]
    if set(tested) != set(gtfa_names) or len(tested) != 44:
        raise SystemExit('tested_set_mismatch')
    valid = [r['pool'] for r in u2_doc['selected']]
    if len(valid) != 24 or not set(valid) <= set(tested):
        raise SystemExit('valid_not_in_tested')
    invalid = [p for p in tested if p not in set(valid)]
    untested = [r['pool'] for r in list_l if r['pool'] not in set(tested)]
    if len(invalid) != 20 or len(untested) != 215:
        raise SystemExit('partition_sizes')
    return valid, invalid, untested


def n_eff(per_pool, valid, invalid, untested, threshold=N50_THRESHOLD):
    active = {p for p, n in per_pool.items() if n >= threshold}
    av, ai, au = (len(active & set(g)) for g in (valid, invalid, untested))
    point = av + au * P_POINT[0] // P_POINT[1]
    low = av + int(au * P_LOW)
    high = av + int(au * P_HIGH)
    verdict = ('INFAISABLE' if high < VERDICT_LIMIT else 'U2BIS_A_PROPOSER' if low >= VERDICT_LIMIT
               else 'ZONE_INCERTAINE')
    return dict(threshold=threshold, n50_raw=len(active), active_valid=av, active_invalid=ai, active_untested=au,
                n_eff_point=point, n_eff_low=low, n_eff_high=high, p=dict(point='24/44', low=P_LOW, high=P_HIGH),
                verdict=verdict, verdict_limit=VERDICT_LIMIT)


DESCRIPTIVE_THRESHOLDS = (180, 360, 1000)              # R02 18:05Z (asked by R04): DESCRIPTIVE ONLY, never a verdict


def descriptive_thresholds(per_pool, valid, invalid, untested):
    out = {}
    for t in DESCRIPTIVE_THRESHOLDS:
        d = n_eff(per_pool, valid, invalid, untested, threshold=t)
        d.pop('verdict')
        d['non_decisionnel'] = True
        out[str(t)] = d
    return out


def main():
    p = argparse.ArgumentParser()
    for k in ('--pkg', '--list-l', '--u2', '--gtfa-dir', '--out', '--prior-result', '--prior-ledger'):
        p.add_argument(k, type=Path, required=True)
    a = p.parse_args()
    if (a.out / RESULT).exists():
        raise SystemExit('t2_already_run')
    if a.out.exists():
        raise SystemExit('out_exists')
    if sha_of(a.list_l) != LIST_L_SHA256 or sha_of(a.u2) != U2_SHA256:
        raise SystemExit('inputs_not_anchored')
    if sha_of(a.prior_result) != PRIOR_RESULT_SHA256 or sha_of(a.prior_ledger) != PRIOR_LEDGER_SHA256:
        raise SystemExit('prior_t2_not_the_anchored_stop')
    prior_credits = json.loads(a.prior_ledger.read_bytes())['credits']
    cap = B.T2_CAP - prior_credits
    ldoc = json.loads(a.list_l.read_bytes())
    lst = ldoc['list']
    if rpc.sha(lst) != SHA_L or len(lst) != 259:
        raise SystemExit('list_l_not_anchored')
    u2_doc = json.loads(a.u2.read_bytes())
    names = [f.name[len('creation_'):-len('.json.gz')] for f in sorted(a.gtfa_dir.glob('creation_*.json.gz'))]
    valid, invalid, untested = partition(lst, u2_doc, names)
    a.out.mkdir(parents=True)
    pools = [r['pool'] for r in lst]                      # exactly the 259 of L, in the order of L
    live = rpc.LiveRpc(ENDPOINT, authorization_file=a.pkg / AUTH_FILE, timeout_s=120)
    client = rpc.Client(live, B.PilotBudget(a.out / 'ledger_t2.json', stage='t2', max_credits=cap),
                        a.out / 'calls_t2.jsonl')
    t0p = int(time.time())
    res = dict(schema='t2-activity-v1', t0_prime=t0p, window=[t0p - step1.DAY, t0p], list_l_sha256=LIST_L_SHA256,
               sha_l=SHA_L, u2_sha256=U2_SHA256, driver_sha256=sha_of(__file__),
               groups=dict(valid=len(valid), invalid=len(invalid), untested=len(untested)),
               prior_credits=prior_credits, cap_this_run=cap)
    try:
        cnt = step1.count_24h(client, pools, t0_time=t0p, checkpoint=a.out / PARTIAL)
        per_pool = cnt['per_pool']
        res.update(verdict_run='DONE', per_pool=per_pool, mean_signatures=cnt['r_hat'],
                   n50=n_eff(per_pool, valid, invalid, untested),
                   descriptive_thresholds=descriptive_thresholds(per_pool, valid, invalid, untested),
                   group_of={pl: ('valid' if pl in set(valid) else 'invalid' if pl in set(invalid) else 'untested')
                             for pl in pools})
    except Exception as exc:                               # first incident: STOP, no retry, partial published
        res.update(verdict_run='STOP', error=type(exc).__name__, tag=str(exc)[:120],
                   error_text=getattr(exc, 'error_text', None))
        if (a.out / PARTIAL).exists():                     # the partial is PUBLISHED, never used for a verdict
            part = json.loads((a.out / PARTIAL).read_text())
            res.update(partial=dict(per_pool=part['per_pool'], pools_done=part['pools_done'],
                                    pools_total=part['pools_total'], non_decisionnel=True))
    res.update(budget=client.budget.snapshot())
    (a.out / RESULT).write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: res.get(k) for k in ('verdict_run', 'n50', 'budget', 'error', 'tag', 't0_prime')}, default=str))


if __name__ == '__main__':
    main()
