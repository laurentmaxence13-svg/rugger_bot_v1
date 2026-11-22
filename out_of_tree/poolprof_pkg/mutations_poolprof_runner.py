import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'poolprof' / 'profile.py').read_text()
MUT = [
 ("    return [entry for _size, _name, entry in sorted(sized, key=lambda row: (-row[0], row[1]))]", "    return [entry for _size, _name, entry in sorted(sized, key=lambda row: (row[0], row[1]))]", 'rank_smallest_first'),
 ("    if _sha_file(pools_dir / chosen['file']) != chosen['sha256']:", "    if False:", 'archive_sha_unchecked'),
 ("    if _sha_file(pools_dir / 'MANIFEST.json') != manifest_sha256:", "    if False:", 'manifest_unchecked'),
 ("                                     creator_history=history, arms=arms)", "                                     creator_history=None, arms=arms)", 'creator_history_dropped'),
 ("    arms = hrr.ARMS + (hrr.PLACEBO_ARM,)", "    arms = hrr.ARMS", 'placebo_dropped'),
 ("window=hrr.collection_window(entry, loaded, params), exit_options=w1_run.L1_EXIT,", "window=None, exit_options=w1_run.L1_EXIT,", 'window_dropped'),
 ("window=hrr.collection_window(entry, loaded, params), exit_options=w1_run.L1_EXIT,", "window=hrr.collection_window(entry, loaded, params), exit_options=None,", 'exit_options_dropped'),
 ("               fast_analyser=False, total_time_s=round(stats.total_tt, 6), top_by_cumtime=rows[:TOP],", "               fast_analyser=False, total_time_s=round(stats.total_tt, 6), top_by_cumtime=rows,", 'not_top_30'),
 ("    rows.sort(key=lambda row: (-row['cumtime'], row['function']))", "    rows.sort(key=lambda row: (-row['tottime'], row['function']))", 'sorted_by_tottime'),
 ("        rows.append(dict(function='%s:%d(%s)' % (os.path.basename(filename), line, name), ncalls=ncalls,", "        rows.append(dict(function='%s:%d(%s)' % (filename, line, name), ncalls=ncalls,", 'full_paths'),
 ("    if type(rank) is not int or not 1 <= rank <= len(entries):", "    if type(rank) is not int or not 0 <= rank <= len(entries):", 'rank_zero_accepted'),
]
base = subprocess.run([V, '-B', '-m', 'pytest', str(D / 'poolprof' / 'tests'), '-p', 'no:cacheprovider', '-q', '-W', 'error'],
                      cwd=W, env={'PYTHONPATH': f'{PP}:{D}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'},
                      capture_output=True, text=True, timeout=600)
if base.returncode != 0:
    print(base.stdout[-2000:], base.stderr[-2000:])
    raise SystemExit('baseline_does_not_pass: no mutant is run')
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'poolprof', work / 'poolprof')
    (work / 'poolprof' / 'profile.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'poolprof' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True, timeout=600)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
