"""Portable P3 evidence, without copying SQLite or changing observation times.

Bundles preserve the journal's logical JSON and original hash chain, not raw
HTTP bytes or provider authenticity. A caller-supplied completeness declaration
must disclose bodies discarded before export. Close the writer before export;
an active/WAL journal is outside this format's contract. No network is used.
"""
from io import BytesIO
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zlib

from bot.p3.store import CaptureStore, _canonical, _safe_json


MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_MAX_MANIFEST_BYTES = 64 * 1024
_ARCHIVE = 'events.jsonl.gz'
_MANIFEST = 'manifest.json'
_SCHEMA = 'p3-evidence-bundle-v1'
_HEX64 = re.compile(r'[0-9a-f]{64}\Z')
_REVISION = re.compile(r'[0-9a-f]{40}\Z')
_RUN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z')
_EXTRA = {'id', 'payload', 'payload_sha256', 'previous_hash', 'record_hash'}
_ENVELOPE = {'kind', 'received_at_ms', 'stored_at_ms', 'available_at_ms', 'outcome',
             'source_time_ms', 'source_time_raw', 'source_slot', 'source_slot_raw',
             'signature', 'mint', 'reason', 'request_id', 'provenance', 'quality_flags'}
_FIELDS = {'schema', 'run_id', 'source_revision', 'plan_sha256', 'records', 'tail_hash',
           'compressed_bytes', 'uncompressed_bytes', 'compressed_sha256',
           'uncompressed_sha256', 'completeness', 'archive'}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _hex(value):
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _identity(run_id, source_revision, completeness, plan_sha256):
    if type(run_id) is not str or _RUN.fullmatch(run_id) is None:
        raise ValueError('Invalid evidence run identifier')
    if type(source_revision) is not str or _REVISION.fullmatch(source_revision) is None:
        raise ValueError('Evidence requires a complete source revision')
    if type(completeness) is not dict:
        raise ValueError('Evidence requires an explicit completeness declaration')
    if plan_sha256 is not None and not _hex(plan_sha256):
        raise ValueError('Invalid retained plan digest')
    _safe_json(completeness)


def _rows(events):
    rows = []
    for event in events:
        if type(event) is not dict or set(event) != _ENVELOPE | _EXTRA:
            raise ValueError('Unexpected evidence event schema')
        if (type(event['id']) is not int or event['id'] < 1
                or any(not _hex(event[key]) for key in
                       ('payload_sha256', 'previous_hash', 'record_hash'))):
            raise ValueError('Invalid evidence event identity')
        envelope = {key: event[key] for key in _ENVELOPE}
        rows.append((event['id'], event['available_at_ms'], _canonical(envelope),
                     _canonical(event['payload']), event['payload_sha256'],
                     event['previous_hash'], event['record_hash']))
    return rows


def _read_bounded(path, maximum):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Evidence must be a regular file')
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Evidence exceeds its byte limit')
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate evidence JSON key')
        result[key] = value
    return result


def _json(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        _safe_json(value)
        return value
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Invalid evidence JSON') from error


def _publish_new(path, data):
    """Publish one complete file exclusively; never replace an existing name."""
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_capture(source_path, destination_dir, *, run_id, source_revision,
                   completeness: dict, plan_sha256=None):
    """Export a closed, dedicated P3 journal into a NEW directory.

    A manifest published last marks a complete bundle. An interrupted export may
    leave a partial new directory, which is refused on a retry instead of erased.
    Existing files and the source journal are never changed or copied as SQLite.
    """
    _identity(run_id, source_revision, completeness, plan_sha256)
    source, destination = Path(source_path), Path(destination_dir)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Evidence destination must be new')
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError('Evidence source is missing, unsupported or too large')
    if any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Close the journal; active/WAL evidence is not supported')
    with CaptureStore(source, readonly=True) as store:
        events = store.events()
        tail = store.verify_integrity()
    # Reuse exactly the original hash verifier before publishing any bytes.
    if CaptureStore._verify_records(_rows(events)) != tail:
        raise ValueError('Evidence export changed the retained chain')
    raw = b''.join((_canonical(event) + '\n').encode('utf-8') for event in events)
    if len(raw) > MAX_EVIDENCE_BYTES:
        raise ValueError('Evidence exceeds its byte limit')
    buffer = BytesIO()
    with gzip.GzipFile(filename='', fileobj=buffer, mode='wb', mtime=0) as stream:
        stream.write(raw)
    compressed = buffer.getvalue()
    if len(compressed) > MAX_EVIDENCE_BYTES:
        raise ValueError('Compressed evidence exceeds its byte limit')
    manifest = dict(schema=_SCHEMA, archive=_ARCHIVE, run_id=run_id,
                    source_revision=source_revision, plan_sha256=plan_sha256,
                    records=len(events), tail_hash=tail,
                    compressed_bytes=len(compressed), uncompressed_bytes=len(raw),
                    compressed_sha256=_sha(compressed), uncompressed_sha256=_sha(raw),
                    completeness=completeness)
    manifest_raw = (_canonical(manifest) + '\n').encode('utf-8')
    if len(manifest_raw) > _MAX_MANIFEST_BYTES:
        raise ValueError('Evidence manifest exceeds its byte limit')
    destination.mkdir(parents=True, exist_ok=False)
    _publish_new(destination / _ARCHIVE, compressed)
    _publish_new(destination / _MANIFEST, manifest_raw)
    return manifest


def verify_bundle(directory, expected_tail=None):
    """Verify a portable bundle entirely offline and return its original events.

    An expected_tail from a separately retained anchor also detects a coherent
    suffix truncation/replacement. The self-declared manifest is not a signature.
    Returned events retain their historical provenance and availability times;
    they must not be treated as newly observed live market data.
    """
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Evidence bundle directory is missing or unsupported')
    manifest = _json(_read_bounded(root / _MANIFEST, _MAX_MANIFEST_BYTES))
    if (type(manifest) is not dict or set(manifest) != _FIELDS
            or manifest.get('schema') != _SCHEMA or manifest.get('archive') != _ARCHIVE):
        raise ValueError('Unexpected evidence manifest schema')
    _identity(manifest['run_id'], manifest['source_revision'], manifest['completeness'],
              manifest['plan_sha256'])
    for key in ('records', 'compressed_bytes', 'uncompressed_bytes'):
        if type(manifest[key]) is not int or not 0 <= manifest[key] <= MAX_EVIDENCE_BYTES:
            raise ValueError('Invalid evidence size or count')
    if any(not _hex(manifest[key]) for key in
           ('tail_hash', 'compressed_sha256', 'uncompressed_sha256')):
        raise ValueError('Invalid evidence digest')
    if expected_tail is not None and not _hex(expected_tail):
        raise ValueError('Invalid expected evidence anchor')
    compressed = _read_bounded(root / _ARCHIVE, MAX_EVIDENCE_BYTES)
    if len(compressed) != manifest['compressed_bytes'] or _sha(compressed) != manifest['compressed_sha256']:
        raise ValueError('Compressed evidence digest or size mismatch')
    try:
        with gzip.GzipFile(fileobj=BytesIO(compressed), mode='rb') as stream:
            raw = stream.read(MAX_EVIDENCE_BYTES + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError('Invalid compressed evidence') from error
    if (len(raw) > MAX_EVIDENCE_BYTES or len(raw) != manifest['uncompressed_bytes']
            or _sha(raw) != manifest['uncompressed_sha256']):
        raise ValueError('Uncompressed evidence digest or size mismatch')
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Evidence JSONL is incomplete')
    events = [_json(line) for line in raw.splitlines()]
    if len(events) != manifest['records']:
        raise ValueError('Evidence record count mismatch')
    tail = CaptureStore._verify_records(_rows(events))
    if tail != manifest['tail_hash'] or expected_tail is not None and tail != expected_tail:
        raise ValueError('Evidence tail does not match its retained anchor')
    return dict(manifest, events=events)
