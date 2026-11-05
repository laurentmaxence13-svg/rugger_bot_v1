"""Causal SOL/USD series from a verified backfill window of ONE SOL/USDC pool.

Output: ``rugger-sol-usd-series-v1`` exactly as specified by RUGGER 01 (T-0031 @ 1c28f76,
``docs/research/SOL_USD_SERIES_SPEC.md``), ``source_kind = sol_usdc_pool_last_trade``:

- one point per successful transaction in which the pool's WSOL vault and USDC vault
  move in OPPOSITE directions (a swap); a liquidity deposit or withdrawal moves both
  the same way and gives no price;
- price in USD per SOL = |delta USDC| / |delta SOL| from the vaults' raw token
  balances (pre/postTokenBalances), computed with exact fractions and rounded half-even
  to a mantissa at ``exponent = -8``; never interpolated or averaged;
- ``slot``, ``transaction_index`` and ``block_time`` come from the signed transaction.
  ``transaction_index`` is the real position when the provider gives it; otherwise it
  is ``null``, which the spec allows (usable only from a strictly earlier slot). A
  ``null`` point sharing its slot with another point is dropped: its order inside the
  slot is unknown and the series must stay strictly sorted; ``signature`` is its signature; ``evidence_sha256`` is the
  SHA-256 of that raw transaction (canonical JSON, sorted keys, no spaces);
- points are strictly sorted by ``(slot, transaction_index)``.

Why not ``pyth_onchain_account`` for a backfill: the spec's evidence is the raw price
ACCOUNT at each update, and JSON-RPC has no historical account state. That source is
only collectable prospectively (account subscription).

The vault addresses are inputs (read once from the pool account by the operator);
nothing here touches the network.
"""
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path

from bot.market.backfill import BackfillError, read_segment, verify
from bot.market.backfill_export import account_keys
from bot.market.launchlab_events import WSOL_MINT

USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
POINT_SCHEMA = 'rugger-sol-usd-point-v1'
SERIES_SCHEMA = 'rugger-sol-usd-series-v1'
SOURCE_KIND = 'sol_usdc_pool_last_trade'
EXPONENT = -8
LABELS = ('COLLECTED', 'SYNTHETIC_TEST_FIXTURE')


def canonical_sha256(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _vault_balance(tx, field, vault, mint, decimals):
    keys = account_keys(tx)
    for item in (tx.get('meta') or {}).get(field) or []:
        index = item.get('accountIndex')
        if type(index) is int and 0 <= index < len(keys) and keys[index] == vault:
            amount = item.get('uiTokenAmount') or {}
            if item.get('mint') != mint or amount.get('decimals') != decimals:
                raise BackfillError(f'vault_mint_or_decimals_mismatch:{vault}')
            return int(amount['amount'])
    return None


def _half_even(value):
    floor = value.numerator // value.denominator
    rest = value - floor
    if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and floor % 2):
        return floor + 1
    return floor


def point_from_transaction(entry, *, pool, sol_vault, usdc_vault):
    """The spec point for one raw transaction, or None when it is not a swap."""
    if (entry.get('meta') or {}).get('err') is not None:
        return None
    values = []
    for vault, mint, decimals in ((sol_vault, WSOL_MINT, 9), (usdc_vault, USDC_MINT, 6)):
        pre = _vault_balance(entry, 'preTokenBalances', vault, mint, decimals)
        post = _vault_balance(entry, 'postTokenBalances', vault, mint, decimals)
        if pre is None or post is None:
            return None
        values.append(post - pre)
    d_sol, d_usdc = values
    if d_sol == 0 or d_usdc == 0 or (d_sol > 0) == (d_usdc > 0):
        return None
    price = Fraction(abs(d_usdc), 10 ** 6) / Fraction(abs(d_sol), 10 ** 9)
    mantissa = _half_even(price * Fraction(10) ** -EXPONENT)
    if mantissa < 1:
        return None
    if type(entry.get('slot')) is not int:
        raise BackfillError('sol_usd_point_needs_a_slot')
    index = entry.get('transactionIndex')
    raw = {k: v for k, v in entry.items() if k != 'signature'}
    return {'schema': POINT_SCHEMA, 'slot': entry['slot'],
            'transaction_index': index if type(index) is int else None,
            'block_time': entry.get('blockTime'),
            'received_at_ms': None, 'publish_time': None, 'price': mantissa, 'exponent': EXPONENT,
            'confidence': None, 'source_kind': SOURCE_KIND, 'source_ref': pool,
            'evidence_sha256': canonical_sha256(raw), 'signature': entry['signature']}


def build_series(window_dir, *, pool, sol_vault, usdc_vault, label='COLLECTED'):
    """Series document from a verified, complete window whose address is ``pool``."""
    if label not in LABELS:
        raise BackfillError('series_label_must_be_COLLECTED_or_SYNTHETIC_TEST_FIXTURE')
    window_dir = Path(window_dir)
    checked = verify(window_dir)
    manifest = json.loads((window_dir / 'manifest.json').read_text())
    if not checked['ok'] or not manifest['complete']:
        raise BackfillError('window_not_verified_or_incomplete')
    if manifest['window']['address'] != pool:
        raise BackfillError('window_address_is_not_the_pool')
    entries = [row for seg in manifest['segments'] if seg['kind'] == 'tx'
               for row in read_segment(window_dir / seg['path'])]
    points = [p for p in (point_from_transaction(e, pool=pool, sol_vault=sol_vault,
                                                 usdc_vault=usdc_vault) for e in entries) if p]
    per_slot = {}
    for point in points:
        per_slot[point['slot']] = per_slot.get(point['slot'], 0) + 1
    # A null index has an unknown place inside its slot: keep it only when alone there.
    points = [p for p in points if p['transaction_index'] is not None or per_slot[p['slot']] == 1]
    points.sort(key=lambda p: (p['slot'], p['transaction_index'] or 0))
    if not points:
        raise BackfillError('no_swap_in_window')
    keys = [(p['slot'], p['transaction_index'] or 0) for p in points]
    if any(b <= a for a, b in zip(keys, keys[1:])):
        raise BackfillError('series_positions_not_strictly_increasing')
    return {'schema': SERIES_SCHEMA, 'label': label, 'points': points}


def write_series(document, path):
    """Write the series (``.json`` or ``.json.gz``); return the file and canonical digests."""
    path = Path(path)
    data = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if path.suffix == '.gz':
        data = gzip.compress(data, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {'file_sha256': hashlib.sha256(data).hexdigest(),
            'canonical_sha256': canonical_sha256(document), 'points': len(document['points'])}


def density(document):
    """Largest gap, in seconds of block time, between consecutive points (spec: <= 4 s)."""
    times = [p['block_time'] for p in document['points'] if p['block_time'] is not None]
    gaps = [b - a for a, b in zip(times, times[1:])]
    return {'points': len(document['points']), 'max_gap_s': max(gaps) if gaps else None,
            'first_block_time': times[0] if times else None,
            'last_block_time': times[-1] if times else None}
