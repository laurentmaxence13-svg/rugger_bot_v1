"""The active loop settles the same projected quantities across native exits."""
import asyncio
from contextlib import closing
import json
import sqlite3

import pytest

from bot.economic_demo import run_economic_demo


def test_four_atomic_economic_cases_use_active_engine_and_reconcile(tmp_path):
    async def scenario():
        before = asyncio.all_tasks()
        result = await run_economic_demo(tmp_path/'demo')
        assert asyncio.all_tasks() == before
        return result
    result = asyncio.run(scenario())
    assert result['data_kind'] == 'synthetic' and result['network_requests'] == 0
    assert result['acquisition_verified'] is result['execution_verified'] is False
    assert result['economic_profitability_verified'] is False
    assert result['fully_settled_positions'] == 3
    assert result['positions_with_remaining_inventory'] == 1
    cases = {case['case']:case for case in result['cases']}
    expected = {'full_tp':'199985000', 'partial_restart':'49975000',
                'refused_liquidity':'0', 'adverse_sl':'-300015000'}
    for name, pnl in expected.items():
        case = cases[name]
        assert case['simulated_realized_pnl_lamports'] == pnl
        assert case['ledger_reconciled'] is case['quantity_conservation_verified'] is True
        assert case['acquired_atomic'] == '25000000'
        assert case['trace'][0]['inventory']['entry_budget_lamports'] == '1000000000'
        assert case['trace'][0]['position_state'] == 'open'
        with closing(sqlite3.connect(tmp_path/'demo'/case['database_file'],timeout=0)) as con:
            con.execute('BEGIN EXCLUSIVE')
            assert con.execute('SELECT COUNT(*) FROM launch_candidates').fetchone() == (1,)
            assert con.execute('SELECT state FROM scanner_tx_recovery').fetchone() == ('done',)
    partial = cases['partial_restart']
    assert partial['restart_verified'] is partial['duplicate_exit_ignored'] is True
    assert [leg['quantity_atomic'] for leg in partial['legs']] == ['10000000','15000000']
    assert cases['refused_liquidity']['legs'] == []
    assert cases['refused_liquidity']['remaining_atomic'] == '25000000'
    assert cases['refused_liquidity']['position_state'] == 'open'
    assert cases['adverse_sl']['exit_reason'] == 'SL'
    assert cases['full_tp']['exit_reason'] == 'TP'
    assert json.loads((tmp_path/'demo/demo_result.json').read_text()) == result


def test_economic_demo_preserves_existing_output_directory(tmp_path):
    marker = tmp_path/'keep.txt'
    marker.write_text('preserve')
    with pytest.raises(FileExistsError):
        asyncio.run(run_economic_demo(tmp_path))
    assert marker.read_text() == 'preserve'
    assert not (tmp_path/'demo_result.json').exists()
