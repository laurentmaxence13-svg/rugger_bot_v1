import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'livesim' / 'sim.py').read_text()
MUT = [
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
 ('                win_rate=wins / len(rows) if rows else NM,', "                win_rate=wins / max(1, sum(1 for r in rows if r.get('status') == 'entered')) if rows else NM,", 'win_rate_on_entered_only'),
 ("    return dict(signals=signals, entries=sum(1 for r in rows if r.get('status') in ('entered', 'unpriced_zero_sale')),", '    return dict(signals=signals, entries=len(rows),', 'refusals_are_entries'),
 ('                net_return_per_position=cum / (len(rows) * CC.STAKE_LAMPORTS) if rows else NM,', '                net_return_per_position=cum / (10 * 10 ** 9) if rows else NM,', 'return_on_10_sol'),
 ('                max_drawdown_sol=worst / 1e9, max_drawdown_stakes=worst / CC.STAKE_LAMPORTS,', '                max_drawdown_sol=worst / 1e9, max_drawdown_stakes=worst / 1e9,', 'drawdown_stakes_wrong'),
 ("        seen = [c['capital_sol'] for c in curve if c['time'] is not None and c['time'] <= t]", "        seen = [c['capital_sol'] for c in curve if c['time'] is not None and c['time'] < t]", 'by_hour_strict'),
 ('        out.append(dict(time=t, capital_sol=seen[-1] if seen else 0.0))', '        out.append(dict(time=t, capital_sol=seen[0] if seen else 0.0))', 'by_hour_first_not_last'),
 ('        days = max(1, math.ceil((t - start) / DAY_S))', '        days = 1', 'n1_one_day_only'),
 ('            pos = K.continuous_position(truncated(line, t), config, start_time=start, end_time=start + days * DAY_S)', '            pos = K.continuous_position(line, config, start_time=start, end_time=start + days * DAY_S)', 'n1_sees_the_future'),
 ('    t = start + step_s\n    while t <= now:\n        days', '    t = start\n    while t <= now:\n        days', 'n1_mark_at_start'),
 ('    if not start < now:', '    if False:', 'now_unchecked'),
 ("    if g['primary']['signals'] == 0:", '    if False:', 'zero_message_dropped'),
 ('            union = replace(sim, swaps=tuple(sorted(pre.swaps + sim.swaps, key=lambda s: s.key)),', '            union = replace(sim, swaps=tuple(sorted(sim.swaps, key=lambda s: s.key)),', 'n1_without_pre_state'),
 ('        ok = med >= bar\n', '        ok = med > bar\n', 'n1_threshold_strict'),
 ('        ok = med >= bar\n', '        ok = True\n', 'n1_threshold_ignored'),
 ('        days = N1R.daily_rotation(line, start)', '        days = N1R.daily_rotation(line, start + 3_600)', 'n1_history_shifted'),
 ('                min_pools=N1R.MIN_POOLS, min_pools_met=len(kept) >= N1R.MIN_POOLS)', '                min_pools=N1R.MIN_POOLS, min_pools_met=True)', 'min_pools_always_met'),
 ('        if not path.is_file():\n            raise', '        if False:\n            raise', 'manifest_missing_ignored'),
 ('        if _sha(data) != sha:', '        if False:', 'manifest_sha_unchecked'),
 ('            if not f.is_file() or _sha(f.read_bytes()) != digest:', '            if not f.is_file():', 'listed_files_unchecked'),
 ('            if not f.is_file() or _sha(f.read_bytes()) != digest:', '            if _sha(f.read_bytes()) != digest if f.is_file() else False:', 'missing_file_ignored'),
 ('            if rel not in listed:', '            if False:', 'loaded_files_unchecked'),
 ('        if git_tree(locate(name)) != tree:', '        if False:', 'tree_unchecked'),
 ("        if child.name == '__pycache__':", "        if child.name == '__never__':", 'pycache_hashed'),
 ("            mode = b'100755' if os.access(child, os.X_OK) else b'100644'", "            mode = b'100644'", 'mode_ignored'),
 ([('    frozen = dict(manifests=check_frozen(), trees=check_trees())       # before any page is read\n', ''), ('    seed = _sha(', '    frozen = dict(manifests=check_frozen(), trees=check_trees())\n    seed = _sha(')], None, 'check_after_reading'),
 ('    if dict(manifests=check_frozen(), trees=check_trees()) != frozen:  # and after the run', '    if False:', 'no_check_after'),
 ("    'cpmmpilot': ('MANIFEST_cpmmpilot_v0_2_8.txt',", "    'cpmmpilotX': ('MANIFEST_cpmmpilot_v0_2_8.txt',", 'cpmmpilot_not_checked'),
 ('if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or N1R.DAYS != PRE_DAYS or \\\n        N1R.R046_STAKE_PPM != K.STAKE_PPM:', 'if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or N1R.DAYS != PRE_DAYS:', 'stake_ppm_unchecked'),
 ('if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or N1R.DAYS != PRE_DAYS or', 'if CC.STAKE_LAMPORTS != 10 ** 8 or R.COUNT_DAYS != PRE_DAYS or', 'n1_days_unchecked'),
 ('    if a.out.exists():', '    if False:', 'out_overwritten'),
 ('    if FORBIDDEN_POOLS & set(pools):', '    if PILOT_POOLS & set(pools):', 'forbidden_2ylfom_allowed'),
 ('    if FORBIDDEN_POOLS & set(pools):', '    if False:', 'pilot_pools_allowed'),
 ("    eligible = [x for x in pools if gates[x]['admitted'] and b3[x] > 0]", '    eligible = [x for x in pools if b3[x] > 0]', 'gate_ignored'),
 ("    eligible = [x for x in pools if gates[x]['admitted'] and b3[x] > 0]", "    eligible = [x for x in pools if gates[x]['admitted']]", 'b3_zero_eligible'),
 ('    if len(eligible) < MIN_ELIGIBLE:\n        doc.update(', '    if len(eligible) < 2:\n        doc.update(', 'two_eligible_enough'),
 ('        doc.update(status=NON_EVALUABLE, g23=None, n1=None, journal=None,', '        doc.update(status=NON_EVALUABLE, n1=None, journal=None,', 'non_evaluable_keeps_figures'),
 ('    if set(configs) != set(pools) or set(b3) != set(pools):', '    if False:', 'configs_unchecked'),
 ('        got = g23_rows(sim, sim_txs, configs[sim.pool], b3[sim.pool], seed_sha, start=start, now=now)', '        got = g23_rows(sim, sim_txs, configs[pools[0]], b3[sim.pool], seed_sha, start=start, now=now)', 'g23_first_pool_config'),
 ('    gates = {sim.pool: CC.pool_gate(truncated(sim, now), configs[sim.pool]) for _p, _t, sim, _s in pairs}', '    gates = {sim.pool: CC.pool_gate(truncated(sim, now), configs[pools[0]]) for _p, _t, sim, _s in pairs}', 'gate_first_pool_config'),
 ('            n1[sim.pool] = n1_observations(union, configs[sim.pool], start=start, now=now)', '            n1[sim.pool] = n1_observations(union, configs[pools[0]], start=start, now=now)', 'n1_first_pool_config'),
 ("    n1_pools = [x for x in universe['kept'] if x in eligible]", '    n1_pools = list(eligible)', 'n1_ignores_its_universe'),
 ("    n1_pools = [x for x in universe['kept'] if x in eligible]", "    n1_pools = list(universe['kept'])", 'n1_ignores_eligibility'),
 ('        if sim.pool in n1_pools and len(n1_pools) >= N1R.MIN_POOLS:', '        if sim.pool in n1_pools:', 'n1_floor_ignored'),
 ('            bar = N1R.break_even_rotation_r04_6(line, configs[line.pool], start)', '            bar = N1R.break_even_rotation(configs[line.pool])', 'n1_other_threshold'),
 ('                       result_12_days=NM,', '                       result_12_days=None,', 'n1_12_days_given'),
 ("               amm_config_sha256={x: configs[x]['sha256'] for x in pools}, limits=list(LIMITS),", "               amm_config_sha256={x: configs[x]['sha256'] for x in pools}, limits=list(LIMITS[:6]),", 'a_limit_dropped'),
 ("    lines += ['', '## Limites (7)', ''] + ['- %s' % x for x in doc['limits']]", "    lines += ['', '## Limites (7)', '']", 'limits_not_rendered'),
 ("        doc.update(status=NON_EVALUABLE, g23=None, n1=None, journal=None,\n                   conduct='moins de %d pools éligibles (G-0 admis et b₃ > 0) : aucun chiffre de P&L' % MIN_ELIGIBLE)\n        return G1.check_vocabulary(doc)", "        doc.update(status=NON_EVALUABLE, g23=None, n1=None, journal=None,\n                   conduct='moins de %d pools éligibles (G-0 admis et b₃ > 0) : aucun chiffre de P&L' % MIN_ELIGIBLE)\n        return doc", 'vocabulary_unchecked_non_evaluable'),
 ('               journal=journal)\n    return G1.check_vocabulary(doc)', '               journal=journal)\n    return doc', 'vocabulary_unchecked'),
 ("               placebo_note='témoin retiré", "               placebo_note='témoin", 'placebo_redraw_not_declared'),
 ("                  '- %s.' % doc['placebo_note'], '',", "                  '',", 'placebo_note_not_rendered'),
 ('    line, txs = GR.window_line(pool, mint, d, start=start - PRE_DAYS * DAY_S, end=start)', '    line, txs = GR.window_line(pool, mint, d, start=start - 6 * DAY_S, end=start)', 'pre_window_6_days'),
 ('    if file_sha(path) != LIST_L_SHA256:', '    if False:', 'list_l_unchecked'),
 ("    row = dict(rows[0], amm_config=list_l['configs'][rows[0]['config']])", "    row = dict(rows[0], amm_config=list_l['configs'][list_l['list'][0]['config']])", 'config_of_the_first_row'),
 ("    if len(rows) != 1:\n        raise SimError('pool_not_once", "    if not rows:\n        raise SimError('pool_not_once", 'duplicate_list_l_row'),
 ("    if _sha('\\n'.join(pools).encode()) != q['list_sha256']:", '    if False:', 'qualified_sha_unchecked'),
 ("        if c['window'] != [start + i * CHUNK_S, start + (i + 1) * CHUNK_S] or c['name'] != 'live_%03d' % i:", '        if False:', 'chunks_not_checked'),
 ("            if not c['done']:", '            if False:', 'undone_chunk_used'),
 ("    if not out or out[-1]['window'][1] != now or now > start + LIVE_S:", '    if not out or now > start + LIVE_S:', 'now_between_chunks'),
 ("    if not out or out[-1]['window'][1] != now or now > start + LIVE_S:", "    if not out or out[-1]['window'][1] != now:", 'beyond_24h'),
 ("        _line, got = GR.window_line(pool, mint, d, start=c['window'][0], end=c['window'][1])", "        _line, got = GR.window_line(pool, mint, d, start=c['window'][0] - 3_600, end=c['window'][1] + 3_600)", 'chunk_window_loose'),
 ("        ok = gate['admitted'] and b3 > 0\n", '        ok = b3 > 0\n', 'eligible_without_gate'),
 ("        ok = gate['admitted'] and b3 > 0\n", "        ok = gate['admitted']\n", 'eligible_with_b3_zero'),
 ('        gate = CC.pool_gate(pre, cfg)', "        gate = CC.pool_gate(pre, pool_config(list_l, col['pools'][0]))", 'eligible_gate_config'),
 ('                evaluable=len(eligible) >= MIN_ELIGIBLE, min_eligible=MIN_ELIGIBLE,', '                evaluable=True, min_eligible=MIN_ELIGIBLE,', 'evaluable_always'),
 ("    if eligible_doc['t_start'] != col['t_start'] or eligible_doc['qualified_sha256'] != col['qualified_sha256']:", "    if eligible_doc['t_start'] != col['t_start']:", 'qualified_sha_not_compared'),
 ("    if eligible_doc['t_start'] != col['t_start'] or eligible_doc['qualified_sha256'] != col['qualified_sha256']:", "    if eligible_doc['qualified_sha256'] != col['qualified_sha256']:", 't_start_not_compared'),
 ("    if not set(pools) <= set(col['pools']) or [x for x in col['pools'] if x in pools] != pools:", "    if not set(pools) <= set(col['pools']):", 'order_unchecked'),
 ('    if len(pools) < MIN_ELIGIBLE:\n        raise', '    if len(pools) < 1:\n        raise', 'bilan_below_3'),
 ("        if sha != recorded[x]['pre_pages_sha256'] or b3[x] != recorded[x]['b3']:", "        if b3[x] != recorded[x]['b3']:", 'pre_pages_unchecked'),
 ("        if sha != recorded[x]['pre_pages_sha256'] or b3[x] != recorded[x]['b3']:", "        if sha != recorded[x]['pre_pages_sha256']:", 'b3_unchecked'),
 ('        b3[x] = G2.baseline_b3(pre, pre_txs, start)', "        b3[x] = recorded[x]['b3']", 'b3_not_recomputed'),
 ('        if file_sha(a.eligible) != a.eligible_sha:', '        if False:', 'eligible_sha_unchecked'),
 ('    if file_sha(result_path) != N1ROT_RESULT_SHA256:', '    if False:', 'identity_result_unanchored'),
 ("    diffs = [k for k in ('kept', 'list_sha256') if mine[k] != ref[k]]", '    diffs = []', 'identity_kept_not_compared'),
 ("    keys = ('pool', 'kept', 'median_rotation_exact', 'threshold_exact', 'days')", "    keys = ('pool', 'kept', 'median_rotation_exact', 'days')", 'identity_threshold_not_compared'),
 ('                identical=not diffs, differences=diffs,', '                identical=True, differences=diffs,', 'identity_always'),
 ('    mine = n1_universe([lines[x] for x in N1R.NAMED_POOLS], {x: config for x in N1R.NAMED_POOLS}, t0_time)', '    mine = n1_universe(list(lines.values()), {x: config for x in N1R.NAMED_POOLS}, t0_time)', 'identity_order'),
 ('N_MIN = 30 ', 'N_MIN = 29 ', 'n_min_29'),
 ('capital_end_sol=cum / 1e9, n_insufficient=len(rows) < N_MIN)', 'capital_end_sol=cum / 1e9, n_insufficient=len(rows) <= N_MIN)', 'n_insufficient_at_30'),
 ("            if m['n_insufficient']:\n", '            if False:\n', 'n_insufficient_not_rendered'),
 ('    n1_pool_days = len(n1) * math.ceil((now - start) / DAY_S)', '    n1_pool_days = len(n1_pools) * math.ceil((now - start) / DAY_S)', 'n1_pool_days_unmarked_counted'),
 ('pool_days=n1_pool_days, n_insufficient=n1_pool_days < N_MIN,', 'pool_days=n1_pool_days, n_insufficient=False,', 'n1_n_insufficient_never'),
 ("    'faut.',\n", "    'faut',\n", 'limit_text_altered'),
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
