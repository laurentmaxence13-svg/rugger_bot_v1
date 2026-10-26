"""Append-only, locally available point-in-time capture in a separate database.

The hash chain detects corruption relative to a retained anchor; it is not a
signature and cannot prove integrity against someone who rewrites the whole DB.
Source time is never substituted for the time evidence became locally available.
"""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit


_APPLICATION_ID = 0x52554733  # RUG3, not the PAPER application's ledger.
_VERSION = 1
_TABLE = 'p3_capture_events'
_GENESIS = '0' * 64
_MAX_INTEGER = 2**63 - 1
_KINDS = frozenset(('transaction', 'launch', 'candidate_decision', 'quote_attempt',
                    'fx', 'gap', 'checkpoint', 'request'))
_PROVENANCES = frozenset(('live', 'synthetic', 'historical_replay'))
_URL = re.compile(r'(?:https?|wss?)://[^\s<>"\']+', re.IGNORECASE)
_AUTH_TEXT = re.compile(
    r'\b(?:api[_-]?key|authorization|access[_-]?token|password|secret|private[_-]?key)\s*[:=]',
    re.IGNORECASE)
_SECRET_KEYS = frozenset(('apikey', 'authorization', 'proxyauthorization',
                         'accesstoken', 'refreshtoken', 'password', 'passwd',
                         'secret', 'clientsecret', 'privatekey', 'seedphrase',
                         'mnemonic', 'keypair', 'cookie', 'setcookie', 'xapikey',
                         'authtoken', 'xauthtoken', 'bearertoken', 'secretkey',
                         'subscriptionkey', 'ocpapimsubscriptionkey'))


class CaptureIntegrityError(ValueError):
    """Stored capture evidence does not match its append-only hash chain."""


def _integer(value, name):
    if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
        raise ValueError('Invalid ' + name)
    return value


def _safe_json(value):
    """Reject authentication material without echoing keys or values in errors."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError('Capture JSON keys must be strings')
            normalized = re.sub(r'[^a-z0-9]', '', key.lower())
            if normalized in _SECRET_KEYS:
                raise ValueError('Authentication material is forbidden in capture evidence')
            _safe_json(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _safe_json(item)
    elif isinstance(value, str):
        if _AUTH_TEXT.search(value):
            raise ValueError('Authentication material is forbidden in capture evidence')
        for match in _URL.finditer(value):
            try:
                url = urlsplit(match.group())
            except ValueError:
                raise ValueError('Invalid URL in capture evidence') from None
            # Store logical provider names, not request URLs with arbitrary
            # query/fragment values whose authentication semantics are unknown.
            if url.username is not None or url.password is not None or url.query or url.fragment:
                raise ValueError('Authenticated or parameterized URLs are forbidden in capture evidence')
    elif value is not None and type(value) not in (bool, int, float):
        raise ValueError('Capture evidence must be JSON data')
    elif type(value) is float and not math.isfinite(value):
        raise ValueError('Capture evidence must contain finite numbers')


def _canonical(value):
    _safe_json(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _raw(value):
    # Invalid source dates must remain inspectable without inserting NaN/inf
    # into JSON or coercing booleans/strings into authoritative integers.
    if type(value) is float and not math.isfinite(value):
        return {'type': 'float', 'value': str(value)}
    _safe_json(value)
    return value


class CaptureStore:
    """Dedicated journal; existing databases require this exact schema marker.

    received_at_ms is the collector's receipt time. The stored_at_ms field is
    measured after acquiring the write lock, before commit: it is an ingestion
    barrier, NOT proof of durability at that timestamp. available_at_ms is the
    maximum of receipt/ingestion/previous availability, so neither lock waiting
    nor replays backdate new ingestion. Consumers must wait for append to return
    (after commit) before using its evidence. The journal does not certify an
    exact durable-commit timestamp. clock_ms supports deterministic offline tests.
    """

    def __init__(self, path, *, clock_ms=None, readonly=False):
        self.path = Path(path)
        if clock_ms is not None and not callable(clock_ms):
            raise ValueError('clock_ms must be callable')
        if type(readonly) is not bool:
            raise ValueError('readonly must be a boolean')
        self._clock_ms = clock_ms if clock_ms is not None else (lambda: time.time_ns() // 1_000_000)
        self._readonly = readonly
        self._con = None
        if str(path) == ':memory:':
            raise ValueError('Use a dedicated persistent capture path')
        if readonly:
            if not self.path.is_file():
                raise ValueError('Read-only capture file is missing')
            try:
                uri = self.path.resolve().as_uri() + '?mode=ro&immutable=1'
                self._con = sqlite3.connect(uri, uri=True, isolation_level=None)
                self._check_schema(self._con)
                self.verify_integrity()
            except BaseException:
                self.close()
                raise
            return
        created = False
        if self.path.exists():
            self._inspect_existing()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation distinguishes our new empty file from a
            # pre-existing empty/user database, including an initialization race.
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                self._inspect_existing()
            else:
                os.close(descriptor)
                created = True
        try:
            con = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            self._con = con
            con.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                self._check_schema(con)
            elif created:
                # Only a newly-created file can be initialized. An empty file
                # pre-existing at the read-only inspection was already refused.
                con.execute(f'PRAGMA application_id={_APPLICATION_ID}')
                con.execute(f'PRAGMA user_version={_VERSION}')
                con.execute(f'''CREATE TABLE {_TABLE}(
                    id INTEGER PRIMARY KEY CHECK(id>0),
                    available_at_ms INTEGER NOT NULL CHECK(available_at_ms>=0),
                    envelope_json TEXT NOT NULL, payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, previous_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL UNIQUE)''')
                con.execute(f'CREATE INDEX p3_available_idx ON {_TABLE}(available_at_ms,id)')
                for operation in ('UPDATE', 'DELETE'):
                    con.execute(f'''CREATE TRIGGER p3_no_{operation.lower()}
                        BEFORE {operation} ON {_TABLE} BEGIN
                        SELECT RAISE(ABORT,'capture journal is append-only'); END''')
            else:
                raise ValueError('Refusing an empty or replaced capture schema')
            con.commit()
            self.verify_integrity()
        except BaseException:
            self.close()
            raise

    def _inspect_existing(self):
        # immutable avoids sidecar creation or recovery writes while deciding
        # whether this is a capture journal rather than a user's PAPER ledger.
        uri = self.path.resolve().as_uri() + '?mode=ro&immutable=1'
        with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as con:
            self._check_schema(con)

    @staticmethod
    def _check_schema(con):
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        marker = con.execute('PRAGMA application_id').fetchone()[0]
        version = con.execute('PRAGMA user_version').fetchone()[0]
        columns = [row[1] for row in con.execute(f'PRAGMA table_info({_TABLE})')]
        triggers = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if (tables != {_TABLE} or marker != _APPLICATION_ID or version != _VERSION
                or columns != ['id', 'available_at_ms', 'envelope_json', 'payload_json',
                               'payload_sha256', 'previous_hash', 'record_hash']
                or not {'p3_no_update', 'p3_no_delete'} <= triggers):
            raise ValueError('Refusing a historical ledger or unknown capture schema')

    def close(self):
        if self._con is not None:
            con, self._con = self._con, None
            con.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _connection(self):
        if self._con is None:
            raise ValueError('Capture store is closed')
        return self._con

    def append(self, kind, *, received_at_ms, outcome, source_time_ms=None,
               source_slot=None, signature=None, mint=None, reason=None,
               payload=None, request_id=None, provenance='live'):
        """Append atomically; return only after commit, with precommit ingestion time."""
        if self._readonly:
            raise ValueError('Read-only capture store cannot append')
        if kind not in _KINDS or provenance not in _PROVENANCES:
            raise ValueError('Invalid capture kind or provenance')
        if not isinstance(outcome, str) or not outcome:
            raise ValueError('Capture outcome is required')
        received = _integer(received_at_ms, 'receipt timestamp')
        if any(value is not None and not isinstance(value, str)
               for value in (signature, mint, reason, request_id)):
            raise ValueError('Capture identifiers and reasons must be strings')
        flags = []
        valid_time = type(source_time_ms) is int and 0 < source_time_ms <= received
        if source_time_ms is None:
            flags.append('source_time_unknown')
        elif not valid_time:
            flags.append('source_time_future' if type(source_time_ms) is int
                         and source_time_ms > received else 'source_time_invalid')
        valid_slot = type(source_slot) is int and 0 <= source_slot <= _MAX_INTEGER
        if source_slot is not None and not valid_slot:
            flags.append('source_slot_invalid')
        serialized = _canonical(payload)
        if kind == 'gap':
            gap_id = payload.get('gap_id') if isinstance(payload, dict) else None
            if not isinstance(gap_id, str) or not gap_id or outcome not in ('open', 'closed'):
                raise ValueError('Gap observations require a stable gap_id and open/closed outcome')
        con = self._connection()
        try:
            con.execute('BEGIN IMMEDIATE')
            stored = _integer(self._clock_ms(), 'local clock timestamp')
            if received > stored:
                flags.append('receipt_after_storage_clock')
            tail = con.execute(f'SELECT id,available_at_ms,record_hash,envelope_json FROM {_TABLE} ORDER BY id DESC LIMIT 1').fetchone()
            previous_id, previous_available, previous_hash, previous_envelope = tail or (0, 0, _GENESIS, '{"stored_at_ms":0}')
            if stored < json.loads(previous_envelope)['stored_at_ms']:
                flags.append('local_clock_regressed')
            available = max(received, stored, previous_available)
            envelope = dict(kind=kind, received_at_ms=received, stored_at_ms=stored,
                            available_at_ms=available, outcome=outcome,
                            source_time_ms=source_time_ms if valid_time else None,
                            source_time_raw=_raw(source_time_ms),
                            source_slot=source_slot if valid_slot else None,
                            source_slot_raw=_raw(source_slot), signature=signature,
                            mint=mint, reason=reason, request_id=request_id,
                            provenance=provenance, quality_flags=flags)
            envelope_json = _canonical(envelope)
            identity = previous_id + 1
            payload_hash = _hash(serialized)
            record_hash = _hash(_canonical(dict(id=identity, envelope=envelope,
                payload_sha256=payload_hash, previous_hash=previous_hash)))
            con.execute(f'INSERT INTO {_TABLE} VALUES(?,?,?,?,?,?,?)',
                        (identity, available, envelope_json, serialized, payload_hash,
                         previous_hash, record_hash))
            con.commit()
            return identity
        except BaseException:
            con.rollback()
            raise

    def _records(self):
        return self._connection().execute(f'SELECT * FROM {_TABLE} ORDER BY id').fetchall()

    def verify_integrity(self):
        return self._verify_records(self._records())

    @staticmethod
    def _verify_records(records):
        previous_hash, previous_available = _GENESIS, 0
        for expected_id, row in enumerate(records, 1):
            identity, available, raw_envelope, raw_payload, payload_hash, prior, record_hash = row
            try:
                envelope, payload = json.loads(raw_envelope), json.loads(raw_payload)
                valid = (identity == expected_id and prior == previous_hash
                         and type(available) is int and available >= previous_available
                         and available == envelope['available_at_ms']
                         and _hash(_canonical(payload)) == payload_hash
                         and _hash(_canonical(dict(id=identity, envelope=envelope,
                             payload_sha256=payload_hash, previous_hash=prior))) == record_hash)
            except (ValueError, TypeError, KeyError):
                valid = False
            if not valid:
                raise CaptureIntegrityError('Capture journal integrity check failed')
            previous_hash, previous_available = record_hash, available
        return previous_hash

    def events(self, as_of_ms=None, kind=None):
        if as_of_ms is not None:
            _integer(as_of_ms, 'as-of timestamp')
        if kind is not None and kind not in _KINDS:
            raise ValueError('Invalid capture kind')
        records = self._records()
        self._verify_records(records)
        result = []
        for identity, available, raw_envelope, raw_payload, payload_hash, prior, record_hash in records:
            envelope = json.loads(raw_envelope)
            if ((as_of_ms is None or available <= as_of_ms)
                    and (kind is None or envelope['kind'] == kind)):
                result.append(dict(envelope, id=identity, payload=json.loads(raw_payload),
                                   payload_sha256=payload_hash, previous_hash=prior,
                                   record_hash=record_hash))
        return result

    def quality_report(self, as_of_ms=None):
        records = self.events(as_of_ms=as_of_ms)
        kinds, outcomes, flags, provenances = {}, {}, {}, {}
        gaps, unmatched_closures = set(), 0
        for event in records:
            for counts, key in ((kinds, event['kind']), (outcomes, event['outcome']),
                                (provenances, event['provenance'])):
                counts[key] = counts.get(key, 0) + 1
            for flag in event['quality_flags']:
                flags[flag] = flags.get(flag, 0) + 1
            if event['kind'] == 'gap':
                gap_id = event['payload']['gap_id']
                if event['outcome'] == 'open':
                    gaps.add(gap_id)
                elif gap_id in gaps:
                    gaps.remove(gap_id)
                else:
                    unmatched_closures += 1
        return {
            'schema': 'p3-capture-quality-v1', 'as_of_ms': as_of_ms,
            'records': len(records), 'kind_counts': kinds, 'outcome_counts': outcomes,
            'provenance_counts': provenances, 'quality_flag_counts': flags,
            'open_gap_count': len(gaps), 'open_gap_ids': sorted(gaps),
            'unmatched_gap_closures': unmatched_closures,
            'missing_transactions': sum(e['kind'] == 'transaction' and e['outcome'] in
                                        ('missing', 'unavailable', 'failed', 'timeout') for e in records),
            'rejected_candidates': sum(e['kind'] == 'candidate_decision' and e['outcome'] in
                                      ('rejected', 'blocked', 'block') for e in records),
            'unavailable_quotes': sum(e['kind'] == 'quote_attempt' and e['outcome'] not in
                                     ('observed', 'available', 'ok', 'success', 'quoted') for e in records),
            'quotes_without_source_time': sum(e['kind'] == 'quote_attempt'
                                             and e['source_time_ms'] is None for e in records),
            'fx_without_source_time': sum(e['kind'] == 'fx' and e['source_time_ms'] is None
                                         for e in records),
            'integrity': 'verified_hash_chain_not_authenticated',
            'market_detection_coverage': None,
            'economic_validation': 'INSUFFICIENT DATA',
            'p3_go': False,
        }
