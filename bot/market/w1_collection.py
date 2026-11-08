"""W1 collection plan (W1 protocol, item R6). Offline: nothing here sends a request.

The collection itself is the audited program-window backfill (``bot.market.backfill``:
getTransactionsForAddress full pages of the LaunchLab program, getSignaturesForAddress
reconciliation, request AND credit caps charged on disk before every send) and its export
(``bot.market.backfill_export``: per-pool archives and the L1 MANIFEST). This module only
fixes the W1 numbers of the protocol and checks them:

* window [S0, S0 + 2 020 113): warm-up [S0, S0 + 402 800) (creator history only),
  evaluation [S0 + 402 800, S0 + 2 015 600), gap of 4 513 slots (no entry; positions close);
  entry_cutoff_slot = S0 + 2 015 599 and window_slot_max = S0 + 2 020 112;
* hard credit cap 1 000 000 for the whole free month, the pilot (at most 50 000) included;
  the cost table is the documented Helius one;
* cap rule: after the pilot and before any W1 slot is read, if the projection exceeds the
  credits left, the evaluation range is shortened to fit, never below 806 400 slots (48 h);
  below that, STOP. The projection is integer arithmetic on the pilot's measured spend.
"""
from bot.market import backfill as bf
from bot.market import backfill_export as bx

WARMUP_SLOTS = 402_800
EVALUATION_SLOTS = 1_612_800
GAP_SLOTS = 4_513
MIN_EVALUATION_SLOTS = 806_400
CREDIT_CAP = 1_000_000
PILOT_MAX_CREDITS = 50_000
PILOT_SLOTS = (466_226_737, 466_248_336)
COSTS = 'helius-documented-20261108'


def bounds(s0, evaluation_slots=EVALUATION_SLOTS):
    """Every W1 slot bound from S0 (the evaluation range may only be shortened)."""
    if type(s0) is not int or s0 <= 0:
        raise bf.BackfillError('invalid_s0')
    if type(evaluation_slots) is not int or not MIN_EVALUATION_SLOTS <= evaluation_slots <= EVALUATION_SLOTS:
        raise bf.BackfillError('evaluation_slots_outside_protocol')
    evaluation_start = s0 + WARMUP_SLOTS
    evaluation_end = evaluation_start + evaluation_slots
    slot_max = evaluation_end + GAP_SLOTS - 1
    return dict(slot_min=s0, slot_max=slot_max, warmup=(s0, evaluation_start),
                evaluation=(evaluation_start, evaluation_end), entry_cutoff_slot=evaluation_end - 1,
                window_slot_max=slot_max, gap_slots=GAP_SLOTS, evaluation_slots=evaluation_slots,
                collected_slots=slot_max - s0 + 1)


def fit_to_cap(s0, *, pilot_credits, pilot_slots, credits_left):
    """('FULL' | 'SHORTENED', bounds) or ('STOP', None), from the pilot's measured spend."""
    for value in (pilot_credits, pilot_slots, credits_left):
        if type(value) is not int or value < 0:
            raise bf.BackfillError('invalid_cap_inputs')
    if pilot_slots == 0 or pilot_credits == 0:
        raise bf.BackfillError('pilot_measured_nothing')
    full = bounds(s0)
    if -(-pilot_credits * full['collected_slots'] // pilot_slots) <= credits_left:
        return 'FULL', full
    affordable_slots = credits_left * pilot_slots // pilot_credits
    evaluation_slots = affordable_slots - WARMUP_SLOTS - GAP_SLOTS
    if evaluation_slots < MIN_EVALUATION_SLOTS:
        return 'STOP', None
    return 'SHORTENED', bounds(s0, evaluation_slots)


# The 14-line wrapper tools/backfill_launchlab_window.py (it only calls backfill_cli.main) is not
# a root: it stays outside the offline harness copy; its sha256 is listed in the frozen protocol.
COLLECTOR_ROOTS = ('bot/market/backfill.py', 'bot/market/backfill_cli.py', 'bot/market/backfill_export.py',
                   'bot/market/w1_collection.py')


def _read_json(path):
    import json
    from pathlib import Path
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _spend(run_dir):
    """The spend ledger of a run directory (written before every send: the authoritative spend)."""
    from pathlib import Path
    spend = _read_json(Path(run_dir) / 'spend.json')
    if spend.get('schema') != bf.CreditBudget.SCHEMA or spend.get('costs') != bf.COST_PRESETS[COSTS]:
        raise bf.BackfillError('ledger_not_on_the_w1_cost_table')
    if type(spend.get('credits')) is not int or spend['credits'] < 0:
        raise bf.BackfillError('invalid_spend_ledger')
    return spend


def reserved_credits(run_dirs):
    """Credits reserved by other runs of the collection month (v2.4: the SOL/USD runs).

    Each run reserves the LARGEST cap it ever ran under (not only what it spent): whatever it
    may still spend is counted, so the month can never exceed CREDIT_CAP.
    """
    total = 0
    for run_dir in run_dirs:
        spend = _spend(run_dir)
        caps = [cap['max_credits'] for cap in spend.get('cap_history') or []]
        if not caps:
            raise bf.BackfillError('run_without_cap_history')
        total += max(max(caps), spend['credits'])
    return total


def main_run_cap(pilot_dir, other_runs=()):
    """Credits left for a W1 run: 1 000 000 minus the pilot's spend and the other runs' caps.

    The pilot directory must be the pilot window (LaunchLab program, P0 slots PILOT_SLOTS),
    every cap it ever ran under at most PILOT_MAX_CREDITS, its ledger on the W1 cost table.
    ``other_runs``: every other run directory of the month (v2.4: SOL/USD study and collection).
    """
    from pathlib import Path
    window = _read_json(Path(pilot_dir) / 'manifest.json')['window']
    if (window['address'], window['slot_min'], window['slot_max']) != (bf.LAUNCHLAB_PROGRAM,) + PILOT_SLOTS:
        raise bf.BackfillError('not_the_pilot_window')
    spend = _spend(pilot_dir)
    caps = [cap['max_credits'] for cap in spend.get('cap_history') or []]
    if not caps or max(caps) > PILOT_MAX_CREDITS or spend['credits'] > PILOT_MAX_CREDITS:
        raise bf.BackfillError('pilot_spend_above_its_cap')
    return CREDIT_CAP - spend['credits'] - reserved_credits(other_runs)


def check_run_cap(max_credits, pilot_dir, other_runs=()):
    """Called BEFORE a W1 run starts: its credit cap must fit what the pilot and other runs left."""
    if type(max_credits) is not int or max_credits < 0 or max_credits > main_run_cap(pilot_dir, other_runs):
        raise bf.BackfillError('run_cap_above_credits_left_after_the_pilot')
    return max_credits


def collector_code():
    """Fingerprint of the collection and decoding code (closure of COLLECTOR_ROOTS)."""
    import hashlib
    import json
    from bot.master_v2 import harness
    modules = harness.code_modules(roots=COLLECTOR_ROOTS)
    rows = [(path, hashlib.sha256((harness._ROOT / path).read_bytes()).hexdigest()) for path in modules]
    return dict(rule=harness.FINGERPRINT_RULE.replace('CODE_ROOTS', 'COLLECTOR_ROOTS'), roots=list(COLLECTOR_ROOTS),
                modules=list(modules), sha256=hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest())


def export(window_dir, pools_dir, s0, *, pilot_dir, evaluation_slots=EVALUATION_SLOTS, other_runs=()):
    """Export a verified W1 window; its bounds and spend must be those of the protocol.

    Pilot plus collection stay within CREDIT_CAP: every cap the run ever had fits what the pilot
    left, and the two ledgers together never exceed 1 000 000 credits (R02 R6-1).
    """
    from pathlib import Path
    planned = bounds(s0, evaluation_slots)
    manifest = _read_json(Path(window_dir) / 'manifest.json')
    window = manifest['window']
    if (window['address'], window['slot_min'], window['slot_max']) != (
            bf.LAUNCHLAB_PROGRAM, planned['slot_min'], planned['slot_max']):
        raise bf.BackfillError('window_is_not_the_w1_window')
    left = main_run_cap(pilot_dir, other_runs)
    spend = _spend(window_dir)
    caps = [cap['max_credits'] for cap in spend.get('cap_history') or []]
    if (manifest['budget']['costs'] != bf.COST_PRESETS[COSTS] or not caps or max(caps) > left
            or manifest['budget']['max_credits'] > left or spend['credits'] > left
            or manifest['budget']['credits'] > spend['credits']):
        raise bf.BackfillError('window_not_collected_under_the_w1_cap')
    result = bx.export_pools(window_dir, pools_dir, entry_cutoff_gap_slots=GAP_SLOTS,
                             collector_code=collector_code())
    if (result['entry_cutoff_slot'], result['window_slot_max']) != (
            planned['entry_cutoff_slot'], planned['window_slot_max']):
        raise bf.BackfillError('exported_window_differs_from_the_plan')
    return result
