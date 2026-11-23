"""plbench 0.1 -- end-to-end PAPER_LIVE TEST BENCH on fixtures (task PL-1, owner directive of 23/11 relayed by R04).
Label SIMULATED_FEED, never PAPER_LIVE: the feed is the recorded fixture events delivered one by one (with injectable
delivery faults); nothing is connected, sent or signed; no cycle can count for 50/20 (no cycle_receipt can exist).

CHAIN (protocol PAPER_LIVE v0.2, 1386a40, CONFORME R02):
  feed -> rtgate 0.2 (``FrontGate``, subclassed so that its engine is papercost 0.1 ``CostedTrade``)
       -> the frozen L1 call (``hrr.run_replay`` with l1_params, the anchored series, L1_EXIT, CreatorHistory, placebo;
          only ``hrr.replay`` is swapped, as paperstream / papercost do)
       -> journal (the CostedTrade journal of each pool and arm, and the gate record)
       -> reconciliation (papercost ``row_costs``: zero-residual decomposition, both cost modes, frozen net beside)
       -> checks S-1 to S-6 with the thresholds FIXED by R02 (21:36Z), and the hard stops of section 7 (``stops``).
A pool whose gate ends INCOMPLETE is recorded as unpriced (an open position there is valued at 0 and COUNTED, S-1).
The rtgate source stays 'HISTORICAL_REPLAY' (what the fixture feed truly is); the bench's own label is SIMULATED_FEED.
"""
import contextlib
import hashlib
import json
import statistics
import sys
from dataclasses import asdict, replace
from pathlib import Path

from bot.market import replay as R
from bot.master_v2 import w1_run
from bot.p4 import historical_research_replay as hrr
from landslip import guard as LG
from papercost import engine as PC
from paperstream import engine as PS
from rtgate import gate as RT

SCHEMA = 'plbench-v0.1'
LABEL = 'SIMULATED_FEED'
S1_MIN_COMPLETE = 0.95
S3_P95_MAX_SLOTS = 4
S5_MAX_STALE = 0.05
STOP_CREDITS_SHARE = 0.98
STOP_INCOMPLETE_24H = 0.20
STOP_FEED_GAP_MIN = 30
STOP_CLOCK_DRIFT_S = 2
STOP_DISK_SHARE = 0.90
FROZEN_FILES = dict(paperstream=(PS, 'e86f66b009444c0ed97af11ae89a1e965e9437674a17f5f1c3aa0027bddc9f4a'),
                    rtgate=(RT, '0d7ff00118b695c090ff3b9ae93d89dc7f7b0333e1343e559c8bdebd9bae1813'),
                    papercost=(PC, 'dd120b8665919ce15767e6148217335d6fca555fccb728bddeaae5b76a3b26c6'),
                    landslip_guard=(LG, '27336325dce2ca32f2520b187eb852befec272d728e7f27b1bd721300700320a'))
FORBIDDEN_MODULES = ('bot.live.engine', 'bot.live.route', 'bot.live.route_dispatch', 'bot.live.cleanup',
                     'bot.live.safety', 'bot.live.journal', 'bot.live.cpmm_swap', 'bot.live.cpmm_exit',
                     'bot.live.helius_readonly_rpc', 'bot.live.signer', 'bot.live.runtime')
SECRET_MARKERS = ('api-key=', 'api_key=', 'apikey=', 'authorization:', 'bearer ', 'private_key', 'secret_key',
                  'mnemonic')


class BenchError(RuntimeError):
    pass


def fingerprint():
    """sha256 of the audited files the bench runs (stop 0 / S-2: any change during a window is a hard stop)."""
    found = {}
    for name, (module, _expected) in FROZEN_FILES.items():
        found[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    found['python'] = '%d.%d.%d' % sys.version_info[:3]
    return found


def frozen_check():
    found = fingerprint()
    for name, (_module, expected) in FROZEN_FILES.items():
        if found[name] != expected:
            raise BenchError('audited_file_differs:%s' % name)
    return found


# -- the simulated feed -------------------------------------------------------------------------------------------
def feed(events, faults=None):
    """Deliveries of one pool: events in order, with optional faults {'drop': [i], 'dup': [i], 'reverse_slots': bool,
    'gap_before': [i] (a declared reconnect just before event i)}."""
    faults = faults or {}
    events = list(events)
    if faults.get('reverse_slots'):
        out, block = [], []
        for e in events:
            if block and e.slot != block[-1].slot:
                out += block[::-1]
                block = []
            block.append(e)
        events = out + block[::-1]
    drop, dup, gaps = set(faults.get('drop', ())), set(faults.get('dup', ())), set(faults.get('gap_before', ()))
    deliveries = []
    for i, e in enumerate(events):
        if i in gaps:
            deliveries.append(('gap', events[i - 1].slot if i else e.slot, e.slot))
        if i in drop:
            continue
        deliveries.append(e)
        if i in dup:
            deliveries.append(e)
    return deliveries


class BenchGate(RT.FrontGate):
    """rtgate 0.2 with papercost 0.1 behind it (the audited gate is unchanged; only its engine object is replaced)."""

    def __init__(self, pool, strategy, model, *, quote_mint, options):
        super().__init__(pool, strategy, model, quote_mint=quote_mint, source='HISTORICAL_REPLAY')
        self.trade = PC.CostedTrade(pool, strategy, model, quote_mint=quote_mint, options=options)


STATE = dict(options=None, faults={}, records=[])


def bench_replay(timeline, strategy, model=R.ExecutionModel(), *, quote_mint):
    """Drop-in for the frozen ``replay``: the pool's feed goes through the gate; INCOMPLETE = unpriced (S-1)."""
    gate = BenchGate(timeline.pool, strategy, model, quote_mint=quote_mint, options=STATE['options'])
    for item in feed(timeline.events, STATE['faults'].get(timeline.pool)):
        if type(item) is tuple:
            gate.declare_gap(item[1], item[2])
        else:
            gate.deliver(item)
    record = gate.close()
    STATE['records'].append(dict(pool=timeline.pool, arm=getattr(strategy, 'name', None), status=record['status'],
                                 reasons=record['reasons'], duplicates=record['duplicates_dropped'],
                                 journal=record['journal'], engine=type(gate.trade).__name__))
    if record['status'] == RT.COMPLETE:
        return gate.trade.result
    result = gate.trade.result
    if result.entry_index is not None:
        result.outcome = 'counterfactual_divergence'          # open position in an INCOMPLETE pool: valued at 0
    else:
        result.outcome = 'no_entry'
    result.notes.append('rtgate:INCOMPLETE:' + ','.join(record['reasons']))
    return result


@contextlib.contextmanager
def bench_engine(options, faults):
    original = hrr.replay
    STATE.update(options=options, faults=dict(faults or {}), records=[])
    hrr.replay = bench_replay
    try:
        yield
    finally:
        hrr.replay = original


def _bundle(pack, series):
    archives = [a for _e, a in hrr.load_fixtures(pack)[2]]
    return hrr.run_replay(pack, w1_run.l1_params(), series, w1_run.L1_EXIT,
                          hrr.CreatorHistory.from_archives(archives, 'manifest'), placebo_arm=True)


def _sha(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _once(pack, series, options, faults):
    with bench_engine(options, faults):
        bundle = _bundle(pack, series)
        records = list(STATE['records'])
    rows = []
    for pool in bundle['pools']:
        for arm, row in pool['arms'].items():
            costs = {mode: PC.row_costs(row, mode) for mode in PC.MODES}
            frozen = PC.row_costs(row, 'frozen_assumption')
            for c in list(costs.values()) + [frozen]:
                if sum(c['parts'].values()) != c['net_lamports']:
                    raise BenchError('reconciliation_residual')
            rows.append(dict(arm=arm, outcome=row['outcome'], entered=row.get('entry_index') is not None,
                             costs=costs, frozen_net=frozen['net_lamports'],
                             incomplete=any(n.startswith('rtgate:INCOMPLETE') for n in row['notes'])))
    return bundle, records, rows


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, max(0, -(-q * len(ordered) // 100) - 1))]


def run_bench(pack, series, *, options=None, faults=None, latency_slots=None):
    """One bench run; S-2 replays the same feed a second time and compares the bytes."""
    start = frozen_check()
    options = PC.Options.primary() if options is None else options
    bundle, records, rows = _once(pack, series, options, faults)
    _b2, records2, rows2 = _once(pack, series, options, faults)
    pools = sorted({r['pool'] for r in records})
    complete = {r['pool'] for r in records if r['status'] == RT.COMPLETE}
    incomplete_pools = [p for p in pools if p not in complete]
    master = bundle['totals']['master']
    stale = master['blocking_reasons'].get('sol_usd_stale', 0)
    s1 = len(complete) / len(pools) if pools else 0.0
    s3 = None if not latency_slots else dict(p95=percentile(latency_slots, 95), p99=percentile(latency_slots, 99))
    s5 = stale / master['decisions'] if master['decisions'] else 0.0
    summary = {mode: dict(net_lamports=sum(r['costs'][mode]['net_lamports'] for r in rows if r['costs'][mode]['counted']),
                          counted=sum(r['costs'][mode]['counted'] for r in rows)) for mode in PC.MODES}
    summary['frozen'] = dict(net_lamports=sum(r['frozen_net'] for r in rows if r['outcome'] in PC.PRICED))
    checks = dict(
        S1_coverage=dict(value=s1, threshold=S1_MIN_COMPLETE, passed=s1 >= S1_MIN_COMPLETE,
                         incomplete_reasons=sorted({x for r in records if r['status'] != RT.COMPLETE for x in r['reasons']})),
        S2_rerun_identical=dict(passed=_sha([records, rows]) == _sha([records2, rows2]) and fingerprint() == start),
        S3_latency=dict(value=s3, threshold_p95_slots=S3_P95_MAX_SLOTS,
                        passed=bool(s3 is not None and s3['p95'] <= S3_P95_MAX_SLOTS)),
        S4_no_signer=dict(passed=not [m for m in FORBIDDEN_MODULES if m in sys.modules]),
        S5_sol_usd_fresh=dict(value=s5, threshold=S5_MAX_STALE, passed=s5 <= S5_MAX_STALE),
        S6_costs_published=dict(passed=all(m in summary for m in PC.MODES + ('frozen',)), summary=summary))
    passed = all(checks[k]['passed'] for k in ('S1_coverage', 'S2_rerun_identical', 'S3_latency', 'S4_no_signer',
                                               'S5_sol_usd_fresh'))
    return dict(schema=SCHEMA, label=LABEL, counts_for_operational_master=False, cycle_receipts=0,
                fingerprint=start, pools=len(pools), incomplete_pools=len(incomplete_pools), checks=checks,
                technical_success=passed, economic_claim=None,
                records_sha256=_sha(records), rows_sha256=_sha(rows))


# -- hard stops of the protocol (section 7, with addition a of R02) -----------------------------------------------
def scan_for_secrets(texts):
    lowered = [t.lower() for t in texts]
    return any(marker in t for t in lowered for marker in SECRET_MARKERS)


def stops(state, fingerprint_t0):
    """The hard stops triggered by a state of the window, in the protocol order (0 first)."""
    out = []
    if state.get('fingerprint') != fingerprint_t0:
        out.append('0_code_or_environment_sha_changed')
    if state['credits_used'] >= STOP_CREDITS_SHARE * state['credits_cap']:
        out.append('1_credits_98_percent')
    if [m for m in FORBIDDEN_MODULES if m in state.get('modules', ())]:
        out.append('2_signing_or_sending_module')
    if scan_for_secrets(state.get('log_lines', ())):
        out.append('3_secret_in_a_log')
    if state['incomplete_share_24h'] > STOP_INCOMPLETE_24H:
        out.append('4_incomplete_over_20_percent_24h')
    if state['feed_gap_minutes'] > STOP_FEED_GAP_MIN:
        out.append('5_feed_cut_over_30_min_new_segment')
    if abs(state['clock_drift_s']) > STOP_CLOCK_DRIFT_S:
        out.append('6_clock_drift_over_2_s_pause')
    if state['disk_used_share'] >= STOP_DISK_SHARE:
        out.append('7_disk_90_percent')
    return out
