import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
MUT = [
 ('fast.py', "        if found is not None and found[0] is tx:", "        if found is not None:", 'memo_object_unchecked'),
 ('fast.py', "        'classify', tx, (mint, creator), lambda: saved['ccb'](tx, mint, creator), copy=dict)", "        'classify', tx, (mint, creator), lambda: saved['ccb'](tx, mint, creator))", 'classify_not_copied'),
 ('fast.py', "            if self.verify and compute() != value:", "            if False:", 'verify_ignored'),
 ('fast.py', "        if type(obj) is dict and kwargs == {'separators': (',', ':')}:", "        if type(obj) is dict:", 'shim_ignores_kwargs'),
 ('fast.py', "        bp._owner_balances, bp._is_swap, bp.json = saved['ob'], saved['sw'], saved['js']", "        bp._owner_balances, bp._is_swap = saved['ob'], saved['sw']", 'json_not_restored'),
 ('fast.py', "        with memoized(verify):\n            return original(*args, **kwargs)", "        return original(*args, **kwargs)", 'no_memo_per_pool'),
 ('engine.py', "                fast_analyser=bool(fast_analyser),", "", 'fast_flag_not_in_key'),
 ('engine.py', "            if len(found) != 1 or residual(row, found[0]):\n                raise StreamError('journal_does_not_reconcile')\n            checked += 1\n    return checked\n\n\ndef thresholds", "            if residual(row, found[0]):\n                raise StreamError('journal_does_not_reconcile')\n            checked += 1\n    return checked\n\n\ndef thresholds", 'reconcile_all_duplicates_allowed'),
 ('engine.py', "    if series is None:                                   # P-2", "    if True:                                   # P-2", 'series_loaded_twice'),
 ('engine.py', "    elif not isinstance(series, sus.SolUsdSeries):", "    elif False:", 'series_type_unchecked'),
 ('engine.py', "        if fast_analyser:                                 # P-1", "        if False:                                 # P-1", 'fast_flag_ignored'),
 ('engine.py', "    parts.append(inspect.getsource(fast))", "    pass", 'fast_source_not_in_code_sha'),
]
out = []
for fname, old, new, name in MUT:
    src = (D / 'paperstream' / fname).read_text()
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'paperstream', work / 'paperstream')
    (work / 'paperstream' / fname).write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'paperstream' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
