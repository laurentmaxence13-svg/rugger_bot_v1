"""Exact integer arithmetic of the LaunchLab constant-product bonding curve.

State convention (identical to the on-chain ``TradeEvent`` fields):

* ``real_base``  -- base tokens already sold by the curve (atomic units);
* ``real_quote`` -- quote collected by the curve, fees excluded (atomic units);
* effective reserves: ``x = virtual_base - real_base``, ``y = virtual_quote + real_quote``.

Fee rule (verified against signed mainnet transactions, see tests):

* buy exact-in: ``fee = ceil(amount_in * rate / 1e6)`` taken from the input,
  ``out = floor(net * x / (y + net))`` with ``net = amount_in - fee``;
* sell exact-in: ``gross = floor(amount_in * y / (x + amount_in))``,
  ``fee = ceil(gross * rate / 1e6)``, ``out = gross - fee``.

``rate`` is the sum of protocol, platform, creator and share fee rates (ppm).
Exact-out instructions and the migration boundary are deliberately refused:
callers must treat them as unknown rather than approximate them.
"""
from dataclasses import dataclass, replace

FEE_DENOMINATOR = 1_000_000
U64_MAX = (1 << 64) - 1


class CurveError(ValueError):
    """The requested trade cannot be priced exactly on this curve state."""


def _ceil_div(a, b):
    return -(-a // b)


def _uint(value, name, *, positive=False):
    if type(value) is not int or value < 0 or value > U64_MAX or (positive and value == 0):
        raise CurveError(f'invalid_{name}')
    return value


@dataclass(frozen=True)
class CurveState:
    virtual_base: int
    virtual_quote: int
    real_base: int
    real_quote: int
    total_base_sell: int

    def __post_init__(self):
        for name in ('virtual_base', 'virtual_quote', 'real_base', 'real_quote', 'total_base_sell'):
            _uint(getattr(self, name), name)
        if self.real_base > self.total_base_sell or self.real_base >= self.virtual_base:
            raise CurveError('invalid_curve_state')

    @property
    def base_reserve(self):
        return self.virtual_base - self.real_base

    @property
    def quote_reserve(self):
        return self.virtual_quote + self.real_quote

    @property
    def remaining_base(self):
        return self.total_base_sell - self.real_base

    @property
    def progress_ppm(self):
        """Share of the sellable supply already bought, in ppm (floor)."""
        if self.total_base_sell == 0:
            return 0
        return self.real_base * FEE_DENOMINATOR // self.total_base_sell

    def spot_price(self):
        """Marginal quote atomic units per base atomic unit, as (num, den)."""
        return self.quote_reserve, self.base_reserve


@dataclass(frozen=True)
class Fill:
    side: str
    amount_in: int
    amount_out: int
    fee: int
    before: CurveState
    after: CurveState


def fee_for(amount, rate_ppm):
    _uint(rate_ppm, 'fee_rate')
    if rate_ppm >= FEE_DENOMINATOR:
        raise CurveError('fee_rate_not_below_denominator')
    return _ceil_div(amount * rate_ppm, FEE_DENOMINATOR)


def buy_exact_in(state, quote_in, rate_ppm):
    """Spend exactly ``quote_in`` quote atomic units (fees included)."""
    _uint(quote_in, 'quote_in', positive=True)
    fee = fee_for(quote_in, rate_ppm)
    net = quote_in - fee
    if net <= 0:
        raise CurveError('input_consumed_by_fee')
    x, y = state.base_reserve, state.quote_reserve
    out = net * x // (y + net)
    if out <= 0:
        raise CurveError('output_rounds_to_zero')
    if out > state.remaining_base:
        # The program caps the buy and refunds; that path is not modelled.
        raise CurveError('buy_crosses_migration_boundary')
    after = replace(state, real_base=state.real_base + out, real_quote=state.real_quote + net)
    return Fill('buy', quote_in, out, fee, state, after)


def sell_exact_in(state, base_in, rate_ppm):
    """Sell exactly ``base_in`` base atomic units; output is net of fees."""
    _uint(base_in, 'base_in', positive=True)
    if base_in > state.real_base:
        raise CurveError('sell_exceeds_curve_inventory')
    x, y = state.base_reserve, state.quote_reserve
    gross = base_in * y // (x + base_in)
    if gross > state.real_quote:
        raise CurveError('sell_exceeds_quote_reserve')
    fee = fee_for(gross, rate_ppm)
    out = gross - fee
    if out <= 0:
        raise CurveError('output_rounds_to_zero')
    after = replace(state, real_base=state.real_base - base_in, real_quote=state.real_quote - gross)
    return Fill('sell', base_in, out, fee, state, after)
