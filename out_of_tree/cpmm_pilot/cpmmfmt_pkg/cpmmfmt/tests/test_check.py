"""cpmmfmt: counts only, anchored visible MANIFEST, frame depths, decode kinds and error classes, no identifiers."""
import base64
import gzip
import hashlib
import json
import shutil
import socket
import struct
from pathlib import Path

import pytest

from cpmmfmt import check as C
from cpmmx import events as ev

PACK = Path.cwd() / 'tests' / 'fixtures' / 'launchlab_sol_pools'       # run from the frozen tree (aff97638)
CP = ev.CPMM_PROGRAM
POOL = bytes(range(32))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('network access attempted')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)


def _swap(current=True):
    head = struct.pack('<32s6Q?', POOL, 10, 20, 3, 4, 1, 0, True)
    tail = struct.pack('<32s32s2Q?', bytes(32), bytes([1]) * 32, 1, 0, True) if current else b''
    return 'Program data: ' + base64.b64encode(ev.SWAP_DISCRIMINATOR + head + tail).decode()


def _tx(lines, err=None):
    return dict(meta=dict(logMessages=lines, err=err), slot=1, blockTime=1, transactionIndex=0, transaction={})


TXS = {
    '5sigQmigrXz9': _tx(['Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj invoke [1]', f'Program {CP} invoke [2]',
                 _swap(), 'Program data: ' + base64.b64encode(b'\x01' * 8 + b'x').decode(), f'Program {CP} success',
                 'Program LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj success']),
    '5sigQtopXz9': _tx([f'Program {CP} invoke [1]', _swap(current=False), f'Program {CP} success']),
    '5sigQbadXz9': _tx([f'Program {CP} invoke [1]', 'Program data: ' + base64.b64encode(ev.SWAP_DISCRIMINATOR + b'z' * 7).decode(),
                f'Program {CP} success']),
    '5sigQunbXz9': _tx([f'Program {CP} invoke [1]', _swap()]),
    '5sigQtrnXz9': _tx([f'Program {CP} invoke [1]', 'Log truncated'], err={'x': 1}),
    '5sigQothXz9': _tx(['Program 11111111111111111111111111111111 invoke [1]', 'Program 11111111111111111111111111111111 success']),
}


def _pack(tmp_path):
    out = tmp_path / 'pack'
    shutil.copytree(PACK, out)
    manifest = json.loads((out / 'MANIFEST.json').read_text())
    entry = manifest['pools'][0]
    path = out / entry['file']
    doc = json.loads(gzip.decompress(path.read_bytes()))
    doc['transactions'].update(TXS)
    path.write_bytes(gzip.compress(json.dumps(doc).encode(), mtime=0))
    entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / 'MANIFEST.json').write_text(json.dumps(manifest))
    return out, hashlib.sha256((out / 'MANIFEST.json').read_bytes()).hexdigest()


def test_counts(tmp_path):
    pack, sha = _pack(tmp_path)
    doc = C.run(pack, sha)
    c = doc['counts']
    assert c['archives'] == 3 and c['archives_with_cpmm'] == 1 and c['transactions_with_cpmm'] == 5
    assert c['cpmm_frames_depth_2_plus'] == 1 and c['cpmm_frames_depth_1'] == 4
    assert c['frames_ok'] == 3 and c['frames_error:EventDecodeError:unbalanced_program_frames'] == 1
    assert c['frames_error:LogsTruncated:log_truncated'] == 1 and c['failed_transactions_with_cpmm'] == 1
    assert c['payload:swap_current'] == 1 and c['payload:swap_legacy'] == 1 and c['payload:other_discriminator'] == 1
    assert c['payload:decode_error:unknown_swap_event_size'] == 1
    assert doc['creditable_for_c1'] is False and doc['network'] is False


def test_only_counts_leave(tmp_path, capsys):
    pack, sha = _pack(tmp_path)
    assert C.main(['--pack', str(pack), '--manifest-sha256', sha, '--out', str(tmp_path / 'o')]) == 0
    text = (tmp_path / 'o' / 'FORMAT_COUNTS.json').read_text()
    assert capsys.readouterr().out.strip() == hashlib.sha256(text.encode()).hexdigest()
    doc = json.loads(text)
    assert all(type(v) is int for v in doc['counts'].values())
    manifest = json.loads((pack / 'MANIFEST.json').read_text())
    for entry in manifest['pools']:
        assert entry['pool'] not in text
    for key in TXS:
        assert key not in text
    assert ev.b58encode(POOL) not in text


def test_refusals(tmp_path):
    pack, sha = _pack(tmp_path)
    with pytest.raises(C.FormatError, match='manifest_is_not_the_anchored_visible_one'):
        C.run(pack, '0' * 64)
    first = json.loads((pack / 'MANIFEST.json').read_text())['pools'][1]['file']
    (pack / first).write_bytes(gzip.compress(b'{}'))
    with pytest.raises(C.FormatError, match='archive_sha256_mismatch'):
        C.run(pack, sha)
    (tmp_path / 'o').mkdir()
    with pytest.raises(C.FormatError, match='output_exists'):
        C.main(['--pack', str(pack), '--manifest-sha256', sha, '--out', str(tmp_path / 'o')])


def test_the_frozen_fixtures_hold_no_cpmm_transaction():
    sha = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
    c = C.run(PACK, sha)['counts']
    assert c['archives'] == 3 and 'transactions_with_cpmm' not in c
