"""PAPER live-simulation collection (decision R04-10, owner directive 25/11 08:39:28Z), cpmmpilot 0.2.9 (stage 'livesim').
Written OFFLINE, NOT run. One invocation = ONE bounded pass; the 24 h are covered by repeated passes (wake-ups), each
resuming from files on disk (STATE per pool and chunk, cumulative ledger, CONFIG, PASSES.jsonl, STOP marker).
  --phase qualify : for the anchored ordered universe (holders then replacements), the oldest transaction of each pool
                    not already 'valid' (GTFA asc limit 1) is checked by the FROZEN u2.creation_check (age >= 7 d at
                    T_start, no LaunchLab, Initialize at depth 1); the first K valid in order are kept (QUALIFIED.json).
  --phase history : raw GTFA pages of the qualified pools over [T_start - 7 d ; T_start)            (phase 'pre')
  --phase poll    : raw GTFA pages over [edge ; min(now - 120 s, T_start + 24 h)), one chunk per pass ('live_NNN');
                    an unfinished chunk is resumed first, never re-cut.
A truncated response may be re-read ONCE (audited RetryOnceClient); any other incident = STOP marker, no later pass.
Forbidden pools (the 4 pilot pools, 2yLFom) are refused before any call. No decision, position or return is computed.
Usage: python -B livesim_collect.py --phase qualify|history|poll --universe <LIVESIM_UNIVERSE.json>
       --out <DIR> --t-start <unix> --cap <P> --authorization <file>"""
import argparse
import hashlib
import importlib.util
import json
import time
from pathlib import Path

from cpmmpilot import budget as B
from cpmmpilot import rpc, step1, u2
from cpmmpilot.store import write_gz_page

ENDPOINT = 'https://beta.helius-rpc.com/'
UNIVERSE_LIST_SHA256 = '5c4fefb670cf747b2af90d50bceb0ea4e50cd9573927f92fcd246056a5b7ea68'
FORBIDDEN = frozenset({'AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'Gms3MaNaz9mFKWwh3dvrHTF7f6FWstcPis21YYNPq3Fr',
                       'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh', 'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A',
                       '2yLFomCTck19BqK7EzJqsUWXPWP3uWGNBSrfKvJzNzp2'})
K = 8
HISTORY_S = 7 * 86_400
LIVE_S = 24 * 3_600
MARGIN_S = 120
CAP_MAX = 20_000
HARD_STOP_PCT = 98
RETRY_ON_TRUNCATED = 1
LIVESIM_TEXT_SHA256 = None                           # owner text for this collection, written in the R03 session, anchored
NOT_COVERING = frozenset({'e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1',
                          'b75e657a60a0de335906e091936c93ba707b639a3b9ca5fc56c7623142a063f9',
                          'cae25a3c1f07c3daafef18131d6ace13c8604b6d847f00fbaed69fe451c0967d',
                          '3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b'})


class LiveSimStop(SystemExit):
    pass


def sha_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def list_sha(pools):
    return hashlib.sha256('\n'.join(pools).encode()).hexdigest()


def _retry_client():
    spec = importlib.util.spec_from_file_location('activity_l2', Path(__file__).resolve().parent / 'activity_l2.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RetryOnceClient


def _read(path):
    return json.loads(Path(path).read_text())


def _write(path, doc):
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + '\n')
    tmp.replace(path)


def universe_rows(path):
    doc = _read(path)
    rows = sorted(doc['ordered'], key=lambda r: r['rank'])
    pools = [r['pool'] for r in rows]
    if list_sha(pools) != UNIVERSE_LIST_SHA256 or doc.get('ordered_list_sha256') != UNIVERSE_LIST_SHA256:
        raise LiveSimStop('universe_not_anchored')
    if FORBIDDEN & set(pools) or len(set(pools)) != len(pools):
        raise LiveSimStop('forbidden_or_duplicate_pool')
    return rows


def _check_config(out, t_start, cap):
    cfg_path = out / 'CONFIG.json'
    cfg = dict(t_start=t_start, cap=cap, universe_list_sha256=UNIVERSE_LIST_SHA256, k=K)
    if cfg_path.exists():
        if _read(cfg_path) != cfg:
            raise LiveSimStop('config_differs_from_first_pass')
    else:
        out.mkdir(parents=True, exist_ok=True)
        _write(cfg_path, cfg)


def _qualified(out):
    path = out / 'QUALIFIED.json'
    if not path.exists():
        raise LiveSimStop('qualify_first')
    doc = _read(path)
    if list_sha(doc['pools']) != doc['list_sha256'] or FORBIDDEN & set(doc['pools']):
        raise LiveSimStop('qualified_list_corrupt')
    return doc


def phase_qualify(client, out, rows, t_start):
    if (out / 'QUALIFIED.json').exists():
        raise LiveSimStop('already_qualified')
    kept, tested = [], []
    for r in rows:
        if len(kept) == K:
            break
        if r['group'] == 'valid':
            kept.append(r['pool'])
            tested.append(dict(pool=r['pool'], valid=True, reason='already_valid_u2'))
            continue
        page = client.call('getTransactionsForAddress', [r['pool'], dict(
            transactionDetails='full', sortOrder='asc', limit=1, encoding='json',
            maxSupportedTransactionVersion=step1.MAX_TX_VERSION)])
        write_gz_page(out / 'raw' / ('creation_%s.json.gz' % r['pool']), page)
        ok, why = u2.creation_check((page.get('data') or [None])[0], t0_time=t_start)
        tested.append(dict(pool=r['pool'], valid=ok, reason=why))
        if ok:
            kept.append(r['pool'])
    doc = dict(pools=kept, list_sha256=list_sha(kept), tested=tested, k=len(kept), k_target=K,
               complete=len(kept) == K)
    _write(out / 'QUALIFIED.json', doc)
    return doc


def phase_history(client, out, pools, t_start, sel):
    step1.collect(client, out, pools, start_time=t_start - HISTORY_S, end_time=t_start, phase='pre')
    return dict(tx_format=step1.require_tx_format(out, 'pre', sel))


def phase_poll(client, out, pools, t_start, now, sel):
    polls_path = out / 'POLLS.json'
    polls = _read(polls_path) if polls_path.exists() else []
    if polls and not polls[-1]['done']:
        chunk = polls[-1]                              # resume the unfinished chunk, never re-cut its window
    else:
        edge = polls[-1]['window'][1] if polls else t_start
        stop_at = min(now - MARGIN_S, t_start + LIVE_S)
        if stop_at <= edge:
            return dict(nothing_to_collect=True, edge=edge)
        chunk = dict(name='live_%03d' % len(polls), window=[edge, stop_at], done=False)
        polls.append(chunk)
        _write(polls_path, polls)
    step1.collect(client, out, pools, start_time=chunk['window'][0], end_time=chunk['window'][1], phase=chunk['name'])
    fmt = step1.require_tx_format(out, chunk['name'], sel)
    chunk['done'] = True
    _write(polls_path, polls)
    return dict(chunk=chunk['name'], window=chunk['window'], tx_format=fmt,
                live_complete=chunk['window'][1] >= t_start + LIVE_S)


def main(argv=None, now=None):
    p = argparse.ArgumentParser()
    p.add_argument('--phase', choices=('qualify', 'history', 'poll'), required=True)
    for k in ('--pkg', '--universe', '--out', '--authorization'):
        p.add_argument(k, type=Path, required=True)
    p.add_argument('--t-start', type=int, required=True)
    p.add_argument('--cap', type=int, required=True)
    a = p.parse_args(argv)
    now = int(time.time()) if now is None else now
    if 'livesim' not in B.STAGES:
        raise LiveSimStop('package_without_livesim_stage')
    if not 1_000 <= a.cap <= CAP_MAX:
        raise LiveSimStop('cap_out_of_range')
    if a.t_start > now or a.phase == 'qualify' and a.t_start < now - 3_600:
        raise LiveSimStop('t_start_must_be_past_and_within_the_last_hour_at_qualify')
    auth = sha_of(a.authorization)
    if LIVESIM_TEXT_SHA256 is None or auth in NOT_COVERING or auth != LIVESIM_TEXT_SHA256:
        raise LiveSimStop('livesim_owner_text_not_anchored')
    if (a.out / 'STOP.json').exists():
        raise LiveSimStop('stopped_earlier_no_further_pass')
    rows = universe_rows(a.universe)
    _check_config(a.out, a.t_start, a.cap)
    pools = sel = None
    if a.phase != 'qualify':
        q = _qualified(a.out)
        pools = q['pools']
        by = {r['pool']: r for r in rows}
        sel = [dict(pool=x, base_mint=by[x]['base_mint']) for x in pools]
        if a.phase == 'history' and (a.out / 'HISTORY_DONE.json').exists():
            raise LiveSimStop('history_already_done')
        if a.phase == 'poll' and not (a.out / 'HISTORY_DONE.json').exists():
            raise LiveSimStop('history_first')
    cap = a.cap * HARD_STOP_PCT // 100
    live = rpc.LiveRpc(ENDPOINT, authorization_file=a.authorization, timeout_s=120)
    inner = rpc.Client(live, B.PilotBudget(a.out / 'ledger_livesim.json', stage='livesim', max_credits=cap),
                       a.out / 'calls_livesim.jsonl')
    client = _retry_client()(inner, RETRY_ON_TRUNCATED)
    rec = dict(phase=a.phase, at=now, driver_sha256=sha_of(__file__), authorization_sha256=live.authorization_sha256)
    try:
        if a.phase == 'qualify':
            rec.update(result=phase_qualify(client, a.out, rows, a.t_start))
        elif a.phase == 'history':
            rec.update(result=phase_history(client, a.out, pools, a.t_start, sel))
            _write(a.out / 'HISTORY_DONE.json', dict(window=[a.t_start - HISTORY_S, a.t_start]))
        else:
            rec.update(result=phase_poll(client, a.out, pools, a.t_start, now, sel))
        rec.update(verdict_run='DONE')
    except Exception as exc:                          # STOP: no fallback; later passes refused; pages kept
        rec.update(verdict_run='STOP', error=type(exc).__name__, tag=str(exc)[:120],
                   error_text=getattr(exc, 'error_text', None))
        _write(a.out / 'STOP.json', rec)
    rec.update(budget=client.budget.snapshot(), retries=client.retries)
    with open(a.out / 'PASSES.jsonl', 'a') as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: rec.get(k) for k in ('phase', 'verdict_run', 'budget', 'retries', 'tag')}))
    return rec


if __name__ == '__main__':
    main()
