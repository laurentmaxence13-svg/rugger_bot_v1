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

from dataclasses import dataclass, replace

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
    discriminators: frozenset          # prefixes of the swap instruction data (8-byte
                                       # Anchor discriminators, or a 1-byte tag)
    pool_account_index: int            # position of the pool account in the instruction
    min_sol_lamports: int = MIN_SOL_LAMPORTS
    # Per-discriminator positions, when the swap variants differ (Orca Whirlpool): sorted
    # ``(discriminator, frozenset_of_positions)`` pairs. A discriminator listed here uses
    # its own positions instead of ``pool_account_index``; a two-hop variant lists both
    # hop positions, and the pool at both positions counts as two swaps (multi_swap).
    pool_positions: tuple = ()
    # Where the swap instruction lists the pool's two vaults (R02 C-b on 43cc1d1, closes O7):
    # sorted ``(discriminator, frozenset_of_rules)`` pairs; a rule is ``(pool_position,
    # vault_i, vault_j, account_count_or_None)``. The accepted swap must name exactly the
    # given SOL and USDC vaults (either order: CPMM orders them by direction) at the
    # positions of the rule matching its pool position. Empty = not checked (custom).
    vault_positions: tuple = ()

    def positions_for(self, prefix):
        return dict(self.pool_positions).get(prefix, frozenset({self.pool_account_index}))


# Raydium CPMM: swap_base_input is pinned from raydium-idl in bot/live/cpmm_swap.py;
# swap_base_output follows the same Anchor rule sha256("global:<name>")[:8]; the pool
# state is account 3 of both (CPMM_SWAP_ROLES). Other pool kinds must pass their own
# filter, verified against their IDL first.
WHIRLPOOL_SWAP = bytes((248, 198, 158, 145, 225, 117, 135, 200))
WHIRLPOOL_SWAP_V2 = bytes((43, 4, 237, 11, 26, 201, 30, 98))
WHIRLPOOL_TWO_HOP_SWAP = bytes((195, 96, 237, 108, 68, 162, 219, 230))
WHIRLPOOL_TWO_HOP_SWAP_V2 = bytes((186, 143, 209, 29, 254, 2, 194, 117))

SWAP_FILTERS = {
    'raydium-cpmm': SwapFilter(
        'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C',
        frozenset({bytes((143, 190, 90, 218, 196, 30, 51, 222)),
                   bytes((55, 217, 98, 86, 163, 74, 180, 173))}),
        3,
        # CPMM_SWAP_ROLES (bot/live/cpmm_swap.py): input_vault 6, output_vault 7.
        vault_positions=tuple(sorted(
            (d, frozenset({(3, 6, 7, None)}))
            for d in (bytes((143, 190, 90, 218, 196, 30, 51, 222)),
                      bytes((55, 217, 98, 86, 163, 74, 180, 173)))))),
    # Raydium AMM v4 (not Anchor): the instruction data starts with a 1-byte tag. Pinned from
    # the official source github.com/raydium-io/raydium-amm @ 91739d8d9f5cf347e0ce14ebe4d2bb7069fb31b6,
    # program/src/instruction.rs (sha256 499a331b01a1142975dece9ca7258a937ae0598422c33ec516c2f3e4883e0818):
    # AmmInstruction::unpack maps tag 9 to
    # SwapBaseIn, 11 to SwapBaseOut, 16 to SwapBaseInV2, 17 to SwapBaseOutV2, each followed
    # by two u64 (17 bytes). In all four account lists the AMM account is account 1.
    # Program id from program/src/lib.rs (mainnet declare_id). Every other AMM v4
    # instruction touching the pool (deposit 3, withdraw 4...) counts as another pool
    # instruction and rejects the point.
    'raydium-amm-v4': SwapFilter(
        '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',
        frozenset({bytes((9,)), bytes((11,)), bytes((16,)), bytes((17,))}),
        1,
        # instruction.rs (same pin): SwapBaseIn/SwapBaseOut list "(optional) AMM target
        # orders" at 4, so the coin/pc vaults are 4/5 with 17 accounts and 5/6 with 18;
        # SwapBaseInV2/SwapBaseOutV2: coin/pc vaults 3/4.
        vault_positions=(
            (bytes((9,)), frozenset({(1, 4, 5, 17), (1, 5, 6, 18)})),
            (bytes((11,)), frozenset({(1, 4, 5, 17), (1, 5, 6, 18)})),
            (bytes((16,)), frozenset({(1, 3, 4, None)})),
            (bytes((17,)), frozenset({(1, 3, 4, None)})))),
    # Orca Whirlpool (Anchor). Pinned from the official source github.com/orca-so/whirlpools
    # @ cc683ec92acb5e7606caa3d8e514d9383e9c7c11 (docs/research/WHIRLPOOL_PRESET.md):
    # programs/whirlpool/src/lib.rs (declare_id, fn swap / two_hop_swap / swap_v2 /
    # two_hop_swap_v2, no custom discriminator), discriminators = sha256("global:<fn>")[:8],
    # identical to ts-sdk/client/src/generated/instructions/{swap,twoHopSwap,swapV2,
    # twoHopSwapV2}.ts. Pool positions from the #[derive(Accounts)] structs:
    # Swap.whirlpool = 2; SwapV2.whirlpool = 4; TwoHopSwap.whirlpool_one/two = 2/3;
    # TwoHopSwapV2.whirlpool_one/two = 0/1. Liquidity, fee and reward instructions (Anchor or
    # the pinocchio fast path) touching the pool count as other pool instructions.
    'orca-whirlpool': SwapFilter(
        'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc',
        frozenset({WHIRLPOOL_SWAP, WHIRLPOOL_SWAP_V2, WHIRLPOOL_TWO_HOP_SWAP,
                   WHIRLPOOL_TWO_HOP_SWAP_V2}),
        2,
        pool_positions=tuple(sorted({
            WHIRLPOOL_SWAP: frozenset({2}),
            WHIRLPOOL_SWAP_V2: frozenset({4}),
            WHIRLPOOL_TWO_HOP_SWAP: frozenset({2, 3}),
            WHIRLPOOL_TWO_HOP_SWAP_V2: frozenset({0, 1}),
        }.items())),
        # Same Accounts structs: Swap vaults a/b 4/6; SwapV2 8/10; TwoHopSwap 5/7 (hop one,
        # pool at 2) or 9/11 (hop two, pool at 3); TwoHopSwapV2 9/10 (one, pool at 0) or
        # 11/12 (two, pool at 1).
        vault_positions=tuple(sorted({
            WHIRLPOOL_SWAP: frozenset({(2, 4, 6, None)}),
            WHIRLPOOL_SWAP_V2: frozenset({(4, 8, 10, None)}),
            WHIRLPOOL_TWO_HOP_SWAP: frozenset({(2, 5, 7, None), (3, 9, 11, None)}),
            WHIRLPOOL_TWO_HOP_SWAP_V2: frozenset({(0, 9, 10, None), (1, 11, 12, None)}),
        }.items()))),
}
AMM_V4_SWAP_DATA_LEN = 17
REJECTIONS = ('failed', 'no_vault_balance', 'same_direction', 'no_swap_instruction',
              'multi_swap', 'other_pool_instruction', 'vault_position_mismatch',
              'below_min_size', 'price_rounds_to_zero')


def _swap_prefix(data, swap_filter):
    """The matching swap discriminator of ``data``, or None (same rule as _is_swap_data)."""
    for prefix in sorted(swap_filter.discriminators):
        if data.startswith(prefix):
            return prefix if len(prefix) == 8 or len(data) == AMM_V4_SWAP_DATA_LEN else None
    return None


def _is_swap_data(data, swap_filter):
    """Prefix match. A 1-byte tag (AMM v4 layout) also requires the exact 17-byte swap data, so
    a longer or shorter instruction that merely starts with the tag is not taken as a swap.
    Any 1-byte prefix, preset or custom, implies that 17-byte layout (R02 O2 on 92e6303).
    Prefixes are tried in sorted order, so the result never depends on set iteration order
    (R02 O1); swap_filter_from_args also refuses overlapping prefixes."""
    return _swap_prefix(data, swap_filter) is not None


def _pool_swap_hits(tx, pool, swap_filter):
    """([(prefix, pool_position, account_keys)...], others) for the pool program's
    instructions that touch ``pool`` (see :func:`pool_instruction_counts`)."""
    keys = account_keys(tx)
    message = (tx.get('transaction') or {}).get('message') or {}
    instructions = list(message.get('instructions') or [])
    for group in (tx.get('meta') or {}).get('innerInstructions') or []:
        instructions.extend(group.get('instructions') or [])
    hits, others = [], 0
    for ix in instructions:
        program, refs = ix.get('programIdIndex'), ix.get('accounts') or []
        if type(program) is not int or not 0 <= program < len(keys):
            continue
        if keys[program] != swap_filter.program:
            continue
        touched = [i for i, ref in enumerate(refs)
                   if type(ref) is int and 0 <= ref < len(keys) and keys[ref] == pool]
        if not touched:
            continue
        try:
            data = b58decode(ix.get('data') or '')
        except EventDecodeError:
            data = b''
        prefix = _swap_prefix(data, swap_filter)
        positions = sorted(swap_filter.positions_for(prefix) & set(touched)) if prefix else []
        if positions:
            named = [keys[ref] if type(ref) is int and 0 <= ref < len(keys) else None
                     for ref in refs]
            # a two-hop through this pool twice counts as two
            hits.extend((prefix, position, named) for position in positions)
        else:
            others += 1
    return hits, others


def pool_instruction_counts(tx, pool, swap_filter):
    """(swaps, others): instructions of the pool program that touch ``pool``.

    ``swaps`` = matching swap instructions (discriminator + pool at its position);
    ``others`` = every other instruction of that program referencing the pool at any
    position (a deposit, a withdrawal...). A deposit or withdrawal in the same
    transaction moves the vaults too, so the net deltas are no longer a swap price
    (R02 observation on T-0032 and T-0033). Instructions of other programs (an
    aggregator calling the pool by CPI) are not counted.
    """
    hits, others = _pool_swap_hits(tx, pool, swap_filter)
    return len(hits), others


def swap_vaults_conform(tx, pool, sol_vault, usdc_vault, swap_filter):
    """True when every swap instruction on ``pool`` names exactly the SOL and USDC vaults at
    the positions its variant defines (R02 C-b on 43cc1d1). A filter without
    ``vault_positions`` (custom) is not checked; a preset discriminator without a rule fails."""
    if not swap_filter.vault_positions:
        return True
    rules = dict(swap_filter.vault_positions)
    hits, _ = _pool_swap_hits(tx, pool, swap_filter)
    for prefix, position, named in hits:
        if not any(rule_pool == position and (count is None or count == len(named))
                   and max(i, j) < len(named) and {named[i], named[j]} == {sol_vault, usdc_vault}
                   for rule_pool, i, j, count in rules.get(prefix, ())):
            return False
    return True


def swap_instruction_count(tx, pool, swap_filter):
    """Matching swap instructions on ``pool`` (see :func:`pool_instruction_counts`)."""
    return pool_instruction_counts(tx, pool, swap_filter)[0]


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
    swaps, others = pool_instruction_counts(entry, pool, swap_filter)
    if swaps == 0:
        return reject('no_swap_instruction')
    if swaps > 1:
        return reject('multi_swap')
    if others:
        return reject('other_pool_instruction')
    if not swap_vaults_conform(entry, pool, sol_vault, usdc_vault, swap_filter):
        return reject('vault_position_mismatch')
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
    """A preset (``raydium-cpmm``, ``raydium-amm-v4``, ``orca-whirlpool``) or an explicit
    filter (all three fields)."""
    if kind != 'custom':
        if kind not in SWAP_FILTERS:
            raise BackfillError(f'unknown_pool_kind:{kind}')
        return replace(SWAP_FILTERS[kind], min_sol_lamports=min_sol_lamports)
    if not program or not discriminators or pool_account_index is None:
        raise BackfillError('custom_filter_needs_program_discriminators_and_pool_index')
    parsed = frozenset(bytes.fromhex(d) for d in discriminators)
    if any(len(d) not in (1, 8) for d in parsed):
        raise BackfillError('discriminator_must_be_1_or_8_bytes_hex')
    if len({len(d) for d in parsed}) > 1:
        raise BackfillError('discriminators_must_share_one_length')
    return SwapFilter(program, parsed, pool_account_index, min_sol_lamports)


def describe_filter(swap_filter):
    return {'program': swap_filter.program,
            'discriminators': sorted(d.hex() for d in swap_filter.discriminators),
            'pool_account_index': swap_filter.pool_account_index,
            'min_sol_lamports': swap_filter.min_sol_lamports,
            **({'pool_positions': {d.hex(): sorted(p) for d, p in swap_filter.pool_positions}}
               if swap_filter.pool_positions else {}),
            **({'vault_positions': {d.hex(): sorted([list(r) for r in rules],
                                                    key=lambda r: [x if x is not None else -1
                                                                   for x in r])
                                    for d, rules in swap_filter.vault_positions}}
               if swap_filter.vault_positions else {})}


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
