"""Step 1 of the CPMM pilot, in the order of owner text C (R02 v1.2):
(1) signature count over the 24 h before T0 (getSignaturesForAddress, no transaction read) -> R^, then the point-(2)
    stop rule (24 x R^ x 8 x 0.10 + 400 > 32 900 -> STOP, no trial);
(2) trigger counts of R-CP1 and B1 over [T0 - 7 d ; T0) (frozen cpmmprereg / cpmmb1, no outcome);
(3) freeze sheets (R-CP1 and B1: list, T0, D, codes) -- the window is read ONLY with the sha anchored by R02;
(4) collection of the raw transactions of the pools over [T0 ; T0 + D) (GTFA full, asc, 100 per page, gz pages,
    resumable after a container restart, hard stop at 49 000 credits);
(5) G-1 inputs with the frozen rules; the G-1 verdict itself is taken from the frozen code if it exists there.
"""
import hashlib
import json
from pathlib import Path

from cpmmprereg import rule as RCP1
from cpmmb1 import rule as B1
from cpmmx import timeline as TL
from cpmmcost import model as CC

from . import budget as B
from .rpc import canonical, sha
from .store import disk_free_ok, file_sha, read_gz_page, read_json, write_gz_page, write_json

DAY = 86_400
MIN_FREE_BYTES = 2 * 1024 ** 3
SCHEMA = 'cpmmpilot-step1-v0.1'


class Step1Stop(RuntimeError):
    pass


# -- (1) -----------------------------------------------------------------------------------------------------------
def count_24h(client, pools, *, t0_time):
    per_pool = {}
    for pool in pools:
        n, before = 0, None
        while True:
            opts = dict(limit=1000)
            if before:
                opts['before'] = before
            page = client.call('getSignaturesForAddress', [pool, opts])
            if not page:
                break
            n += sum(1 for s in page if t0_time - DAY <= (s.get('blockTime') or 0) < t0_time)
            before = page[-1]['signature']
            if (page[-1].get('blockTime') or 0) < t0_time - DAY or len(page) < 1000:
                break
        per_pool[pool] = n
    r_hat = sum(per_pool.values()) / len(per_pool) if per_pool else 0.0
    return dict(per_pool=per_pool, r_hat=r_hat, statistic='mean signatures per pool over the 24 h before T0',
                point2=B.point2_stop(r_hat), d_max_days=B.d_max_days(r_hat))


# -- collection (phase 'pre' for (2), phase 'window' for (4)) ----------------------------------------------------------
def collect(client, out, pools, *, start_time, end_time, phase, min_free=MIN_FREE_BYTES):
    """GTFA pages of every pool over [start_time ; end_time), written gz page by page; a per-pool state file makes the
    collection resumable after any interruption (the credit ledger, written before each call, never goes back)."""
    root = Path(out) / 'collect' / phase
    for pool in pools:
        d = root / pool
        state_path = d / 'STATE.json'
        state = read_json(state_path) if state_path.exists() else dict(pages=0, token=None, done=False,
                                                                     transactions=0, window=[start_time, end_time])
        if state['window'] != [start_time, end_time]:
            raise Step1Stop('state_window_differs')
        while not state['done']:
            Path(out).mkdir(parents=True, exist_ok=True)
            if not disk_free_ok(Path(out), min_free):
                raise Step1Stop('disk_below_minimum')
            opts = dict(transactionDetails='full', sortOrder='asc', limit=B.GTFA_MAX_LIMIT, encoding='json',
                        maxSupportedTransactionVersion=0, filters=dict(blockTime=dict(gte=start_time, lt=end_time)))
            if state['token']:
                opts['paginationToken'] = state['token']
            page = client.call('getTransactionsForAddress', [pool, opts])
            write_gz_page(d / ('page_%05d.json.gz' % state['pages']), page)
            state = dict(state, pages=state['pages'] + 1, token=page.get('paginationToken'),
                         transactions=state['transactions'] + len(page.get('data') or []),
                         done=page.get('paginationToken') is None)
            write_json(state_path, state)
    return {pool: read_json(root / pool / 'STATE.json') for pool in pools}


def transactions_of(out, phase, pool):
    txs = {}
    for p in sorted((Path(out) / 'collect' / phase / pool).glob('page_*.json.gz')):
        for tx in read_gz_page(p).get('data') or []:
            txs[tx['transaction']['signatures'][0]] = tx
    return txs


def timelines(out, phase, selected):
    return [TL.build(r['pool'], transactions_of(out, phase, r['pool']), base_mint=r['base_mint'])
            for r in selected]


def amm_config_for_rules(selected, t0_slot):
    """The single AmmConfig of the selected pools, READ and hashed with its slot (cpmmcost.fees_from_amm_config)."""
    configs = {canonical(r['amm_config']) for r in selected}
    if len(configs) != 1:
        raise Step1Stop('selected_pools_use_several_amm_configs')
    cfg = json.loads(configs.pop())
    return dict(cfg, sha256=hashlib.sha256(canonical(cfg).encode()).hexdigest(), slot=t0_slot)


# -- (2) ---------------------------------------------------------------------------------------------------------------
def trigger_counts(out, selected, *, t0_time, t0_slot):
    lines = timelines(out, 'pre', selected)
    cfg = amm_config_for_rules(selected, t0_slot)
    return dict(rcp1=RCP1.trigger_count(lines, cfg, t0_time), b1=B1.trigger_count(lines, cfg, t0_time),
                skipped_transactions=sum(len(l.skipped) for l in lines))


# -- (3) ---------------------------------------------------------------------------------------------------------------
def freeze_sheets(out, *, u2_doc, count_doc, triggers, d_days, code_sha):
    common = dict(schema=SCHEMA, t0_slot=u2_doc['t0_slot'], t0_time=u2_doc['t0_time'], sha_l=u2_doc['sha_l'],
                  pools=[r['pool'] for r in u2_doc['selected']], d_days=d_days,
                  window=[u2_doc['t0_time'], u2_doc['t0_time'] + int(d_days * DAY)],
                  r_hat=count_doc['r_hat'], code=code_sha, frozen_rules=CC.frozen_check())
    sheets = {}
    for name, rule, trial in (('RCP1', 'cpmmprereg 0.2', 169), ('B1', 'cpmmb1 0.1.1', 170)):
        doc = dict(common, hypothesis=name, rule=rule, trial=trial,
                   trigger_count=triggers['rcp1' if name == 'RCP1' else 'b1'])
        path = Path(out) / ('FICHE_GEL_%s.json' % name)
        write_json(path, doc)
        sheets[name] = file_sha(path)
    return sheets


def check_anchor(out, anchored):
    """The window is read only if R02's anchored sha of BOTH sheets equal the files on disk."""
    for name in ('RCP1', 'B1'):
        if file_sha(Path(out) / ('FICHE_GEL_%s.json' % name)) != anchored.get(name):
            raise Step1Stop('freeze_sheet_not_anchored:%s' % name)


# -- (5) ---------------------------------------------------------------------------------------------------------------
def g1_inputs(out, selected, *, t0_slot, sheets):
    lines = timelines(out, 'window', selected)
    cfg = amm_config_for_rules(selected, t0_slot)
    result = {}
    for name, rule in (('RCP1', RCP1), ('B1', B1)):
        primary, placebo = [], []
        for line in lines:
            idx = rule.decisions(line, cfg)
            primary += rule.positions(line, cfg, idx)
            placebo += rule.positions(line, cfg, rule.placebo(line, len(idx), sheets[name]))
        entered = [p for p in primary if 'net_return' in p and p.get('entered', True)]
        verdict_fn = getattr(rule, 'pilot_verdict', None)
        result[name] = dict(
            positions=len(primary), entered=len(entered), pools_with_entries=len({p['pool'] for p in entered}),
            unpriced=sum('net_return' not in p for p in primary), placebo_positions=len(placebo),
            g1=(verdict_fn(primary, placebo_=placebo, freeze_sheet_sha256=sheets[name]) if verdict_fn
                else 'G1_RULE_NOT_FROZEN: no pilot_verdict function in the frozen rule; G-1 is computed by R02 '
                     'from the published positions'))
        write_json(Path(out) / ('G1_INPUTS_%s.json' % name), dict(primary=primary, placebo=placebo))
    return result
