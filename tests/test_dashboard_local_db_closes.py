"""The read-only dashboard must close its SQLite handle (Windows keeps files locked otherwise)."""
import sqlite3

import pytest

import bot.dashboard.local_db as local_db


def _record_connections(monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def connect(*args, **kwargs):
        con = real_connect(*args, **kwargs)
        opened.append(con)
        return con

    monkeypatch.setattr(local_db.sqlite3, 'connect', connect)
    return opened


def test_read_paper_db_closes_connection_on_success(tmp_path, monkeypatch):
    path = tmp_path / 'rugger_bot.db'
    with sqlite3.connect(path) as setup:
        setup.execute('CREATE TABLE unrelated(x INTEGER)')
    setup.close()
    opened = _record_connections(monkeypatch)
    result = local_db.read_paper_db(path)
    assert result['cycles'] == [] and len(result['sources']) == 1
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute('SELECT 1')


def test_read_paper_db_closes_connection_when_reading_fails(tmp_path, monkeypatch):
    path = tmp_path / 'rugger_bot.db'
    with sqlite3.connect(path) as setup:
        setup.execute('CREATE TABLE unrelated(x INTEGER)')
    setup.close()
    opened = _record_connections(monkeypatch)

    def boom(con, name):
        raise sqlite3.OperationalError('simulated read failure')

    monkeypatch.setattr(local_db, '_table', boom)
    with pytest.raises(sqlite3.OperationalError):
        local_db.read_paper_db(path)
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute('SELECT 1')
