import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cdgate' / 'gate.py').read_text()
MUT = [
 ("k for k, e in enumerate(events) if e.slot - creation_slot >= LATE_SLOTS and whole(events, k)", "k for k, e in enumerate(events) if e.slot - creation_slot >= LATE_SLOTS", 'not_whole_event'),
 ("if e.slot - creation_slot >= LATE_SLOTS and", "if e.slot - creation_slot > LATE_SLOTS and", 'age_strict'),
 ("rate, _evidence = causal_fee_rate(events[:k + 1])", "rate, _evidence = causal_fee_rate(events)", 'rate_reads_future'),
 ("return tier(rate) <= LOW_TIER_PPM, rate", "return tier(rate) < LOW_TIER_PPM, rate", 'tier_strict'),
 ("return tier(rate) <= LOW_TIER_PPM, rate", "return rate <= LOW_TIER_PPM, rate", 'raw_rate_comparison'),
 ("return int(round(rate / TIER_STEP_PPM)) * TIER_STEP_PPM", "return (rate // TIER_STEP_PPM) * TIER_STEP_PPM", 'tier_floor_not_round'),
 ("RULE = dict(id='TP7_SL5_CLOCK30', take_profit=0.07, stop_loss=0.05, clock_s=30)", "RULE = dict(id='TP7_SL5_CLOCK30', take_profit=0.07, stop_loss=0.05, clock_s=60)", 'clock_60'),
 ("            if events[k].block_time - facts['creation_block_time'] >= HW1_AGE_S:", "            if False:", 'hw1_600s_replayed'),
 ("n_ok=out['n'] >= LL.MIN_N,", "n_ok=True,", 'gate_without_n'),
 ("high_bound_ok=high is not None and high >= 0)", "high_bound_ok=out['mean_net_return'] is not None and out['mean_net_return'] >= 0)", 'gate_on_mean'),
 ("    gross_sale = (received * FEE_DENOMINATOR) // (FEE_DENOMINATOR - rate) if rate < FEE_DENOMINATOR else received", "    gross_sale = received", 'sell_fee_on_net'),
 ("    if LL.half_of(facts['creation_slot']) is None:", "    if False:", 'outside_range_read'),
 ("    if manifest_sha != manifest_sha256:", "    if False:", 'manifest_ignored'),
 ("        ok, rate = eligible(events, placebo)\n        if ok:", "        ok, rate = eligible(events, placebo)\n        if True:", 'placebo_unrestricted'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cdgate', work / 'cdgate')
    (work / 'cdgate' / 'gate.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cdgate' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
