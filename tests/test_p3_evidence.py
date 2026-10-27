"""Synthetic durable bundles, without provider calls or real market fixtures."""
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from bot.p3 import evidence
from bot.p3.store import CaptureStore, CaptureIntegrityError


REVISION = 'a' * 40


def fixture(tmp_path):
    source = tmp_path / 'capture.sqlite'
    times = iter((2_000, 1_900, 2_200))
    with CaptureStore(source, clock_ms=lambda: next(times)) as store:
        store.append('pool_snapshot', received_at_ms=1_990, source_slot=11,
                     source_time_ms=1_800, outcome='observed', provenance='synthetic',
                     payload={'requested_addresses': ['pool', 'mint'], 'raw_rpc_result': {
                         'context': {'slot': 11}, 'value': [{'data': ['AAAA', 'base64']}, None]}})
        store.append('gap', received_at_ms=1_850, outcome='open', reason='missing_quote',
                     payload={'gap_id': 'synthetic-gap'}, provenance='synthetic')
        store.append('candidate_decision', received_at_ms=2_100, outcome='blocked',
                     payload={'entry_permitted': False}, provenance='synthetic')
        events, tail = store.events(), store.verify_integrity()
    return source, events, tail


def export(source, target):
    return evidence.export_capture(source, target, run_id='synthetic-001', source_revision=REVISION,
        plan_sha256='b'*64, completeness={'pool_accounts': 'retained', 'quote_raw_body': 'unavailable'})


def rewrite_payload_files(directory, events):
    raw = b''.join((json.dumps(event, sort_keys=True, separators=(',', ':'))+'\n').encode()
                   for event in events)
    compressed = gzip.compress(raw, mtime=0)
    (directory/'events.jsonl.gz').write_bytes(compressed)
    p = directory/'manifest.json'
    manifest = json.loads(p.read_text())
    manifest.update(records=len(events), compressed_bytes=len(compressed), uncompressed_bytes=len(raw),
                    compressed_sha256=hashlib.sha256(compressed).hexdigest(),
                    uncompressed_sha256=hashlib.sha256(raw).hexdigest(),
                    tail_hash=events[-1]['record_hash'] if events else '0'*64)
    p.write_text(json.dumps(manifest))


def test_portable_round_trip_preserves_original_evidence_and_times(tmp_path):
    source, original, tail = fixture(tmp_path)
    before = source.read_bytes()
    a, b = tmp_path/'a', tmp_path/'b'
    manifest = export(source, a)
    assert export(source, b) == manifest
    assert (a/'events.jsonl.gz').read_bytes() == (b/'events.jsonl.gz').read_bytes()
    assert (a/'manifest.json').read_bytes() == (b/'manifest.json').read_bytes()
    # Remove the original journal: a replay must depend only on portable files.
    assert source.read_bytes() == before
    source.unlink()
    replay = evidence.verify_bundle(a, expected_tail=tail)
    assert replay['events'] == original
    assert replay['records'] == 3 and replay['tail_hash'] == tail
    assert replay['events'][1]['stored_at_ms'] == 1_900
    assert replay['events'][1]['available_at_ms'] == 2_000
    assert 'local_clock_regressed' in replay['events'][1]['quality_flags']
    assert all(event['provenance'] == 'synthetic' for event in replay['events'])
    assert sorted(path.name for path in a.iterdir()) == ['events.jsonl.gz', 'manifest.json']
    assert manifest['completeness']['quote_raw_body'] == 'unavailable'


def test_tampering_is_rejected_even_if_outer_file_digests_are_recalculated(tmp_path):
    source, events, _ = fixture(tmp_path)
    target = tmp_path/'bundle'
    export(source, target)
    events[0]['payload']['raw_rpc_result']['context']['slot'] = 999
    rewrite_payload_files(target, events)
    with pytest.raises(CaptureIntegrityError):
        evidence.verify_bundle(target)


def test_retained_anchor_detects_coherent_suffix_truncation(tmp_path):
    source, events, tail = fixture(tmp_path)
    target = tmp_path/'bundle'
    export(source, target)
    rewrite_payload_files(target, events[:-1])
    assert evidence.verify_bundle(target)['records'] == 2
    with pytest.raises(ValueError, match='anchor'):
        evidence.verify_bundle(target, expected_tail=tail)


def test_legacy_database_and_existing_destination_are_never_changed(tmp_path):
    legacy = tmp_path/'paper.sqlite'
    with sqlite3.connect(legacy) as con:
        con.execute('CREATE TABLE paper_portfolio(capital_sol REAL)')
        con.execute('INSERT INTO paper_portfolio VALUES(10)')
    original = legacy.read_bytes()
    with pytest.raises(ValueError):
        export(legacy, tmp_path/'refused')
    assert legacy.read_bytes() == original and not (tmp_path/'refused').exists()
    source, _, _ = fixture(tmp_path)
    target = tmp_path/'existing'
    target.mkdir()
    retained = target/'manifest.json'
    retained.write_text('original')
    with pytest.raises(ValueError, match='new'):
        export(source, target)
    assert retained.read_text() == 'original' and list(target.iterdir()) == [retained]


def test_export_and_replay_enforce_explicit_byte_limits(tmp_path, monkeypatch):
    source, _, _ = fixture(tmp_path)
    target = tmp_path/'bundle'
    export(source, target)
    monkeypatch.setattr(evidence, 'MAX_EVIDENCE_BYTES', 100)
    with pytest.raises(ValueError):
        export(source, tmp_path/'too-large')
    assert not (tmp_path/'too-large').exists()
    with pytest.raises(ValueError):
        evidence.verify_bundle(target)


def test_invalid_manifest_and_credential_shaped_metadata_fail_before_export(tmp_path):
    source, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match='Authentication'):
        evidence.export_capture(source, tmp_path/'unsafe', run_id='synthetic', source_revision=REVISION,
                                completeness={'api_key': 'must-never-be-captured'})
    assert not (tmp_path/'unsafe').exists()
    target = tmp_path/'bundle'
    export(source, target)
    manifest = target/'manifest.json'
    payload = json.loads(manifest.read_text())
    payload['archive'] = '../../another-file'
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='schema'):
        evidence.verify_bundle(target)
