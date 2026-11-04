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
- Pools still trading close to ``slot_max`` are flagged ``active_near_window_end``:
  their history is truncated by the window, not by the chain.
"""
import gzip
import hashlib
import json
from pathlib import Path

from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.market.backfill import LAUNCHLAB_PROGRAM, BackfillError, read_segment, verify
from bot.market.collector import ARCHIVE_VERSION
from bot.market.launchlab_events import EventDecodeError, extract_trade_events

SCHEMA_EXPORT = 'rugger-backfill-pool-export-v1'
NEAR_END_SLOTS = 750            # about 5 minutes at 400 ms per slot (the L1 position horizon)
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


def creation_quote_mint(tx, pool):
    """Quote mint of ``pool`` in its LaunchLab initialize instruction (accounts[7])."""
    keys = _keys(tx)
    message = tx['transaction']['message']
    candidates = list(message.get('instructions') or [])
    for group in (tx.get('meta') or {}).get('innerInstructions') or []:
        candidates.extend(group.get('instructions') or [])
    for ix in candidates:
        refs = ix.get('accounts') or []
        if (keys[ix['programIdIndex']] == LAUNCHLAB_PROGRAM and len(refs) >= 8
                and keys[refs[5]] == pool):
            return keys[refs[7]]
    raise BackfillError(f'creation_quote_mint_not_found:{pool}')


def _signature_row(entry):
    row = {'blockTime': entry.get('blockTime'), 'confirmationStatus': 'finalized',
           'err': (entry.get('meta') or {}).get('err'), 'memo': None,
           'signature': entry['signature'], 'slot': entry['slot'],
           'transactionIndex': entry.get('transactionIndex')}
    return {k: row[k] for k in _SIG_FIELDS}


def export_pools(window_dir, out_dir):
    window_dir, out_dir = Path(window_dir), Path(out_dir)
    checked = verify(window_dir)
    manifest = json.loads((window_dir / 'manifest.json').read_text())
    if not checked['ok'] or not manifest['complete']:
        raise BackfillError('window_not_verified_or_incomplete')
    if manifest['window']['address'] != LAUNCHLAB_PROGRAM:
        raise BackfillError('export_needs_a_launchlab_program_window')
    slot_max = manifest['window']['slot_max']
    entries = [row for seg in manifest['segments'] if seg['kind'] == 'tx'
               for row in read_segment(window_dir / seg['path'])]
    entries.sort(key=lambda e: (e['slot'], e.get('transactionIndex') or 0, e['signature']))

    created, traded = {}, set()                        # pool -> creation entry; pools seen trading
    for entry in entries:
        if (entry.get('meta') or {}).get('err') is not None:
            continue
        try:
            launches = compiled_launchlab_creations(entry)
        except ValueError:
            launches = []
        for launch in launches:
            created.setdefault(launch['pool_state'], entry)
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
        if history[0]['signature'] != created[pool]['signature']:
            skipped[pool] = 'earliest_transaction_is_not_the_creation'
            continue
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
                      'quote_mint': creation_quote_mint(created[pool], pool),
                      'signatures': len(signatures), 'transactions': len(transactions),
                      'first_slot': history[0]['slot'], 'last_slot': history[-1]['slot'],
                      'active_near_window_end': history[-1]['slot'] > slot_max - NEAR_END_SLOTS})
    export = {'schema': SCHEMA_EXPORT, 'version': 1, 'pools': pools,
              'source': {'window': manifest['window'],
                         'window_manifest_sha256': checked['manifest_sha256'],
                         'endpoint': manifest['endpoint']},
              'skipped': dict(sorted(skipped.items())),
              'contents': 'Per-pool archives rebuilt from a verified LaunchLab program-window '
                          'backfill; account is null by design (never an L1 input).'}
    (out_dir / 'MANIFEST.json').write_text(json.dumps(export, indent=2, sort_keys=True) + '\n')
    return export
