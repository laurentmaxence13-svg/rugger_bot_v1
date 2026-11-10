"""Append-only, hash-chained dry-run journal (one JSON object per line).

Every record carries the sha256 of the previous record and the fixed dry-run
flags below. This file is the harness's own book: it is unrelated to
``bot.live.journal.ExecutionJournal`` and is never read by the live engine.
"""
import hashlib
import json
import os
from pathlib import Path

FLAGS = dict(
    dry_run=True, signed=False, submitted=False, funds_used=False,
    master_operational_trade=False, live_ready_to_arm=False,
    live_execution_verified=False, economic_edge_validated=False)
GENESIS = '0' * 64
_RESERVED = frozenset(('seq', 'kind', 'at_ms', 'prev_sha256', 'sha256', *FLAGS))


class JournalError(ValueError):
    """The dry-run journal is corrupt, tampered with or used inconsistently."""


def _no_floats(value):
    if type(value) is float:
        raise JournalError('float_amount_forbidden_in_dry_run_journal')
    if isinstance(value, dict):
        for item in value.values():
            _no_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _no_floats(item)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(body):
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def verify_journal(path, *, expected_head=None):
    """Return the records of a journal whose chain and flags are intact.

    A hash chain cannot see that its last records were removed or rewritten
    together; pass ``expected_head`` (a head hash noted elsewhere) to detect it.
    """
    records, previous = [], GENESIS
    with open(path, encoding='utf-8') as handle:
        for index, line in enumerate(handle):
            try:
                record = json.loads(line)
            except ValueError:
                raise JournalError(f'record_{index}_unparseable') from None
            if type(record) is not dict:
                raise JournalError(f'record_{index}_unparseable')
            body = {key: value for key, value in record.items() if key != 'sha256'}
            if record.get('seq') != index or record.get('prev_sha256') != previous:
                raise JournalError(f'record_{index}_chain_broken')
            if record.get('sha256') != _digest(body):
                raise JournalError(f'record_{index}_hash_mismatch')
            if any(record.get(flag) is not value for flag, value in FLAGS.items()):
                raise JournalError(f'record_{index}_dry_run_flags_altered')
            records.append(record)
            previous = record['sha256']
    if expected_head is not None and previous != expected_head:
        raise JournalError('journal_head_differs_from_expected_head')
    return records


class DryRunJournal:
    """Verified on open; the only mutation offered is ``append``."""

    def __init__(self, path):
        self.path = Path(path)
        self.records = verify_journal(self.path) if self.path.exists() else []

    @property
    def head(self):
        return self.records[-1]['sha256'] if self.records else GENESIS

    def append(self, kind, at_ms, **fields):
        if type(at_ms) is not int or at_ms < 0 or _RESERVED & fields.keys():
            raise JournalError('invalid_dry_run_record')
        _no_floats(fields)
        body = dict(fields, seq=len(self.records), kind=kind, at_ms=at_ms,
                    prev_sha256=self.head, **FLAGS)
        record = dict(body, sha256=_digest(body))
        with open(self.path, 'a', encoding='utf-8') as handle:
            handle.write(canonical(record) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        self.records.append(record)
        return record
