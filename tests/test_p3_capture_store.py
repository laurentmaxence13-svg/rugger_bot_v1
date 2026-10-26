"""Dedicated capture evidence: PIT availability, append-only data and no ledger writes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from bot.p3.store import CaptureIntegrityError, CaptureStore


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append(store, **kwargs):
    options = dict(received_at_ms=90, source_time_ms=50, source_slot=1,
                   outcome='observed', signature='synthetic-signature',
                   mint='synthetic-mint', provenance='synthetic', payload={'mint': 'mint'})
    options.update(kwargs)
    return store.append('launch', **options)


def test_observations_are_immutable_and_duplicates_remain_explicit(tmp_path):
    path = tmp_path / 'capture.sqlite'
    payload = {'nested': {'mints': ['first', 'second']}}
    with CaptureStore(path, clock_ms=lambda: 100) as store:
        first = append(store, payload=payload)
        payload['nested']['mints'].append('mutated-after-append')
        second = append(store, payload={'nested': {'mints': ['first', 'second']}})
        assert (first, second) == (1, 2)
        records = store.events()
        assert records[0]['payload'] == records[1]['payload'] == {'nested': {'mints': ['first', 'second']}}
        assert records[0]['payload_sha256'] == records[1]['payload_sha256']
        assert records[1]['previous_hash'] == records[0]['record_hash']
        assert records[0]['record_hash'] != records[1]['record_hash']
        records[0]['payload']['nested']['mints'].clear()
        assert store.events()[0]['payload']['nested']['mints'] == ['first', 'second']
        assert store.verify_integrity() == records[-1]['record_hash']
    before, files = digest(path), sorted(p.name for p in tmp_path.iterdir())
    with CaptureStore(path, readonly=True) as reopened:
        assert len(reopened.events()) == 2
        assert reopened.quality_report()['integrity'] == 'verified_hash_chain_not_authenticated'
        with pytest.raises(ValueError, match='Read-only'):
            append(reopened)
    assert digest(path) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == files


def test_replay_availability_cannot_be_backdated_to_source_or_old_receipt(tmp_path):
    clock = iter((100, 500))
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: next(clock)) as store:
        append(store, received_at_ms=80, source_time_ms=20)
        append(store, received_at_ms=40, source_time_ms=10, provenance='historical_replay')
        assert store.events(as_of_ms=99) == []
        assert len(store.events(as_of_ms=100)) == 1
        assert len(store.events(as_of_ms=499)) == 1
        assert len(store.events(as_of_ms=500)) == 2
        replay = store.events()[-1]
        assert replay['received_at_ms'] == 40
        assert replay['stored_at_ms'] == replay['available_at_ms'] == 500


@pytest.mark.parametrize('source', [None, 0, -1, True, '50', 50.5, float('nan'), float('inf'), 500])
def test_unknown_invalid_and_future_source_times_stay_unknown_not_repaired(tmp_path, source):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        append(store, source_time_ms=source)
        event = store.events()[0]
        assert event['source_time_ms'] is None
        assert event['available_at_ms'] == 100
        assert any(flag.startswith('source_time_') for flag in event['quality_flags'])
        if source == 500:
            assert event['quality_flags'] == ['source_time_future']
        json.dumps(event, allow_nan=False)


@pytest.mark.parametrize('slot', [True, -1, 1.5, '1', 2**63])
def test_invalid_source_slots_are_preserved_as_raw_diagnostics(tmp_path, slot):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        append(store, source_slot=slot)
        event = store.events()[0]
        assert event['source_slot'] is None
        assert event['source_slot_raw'] == slot
        assert 'source_slot_invalid' in event['quality_flags']


@pytest.mark.parametrize('received', [True, -1, 1.5, None, float('nan'), 2**63])
def test_invalid_receipt_timestamp_fails_without_appending(tmp_path, received):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        with pytest.raises(ValueError, match='receipt timestamp'):
            append(store, received_at_ms=received)
        assert store.events() == []


@pytest.mark.parametrize('clock', [True, -1, 1.5, float('inf')])
def test_invalid_local_clock_cannot_forge_availability(tmp_path, clock):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: clock) as store:
        with pytest.raises(ValueError, match='clock timestamp'):
            append(store)
        assert store.events() == []


def test_wall_clock_rollback_never_moves_new_evidence_before_previous_knowledge(tmp_path):
    clock = iter((100, 90))
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: next(clock)) as store:
        append(store)
        append(store, received_at_ms=80)
        second = store.events()[-1]
        assert second['stored_at_ms'] == 90
        assert second['available_at_ms'] == 100
        assert 'local_clock_regressed' in second['quality_flags']
        assert store.events(as_of_ms=99) == []


@pytest.mark.parametrize('schema', ['CREATE TABLE paper_portfolio(capital REAL)',
                                   'CREATE TABLE launch_candidates(mint TEXT)',
                                   'CREATE TABLE unrelated(value TEXT)', ''])
def test_existing_foreign_or_empty_database_is_rejected_without_any_file_change(tmp_path, schema):
    path = tmp_path / 'existing.sqlite'
    with closing(sqlite3.connect(path)) as con:
        if schema:
            con.execute(schema)
            con.commit()
    before, files = digest(path), sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(ValueError, match='historical ledger or unknown'):
        CaptureStore(path)
    assert digest(path) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == files


def test_symlink_to_legacy_ledger_is_not_migrated(tmp_path):
    ledger = tmp_path / 'legacy.sqlite'
    with closing(sqlite3.connect(ledger)) as con:
        con.execute('CREATE TABLE paper_prices(value TEXT)')
        con.commit()
    alias = tmp_path / 'capture.sqlite'
    alias.symlink_to(ledger)
    before = digest(ledger)
    with pytest.raises(ValueError):
        CaptureStore(alias)
    assert digest(ledger) == before


def test_readonly_missing_path_does_not_create_database_or_parent_directory(tmp_path):
    path = tmp_path / 'absent-parent' / 'capture.sqlite'
    with pytest.raises(ValueError, match='missing'):
        CaptureStore(path, readonly=True)
    assert not path.parent.exists()


def test_existing_capture_schema_version_is_checked_before_writing(tmp_path):
    path = tmp_path / 'capture.sqlite'
    with CaptureStore(path) as store:
        append(store)
    with closing(sqlite3.connect(path)) as con:
        con.execute('PRAGMA user_version=999')
    before = digest(path)
    with pytest.raises(ValueError, match='unknown capture schema'):
        CaptureStore(path)
    assert digest(path) == before


def test_insert_failure_rolls_back_without_forking_chain(tmp_path):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        append(store)
        anchor = store.verify_integrity()
        store._connection().execute('''CREATE TRIGGER inject_insert_failure BEFORE INSERT
            ON p3_capture_events WHEN NEW.id=2 BEGIN SELECT RAISE(ABORT,'synthetic failure'); END''')
        with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
            append(store)
        assert len(store.events()) == 1
        assert store.verify_integrity() == anchor
        store._connection().execute('DROP TRIGGER inject_insert_failure')
        assert append(store) == 2
        assert store.events()[-1]['previous_hash'] == anchor


def test_updates_and_deletes_are_forbidden_and_forced_corruption_is_detected(tmp_path):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        append(store)
        for sql in ('UPDATE p3_capture_events SET payload_json=\'{}\'', 'DELETE FROM p3_capture_events'):
            with pytest.raises(sqlite3.IntegrityError, match='append-only'):
                store._connection().execute(sql)
        store._connection().execute('DROP TRIGGER p3_no_update')
        store._connection().execute("UPDATE p3_capture_events SET payload_json='{}'")
        with pytest.raises(CaptureIntegrityError):
            store.events()
        with pytest.raises(CaptureIntegrityError):
            store.quality_report()


def test_two_independent_writers_serialize_their_hash_chain(tmp_path):
    path = tmp_path / 'capture.sqlite'
    CaptureStore(path).close()
    barrier = threading.Barrier(2)

    def write(name):
        with CaptureStore(path, clock_ms=lambda: 100) as store:
            barrier.wait(timeout=5)
            for i in range(8):
                append(store, signature=f'{name}-{i}')

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write, str(i)) for i in range(2)]
        for future in futures:
            future.result(timeout=10)
    with CaptureStore(path, readonly=True) as store:
        events = store.events()
        assert [e['id'] for e in events] == list(range(1, 17))
        assert len({e['signature'] for e in events}) == 16
        assert store.verify_integrity() == events[-1]['record_hash']


@pytest.mark.parametrize('received', [1000, 1500])
def test_ingestion_clock_is_measured_after_waiting_for_the_write_lock(tmp_path, received):
    path = tmp_path / 'capture.sqlite'
    CaptureStore(path).close()
    ready, begin_append, attempting_lock = (threading.Event() for _ in range(3))
    clock = {'now': 1000}

    def write():
        with CaptureStore(path, clock_ms=lambda: clock['now']) as store:
            store._connection().set_trace_callback(
                lambda sql: attempting_lock.set() if sql == 'BEGIN IMMEDIATE' else None)
            ready.set()
            assert begin_append.wait(timeout=5)
            append(store, received_at_ms=received)
            return store.events()[0], store.events(as_of_ms=1750)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(write)
        assert ready.wait(timeout=5)
        with closing(sqlite3.connect(path, isolation_level=None)) as competing:
            competing.execute('BEGIN IMMEDIATE')
            begin_append.set()
            assert attempting_lock.wait(timeout=5)
            # The writer has attempted BEGIN while the competing connection
            # owns the lock. Its old pre-lock timestamp must not survive.
            clock['now'] = 2000
            competing.commit()
        record, past = future.result(timeout=10)
    assert record['received_at_ms'] == received
    assert record['stored_at_ms'] == record['available_at_ms'] == 2000
    assert 'receipt_after_storage_clock' not in record['quality_flags']
    assert past == []


def test_gap_closure_only_changes_quality_after_its_local_availability(tmp_path):
    clock = iter((100, 200, 300))
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: next(clock)) as store:
        store.append('gap', received_at_ms=90, outcome='open', payload={'gap_id': 'outage-1'}, reason='disconnected')
        store.append('gap', received_at_ms=190, outcome='closed', payload={'gap_id': 'outage-1'})
        store.append('gap', received_at_ms=290, outcome='closed', payload={'gap_id': 'unknown-outage'})
        assert store.quality_report(as_of_ms=99)['records'] == 0
        assert store.quality_report(as_of_ms=199)['open_gap_count'] == 1
        assert store.quality_report(as_of_ms=200)['open_gap_count'] == 0
        assert store.quality_report()['unmatched_gap_closures'] == 1
        assert store.quality_report()['market_detection_coverage'] is None
        assert store.quality_report()['p3_go'] is False


@pytest.mark.parametrize('payload', [
    {'nested': {'X-API-Key': 'synthetic-sensitive-value'}},
    {'authorization': 'synthetic-sensitive-value'},
    {'list': [{'access_token': 'synthetic-sensitive-value'}]},
    {'private_key': 'synthetic-sensitive-value'},
    {'url': 'https://provider.test/path?api-key=synthetic-sensitive-value'},
    {'text': 'request failed at https://user:synthetic-sensitive-value@provider.test/path'},
    {'url': 'https://provider.test/path#synthetic-sensitive-value'},
    {'error': 'api_key=synthetic-sensitive-value'},
])
def test_credentials_and_secret_urls_are_rejected_without_echoing_values(tmp_path, payload):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        with pytest.raises(ValueError) as error:
            append(store, payload=payload)
        assert 'synthetic-sensitive-value' not in str(error.value)
        assert store.events() == []


def test_public_mint_metadata_and_bare_public_urls_remain_recordable(tmp_path):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        append(store, payload={'tokenMint': 'public-mint', 'url': 'https://provider.test/public-pair'})
        assert store.events()[0]['payload']['tokenMint'] == 'public-mint'


def test_quality_keeps_all_missing_rejected_and_indicative_evidence(tmp_path):
    with CaptureStore(tmp_path / 'capture.sqlite', clock_ms=lambda: 100) as store:
        store.append('transaction', received_at_ms=90, outcome='missing', provenance='synthetic')
        store.append('candidate_decision', received_at_ms=90, outcome='rejected', provenance='synthetic')
        store.append('quote_attempt', received_at_ms=90, outcome='unavailable', provenance='synthetic')
        store.append('quote_attempt', received_at_ms=90, outcome='quoted', provenance='synthetic')
        store.append('fx', received_at_ms=90, outcome='indicative', provenance='synthetic')
        report = store.quality_report()
        assert report['missing_transactions'] == report['rejected_candidates'] == 1
        assert report['unavailable_quotes'] == 1
        assert report['quotes_without_source_time'] == 2
        assert report['fx_without_source_time'] == 1
        assert report['economic_validation'] == 'INSUFFICIENT DATA'
        assert report['market_detection_coverage'] is None
        assert report['p3_go'] is False
