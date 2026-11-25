import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'g23run' / 'run.py').read_text()
MUT = [
 ("            if not start <= when < end:", "            if not start <= when <= end:", 'window_end_included'),
 ("            if not start <= when < end:", "            if not start < when < end:", 'window_start_excluded'),
 ("    if not pages:\n        raise RunError('no_window_page')", "    if False:\n        raise RunError('no_window_page')", 'empty_window_allowed'),
 ("            if type(when) is not int:", "            if False:", 'block_time_unchecked'),
 ("            PILOT.zero_sale(dict(r, decision_slot=line.swaps[r['decision_index']].slot), failures) for r in rows]", "            PILOT.zero_sale(dict(r, decision_slot=line.swaps[r['decision_index']].slot)) for r in rows]", 'k01_ignores_failures'),
 ("        except CC.CostError as exc:\n            out.append(", "        except ValueError as exc:\n            raise\n            out.append(", 'exit_point_error_stops'),
 ("            out += R.positions(line, config, [i], **kw)", "            out += R.positions(line, config, [i])", 'variants_ignored'),
 ("               placebo=converted(line, positions_each(line, config, R.placebo(line, len(idx), sheet_sha))))", "               placebo=converted(line, positions_each(line, config, R.placebo(line, len(idx) + 1, sheet_sha))))", 'placebo_count_off'),
 ("                                                            latency_slots=CC.SENSITIVITY_LATENCY_SLOTS))", "                                                            latency_slots=CC.LATENCY_SLOTS))", 'c5_at_4_slots'),
 ("        out['a1_one_failure'] = converted(line, positions_each(line, config, idx, failures=CC.SENSITIVITY_FAILURES),", "        out['a1_one_failure'] = converted(line, positions_each(line, config, idx),", 'a1_without_failure'),
 ("    sigma = statistics.stdev(nets)", "    sigma = statistics.pstdev(nets)", 'sigma_population'),
 ("    r = entries / D_PILOT", "    r = len(nets) / D_PILOT", 'r_counts_refusals'),
 ("    alpha = ALPHA_2 / kept", "    alpha = ALPHA_2", 'n_c_alpha_not_holm'),
 ("    d_c = 30 if r == 0 else min(30, max(12, math.ceil(n_c / r)))", "    d_c = 30 if r == 0 else min(30, max(12, int(n_c / r)))", 'd_c_floor'),
 ("    d_c = 30 if r == 0 else min(30, max(12, math.ceil(n_c / r)))", "    d_c = 30 if r == 0 else min(30, math.ceil(n_c / r))", 'd_c_no_minimum'),
 ("ALPHA_2, SIGMA_FLOOR, DELTA = 0.025, 0.025, 0.005", "ALPHA_2, SIGMA_FLOOR, DELTA = 0.025, 0.02, 0.005", 'sigma_floor_2'),
 ("        c1=main['lower_bound_95'] is not None and main['lower_bound_95'] > 0,", "        c1=main['lower_bound_95'] is not None and main['lower_bound_95'] >= 0,", 'c1_zero_ok'),
 ("        c2=type(gap) is float and gap > 0,", "        c2=type(gap) is float,", 'c2_sign_ignored'),
 ("        c3=main['halves']['both_positive'],", "        c3=True,", 'c3_ignored'),
 ("            and main['without_top_pool']['lower_bound_95'] > 0),", "            and True),", 'c5_guard_ignored'),
 ("        a1=type(a1['mean_net_return']) is float and a1['mean_net_return'] > 0)", "        a1=True)", 'a1_ignored'),
 ("    if not main['floors']['passed']:\n        return 'INCONCLUSIF'", "    if False:\n        return 'INCONCLUSIF'", 'floors_ignored'),
 ("    holm = V.holm({k: (p_values[k] if words[k] == 'CRITÈRES REMPLIS' else None) for k in words})", "    holm = V.holm({k: p_values[k] for k in words})", 'holm_uses_failed_p'),
 ("    return {k: ('CONFIRMÉ' if words[k] == 'CRITÈRES REMPLIS' and holm[k] else", "    return {k: ('CONFIRMÉ' if words[k] == 'CRITÈRES REMPLIS' else", 'holm_ignored'),
 ("        if pilot_decision != 'GO_PILOTE':", "        if False:", 'confirmation_without_go'),
 ("        if alpha != 0.05:", "        if False:", 'pilot_alpha_unchecked'),
 ("        if alpha not in (0.025, 0.0125):", "        if alpha not in (0.025, 0.0125, 0.05):", 'confirmation_alpha_005'),
 ("    if V.SCHEMA != VERSIONS.get(phase):", "    if False:", 'version_unchecked'),
 ("    if hashlib.sha256('\\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:\n        raise RunError('named_list_altered')\n    if phase", "    if False:\n        raise RunError('named_list_altered')\n    if phase", 'list_unchecked'),
 ("B3 = dict(zip(POOLS, (2, 1, 6, 1)))", "B3 = dict(zip(POOLS, (1, 2, 6, 1)))", 'b3_swapped'),
 ("T0, T0_C, D_PILOT = 1795515686, 1796552486, 12", "T0, T0_C, D_PILOT = 1795515686, 1796552487, 12", 't0_c_off'),
 ("        start, d_days = T0_C, d_c", "        start, d_days = T0, d_c", 'confirmation_on_pilot_window'),
 ("        c5 = V.report(rows['c5_10_slots'], [], alpha=alpha, **common)", "        c5 = V.report(rows['primary'], [], alpha=alpha, **common)", 'c5_on_primary'),
 ("        a1 = V.report(rows['a1_one_failure'], [], alpha=alpha, **common)", "        a1 = V.report(rows['primary'], [], alpha=alpha, **common)", 'a1_on_primary'),
 ("        main = V.report(rows['primary'], rows['placebo'], alpha=alpha, **common)", "        main = V.report(rows['primary'], rows['placebo'], **common)", 'main_at_0_05'),
 ("    if a.out.exists():", "    if False:", 'out_overwritten'),
 ("    if u2.get('t0_time') != T0:", "    if False:", 'u2_t0_unchecked'),
 ("        out[name] = hashlib.sha256(text.encode()).hexdigest()", "        out[name] = hashlib.sha256(text[:-1].encode()).hexdigest()", 'printed_sha_wrong'),
 # R02 decisions: G-0 gate, L-FIN, erratum C-169, D_c
 ("            ok = False", "            ok = True", 'integrity_failure_not_stop'),
 ("        if not gate[line.pool]['admitted']:\n            continue", "        if False:\n            continue", 'non_admitted_pool_kept'),
 ("        if exit_time is not None and exit_time > end:", "        if exit_time is not None and exit_time >= end:", 'l_fin_boundary'),
 ("        if exit_time is not None and exit_time > end:", "        if exit_time is not None:", 'l_fin_counts_all_clock_exits'),
 ("    return dict(c_j=c_j, p=math.ceil(CREDIT_MARGIN * c_j * design['d_c']),", "    return dict(c_j=c_j, p=math.ceil(c_j * design['d_c']),", 'p_without_margin'),
 ("    return dict(c_j=c_j, p=math.ceil(CREDIT_MARGIN * c_j * design['d_c']),", "    return dict(c_j=c_j, p=round(CREDIT_MARGIN * c_j * design['d_c']),", 'p_rounded'),
 ("                d_c33=min(design['d_c'], math.floor(CREDIT_CAP / (CREDIT_MARGIN * c_j))))", "                d_c33=math.floor(CREDIT_CAP / (CREDIT_MARGIN * c_j)))", 'd_c33_not_capped_by_d_c_star'),
 ("                d_c33=min(design['d_c'], math.floor(CREDIT_CAP / (CREDIT_MARGIN * c_j))))", "                d_c33=min(design['d_c'], math.ceil(CREDIT_CAP / (CREDIT_MARGIN * c_j))))", 'd_c33_ceil'),
 ("    c_j = credits / D_PILOT", "    c_j = credits / 12.5", 'c_j_wrong_days'),
 ("CREDIT_CAP, CREDIT_MARGIN = 32_340, 1.25", "CREDIT_CAP, CREDIT_MARGIN = 33_000, 1.25", 'cap_33000'),
 ("    if type(credits) not in (int, float) or not credits > 0:", "    if False:", 'credits_unchecked'),
 ("        if d_c not in (design['d_c'], design['d_c33']):", "        if False:", 'd_c_free'),
 ("        if type(d_c) is not int or d_c < V.MIN_D:", "        if False:", 'd_c_minimum_unchecked'),
 ("            doc['erratum_c169'] = {'K=%d' % k: dict(d_confirmation(rows['primary'], kept=k),", "            doc['erratum_c169'] = {'K=%d' % k: dict(d_confirmation(rows['primary'], kept=1),", 'erratum_k_ignored'),
]
MUT += [   # 0.1.2: the reconstruction step (cpmmrecon 0.1 between window_line and G-0)
 ("        out.append((new, txs))", "        out.append((line, txs))", 'recon_rebuilt_line_dropped'),
 ("    if recon is not None:\n        recon.update(report)", "    if False:\n        recon.update(report)", 'recon_report_not_published'),
 ("                kept[why] = kept.get(why, 0) + 1", "                kept[why] = 1", 'recon_kept_not_counted'),
 ("rebuilt_swaps=len(new.swaps) - len(line.swaps)", "rebuilt_swaps=len(new.swaps)", 'recon_rebuilt_swaps_total'),
 ("        except CC.CostError:\n            side = None", "        except ZeroDivisionError:\n            side = None", 'recon_creator_side_error_raises'),
 ("                                     kept={'kept:not_tried_creator_side': len(line.skipped)}, transactions={})", "                                     kept={}, transactions={})", 'recon_not_tried_unreported'),
 ("        if not line.skipped:", "        if False:", 'recon_clean_lines_rebuilt'),
 ("        new, rep = RB.rebuild(line, txs, wsol_vault=by_pool[line.pool]['wsol_vault'], fees=fees, on_input=side)", "        new, rep = RB.rebuild(line, txs, wsol_vault=by_pool[line.pool]['wsol_vault'], fees=fees, on_input=not side)", 'recon_creator_side_flipped'),
 ("    fees = CC.fees_from_amm_config(config)\n    out, report", "    fees = CC.fees_from_amm_config(dict(config, trade_fee_rate=config['trade_fee_rate'] + 1))\n    out, report", 'recon_fees_altered'),
 ("rebuilt=sum(1 for v in rep.values() if v.startswith('rebuilt'))", "rebuilt=len(rep)", 'recon_rebuilt_counts_kept'),
 ("    pairs, report = rebuilt(_lines(selected, root, start=start, end=end), selected, config)", "    pairs, report = _lines(selected, root, start=start, end=end), rebuilt(_lines(selected, root, start=start, end=end), selected, config)[1]", 'recon_gates_on_raw_lines'),
 ("('RECONSTRUCTION.json', dict(schema=RECONSTRUCTION_SCHEMA, pools=recon))", "('RECONSTRUCTION.json', dict(schema=RECONSTRUCTION_SCHEMA, pools={}))", 'recon_file_empty'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'g23run' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D.parent / 'g23run_pkg' / 'g23run', M / 'g23run_pkg' / 'g23run', ignore=shutil.ignore_patterns('__pycache__'),
                dirs_exist_ok=True)   # the anchored runner, read by the identity test (parents[3] / BASE_DIR)
shutil.copytree(D / 'g23run', base / 'g23run', ignore=shutil.ignore_patterns('__pycache__'))
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
for old, new, name in MUT:
    assert src.count(old) == 1, name
def one(m):
    old, new, name = m
    work = M / name
    shutil.copytree(D / 'g23run', work / 'g23run', ignore=shutil.ignore_patterns('__pycache__'))
    (work / 'g23run' / 'run.py').write_text(src.replace(old, new))
    return dict(mutant=name, detected=run(work).returncode != 0)
with ThreadPoolExecutor(4) as ex:
    out = list(ex.map(one, MUT))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
