"""Decode Raydium LaunchLab ``TradeEvent`` records from signed transactions.

Source of truth: the Anchor ``emit_cpi!`` self-invocation recorded in the
transaction's inner instructions (``EVENT_IX_TAG || discriminator || payload``).
Unlike ``Program data:`` log lines, inner instructions are never truncated, and
the program's event-authority signer check means a successful transaction
cannot contain a forged self-CPI. Failed transactions are ignored.

Every decoded event is checked against the exact curve arithmetic of
:mod:`bot.market.launchlab_curve`; events whose reserves or amounts are not
reproduced exactly are returned with explicit ``violations`` instead of
being silently trusted.

Input is a ``getTransaction`` result decoded with ``encoding='json'`` or
``'jsonParsed'``.
No network access happens here.
"""
from dataclasses import dataclass, field
import hashlib
import struct

from bot.market.launchlab_curve import (
    CurveError, CurveState, FEE_DENOMINATOR, buy_exact_in, sell_exact_in,
)

LAUNCHLAB_PROGRAM = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
EVENT_IX_TAG = bytes.fromhex('e445a52e51cb9a1d')  # sha256("anchor:event")[:8]
TRADE_EVENT_DISCRIMINATOR = hashlib.sha256(b'event:TradeEvent').digest()[:8]
TRADE_EVENT_SIZE = 8 + 32 + 13 * 8 + 3
_U64_FIELDS = (
    'total_base_sell', 'virtual_base', 'virtual_quote',
    'real_base_before', 'real_quote_before', 'real_base_after', 'real_quote_after',
    'amount_in', 'amount_out', 'protocol_fee', 'platform_fee', 'creator_fee', 'share_fee',
)
BUY, SELL = 'buy', 'sell'
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_B58_INDEX = {c: i for i, c in enumerate(_B58)}


class EventDecodeError(ValueError):
    pass


def b58encode(raw):
    n = int.from_bytes(raw, 'big')
    out = ''
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + out


def b58decode(text):
    n = 0
    for char in text:
        try:
            n = n * 58 + _B58_INDEX[char]
        except KeyError:
            raise EventDecodeError('invalid_base58') from None
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big') if n else b''
    return b'\0' * (len(text) - len(text.lstrip('1'))) + raw


@dataclass(frozen=True)
class TradeEvent:
    signature: str
    slot: int
    block_time: object          # int seconds, or None when the node has no time
    event_index: int            # order of this event inside its transaction
    fee_payer: str
    pool: str
    side: str                   # BUY or SELL
    exact_in: bool
    pool_status: int
    total_base_sell: int
    virtual_base: int
    virtual_quote: int
    real_base_before: int
    real_quote_before: int
    real_base_after: int
    real_quote_after: int
    amount_in: int
    amount_out: int
    protocol_fee: int
    platform_fee: int
    creator_fee: int
    share_fee: int
    violations: tuple = field(default=())

    @property
    def key(self):
        return self.signature, self.event_index

    @property
    def total_fee(self):
        return self.protocol_fee + self.platform_fee + self.creator_fee + self.share_fee

    @property
    def quote_volume(self):
        """Quote paid (buy) or received before fees (sell), atomic units."""
        return self.amount_in if self.side == BUY else self.amount_out + self.total_fee

    def state_before(self):
        return CurveState(self.virtual_base, self.virtual_quote, self.real_base_before,
                          self.real_quote_before, self.total_base_sell)

    def state_after(self):
        return CurveState(self.virtual_base, self.virtual_quote, self.real_base_after,
                          self.real_quote_after, self.total_base_sell)


def decode_trade_payload(payload):
    """Decode the bytes following ``EVENT_IX_TAG`` (discriminator included)."""
    if len(payload) != TRADE_EVENT_SIZE or payload[:8] != TRADE_EVENT_DISCRIMINATOR:
        raise EventDecodeError('not_a_trade_event')
    values = dict(zip(_U64_FIELDS, struct.unpack_from('<13Q', payload, 40)))
    direction, status, exact_in = payload[144], payload[145], payload[146]
    if direction not in (0, 1) or exact_in not in (0, 1):
        raise EventDecodeError('invalid_trade_event_enum')
    values.update(pool=b58encode(payload[8:40]), side=BUY if direction == 0 else SELL,
                  exact_in=bool(exact_in), pool_status=status)
    return values


def check_trade(values):
    """Return the tuple of exact-arithmetic violations for a decoded event."""
    issues = []
    fees = (values['protocol_fee'] + values['platform_fee']
            + values['creator_fee'] + values['share_fee'])
    vb, vq = values['virtual_base'], values['virtual_quote']
    rb0, rq0 = values['real_base_before'], values['real_quote_before']
    rb1, rq1 = values['real_base_after'], values['real_quote_after']
    a_in, a_out = values['amount_in'], values['amount_out']
    if values['side'] == BUY:
        if rb1 - rb0 != a_out:
            issues.append('buy_base_delta_mismatch')
        if rq1 - rq0 != a_in - fees:
            issues.append('buy_quote_delta_mismatch')
        basis = a_in
    else:
        if rb0 - rb1 != a_in:
            issues.append('sell_base_delta_mismatch')
        if rq0 - rq1 != a_out + fees:
            issues.append('sell_quote_delta_mismatch')
        basis = a_out + fees
    x0, y0, x1, y1 = vb - rb0, vq + rq0, vb - rb1, vq + rq1
    if min(x0, y0, x1, y1) <= 0:
        issues.append('non_positive_reserve')
    elif x1 * y1 < x0 * y0:
        issues.append('constant_product_decreased')
    if values['exact_in'] and not issues and basis > 0:
        rate = implied_fee_rate_ppm(values)
        state = CurveState(vb, vq, rb0, rq0, values['total_base_sell'])
        try:
            fill = (buy_exact_in(state, a_in, rate) if values['side'] == BUY
                    else sell_exact_in(state, a_in, rate))
            if fill.amount_out != a_out or fill.fee != fees:
                issues.append('curve_output_not_reproduced')
        except CurveError as exc:
            issues.append(f'curve_refused:{exc}')
    return tuple(issues)


def implied_fee_rate_ppm(values):
    """Smallest total ppm rate whose ceil-fee on the basis equals the event fee.

    The on-chain rate is the sum of configured rates; the event only reveals the
    rounded fee, so several rates may be compatible. The smallest one is
    returned; exactness of the whole trade is then re-checked by ``check_trade``.
    """
    fees = (values['protocol_fee'] + values['platform_fee']
            + values['creator_fee'] + values['share_fee'])
    if values['side'] == BUY:
        basis = values['amount_in']
    else:
        basis = values['amount_out'] + fees
    if basis <= 0 or fees == 0:
        return 0
    # ceil(basis*r/D) == fees  <=>  (fees-1)*D < basis*r <= fees*D
    rate = ((fees - 1) * FEE_DENOMINATOR) // basis + 1
    return min(rate, FEE_DENOMINATOR - 1)


def _account_keys(result):
    message = result['transaction']['message']
    keys = [k if isinstance(k, str) else k['pubkey'] for k in message['accountKeys']]
    loaded = (result.get('meta') or {}).get('loadedAddresses') or {}
    return keys + list(loaded.get('writable') or []) + list(loaded.get('readonly') or [])


def extract_trade_events(tx):
    """Return every LaunchLab ``TradeEvent`` of one successful transaction.

    ``tx`` may be the raw JSON-RPC envelope or its ``result``. Returns an empty
    list for failed transactions or transactions without LaunchLab events.
    """
    result = tx.get('result', tx) if isinstance(tx, dict) else None
    if not isinstance(result, dict) or 'transaction' not in result:
        raise EventDecodeError('not_a_transaction_result')
    meta = result.get('meta')
    if not isinstance(meta, dict):
        raise EventDecodeError('missing_transaction_meta')
    if meta.get('err') is not None:
        return []
    inner = meta.get('innerInstructions')
    if inner is None:
        raise EventDecodeError('inner_instructions_unavailable')
    keys = _account_keys(result)
    signature = result['transaction']['signatures'][0]
    slot = result['slot']
    block_time = result.get('blockTime')
    events = []
    for group in sorted(inner, key=lambda g: g['index']):
        for ix in group['instructions']:
            index = ix.get('programIdIndex')   # encoding='json'
            program = ix.get('programId')      # encoding='jsonParsed'
            if program is None and isinstance(index, int) and 0 <= index < len(keys):
                program = keys[index]
            if program != LAUNCHLAB_PROGRAM:
                continue
            data = b58decode(ix.get('data', ''))
            if not data.startswith(EVENT_IX_TAG + TRADE_EVENT_DISCRIMINATOR):
                continue
            values = decode_trade_payload(data[len(EVENT_IX_TAG):])
            events.append(TradeEvent(
                signature=signature, slot=slot, block_time=block_time,
                event_index=len(events), fee_payer=keys[0],
                violations=check_trade(values), **values))
    return events
