"""T-REG S-001 / T-0002: offline baseline report on the pack certified by T-0001.

No network, no keys. Reuses tools/launchlab_baseline_report.report_pool on the
committed fixture pack instead of the git-ignored data/launchlab_trades.

  python -B validation/treg_s001/run_baseline.py > validation/treg_s001/baseline_report.jsonl
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
spec = importlib.util.spec_from_file_location('baseline', ROOT / 'tools' / 'launchlab_baseline_report.py')
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
for archive in sorted(PACK.glob('*.json.gz')):
    print(json.dumps(baseline.report_pool(PACK, archive.name[:-len('.json.gz')]), sort_keys=True))
