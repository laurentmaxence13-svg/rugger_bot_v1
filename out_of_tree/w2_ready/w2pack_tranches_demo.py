"""Does the FROZEN w1_collection.export accept a 7-day collection slice as one 4-day W2 window? (offline, no network)"""
import json, sys, tempfile
from pathlib import Path
from bot.market import backfill as bf, w1_collection as wc

S0 = 470_904_145                       # any W2-like s0 (W1 s0 + 2 x 1 612 800)
SLOTS_PER_DAY = 86_400_000 // 215      # 215 ms per slot (measured)
plan = wc.bounds(S0)
print('planned window', plan['slot_min'], plan['slot_max'], 'collected_slots', plan['collected_slots'],
      'days', round(plan['collected_slots'] / SLOTS_PER_DAY, 2))
cases = {'7-day slice starting at s0': (S0, S0 + 7 * SLOTS_PER_DAY - 1),
         '7-day slice containing the window': (S0 - SLOTS_PER_DAY, S0 - SLOTS_PER_DAY + 7 * SLOTS_PER_DAY - 1),
         'exact window bounds': (plan['slot_min'], plan['slot_max'])}
for name, (lo, hi) in cases.items():
    with tempfile.TemporaryDirectory() as run:
        Path(run, 'manifest.json').write_text(json.dumps(dict(window=dict(address=bf.LAUNCHLAB_PROGRAM, slot_min=lo, slot_max=hi))))
        try:
            wc.export(run, Path(run) / 'pools', S0, pilot_dir=run)
            print(name, '-> ACCEPTED')
        except (bf.BackfillError, KeyError, FileNotFoundError) as exc:
            print(name, '->', type(exc).__name__, exc)
nxt = wc.bounds(S0 + wc.EVALUATION_SLOTS)
print('overlap with the next window (slots):', plan['slot_max'] - nxt['slot_min'] + 1,
      '= warm-up', wc.WARMUP_SLOTS, '+ gap', wc.GAP_SLOTS, '; collected/new ratio',
      round(plan['collected_slots'] / wc.EVALUATION_SLOTS, 4))
