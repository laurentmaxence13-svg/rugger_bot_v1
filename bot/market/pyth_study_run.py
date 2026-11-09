"""Offline runner of the pre-registered SOL/USD age study (W1 protocol v2.5.1). No network.

Input: the run directories written by the audited backfill (bot.market.backfill_cli run) for the
density probe and the three study windows of the protocol, all on the Pyth SOL/USD price account.
Each directory must verify, be complete, cover exactly its pre-registered slots and use the W1
cost table. Nothing here sends a request; the runs themselves are made by a person after the
owner's GO, with the Helius key provided by the owner's mechanism and RUGGER_NO_DOTENV=1.

Steps:
* ``probe_decision(probe_dir)``: the probe's ledger must show every cap and the spend at most
  PROBE_MAX_CREDITS; transactions per slot of the probe -> pyth_age_study.study_go_no_go for the
  3 windows (50 349 slots): 'GO' or 'STOP' with the projected credits.
* ``window_projection(probe_dir)`` (step 1 bis, owner option B): each window priced on the probe's
  real cost per page with a prudent hypothesis; 'GO' only if each is <= 720 (cap 800 per window).
* ``run_study(window_dirs, out, probe_dir=...)``: recomputes probe_decision and refuses unless GO;
  the credits reserved by the probe and the 3 windows (largest cap each ever ran under, ledgers on
  the W1 cost table) must be at most STUDY_TOTAL_MAX_CREDITS; effective points of each window
  (pyth_push.decode_entries); measured seconds per protocol rule; pyth_age_study.study; report
  (with the credit amounts) written as canonical JSON with its sha256, for RUGGER 02's anchoring.

* ``dashboard_check(probe_dir, dashboard)`` (R02 C-4): the owner's Helius dashboard readings just
  before and just after the probe. Autoscaling must read 'disabled' both times (no overage
  billing), and the credits the dashboard shows consumed by the probe must EQUAL the probe ledger's
  spend on the W1 cost table (GTFA 10 per page). Anything else is a STOP before the study: every
  budget would have to be recomputed in real credits and re-authorized. run_study repeats it.

Measured seconds of a window (R02 audit 2e310e5a, C-1): the half-open interval [start, end) with
start = the first whole second after the window's first effective point (its block_time + 1) and
end = the LAST block_time among ALL the window's transactions (points, readers, failed); the
second ``end`` itself is excluded, as in pyth_age_study ([start_s, end_s)). The final gap of a
window, where the largest ages occur, is therefore measured rather than dropped.
"""
import hashlib
import json
import os
from pathlib import Path

from bot.market import backfill as bf
from bot.market import pyth_age_study as st
from bot.market import pyth_push
from bot.market import w1_collection

STUDY_WINDOWS = ((466_226_737, 466_243_519), (466_298_737, 466_315_519), (466_370_737, 466_387_519))
PROBE = (466_226_737, 466_229_533)
PROBE_MAX_CREDITS = 200
# Owner decision "option B" (2026-11-09): strict overall ceiling of 2 600 free Helius credits, probe
# included, about 800 at most per window. 200 + 3 x 800 = 2 600: the reserved caps alone fit it.
WINDOW_MAX_CREDITS = 800
STUDY_TOTAL_MAX_CREDITS = 2_600
assert PROBE_MAX_CREDITS + len(STUDY_WINDOWS) * WINDOW_MAX_CREDITS <= STUDY_TOTAL_MAX_CREDITS
# Step 1 bis: a window is launched only if its prudent projection leaves >= 10 % of its cap for
# the density variance between windows (same margin as the former 600 / 666).
WINDOW_PROJECTION_LIMIT = 720
GTFA_PAGE_CREDITS = 10
GSFA_PAGE_ROWS = 1_000
SCHEMA = 'rugger-sol-usd-age-study-report-v1'


class StudyRunError(RuntimeError):
    pass


def _require_no_dotenv(environ=None):
    if (os.environ if environ is None else environ).get('RUGGER_NO_DOTENV') != '1':
        raise StudyRunError('set_RUGGER_NO_DOTENV_1_before_the_study')


def _entries(run_dir, slots):
    checked = bf.verify(run_dir)
    manifest = json.loads((Path(run_dir) / 'manifest.json').read_text(encoding='utf-8'))
    window = manifest['window']
    if not checked['ok'] or not manifest['complete']:
        raise StudyRunError('study_run_not_verified_or_incomplete:' + str(run_dir))
    if (window['address'], window['slot_min'], window['slot_max']) != (pyth_push.SOL_USD_ACCOUNT,) + tuple(slots):
        raise StudyRunError('not_the_preregistered_study_window:' + str(run_dir))
    if manifest['budget']['costs'] != bf.COST_PRESETS[w1_collection.COSTS]:
        raise StudyRunError('study_run_not_on_the_w1_cost_table')
    rows = [row for seg in manifest['segments'] if seg['kind'] == 'tx'
            for row in bf.read_segment(Path(run_dir) / seg['path'])]
    return rows, manifest


def _run_credits(run_dir):
    """Largest cap the run ever ran under and its spend, from its ledger (W1 cost table)."""
    try:
        spend = w1_collection._spend(run_dir)
    except bf.BackfillError as exc:
        raise StudyRunError(f'{exc}:{run_dir}') from None
    caps = [cap['max_credits'] for cap in spend.get('cap_history') or []]
    if not caps:
        raise StudyRunError('run_without_cap_history:' + str(run_dir))
    return dict(cap=max(caps), spent=spend['credits'], reserved=max(max(caps), spend['credits']))


def probe_decision(probe_dir):
    _require_no_dotenv()
    rows, manifest = _entries(probe_dir, PROBE)
    credits = _run_credits(probe_dir)
    if credits['cap'] > PROBE_MAX_CREDITS or credits['spent'] > PROBE_MAX_CREDITS:
        raise StudyRunError('probe_spend_above_its_cap')
    slots = PROBE[1] - PROBE[0] + 1
    target = sum(end - start + 1 for start, end in STUDY_WINDOWS)
    decision, projected = st.study_go_no_go(len(rows), slots, target)
    return dict(decision=decision, projected_credits=projected, probe_transactions=len(rows), probe_slots=slots,
                probe_spend=manifest['budget'], probe_credits=credits, windows_slots=target)


def _probe_gtfa_pages(probe_dir, manifest):
    """GTFA body pages the probe really paid for (anchor excluded).

    From calls.jsonl when the run has one (option B, item 2); otherwise from the ledger, whose two
    totals (requests, credits) on the W1 table (GTFA 10, GSFA 1) give a unique split for a GTFA-bodies
    run: 10 a + b = credits, a + b = requests. The probe 7UVimf: 121, 13 -> a = 12 (1 anchor + 11).
    """
    calls = manifest.get('calls')
    if calls is not None:
        lines = [json.loads(raw) for raw in (Path(probe_dir) / bf.CALLS_LOG).read_text().splitlines() if raw]
        return sum(1 for line in lines if line['method'] == 'getTransactionsForAddress'
                   and line['phase'] == 'gtfa' and 'error' not in line)
    budget = manifest['budget']
    if manifest['bodies'] != 'gtfa' or budget['costs'] != bf.COST_PRESETS[w1_collection.COSTS]:
        raise StudyRunError('probe_page_split_needs_a_gtfa_run_on_the_w1_table')
    gtfa, rest = divmod(budget['credits'] - budget['requests'], GTFA_PAGE_CREDITS - 1)
    if rest or not 0 <= gtfa <= budget['requests']:
        raise StudyRunError('probe_ledger_has_no_gtfa_gsfa_split')
    return gtfa - (1 if manifest.get('gsfa_anchor') else 0)


def window_projection(probe_dir):
    """Step 1 bis (owner option B, item 3): each window priced on the cost the probe REALLY paid.

    Prudent hypothesis (R02, 2026-11-08, (ii)): the probe's pages were partly filled all along, not
    full pages plus one empty last page. So:
    * density = probe transactions / probe slots, rounded UP to the thousandth;
    * window transactions = ceil(density x window slots);
    * transactions per GTFA page = floor(probe transactions / GTFA pages the probe paid) (995/11 -> 90);
    * GTFA pages = ceil(window transactions / that) + 1 last page;
    * GSFA pages = ceil(window transactions / 1000) + 1 last page; + 1 anchor (10).
    'GO' only if every window is at most WINDOW_PROJECTION_LIMIT and the reserved caps fit 2 600.
    """
    _require_no_dotenv()
    probe = probe_decision(probe_dir)
    manifest = json.loads((Path(probe_dir) / 'manifest.json').read_text(encoding='utf-8'))
    pages = _probe_gtfa_pages(probe_dir, manifest)
    tx, slots = probe['probe_transactions'], probe['probe_slots']
    if pages <= 0 or tx <= 0:
        raise StudyRunError('probe_without_gtfa_page_or_transaction')
    per_page = tx // pages
    density_milli = -(-tx * 1000 // slots)
    costs = bf.COST_PRESETS[w1_collection.COSTS]
    windows = []
    for start, end in STUDY_WINDOWS:
        window_tx = -(-density_milli * (end - start + 1) // 1000)
        gtfa = -(-window_tx // per_page) + 1
        gsfa = -(-window_tx // GSFA_PAGE_ROWS) + 1
        credits = (gtfa + 1) * costs['getTransactionsForAddress'] + gsfa * costs['getSignaturesForAddress']
        windows.append(dict(slots=[start, end], transactions=window_tx, gtfa_pages=gtfa, gsfa_pages=gsfa,
                            anchor=1, credits=credits))
    reserved = probe['probe_credits']['reserved'] + len(STUDY_WINDOWS) * WINDOW_MAX_CREDITS
    ok = (probe['decision'] == 'GO' and reserved <= STUDY_TOTAL_MAX_CREDITS
          and all(w['credits'] <= WINDOW_PROJECTION_LIMIT for w in windows))
    return dict(decision='GO' if ok else 'STOP', density_tx_per_slot=density_milli / 1000,
                probe_gtfa_pages=pages, transactions_per_page=per_page, windows=windows,
                limit=WINDOW_PROJECTION_LIMIT, window_cap=WINDOW_MAX_CREDITS,
                reserved_with_window_caps=reserved, total_max=STUDY_TOTAL_MAX_CREDITS)


def dashboard_check(probe_dir, dashboard):
    """STOP unless the owner's readings show autoscaling disabled and real probe cost == ledger."""
    _require_no_dotenv()
    probe = probe_decision(probe_dir)
    try:
        before, after = dashboard['before_probe'], dashboard['after_probe']
        readings = [(before['credits_remaining'], before['autoscaling']),
                    (after['credits_remaining'], after['autoscaling'])]
        plan = before['plan']
    except (KeyError, TypeError):
        raise StudyRunError('dashboard_readings_incomplete') from None
    if dashboard.get('read_by') != 'owner' or type(plan) is not str or not plan:
        raise StudyRunError('dashboard_readings_incomplete')
    if any(type(credits) is not int or credits < 0 for credits, _ in readings):
        raise StudyRunError('dashboard_readings_incomplete')
    if any(autoscaling != 'disabled' for _, autoscaling in readings):
        raise StudyRunError('autoscaling_not_disabled')
    real = before['credits_remaining'] - after['credits_remaining']
    counted = probe['probe_credits']['spent']
    if real != counted:
        raise StudyRunError(f'dashboard_cost_differs_from_the_w1_cost_table:{real}!={counted}')
    return dict(plan=plan, before=before['credits_remaining'], after=after['credits_remaining'],
                real_probe_credits=real, counted_probe_credits=counted, autoscaling='disabled')


def measured_seconds(points, rows):
    """[start, end) of a window: first whole second after its first point; last block_time of all rows."""
    if not points:
        raise StudyRunError('study_window_without_point')
    times = [row.get('blockTime') for row in rows]
    if not times or any(type(t) is not int for t in times):
        raise StudyRunError('study_window_without_block_times')
    first = min(points, key=lambda p: (p['slot'], p['transaction_index']))
    start, end = first['block_time'] + 1, max(times)
    if end <= start:
        raise StudyRunError('study_window_without_measured_second')
    return start, end


def run_study(window_dirs, out, *, probe_dir, dashboard):
    _require_no_dotenv()
    if len(window_dirs) != len(STUDY_WINDOWS):
        raise StudyRunError('three_study_windows_required')
    dashboard_result = dashboard_check(probe_dir, dashboard)
    probe = probe_decision(probe_dir)
    if probe['decision'] != 'GO':
        raise StudyRunError('probe_decision_is_not_go')
    projection = window_projection(probe_dir)
    if projection['decision'] != 'GO':
        raise StudyRunError('window_projection_is_not_go')
    window_credits = [_run_credits(run_dir) for run_dir in window_dirs]
    if any(c['cap'] > WINDOW_MAX_CREDITS for c in window_credits):
        raise StudyRunError('study_window_cap_above_' + str(WINDOW_MAX_CREDITS))
    reserved = probe['probe_credits']['reserved'] + sum(c['reserved'] for c in window_credits)
    if reserved > STUDY_TOTAL_MAX_CREDITS:
        raise StudyRunError('study_reserved_credits_above_' + str(STUDY_TOTAL_MAX_CREDITS))
    points, windows, decoding, spend = [], [], [], []
    for run_dir, slots in zip(window_dirs, STUDY_WINDOWS):
        rows, manifest = _entries(run_dir, slots)
        decoded = pyth_push.decode_entries(rows)
        start, end = measured_seconds(decoded['points'], rows)
        points += decoded['points']
        windows.append((start, end))
        decoding.append(dict(slots=list(slots), transactions=len(rows), updates=decoded['updates'],
                             not_newer=decoded['not_newer'], points=len(decoded['points']), seconds=[start, end]))
        spend.append(manifest['budget'])
    result = st.study(points, windows)
    credits = dict(probe=probe['probe_credits'], windows=window_credits, reserved_total=reserved,
                   probe_max=PROBE_MAX_CREDITS, window_max=WINDOW_MAX_CREDITS,
                   total_max=STUDY_TOTAL_MAX_CREDITS, costs=w1_collection.COSTS, window_projection=projection)
    report = dict(schema=SCHEMA, account=pyth_push.SOL_USD_ACCOUNT, feed_id=pyth_push.SOL_USD_FEED_ID,
                  windows=decoding, spend=spend, credits=credits, dashboard=dashboard_result,
                  probe=dict(decision=probe['decision'], projected_credits=probe['projected_credits'],
                             transactions=probe['probe_transactions'], slots=probe['probe_slots']),
                  measured_seconds_rule='[first_point_block_time+1, last_block_time_of_all_window_transactions)',
                  **result)
    data = json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(data)
    return report, hashlib.sha256(data).hexdigest()
