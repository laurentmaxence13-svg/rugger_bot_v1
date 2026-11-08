"""Offline runner of the pre-registered SOL/USD age study (W1 protocol v2.5.1). No network.

Input: the run directories written by the audited backfill (bot.market.backfill_cli run) for the
density probe and the three study windows of the protocol, all on the Pyth SOL/USD price account.
Each directory must verify, be complete, cover exactly its pre-registered slots and use the W1
cost table. Nothing here sends a request; the runs themselves are made by a person after the
owner's GO, with the Helius key provided by the owner's mechanism and RUGGER_NO_DOTENV=1.

Steps:
* ``probe_decision(probe_dir)``: transactions per slot of the probe -> pyth_age_study.study_go_no_go
  for the 3 windows (50 349 slots): 'GO' or 'STOP' with the projected credits.
* ``run_study(window_dirs, out)``: effective points of each window (pyth_push.decode_entries),
  measured seconds per protocol rule (from the first whole second after the window's first point
  to the window's last block_time), pyth_age_study.study, report written as canonical JSON with
  its sha256, ready for RUGGER 02's anchoring.
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


def probe_decision(probe_dir):
    _require_no_dotenv()
    rows, manifest = _entries(probe_dir, PROBE)
    slots = PROBE[1] - PROBE[0] + 1
    target = sum(end - start + 1 for start, end in STUDY_WINDOWS)
    decision, projected = st.study_go_no_go(len(rows), slots, target)
    return dict(decision=decision, projected_credits=projected, probe_transactions=len(rows), probe_slots=slots,
                probe_spend=manifest['budget'], windows_slots=target)


def measured_seconds(points):
    """The window's measured seconds: first whole second after its first point to its last block_time."""
    if not points:
        raise StudyRunError('study_window_without_point')
    ordered = sorted(points, key=lambda p: (p['slot'], p['transaction_index']))
    return ordered[0]['block_time'] + 1, max(p['block_time'] for p in ordered)


def run_study(window_dirs, out):
    _require_no_dotenv()
    if len(window_dirs) != len(STUDY_WINDOWS):
        raise StudyRunError('three_study_windows_required')
    points, windows, decoding, spend = [], [], [], []
    for run_dir, slots in zip(window_dirs, STUDY_WINDOWS):
        rows, manifest = _entries(run_dir, slots)
        decoded = pyth_push.decode_entries(rows)
        start, end = measured_seconds(decoded['points'])
        points += decoded['points']
        windows.append((start, end))
        decoding.append(dict(slots=list(slots), transactions=len(rows), updates=decoded['updates'],
                             not_newer=decoded['not_newer'], points=len(decoded['points']), seconds=[start, end]))
        spend.append(manifest['budget'])
    result = st.study(points, windows)
    report = dict(schema=SCHEMA, account=pyth_push.SOL_USD_ACCOUNT, feed_id=pyth_push.SOL_USD_FEED_ID,
                  windows=decoding, spend=spend, **result)
    data = json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(data)
    return report, hashlib.sha256(data).hexdigest()
