"""Driver of STEP 1, part A2 RETRY (R02 d9b63ddf (a) + erratum f2e62c72), cpmmpilot 0.2.5 (v1 transactions). ONE run
after the -32015 STOP of 24/11 11:46:23Z (STEP1A2_RESULT.json, sha checked); any new error = FINAL STOP of step 1.
Format guard on every pre transaction before the timelines (STOP_TX_FORMAT, no sheet); counts by version published.
Based on the audited A2 driver (21cff5e5): One run only, after R02 anchored the
count of part A (COUNT_24H.json) and its point-(2) result.
(3) pre-T0 collection [T0 - 7 d ; T0) (GTFA full) of the 24 anchored pools and trigger counts of R-CP1 and B1, no outcome;
    then D by R02's rule (note e294655a, step1.d_rule); UNDERPOWERED -> STOP before the sheets, no trial, owner referred;
    then the WINDOW BUDGET check (R02 K-1, 24/11 11:20Z): projected = credits used + ceil(pre x D / 7) > 49 000 -> STOP
    before the sheets, no trial, owner referred (the hard stop must never cut the window after trials 169/170 are consumed);
(4) the two freeze sheets (list, T0, D, cut_time, codes, d_rule), then STOP: R02 anchors them before any window read.
Resumes the ledger of part A (stage 'step1', hard stop 49 000). Prints only shas and counts; never the endpoint or a key.
Usage: python -B step1_a2r.py --pkg <pkg> --u2 <U2.json> --anchored-u2-sha <hex> --run <part-A dir> --anchored-count-sha <hex>"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, step1
from cpmmpilot.rehearse import code_sha

ENDPOINT = 'https://beta.helius-rpc.com/'          # admitted by R02 (07:20Z); the key is injected by the proxy
PRIOR_A2_RESULT_SHA256 = '58a5e5472644d531b0abd9a9e57b4bdcddfc4d05bc9c75536238414ae8786e9d'   # the -32015 STOP
RESULT = 'STEP1A2R_RESULT.json'


def sha_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def window_budget(credits_before_pre, credits_after_pre, d_days, hard_stop=B.STEP1_HARD_STOP):
    """R02 K-1: the window [T0 ; T0 + D) is priced at the MEASURED cost of the 7 pre days, scaled to D."""
    pre = credits_after_pre - credits_before_pre
    projected = credits_after_pre + -(-pre * d_days // 7)
    return dict(pre_credits=pre, projected_credits=projected, hard_stop=hard_stop, margin=hard_stop - projected,
                stop=projected > hard_stop)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pkg', type=Path, required=True)
    p.add_argument('--u2', type=Path, required=True)
    p.add_argument('--anchored-u2-sha', required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--anchored-count-sha', required=True)
    a = p.parse_args()
    if (a.run / RESULT).exists():
        raise SystemExit('a2_retry_already_run')
    if sha_of(a.run / 'STEP1A2_RESULT.json') != PRIOR_A2_RESULT_SHA256:
        raise SystemExit('prior_a2_result_not_the_anchored_stop')
    if (a.run / 'step1' / 'collect' / 'pre').exists():
        raise SystemExit('pre_collection_already_started')
    for h in (a.anchored_u2_sha, a.anchored_count_sha):
        if not re.fullmatch('[0-9a-f]{64}', h):
            raise SystemExit('anchored_sha_must_be_64_hex')
    if sha_of(a.u2) != a.anchored_u2_sha:
        raise SystemExit('u2_not_anchored')
    if sha_of(a.run / 'COUNT_24H.json') != a.anchored_count_sha:
        raise SystemExit('count_not_anchored')
    if json.loads((a.run / 'STEP1A_RESULT.json').read_text()).get('verdict') != 'POINT2_PASSED_AWAIT_R02_ANCHOR':
        raise SystemExit('point2_not_passed')
    doc = json.loads(a.u2.read_bytes())
    cnt = json.loads((a.run / 'COUNT_24H.json').read_text())
    if cnt['point2']['stop']:
        raise SystemExit('point2_stop')
    selected, pools, t0 = doc['selected'], [r['pool'] for r in doc['selected']], doc['t0_time']
    live = rpc.LiveRpc(ENDPOINT, authorization_file=a.pkg / 'AUTORISATION_B_C_v1_3.txt', timeout_s=120)
    client = rpc.Client(live, B.PilotBudget(a.run / 'ledger_step1.json', stage='step1', max_credits=B.STEP1_HARD_STOP),
                        a.run / 'calls_step1.jsonl')
    res = dict(u2_sha256=a.anchored_u2_sha, count_sha256=a.anchored_count_sha, t0_time=t0, credits_before=client.budget.credits)
    try:
        step1.collect(client, a.run / 'step1', pools, start_time=t0 - 7 * step1.DAY, end_time=t0, phase='pre')
        res.update(tx_format=step1.require_tx_format(a.run / 'step1', 'pre', selected))   # R02 caf86646 (d)
        trig = step1.trigger_counts(a.run / 'step1', selected, t0_time=t0, t0_slot=doc['t0_slot'])
        rule = step1.d_rule(trig['rcp1'], cnt['d_max_days'])
        res.update(triggers=dict(rcp1=trig['rcp1']['triggers'], b1=trig['b1']['triggers'],
                                 skipped=trig['skipped_transactions']), d_rule=rule)
        wb = window_budget(res['credits_before'], client.budget.credits, rule['d_days'])
        res.update(window_budget=wb)
        if rule['power_stop'] == 'UNDERPOWERED_DECLARED_OWNER_DECIDES':
            res.update(verdict='STOP_UNDERPOWERED_NO_TRIAL_OWNER_REFERRED')
        elif wb['stop']:
            res.update(verdict='STOP_WINDOW_BUDGET_NO_TRIAL_OWNER_REFERRED')
        else:
            sheets = step1.freeze_sheets(a.run / 'step1', u2_doc=doc, count_doc=cnt, triggers=trig, d_days=rule['d_days'],
                                         code_sha=code_sha(), d_rule=rule)
            res.update(verdict='SHEETS_AWAIT_R02_ANCHOR', sheets=sheets,
                       window=[t0, t0 + rule['d_days'] * step1.DAY], cut_time=t0 + rule['d_days'] * step1.DAY // 2)
    except Exception as exc:                                   # STOP, no fallback: type and tag only
        res.update(verdict='STOP_TX_FORMAT' if isinstance(exc, step1.TxFormatStop) else 'STOP',
                   error=type(exc).__name__, tag=str(exc)[:120],
                   error_text=getattr(exc, 'error_text', None))      # redacted by rpc (R02 f2e62c72 (c))
    res.update(budget=client.budget.snapshot())
    (a.run / RESULT).write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(res, default=str))


if __name__ == '__main__':
    main()
