import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'n1verdict' / 'lines.py').read_text()
MUT = [
 ("            if side == 'pre' and when >= t0:", "            if side == 'pre' and when > t0:", 'pre_t0_second_allowed'),
 ("            if side == 'window' and not t0 <= when < t0 + d_days * N.DAY_S:", "            if side == 'window' and not t0 <= when <= t0 + d_days * N.DAY_S:", 'window_end_included'),
 ("            if side == 'window' and not t0 <= when < t0 + d_days * N.DAY_S:", "            if side == 'window' and not t0 - 3_600 <= when < t0 + d_days * N.DAY_S:", 'window_start_earlier'),
 ("    if set(pre) & set(window):\n        raise LinesError('signature_on_both_sides')\n    return TL.build(", "    if False:\n        raise LinesError('signature_on_both_sides')\n    return TL.build(", 'both_sides_allowed'),
 ("    if set(pre) & set(window):\n        raise LinesError('signature_on_both_sides')\n    union", "    if False:\n        raise LinesError('signature_on_both_sides')\n    union", 'both_sides_allowed_023'),
 ("    if not pages:\n        raise LinesError('no_%s_page' % side)", "    if False:\n        raise LinesError('no_%s_page' % side)", 'empty_side_allowed'),
 ("            if type(when) is not int:\n                raise LinesError('transaction_without_block_time')", "            if when is None:\n                when = t0 - 1", 'missing_time_tolerated'),
 ("            for p in pools]", "            for p in sorted(pools)]", 'order_not_the_sheet'),
 ("    if missing:\n        raise LinesError('a_named_pool_is_missing_from_the_selection')", "    if False:\n        raise LinesError('a_named_pool_is_missing_from_the_selection')", 'missing_pool_tolerated'),
 ("    if a.result.exists() or a.reconstruction.exists():", "    if False:", 'result_overwritten'),
 ("    if a.result.exists() or a.reconstruction.exists():", "    if a.result.exists():", 'reconstruction_overwritten'),
 ("    if u2.get('t0_time') != T0:", "    if False:", 't0_unchecked'),
 ("    if hashlib.sha256('\\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:", "    if False:", 'list_sha_unchecked'),
 ("    doc = N.report(lines, config, pools=list(POOLS), g0_passed=g0_passed,", "    doc = N.report(lines, config, pools=list(POOLS), g0_passed=True,", 'g0_ignored'),
 ("                                                            t0=T0, d_days=D_DAYS)", "                                                            t0=T0, d_days=D_DAYS + 2)", 'window_length_wrong'),
 ("    return TL.build(pool, {**pre, **window}, base_mint=base_mint)", "    return TL.build(pool, window, base_mint=base_mint)", 'pre_t0_dropped'),
 ("    print(hashlib.sha256(text.encode()).hexdigest(), a.result)", "    print(hashlib.sha256(text[:-1].encode()).hexdigest(), a.result)", 'printed_sha_wrong'),
]
MUT += [   # 0.2.3: cpmmrecon before the positions, G-0 computed, RECONSTRUCTION.json
 ("        lines[p], rep_u = rebuilt(u_line, u_txs, by_pool[p], config)", "        lines[p], rep_u = u_line, rebuilt(u_line, u_txs, by_pool[p], config)[1]", 'union_not_rebuilt'),
 ("        w_new, rep_w = rebuilt(w_line, w_txs, by_pool[p], config)", "        w_new, rep_w = w_line, rebuilt(w_line, w_txs, by_pool[p], config)[1]", 'window_not_rebuilt'),
 ("    gates, g0_passed = gate(windows, config)", "    gates, g0_passed = gate([lines[p] for p in pools], config)", 'g0_on_the_union'),
 ("        undecoded[p] = undecoded_keys(lines[p], u_txs)", "        undecoded[p] = undecoded_keys(u_line, u_txs)", 'undecoded_before_rebuild'),
 ("    return [lines[p] for p in pools if p not in excluded], undecoded", "    return [lines[p] for p in pools], undecoded", 'excluded_lines_kept'),
 ("            out[line.pool] = dict(admitted=False, reasons=['integrity_failure:%s' % exc])\n            ok = False", "            out[line.pool] = dict(admitted=False, reasons=['integrity_failure:%s' % exc])\n            ok = True", 'integrity_failure_swallowed'),
 ("    excluded = {p: gates[p]['reasons'] for p in pools if not gates[p]['admitted']}", "    excluded = {}", 'nothing_excluded'),
 ("    except CC.CostError:\n        side = None", "    except ZeroDivisionError:\n        side = None", 'creator_side_error_raises'),
 ("            kept[why] = kept.get(why, 0) + 1", "            kept[why] = 1", 'kept_not_counted'),
 ("rebuilt=sum(1 for v in rep.values() if v.startswith('rebuilt'))", "rebuilt=len(rep)", 'rebuilt_counts_kept'),
 ("rebuilt_swaps=len(new.swaps) - len(line.swaps)", "rebuilt_swaps=len(new.swaps)", 'rebuilt_swaps_total'),
 ("wsol_vault=row['wsol_vault']", "wsol_vault=row['base_mint']", 'wsol_vault_wrong'),
 ("fees=CC.fees_from_amm_config(config), on_input=side)", "fees=CC.fees_from_amm_config(config), on_input=not side)", 'creator_side_flipped'),
 ("fees=CC.fees_from_amm_config(config), on_input=side)", "fees=CC.fees_from_amm_config(dict(config, trade_fee_rate=config['trade_fee_rate'] + 1)), on_input=side)", 'fees_altered'),
 ("                          kept={'kept:not_tried_creator_side': len(line.skipped)}, transactions={})", "                          kept={}, transactions={})", 'not_tried_unreported'),
 ("        report[p]['g0'] = gates[p]", "        report[p]['g0'] = {}", 'g0_not_in_reconstruction'),
("undecoded_after=len(undecoded[p]),", "undecoded_after=0,", 'undecoded_count_dropped'),
 ("t0=T0, d_days=D_DAYS, undecoded=undecoded, excluded=excluded)", "t0=T0, d_days=D_DAYS, undecoded=None, excluded=excluded)", 'undecoded_not_to_the_verdict'),
 ("t0=T0, d_days=D_DAYS, undecoded=undecoded, excluded=excluded)", "t0=T0, d_days=D_DAYS, undecoded=undecoded, excluded=None)", 'excluded_not_to_the_verdict'),
 ("dict(schema=RECONSTRUCTION_SCHEMA, g0_passed=g0_passed, pools=recon)", "dict(schema=RECONSTRUCTION_SCHEMA, g0_passed=g0_passed, pools={})", 'reconstruction_empty'),
 ("dict(schema=RECONSTRUCTION_SCHEMA, g0_passed=g0_passed, pools=recon)", "dict(schema=RECONSTRUCTION_SCHEMA, g0_passed=True, pools=recon)", 'reconstruction_g0_fixed'),
 ("    return sum(1 for k in range(1, d_days) if", "    return sum(1 for k in range(0, d_days) if", 'marks_from_day_0'),
 ("    return sum(1 for k in range(1, d_days) if", "    return sum(1 for k in range(1, d_days + 1) if", 'marks_to_day_d'),
 ("N._span_hit(line, undecoded, t0 + k * N.DAY_S, t0 + k * N.DAY_S))", "N._span_hit(line, undecoded, t0 + k * N.DAY_S, t0 + k * N.DAY_S + N.DAY_S))", 'marks_span_a_day'),
 ("                         undecoded_marks=marks_touched(lines[p], undecoded[p], t0=t0, d_days=d_days))", "                         undecoded_marks=0)", 'marks_not_published'),
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
    (work / 'n1verdict' / 'lines.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
