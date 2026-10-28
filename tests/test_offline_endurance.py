"""Virtual-time stress uses real native settlement and committed backups."""
import json
import sqlite3

import pytest

from bot.offline_endurance import run_offline_endurance


@pytest.mark.parametrize('cycles',[8,25])
def test_endurance_conserves_quantities_fees_capital_and_dedup_after_backup_restart(tmp_path,cycles):
    destination=tmp_path/'new'
    report=run_offline_endurance(destination,cycles=cycles)
    assert report['settled_legs']==report['replayed_quotes_ignored']==cycles
    assert report['backups_verified']==report['restarts_verified']>=8
    assert report['inventory_remaining_atomic']=='0'
    assert report['admission_refusals']>0
    assert all(report['health_phase_counts'][name]>0 for name in ('healthy','stale','emergency','disconnected'))
    assert report['fixture_net_pnl_lamports']==str(50_000_000-5000-10000*cycles)
    assert report['network_requests']==0 and report['economic_profitability_verified'] is False
    assert report==json.loads((destination/'report.json').read_text())
    with sqlite3.connect(destination/report['final_database']) as con:
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(cycles,)
        assert con.execute('SELECT status FROM paper_trades').fetchone()==('closed',)
        assert con.execute('SELECT acquired_atomic,remaining_atomic FROM paper_token_inventory').fetchone()==(str(cycles*1000),'0')
    first=report['restart_snapshots'][0]
    assert int(first['remaining_atomic'])>0
    with sqlite3.connect(destination/('backup-'+str(first['after_cycle'])+'.sqlite')) as con:
        # A backup becomes an active continuation book, so old backup files may
        # advance after the restore. The final ledger is authoritative.
        assert con.execute('PRAGMA quick_check').fetchone()==('ok',)


@pytest.mark.parametrize('cycles',[True,0,1,1001,2.0])
def test_endurance_refuses_invalid_budget_without_creating_output(tmp_path,cycles):
    destination=tmp_path/'new'
    with pytest.raises(ValueError):run_offline_endurance(destination,cycles=cycles)
    assert not destination.exists()


def test_endurance_preserves_existing_output(tmp_path):
    destination=tmp_path/'existing';destination.mkdir()
    proof=destination/'proof';proof.write_text('keep')
    with pytest.raises(ValueError):run_offline_endurance(destination,cycles=8)
    assert proof.read_text()=='keep' and list(destination.iterdir())==[proof]
