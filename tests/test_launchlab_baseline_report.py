"""The offline baseline report must never replay a pool that is not quoted in SOL."""
import importlib.util
from pathlib import Path

from bot.market import collector as col
from test_launchlab_collector import FakeRpc, POOL

OTHER_QUOTE = 'TSM2Hiuf7Z9REcwZFQvsBEekBYCYziWBABfFnj6V6gQ'
TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'launchlab_baseline_report.py'


def _report_module():
    spec = importlib.util.spec_from_file_location('launchlab_baseline_report', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_non_sol_pool_is_reported_but_never_replayed(tmp_path):
    archive = col.collect_pool(FakeRpc(50), POOL, tmp_path)
    archive.account = dict(archive.account, mint_quote=OTHER_QUOTE)
    col.save_archive(tmp_path, archive)
    info = _report_module().report_pool(tmp_path, POOL)
    assert info['quote_is_sol'] is False
    assert 'replay' not in info
