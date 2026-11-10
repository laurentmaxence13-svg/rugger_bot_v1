"""Synthetic scale pack (R02 C-Z2): the frozen test pack copied K times with renamed pools.

For LOAD MEASUREMENT ONLY (time and memory slope of the W1 chain), never for any economic reading.
Each copy k of a pool replaces its 32-byte pool address everywhere: in every JSON string equal to its
base58 form (account keys, balances, ...) and inside every base58 instruction ``data`` blob (event
payloads carry the pool bytes). Signatures, slots and block times are unchanged. The copies'
transaction signatures no longer match their (rewritten) messages, so their creation is not
signature-verified: V2 policies requiring a signed creator abstain on the copies and the L1
arms WAIT, while the L1 observer still scores every decision (the dominant output). The MANIFEST
is rebuilt with each file's sha256 and a ``synthetic`` block naming the source pack.
"""
import gzip
import hashlib
import json
from pathlib import Path

from bot.market.launchlab_events import b58decode, b58encode

SOURCE = Path('tests/fixtures/launchlab_sol_pools')
SOURCE_MANIFEST_SHA256 = '3224686db130e6b8e0c96a0a8e4bc19ad2cb5f62484ae7c0ae5707716b497e5e'


class SyntheticError(RuntimeError):
    pass


def _rename(value, old_b58, new_b58, old_raw, new_raw):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == 'data' and isinstance(item, str) and item:
                try:
                    raw = b58decode(item)
                except ValueError:
                    raw = None
                if raw is not None and old_raw in raw:
                    out[key] = b58encode(raw.replace(old_raw, new_raw))
                    continue
            out[key] = _rename(item, old_b58, new_b58, old_raw, new_raw)
        return out
    if isinstance(value, list):
        return [_rename(item, old_b58, new_b58, old_raw, new_raw) for item in value]
    if value == old_b58:
        return new_b58
    return value


def new_pool_address(pool, copy):
    return b58encode(hashlib.sha256(f'w1aux-synthetic:{copy}:{pool}'.encode()).digest())


def build(out, copies):
    """Write the frozen pack x ``copies`` (copy 0 = the original pools) to ``out``; return the MANIFEST."""
    if type(copies) is not int or copies < 1:
        raise SyntheticError('copies_must_be_a_positive_integer')
    raw_manifest = (SOURCE / 'MANIFEST.json').read_bytes()
    if hashlib.sha256(raw_manifest).hexdigest() != SOURCE_MANIFEST_SHA256:
        raise SyntheticError('source_is_not_the_frozen_test_pack')
    out = Path(out)
    if out.exists():
        raise SyntheticError('output_directory_already_exists')
    out.mkdir(parents=True)
    manifest = json.loads(raw_manifest)
    entries = []
    for entry in manifest['pools']:
        source = json.loads(gzip.decompress((SOURCE / entry['file']).read_bytes()))
        old_raw = b58decode(entry['pool'])
        for copy in range(copies):
            pool = entry['pool'] if copy == 0 else new_pool_address(entry['pool'], copy)
            data = source if copy == 0 else _rename(source, entry['pool'], pool, old_raw, b58decode(pool))
            blob = gzip.compress(json.dumps(data, sort_keys=True).encode(), mtime=0)
            (out / f'{pool}.json.gz').write_bytes(blob)
            entries.append(dict(entry, pool=pool, file=f'{pool}.json.gz', sha256=hashlib.sha256(blob).hexdigest()))
    doc = dict(manifest, pools=sorted(entries, key=lambda e: e['pool']),
               synthetic=dict(source_manifest_sha256=SOURCE_MANIFEST_SHA256, copies=copies,
                              purpose='LOAD_MEASUREMENT_ONLY_NOT_FOR_ECONOMICS'))
    (out / 'MANIFEST.json').write_text(json.dumps(doc, indent=1, sort_keys=True))
    return doc
