"""Causal SOL/USD series from a verified backfill window of ONE SOL/USDC pool.

Output: ``rugger-sol-usd-series-v1`` exactly as specified by RUGGER 01 (T-0031 @ 1c28f76,
``docs/research/SOL_USD_SERIES_SPEC.md``), ``source_kind = sol_usdc_pool_last_trade``:

- one point per successful transaction that holds EXACTLY ONE swap instruction on the
  pool (outer or inner; matched by program id, 8-byte discriminator and the pool
  account at its position, see :class:`SwapFilter`) and in which the pool's WSOL vault
  and USDC vault move in OPPOSITE directions by at least ``min_sol_lamports``. A
  round trip or several hops through the same pool (``multi_swap``) would leave a tiny
  net residue and an absurd price (R02 finding B1 on T-0032); a liquidity deposit or
  withdrawal moves both vaults the same way; both are rejected and counted;
- the price is an EXECUTION price (pool fee and price impact included), not a mid
  price: a small directional bias of the pool fee tier (R02 observation O1);
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

from dataclasses import dataclass

from bot.market.backfill import BackfillError, read_segment, verify
from bot.market.backfill_export import account_keys
from bot.market.launchlab_events import WSOL_MINT, EventDecodeError, b58decode

USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
POINT_SCHEMA = 'rugger-sol-usd-point-v1'
SERIES_SCHEMA = 'rugger-sol-usd-series-v1'
SOURCE_KIND = 'sol_usdc_pool_last_trade'
EXPONENT = -8
LABELS = ('COLLECTED', 'SYNTHETIC_TEST_FIXTURE')
MIN_SOL_LAMPORTS = 100_000_000          # 0.1 SOL: smaller net moves give no point


@dataclass(frozen=True)
class SwapFilter:
    """What counts as ONE swap instruction on the reference pool."""
    program: str
    discriminators: frozenset          # 8-byte prefixes of the swap instruction data
    pool_account_index: int            # position of the pool account in the instruction
    min_sol_lamports: int = MIN_SOL_LAMPORTS


# Raydium CPMM: swap_base_input is pinned from raydium-idl in bot/live/cpmm_swap.py;
# swap_base_output follows the same Anchor rule sha256("global:<name>")[:8]; the pool
# state is account 3 of both (CPMM_SWAP_ROLES). Other pool kinds must pass their own
# filter, verified against their IDL first.
SWAP_FILTERS = {
    'raydium-cpmm': SwapFilter(
        'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C',
        frozenset({bytes((143, 190, 90, 218, 196, 30, 51, 222)),
                   bytes((55, 217, 98, 86, 163, 74, 180, 173))}),
        3),
}
REJECTIONS = ('failed', 'no_vault_balance', 'same_direction', 'no_swap_instruction',
              'multi_swap', 'below_min_size', 'price_rounds_to_zero')


def swap_instruction_count(tx, pool, swap_filter):
    """Outer and inner instructions that are a swap of ``swap_filter`` on ``pool``."""
    keys = account_keys(tx)
    message = (tx.get('transaction') or {}).get('message') or {}
    instructions = list(message.get('instructions') or [])
    for group in (tx.get('meta') or {}).get('innerInstructions') or []:
        instructions.extend(group.get('instructions') or [])
    count = 0
    for ix in instructions:
        program, refs = ix.get('programIdIndex'), ix.get('accounts') or []
        if type(program) is not int or not 0 <= program < len(keys):
            continue
        if keys[program] != swap_filter.program or len(refs) <= swap_filter.pool_account_index:
            continue
        ref = refs[swap_filter.pool_account_index]
        if type(ref) is not int or not 0 <= ref < len(keys) or keys[ref] != pool:
            continue
        try:
            data = b58decode(ix.get('data') or '')
        except EventDecodeError:
            continue
        if data[:8] in swap_filter.discriminators:
            count += 1
    return count


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


def point_from_transaction(entry, *, pool, sol_vault, usdc_vault, swap_filter, rejected=None):
    """The spec point for one raw transaction, or None (reason counted in ``rejected``)."""
    def reject(reason):
        if rejected is not None:
            rejected[reason] = rejected.get(reason, 0) + 1
        return None
    if (entry.get('meta') or {}).get('err') is not None:
        return reject('failed')
    values = []
    for vault, mint, decimals in ((sol_vault, WSOL_MINT, 9), (usdc_vault, USDC_MINT, 6)):
        pre = _vault_balance(entry, 'preTokenBalances', vault, mint, decimals)
        post = _vault_balance(entry, 'postTokenBalances', vault, mint, decimals)
        if pre is None or post is None:
            return reject('no_vault_balance')
        values.append(post - pre)
    d_sol, d_usdc = values
    if d_sol == 0 or d_usdc == 0 or (d_sol > 0) == (d_usdc > 0):
        return reject('same_direction')
    swaps = swap_instruction_count(entry, pool, swap_filter)
    if swaps == 0:
        return reject('no_swap_instruction')
    if swaps > 1:
        return reject('multi_swap')
    if abs(d_sol) < swap_filter.min_sol_lamports:
        return reject('below_min_size')
    price = Fraction(abs(d_usdc), 10 ** 6) / Fraction(abs(d_sol), 10 ** 9)
    mantissa = _half_even(price * Fraction(10) ** -EXPONENT)
    if mantissa < 1:
        return reject('price_rounds_to_zero')
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


def build_series(window_dir, *, pool, sol_vault, usdc_vault, swap_filter, label='COLLECTED',
                 report=None):
    """Series document from a verified, complete window whose address is ``pool``.

    ``report`` (a dict), when given, receives the accepted count and every rejection
    by reason, for the operator's journal.
    """
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
    rejected = {}
    points = [p for p in (point_from_transaction(e, pool=pool, sol_vault=sol_vault,
                                                 usdc_vault=usdc_vault, swap_filter=swap_filter,
                                                 rejected=rejected) for e in entries) if p]
    if report is not None:
        report.update({'candidates': len(entries), 'accepted': len(points),
                       'rejected': dict(sorted(rejected.items())),
                       'min_sol_lamports': swap_filter.min_sol_lamports,
                       'swap_program': swap_filter.program})
    per_slot = {}
    for point in points:
        per_slot[point['slot']] = per_slot.get(point['slot'], 0) + 1
    # A null index has an unknown place inside its slot: keep it only when alone there.
    kept = [p for p in points if p['transaction_index'] is not None or per_slot[p['slot']] == 1]
    if report is not None:
        report['dropped_null_index_shared_slot'] = len(points) - len(kept)
        report['accepted'] = len(kept)
    points = kept
    points.sort(key=lambda p: (p['slot'], p['transaction_index'] or 0))
    if not points:
        raise BackfillError('no_swap_in_window')
    keys = [(p['slot'], p['transaction_index'] or 0) for p in points]
    if any(b <= a for a, b in zip(keys, keys[1:])):
        raise BackfillError('series_positions_not_strictly_increasing')
    return {'schema': SERIES_SCHEMA, 'label': label, 'points': points}


def swap_filter_from_args(kind, *, program=None, discriminators=(), pool_account_index=None,
                          min_sol_lamports=MIN_SOL_LAMPORTS):
    """A preset (``raydium-cpmm``) or an explicit filter; explicit needs all three fields."""
    if kind != 'custom':
        if kind not in SWAP_FILTERS:
            raise BackfillError(f'unknown_pool_kind:{kind}')
        base = SWAP_FILTERS[kind]
        return SwapFilter(base.program, base.discriminators, base.pool_account_index,
                          min_sol_lamports)
    if not program or not discriminators or pool_account_index is None:
        raise BackfillError('custom_filter_needs_program_discriminators_and_pool_index')
    parsed = frozenset(bytes.fromhex(d) for d in discriminators)
    if any(len(d) != 8 for d in parsed):
        raise BackfillError('discriminator_must_be_8_bytes_hex')
    return SwapFilter(program, parsed, pool_account_index, min_sol_lamports)


def describe_filter(swap_filter):
    return {'program': swap_filter.program,
            'discriminators': sorted(d.hex() for d in swap_filter.discriminators),
            'pool_account_index': swap_filter.pool_account_index,
            'min_sol_lamports': swap_filter.min_sol_lamports}


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
