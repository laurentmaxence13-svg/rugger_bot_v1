"""Streaming equivalent of the frozen ``bot.market.backfill_export.export_pools``: same files, byte for byte.

The frozen export reads EVERY transaction of the window into memory, sorts the list and keeps, per pool,
references to its transactions: about 37 KB of memory per stored transaction, i.e. far more than the
session's RAM for W1 (2.2 million transactions; the process was killed on day J). ``export_pools`` below
writes the SAME pool archives and the SAME ``MANIFEST.json`` and returns the SAME value while holding one
transaction at a time (passes 1 and 2) or one bucket of pools at a time (pass 3):

  pass 1  every transaction, in the manifest order: integer ``transactionIndex`` checked; for a successful
          one, the frozen ``compiled_launchlab_creations`` and ``extract_trade_events`` with the frozen
          ``try`` / ``except``. The creation kept for a pool is the FIRST one in the order
          (slot, transactionIndex, signature, reading rank): what the frozen stable sort + ``setdefault`` give.
  pass 2  every transaction again: ``set(account_keys(tx))`` (frozen) restricted to the created pools; for
          each such pool one record goes to a bucket file on disk: the frozen ``_signature_row`` and, for a
          successful transaction, the final JSON text of its body (same ``json.dumps``).
  pass 3  bucket by bucket, pool by pool: the history in the frozen order, the frozen rules in the frozen
          order (first successful transaction = the creation, ``creation_quote_mint``, SOL quote, flag near
          the end of the window), the same archive text, the same gzip stream (level 9, mtime 0), the same
          MANIFEST entry.

Nothing else differs: ``verify``, the window checks, the cutoff, the ``skipped`` reasons, the optional
SOL/USD reference and the MANIFEST are the frozen ones. Duplicate signatures behave as in the frozen code
(stable order, the last body wins). No rule is rewritten, no data is changed, no network.

``streaming_export()`` replaces ``backfill_export.export_pools`` for the duration of a ``with`` block, so
that the frozen ``w1_collection.export`` (window and credit-cap checks) is called unchanged.
"""
import contextlib
import gzip
import hashlib
import json
import shutil
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bot.market import backfill_export as bx
from bot.market.backfill import LAUNCHLAB_PROGRAM, BackfillError, verify
from bot.market.collector import ARCHIVE_VERSION
from bot.market.launchlab_events import WSOL_MINT, EventDecodeError

BUCKETS = 256
_COMPACT = dict(separators=(',', ':'), sort_keys=True)


class StreamExportError(RuntimeError):
    pass


def gzip_stream_is_the_one_shot_stream():
    """True when a chunked gzip stream equals ``gzip.compress(data, mtime=0)`` on this interpreter and zlib."""
    block = hashlib.sha256(b'w1aux').digest()
    data = b''.join(hashlib.sha256(block + bytes([i % 251])).hexdigest().encode() * (1 + i % 7) + b'{"k":%d}' % i
                    for i in range(40_000))
    stream = zlib.compressobj(9, zlib.DEFLATED, 31)
    out, cursor, step = [], 0, 1
    while cursor < len(data):
        out.append(stream.compress(data[cursor:cursor + step]))
        cursor, step = cursor + step, step * 3 % 65_521 + 1
    out.append(stream.flush())
    return b''.join(out) == gzip.compress(data, mtime=0)


def _rows(window_dir, manifest):
    """(reading rank, transaction) of every tx segment, one line at a time (same parse as read_segment)."""
    rank = 0
    for seg in manifest['segments']:
        if seg['kind'] != 'tx':
            continue
        with gzip.open(Path(window_dir) / seg['path'], 'rt', encoding='utf-8') as handle:
            for line in handle:
                yield rank, json.loads(line)
                rank += 1


def _bucket(pool, buckets):
    return int(hashlib.sha256(pool.encode()).hexdigest()[:12], 16) % buckets


def _first_pass(window_dir, manifest):
    """pool -> (key, rank, base mint, packed creation transaction), and the pools seen trading."""
    created, traded, bad_index, failure = {}, set(), False, None
    for rank, entry in _rows(window_dir, manifest):
        if type(entry.get('transactionIndex')) is not int:
            bad_index = True
        if bad_index or failure is not None:
            continue                                   # the frozen code checks every index before anything else
        try:
            key = (entry['slot'], entry['transactionIndex'], entry['signature'])
            if (entry.get('meta') or {}).get('err') is not None:
                continue
            try:
                launches = bx.compiled_launchlab_creations(entry)
            except ValueError:
                launches = []
            for launch in launches:
                best = created.get(launch['pool_state'])
                if best is None or (key, rank) < (best[0], best[1]):
                    packed = zlib.compress(json.dumps(entry, separators=(',', ':')).encode(), 1)
                    created[launch['pool_state']] = (key, rank, launch['mint'], packed)
            try:
                traded.update(event.pool for event in bx.extract_trade_events(entry))
            except EventDecodeError:
                pass
        except Exception as exc:                       # noqa: BLE001  (raised below, after the index check)
            failure = exc
    if bad_index:
        raise BackfillError('transaction_index_missing_use_gtfa_bodies')
    if failure is not None:
        raise failure
    return created, traded


def _second_pass(window_dir, manifest, created, work, buckets):
    """One record per (pool, member transaction) in the bucket file of the pool; returns the record count."""
    handles, records = {}, 0
    try:
        for rank, entry in _rows(window_dir, manifest):
            pools = [key for key in set(bx.account_keys(entry)) if key in created]
            if not pools:
                continue
            success = (entry.get('meta') or {}).get('err') is None
            body = json.dumps({k: v for k, v in entry.items() if k != 'signature'}, **_COMPACT) if success else ''
            head = [entry['slot'], entry['transactionIndex'], entry['signature'], rank, success, bx._signature_row(entry)]
            for pool in pools:
                index = _bucket(pool, buckets)
                if index not in handles:
                    handles[index] = gzip.open(work / f'bucket-{index:04d}.jsonl.gz', 'wt', encoding='utf-8',
                                               compresslevel=1)
                handles[index].write(json.dumps([pool] + head, separators=(',', ':')) + '\n' + body + '\n')
                records += 1
    finally:
        for handle in handles.values():
            handle.close()
    return records


def _write_archive(path, parts):
    """Write the gzip stream of ``''.join(parts)`` (level 9, mtime 0); return the sha256 of the file bytes."""
    stream, digest = zlib.compressobj(9, zlib.DEFLATED, 31), hashlib.sha256()
    with open(path, 'wb') as handle:
        for part in parts:
            data = stream.compress(part.encode())
            if data:
                digest.update(data)
                handle.write(data)
        data = stream.flush()
        digest.update(data)
        handle.write(data)
    return digest.hexdigest()


def _archive_parts(pool, signatures, transactions):
    """The text of json.dumps(archive, separators=(',', ':'), sort_keys=True), piece by piece."""
    yield '{"account":null,"pool":' + json.dumps(pool) + ',"signatures":' + json.dumps(signatures, **_COMPACT)
    yield ',"signatures_complete":true,"transactions":{'
    for number, signature in enumerate(sorted(transactions)):
        yield (',' if number else '') + json.dumps(signature) + ':' + transactions[signature]
    yield '},"version":' + json.dumps(ARCHIVE_VERSION, **_COMPACT) + '}'


def _export_bucket(job):
    """Pass 3 for one bucket: (MANIFEST entries, skipped reasons) of its pools."""
    bucket_path, creations_path, out_dir, slot_max = job
    out_dir = Path(out_dir)
    with gzip.open(creations_path, 'rt', encoding='utf-8') as handle:
        creations = json.load(handle)                  # pool -> [creation signature, base mint, creation transaction]
    members = {pool: [] for pool in creations}
    if Path(bucket_path).exists():
        with gzip.open(bucket_path, 'rt', encoding='utf-8') as handle:
            while True:
                head = handle.readline()
                if not head:
                    break
                pool, slot, index, signature, rank, success, row = json.loads(head)
                members[pool].append((slot, index, signature, rank, success, row, handle.readline()[:-1]))
    pools, skipped = [], {}
    for pool in sorted(members):
        history = sorted(members.pop(pool), key=lambda r: r[:4])
        creation_signature, base_mint, creation = creations[pool]
        successful = [r for r in history if r[4]]
        if successful[0][2] != creation_signature:
            skipped[pool] = 'earliest_transaction_is_not_the_creation'
            continue
        quote_mint = bx.creation_quote_mint(creation, pool, base_mint)
        if quote_mint != WSOL_MINT:
            skipped[pool] = f'quote_not_sol:{quote_mint}'
            continue
        near_end = history[-1][0] > slot_max - bx.NEAR_END_SLOTS
        transactions = {r[2]: r[6] for r in successful}           # history order: the last body of a signature wins
        signatures = [r[5] for r in reversed(history)]            # newest first
        name = f'{pool}.json.gz'
        sha256 = _write_archive(out_dir / name, _archive_parts(pool, signatures, transactions))
        pools.append({'pool': pool, 'file': name, 'sha256': sha256, 'quote_mint': quote_mint,
                      'signatures': len(signatures), 'transactions': len(transactions),
                      'first_slot': history[0][0], 'last_slot': history[-1][0],
                      'active_near_window_end': near_end})
    return pools, skipped


def export_pools(window_dir, out_dir, *, entry_cutoff_gap_slots=bx.DEFAULT_CUTOFF_GAP_SLOTS, sol_usd_series=None,
                 collector_code=None, work_dir=None, buckets=BUCKETS, workers=1):
    """Same arguments, files and return value as the frozen export_pools (``work_dir``: temporary, removed)."""
    window_dir, out_dir = Path(window_dir), Path(out_dir)
    if type(buckets) is not int or buckets < 1 or type(workers) is not int or workers < 1:
        raise StreamExportError('invalid_buckets_or_workers')
    if not gzip_stream_is_the_one_shot_stream():
        raise StreamExportError('chunked_gzip_differs_from_gzip_compress_on_this_interpreter')
    checked = verify(window_dir)
    manifest = json.loads((window_dir / 'manifest.json').read_text())
    if not checked['ok'] or not manifest['complete']:
        raise BackfillError('window_not_verified_or_incomplete')
    if manifest['window']['address'] != LAUNCHLAB_PROGRAM:
        raise BackfillError('export_needs_a_launchlab_program_window')
    slot_max = manifest['window']['slot_max']
    if type(entry_cutoff_gap_slots) is not int or entry_cutoff_gap_slots < bx.MIN_CUTOFF_GAP_SLOTS:
        raise BackfillError(f'entry_cutoff_gap_slots_below_{bx.MIN_CUTOFF_GAP_SLOTS}')
    entry_cutoff_slot = slot_max - entry_cutoff_gap_slots
    if entry_cutoff_slot <= manifest['window']['slot_min']:
        raise BackfillError('window_shorter_than_entry_cutoff_gap')
    work = Path(work_dir) if work_dir is not None else out_dir.parent / (out_dir.name + '.stream_tmp')
    if work.exists():
        raise StreamExportError('work_directory_already_exists')

    created, traded = _first_pass(window_dir, manifest)
    # Pools trading in the window but created before it are counted, never dropped silently.
    skipped = {pool: 'creation_not_in_window' for pool in traded - set(created)}
    work.mkdir(parents=True)
    try:
        _second_pass(window_dir, manifest, created, work, buckets)
        by_bucket = {}
        for pool, (key, _rank, mint, packed) in created.items():
            by_bucket.setdefault(_bucket(pool, buckets), {})[pool] = [key[2], mint, json.loads(zlib.decompress(packed))]
        created.clear()
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs = []
        for index in sorted(by_bucket):
            path = work / f'creations-{index:04d}.json.gz'
            with gzip.open(path, 'wt', encoding='utf-8', compresslevel=1) as handle:
                json.dump(by_bucket[index], handle, separators=(',', ':'))
            jobs.append((str(work / f'bucket-{index:04d}.jsonl.gz'), str(path), str(out_dir), slot_max))
        by_bucket.clear()
        if workers == 1:
            results = [_export_bucket(job) for job in jobs]
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                results = list(executor.map(_export_bucket, jobs))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    pools = []
    for found, reasons in results:
        pools.extend(found)
        skipped.update(reasons)
    pools.sort(key=lambda entry: entry['pool'])
    series_ref = None
    if sol_usd_series is not None:
        from bot.market.sol_usd_collect import canonical_sha256
        source = Path(sol_usd_series)
        data = source.read_bytes()
        document = json.loads(gzip.decompress(data) if source.suffix == '.gz' else data)
        name = 'sol_usd_series.json.gz' if source.suffix == '.gz' else 'sol_usd_series.json'
        (out_dir / name).write_bytes(data)
        kinds = sorted({p['source_kind'] for p in document['points']})
        series_ref = {'file': name, 'file_sha256': hashlib.sha256(data).hexdigest(),
                      'canonical_sha256': canonical_sha256(document), 'label': document['label'],
                      'source_kinds': kinds, 'points': len(document['points'])}
    export = {'schema': bx.SCHEMA_EXPORT, 'version': 2, 'pools': pools,
              'entry_cutoff_slot': entry_cutoff_slot, 'window_slot_max': slot_max,
              'entry_cutoff_gap_slots': entry_cutoff_gap_slots, 'sol_usd_series': series_ref,
              'source': {'window': manifest['window'],
                         'window_manifest_sha256': checked['manifest_sha256'],
                         'endpoint': manifest['endpoint']},
              'collection_budget': manifest['budget'],
              'collector_code': collector_code,
              'skipped': dict(sorted(skipped.items())),
              'contents': 'Per-pool archives rebuilt from a verified LaunchLab program-window '
                          'backfill; account is null by design (never an L1 input).'}
    (out_dir / 'MANIFEST.json').write_text(json.dumps(export, indent=2, sort_keys=True) + '\n')
    return export


@contextlib.contextmanager
def streaming_export(*, work_dir=None, buckets=BUCKETS, workers=1):
    """Within the block, every frozen caller of backfill_export.export_pools gets the streaming one."""
    original = bx.export_pools

    def replacement(window_dir, out_dir, **kwargs):
        return export_pools(window_dir, out_dir, work_dir=work_dir, buckets=buckets, workers=workers, **kwargs)
    bx.export_pools = replacement
    try:
        yield
    finally:
        bx.export_pools = original
