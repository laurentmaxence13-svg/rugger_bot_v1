"""Operational checks reuse one PAPER ledger and never poll a market source."""
from contextlib import closing
import asyncio
import io
import json
import sqlite3

import pytest

from bot.operations import (build_operational_health, OperationalEntryGuard,
                            backup_paper_database, make_read_only_handler)
from bot.analyser.paper_trader import setup, ensure_paper_portfolio
from bot.analyser.paper_engine import _entry_guard_allows
from test_inventory_reporting import native_position


def ledger(path=':memory:'):
    con = sqlite3.connect(path)
    setup(con)
    ensure_paper_portfolio(con, 10, 0)
    con.commit()
    return con


def observations(at=3000):
    return {'scanner': {'state': 'ready', 'observed_at_ms': at},
            'rpc': {'state': 'healthy', 'observed_at_ms': at},
            'websocket': {'state': 'subscribed', 'observed_at_ms': at}}


def test_health_reads_existing_book_without_writes_or_reset_and_retains_restart_inventory():
    with closing(ledger()) as con:
        native_position(con, partial=True)
        before = con.total_changes
        con.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in (
            sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_TABLE) else sqlite3.SQLITE_OK)
        report = build_operational_health(con, observations(), now_ms=3000)
        assert con.total_changes == before
        assert report['allow_new_entries'] is True
        assert report['available_cash_sol'] == pytest.approx(9.499997)
        assert report['remaining_positions'] == [{'mint': 'native', 'remaining_atomic': '60',
                                                'version': 1, 'last_settlement_ms': None}]
        assert report['restart_action'] == 'resume_existing_positions_without_reentry_or_capital_reset'
        assert report['economic_pnl_verified'] is False
        json.dumps(report, allow_nan=False)


def test_read_only_report_holds_one_wal_snapshot_across_concurrent_commit(tmp_path, monkeypatch):
    from bot.analyser import functional_report
    source = tmp_path/'paper.sqlite'
    with closing(ledger(source)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True)) as reader:
            atomic_report = functional_report._atomic_inventory_report
            def report_then_commit(con):
                result = atomic_report(con)
                assert con.in_transaction
                # A coherent new book appears while the reporter is between its
                # inventory read and its cash/reconciliation reads.
                writer.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,"
                    "exit_time,position_sol,pnl_sol,status) VALUES('later','c',1,1,1,2,1,1,'closed')")
                writer.execute('UPDATE paper_portfolio SET realized_capital_sol=11')
                writer.commit()
                return result
            monkeypatch.setattr(functional_report, '_atomic_inventory_report', report_then_commit)
            assert reader.in_transaction is False
            report = build_operational_health(reader, observations(), now_ms=3000)
            assert report['allow_new_entries'] is True
            assert report['capital_sol'] == report['available_cash_sol'] == 10
            assert reader.in_transaction is False
            # Ending our own snapshot exposes the independently committed book.
            assert reader.execute('SELECT realized_capital_sol FROM paper_portfolio').fetchone() == (11,)
            assert writer.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)


def test_health_preserves_callers_uncommitted_transaction_even_when_validation_fails():
    with closing(ledger()) as con:
        con.execute('UPDATE paper_portfolio SET updated_at=123')
        assert con.in_transaction
        report = build_operational_health(con, observations(), now_ms=3000)
        assert report['allow_new_entries'] is True
        assert con.in_transaction
        with pytest.raises(ValueError):
            build_operational_health(con, observations(), now_ms=-1)
        assert con.in_transaction
        assert con.execute('SELECT updated_at FROM paper_portfolio').fetchone() == (123,)
        con.rollback()
        assert con.execute('SELECT updated_at FROM paper_portfolio').fetchone() == (0,)


@pytest.mark.parametrize('source', ['scanner', 'rpc', 'websocket'])
@pytest.mark.parametrize('damage', ['missing', 'stale', 'future', 'wrong_state', 'boolean_time'])
def test_missing_stale_future_and_unhealthy_sources_block_only_new_admission(source, damage):
    with closing(ledger()) as con:
        data = observations()
        if damage == 'missing':
            del data[source]
        elif damage == 'stale':
            data[source]['observed_at_ms'] = 0
        elif damage == 'future':
            data[source]['observed_at_ms'] = 3001
        elif damage == 'boolean_time':
            data[source]['observed_at_ms'] = True
        else:
            data[source]['state'] = 'disconnected'
        report = build_operational_health(con, data, now_ms=3000, max_age_ms=1000)
        assert report['allow_new_entries'] is False
        assert source+'_unhealthy_stale_or_unknown' in report['blocking_reasons']
        assert report['capital_sol'] == 10


def test_emergency_gate_composes_with_existing_engine_entry_contract_and_dynamic_observations():
    with closing(ledger()) as con:
        stopped = [False]
        calls = []
        class Scanner:
            def allows(self, same_con):
                calls.append(same_con)
                return True
        guard = OperationalEntryGuard(con, observations, emergency_stop_provider=lambda: stopped[0],
                                      clock_ms=lambda: 3000, scanner_guard=Scanner())
        assert _entry_guard_allows(guard, con) is True
        assert calls == [con]
        stopped[0] = True
        assert _entry_guard_allows(guard, con) is False
        assert calls == [con]  # Emergency state prevents scanner permission bypass.
        assert guard.last_health['blocking_reasons'] == ['emergency_stop_or_invalid_stop_state']
        assert con.execute('SELECT realized_capital_sol FROM paper_portfolio').fetchone() == (10,)


def test_guard_supervisor_failure_and_unreconciled_cash_fail_closed():
    with closing(ledger()) as con:
        con.execute('UPDATE paper_portfolio SET realized_capital_sol=11')
        report = build_operational_health(con, observations(), now_ms=3000)
        assert report['allow_new_entries'] is False
        assert report['available_cash_sol'] is None
        def failed():
            raise RuntimeError('synthetic supervisor failure')
        assert OperationalEntryGuard(con, failed, clock_ms=lambda: 3000)() is False


def test_real_engine_emergency_blocks_new_position_but_still_closes_existing_and_never_recredits():
    from test_scanner_entry_integrity import database, cycle, permission
    from bot.analyser.paper_trader import MarketQuote
    with closing(database()) as con:
        ensure_paper_portfolio(con, 10, 0)
        stopped, now = [False], [1000000]
        guard = OperationalEntryGuard(con, lambda: observations(now[0]),
            emergency_stop_provider=lambda: stopped[0], clock_ms=lambda: now[0])
        asyncio.run(cycle(con, guard))
        assert con.execute('SELECT status FROM paper_trades').fetchone() == ('open',)
        stopped[0], now[0] = True, 1001000
        con.execute("INSERT INTO launch_candidates VALUES(2,'second','creator',981,'creator_identified',NULL)")
        asyncio.run(cycle(con, guard, now=1001,
                          quote=MarketQuote(20000, 1.2, 'pair', quote_source='dex_market')))
        assert permission(con) == (1, 0)
        assert con.execute('SELECT mint,status,exit_reason FROM paper_trades').fetchall() == [('mint','closed','TP')]
        assert con.execute('SELECT realized_capital_sol FROM paper_portfolio').fetchone()[0] == pytest.approx(10.18)
        asyncio.run(cycle(con, guard, now=1002))
        assert con.execute('SELECT realized_capital_sol FROM paper_portfolio').fetchone()[0] == pytest.approx(10.18)
        assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)


def test_unknown_native_fees_and_legacy_quantities_do_not_become_safe_restart_capital():
    with closing(ledger()) as con:
        native_position(con, partial=True)
        con.execute("UPDATE paper_token_inventory SET entry_extra_lamports=NULL,cost_basis_remaining_lamports=NULL")
        report = build_operational_health(con, observations(), now_ms=3000)
        assert report['allow_new_entries'] is False
        assert 'open_inventory_costs_unknown' in report['blocking_reasons']
        assert report['available_cash_sol'] is None
    with closing(ledger()) as con:
        con.execute("INSERT INTO paper_trades(mint,creator,signal_time,entry_time,entry_price,position_sol,status) "
                    "VALUES('old','c',1,1,1,1,'open')")
        report = build_operational_health(con, observations(), now_ms=3000)
        assert report['allow_new_entries'] is False
        assert report['blocking_reasons'] == ['open_legacy_inventory_unknown']
        assert report['remaining_positions'][0]['remaining_atomic'] is None


def test_online_backup_includes_committed_wal_and_reconnects_same_atomic_book(tmp_path):
    source, target = tmp_path/'paper.sqlite', tmp_path/'backup.sqlite'
    with closing(ledger(source)) as con:
        con.execute('PRAGMA journal_mode=WAL')
        pnl = native_position(con, partial=True)
        con.commit()
        before = con.total_changes
        receipt = backup_paper_database(source, target)
        assert con.total_changes == before
        assert receipt['source_modified'] is False and receipt['restore_performed'] is False
        assert receipt['pages_copied'] > 0 and receipt['bytes'] > 0
        assert len(receipt['backup_sha256']) == 64
        with closing(sqlite3.connect(target)) as restored:
            health = build_operational_health(restored, observations(), now_ms=3000)
            assert health['allow_new_entries'] is True
            assert health['capital_sol'] == pytest.approx(10+pnl/1e9)
            assert restored.execute('SELECT remaining_atomic FROM paper_token_inventory').fetchone() == ('60',)
            assert restored.execute('SELECT COUNT(*) FROM paper_token_legs').fetchone() == (1,)
            assert restored.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)
        # Source handles are not leaked by backup: reader/writer must release locks.
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    with closing(sqlite3.connect(target, timeout=0)) as con:
        con.execute('BEGIN EXCLUSIVE')


def test_backup_refuses_existing_targets_symlinks_missing_source_and_rolls_back_bad_input(tmp_path):
    source, target = tmp_path/'paper.sqlite', tmp_path/'backup.sqlite'
    with closing(ledger(source)):
        pass
    target.write_bytes(b'preserve')
    with pytest.raises(ValueError):
        backup_paper_database(source, target)
    assert target.read_bytes() == b'preserve'
    target.unlink()
    alias = tmp_path/'alias.sqlite'
    alias.symlink_to(source)
    with pytest.raises(ValueError):
        backup_paper_database(alias, target)
    with pytest.raises(ValueError):
        backup_paper_database(tmp_path/'missing.sqlite', target)
    invalid = tmp_path/'invalid.sqlite'
    invalid.write_bytes(b'not a SQLite database')
    with pytest.raises(sqlite3.DatabaseError):
        backup_paper_database(invalid, target)
    assert not target.exists()


def test_backup_never_includes_uncommitted_writer_changes_and_timeout_removes_partial_file(tmp_path, monkeypatch):
    from bot import operations
    source, target = tmp_path/'paper.sqlite', tmp_path/'snapshot.sqlite'
    with closing(ledger(source)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('UPDATE paper_portfolio SET realized_capital_sol=999')
        backup_paper_database(source, target)
        with closing(sqlite3.connect(target)) as reader:
            assert reader.execute('SELECT realized_capital_sol FROM paper_portfolio').fetchone() == (10,)
        assert writer.in_transaction
        writer.rollback()
    partial = tmp_path/'partial.sqlite'
    times = iter((0, 11))
    monkeypatch.setattr(operations.time, 'monotonic', lambda: next(times))
    with pytest.raises(TimeoutError, match='deadline'):
        backup_paper_database(source, partial)
    assert not partial.exists()


@pytest.mark.parametrize('route', ['/health','/portfolio','/positions','/unknown'])
def test_read_only_http_adapter_uses_fresh_snapshot_and_has_no_mutation_route(route):
    with closing(ledger()) as con:
        calls = []
        def fresh():
            calls.append(1)
            return build_operational_health(con, observations(), now_ms=3000)
        handler_class = make_read_only_handler(fresh)
        handler = object.__new__(handler_class)
        handler.path, handler.wfile = route, io.BytesIO()
        status, headers = [], {}
        handler.send_response = status.append
        handler.send_header = headers.__setitem__
        handler.end_headers = lambda: None
        before = con.total_changes
        handler.do_GET()
        assert status == [404 if route == '/unknown' else 200]
        assert len(calls) == (0 if route == '/unknown' else 1)
        assert headers['Cache-Control'] == 'no-store'
        assert int(headers['Content-Length']) == len(handler.wfile.getvalue())
        json.loads(handler.wfile.getvalue())
        handler.wfile, status[:] = io.BytesIO(), []
        handler.do_POST()
        assert status == [405]
        assert con.total_changes == before


def test_cli_health_is_read_only_and_backup_command_uses_new_target(tmp_path, monkeypatch, capsys):
    from bot import operations
    source, heartbeats = tmp_path/'paper.sqlite', tmp_path/'observations.json'
    output, backup = tmp_path/'health.json', tmp_path/'backup.sqlite'
    with closing(ledger(source)):
        pass
    heartbeats.write_text(json.dumps(observations()))
    monkeypatch.setattr(operations.time, 'time_ns', lambda: 3000000000)
    operations.main(['health','--db',str(source),'--observations',str(heartbeats),'--output',str(output)])
    assert json.loads(output.read_text())['allow_new_entries'] is True
    assert json.loads(capsys.readouterr().out)['report'] == str(output)
    operations.main(['backup','--db',str(source),'--output',str(backup)])
    assert json.loads(capsys.readouterr().out)['restore_performed'] is False
    with pytest.raises(SystemExit):
        operations.main(['health','--db',str(source),'--observations',str(heartbeats),'--output',str(output)])


def test_manual_api_binds_only_loopback_and_reloads_heartbeats_without_starting_network(tmp_path, monkeypatch):
    from bot import operations
    source, heartbeats = tmp_path/'paper.sqlite', tmp_path/'observations.json'
    with closing(ledger(source)):
        pass
    heartbeats.write_text(json.dumps(observations()))
    monkeypatch.setattr(operations.time, 'time_ns', lambda: 3000000000)
    captured = []
    class Server:
        def __init__(self, address, handler):
            captured.append(address)
            self.handler = handler
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def serve_forever(self, **kwargs):
            instance = object.__new__(self.handler)
            instance.path = '/health'
            responses = []
            instance._json = lambda status, payload: responses.append((status,payload))
            instance.do_GET()
            assert responses[-1][1]['allow_new_entries'] is True
            heartbeats.write_text('{}')
            instance.do_GET()
            assert responses[-1][1]['allow_new_entries'] is False
    monkeypatch.setattr(operations, 'ThreadingHTTPServer', Server)
    operations.main(['serve','--db',str(source),'--observations',str(heartbeats)])
    assert captured == [('127.0.0.1',8765)]
