"""Run the public CLI in disposable package copies with secrets/network tripwires."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from bot.analyser.paper_trader import setup, ensure_paper_portfolio


@pytest.fixture
def cli_tree(tmp_path):
    root = tmp_path/'cli-source'
    root.mkdir()
    source = Path(__file__).resolve().parents[1]/'bot'
    for path in source.rglob('*.py'):
        relative = path.relative_to(source)
        if relative.parts[0] == 'bot' or path.is_symlink():
            continue  # Historical nested copies are not the active package.
        target = root/'bot'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    # Loaded in the child before ``python -m bot``: even help may not invoke
    # dotenv, and an accidental real provider must fail before opening a socket.
    (root/'sitecustomize.py').write_text('''
import os
from pathlib import Path
import sys
import types

def no_dotenv(*args, **kwargs):
    raise RuntimeError('offline CLI invoked dotenv loader')

dotenv = types.ModuleType('dotenv')
dotenv.load_dotenv = no_dotenv
sys.modules['dotenv'] = dotenv

def guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
        raise RuntimeError('offline CLI attempted network access')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).name.startswith('.env'):
            raise RuntimeError('offline CLI attempted dotenv file access')

sys.addaudithook(guard)
''')
    return root


def cli(root, *args):
    # No runtime credentials are inherited by the child.
    env = {'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1',
           'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PATH': os.defpath}
    return subprocess.run([sys.executable, '-B', '-m', 'bot', *map(str, args)],
                          cwd=root, env=env, capture_output=True, text=True,
                          timeout=20, check=False)


@pytest.mark.parametrize('args', [('--help',), ('paper', '--help')])
def test_public_help_does_not_load_dotenv_open_network_or_create_database(cli_tree, args):
    result = cli(cli_tree, *args)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout
    assert result.stderr == ''
    assert not list(cli_tree.rglob('*.db'))


def test_paper_requires_network_optin_before_importing_config(cli_tree):
    result = cli(cli_tree, 'paper')
    assert result.returncode == 2
    assert 'requires --network' in result.stderr
    assert 'offline CLI invoked dotenv loader' not in result.stderr
    assert not list(cli_tree.rglob('*.db'))


def test_report_uses_readonly_connection_and_preserves_existing_output(cli_tree):
    database, output = cli_tree/'synthetic.db', cli_tree/'dashboard.json'
    with sqlite3.connect(database) as con:
        setup(con)
        ensure_paper_portfolio(con, 10, 0)
    before = database.read_bytes()
    result = cli(cli_tree, 'report', '--db', database, '--output', output, '--data-kind', 'synthetic')
    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert database.read_bytes() == before
    report = json.loads(output.read_text())
    assert report['data_kind'] == 'synthetic'
    assert report['metrics']['capital_initial_sol']['value'] == 10
    assert report['economic_pnl_verified'] is False
    assert report['valuation_scope']['return_conversion_assumption'] == 'constant_SOL_USD'
    retained = output.read_bytes()
    again = cli(cli_tree, 'report', '--db', database, '--output', output)
    assert again.returncode == 2
    assert output.read_bytes() == retained and database.read_bytes() == before


def test_demo_command_completes_active_pipeline_then_report_reads_persisted_ledger(cli_tree):
    directory = cli_tree/'complete-demo'
    result = cli(cli_tree, 'demo', '--output', directory)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    demo = json.loads((directory/'demo_result.json').read_text())
    assert demo['schema'] == 'rugger-functional-demo-v1'
    assert demo['data_kind'] == 'synthetic' and demo['network_requests'] == 0
    assert demo['real_orders_enabled'] is demo['economic_profitability_verified'] is False
    assert demo['atomic_token_inventory_observed'] is False
    assert demo['recovery_fetch_count'] == 1
    assert demo['initial_capital_sol'] == 10
    assert demo['final_capital_sol'] == pytest.approx(10.18)
    assert demo['net_paper_pnl_sol'] == pytest.approx(.18)
    assert demo['assumed_cost_sol'] == pytest.approx(.02)
    stages = {event['stage']: event for event in demo['trace']}
    assert stages['scanner_gate']['baseline_entry_refused'] is True
    assert stages['scanner_gate']['caught_up_entry_allowed'] is True
    assert stages['restart']['completed_notification_ignored_after_restart'] is True
    assert stages['follow']['position_state'] == 'open'
    assert stages['exit']['position_state'] == 'closed'
    database = directory/'paper.sqlite'
    before = database.read_bytes()
    dashboard = directory/'reopened-dashboard.json'
    reopened = cli(cli_tree, 'report', '--db', database, '--output', dashboard,
                   '--data-kind', 'synthetic')
    assert reopened.returncode == 0, reopened.stderr
    assert database.read_bytes() == before
    metrics = json.loads(dashboard.read_text())['metrics']
    assert metrics['positions_closed']['value'] == 1
    assert metrics['capital_final_sol']['value'] == pytest.approx(10.18)
    assert metrics['modeled_cost_sol']['value'] == pytest.approx(.02)
    assert metrics['pnl_gross_sol']['value'] == pytest.approx(.20)
    assert metrics['pnl_net_sol']['value'] == pytest.approx(.18)
    assert metrics['pnl_net_sol']['reliability'] == 'model_only'
    retained = (directory/'demo_result.json').read_bytes()
    repeated = cli(cli_tree, 'demo', '--output', directory)
    assert repeated.returncode != 0
    assert (directory/'demo_result.json').read_bytes() == retained
    assert database.read_bytes() == before
