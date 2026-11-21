"""cpmmfmt 0.1 -- FORMAT check of the cpmmx log parser on the CPMM frames of the migration transactions of P0 VISIBLE.

Authorized by R02 (d67570d9) under conditions: script audited by R02 BEFORE execution; input = the anchored VISIBLE pack
only (never the 9f19ccac holdout: the MANIFEST sha must equal the anchored visible one); output = COUNTS ONLY; run
offline by R03; NOT creditable for C-1 (no swap of an established pool is in a LaunchLab collection).

  python -B -m cpmmfmt.check --pack <P0 visible pack> --manifest-sha256 <anchored visible MANIFEST sha> --out <DIR>

For every archive (file sha checked against the MANIFEST, one archive in memory at a time) and every transaction whose
logs name the CPMM program: depth of its CPMM frames (1 = top level, >1 = called by another program), result of
``cpmmx.events.program_frames`` (ok, or the error class), and for each payload logged in a CPMM frame the decoded kind
(swap_current / swap_legacy / lp_change / other_discriminator) or the decode error class. Failed transactions are
counted apart. Output: FORMAT_COUNTS.json, whitelisted integer counts only: no pool, no signature, no amount, no slot.
Standard library + cpmmx only; no network.
"""
import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from cpmmx import events as ev

SCHEMA = 'cpmmfmt-v0.1'
PREFIX = 'Program ' + ev.CPMM_PROGRAM + ' invoke ['


class FormatError(RuntimeError):
    pass


def _kind(payload):
    try:
        event = ev.decode(payload)
    except ev.EventDecodeError as exc:
        return 'decode_error:' + str(exc).split(':')[0]
    if event is None:
        return 'other_discriminator'
    if isinstance(event, ev.LpChangeEvent):
        return 'lp_change'
    return 'swap_legacy' if getattr(event, 'layout', None) == 'legacy' else 'swap_current'


def count_transaction(tx, counts):
    logs = (tx.get('meta') or {}).get('logMessages')
    if not logs or not any(line.startswith(PREFIX) for line in logs):
        return
    counts['transactions_with_cpmm'] += 1
    for line in logs:
        if line.startswith(PREFIX):
            depth = int(line[len(PREFIX):].rstrip(']'))
            counts['cpmm_frames_depth_1' if depth == 1 else 'cpmm_frames_depth_2_plus'] += 1
    if (tx.get('meta') or {}).get('err') is not None:
        counts['failed_transactions_with_cpmm'] += 1
    try:
        frames = ev.program_frames(logs)
    except ev.EventDecodeError as exc:
        counts['frames_error:' + type(exc).__name__ + ':' + str(exc).split(':')[0]] += 1
        return
    counts['frames_ok'] += 1
    for payload, _depth in frames:
        counts['payload:' + _kind(payload)] += 1


def run(pack, manifest_sha256):
    pack = Path(pack)
    raw = (pack / 'MANIFEST.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise FormatError('manifest_is_not_the_anchored_visible_one')
    manifest = json.loads(raw)
    counts = Counter()
    for entry in sorted(manifest['pools'], key=lambda e: e['pool']):
        data = (pack / entry['file']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise FormatError('archive_sha256_mismatch')
        archive = json.loads(gzip.decompress(data))
        counts['archives'] += 1
        transactions = archive.get('transactions') or {}
        counts['transactions'] += len(transactions)
        before = counts['transactions_with_cpmm']
        for tx in transactions.values():
            count_transaction(tx, counts)
        if counts['transactions_with_cpmm'] > before:
            counts['archives_with_cpmm'] += 1
        del archive, data
    return dict(schema=SCHEMA, manifest_sha256=manifest_sha256, counts=dict(sorted(counts.items())),
                creditable_for_c1=False, network=False,
                scope='format of the cpmmx log parser on CPMM frames of LaunchLab migration transactions; counts only')


def main(argv=None):
    p = argparse.ArgumentParser(prog='cpmmfmt.check')
    p.add_argument('--pack', type=Path, required=True)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    if a.out.exists():
        raise FormatError('output_exists')
    doc = run(a.pack, a.manifest_sha256)
    a.out.mkdir(parents=True)
    path = a.out / 'FORMAT_COUNTS.json'
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + '\n', encoding='utf-8')
    print(hashlib.sha256(path.read_bytes()).hexdigest())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
