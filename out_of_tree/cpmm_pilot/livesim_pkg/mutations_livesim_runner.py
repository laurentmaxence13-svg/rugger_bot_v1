import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'livesim' / 'sim.py').read_text()
MUT = [
 ('    if PILOT_POOLS & set(pools):', '    if False:', 'pilot_pools_allowed'),
 ('    if not pools or len(set(pools)) != len(pools):', '    if False:', 'duplicates_allowed'),
 ('    swaps = tuple(s for s in line.swaps if s.block_time <= now)', '    swaps = tuple(line.swaps)', 'future_data_seen'),
 ('    idx = [i for i in G2.decisions_g23(known, txs, b3) if known.swaps[i].block_time >= start]', '    idx = list(G2.decisions_g23(known, txs, b3))', 'signals_before_start'),
 ('            if _slot is None and clock is not None and clock > now:', '            if False:', 'open_positions_valued'),
 ('            if _slot is None and clock is not None and clock > now:', '            if _slot is None and clock is not None and clock > now + 3_600:', 'open_threshold_shifted'),
 ("        return gross, gross - row['net_lamports']", "        return gross, -row['net_lamports']", 'costs_wrong'),
 ("    return 0.0, -row['net_lamports']", '    return 0.0, 0.0', 'refusal_costs_dropped'),
 ("    rows = sorted(closed, key=lambda r: (r['exit_time'], r['pool'], r['decision_index']))", '    rows = list(closed)', 'curve_not_by_exit_time'),
 ('    cum, peak, worst, curve = 0, 0, 0, [dict(time=None, capital_sol=0.0)]', '    cum, peak, worst, curve = 10 ** 10, 10 ** 10, 0, [dict(time=None, capital_sol=0.0)]', 'capital_not_from_zero'),
 ('        peak = max(peak, cum)', '        pass', 'peak_never_updated'),
 ('        worst = max(worst, peak - cum)', '        worst = max(worst, -cum)', 'drawdown_from_zero_only'),
 ("    wins = sum(1 for r in rows if r['net_lamports'] > 0)", "    wins = sum(1 for r in rows if r['net_lamports'] >= 0)", 'zero_counted_as_win'),
 ("                win_rate=wins / len(rows) if rows else NM,", "                win_rate=wins / max(1, sum(1 for r in rows if r.get('status') == 'entered')) if rows else NM,", 'win_rate_on_entered_only'),
 ("    return dict(signals=signals, entries=sum(1 for r in rows if r.get('status') in ('entered', 'unpriced_zero_sale')),", "    return dict(signals=signals, entries=len(rows),", 'refusals_are_entries'),
 ("                net_return_per_position=cum / (len(rows) * CC.STAKE_LAMPORTS) if rows else NM,", "                net_return_per_position=cum / (10 * 10 ** 9) if rows else NM,", 'return_on_10_sol'),
 ("                max_drawdown_sol=worst / 1e9, max_drawdown_stakes=worst / CC.STAKE_LAMPORTS,", "                max_drawdown_sol=worst / 1e9, max_drawdown_stakes=worst / 1e9,", 'drawdown_stakes_wrong'),
 ("        seen = [c['capital_sol'] for c in curve if c['time'] is not None and c['time'] <= t]", "        seen = [c['capital_sol'] for c in curve if c['time'] is not None and c['time'] < t]", 'by_hour_strict'),
 ("        out.append(dict(time=t, capital_sol=seen[-1] if seen else 0.0))", "        out.append(dict(time=t, capital_sol=seen[0] if seen else 0.0))", 'by_hour_first_not_last'),
 ('        days = max(1, math.ceil((t - start) / DAY_S))', '        days = 1', 'n1_one_day_only'),
 ('            pos = K.continuous_position(truncated(line, t), config, start_time=start, end_time=start + days * DAY_S)', '            pos = K.continuous_position(line, config, start_time=start, end_time=start + days * DAY_S)', 'n1_sees_the_future'),
 ('    t = start + step_s\n    while t <= now:\n        days', '    t = start\n    while t <= now:\n        days', 'n1_mark_at_start'),
 ("        if not gates[sim.pool]['admitted']:\n            continue", '        if False:\n            continue', 'gate_ignored'),
 ('    if not start < now:', '    if False:', 'now_unchecked'),
 ("    if g['primary']['signals'] == 0:", '    if False:', 'zero_message_dropped'),
 ('    return G1.check_vocabulary(doc)\n', '    return doc\n', 'vocabulary_unchecked'),
 ('            union = replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda s: s.key)),', '            union = replace(sim, swaps=tuple(sorted(sim.swaps, key=lambda s: s.key)),', 'n1_without_pre_state'),
 ("        if sim.pool in universe['kept']:", '        if True:', 'n1_ignores_its_universe'),
 ('        ok = med >= bar\n', '        ok = med > bar\n', 'n1_threshold_strict'),
 ('        ok = med >= bar\n', '        ok = True\n', 'n1_threshold_ignored'),
 ('        days = N1R.daily_rotation(line, start)', '        days = N1R.daily_rotation(line, start + 3_600)', 'n1_history_shifted'),
 ('            bar = N1R.break_even_rotation_r04_6(line, config, start)', '            bar = N1R.break_even_rotation(config)', 'n1_other_threshold'),
 ('                min_pools=N1R.MIN_POOLS, min_pools_met=len(kept) >= N1R.MIN_POOLS)', '                min_pools=N1R.MIN_POOLS, min_pools_met=True)', 'min_pools_always_met'),
 ("               n1=dict(universe=universe, observations=n1, stake_ppm=K.STAKE_PPM, result_12_days=NM,", "               n1=dict(universe=universe, observations=n1, stake_ppm=K.STAKE_PPM, result_12_days=None,", 'n1_12_days_given'),
 ("               limits=list(LIMITS), journal=journal)", "               limits=list(LIMITS[:6]), journal=journal)", 'a_limit_dropped'),
 ("              '', '## Limites (7)', ''] + ['- %s' % x for x in doc['limits']]", "              '', '## Limites (7)', '']", 'limits_not_rendered'),
 ('        if not path.is_file():\n            raise', '        if False:\n            raise', 'manifest_missing_ignored'),
 ('        if _sha(data) != sha:', '        if False:', 'manifest_sha_unchecked'),
 ('            if not f.is_file() or _sha(f.read_bytes()) != digest:', '            if not f.is_file():', 'listed_files_unchecked'),
 ('            if not f.is_file() or _sha(f.read_bytes()) != digest:', '            if _sha(f.read_bytes()) != digest if f.is_file() else False:', 'missing_file_ignored'),
 ('            if rel not in listed:', '            if False:', 'loaded_files_unchecked'),
 ('        if git_tree(locate(name)) != tree:', '        if False:', 'tree_unchecked'),
 ("        if child.name == '__pycache__':", "        if child.name == '__never__':", 'pycache_hashed'),
 ("            mode = b'100755' if os.access(child, os.X_OK) else b'100644'", "            mode = b'100644'", 'mode_ignored'),
 ([('    frozen = dict(manifests=check_frozen(), trees=check_trees())       # before any page is read\n', ''),
   ('    seed = _sha(', '    frozen = dict(manifests=check_frozen(), trees=check_trees())\n    seed = _sha(')], None, 'check_after_reading'),
 ('    if dict(manifests=check_frozen(), trees=check_trees()) != frozen:  # and after the run', '    if False:', 'no_check_after'),
 ("    'cpmmpilot': ('MANIFEST_cpmmpilot_v0_2_8.txt',", "    'cpmmpilotX': ('MANIFEST_cpmmpilot_v0_2_8.txt',", 'cpmmpilot_not_checked'),
 ('        pre, pre_txs = GR.window_line(x, rows[x][\'base_mint\'], a.pre_root / x, start=a.start - PRE_DAYS * DAY_S,', '        pre, pre_txs = GR.window_line(x, rows[x][\'base_mint\'], a.pre_root / x, start=a.start - 6 * DAY_S,', 'pre_window_6_days'),
 ("        b3[x] = G2.baseline_b3(pre, pre_txs, a.start)", "        b3[x] = 2", 'b3_not_recomputed'),
 ("if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or N1R.DAYS != PRE_DAYS or \\\n        N1R.R046_STAKE_PPM != K.STAKE_PPM:", "if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or N1R.DAYS != PRE_DAYS:", 'stake_ppm_unchecked'),
 ("if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or N1R.DAYS != PRE_DAYS or", "if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or", 'n1_days_unchecked'),
 ('    if a.out.exists():', '    if False:', 'out_overwritten'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'livesim' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'livesim', base / 'livesim', ignore=shutil.ignore_patterns('__pycache__'))
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
def pairs(old, new):
    return old if new is None else [(old, new)]
for old, new, name in MUT:
    for o, _n in pairs(old, new):
        assert src.count(o) == 1, name
def one(m):
    old, new, name = m
    work = M / name
    shutil.copytree(D / 'livesim', work / 'livesim', ignore=shutil.ignore_patterns('__pycache__'))
    text = src
    for o, n in pairs(old, new):
        text = text.replace(o, n)
    (work / 'livesim' / 'sim.py').write_text(text)
    return dict(mutant=name, detected=run(work).returncode != 0)
with ThreadPoolExecutor(4) as ex:
    out = list(ex.map(one, MUT))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
