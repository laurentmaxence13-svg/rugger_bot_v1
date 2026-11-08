"""Shared helper of the W1 tests (not a test module)."""
import json

from bot.market import backfill as bf
from bot.market import w1_collection as w1


def pilot_dir(tmp_path, credits):
    run = tmp_path / 'pilot'
    budget = bf.CreditBudget(10**6, w1.PILOT_MAX_CREDITS, bf.COST_PRESETS[w1.COSTS], ledger=run / 'spend.json')
    for _ in range(credits):
        budget.next_method = 'getSignaturesForAddress'
        budget.charge()
    (run / 'manifest.json').write_text(json.dumps({'window': {
        'address': bf.LAUNCHLAB_PROGRAM, 'slot_min': w1.PILOT_SLOTS[0], 'slot_max': w1.PILOT_SLOTS[1]}}))
    return run
