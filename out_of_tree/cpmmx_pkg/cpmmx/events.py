"""Decode cp-swap ``SwapEvent`` and ``LpChangeEvent`` from the log messages of a raw transaction.

cp-swap emits its events with Anchor ``emit!`` (``sol_log_data``): one ``Program data: <base64>``
log line, 8-byte discriminator ``sha256("event:<Name>")[:8]`` followed by the Borsh fields in the
order of states/events.rs. Only a line logged WHILE THE CPMM PROGRAM IS THE RUNNING FRAME is
accepted (the invoke / success lines are tracked as a stack), so another program printing the
same bytes cannot forge a swap. A truncated log (``Log truncated``) is refused, never guessed.

Two SwapEvent sizes are accepted: the current one (162 bytes, with mints and fees) and the first
deployed one (81 bytes, up to ``base_input``). Any other size is an explicit error.
"""
import base64
from dataclasses import dataclass
import hashlib
import struct

CPMM_PROGRAM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
SWAP_DISCRIMINATOR = hashlib.sha256(b'event:SwapEvent').digest()[:8]
LP_DISCRIMINATOR = hashlib.sha256(b'event:LpChangeEvent').digest()[:8]
_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_SWAP_HEAD = struct.Struct('<32s6Q?')                 # pool .. base_input: 81 bytes
_SWAP_TAIL = struct.Struct('<32s32s2Q?')              # input_mint .. creator_fee_on_input: 81 bytes
_LP = struct.Struct('<32s7QB')                        # 89 bytes


class EventDecodeError(ValueError):
    pass


class LogsTruncated(EventDecodeError):
    pass


def b58encode(raw):
    number = int.from_bytes(raw, 'big')
    out = ''
    while number:
        number, digit = divmod(number, 58)
        out = _ALPHABET[digit] + out
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + out


@dataclass(frozen=True)
class SwapEvent:
    pool: str
    input_vault_before: int      # reserve of the input token, fees excluded, before this swap
    output_vault_before: int
    input_amount: int            # received by the pool (after any token transfer fee)
    output_amount: int           # sent to the trader (before any token transfer fee)
    input_transfer_fee: int
    output_transfer_fee: int
    base_input: bool             # True: swap_base_input (exact in); False: swap_base_output (exact out)
    input_mint: str = None       # the five fields below exist only in the current layout
    output_mint: str = None
    trade_fee: int = None
    creator_fee: int = None
    creator_fee_on_input: bool = None
    layout: str = 'current'


@dataclass(frozen=True)
class LpChangeEvent:
    pool: str
    lp_amount_before: int
    token_0_vault_before: int
    token_1_vault_before: int
    token_0_amount: int
    token_1_amount: int
    token_0_transfer_fee: int
    token_1_transfer_fee: int
    change_type: int             # 0 deposit, 1 withdraw (2 initialize in later versions)


def _bool(value):
    if value not in (0, 1):
        raise EventDecodeError('invalid_bool')
    return bool(value)


def decode(payload):
    """A decoded event, or None when the discriminator is not one of ours."""
    head, body = payload[:8], payload[8:]
    if head == SWAP_DISCRIMINATOR:
        if len(body) not in (_SWAP_HEAD.size, _SWAP_HEAD.size + _SWAP_TAIL.size):
            raise EventDecodeError('unknown_swap_event_size:%d' % len(body))
        if body[80] not in (0, 1):
            raise EventDecodeError('invalid_bool')
        pool, in_before, out_before, amount_in, amount_out, fee_in, fee_out, base_input = _SWAP_HEAD.unpack_from(body)
        common = (b58encode(pool), in_before, out_before, amount_in, amount_out, fee_in, fee_out, base_input)
        if len(body) == _SWAP_HEAD.size:
            return SwapEvent(*common, layout='legacy')
        if body[-1] not in (0, 1):
            raise EventDecodeError('invalid_bool')
        mint_in, mint_out, trade_fee, creator_fee, on_input = _SWAP_TAIL.unpack_from(body, _SWAP_HEAD.size)
        return SwapEvent(*common, b58encode(mint_in), b58encode(mint_out), trade_fee, creator_fee, on_input)
    if head == LP_DISCRIMINATOR:
        if len(body) != _LP.size:
            raise EventDecodeError('unknown_lp_event_size:%d' % len(body))
        pool, *numbers = _LP.unpack(body)
        return LpChangeEvent(b58encode(pool), *numbers)
    return None


def program_data(log_messages, program=CPMM_PROGRAM):
    """Payloads of the ``Program data:`` lines logged while ``program`` is the running frame."""
    if log_messages is None:
        raise EventDecodeError('log_messages_missing')
    stack, payloads = [], []
    for line in log_messages:
        if line.startswith('Log truncated'):
            raise LogsTruncated('log_truncated')
        parts = line.split(' ')
        # A frame line names a program id; ``Program log: ...`` (free text of a program) never is one.
        frame = len(parts) >= 3 and parts[0] == 'Program' and not parts[1].endswith(':')
        if frame and len(parts) == 4 and parts[2] == 'invoke' and parts[3].startswith('['):
            stack.append(parts[1])
        elif frame and (parts[2] == 'success' or parts[2].startswith('failed')):
            if not stack or stack[-1] != parts[1]:
                raise EventDecodeError('unbalanced_program_frames')
            stack.pop()
        elif line.startswith('Program data: '):
            if not stack:
                raise EventDecodeError('program_data_outside_any_frame')
            if stack[-1] == program:
                try:
                    payloads.append(base64.b64decode(line[len('Program data: '):], validate=True))
                except ValueError as exc:
                    raise EventDecodeError('invalid_base64') from exc
    if stack:
        raise EventDecodeError('unbalanced_program_frames')
    return payloads


def transaction_events(tx, pool):
    """Events of ``pool`` in a raw ``getTransaction`` result, in execution order; [] for a failed transaction."""
    meta = tx.get('meta') or {}
    if meta.get('err') is not None:
        return []                               # a failed transaction changes no reserve
    events = [decode(payload) for payload in program_data(meta.get('logMessages'))]
    return [event for event in events if event is not None and event.pool == pool]
