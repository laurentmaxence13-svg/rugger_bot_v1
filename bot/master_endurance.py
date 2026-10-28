"""Bounded offline endurance of shadow auditing beside the native PAPER book.

Only synthetic observations and virtual time are used. Shadow proposals never
settle a leg; the existing inventory and bankroll must remain exactly unchanged.
"""
import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time


_FINANCIAL_TABLES=('paper_portfolio','paper_trades','paper_prices','paper_decisions',
    'paper_quote_conflicts','paper_token_inventory','paper_token_legs','paper_token_exit_attempts')
_SOURCE_FILES=('master_endurance.py','master_audit.py','master_decision.py','master_positions.py',
    'p4_experiment.py','operations.py','analyser/paper_trader.py','analyser/token_inventory.py',
    'p3/exit_qualification.py','p3/accounting.py')


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _financial_snapshot(con):
    return {table:con.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            for table in _FINANCIAL_TABLES}


def _require(condition,message):
    if not condition:raise RuntimeError(message)


def run_master_endurance(output,*,events=1000,restarts=10,wall_seconds=0):
    """Create a NEW local fixture book, then audit N proposals without trading.

    A projected native position is opened once through record_quote before the
    stress test. Missing market observations deliberately produce WAIT_FOR_DATA.
    Interruptions, duplicates, conflicting identities and backups must neither
    change that book nor manufacture additional economic cycles.
    """
    output=Path(output)
    if type(events) is not int or not 2<=events<=1000:
        raise ValueError('Synthetic event budget must be an integer in 2..1000')
    if type(restarts) is not int or not 1<=restarts<=min(10,events):
        raise ValueError('Restart budget must be an integer in 1..min(10, events)')
    if (type(wall_seconds) not in (int,float) or not math.isfinite(wall_seconds)
            or not 0<=wall_seconds<=60):
        raise ValueError('Optional local wall-time pacing must be bounded to 0..60 seconds')
    if output.exists() or output.is_symlink() or output.name.startswith('.env'):
        raise ValueError('A new dedicated synthetic endurance directory is required')
    output.mkdir(parents=True)

    from bot.economic_demo import _load_api,_public_address,_quote_observation
    from bot.master_audit import (MasterShadow,setup_master_schema,record_master_decision,
        complete_master_reference,master_report)
    from bot.operations import backup_paper_database
    from bot.analyser.artifacts import atomic_write_json
    api=_load_api()
    from bot.analyser.paper_trader import record_quote,_paper_free_capital
    from bot.analyser.token_inventory import inventory_state

    source_hashes={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                   for name in _SOURCE_FILES}
    fixture=dict(schema='master-shadow-endurance-fixture-v1',mint_byte=71,creator_byte=72,
        pool_byte=73,epoch_ms=1700000000000,step_ms=1000,input_lamports=1000000000,
        acquired_atomic=1000,entry_extra_lamports=5000,exit_extra_lamports=10000,
        events=events,restarts=restarts,missing_features=True)
    if wall_seconds:fixture['wall_seconds']=wall_seconds
    epoch=fixture['epoch_ms'];mint,creator,pool=(_public_address(n) for n in (71,72,73))
    database=output/'initial.sqlite'
    con=sqlite3.connect(database,isolation_level=None)
    shadow=MasterShadow()
    restart_at={(i*events+restarts-1)//restarts for i in range(1,restarts+1)}
    counts=dict(retained=0,duplicates=0,conflicts=0,interruptions=0,backups=0,restarts=0,checks=0)
    receipts=[];chain='0'*64
    try:
        api['setup'](con)
        api['ensure_paper_portfolio'](con,10.0,epoch//1000)
        setup_master_schema(con)
        con.execute('PRAGMA journal_mode=WAL')
        fees=api['SolFeeBreakdown'](5000,10000,(),provenance='synthetic')
        buy=_quote_observation(api,side='buy',mint=mint,pool=pool,amount=1000000000,
            output=1000,requested=epoch-30,index=1,case='master-endurance')
        buy['id']='synthetic-master-endurance-buy'
        model=dict(decision_approved=True,decision_score=75,tp_pct=10,sl_pct=8,
                   trailing_stop_pct=5,hold_seconds=3600,cost_bps=200)
        message=record_quote(con,mint,creator,epoch//1000,epoch//1000,
            api['MarketQuote'](20000,1,pool),model,strategy_mode='shadow_final',
            inventory_context=dict(buy_observation=buy,token_decimals=6,fees=fees,
                decision_at_ms=epoch),require_inventory=True)
        _require(message.startswith('ENTRY '),'Fixture entry did not use native inventory')
        baseline=_financial_snapshot(con);baseline_hash=_hash(baseline)
        native=inventory_state(con,mint)
        _require(native['remaining_atomic']=='1000','Fixture position quantity is wrong')
        baseline_cash=_paper_free_capital(con)

        wall_start=time.monotonic()
        for index in range(1,events+1):
            # A wall-time run exercises the same local journal, not a scanner.
            # Wait in bounded pieces; observation timestamps remain synthetic.
            target=wall_start+wall_seconds*index/events
            while wall_seconds and (remaining_wait:=target-time.monotonic())>0:
                time.sleep(min(remaining_wait,.1))
            frame=dict(id='synthetic-master-'+str(index),mint=mint,creator=creator,pool=pool,
                detected_at_ms=epoch,available_at_ms=epoch+index*fixture['step_ms'],
                data_kind='synthetic',observation_scope='missing_source_data_fixture')
            # Interrupted work is rolled back in the same native SQLite book.
            interrupted=dict(frame,id='uncommitted-'+str(index))
            con.execute('BEGIN IMMEDIATE')
            try:
                shadow.evaluate(con,interrupted,inventory=native)
                raise InterruptedError('Synthetic process interruption before commit')
            except InterruptedError:
                con.rollback()
            _require(con.execute('SELECT COUNT(*) FROM paper_master_decisions').fetchone()[0]==index-1,
                     'Interrupted event survived rollback')
            counts['interruptions']+=1;counts['checks']+=1

            con.execute('BEGIN IMMEDIATE')
            reference=(dict(action='WAIT_FOR_DATA',intent_only=True,
                observed_at_ms=frame['available_at_ms'],selected_strategy=None,
                reasons=['no_new_market_observation_reference_action_unavailable'],
                scope='synthetic_persistence_intent_fixture_not_reference_strategy_replay') if wall_seconds else None)
            key,decision=shadow.evaluate(con,frame,inventory=native,reference=reference,
                measure_latency=bool(wall_seconds))
            _require(decision['action']=='WAIT_FOR_DATA','Missing observations did not remain unknown')
            outcome=dict(proposal_applied=False,reference_engine_result='NO_REFERENCE_ACTION',
                native_inventory_remaining_atomic=native['remaining_atomic'],
                native_inventory_version=native['version'])
            complete_master_reference(con,key,outcome)
            _require(shadow.evaluate(con,frame,inventory=native,reference=reference)==(key,decision),
                     'Exact duplicate changed the shadow proposal')
            complete_master_reference(con,key,outcome)
            counts['duplicates']+=1
            conflicting=dict(frame,observation_scope='changed_evidence_same_identity')
            try:
                record_master_decision(con,conflicting,decision,
                    inputs=dict(inventory=native,health=None,capital=None))
            except ValueError as error:
                _require('conflicts' in str(error),'Unexpected conflict refusal')
                counts['conflicts']+=1
            else:
                raise RuntimeError('Conflicting duplicate was accepted')
            con.commit()
            counts['retained']+=1;counts['checks']+=3
            _require(_financial_snapshot(con)==baseline,'Shadow auditing changed the PAPER book')
            _require(_paper_free_capital(con)==baseline_cash,'Shadow auditing changed shared cash')
            _require(inventory_state(con,mint)==native,'Shadow auditing changed native inventory')
            counts['checks']+=3
            chain=_hash(dict(previous=chain,event_key=key,decision=decision,outcome=outcome))

            if index in restart_at:
                # A separate backup reader sees committed WAL only, while an
                # uncommitted audit row is present in the active writer.
                con.execute('BEGIN IMMEDIATE')
                shadow.evaluate(con,dict(frame,id='backup-pending-'+str(index)),inventory=native)
                target=output/('backup-'+str(index)+'.sqlite')
                receipt=backup_paper_database(database,target)
                with closing(sqlite3.connect(target)) as restored:
                    _require(restored.execute('SELECT COUNT(*) FROM paper_master_decisions').fetchone()[0]==index,
                             'Backup included an uncommitted shadow event')
                    _require(_financial_snapshot(restored)==baseline,
                             'Committed backup changed native finances')
                con.rollback();con.close()
                # Preserve the evidence snapshot unchanged. A separate working
                # copy carries all later writes after the simulated restart.
                database=output/('working-'+str(index)+'.sqlite')
                restored_receipt=backup_paper_database(target,database)
                con=sqlite3.connect(database,isolation_level=None)
                con.execute('PRAGMA journal_mode=WAL')
                shadow=MasterShadow()
                retained,pending=con.execute('SELECT COUNT(*),COALESCE(SUM(reference_outcome_json IS NULL),0) '
                    'FROM paper_master_decisions').fetchone()
                _require(retained==index and pending==0,
                    'Restart lost committed events or outcomes')
                _require(shadow.evaluate(con,frame,inventory=native,reference=reference)==(key,decision),
                         'Restart changed duplicate identity or decision')
                _require(_financial_snapshot(con)==baseline,'Restart changed native PAPER book')
                receipts.append(dict(after_event=index,file=target.name,
                    committed_decisions=index,quick_check=receipt['quick_check'],
                    backup_sha256=receipt['backup_sha256'],uncommitted_event_excluded=True,
                    restore_working_file=database.name,restore_quick_check=restored_receipt['quick_check']))
                counts['backups']+=1;counts['restarts']+=1;counts['checks']+=5

        summary=master_report(con)
        _require(summary['decisions']==events and summary['pending_reference_outcomes']==0,
                 'Final audit count is inconsistent')
        _require(con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(0,),
                 'A shadow proposal settled a financial leg')
        _require(con.execute('SELECT status FROM paper_trades').fetchone()==('open',),
                 'A shadow proposal closed the fixture position')
        _require(_financial_snapshot(con)==baseline,'Final financial invariance failed')
        counts['checks']+=4
        report=dict(schema='rugger-master-shadow-endurance-v1',data_kind='synthetic',
            retained_shadow_events=counts['retained'],duplicate_replays_ignored=counts['duplicates'],
            conflicting_duplicates_refused=counts['conflicts'],
            interrupted_transactions_rolled_back=counts['interruptions'],
            backups_verified=counts['backups'],restarts_verified=counts['restarts'],
            sqlite_backup_operations=counts['backups']*2,immutable_snapshots=counts['backups'],
            invariant_checks=counts['checks'],master_shadow=summary,restart_snapshots=receipts,
            fixture_sha256=_hash(fixture),fixture=fixture,source_sha256=source_hashes,
            source_hash_scope='listed_sources_only',event_chain_sha256=chain,
            initial_financial_sha256=baseline_hash,final_financial_sha256=_hash(_financial_snapshot(con)),
            inventory_acquired_atomic=native['acquired_atomic'],inventory_remaining_atomic=native['remaining_atomic'],
            position_status='open',fixture_entry_lamports='1000000000',
            fixture_entry_extra_lamports='5000',final_capital_sol=baseline_cash[0],
            final_available_cash_sol=baseline_cash[1],settled_shadow_legs=0,
            virtual_elapsed_ms=events*fixture['step_ms'],virtual_time_only=not bool(wall_seconds),
            wall_time_paced=bool(wall_seconds),wall_target_ms=wall_seconds*1000,
            wall_elapsed_ms=(time.monotonic()-wall_start)*1000,
            observation_clock='synthetic_fixture_clock_not_market_or_provider_time',
            final_database=database.name,network_requests=0,real_orders_enabled=False,
            proposal_applied=False,promotion_allowed=False,active_policy_changed=False,
            strict_economic_cycles=0,economic_profitability_verified=False,execution_verified=False,
            scope='synthetic shadow persistence endurance; no wall-clock availability or market edge proof')
        atomic_write_json(output/'report.json',report,indent=2,sort_keys=True,allow_nan=False)
        return report
    finally:
        con.close()


def main(argv=None):
    os.environ['RUGGER_NO_DOTENV']='1'
    from bot.__main__ import _offline_policy
    sys.addaudithook(_offline_policy)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New dedicated local fixture directory')
    parser.add_argument('--events',type=int,default=1000)
    parser.add_argument('--restarts',type=int,default=10)
    parser.add_argument('--wall-seconds',type=float,default=0,
        help='Optional local paced endurance, 0..60 wall seconds; no market traffic')
    args=parser.parse_args(argv)
    print(json.dumps(run_master_endurance(args.output,events=args.events,restarts=args.restarts,
        wall_seconds=args.wall_seconds),
        sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
