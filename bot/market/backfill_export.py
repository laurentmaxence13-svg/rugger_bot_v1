"""Turn a verified program-window backfill into per-pool archives for the L1 replay.

Output contract = what ``bot/p4/historical_research_replay.load_fixtures`` reads
(RUGGER 01, L1): a ``MANIFEST.json`` whose ``pools`` entries give ``pool``,
``file`` (``<pool>.json.gz``), ``sha256`` of the file bytes and ``quote_mint``, and
one ``bot.market.collector.PoolArchive`` per pool.

Rules, all offline:

- The window must verify and be complete (manifest digests, reconciliation).
- A pool is exported only when its creation transaction lies inside the window
  and is its earliest transaction: its history is then complete from creation
  up to ``slot_max``. Pools created earlier are counted, not exported.
- A transaction belongs to a pool when the pool address is one of its account
  keys, static or loaded from a lookup table: the same rule as
  ``getSignaturesForAddress(pool)``. Failed transactions are listed in
  ``signatures``; only successful bodies go to ``transactions``, as the
  collector does.
- ``account`` stays ``None``: the L1 replay never reads the pool account, and no
  account read is invented. ``quote_mint`` comes from the creation instruction.
- Only WSOL-quoted pools enter the L1 MANIFEST (the replay prices in SOL and
  aborts on another quote); the others are counted as ``quote_not_sol:<mint>``.
- Window rule M1 (anti survival bias, spec T-0031 section 6): EVERY complete SOL
  pool is kept, including pools still trading near ``slot_max`` (flagged
  ``active_near_window_end`` for information). The MANIFEST carries
  ``entry_cutoff_slot = slot_max - entry_cutoff_gap_slots`` and ``window_slot_max =
  slot_max``: the L1 replay admits no entry after the cutoff and counts a cycle only
  if it exits by ``window_slot_max``. The gap must be at least ``MIN_CUTOFF_GAP_SLOTS``.
- An optional SOL/USD series file (``bot.market.sol_usd_collect``) is copied next to
  the archives and referenced in the MANIFEST with its file and canonical SHA-256.
- Every body must carry an integer ``transactionIndex`` (the L1 ordering key):
  windows fetched with ``--bodies rpc`` (plain getTransaction) are refused.
"""
import gzip
import hashlib
import json
from pathlib import Path

from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.market.backfill import LAUNCHLAB_PROGRAM, BackfillError, read_segment, verify
from bot.market.collector import ARCHIVE_VERSION
from bot.market.launchlab_events import WSOL_MINT, EventDecodeError, extract_trade_events

SCHEMA_EXPORT = 'rugger-backfill-pool-export-v1'
NEAR_END_SLOTS = 750            # information flag only: last trade within ~5 minutes of slot_max
# Slot duration floor (R02 decision on C1, 2026-11-07), measured on P0 (slots 466226737-466442736,
# 214.5 ms per slot on average) with sliding windows and the bound (dt -/+ 1) / dslots:
# 200 ms is proven for windows >= 60 s (min lower bound 200.68 ms, dense AMM v4 listing), but over
# 30 s the min lower bound is 193.3 ms, so horizons under 60 s use a PRUDENT floor of 190 ms.
# The former 400 ms assumption made the L1 minimum gap far too small (79 slots, about 17 s).
SLOT_MS_FLOOR = 200             # proven for windows >= 60 s
SLOT_MS_FLOOR_SHORT = 190       # prudent floor for horizons < 60 s (R02)
L1_EXIT_HORIZON_MS = 30_000     # L1 replay exit horizon (< 60 s, so the short floor applies)
L1_LATENCY_SLOTS = 2            # L1 entry latency, paid at entry and at exit
MIN_CUTOFF_GAP_SLOTS = -(-L1_EXIT_HORIZON_MS // SLOT_MS_FLOOR_SHORT) + 2 * L1_LATENCY_SLOTS  # = 162
# Default for FUTURE exports: >= MIN_CUTOFF_GAP_SLOTS with 8 slots of margin. The P0 export already
# written (gap 160) is NOT valid for the 30 s L1 horizon under this floor; R02 accepted it only for
# the revised P0 plan (25 s horizon, latency 4: ceil(25 000 / 190) + 8 = 140 <= 160).
DEFAULT_CUTOFF_GAP_SLOTS = 170
_SIG_FIELDS = ('blockTime', 'confirmationStatus', 'err', 'memo', 'signature', 'slot',
               'transactionIndex')


def _keys(tx):
    return [k['pubkey'] for k in normalized_compiled_transaction(tx)['transaction']['message']
            ['accountKeys']]


def account_keys(tx):
    """Static plus lookup-table keys; [] when the body cannot be normalized."""
    try:
        return _keys(tx)
    except (ValueError, KeyError, IndexError, TypeError):
        message = (tx.get('transaction') or {}).get('message') or {}
        keys = [k if isinstance(k, str) else (k or {}).get('pubkey')
                for k in message.get('accountKeys') or []]
        loaded = (tx.get('meta') or {}).get('loadedAddresses') or {}
        return [k for k in keys + list(loaded.get('writable') or [])
                + list(loaded.get('readonly') or []) if isinstance(k, str)]


def creation_quote_mint(tx, pool, base_mint):
    """Quote mint (accounts[7]) of the decoded creation: same pool AND base mint."""
    keys = _keys(tx)
    message = tx['transaction']['message']
    candidates = list(message.get('instructions') or [])
    for group in (tx.get('meta') or {}).get('innerInstructions') or []:
        candidates.extend(group.get('instructions') or [])
    for ix in candidates:
        refs = ix.get('accounts') or []
        if (keys[ix['programIdIndex']] == LAUNCHLAB_PROGRAM and len(refs) >= 8
                and keys[refs[5]] == pool and keys[refs[6]] == base_mint):
            return keys[refs[7]]
    raise BackfillError(f'creation_quote_mint_not_found:{pool}')


def _signature_row(entry):
    row = {'blockTime': entry.get('blockTime'), 'confirmationStatus': 'finalized',
           'err': (entry.get('meta') or {}).get('err'), 'memo': None,
           'signature': entry['signature'], 'slot': entry['slot'],
           'transactionIndex': entry.get('transactionIndex')}
    return {k: row[k] for k in _SIG_FIELDS}


def export_pools(window_dir, out_dir, *, entry_cutoff_gap_slots=DEFAULT_CUTOFF_GAP_SLOTS,
                 sol_usd_series=None, collector_code=None):
    window_dir, out_dir = Path(window_dir), Path(out_dir)
    checked = verify(window_dir)
    manifest = json.loads((window_dir / 'manifest.json').read_text())
    if not checked['ok'] or not manifest['complete']:
        raise BackfillError('window_not_verified_or_incomplete')
    if manifest['window']['address'] != LAUNCHLAB_PROGRAM:
        raise BackfillError('export_needs_a_launchlab_program_window')
    slot_max = manifest['window']['slot_max']
    if type(entry_cutoff_gap_slots) is not int or entry_cutoff_gap_slots < MIN_CUTOFF_GAP_SLOTS:
        raise BackfillError(f'entry_cutoff_gap_slots_below_{MIN_CUTOFF_GAP_SLOTS}')
    entry_cutoff_slot = slot_max - entry_cutoff_gap_slots
    if entry_cutoff_slot <= manifest['window']['slot_min']:
        raise BackfillError('window_shorter_than_entry_cutoff_gap')
    entries = [row for seg in manifest['segments'] if seg['kind'] == 'tx'
               for row in read_segment(window_dir / seg['path'])]
    if any(type(e.get('transactionIndex')) is not int for e in entries):
        raise BackfillError('transaction_index_missing_use_gtfa_bodies')
    entries.sort(key=lambda e: (e['slot'], e['transactionIndex'], e['signature']))

    created, traded = {}, set()                        # pool -> creation entry; pools seen trading
    for entry in entries:
        if (entry.get('meta') or {}).get('err') is not None:
            continue
        try:
            launches = compiled_launchlab_creations(entry)
        except ValueError:
            launches = []
        for launch in launches:
            created.setdefault(launch['pool_state'], (entry, launch['mint']))
        try:
            traded.update(event.pool for event in extract_trade_events(entry))
        except EventDecodeError:
            pass
    # Pools trading in the window but created before it are counted, never dropped silently.
    skipped = {pool: 'creation_not_in_window' for pool in traded - set(created)}

    members = {pool: [] for pool in created}
    for entry in entries:
        for key in set(account_keys(entry)):
            if key in members:
                members[key].append(entry)

    out_dir.mkdir(parents=True, exist_ok=True)
    pools = []
    for pool in sorted(members):
        history = members[pool]
        creation, base_mint = created[pool]
        successful = [e for e in history if (e.get('meta') or {}).get('err') is None]
        # A failed attempt may reference the pool before its creation (same slot):
        # it stays listed; the creation must be the earliest SUCCESSFUL transaction.
        if successful[0]['signature'] != creation['signature']:
            skipped[pool] = 'earliest_transaction_is_not_the_creation'
            continue
        quote_mint = creation_quote_mint(creation, pool, base_mint)
        if quote_mint != WSOL_MINT:
            skipped[pool] = f'quote_not_sol:{quote_mint}'
            continue
        near_end = history[-1]['slot'] > slot_max - NEAR_END_SLOTS     # kept (M1), flagged only
        transactions = {e['signature']: {k: v for k, v in e.items() if k != 'signature'}
                        for e in history if (e.get('meta') or {}).get('err') is None}
        signatures = [_signature_row(e) for e in reversed(history)]       # newest first
        archive = {'version': ARCHIVE_VERSION, 'pool': pool, 'account': None,
                   'signatures': signatures, 'signatures_complete': True,
                   'transactions': transactions}
        data = gzip.compress(json.dumps(archive, separators=(',', ':'), sort_keys=True).encode(),
                             mtime=0)
        name = f'{pool}.json.gz'
        (out_dir / name).write_bytes(data)
        pools.append({'pool': pool, 'file': name, 'sha256': hashlib.sha256(data).hexdigest(),
                      'quote_mint': quote_mint,
                      'signatures': len(signatures), 'transactions': len(transactions),
                      'first_slot': history[0]['slot'], 'last_slot': history[-1]['slot'],
                      'active_near_window_end': near_end})
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
    export = {'schema': SCHEMA_EXPORT, 'version': 2, 'pools': pools,
              'entry_cutoff_slot': entry_cutoff_slot, 'window_slot_max': slot_max,
              'entry_cutoff_gap_slots': entry_cutoff_gap_slots, 'sol_usd_series': series_ref,
              'source': {'window': manifest['window'],
                         'window_manifest_sha256': checked['manifest_sha256'],
                         'endpoint': manifest['endpoint']},
              # W1 protocol R6: the spend of the collection (requests, credits charged before
              # each send, caps and cost table) travels with the MANIFEST it produced.
              'collection_budget': manifest['budget'],
              # W1 protocol R6 (R02): fingerprint of the collection and decoding code, if given.
              'collector_code': collector_code,
              'skipped': dict(sorted(skipped.items())),
              'contents': 'Per-pool archives rebuilt from a verified LaunchLab program-window '
                          'backfill; account is null by design (never an L1 input).'}
    (out_dir / 'MANIFEST.json').write_text(json.dumps(export, indent=2, sort_keys=True) + '\n')
    return export
