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
import math
from pathlib import Path

from cpmmprereg import rule as RCP1
from cpmmb1 import rule as B1
from cpmmx import timeline as TL
from cpmmcost import model as CC
from closedacct import model as CA

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
    return dict(cfg, sha256=cfg['raw_sha256'], slot=t0_slot)     # R02: sha of the RAW account bytes


# -- (2) ---------------------------------------------------------------------------------------------------------------
def trigger_counts(out, selected, *, t0_time, t0_slot):
    lines = timelines(out, 'pre', selected)
    cfg = amm_config_for_rules(selected, t0_slot)
    return dict(rcp1=RCP1.trigger_count(lines, cfg, t0_time), b1=B1.trigger_count(lines, cfg, t0_time),
                skipped_transactions=sum(len(l.skipped) for l in lines))


# -- (3) ---------------------------------------------------------------------------------------------------------------
D_TARGET_ENTRIES, D_MIN, D_CAP = 155, 7, 60          # R02 note e294655a (24/11), fixed before any step-1 call


def d_rule(trigger_count_rcp1, d_max_days):
    """R02 note e294655a. T = R-CP1 triggers over [T0 - 7 d ; T0). D_155 = smallest integer D with floor(T x D / 7) >= 155
    (infinite if T = 0). D = min(max(D_155, 7), floor(D_max), 60). expected = cpmmprereg.expected_entries(count, D);
    power_stop from cpmmprereg. UNDERPOWERED -> the caller STOPS before the sheets (no trial, owner referred)."""
    t = trigger_count_rcp1['triggers']
    if t > 0:
        d155 = -(-D_TARGET_ENTRIES * 7 // t)       # ceil(155 x 7 / T): floor(T x D / 7) >= 155 <=> T x D >= 1 085
        lower = max(d155, D_MIN)
    else:
        d155, lower = None, D_CAP
    d = min(lower, math.floor(d_max_days), D_CAP)
    if d < 1:
        raise Step1Stop('d_below_one_day')
    expected = RCP1.expected_entries(trigger_count_rcp1, d)
    return dict(rule='R02 e294655a: D = min(max(D_155, 7), floor(D_max), 60)', t_rcp1=t,
                d_155='inf' if d155 is None else d155, d_max_days=d_max_days, d_days=d, expected_entries=expected,
                power_stop=RCP1.power_stop(expected))


def freeze_sheets(out, *, u2_doc, count_doc, triggers, d_days, code_sha, d_rule=None):
    common = dict(schema=SCHEMA, t0_slot=u2_doc['t0_slot'], t0_time=u2_doc['t0_time'], sha_l=u2_doc['sha_l'],
                  pools=[r['pool'] for r in u2_doc['selected']], d_days=d_days,
                  window=[u2_doc['t0_time'], u2_doc['t0_time'] + int(d_days * DAY)],
                  cut_time=u2_doc['t0_time'] + int(d_days * DAY) // 2,      # R02 21:57Z: (D x 86 400) // 2, anchored with the sheet
                  r_hat=count_doc['r_hat'], code=code_sha, frozen_rules=CC.frozen_check(), d_rule=d_rule)
    if d_rule is not None and d_rule['d_days'] != d_days:
        raise Step1Stop('d_rule_differs_from_d_days')
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
SENSITIVITIES = dict(                       # keys IDENTICAL to g1ind.report.SUPPLIED (R01 g1ind 0.6, PASS R02)
    latency_10_slots=dict(latency_slots=CC.SENSITIVITY_LATENCY_SLOTS),
    one_failure_per_tx=dict(failures=CC.SENSITIVITY_FAILURES),
    rent_lost_vs_closed_account=dict(failures=CC.Failures(0, 0, CA.MAX_CLEANUP_ATTEMPTS)),
    guard_5_percent=dict(buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM),
)


def _converted(line, rows, failures=CC.FROZEN_FAILURES):
    """K01: every raw unpriced row of the frozen rule becomes a zero-sale row (failures of ITS series). The frozen
    unpriced row has no decision_slot (cpmmprereg.positions); it is copied from the timeline -- an identifier used by
    g1ind for the exit order of the drawdown, never a value."""
    return [r if 'net_return' in r else
            zero_sale(dict(r, decision_slot=line.swaps[r['decision_index']].slot), failures) for r in rows]


def g1(out, selected, *, t0_slot, sheets, g0_passed, cut_time):
    """U-4 / G-0 per pool by the frozen cpmmcost.pool_gate; then, per hypothesis, the rows of the admitted pools
    (primary, placebo and the four sensitivities on the SAME decisions) converted by zero_sale (K01, single source) and
    handed to g1ind.report 0.6 (R01 3d9166d, MANIFEST cda05131, PASS R02), which calls the frozen cpmmcost.pilot_verdict (G-1) and computes the paired
    gap, the metrics and the halves. cpmmpilot publishes no number of its own."""
    from g1ind import report as G1IND        # here, not at the top: g1ind imports cpmmpilot.step1 (R01, g1ind >= 0.5)
    lines = timelines(out, 'window', selected)
    cfg = amm_config_for_rules(selected, t0_slot)
    gates = {line.pool: CC.pool_gate(line, cfg) for line in lines}
    admitted = [line for line in lines if gates[line.pool]['admitted']]
    reasons = {}
    for g in gates.values():
        for r in g['reasons']:
            reasons[r] = reasons.get(r, 0) + 1
    result = dict(pools=len(lines), pools_admitted=len(admitted), u4_g0_reasons=reasons)
    for name, rule in (('RCP1', RCP1), ('B1', B1)):
        primary, placebo = [], []
        sens = {k: [] for k in SENSITIVITIES}
        for line in admitted:
            idx = rule.decisions(line, cfg)
            primary += _converted(line, rule.positions(line, cfg, idx))
            placebo += _converted(line, rule.positions(line, cfg, rule.placebo(line, len(idx), sheets[name])))
            for key, kw in SENSITIVITIES.items():
                sens[key] += _converted(line, rule.positions(line, cfg, idx, **kw), kw.get('failures', CC.FROZEN_FAILURES))
        write_json(Path(out) / ('G1_INPUTS_%s.json' % name), dict(primary=primary, placebo=placebo, sensitivities=sens))
        result[name] = G1IND.report(name, primary, placebo, g0_passed=g0_passed, freeze_sheet_sha256=sheets[name],
                                    cut_time=cut_time, sensitivities=sens, lines=admitted)
    assert_closed_vocabulary(result)
    write_json(Path(out) / 'G1.json', result)
    return result


# K01 (R02): an ENTERED position of an admitted pool that cannot be priced takes a sale value of 0 and stays COUNTED;
# K01 corrected by R02 (erratum 22:06Z, audit 6f071c5a): the zero sale is the FROZEN composition of cpmmcost.position
# (l. 231-238) with received = 0 -- every attempt of the buy and the sale, the WSOL close, and the token-account cleanup:
# MAX_CLEANUP_ATTEMPTS failed cleanups leave the account open (each attempt paid + rent lost), otherwise (cleanup + 1)
# transactions and no rent. (0,0,0) -> -100 420 000 ; (1,1,1) -> -100 735 000 ; (0,0,3) -> -102 669 280.
# This function is the SINGLE source of the zero-sale value (imported by g1ind >= 0.5).
def zero_sale_net_lamports(failures=CC.FROZEN_FAILURES, *, wsol_separate_close=CC.WSOL_SEPARATE_CLOSE):
    tx_buy = (1 + failures.buy) * CC.TX_FEE_LAMPORTS
    tx_sell = (1 + failures.sell) * CC.TX_FEE_LAMPORTS
    wsol_close = CC.TX_FEE_LAMPORTS if wsol_separate_close else 0
    if failures.cleanup == CA.MAX_CLEANUP_ATTEMPTS:
        cleanup, rent_lost = failures.cleanup * CC.TX_FEE_LAMPORTS, CC.TOKEN_ACCOUNT_RENT_LAMPORTS
    else:
        cleanup, rent_lost = (failures.cleanup + 1) * CC.TX_FEE_LAMPORTS, 0
    return 0 - CC.STAKE_LAMPORTS - tx_buy - tx_sell - wsol_close - cleanup - rent_lost


ZERO_SALE_NET_LAMPORTS = zero_sale_net_lamports()          # primary value, -100 420 000


def zero_sale(row, failures=CC.FROZEN_FAILURES):
    net = zero_sale_net_lamports(failures)
    return dict(row, status='unpriced_zero_sale', entered=True, received=0, net_lamports=net,
                net_return=net / CC.STAKE_LAMPORTS, unpriced_reason=row['unpriced'],
                failures=dict(buy=failures.buy, sell=failures.sell, cleanup=failures.cleanup))


# K02 (R02): closed vocabulary of every published document (same words as plbench.bench.FORBIDDEN_WORDS, test)
FORBIDDEN_WORDS = ('rentable', 'profitable', 'gagnant')
# the sentence of the sheet (K02) is owned by g1ind.report.SHEET_MEANING: single source, not repeated here


def assert_closed_vocabulary(document):
    text = json.dumps(document, ensure_ascii=False, default=str).lower()
    found = [w for w in FORBIDDEN_WORDS if w in text]
    if found:
        raise Step1Stop('forbidden_word_in_output:%s' % ','.join(found))
    return document

