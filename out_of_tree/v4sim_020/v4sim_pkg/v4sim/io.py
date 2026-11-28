"""Inputs of v4sim: timeline packs (plain files, hashed) and actor identities (protocol V4 v2, C-5, C-6)."""
import hashlib
import json
from pathlib import Path

from bot.market.launchlab_events import WSOL_MINT, TradeEvent
from bot.market.pool_timeline import PoolTimeline

EVENT_FIELDS = ('signature', 'slot', 'block_time', 'event_index', 'fee_payer', 'pool', 'side', 'exact_in',
                'pool_status', 'total_base_sell', 'virtual_base', 'virtual_quote', 'real_base_before',
                'real_quote_before', 'real_base_after', 'real_quote_after', 'amount_in', 'amount_out',
                'protocol_fee', 'platform_fee', 'creator_fee', 'share_fee')


def load_timeline_pack(directory):
    """Read a synthetic timeline pack: MANIFEST.json + one JSON file of events per pool, sha256 checked.

    Return (manifest_sha256, [(entry, PoolTimeline)]). The pack is generated apart and read as files."""
    directory = Path(directory)
    raw = (directory / 'MANIFEST.json').read_bytes()
    manifest = json.loads(raw)
    if manifest.get('schema') != 'v4-synthetic-timeline-pack-v1':
        raise ValueError('not_a_synthetic_timeline_pack')
    pools = []
    for entry in sorted(manifest['pools'], key=lambda item: item['pool']):
        data = (directory / entry['file']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('timeline_file_sha256_mismatch:' + entry['file'])
        events = tuple(TradeEvent(**{name: row[name] for name in EVENT_FIELDS}) for row in json.loads(data)['events'])
        pools.append((entry, PoolTimeline(entry['pool'], events, ())))
    return hashlib.sha256(raw).hexdigest(), pools


def actors_from_archive(archive, events):
    """C-5: actor of each event = owner of the user's token account, from the transaction's token balances.

    The user's account is the non-quote token account whose balance moved by exactly the traded amount
    (+amount_out for a buy, -amount_in for a sell). Unavailable or ambiguous: the fee payer is kept.
    Return ({event key: actor}, stats)."""
    actors, stats = {}, dict(events=0, owner_found=0, owner_differs_from_fee_payer=0, owner_unavailable=0)
    for event in events:
        stats['events'] += 1
        meta = (archive.transactions.get(event.signature) or {}).get('meta') or {}
        before = {(b['accountIndex'], b['mint']): b for b in meta.get('preTokenBalances') or ()}
        after = {(b['accountIndex'], b['mint']): b for b in meta.get('postTokenBalances') or ()}
        wanted = event.amount_out if event.side == 'buy' else -event.amount_in
        owners = set()
        for key in set(before) | set(after):
            if key[1] == WSOL_MINT:
                continue
            row = after.get(key) or before.get(key)
            delta = (int((after.get(key) or {}).get('uiTokenAmount', {}).get('amount', 0))
                     - int((before.get(key) or {}).get('uiTokenAmount', {}).get('amount', 0)))
            if delta == wanted and row.get('owner'):
                owners.add(row['owner'])
        if len(owners) == 1:
            owner = owners.pop()
            actors[event.key] = owner
            stats['owner_found'] += 1
            stats['owner_differs_from_fee_payer'] += owner != event.fee_payer
        else:
            stats['owner_unavailable'] += 1
    return actors, stats
