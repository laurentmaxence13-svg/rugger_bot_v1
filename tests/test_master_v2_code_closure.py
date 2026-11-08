"""W1 protocol R4: the code fingerprint covers the transitive closure of executed repository modules.

The closure is static (every import statement of a module, anywhere in it, relative imports and
package __init__ files included), from CODE_ROOTS. A subprocess runs the W1 code paths (L1
trials with the Master scorer and the placebo, a V2 policy run, the evaluator, the CLI module)
and every repository module it loads must be in the closure.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from bot.master_v2 import harness as h

ROOT = Path(__file__).resolve().parents[1]

RUNTIME = r'''
import json, sys, tempfile, runpy
from pathlib import Path
from bot.master_v2 import harness as h, policies as pol, w1_eval as w
from bot.p4 import historical_research_replay as hrr
pack = Path('tests/fixtures/launchlab_sol_pools')
params = hrr.ReplayParams(latency_slots=4, sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')
with tempfile.TemporaryDirectory() as tmp:
    trials = w.run_l1_trials(pack, params, hrr.ExitOptions(clock_horizon=True),
                             registry_path=Path(tmp) / 'r.jsonl', registered_at='2026-11-08T00:00:00+00:00')
h.run_policy(pack, pol.FixedDelay(delay_s=5), h.ExitRule(max_hold_s=25), hrr.ReplayParams(latency_slots=4, exit_horizon_ms=25_000))
w.trial_metrics(trials['M1'], [p['pool'] for p in trials['M1']['pools']], n_boot=100)
runpy.run_path('tools/master_v2_research.py', run_name='not_main')
root = Path.cwd().resolve()
loaded = set()
for module in list(sys.modules.values()):
    path = getattr(module, '__file__', None)
    if path:
        path = Path(path).resolve()
        if root in path.parents and path.suffix == '.py':
            loaded.add(path.relative_to(root).as_posix())
print(json.dumps(sorted(loaded)))
'''


def test_closure_holds_the_roots_the_scorer_and_the_evaluator():
    modules = set(h.CODE_MODULES)
    assert set(h.CODE_ROOTS) <= modules and h.CODE_MODULES == tuple(sorted(modules))
    for path in ('bot/master_v2/w1_eval.py', 'bot/master_decision.py', 'bot/p4/sol_usd_series.py',
                 'bot/master_v2/registry.py', 'bot/market/replay.py', 'bot/__init__.py', 'bot/master_v2/__init__.py',
                 'tools/master_v2_research.py'):
        assert path in modules, path
    assert h.code_modules() == h.CODE_MODULES


def test_every_repository_module_loaded_at_runtime_is_in_the_closure():
    run = subprocess.run([sys.executable, '-B', '-c', RUNTIME], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr[-2000:]
    loaded = set(json.loads(run.stdout.strip().splitlines()[-1]))
    assert 'bot/master_decision.py' in loaded and 'bot/master_v2/w1_eval.py' in loaded
    assert loaded - set(h.CODE_MODULES) == set()


def _copy_closure(tmp_path):
    copy = tmp_path / 'root'
    for path in h.CODE_MODULES:
        (copy / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, copy / path)
    return copy


def test_fingerprint_follows_a_deep_module_and_a_new_import(monkeypatch, tmp_path):
    copy = _copy_closure(tmp_path)
    monkeypatch.setattr(h, '_ROOT', copy)
    base = h.code_fingerprint()
    assert h.code_modules() == h.CODE_MODULES
    scorer = copy / 'bot/master_decision.py'
    scorer.write_text(scorer.read_text() + '\n# edit\n')
    edited = h.code_fingerprint()
    assert edited != base
    (copy / 'bot/master_v2/new_dependency.py').write_text('VALUE = 1\n')
    evaluator = copy / 'bot/master_v2/w1_eval.py'
    evaluator.write_text(evaluator.read_text() + '\n\ndef _late():\n    from bot.master_v2 import new_dependency\n')
    assert 'bot/master_v2/new_dependency.py' in h.code_modules()
    assert h.code_fingerprint() != edited
    (copy / 'bot/master_v2/new_dependency.py').write_text('VALUE = 2\n')
    with_dep = h.code_fingerprint()
    (copy / 'bot/master_v2/new_dependency.py').write_text('VALUE = 3\n')
    assert h.code_fingerprint() != with_dep


def test_relative_imports_and_package_inits(monkeypatch, tmp_path):
    files = {
        'pkg/__init__.py': 'import json\n',
        'pkg/a.py': 'from .b import X\n',
        'pkg/b.py': 'X = 1\n',
        'pkg/unused.py': 'Y = 2\n',
        'pkg/sub/__init__.py': '',
        'pkg/sub/c.py': 'from .. import a\nimport os\n\ndef f():\n    from ..sub import d\n',
        'pkg/sub/d.py': 'from pkg import b\n',
        'ns/e.py': 'import pkg.b\nimport lonely\n',
        'lonely/__init__.py': 'Z = 3\n',
        'q/__init__.py': 'W = 4\n',
        'q/r.py': '',
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    monkeypatch.setattr(h, 'CODE_ROOTS', ('pkg/sub/c.py', 'ns/e.py', 'q/r.py'))
    assert h.code_modules(tmp_path) == ('lonely/__init__.py', 'ns/e.py', 'pkg/__init__.py', 'pkg/a.py', 'pkg/b.py',
                                        'pkg/sub/__init__.py', 'pkg/sub/c.py', 'pkg/sub/d.py', 'q/__init__.py', 'q/r.py')
    monkeypatch.setattr(h, 'CODE_ROOTS', ('pkg/missing.py',))
    with pytest.raises(ValueError, match='code_module_missing'):
        h.code_modules(tmp_path)


def test_w1_report_publishes_the_rule_and_the_modules():
    from bot.master_v2 import w1_eval
    assert 'transitive-closure-v1' in h.FINGERPRINT_RULE
    assert w1_eval.code_modules is h.code_modules


def test_runtime_is_published_but_not_hashed(monkeypatch):
    record = h.runtime_record()
    assert record['python'] and record['platform'] and record['implementation']
    assert 'dotenv' in record['third_party_imports'] and 'json' not in record['third_party_imports']
    assert 'bot' not in record['third_party_imports'] and record['distributions']
    base = h.code_fingerprint()
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'other')
    assert h.runtime_record()['platform'] == 'other' and h.code_fingerprint() == base
