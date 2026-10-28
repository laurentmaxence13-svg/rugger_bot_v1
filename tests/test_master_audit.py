"""Shadow logging shares the ledger, while optional failures cannot undo exits."""
import asyncio
from contextlib import closing
import json
import io
import sqlite3

import pytest

from bot import master_audit as audit
from bot.analyser import paper_engine as engine
from bot.analyser.paper_trader import MarketQuote
from test_atomic_inventory_transactions import connect, enter, exit_context, MODEL, USDC
from test_master_decision import qualified


def event(at=100, identity='frame'):
    return dict(id=identity,mint='mint',available_at_ms=at), dict(
        policy_sha256='a'*64,promotion_allowed=False,action='WAIT',selected_strategy=None)


def test_shadow_writer_is_idempotent_conflicts_refused_and_caller_rollback_retained():
    with closing(sqlite3.connect(':memory:',isolation_level=None)) as con:
        audit.setup_master_schema(con)
        con.execute('BEGIN')
        frame,decision=event()
        key=audit.record_master_decision(con,frame,decision,inputs={'cash':None})
        assert audit.record_master_decision(con,frame,decision,inputs={'cash':None})==key
        with pytest.raises(ValueError,match='conflicts'):
            audit.record_master_decision(con,frame,decision,inputs={'cash':0})
        assert con.in_transaction
        con.rollback()
        assert audit.master_report(con)['decisions']==0
        assert audit.master_report(con)['pending_reference_outcomes']==0


def test_outcome_restart_and_causal_bounded_history_do_not_modify_finances(tmp_path):
    path=tmp_path/'shadow.sqlite'
    with closing(connect(path)) as con:
        enter(con)
        before=con.execute('SELECT * FROM paper_portfolio').fetchall()
        audit.setup_master_schema(con)
        for at in range(70):
            frame,decision=event(at,str(at))
            key=audit.record_master_decision(con,frame,decision)
        outcome=dict(proposal_applied=False,reference_engine_result='REFUSED')
        audit.complete_master_reference(con,key,outcome)
        audit.complete_master_reference(con,key,outcome)
        with pytest.raises(ValueError,match='different facts'):
            audit.complete_master_reference(con,key,{**outcome,'reference_engine_result':'EXIT'})
        history=audit.master_history(con,'mint',as_of_ms=40)
        assert len(history)==32 and [r['available_at_ms'] for r in history]==list(range(9,41))
        assert con.execute('SELECT * FROM paper_portfolio').fetchall()==before
    with closing(sqlite3.connect(path)) as con:
        report=audit.master_report(con)
        assert report['decisions']==70 and report['pending_reference_outcomes']==69
        assert report['actions']=={'WAIT':70} and report['proposal_applied'] is False


def test_ignored_insert_and_nonfinite_evidence_cannot_claim_persistence():
    with closing(sqlite3.connect(':memory:',isolation_level=None)) as con:
        audit.setup_master_schema(con)
        con.execute('''CREATE TRIGGER ignore_master BEFORE INSERT ON paper_master_decisions
            BEGIN SELECT RAISE(IGNORE); END''')
        with pytest.raises(ValueError,match='exactly once'):
            audit.record_master_decision(con,*event())
        with pytest.raises(ValueError):
            audit.record_master_decision(con,*event(),inputs={'cash':float('nan')})
        assert audit.master_report(con)['decisions']==0


def test_optional_failure_rolls_back_only_audit_and_cancellation_propagates():
    with closing(sqlite3.connect(':memory:',isolation_level=None)) as con:
        audit.setup_master_schema(con)
        con.execute('CREATE TABLE caller_work(value INTEGER)')
        con.execute('BEGIN')
        con.execute('INSERT INTO caller_work VALUES(7)')
        def failure():
            audit.record_master_decision(con,*event())
            raise ValueError('optional audit failure')
        assert audit.shadow_attempt(con,failure)==(None,'ValueError')
        assert con.in_transaction and con.execute('SELECT * FROM caller_work').fetchall()==[(7,)]
        assert audit.master_report(con)['decisions']==0
        def cancel():
            audit.record_master_decision(con,*event())
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            audit.shadow_attempt(con,cancel)
        assert con.in_transaction and audit.master_report(con)['decisions']==0
        con.rollback()


def test_pure_master_proposal_is_durable_without_a_second_bankroll():
    core,frame,health,capital=qualified()
    with closing(connect()) as con:
        audit.setup_master_schema(con)
        shadow=audit.MasterShadow(core)
        con.execute('BEGIN')
        key,decision=shadow.evaluate(con,frame,health=health,capital=capital)
        assert decision['action']=='ENTER'
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()==(0,)
        assert con.execute('SELECT COUNT(*) FROM paper_portfolio').fetchone()==(0,)
        audit.complete_master_reference(con,key,dict(proposal_applied=False,reference_engine_result='NO_REFERENCE_ENTRY'))
        con.commit()
        assert audit.master_report(con)['proposed_strategies']=={'adaptive_hybrid':1}


def test_reports_expose_shadow_readonly_and_corrupt_audit_cannot_reset_capital_or_hide_data():
    from bot.analyser.functional_report import build_functional_report
    from bot.operations import build_operational_health
    from test_operations import observations
    with closing(connect()) as con:
        from bot.analyser.paper_trader import ensure_paper_portfolio
        ensure_paper_portfolio(con,10,0)
        assert 'master_shadow' not in build_functional_report(con)
        audit.setup_master_schema(con)
        key=audit.record_master_decision(con,*event())
        con.execute('UPDATE paper_master_decisions SET decision_json=? WHERE event_key=?',('{bad',key))
        before=con.total_changes
        con.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action in (
            sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE
        ) else sqlite3.SQLITE_OK)
        health=build_operational_health(con,observations(),now_ms=3000)
        dashboard=build_functional_report(con)
        assert health['master_shadow']==dashboard['master_shadow']
        assert dashboard['master_shadow']['status']=='unavailable'
        assert dashboard['master_shadow']['decisions'] is None
        assert health['allow_new_entries'] is False
        assert 'master_shadow_audit_unavailable' in health['blocking_reasons']
        assert health['capital_sol']==health['available_cash_sol']==10
        assert con.total_changes==before


def test_health_api_exposes_durable_shadow_summary_without_a_server_or_database_write():
    from bot.operations import build_operational_health,make_read_only_handler
    from test_operations import observations
    with closing(connect()) as con:
        from bot.analyser.paper_trader import ensure_paper_portfolio
        ensure_paper_portfolio(con,10,0);audit.setup_master_schema(con)
        audit.record_master_decision(con,*event())
        handler=object.__new__(make_read_only_handler(
            lambda:build_operational_health(con,observations(),now_ms=3000)))
        handler.path='/health';handler.wfile=io.BytesIO();status=[]
        handler.send_response=status.append
        handler.send_header=lambda *args:None
        handler.end_headers=lambda:None
        before=con.total_changes;handler.do_GET()
        result=json.loads(handler.wfile.getvalue())
        assert status==[200]
        assert result['master_shadow']['actions']=={'WAIT':1}
        assert result['master_shadow']['pending_reference_outcomes']==1
        assert result['capital_sol']==10 and con.total_changes==before


def prepare(con):
    engine.ensure_signal_status_schema(con)
    con.execute('''CREATE TABLE launch_candidates (
        mint TEXT,deployer_candidate TEXT,block_time INTEGER,status TEXT)''')
    con.execute('INSERT INTO launch_candidates VALUES(?,?,?,?)',(USDC,'creator',100,'creator_identified'))


@pytest.mark.parametrize('broken',[False,True])
def test_shadow_wait_keeps_reference_entry_separate_but_audit_failure_blocks_new_entry(broken,monkeypatch):
    with closing(connect()) as con:
        prepare(con);audit.setup_master_schema(con)
        shadow=audit.MasterShadow()
        if broken:
            def fail(*args,**kwargs):raise ValueError('audit unavailable')
            monkeypatch.setattr(shadow,'evaluate',fail)
        async def quote(*args,**kwargs):return MarketQuote(12000,1,'pair'),0
        messages,_,_=asyncio.run(engine.collect_once(con,object(),[],160,model=engine.shadow_baseline_model(),
            quote_provider=quote,clock=lambda:160,master_shadow=shadow))
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()==(0 if broken else 1,),messages
        if not broken:
            decision,outcome=con.execute('SELECT decision_json,reference_outcome_json FROM paper_master_decisions').fetchone()
            assert json.loads(decision)['action']=='WAIT'
            assert json.loads(outcome)['proposal_applied'] is False


@pytest.mark.parametrize('failure_phase',[None,'evaluate','outcome','post_settlement_read'])
def test_shadow_integration_never_suppresses_native_protective_exit_or_undoes_settlement(monkeypatch,failure_phase):
    with closing(connect()) as con:
        enter(con);prepare(con);audit.setup_master_schema(con)
        shadow=audit.MasterShadow()
        if failure_phase=='evaluate':
            def fail(*args,**kwargs):
                audit.record_master_decision(con,*event())
                raise ValueError('synthetic evaluation failure')
            monkeypatch.setattr(shadow,'evaluate',fail)
        if failure_phase=='outcome':
            original=audit.complete_master_reference
            def fail(*args,**kwargs):
                original(*args,**kwargs)
                raise ValueError('synthetic outcome failure')
            monkeypatch.setattr(audit,'complete_master_reference',fail)
        context=exit_context(con,1000,1100000000)
        if failure_phase=='post_settlement_read':
            from bot.analyser import token_inventory
            original_read=token_inventory.inventory_state
            def fail_read(*args,**kwargs):
                result=original_read(*args,**kwargs)
                if result and result['remaining_atomic']=='0':
                    raise ValueError('synthetic post-settlement audit read failure')
                return result
            monkeypatch.setattr(token_inventory,'inventory_state',fail_read)
        async def quote(*args,**kwargs):return MarketQuote(12000,1.2,'pair'),0
        async def inventory(*args,**kwargs):return context
        messages,_,_=asyncio.run(engine.collect_once(con,object(),[],200,model=MODEL,
            quote_provider=quote,inventory_provider=inventory,clock=lambda:200,
            master_shadow=shadow,entry_guard=lambda:False))
        assert con.execute('SELECT status FROM paper_trades').fetchone()==('closed',),messages
        assert con.execute('SELECT remaining_atomic FROM paper_token_inventory').fetchone()==('0',)
        assert con.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone()==(1,)
        assert con.execute('SELECT realized_capital_sol FROM paper_portfolio').fetchone()[0]==pytest.approx(10.099985)
        summary=audit.master_report(con)
        assert summary['decisions']==(0 if failure_phase=='evaluate' else 1)
        assert summary['pending_reference_outcomes']==(1 if failure_phase in ('outcome','post_settlement_read') else 0)
        assert not con.in_transaction
        if failure_phase is not None:
            assert any('MASTER_SHADOW_' in message for message in messages)
        before=con.total_changes
        report=engine.paper_report(con,200,0)
        assert report['master_shadow']==summary and con.total_changes==before
