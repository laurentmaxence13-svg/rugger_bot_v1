"""Deliberate defects in w1aux/ledger_parallel.py: each must make test_ledger_parallel.py fail."""
import json, shutil, subprocess, sys
from pathlib import Path
S = Path('/tmp/claude-0/-home-user/e0619565-42dc-58dc-a353-d81a7198e975/scratchpad')
V = '/tmp/claude-0/-home-user-rugger-bot-v1/e0619565-42dc-58dc-a353-d81a7198e975/scratchpad/venv312/bin/python'
SRC = S / 'wt_tooling/out_of_tree/w1aux_v75'
MUT = [
 ('lookup_without_argument_check', "    or not all(_same(x, y) for x, y in zip(a, calls[i][0])) \\\n", "    or False \\\n"),
 ('kwargs_not_checked', "or not all(_same(k[name], calls[i][1][name]) for name in k):", "or False:"),
 ('unused_results_accepted', "        if next(position, None) is not None:\n            raise LedgerParallelError('ledger_calls_not_all_used')\n", ""),
 ('results_at_wrong_rank', "                        results[i] = value\n", "                        results[len(results) - 1 - i] = value\n"),
 ('sequential_results_at_wrong_rank', "                results[i] = _work(i)[1]\n", "                results[order.index(i)] = _work(i)[1]\n"),
 ('worker_error_swallowed', "                    executor.shutdown(wait=True, cancel_futures=True)\n                    raise\n", "                    executor.shutdown(wait=True, cancel_futures=True)\n"),
 ('dead_worker_not_reported', "        raise LedgerParallelError('a_ledger_worker_died') from exc\n", "        raise\n"),
 ('missing_result_accepted', "        raise LedgerParallelError('ledger_call_without_result')\n", "        pass\n"),
 ('recorder_returns_none', "            return {}\n", "            return None\n"),
 ('no_lazy_archives', "        with lazy.lazy_archives():\n", "        with contextlib.nullcontext():\n"),
 ('history_always_same', "        return type(a) is type(b) and a.sha256 == b.sha256 and a.label == b.label\n", "        return True\n"),
 ('history_label_ignored', " and a.label == b.label\n", "\n"),
 ('smallest_first', "key=lambda i: (-_JOB['weights'][i], i))", "key=lambda i: (_JOB['weights'][i], i))"),
 ('ledger_sha_not_checked', "    _check_ledger_module()\n    _ORIGINAL", "    _ORIGINAL"),
 ('not_reentrancy_guarded', "    _ACTIVE['on'] = True\n", ""),
 ('workers_not_validated', "    if type(workers) is not int or workers < 1:\n        raise LedgerParallelError('workers_must_be_a_positive_integer')\n", ""),
 ('build_ledger_not_restored', "                ledger.build_ledger = _ORIGINAL['build_ledger']\n", ""),
 ('assembly_ignores_computed_plans', "            return results[i]\n", "            return {}\n"),
 ('probe_peak_not_recorded', "STATS['probe_peak_rss_mb'] = _peak_mb()", "STATS['probe_peak_rss_mb'] = None"),
 ('worker_peaks_not_recorded', "                        peaks[pid] = max(peaks.get(pid, 0), peak)\n", ""),
 ('recorded_events_not_counted', "STATS['recorded_events'] += sum(", "STATS['recorded_events'] += 0 * sum("),
 ('probe_only_no_assembly', "        ledger.derive_l1_plans = lookup\n", "        ledger.derive_l1_plans = recorder\n"),
]
out = []
for name, old, new in MUT:
    dst = S / 'mut_lp' / 'pkg'
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(SRC, dst)
    f = dst / 'w1aux' / 'ledger_parallel.py'
    text = f.read_text()
    assert text.count(old) == 1, name
    f.write_text(text.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(dst / 'w1aux/tests/test_ledger_parallel.py'), '-p', 'no:cacheprovider',
                        '-q', '-x', '-W', 'error'], cwd=S / 'wt_w1', capture_output=True, text=True, timeout=1500,
                       env={'PYTHONPATH': f"{S/'wt_w1'}:{dst}", 'RUGGER_NO_DOTENV': '1', 'PATH': '/usr/bin:/bin'})
    last = (r.stdout.strip().splitlines() or [''])[-1]
    out.append(dict(mutant=name, detected=r.returncode != 0, last=last))
    print(json.dumps(out[-1]), flush=True)
print(f"detected {sum(o['detected'] for o in out)}/{len(out)}")
