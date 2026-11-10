"""Synthetic LaunchLab bank: fixture account bytes moved by exact curve fills.

The accounts are the raw RPC-shaped values the frozen builder decodes. A fill is
computed by ``bot.market.launchlab_curve`` and written back into the pool and
vault bytes, so the next order is built by the frozen builder on the new state.

Not modelled (and therefore not claimed): where curve fees are routed. A fee
leaves the trader and is credited to no account here; the accrued-fee fields of
the pool stay untouched and the quote vault moves only by the curve amounts.
There is no holder ledger either: a trade "by others" is pure curve arithmetic.
"""
import base64
import copy
import struct

from bot.market.launchlab_curve import CurveError, CurveState, buy_exact_in, sell_exact_in
from bot.p3 import launchlab

# Pool u64 fields start at byte 21, eight bytes each, in the order decoded by
# bot/p3/launchlab.py:_pool (supply, total_sell_a, virtual_a, virtual_b,
# real_a, real_b, ...). The SPL token account amount is at byte 64.
_REAL_A_OFFSET = 21 + 8 * 4
_REAL_B_OFFSET = 21 + 8 * 5
_TOKEN_AMOUNT_OFFSET = 64


def _add_u64(account, offset, delta):
    raw = bytearray(base64.b64decode(account['data'][0]))
    value = struct.unpack_from('<Q', raw, offset)[0] + delta
    if not 0 <= value < 2**64:
        raise ValueError('synthetic_bank_balance_out_of_range')
    struct.pack_into('<Q', raw, offset, value)
    account['data'] = [base64.b64encode(bytes(raw)).decode(), 'base64']


def curve_record(state):
    return dict(virtual_base=state.virtual_base, virtual_quote=state.virtual_quote,
                real_base=state.real_base, real_quote=state.real_quote,
                total_base_sell=state.total_base_sell)


class SyntheticBank:
    def __init__(self, accounts, *, pool_address, mint, context_slot):
        self.pool_address, self.mint, self.context_slot = pool_address, mint, context_slot
        self.addresses = launchlab.addresses_from_pool(accounts[pool_address], mint, pool_address)
        self.accounts = {address: copy.deepcopy(accounts[address])
                         for address in self.addresses.values()}

    def copy(self):
        return SyntheticBank(self.accounts, pool_address=self.pool_address,
                             mint=self.mint, context_slot=self.context_slot)

    def snapshot(self):
        """A private copy of the seven pool-role accounts for one builder call."""
        return copy.deepcopy(self.accounts)

    def _pool(self, accounts=None):
        return launchlab._pool((accounts or self.accounts)[self.pool_address])[0]

    def _curve(self, accounts=None):
        pool = self._pool(accounts)
        return CurveState(pool['virtual_a'], pool['virtual_b'], pool['real_a'],
                          pool['real_b'], pool['total_sell_a'])

    @property
    def curve(self):
        return self._curve()

    @property
    def fee_rate_ppm(self):
        """Protocol + platform + creator rate, as the frozen builder sums them.

        The share fee is 0: the builder's swap instruction carries a zero
        share-fee argument (bot/live/route.py, ``struct.pack('<QQQ', ..., 0)``).
        """
        config = launchlab._config(self.accounts[self.addresses['config']])[0]
        platform = launchlab._platform(self.accounts[self.addresses['platform']])[0]
        return (config['trade_fee_rate_ppm'] + platform['platform_fee_rate_ppm']
                + platform['creator_fee_rate_ppm'])

    def quote(self, side, amount_in):
        """Exact fill on the current state, or CurveError with the reason."""
        if side == 'BUY':
            fill = buy_exact_in(self.curve, amount_in, self.fee_rate_ppm)
            # Same second boundary as bot/p3/launchlab.py:constant_product_projection;
            # the curve module only knows the remaining base.
            if fill.after.real_quote >= self._pool()['total_fundraising_b']:
                raise CurveError('buy_reaches_fundraising_boundary')
            return fill
        if side == 'SELL':
            return sell_exact_in(self.curve, amount_in, self.fee_rate_ppm)
        raise CurveError('explicit_BUY_or_SELL_required')

    def apply(self, fill):
        """Write one fill quoted on the current state; all writes or none."""
        if fill.before != self.curve:
            raise ValueError('fill_not_quoted_on_current_bank_state')
        base = fill.after.real_base - fill.before.real_base
        quote = fill.after.real_quote - fill.before.real_quote
        accounts = self.snapshot()
        vault_b = accounts[self.addresses['vault_b']]
        _add_u64(accounts[self.pool_address], _REAL_A_OFFSET, base)
        _add_u64(accounts[self.pool_address], _REAL_B_OFFSET, quote)
        _add_u64(accounts[self.addresses['vault_a']], _TOKEN_AMOUNT_OFFSET, -base)
        _add_u64(vault_b, _TOKEN_AMOUNT_OFFSET, quote)
        vault_b['lamports'] += quote  # native vault: lamports back the WSOL amount
        if self._curve(accounts) != fill.after:
            raise ValueError('synthetic_bank_write_did_not_decode_back')
        self.accounts = accounts
        self.context_slot += 1
