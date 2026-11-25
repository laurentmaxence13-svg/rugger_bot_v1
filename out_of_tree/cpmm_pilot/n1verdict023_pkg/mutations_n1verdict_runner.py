import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'n1verdict' / 'verdict.py').read_text()
MUT = [
 ("    return -(Fraction(1) + Fraction(tx + rent, stake)) / d_days", "    return -(Fraction(1) + Fraction(tx, stake)) / d_days", 'rent_not_lost'),
 ("    return -(Fraction(1) + Fraction(tx + rent, stake)) / d_days", "    return -Fraction(1) / d_days", 'loss_without_transactions'),
 ("    return -(Fraction(1) + Fraction(tx + rent, stake)) / d_days", "    return -(Fraction(1) + Fraction(tx + rent, stake))", 'loss_not_spread'),
 ("        value = total_loss_per_day(stake0, d_days, failures)", "        value = total_loss_per_day(stake0, d_days)", 'loss_ignores_failures'),
 ("    return before[-1].quote_before * K.STAKE_PPM // 1_000_000", "    return before[0].quote_before * K.STAKE_PPM // 1_000_000", 'unpriced_stake_first_swap'),
 ("                     unpriced=str(err), net_return=float(value), stake_lamports=stake0) for k in range(d_days)], None", "                     unpriced=str(err), net_return=float(value), stake_lamports=stake0) for k in range(d_days - 1)], None", 'unpriced_days_dropped'),
 ("        return [dict(pool=line.pool, day=k, decision_time=t0 + k * DAY_S, status='unpriced_total_loss', entered=True,", "        return [dict(pool=line.pool, day=k, decision_time=t0 + k * DAY_S, status='unpriced_total_loss', entered=False,", 'unpriced_not_entries'),
 ("        if not (isinstance(err, _Undecoded) or _unpriced(err)):\n            raise\n", "        if False:\n            raise\n", 'every_error_is_a_loss'),
 ("    return any(isinstance(err, kind) and str(err) == reason for kind, reason in UNPRICED)", "    return any(str(err) == reason for kind, reason in UNPRICED)", 'kind_ignored'),
 ("    (LP.LpCostError, 'exit_state_empty'),\n", "", 'exit_state_empty_not_unpriced'),
 ("    if not before:\n        raise N1Error('pre_t0_state_missing')", "    if not before:\n        return 10 ** 9", 'pre_t0_unchecked'),
 ("                         entered=pos['entered'], net_return=float(d['gap_lamports'] / pos['stake_lamports']),", "                         entered=pos['entered'], net_return=float(d['gap_lamports'] / 10 ** 8),", 'gap_not_per_stake'),
 ("        pos = K.continuous_position(line, config, start_time=t0, end_time=t0 + d_days * DAY_S, failures=failures,", "        pos = K.continuous_position(line, config, start_time=t0, end_time=t0 + (d_days - 1) * DAY_S, failures=failures,", 'position_one_day_short'),
 ("    if [line.pool for line in lines] != list(pools):", "    if set(line.pool for line in lines) != set(pools):", 'order_unchecked'),
 ("BLOCK_DAYS = 2", "BLOCK_DAYS = 1", 'one_day_blocks'),
 ("    low_wo, high_wo = V.stratified_bounds(V.blocks([r for r in rows if r['pool'] != top], t0, d_days, BLOCK_DAYS),", "    low_wo, high_wo = V.stratified_bounds(V.blocks([r for r in rows if r['pool'] != top], t0, d_days),", 'guard_one_day_blocks'),
 ("    elif high is not None and high < 0:", "    elif high is not None and high < -1:", 'no_go_never'),
 ("    top = top_gap_pool(rows)", "    top = V.top_pool(rows)", 'k1_most_entries'),
 ("    return sorted(sums, key=lambda p: (-sums[p], p))[0] if sums else None", "    return sorted(sums, key=lambda p: (sums[p], p))[0] if sums else None", 'k1_smallest_sum'),
 ("    return sorted(sums, key=lambda p: (-sums[p], p))[0] if sums else None", "    return sorted(sums, key=lambda p: (-sums[p], [-ord(c) for c in p]))[0] if sums else None", 'k1_tie_reversed'),
 ("        sums[r['pool']] = sums.get(r['pool'], 0) + r['net_return']", "        sums[r['pool']] = max(sums.get(r['pool'], 0), r['net_return'])", 'k1_best_day_not_sum'),
 ("    elif low is not None and low > 0 and low_wo is not None and low_wo > 0:", "    elif low is not None and low > 0:", 'no_leave_top_out'),
 ("    if not fl['passed']:\n        decision = 'INCONCLUSIF'\n    elif high is not None and high < 0:\n        decision = 'NO-GO'", "    if high is not None and high < 0:\n        decision = 'NO-GO'\n    elif not fl['passed']:\n        decision = 'INCONCLUSIF'", 'no_go_before_floors'),
 ("    seed = int(freeze_sheet_sha256[:8], 16)", "    seed = int(freeze_sheet_sha256[-8:], 16)", 'seed_not_the_sheet_head'),
 ("    if g0_passed is not True:", "    if g0_passed is False:", 'g0_truthy'),
 ("    if type(d_days) is not int or not V.MIN_D <= d_days <= V.MAX_D or d_days % BLOCK_DAYS:", "    if type(d_days) is not int or not V.MIN_D <= d_days <= V.MAX_D:", 'odd_d_allowed'),
 ("    if len(pools) < V.MIN_SELECTED or len(set(pools)) != len(pools):", "    if len(pools) < V.MIN_SELECTED:", 'duplicate_pools'),
 ("guard_50000=dict(buy_guard_ppm=CC.BUY_GUARD_SENSITIVITY_PPM)", "guard_50000=dict(buy_guard_ppm=CC.BUY_GUARD_PPM)", 'guard_sensitivity_frozen'),
 ("                     rent_lost=dict(failures=CC.Failures(0, 0, LP.CA.MAX_CLEANUP_ATTEMPTS)))", "                     rent_lost=dict(failures=CC.Failures(0, 0, 1)))", 'rent_lost_one_cleanup'),
 ("               power=dict(n_entered=len(entered), n_required=target,\n                          flag=V.G1.UNDER_TARGET if len(entered) < target else None))", "               power=dict(n_entered=len(entered), n_required=target, flag=None))", 'power_flag_dropped'),
 ("    return V.G1.check_vocabulary(doc)\n", "    return doc\n", 'vocabulary_unchecked'),
 ("               labels=list(LP.LABELS), counts_for_operational_master=False, meaning=MEANING, scope=SCOPE,", "               labels=list(LP.LABELS), counts_for_operational_master=False, meaning=MEANING, scope='',", 'scope_dropped'),
 ("                costs_return=float(-(d['entry'] + d['exit'] + d['transactions'] + d['rent_lost']) / stake),", "                costs_return=float(-(d['entry'] + d['exit'] + d['transactions']) / stake),", 'costs_without_rent'),
]
MUT += [   # 0.2.3: the UNDECODED rule and the G-0 exclusion
 ("    if _span_hit(line, undecoded, t0, LP.landing_time(t0, latency_slots)):\n        return 'undecoded_transaction_at_entry'", "    if False:\n        return 'undecoded_transaction_at_entry'", 'undecoded_entry_not_checked'),
 ("    if _span_hit(line, undecoded, land_out - 1, land_out):\n        return 'undecoded_transaction_at_exit'", "    if False:\n        return 'undecoded_transaction_at_exit'", 'undecoded_exit_not_checked'),
 ("    return any(low < u and (high is None or u < high) for u in undecoded)", "    return any(low < u for u in undecoded)", 'undecoded_span_unbounded'),
 ("    return any(low < u and (high is None or u < high) for u in undecoded)", "    return any(high is None or u < high for u in undecoded)", 'undecoded_span_no_low'),
 ("    high = after[0].key[:2] if after else None", "    high = after[-1].key[:2] if after else None", 'undecoded_span_last_swap'),
 ("    low = done[-1].key[:2] if done else (-1, -1)", "    low = done[0].key[:2] if done else (-1, -1)", 'undecoded_low_first_swap'),
 ("        if not (isinstance(err, _Undecoded) or _unpriced(err)):", "        if not _unpriced(err):", 'undecoded_raises'),
 ("undecoded=(undecoded or {}).get(line.pool, ()), **kw)", "undecoded=(), **kw)", 'undecoded_not_passed'),
 ("        alt, _w = positions(lines, config, pools=kept, t0=t0, d_days=d_days, undecoded=undecoded, **kw)", "        alt, _w = positions(lines, config, pools=kept, t0=t0, d_days=d_days, **kw)", 'sensitivities_ignore_undecoded'),
 ("    if set(excluded) - set(pools):", "    if False:", 'excluded_not_named_unchecked'),
 ("    kept = [p for p in pools if p not in excluded]", "    kept = list(pools)", 'excluded_kept'),
 ("    for p in excluded:\n        per_pool[p] =", "    for p in ():\n        per_pool[p] =", 'excluded_not_in_per_pool'),
 ("    if excluded:\n        doc['g0_excluded']", "    if False:\n        doc['g0_excluded']", 'excluded_not_published'),
 ("        per_pool[p] = dict(status='excluded_by_g0', g0_reasons=list(excluded[p]), pool_days=0, entries=0)", "        per_pool[p] = dict(status='excluded_by_g0', g0_reasons=[], pool_days=0, entries=0)", 'excluded_reasons_dropped'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'n1verdict' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D.parent / 'n1verdict_pkg' / 'n1verdict', M / 'n1verdict_pkg' / 'n1verdict',
                ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)   # the anchored 0.2.2 (identity test)
shutil.copytree(D / 'n1verdict', base / 'n1verdict')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'n1verdict', work / 'n1verdict')
    (work / 'n1verdict' / 'verdict.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
