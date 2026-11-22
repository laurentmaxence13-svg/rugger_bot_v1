import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'paperstream' / 'fast.py').read_text()
MUT = [
 ("    _sus.SolUsdSeries.as_of, _hrr._PoolObserver._quote = as_of, quote\n", "", 'new_memos_not_installed'),
 ("        _sus.SolUsdSeries.as_of, _hrr._PoolObserver._quote = saved['asof'], saved['quote']", "        pass", 'new_memos_not_restored'),
 ("        return memo.get('as_of', self, (slot, transaction_index, decision_ms),", "        return memo.get('as_of', self, (slot, transaction_index),", 'decision_ms_not_in_key'),
 ("        return memo.get('quote', event, (id(self), sol), lambda: saved['quote'](self, event, sol))", "        return memo.get('quote', event, (id(self),), lambda: saved['quote'](self, event, sol))", 'rate_not_in_quote_key'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'paperstream', work / 'paperstream')
    (work / 'paperstream' / 'fast.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'paperstream' / 'tests' / 'test_v052.py'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error',
                        '--deselect', str(work / 'paperstream' / 'tests' / 'test_v052.py') + '::test_byte_identity_at_w1_size_and_the_gain'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
