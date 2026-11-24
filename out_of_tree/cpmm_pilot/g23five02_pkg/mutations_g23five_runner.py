import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'g23five' / 'verdict.py').read_text()
MUT = [
 ("                rows += block_map[p][days[rng.randrange(len(days))]]", "                q = pools[rng.randrange(len(pools))]\n                rows += block_map[q][sorted(block_map[q])[rng.randrange(len(block_map[q]))]]", 'not_stratified'),
 ("            for _k in days:\n", "            for _k in days[:1]:\n", 'one_block_per_pool'),
 ("ALPHA, DRAWS = 0.05, 10_000", "ALPHA, DRAWS = 0.10, 10_000", 'alpha_10'),
 ("    k = max(0, int(ALPHA * draws) - 1)", "    k = max(0, int(ALPHA * draws))", 'quantile_shift'),
 ("    return sorted(means)[k], sorted(means, reverse=True)[k]", "    return sorted(means)[k], sorted(means)[-1]", 'upper_is_max'),
 ("    seed = int(freeze_sheet_sha256[:8], 16)", "    seed = 1", 'seed_not_from_sheet'),
 ("MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 3, 2.5, 0.5", "MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 29, 3, 2.5, 0.5", 'pool_days_29'),
 ("MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 3, 2.5, 0.5", "MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 2, 2.5, 0.5", 'pools_2'),
 ("MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 3, 2.5, 0.5", "MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 3, 2.4, 0.5", 'kish_2_4'),
 ("MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 3, 2.5, 0.5", "MIN_POOL_DAYS, MIN_POOLS, MIN_KISH, MAX_SHARE = 30, 3, 2.5, 0.6", 'share_0_6'),
 ("kish=kish >= MIN_KISH,", "kish=kish > MIN_KISH,", 'kish_strict'),
 ("max_share=share <= MAX_SHARE)", "max_share=share < MAX_SHARE)", 'share_strict'),
 ("    pool_days = len({(r['pool'], day_of(r, t0, d_days)) for r in ent})", "    pool_days = len(ent)", 'pool_days_are_rows'),
 ("    return [r for r in rows if r.get('entered', True) and r.get('status') != 'guard_failed']", "    return list(rows)", 'refusals_are_entries'),
 ("    return sorted(per_pool, key=lambda p: (-per_pool[p], p))[0] if per_pool else None", "    return sorted(per_pool, key=lambda p: (per_pool[p], p))[0] if per_pool else None", 'top_is_smallest'),
 ("    return sorted(per_pool, key=lambda p: (-per_pool[p], p))[0] if per_pool else None", "    return sorted(per_pool, key=lambda p: (-per_pool[p], [-ord(c) for c in p]))[0] if per_pool else None", 'top_tie_reversed'),
 ("    elif low is not None and low > 0 and low_wo is not None and low_wo > 0:", "    elif low is not None and low > 0:", 'no_leave_top_out'),
 ("    rest = [r for r in rows if r['pool'] != top]", "    rest = list(rows)", 'top_pool_kept'),
 ("    if not fl['passed']:\n        decision = 'INCONCLUSIF'\n    elif high is not None and high < 0:\n        decision = 'NO-GO'", "    if high is not None and high < 0:\n        decision = 'NO-GO'\n    elif not fl['passed']:\n        decision = 'INCONCLUSIF'", 'no_go_before_floors'),
 ("    elif high is not None and high < 0:", "    elif high is not None and high < -1:", 'no_go_never'),
 ("    if g0_passed is not True:", "    if g0_passed is False:", 'g0_truthy'),
 ("    rows = G1.counted(primary)                                    # K01: raw unpriced refused, zero sale checked", "    rows = list(primary)", 'primary_unchecked'),
 ("    plac = G1.counted(placebo, 'placebo')", "    plac = list(placebo)", 'placebo_unchecked'),
 ("    if not 0 <= day < d_days:", "    if not 0 <= day <= d_days:", 'window_end_included'),
 ("    if {r['pool'] for r in rows + plac} - set(pools):", "    if {r['pool'] for r in rows} - set(pools):", 'placebo_pools_unchecked'),
 ("    kept = sorted((p for p, c in counts.items() if c >= MIN_TRIGGERS), key=lambda p: (-counts[p], p))[:TOP_POOLS]", "    kept = sorted((p for p, c in counts.items() if c > MIN_TRIGGERS), key=lambda p: (-counts[p], p))[:TOP_POOLS]", 'select_strict'),
 ("MIN_TRIGGERS, TOP_POOLS, MIN_SELECTED = 3, 5, 3", "MIN_TRIGGERS, TOP_POOLS, MIN_SELECTED = 3, 4, 3", 'top_4'),
 ("MIN_TRIGGERS, TOP_POOLS, MIN_SELECTED = 3, 5, 3", "MIN_TRIGGERS, TOP_POOLS, MIN_SELECTED = 3, 5, 2", 'min_selected_2'),
 ("    kept = sorted((p for p, c in counts.items() if c >= MIN_TRIGGERS), key=lambda p: (-counts[p], p))[:TOP_POOLS]", "    kept = sorted((p for p, c in counts.items() if c >= MIN_TRIGGERS), key=lambda p: (-counts[p], [-ord(x) for x in p]))[:TOP_POOLS]", 'select_tie_reversed'),
 ("        b3 = G2.baseline_b3(line, txs, t0)", "        b3 = 1", 'b3_constant'),
 ("    if type(d_days) is not int or not MIN_D <= d_days <= MAX_D:", "    if type(d_days) is not int:", 'd_unchecked'),
 ("               power=dict(n_entered=len(entries(rows)), n_required=target,\n                          flag=G1.UNDER_TARGET if len(entries(rows)) < target else None),", "               power=dict(n_entered=len(entries(rows)), n_required=target, flag=None),", 'power_flag_dropped'),
 ("    return G1.check_vocabulary(doc)\n", "    return doc\n", 'vocabulary_unchecked'),
 # 0.1.1: the gap to the placebo (descriptive)
 ("        diffs.append(_resampled_mean(primary_blocks, rng) - _resampled_mean(placebo_blocks, rng))", "        diffs.append(_resampled_mean(primary_blocks, rng) - _mean([r for p in placebo_blocks for d in placebo_blocks[p] for r in placebo_blocks[p][d]]))", 'gap_placebo_not_resampled'),
 ("        diffs.append(_resampled_mean(primary_blocks, rng) - _resampled_mean(placebo_blocks, rng))", "        diffs.append(_resampled_mean(placebo_blocks, rng) - _resampled_mean(primary_blocks, rng))", 'gap_sign_reversed'),
 ("        for _d in days:\n", "        for _d in days[:1]:\n", 'gap_one_block_per_pool'),
 ("    tail = max(0, int(ALPHA * draws) - 1)", "    tail = max(0, int(ALPHA * draws))", 'gap_quantile_shift'),
 ("    return sorted(diffs)[tail], sorted(diffs, reverse=True)[tail]", "    return sorted(diffs)[tail], sorted(diffs)[-1]", 'gap_upper_is_max'),
 ("                                      seed=seed, draws=draws)", "                                      seed=seed + 1, draws=draws)", 'gap_seed_not_from_sheet'),
 ("blocks(plac, t0, d_days, block_days),", "blocks(rows, t0, d_days, block_days),", 'gap_placebo_is_primary'),
 # 0.2: block_days
 ("day_of(r, t0, d_days) // block_days, []).append(r)", "day_of(r, t0, d_days), []).append(r)", 'block_key_is_the_day'),
 ("    if type(block_days) is not int or block_days < 1 or d_days % block_days:", "    if False:", 'block_days_unchecked'),
 ("    if type(block_days) is not int or block_days < 1 or d_days % block_days:", "    if type(block_days) is not int or block_days < 1:", 'partial_last_block_allowed'),
 ("    low, high = stratified_bounds(blocks(rows, t0, d_days, block_days), seed=seed, draws=draws)", "    low, high = stratified_bounds(blocks(rows, t0, d_days), seed=seed, draws=draws)", 'main_bounds_one_day_blocks'),
 ("    low_wo, high_wo = stratified_bounds(blocks(rest, t0, d_days, block_days), seed=seed, draws=draws)", "    low_wo, high_wo = stratified_bounds(blocks(rest, t0, d_days), seed=seed, draws=draws)", 'guard_one_day_blocks'),
 ("    d_low, d_high = difference_bounds(blocks(rows, t0, d_days, block_days),", "    d_low, d_high = difference_bounds(blocks(rows, t0, d_days),", 'gap_primary_one_day_blocks'),
 ("def report(primary, placebo, *, pools, g0_passed, freeze_sheet_sha256, t0, d_days, draws=DRAWS, block_days=1):", "def report(primary, placebo, *, pools, g0_passed, freeze_sheet_sha256, t0, d_days, draws=DRAWS, block_days=2):", 'default_block_days_2'),
 ("seed=seed, draws=draws, block_days=block_days,", "seed=seed, draws=draws,", 'block_days_not_published'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'g23five' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
# the tests load the anchored 0.1.1 from the sibling directory (block_days = 1 identity)
shutil.copytree(D.parent / 'g23five_pkg' / 'g23five', M / 'g23five_pkg' / 'g23five', ignore=shutil.ignore_patterns('__pycache__'))
base = M / '_baseline'
shutil.copytree(D / 'g23five', base / 'g23five')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'g23five', work / 'g23five')
    (work / 'g23five' / 'verdict.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
