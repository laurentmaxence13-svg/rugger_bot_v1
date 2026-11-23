import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'g1ind' / 'report.py').read_text()
MUT = [
 ("    g1 = dict(g1, meaning=SHEET_MEANING)", "    g1 = dict(g1)", 'meaning_kept'),
 ("    priced = counted(primary)                                 # K01: zero-sale rows COUNTED, raw unpriced refused", "    priced = [p for p in primary if 'net_return' in p]", 'primary_raw_excluded'),
 ("    if not g1['published_numbers']:", "    if False:", 'stop_publishes_numbers'),
 ("flag=UNDER_TARGET if g1['n_entered'] < target else None", "flag=UNDER_TARGET if g1['n_entered'] <= target else None", 'target_non_strict'),
 ("    wins = [r for r in nets if r > 0]", "    wins = [r for r in nets if r >= 0]", 'zero_is_a_win'),
 ("    losses = [r for r in nets if r <= 0]", "    losses = [r for r in nets if r < 0]", 'zero_not_a_loss'),
 ("profit_factor=(sum(wins) / negative) if negative else NM", "profit_factor=(len(wins) / len(losses)) if negative else NM", 'pf_counts'),
 ("key=lambda i: (exit_times[i], rows[i]['decision_slot'], rows[i]['pool']))", "key=lambda i: (rows[i]['decision_slot'], rows[i]['pool']))", 'dd_entry_order'),
 ("        sol += rows[i]['net_lamports']", "        sol += rows[i]['net_return']", 'dd_sol_in_stakes'),
 ("    return times[0] + hrr.clock_exit_latency_s(row['latency_slots'])", "    return times[0]", 'exit_no_latency'),
 ("    fired = ex['declared'] - row['latency_slots']", "    fired = ex['declared']", 'exit_slot_not_shifted'),
 ("        return line.swaps[row['decision_index']].block_time\n", "        return 0\n", 'refusal_time_zero'),
 ("    pools = {p['pool'] for p in primary} & {p['pool'] for p in placebo}", "    pools = {p['pool'] for p in primary} | {p['pool'] for p in placebo}", 'gap_unpaired_pools'),
 ("    low = W.lower_bound(groups, diff, seed=seed, draws=draws, alpha=ALPHA_DESCRIPTIVE)", "    low = W.lower_bound(groups, diff, seed=seed, draws=draws, alpha=ALPHA_DESCRIPTIVE / 3)", 'gap_alpha'),
 ("    low = W.lower_bound(groups, diff, seed=seed, draws=draws,", "    low = W.lower_bound(groups, diff, seed=seed + 1, draws=draws,", 'gap_seed'),
 ("        if sorted(map(_key, rows)) != keys:", "        if False:", 'sensitivity_any_decisions'),
 ("        if not all(SUPPLIED[name](p) for p in rows):", "        if False:", 'sensitivity_parameter_unchecked'),
 ("p.get('latency_slots') == CC.SENSITIVITY_LATENCY_SLOTS", "p.get('latency_slots') == CC.LATENCY_SLOTS", 'latency_4_accepted'),
 ("or p['failures']['cleanup'] == CA.MAX_CLEANUP_ATTEMPTS)", "or True)", 'rent_lost_unchecked'),
 ("p.get('guard_ppm') == CC.BUY_GUARD_SENSITIVITY_PPM", "p.get('guard_ppm') is not None", 'guard_any'),
 ("        if name not in SUPPLIED:\n            raise ReportError('unknown_sensitivity:' + name)\n", "", 'unknown_sensitivity_accepted'),
 ("    best = sorted(by_pool, key=lambda k: (-sum(by_pool[k]), k))[:5]", "    best = sorted(by_pool, key=lambda k: (-sum(by_pool[k]), k))[:4]", 'best_4_pools'),
 ("    best = sorted(by_pool, key=lambda k: (-sum(by_pool[k]), k))[:5]", "    best = sorted(by_pool, key=lambda k: (sum(by_pool[k]), k))[:5]", 'worst_pools_dropped'),
 ("first=_mean([p['net_return'] for p in primary_priced if p['decision_time'] < cut_time])", "first=_mean([p['net_return'] for p in primary_priced if p['decision_time'] <= cut_time])", 'half_boundary'),
 ("FORBIDDEN_WORDS = ('rentable', 'profitable', 'gagnant')", "FORBIDDEN_WORDS = ('rentable', 'profitable')", 'word_missing'),
 ("    return check_vocabulary(doc)\n", "    return doc\n", 'document_unchecked'),
 ("    out['frozen_mev_grid'] = MEV_NOT_MEASURED\n", "", 'mev_reason_dropped'),
 ("    g1 = CC.pilot_verdict(priced, g0_passed=g0_passed, freeze_sheet_sha256=freeze_sheet_sha256, draws=draws)", "    g1 = CC.pilot_verdict(priced, g0_passed=g0_passed, freeze_sheet_sha256=freeze_sheet_sha256)", 'draws_dropped'),
 ("    if hypothesis not in HYPOTHESES:\n        raise ReportError('unknown_hypothesis')\n", "", 'any_hypothesis'),
 ("    entered = [p for p in rows if p.get('status') not in ('guard_failed', ZERO_STATUS)]", "    entered = [p for p in rows if p.get('status') != 'guard_failed']", 'zero_rows_in_fee_split'),
 ("    entered = [p for p in rows if p.get('status') not in ('guard_failed', ZERO_STATUS)]", "    entered = [p for p in rows if p.get('status') != ZERO_STATUS]", 'refusals_in_fee_split'),
 ("        dd = drawdown(rows, [exit_time(by_pool[p['pool']], p) for p in rows])", "        dd = NM", 'dd_never_computed'),
 ("        if 'net_return' not in p:\n            raise ReportError('raw_unpriced_row_needs_the_runner_zero_sale:' + run)\n", "", 'raw_unpriced_accepted'),
 ("            raise ReportError('raw_unpriced_row_needs_the_runner_zero_sale:' + run)\n", "            return [q for q in rows if 'net_return' in q]\n", 'raw_unpriced_excluded'),
 ("        if p.get('status') == ZERO_STATUS and p.get('entered') is not True:", "        if False:", 'zero_sale_entry_unchecked'),
 ("            out[reason] = out.get(reason, 0) + 1", "            out[reason] = 1", 'reasons_not_counted'),
 ("        return row['decision_time'] + R.CLOCK_S + hrr.clock_exit_latency_s(CC.LATENCY_SLOTS)", "        return row['decision_time']", 'zero_exit_at_decision'),
 ("    placebo_priced = counted(placebo, 'placebo')", "    placebo_priced = [p for p in placebo if 'net_return' in p]", 'placebo_raw_excluded'),
 ("                                  or p['failures'] == dict(buy=CC.SENSITIVITY_FAILURES.buy,", "                                  or p['failures']['buy'] >= 1 and p['failures']['sell'] >= 1 or dict(buy=CC.SENSITIVITY_FAILURES.buy,", 'k2_at_least_one'),
 ("        values = counted(rows, name)", "        values = [p for p in rows if 'net_return' in p]", 'sensitivity_raw_excluded'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'g1ind' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'g1ind', base / 'g1ind')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'g1ind', work / 'g1ind')
    (work / 'g1ind' / 'report.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
