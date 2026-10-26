"""Research date provenance and interrupted-publication regressions, synthetic only."""
import csv
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

from bot.analyser import research_pipeline as research
from bot.analyser.multi_creator_research_engine import ensure_schema
from test_complete_launch_export import payload


@pytest.fixture
def cache(tmp_path):
    path = tmp_path / 'synthetic.db'
    ensure_schema(path)
    return path


@pytest.mark.parametrize('raw_time', [None, 0, -1, True, False, '1000', 1000.0,
                                      float('nan'), float('inf'), 2_000_000_000_000])
def test_saved_date_cannot_repair_unverified_raw_time(cache, tmp_path, raw_time):
    raw = json.dumps(payload([('mint', 'creator', 'pool')], raw_time))
    with closing(sqlite3.connect(cache)) as con:
        con.execute('INSERT INTO research_tx_cache VALUES(?,?,1,?)', ('sig', raw, 'synthetic'))
        con.execute('INSERT INTO research_launches(signature,creator,mint,block_time,updated_at) '
                    'VALUES(?,?,?,?,?)', ('sig', 'creator', 'mint', 1000, 'synthetic'))
        con.commit()
    assert research.verified_launches(cache) == []
    destination = tmp_path / 'dataset.csv'
    assert research.export_dataset(cache, destination) == (0, 0)
    with destination.open(newline='', encoding='utf-8') as stream:
        assert list(csv.DictReader(stream)) == []
    with closing(sqlite3.connect(cache)) as con:
        assert con.execute('SELECT payload FROM research_tx_cache').fetchone() == (raw,)
        assert con.execute('SELECT block_time FROM research_launches').fetchone() == (1000,)


def test_raw_date_is_authoritative_and_no_joined_table_is_required(cache):
    with closing(sqlite3.connect(cache)) as con:
        con.execute('INSERT INTO research_tx_cache VALUES(?,?,1,?)',
                    ('sig', json.dumps(payload([('mint', 'creator', 'pool')], 1000)), 'synthetic'))
        con.execute('DROP TABLE research_launches')
        con.commit()
    assert research.verified_launches(cache) == [(1000, 'sig', 'creator', 'mint', 'pool')]


class InjectedWriteError(OSError):
    pass


def prepare_export(kind, cache, monkeypatch):
    events = [(1000, 'sig', 'creator', 'mint', 'pool')]
    monkeypatch.setattr(research, 'verified_launches', lambda _db: events)
    if kind == 'dataset':
        return lambda destination: research.export_dataset(cache, destination)
    if kind == 'prices':
        with closing(sqlite3.connect(cache)) as con:
            con.execute('CREATE TABLE paper_prices(mint TEXT,timestamp INTEGER,price_usd REAL)')
            con.execute('INSERT INTO paper_prices VALUES(?,?,?)', ('mint', 1060, 1.0))
            con.commit()
        return lambda destination: research.export_prices(cache, destination)
    monkeypatch.setattr(research, 'load_dotenv', lambda: False)
    monkeypatch.setattr(research, 'fetch_birdeye_history',
                        lambda *_args, **_kwargs: [(1060, 1.0), (1300, 1.1),
                                                  (1900, 1.2), (4660, 1.3)])
    return lambda destination: research.backfill_historical_prices(
        cache, destination, delay=0, api_key='synthetic-test-value')


@pytest.mark.parametrize('kind', ['dataset', 'prices', 'historical-prices'])
@pytest.mark.parametrize('existing', [False, True])
def test_interrupted_csv_keeps_previous_complete_artifact(cache, tmp_path, monkeypatch, kind, existing):
    export = prepare_export(kind, cache, monkeypatch)
    destination = tmp_path / 'output.csv'
    previous = b'previous,complete\r\nartifact,1\r\n'
    if existing:
        destination.write_bytes(previous)
    original = csv.writer

    class FaultyWriter:
        def __init__(self, stream, **kwargs):
            self.writer = original(stream, **kwargs)
            self.rows = 0

        def writerow(self, row):
            self.writer.writerow(row)
            self.rows += 1
            if self.rows == 2:
                raise InjectedWriteError('synthetic interruption after a partial CSV write')

        def writerows(self, rows):
            for row in rows:
                self.writerow(row)

    monkeypatch.setattr(research.csv, 'writer', FaultyWriter)
    with pytest.raises(InjectedWriteError):
        export(destination)
    assert destination.read_bytes() == previous if existing else not destination.exists()
    assert sorted(path.name for path in tmp_path.glob('.*.tmp')) == []


@pytest.mark.parametrize('kind', ['dataset', 'prices', 'historical-prices'])
def test_csv_success_publishes_the_complete_result(cache, tmp_path, monkeypatch, kind):
    export = prepare_export(kind, cache, monkeypatch)
    destination = tmp_path / 'nested' / 'output.csv'
    export(destination)
    with destination.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert rows and all(row['mint'] == 'mint' for row in rows)
    assert len(rows) == (4 if kind == 'historical-prices' else 1)
    assert not list(destination.parent.glob('.*.tmp'))


@pytest.mark.parametrize('command', ['backtest', 'backtest-grid', 'momentum-grid', 'behavior-grid'])
def test_json_cli_replace_failure_preserves_previous_report(tmp_path, monkeypatch, command):
    from bot.analyser import artifacts, behavior_pipeline
    previous = b'{"previous_valid_report": true}\n'
    destination = tmp_path / 'report.json'
    destination.write_bytes(previous)
    result = {'status': 'synthetic', 'mean_return': None}
    function = {'backtest': 'backtest', 'backtest-grid': 'backtest_grid',
                'momentum-grid': 'momentum_grid', 'behavior-grid': 'behavior_grid'}[command]
    module = behavior_pipeline if command == 'behavior-grid' else research
    monkeypatch.setattr(module, function, lambda *_args, **_kwargs: result)
    monkeypatch.setattr(sys, 'argv', ['research_pipeline', command, '--db', 'unused.db',
                                    '--prices', 'unused.csv', '--output', str(destination)])

    def failed_replace(*_args):
        raise InjectedWriteError('synthetic replace failure')

    monkeypatch.setattr(artifacts.os, 'replace', failed_replace)
    with pytest.raises(InjectedWriteError):
        research.main()
    assert destination.read_bytes() == previous
    assert not list(tmp_path.glob('.*.tmp'))


@pytest.mark.parametrize('stage', ['fsync', 'replace'])
def test_failed_atomic_publication_removes_temporary_file(tmp_path, monkeypatch, stage):
    from bot.analyser import artifacts
    destination = tmp_path / 'report.json'
    previous = b'{"previous_valid_report": true}\n'
    destination.write_bytes(previous)

    def failed(*_args):
        raise InjectedWriteError('synthetic ' + stage + ' failure')

    monkeypatch.setattr(artifacts.os, stage, failed)
    with pytest.raises(InjectedWriteError):
        artifacts.atomic_write_json(destination, {'new': 'complete'})
    assert destination.read_bytes() == previous
    assert not list(tmp_path.glob('.*.tmp'))


def test_json_serialization_error_never_touches_existing_artifact(tmp_path):
    from bot.analyser.artifacts import atomic_write_json
    destination = tmp_path / 'report.json'
    previous = b'{"previous_valid_report": true}\n'
    destination.write_bytes(previous)
    with pytest.raises(TypeError):
        atomic_write_json(destination, {'not_serializable': object()})
    assert destination.read_bytes() == previous
    assert not list(tmp_path.glob('.*.tmp'))


def test_atomic_json_supports_strict_deterministic_protocol_output(tmp_path):
    from bot.analyser.artifacts import atomic_write_json
    destination = tmp_path / 'protocol.json'
    atomic_write_json(destination, {'z': None, 'a': 1}, sort_keys=True, allow_nan=False)
    expected = b'{\n  "a": 1,\n  "z": null\n}'
    assert destination.read_bytes() == expected
    with pytest.raises(ValueError):
        atomic_write_json(destination, {'invalid': float('nan')}, allow_nan=False)
    assert destination.read_bytes() == expected
    assert not list(tmp_path.glob('.*.tmp'))


def test_export_prices_closes_owned_connection_after_write_failure(cache, tmp_path, monkeypatch):
    export = prepare_export('prices', cache, monkeypatch)
    real_connect = sqlite3.connect

    class OwnedConnection(sqlite3.Connection):
        close_calls = 0

        def close(self):
            self.close_calls += 1
            super().close()

    con = real_connect(cache, factory=OwnedConnection)
    monkeypatch.setattr(research.sqlite3, 'connect', lambda *_args, **_kwargs: con)

    def failed_writer(*_args, **_kwargs):
        raise InjectedWriteError('synthetic CSV initialization failure')

    monkeypatch.setattr(research.csv, 'writer', failed_writer)
    try:
        with pytest.raises(InjectedWriteError):
            export(tmp_path / 'prices.csv')
        assert con.close_calls == 1
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            con.execute('SELECT 1')
    finally:
        sqlite3.Connection.close(con)
