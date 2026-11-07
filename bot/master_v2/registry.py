"""Append-only, hash-chained registry of MASTER V2 research trials (R02 O3, O6).

Every run is registered BEFORE its replay. Each line is a canonical JSON object that
carries the SHA-256 of the previous line; editing or deleting any earlier line breaks
the chain and the registry is refused. ``evaluate`` requires every bundle to be
registered and every registered trial of the same data to be evaluated, so the
deflated Sharpe ratio counts all trials; only registered pre-registrations can
unseal a holdout. The chain head should be anchored outside this tool (T-REG, or a
message to RUGGER 02) to prove when each trial was declared.
"""
import hashlib
import json
from pathlib import Path

SCHEMA = 'rugger-master-v2-trial-registry-v1'
GENESIS = '0' * 64


def _digest(entry):
    body = {k: v for k, v in entry.items() if k != 'entry_sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def load(path):
    """All entries, after verifying the chain; [] for a missing file."""
    path = Path(path)
    if not path.exists():
        return []
    entries, previous = [], GENESIS
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines()):
        entry = json.loads(line)
        if (entry.get('schema') != SCHEMA or entry.get('index') != number
                or entry.get('previous_sha256') != previous or entry.get('entry_sha256') != _digest(entry)):
            raise ValueError(f'registry_chain_broken_at:{number}')
        entries.append(entry)
        previous = entry['entry_sha256']
    return entries


def head(path):
    entries = load(path)
    return entries[-1]['entry_sha256'] if entries else GENESIS


def register(path, record, *, registered_at):
    """Append ``record`` (a pre-registration) unless that pre-registration is already there."""
    if type(registered_at) is not str or not registered_at:
        raise ValueError('registered_at_required')
    entries = load(path)
    for entry in entries:
        if entry['preregistration_sha256'] == record['preregistration_sha256']:
            return entry, False
    entry = dict(record, schema=SCHEMA, index=len(entries), registered_at=registered_at,
                 previous_sha256=entries[-1]['entry_sha256'] if entries else GENESIS)
    entry['entry_sha256'] = _digest(entry)
    with Path(path).open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
    return entry, True


def trials_for(entries, manifest_sha256):
    return {entry['preregistration_sha256'] for entry in entries if entry['manifest_sha256'] == manifest_sha256}
