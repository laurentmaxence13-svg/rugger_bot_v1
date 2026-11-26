"""Mutants of lpcompare 0.1: python3 mutations_lpcompare_runner.py PKG PYTHON CWD WORKDIR PATHS [JOBS] (PATHS: livepaper
0.1.2, livesim 0.3.2 and their dependencies, colon-separated). Each mutant replaces ONE exact string (count == 1) and
must make the tests fail; JOBS mutants run at a time (default 3)."""
import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

F = 'compare.py'
MUT = [
 (F, "    return 'conforme' if t < conform_end else", "    return 'conforme' if t <= conform_end else", 'segment_inclusive'),
 (F, "        opened or any(e is not None and e >= conform_end for e in ends))",
  "        opened or any(e is not None and e > conform_end for e in ends))", 'late_exit_strict'),
 (F, "        opened or any(e is not None and e >= conform_end", "        any(e is not None and e >= conform_end",
  'open_not_apart'),
 (F, "    row['segment'] = SPLIT if row['exit_after_conform_end'] else row['entry_segment']",
  "    row['segment'] = row['entry_segment']", 'apart_merged_into_conforming'),
 (F, "    row['exit_after_conform_end'] = row['entry_segment'] == 'conforme' and (",
  "    row['exit_after_conform_end'] = (", 'apart_for_any_entry'),
 (F, "and low < v[1] <= high)", "and low <= v[1] <= high)", 'missing_low_inclusive'),
 (F, "and low < v[1] <= high)", "and low < v[1] < high)", 'missing_high_exclusive'),
 (F, "    return [list(c) for c in chain if t - window < c[0] < t]",
  "    return [list(c) for c in chain if t - window <= c[0] < t]", 'prior_inclusive'),
 (F, "    return [list(iv) for iv in intervals if iv[0] <= t <= iv[1]]",
  "    return [list(iv) for iv in intervals if iv[0] < t <= iv[1]]", 'inside_open_start'),
 (F, "    for rt, ok, reasons in timeline:\n        if rt >= t:", "    for rt, ok, reasons in timeline:\n        if rt > t:",
  'admission_strict'),
 (F, "    return any(ok for rt, ok, _r in timeline if rt >= t)", "    return any(ok for rt, ok, _r in timeline if rt > t)",
  'ever_admitted_strict'),
 (F, "    if not ever_admitted(side['admission'], t):", "    if False:", 'exclusion_branch_dropped'),
 (F, " + (' (D13)' if is_d13(pool, slot, d13) else '')", "", 'd13_tag_dropped'),
 (F, "    return (pool, slot) == tuple(d13)", "    return slot == d13[1]", 'd13_pool_ignored'),
 (F, "    if (pool, sig) in live['P']:\n        out = [", "    if False:\n        out = [", 'a_posteriori_branch_dropped'),
 (F, "        if inside(live['gaps'], t):", "        if False:", 'gap_flag_dropped'),
 (F, "        if inside(live['resumptions'], t):", "        if False:", 'resumption_flag_dropped'),
 (F, "    if sig not in side['sigs']:\n        return ['transaction absente de la collecte livesim']",
  "    if False:\n        return ['transaction absente de la collecte livesim']", 'livesim_absence_dropped'),
 (F, "    if not side['eligible']:", "    if False:", 'livesim_eligibility_dropped'),
 (F, "', '.join(side['gate_reasons'] or ['b3_zero'])", "', '.join(side['gate_reasons'])", 'b3_zero_dropped'),
 (F, "    if (pool, sig) not in live['P']:", "    if False:", 'live_without_p_dropped'),
 (F, "    if (lo['status'] == 'open') != (so['status'] == 'open'):", "    if False:", 'truncation_dropped'),
 (F, "    if lo['landing'] != so['landing']:", "    if False:", 'latency_dropped'),
 (F, "    if lo['rule'] != so['rule']:", "    if False:", 'rule_dropped'),
 (F, "    if lo['status'] != so['status']:", "    if False:", 'status_dropped'),
 (F, "            if d < pair_s and", "            if d <= pair_s and", 'pairing_inclusive'),
 (F, "(best is None or (d, b['livesim']['trigger_time']) < best[0])", "(best is None)", 'pairing_first_not_nearest'),
 (F, "            if id(b) in taken or b['pool'] != a['pool']:", "            if id(b) in taken:", 'pairing_cross_pool'),
 (F, "            if id(b) in taken or b['pool'] != a['pool']:", "            if b['pool'] != a['pool']:",
  'pairing_reuses_a_row'),
 (F, "        if l and s:\n            row['category'] = 'both'", "        if l:\n            row['category'] = 'both'",
  'both_without_livesim'),
 (F, "            if sw.block_time < window_start:\n                continue\n            out['S'][(x, sw.signature)]",
  "            out['S'][(x, sw.signature)]", 'livesim_before_the_live_start'),
 (F, "        txs = {s: t for s, t in txs.items() if t['blockTime'] <= now}", "        txs = dict(txs)",
  'livesim_after_now'),
 (F, "        eligible = gate['admitted'] and b3[x] > 0", "        eligible = b3[x] > 0", 'livesim_gate_ignored'),
 (F, "            if resumptions and resumptions[-1][1] is None:", "            if resumptions:",
  'resumption_end_overwritten'),
 (F, "    records = records[:steps[-1] + 1]", "    records = records[:]", 'no_cut_at_the_last_step'),
 (F, "records[steps[-1]]['receipt_time']", "records[steps[0]]['receipt_time']", 'now_first_step'),
 (F, "        if a['b3'] != b['b3'] or", "        if", 'b3_unchecked'),
 (F, "    if first['variant'] != variant:", "    if False:", 'variant_unchecked'),
 (F, "    if [p['pool'] for p in first['pools']] != [p['pool'] for p in pools]:", "    if False:",
  'pool_order_unchecked'),
 (F, "latency_s=r['receipt_time'] - r['trigger_time']", "latency_s=r['trigger_time'] - r['receipt_time']",
  'latency_sign'),
 (F, "latency_slots=r['receipt_slot'] - r['trigger_slot']", "latency_slots=r['receipt_time'] - r['trigger_time']",
  'latency_slots_in_seconds'),
 (F, "        k = (x['pool'], tuple(x['entry_key']))",
  "        k = next((kk for kk in s_by_key if kk[1] == tuple(x['entry_key'])), (x['pool'], tuple(x['entry_key'])))",
  'witness_pool_ignored'),
 (F, "            closed = [o['net'] for o in got if o['status'] != 'open']",
  "            closed = [o['net'] or 0 for o in got]", 'open_counted_closed'),
 (F, "            if r['livesim']['outcome']['status'] != 'open' and got['outcome'] != r['livesim']['outcome']:",
  "            if False:", 't24_outcome_unchecked'),
 (F, "            if got is None or (got['decision_slot']", "            if got is not None and (got['decision_slot']",
  't24_missing_tolerated'),
 (F, "             doc['notes']['header_d15'], '', doc['notes']['limit_l4'], '',",
  "             doc['notes']['limit_l4'], '',", 'header_d15_dropped'),
 (F, "        if seg == 'hors_protocole':\n            lines += [doc['notes']['out_of_protocol'], '']",
  "        if False:\n            lines += [doc['notes']['out_of_protocol'], '']", 'out_of_protocol_mention_dropped'),
 (F, "                  % (doc['notes']['placebo'], s['placebo']['rows'],", "                  % ('', s['placebo']['rows'],",
  'placebo_note_dropped'),
 (F, "    text = '\\n'.join(lines)\n    PILOT.assert_closed_vocabulary(text)", "    text = '\\n'.join(lines)",
  'render_vocabulary_unchecked'),
 (F, "    return G1.check_vocabulary(json.loads(json.dumps(doc, default=str)))",
  "    return json.loads(json.dumps(doc, default=str))", 'doc_vocabulary_unchecked'),
 (F, "d13=side == 'absent_live' and is_d13(pool, slot, d13)", "d13=is_d13(pool, slot, d13)", 'd13_on_both_sides'),
 (F, "missing(a, b, start - 1, now)", "missing(a, b, start, now)", 'annex_start_excluded'),
 (F, "live_before_start=sum(1 for v in lp.values() if v[1] < start)",
  "live_before_start=sum(1 for v in lp.values() if v[1] <= start)", 'before_start_inclusive'),
 (F, "    if 'exit_time' in row:", "    if False:", 'row_exit_time_ignored'),
 (F, "    gaps = [[r['gap_start'], r['gap_end']] for r in records if r['kind'] == 'GAP']", "    gaps = []",
  'gaps_dropped'),
 (F, "                                     shifted_rows=sum(1 for r in p if r.get('shifted_with')),",
  "                                     shifted_rows=sum(1 for r in p if r.get('shifted_with')) // 2,",
  'shifted_rows_halved'),
 (F, "            row['reasons'] = ['décidable sur les pages live a posteriori seulement']",
  "            row['reasons'] = ['chaîne de signaux différente']", 'a_posteriori_only_reason'),
 (F, "            (a.livesim_json, a.livesim_json_sha, 'livesim_json')):", "            ):", 'livesim_json_unchecked'),
]


def run(pkg, python, cwd, paths):
    env = dict(PATH='/usr/bin:/bin', RUGGER_NO_DOTENV='1', PYTHONPATH='%s:%s' % (pkg, paths))
    cmd = ['unshare', '-rn', 'env', '-i'] + ['%s=%s' % kv for kv in env.items()] + [
        python, '-B', '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', str(Path(pkg) / 'lpcompare' / 'tests')]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).returncode


def one(args):
    pkg, python, cwd, work, paths, (f, old, new, name) = args
    m = work / name
    shutil.copytree(pkg, m, ignore=shutil.ignore_patterns('__pycache__'))
    p = m / 'lpcompare' / f
    p.write_text(p.read_text().replace(old, new))
    got = dict(mutant=name, file=f, detected=run(str(m), python, cwd, paths) != 0)
    shutil.rmtree(m)
    return got


if __name__ == '__main__':
    pkg, python, cwd, work, paths = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    jobs = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6].isdigit() else 3
    bad = [name for f, old, new, name in MUT if (Path(pkg) / 'lpcompare' / f).read_text().count(old) != 1]
    print(len(bad), bad)
    if bad:
        sys.exit(3)
    if '--check' in sys.argv:
        sys.exit(0)
    base = work / 'base'
    shutil.copytree(pkg, base, ignore=shutil.ignore_patterns('__pycache__'))
    if run(str(base), python, cwd, paths) != 0:
        print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
    shutil.rmtree(base)
    with ThreadPoolExecutor(jobs) as ex:
        out = list(ex.map(one, [(pkg, python, cwd, work, paths, m) for m in MUT]))
    print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
