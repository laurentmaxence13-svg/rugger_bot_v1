"""Exercise the executable fixture pipeline, without any live data or network."""
import asyncio
from contextlib import closing
import json
import math
import sqlite3

import pytest

from bot.functional_demo import run_demo


def test_complete_demo_uses_parser_real_scanner_guard_restart_and_ledger(tmp_path):
    async def scenario():
        before = asyncio.all_tasks()
        result = await run_demo(tmp_path/'demo')
        assert asyncio.all_tasks() == before
        return result
    result = asyncio.run(scenario())
    assert result['data_kind'] == 'synthetic' and result['network_requests'] == 0
    assert result['economic_profitability_verified'] is False
    assert result['strategy_thresholds_modified'] is False
    assert result['recovery_fetch_count'] == 1
    assert result['exit_reason'] == 'TP'
    assert math.isclose(result['net_paper_pnl_sol'],.18,abs_tol=1e-12)
    assert math.isclose(result['final_capital_sol'],10.18,abs_tol=1e-12)
    stages = {x['stage']:x for x in result['trace']}
    assert stages['scanner_gate']['baseline_entry_refused'] is True
    assert stages['scanner_gate']['caught_up_entry_allowed'] is True
    assert stages['restart']['completed_notification_ignored_after_restart'] is True
    assert stages['follow']['position_state'] == 'open'
    assert stages['exit']['position_state'] == 'closed'
    assert json.loads((tmp_path/'demo/demo_result.json').read_text()) == result
    with closing(sqlite3.connect(tmp_path/'demo/paper.sqlite',timeout=0)) as con:
        con.execute('BEGIN EXCLUSIVE')
        assert con.execute('SELECT COUNT(*) FROM launch_candidates').fetchone() == (1,)
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)


def test_demo_refuses_an_existing_output_directory_without_overwriting(tmp_path):
    marker = tmp_path/'keep.txt'
    marker.write_text('preserve existing work')
    with pytest.raises(FileExistsError):
        asyncio.run(run_demo(tmp_path))
    assert marker.read_text() == 'preserve existing work'
    assert not (tmp_path/'paper.sqlite').exists()
