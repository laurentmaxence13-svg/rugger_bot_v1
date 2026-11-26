"""Mutants of lpbilan 0.1.2: python3 mutations_lpbilan_runner.py PKG PYTHON CWD WORKDIR PATHS (PATHS: livepaper 0.1.4 and
its dependencies, colon-separated). Each mutant replaces ONE exact string (count == 1) and must make the tests fail."""
import json, shutil, subprocess, sys
from pathlib import Path

MUT = [
 ('bilan.py', "r['receipt_time'] <= cut), default=None)", "r['receipt_time'] < cut), default=None)", 'cut_strict'),
 ('bilan.py', "    if not any(t > cut for t in times):", "    if False:", 'cover_unchecked'),
 ('bilan.py', "    if any(b < a for a, b in zip(times, times[1:])):", "    if False:", 'decreasing_steps_allowed'),
 ('bilan.py', "    if start.get('label') != LABEL or start.get('counts_for_operational_master') is not False:",
  "    if start.get('counts_for_operational_master') is not False:", 'label_unchecked'),
 ('bilan.py', "records[end].get('wall', cut + 1) <= cut", "True", 'stop_after_cut_kept'),
 ('bilan.py', "    J.verify_records(records)\n    if not records", "    if not records", 'chain_unverified'),
 ('bilan.py', "exit_time=steps[e['step']]['receipt_time']", "exit_time=d['receipt_time']", 'exit_time_is_decision'),
 ('bilan.py', "    ps = positions(pre)", "    ps = positions(records)", 'positions_look_past_the_cut'),
 ('bilan.py', "for p in ps if p['series'] == series and p['closed']]", "for p in ps if p['closed']]", 'placebo_merged'),
 ('bilan.py', "    opened = [p for p in ps if p['series'] == series and not p['closed']]",
  "    opened = [p for p in ps if p['series'] == series and not p['closed'] and p['buy_landing_slot']]",
  'unlanded_open_dropped'),
 ('bilan.py', "row['net_lamports']) > 1:", "row['net_lamports']) > 2:", 'decomposition_tolerance_2'),
 ('bilan.py', "            if row['net_lamports'] != e['net_lamports'] or row['status'] != e['status']:", "            if False:",
  'exit_row_unchecked'),
 ('bilan.py', "- p['decision_slot'] for p in landed]", "- p['decision_slot'] for p in landed if p['series'] == 'primary']",
  'latency_slots_primary_only'),
 ('bilan.py', "x >= 2 * start['poll_s']", "x > 2 * start['poll_s']", 'interval_strict'),
 ('bilan.py', "    credits = dict(at_cut=NM,", "    credits = dict(at_cut=(ledger or {}).get('credits', NM),", 'credits_at_cut_from_snapshot'),
 ('bilan.py', "    fetch = [r['fetch_ms'] for r in steps if r.get('fetch_ms') is not None]", "    fetch = []", 'fetch_ignored'),
 ('bilan.py', "start=start['start'], now=cut)", "start=start['start'], now=cut - 1)", 'hours_end_before_cut'),
 ('bilan.py', "            marks[r['id']] = r", "            marks.setdefault(r['id'], r)", 'first_mark_kept'),
 ('bilan.py', "    text = '\\n'.join(lines) + '\\n'\n    PILOT.assert_closed_vocabulary(text)",
  "    text = '\\n'.join(lines) + '\\n'", 'vocabulary_unchecked'),
 ('bilan.py', "fixed=sum(d[k] for k in FIXED))", "fixed=d['transactions'])", 'fixed_partial'),
 ('bilan.py', "pool_fees=d['trade_and_creator_fees']", "pool_fees=d['price_impact']", 'pool_fees_swapped'),
 ('bilan.py', "price_move=p['decomposition']['gross']", "price_move=0.0", 'gross_dropped'),
 ('bilan.py', "        if d['series'] not in SERIES:", "        if False:", 'series_unchecked'),
 ('bilan.py', "        raise BilanError('entered_row_without_decomposition:%s' % row.get('pool'))", "        return None",
  'missing_decomposition_tolerated'),
 ('bilan.py', "    if set(d) != set(PARTS):", "    if False:", 'decomposition_keys_unchecked'),
 ('bilan.py', "        last = rs[-1]", "        last = rs[0]", 'g0_first_record'),
 ('bilan.py', "            while k > 0 and not rs[k - 1]['admitted']:", "            while False:", 'g0_since_last_record'),
 ('bilan.py', "declared_defects=list(notes))", "declared_defects=[])", 'notes_dropped'),
 ('bilan.py', "split('\\n') if x.strip()]", "split('\\n')]", 'blank_notes_kept'),
 ('bilan.py', "            out.append(dict(pool=pool, admitted=NM,", "            out.append(dict(pool=pool, admitted=False,",
  'pool_without_g0_refused'),
 ('bilan.py', "TRAILING = ('ERROR', 'STOP')", "TRAILING = ('STOP',)", 'trailing_error_dropped'),
 ('bilan.py', "for r in pre if r['kind'] == 'ERROR'],", "for r in pre if r['kind'] == 'ERRORS'],", 'errors_dropped'),
 ('bilan.py', "for r in pre if r['kind'] == 'CATCHUP'],", "for r in pre if r['kind'] == 'CATCHUPS'],", 'catchups_dropped'),
 ('bilan.py', "and r.get('index_source') == 'gsfa_rank_catchup'),", "and r.get('index_source') == 'gsfa_rank'),", 'caught_up_wrong_source'),
 ('bilan.py', "            resumptions=resumptions(pre),", "            resumptions=[],", 'resumptions_dropped'),
 ('bilan.py', "        nxt = next((x for x in pre[i + 1:] if x['kind'] == 'STEP'), None)", "        nxt = next((x for x in reversed(pre[i + 1:]) if x['kind'] == 'STEP'), None)", 'resumption_last_step'),
 ('bilan.py', "        if r['kind'] != 'STOP':\n            continue", "        if r['kind'] != 'STOP' or r['reason'] != 'planned_end_of_process':\n            continue", 'resumption_planned_only'),
 ('bilan.py', "else nxt['wall'] - r['wall']))", "else r['wall'] - nxt['wall']))", 'resumption_sign'),
 ('bilan.py', "                 % sum(1 for x in it['resumptions'] if x['next_step_wall'] is not None))", "                 % len(it['resumptions']))", 'resumption_count_includes_none'),
]


def run(pkg, python, cwd, paths):
    env = dict(PATH='/usr/bin:/bin', RUGGER_NO_DOTENV='1', PYTHONPATH='%s:%s' % (pkg, paths))
    cmd = ['unshare', '-rn', 'env', '-i'] + ['%s=%s' % kv for kv in env.items()] + [
        python, '-B', '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider', str(Path(pkg) / 'lpbilan' / 'tests')]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).returncode


pkg, python, cwd, work, paths = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
for f, old, new, name in MUT:
    assert (Path(pkg) / 'lpbilan' / f).read_text().count(old) == 1, name
base = work / 'base'
shutil.copytree(pkg, base, ignore=shutil.ignore_patterns('__pycache__'))
if run(str(base), python, cwd, paths) != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for f, old, new, name in MUT:
    m = work / name
    shutil.copytree(pkg, m, ignore=shutil.ignore_patterns('__pycache__'))
    p = m / 'lpbilan' / f
    p.write_text(p.read_text().replace(old, new))
    out.append(dict(mutant=name, file=f, detected=run(str(m), python, cwd, paths) != 0))
    shutil.rmtree(m)
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
