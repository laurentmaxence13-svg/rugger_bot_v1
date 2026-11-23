import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cpmmprereg' / 'rule.py').read_text()
MUT = [
 ("DROP = Fraction(-3, 100)", "DROP = Fraction(-1, 100)", 'drop_threshold_1pct'),
 ("        if recent < MIN_SWAPS_IN_LOOKBACK:", "        if False:", 'activity_ignored'),
 ("        if last_open is not None and t - last_open < COOLDOWN_S:", "        if False:", 'cooldown_ignored'),
 ("        if not refs:\n            continue", "        if not refs:\n            refs = [0]", 'no_reference_accepted'),
 ("        if spot_after(line, i, fees) / spot_after(line, refs[-1], fees) - 1 <= DROP:", "        if spot_after(line, i, fees) / spot_after(line, refs[0], fees) - 1 <= DROP:", 'oldest_reference'),
 ("        if ratio >= TP or ratio <= SL:", "        if ratio >= TP:", 'stop_loss_ignored'),
 ("        if ratio >= TP or ratio <= SL:", "        if ratio <= SL:", 'take_profit_ignored'),
 ("            return swap.slot + latency_slots, None", "            return swap.slot, None", 'exit_latency_ignored'),
 ("    return None, deadline + hrr.clock_exit_latency_s(latency_slots)", "    return None, deadline", 'clock_latency_ignored'),
 ("            return swap.slot + latency_slots, None", "            return swap.slot + CC.LATENCY_SLOTS, None", 'exit_latency_sensitivity_ignored'),
 ("    return None, deadline + hrr.clock_exit_latency_s(latency_slots)", "    return None, deadline + CLOCK_LATENCY_S", 'clock_latency_sensitivity_ignored'),
 ("    land = decision.slot + latency_slots * (1 + buy_failures)", "    land = decision.slot + latency_slots", 'exit_buy_failure_delay_ignored'),
 ("              buy_guard_ppm=CC.BUY_GUARD_PPM):", "              buy_guard_ppm=None):", 'guard_off_by_default'),
 ("                              latency_slots=latency_slots, buy_guard_ppm=buy_guard_ppm)", "                              latency_slots=latency_slots)", 'guard_sensitivity_not_passed'),
 ("        row = CC.position(line, i, config, exit_slot=exit_slot, exit_time=exit_time, failures=failures,", "        row = CC.position(line, i, config, exit_slot=exit_slot, exit_time=exit_time,", 'failures_not_passed'),
 ("        if any(s.block_time >= t0 for s in line.swaps):", "        if False:", 'data_after_t0_accepted'),
 ("        per_pool[line.pool] = sum(1 for i in decisions(line, config) if line.swaps[i].block_time >= start)", "        per_pool[line.pool] = len(decisions(line, config))", 'count_before_the_7_days'),
 ("        per_pool[line.pool] = sum(1 for i in decisions(line, config) if line.swaps[i].block_time >= start)", "        per_pool[line.pool] = sum(1 for i in decisions(line, config) if line.swaps[i].block_time > start)", 'count_start_excluded'),
 ("        if line.pool in per_pool:", "        if False:", 'duplicate_pool_accepted'),
 ("    return count['triggers'] * pilot_days // COUNT_DAYS", "    return count['triggers']", 'expected_not_scaled'),
 ("    return count['triggers'] * pilot_days // COUNT_DAYS", "    return -(-count['triggers'] * pilot_days // COUNT_DAYS)", 'expected_rounded_up'),
 ("    if count.get('outcomes_computed') is not False or count.get('days') != COUNT_DAYS:", "    if False:", 'expected_from_anything'),
 ("    sigma_c = max(float(sigma_pilot), SIGMA_FLOOR)", "    sigma_c = SIGMA_FLOOR", 'sigma_pilot_ignored'),
 ("    sigma_c = max(float(sigma_pilot), SIGMA_FLOOR)", "    sigma_c = float(sigma_pilot)", 'sigma_floor_ignored'),
 ("                delta=DELTA_NET_PILOT, n=n_required(sigma=sigma_c, alpha=ALPHA_CONFIRMATION))", "                delta=DELTA_NET_PILOT, n=n_required(sigma=sigma_c))", 'confirmation_alpha_not_bonferroni'),
 ("    low_mean = W.lower_bound(groups, mean_rcp1, seed=seed, draws=draws, alpha=ALPHA_CONFIRMATION)", "    low_mean = W.lower_bound(groups, mean_rcp1, seed=seed, draws=draws, alpha=0.05)", 'c1_alpha_005'),
 ("    low_diff = W.lower_bound(groups, diff, seed=seed, draws=draws, alpha=ALPHA_CONFIRMATION)", "    low_diff = W.lower_bound(groups, mean_rcp1, seed=seed, draws=draws, alpha=ALPHA_CONFIRMATION)", 'c2_not_a_difference'),
 ("              all(h is not None and h > 0 for h in halves),", "              any(h is not None and h > 0 for h in halves),", 'c3_one_half_enough'),
 ("              unpriced == 0 and bool(primary),", "              bool(primary),", 'c4_unpriced_ignored'),
 ("              slow is not None and slow > 0 and without_best5 is not None and without_best5 > 0,", "              without_best5 is not None and without_best5 > 0,", 'c5_10_slots_ignored'),
 ("              one is not None and one > 0,", "              True,", 'a1_one_failure_ignored'),
 ("              point_diff is not None and point_diff > 0)", "              True)", 'a1_point_difference_ignored'),
 ("    entered = sum(1 for p in primary if p.get('entered', True) and 'net_return' in p)", "    entered = len(primary)", 'guard_failed_counted_as_entries'),
 ("    if sorted(map(_key, one_failure)) != keys or sorted(map(_key, ten_slots)) != keys:", "    if False:", 'sensitivities_unpaired'),
 ("    if {p['pool'] for p in placebo_} - {p['pool'] for p in primary}:", "    if False:", 'placebo_pools_unchecked'),
 ("    seed = int(freeze_sheet_sha256[:8], 16)\n    rows", "    seed = int(freeze_sheet_sha256[-8:], 16)\n    rows", 'seed_not_the_sheet_prefix'),
 ("        if all(abs(t - line.swaps[c].block_time) >= COOLDOWN_S for c in chosen):", "        if True:", 'placebo_cooldown_ignored'),
 ("    candidates = [i for i in range(len(line.swaps)) if has_reference(line, i)]", "    candidates = list(range(len(line.swaps)))", 'placebo_without_reference'),
 ("    if eligible_pools < MIN_ELIGIBLE_POOLS:", "    if eligible_pools < 10:", 'eligibility_floor_10'),
 ("    if expected_entries < 30:", "    if expected_entries < 10:", 'power_floor_10'),
 ("    if type(n_before) is not int or n_before + 1 > TRIAL_CAP:", "    if type(n_before) is not int or n_before > TRIAL_CAP:", 'trial_cap_off_by_one'),
 ("SIGMA_DECLARED = 0.025", "SIGMA_DECLARED = 0.02", 'sigma_changed'),
 ("        (first if line.swaps[p['decision_index']].block_time < cut_time else second).append(p['net_return'])", "        first.append(p['net_return'])", 'halves_not_split'),
]
base = subprocess.run([V, '-B', '-m', 'pytest', str(D / 'cpmmprereg' / 'tests'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                      cwd=W, env={'PYTHONPATH': f'{PP}:{D}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'},
                      capture_output=True, text=True, timeout=600)
if base.returncode != 0:
    print(base.stdout[-2000:], base.stderr[-2000:])
    raise SystemExit('baseline_does_not_pass: no mutant is run')
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cpmmprereg', work / 'cpmmprereg')
    (work / 'cpmmprereg' / 'rule.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cpmmprereg' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True, timeout=600)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
