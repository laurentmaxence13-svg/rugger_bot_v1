"""ExecutionJournal must release its SQLite handle on refusal, failure and normal close."""
import os
import sqlite3

import pytest

import bot.live.journal as journal_module
from bot.live.journal import ExecutionJournal


def _record_connections(monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def connect(*args, **kwargs):
        con = real_connect(*args, **kwargs)
        opened.append(con)
        return con

    monkeypatch.setattr(journal_module.sqlite3, 'connect', connect)
    return opened


def _assert_closed(con):
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute('SELECT 1')


def _private_file(path, data):
    path.write_bytes(data)
    os.chmod(path, 0o600)
    return path


def test_foreign_sqlite_database_is_refused_and_closed(tmp_path, monkeypatch):
    path = tmp_path / 'not-a-journal.sqlite'
    with sqlite3.connect(path) as setup:
        setup.execute('CREATE TABLE unrelated(x INTEGER)')
    setup.close()
    os.chmod(path, 0o600)
    opened = _record_connections(monkeypatch)
    with pytest.raises(ValueError, match='not_a_rugger_live_execution_journal'):
        ExecutionJournal(path)
    assert len(opened) == 1
    _assert_closed(opened[0])


def test_corrupt_file_failure_during_initialization_is_closed(tmp_path, monkeypatch):
    path = _private_file(tmp_path / 'corrupt.sqlite', b'this is not an sqlite database file' * 4)
    opened = _record_connections(monkeypatch)
    with pytest.raises(sqlite3.DatabaseError):
        ExecutionJournal(path)
    assert len(opened) == 1
    _assert_closed(opened[0])


def test_context_manager_closes_and_journal_reopens(tmp_path, monkeypatch):
    path = tmp_path / 'private-live.sqlite'
    opened = _record_connections(monkeypatch)
    with ExecutionJournal(path) as journal:
        assert journal.con.execute('PRAGMA application_id').fetchone()[0] == journal_module.APPLICATION_ID
    _assert_closed(opened[0])
    with ExecutionJournal(path) as reopened:
        assert reopened.con.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
    _assert_closed(opened[1])
