"""The hash-chained journal (dossier T-R01-12 point 4): one JSON line per record; every record carries its sequence
number, the sha256 of the previous record (prev; 64 zeros for the first) and its own sha256 (over its canonical JSON
without 'sha'). A record changed afterwards changes every later sha, hence the head pushed every 15 min.
Records are buffered and written ONE STEP AT A TIME (commit: one write + fsync), so a killed process never leaves half
a step. REPLAY mode: on an existing journal, every append is compared with the next existing record (stable fields,
host clocks excluded) instead of being written; past the end, appending resumes normally (restart)."""
import hashlib
import json
import os
from pathlib import Path

ZERO = '0' * 64
KINDS = ('START', 'RECEIVED', 'G0', 'WAIT', 'DECISION', 'ORDER', 'LANDING', 'EXIT', 'MARK', 'GAP', 'STEP', 'CATCHUP', 'ERROR',
         'STOP')
RUNNER_KINDS = ('CATCHUP', 'ERROR', 'STOP')             # 0.1.4: written by the runner, never re-derived
VOLATILE = ('wall', 'mono_ns', 'processing_ms', 'fetch_ms')          # host clocks: published, excluded from the replay identity
CHAIN = ('seq', 'prev', 'sha')


class JournalError(ValueError):
    pass


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _sha(record):
    return hashlib.sha256(canonical({k: v for k, v in record.items() if k != 'sha'}).encode()).hexdigest()


def stable(record):
    """The record without its host clocks and chain fields: what the replay must reproduce byte for byte."""
    return {k: v for k, v in record.items() if k not in VOLATILE + CHAIN}


def read(path):
    lines = Path(path).read_text().split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    out = []
    for n, line in enumerate(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            raise JournalError('unreadable_line:%d' % n) from None
    return out


def verify_records(records):
    prev = ZERO
    for n, r in enumerate(records):
        if r.get('seq') != n or r.get('prev') != prev or r.get('kind') not in KINDS or r.get('sha') != _sha(r):
            raise JournalError('chain_broken_at:%d' % n)
        prev = r['sha']
    return prev


class Journal:
    def __init__(self, path, *, replay=False):
        self.path = Path(path)
        self.records = read(self.path) if self.path.exists() else []
        verify_records(self.records)
        self.loaded = len(self.records)                 # 0.1.5 (b): the records read from disk (0 for a new journal)
        if self.records and not replay:
            raise JournalError('existing_journal_needs_replay_mode')
        self.cursor = 0 if replay else len(self.records)
        self.pending = []

    @property
    def replaying(self):
        return self.cursor < len(self.records)

    @property
    def head(self):
        if self.pending:
            return self.pending[-1]['sha']
        return self.records[-1]['sha'] if self.records else ZERO

    def append(self, kind, **fields):
        if kind not in KINDS:
            raise JournalError('unknown_kind:%s' % kind)
        if set(fields) & set(CHAIN + ('kind',)):
            raise JournalError('reserved_field')
        candidate = dict(fields, kind=kind)
        self.skip_runner_records()
        if self.replaying:
            existing = self.records[self.cursor]
            if stable(existing) != stable(json.loads(canonical(candidate))):
                raise JournalError('replay_differs_at:%d' % self.cursor)
            self.cursor += 1
            return existing
        record = json.loads(canonical(dict(candidate, seq=len(self.records) + len(self.pending), prev=self.head)))
        record['sha'] = _sha(record)
        self.pending.append(record)
        return record

    def skip_runner_records(self):
        """CATCHUP / ERROR / STOP records are written by the runner, not re-derived by the engine: the replay steps over them."""
        while self.replaying and self.records[self.cursor]['kind'] in RUNNER_KINDS:
            self.cursor += 1

    def commit(self):
        if not self.pending:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'a') as handle:
            handle.write(''.join(canonical(r) + '\n' for r in self.pending))
            handle.flush()
            os.fsync(handle.fileno())
        self.records += self.pending
        self.cursor = len(self.records)
        self.pending = []
