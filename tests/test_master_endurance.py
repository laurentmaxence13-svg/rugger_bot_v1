"""Shadow journal stress must preserve the one existing PAPER ledger."""
import json
import hashlib
import sqlite3

import pytest

from bot.master_endurance import run_master_endurance


@pytest.mark.parametrize('events,restarts',[(4,2),(40,3)])
def test_master_endurance_preserves_native_book_across_replay_rollback_and_backup(tmp_path,events,restarts):
    output=tmp_path/'fresh'
    report=run_master_endurance(output,events=events,restarts=restarts)
    assert report['retained_shadow_events']==report['duplicate_replays_ignored']==events
    assert report['conflicting_duplicates_refused']==report['interrupted_transactions_rolled_back']==events
    assert report['backups_verified']==report['restarts_verified']==restarts
    assert report['immutable_snapshots']==restarts and report['sqlite_backup_operations']==2*restarts
    assert report['initial_financial_sha256']==report['final_financial_sha256']
    assert report['inventory_acquired_atomic']==report['inventory_remaining_atomic']=='1000'
    assert report['master_shadow']['actions']=={'WAIT_FOR_DATA':events}
    assert report['master_shadow']['pending_reference_outcomes']==0
    assert report['virtual_elapsed_ms']==events*1000
    assert report['settled_shadow_legs']==report['strict_economic_cycles']==report['network_requests']==0
    assert report['promotion_allowed'] is report['proposal_applied'] is False
    assert all(snapshot['uncommitted_event_excluded'] for snapshot in report['restart_snapshots'])
    for snapshot in report['restart_snapshots']:
        path=output/snapshot['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==snapshot['backup_sha256']
        with sqlite3.connect(path) as backup:
            assert backup.execute('SELECT COUNT(*) FROM paper_master_decisions').fetchone()==(snapshot['after_event'],)
    assert report==json.loads((output/'report.json').read_text())
    with sqlite3.connect(output/report['final_database']) as con:
        assert con.execute('SELECT COUNT(*) FROM paper_master_decisions').fetchone()==(events,)
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(0,)
        assert con.execute('SELECT status FROM paper_trades').fetchone()==('open',)
        assert con.execute('SELECT remaining_atomic FROM paper_token_inventory').fetchone()==('1000',)


def test_virtual_master_endurance_repeats_logical_evidence_deterministically(tmp_path):
    a=run_master_endurance(tmp_path/'a',events=5,restarts=1)
    b=run_master_endurance(tmp_path/'b',events=5,restarts=1)
    for key in ('event_chain_sha256','fixture_sha256','initial_financial_sha256',
                'final_financial_sha256','source_sha256','invariant_checks','master_shadow'):
        assert a[key]==b[key]


@pytest.mark.parametrize('events,restarts',[(True,1),(1,1),(1001,1),(4,0),(4,5),(4,True),(10,11)])
def test_master_endurance_rejects_invalid_budget_before_output_creation(tmp_path,events,restarts):
    output=tmp_path/'fresh'
    with pytest.raises(ValueError):run_master_endurance(output,events=events,restarts=restarts)
    assert not output.exists()


def test_master_endurance_never_overwrites_existing_directory(tmp_path):
    output=tmp_path/'existing';output.mkdir()
    proof=output/'proof';proof.write_text('preserve')
    with pytest.raises(ValueError):run_master_endurance(output,events=4,restarts=1)
    assert proof.read_text()=='preserve' and list(output.iterdir())==[proof]


def test_short_wall_paced_endurance_measures_elapsed_time_and_first_local_latencies(tmp_path):
    report=run_master_endurance(tmp_path/'paced',events=4,restarts=2,wall_seconds=.03)
    assert report['wall_time_paced'] is True and report['virtual_time_only'] is False
    assert report['wall_elapsed_ms']>=report['wall_target_ms']==30
    assert report['observation_clock']=='synthetic_fixture_clock_not_market_or_provider_time'
    assert report['fixture']['wall_seconds']==.03
    paired=report['master_shadow']['master_reference_comparison']
    assert paired['paired_decisions']==4 and paired['action_disagreements']==0
    assert paired['evaluation_latency']['decision_audit_write']['samples']==4
    assert paired['evaluation_latency']['history_read_and_master_evaluation']['p50_ms']>=0
    assert report['initial_financial_sha256']==report['final_financial_sha256']
    assert report['strict_economic_cycles']==report['settled_shadow_legs']==0


def test_detailed_audit_report_is_built_once_without_weakening_restart_or_financial_checks(tmp_path,monkeypatch):
    from bot import master_audit
    original=master_audit.master_report;calls=[]
    def counted(con):
        calls.append(1)
        return original(con)
    monkeypatch.setattr(master_audit,'master_report',counted)
    report=run_master_endurance(tmp_path/'bounded',events=40,restarts=3,wall_seconds=.001)
    assert len(calls)==1
    assert report['invariant_checks']==40*7+3*5+4
    assert report['master_shadow']['decisions']==40
    assert report['master_shadow']['pending_reference_outcomes']==0
    assert report['master_shadow']['master_reference_comparison']['paired_decisions']==40
    assert report['initial_financial_sha256']==report['final_financial_sha256']


@pytest.mark.parametrize('wall',[True,-1,61,float('nan'),float('inf'),'30'])
def test_wall_endurance_rejects_unbounded_or_invalid_pacing_before_writing(tmp_path,wall):
    output=tmp_path/'refused'
    with pytest.raises(ValueError,match='wall-time pacing'):
        run_master_endurance(output,events=4,restarts=1,wall_seconds=wall)
    assert not output.exists()
