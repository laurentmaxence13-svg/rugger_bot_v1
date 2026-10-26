"""Separate SOL-denominated quote projections; never writes a trading ledger.

Atomic amounts are Python integers. Decimal inputs must be exact (Decimal,
string or integer, never binary float). USD marks require two point-in-time
SOL/USD observations; USDC is deliberately not treated as USD. These projections
do not certify a fill, fee execution, token inventory or market profitability.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction


LAMPORTS_PER_SOL = 1_000_000_000


class InsufficientAccountingData(ValueError):
    """Required monetary, fee, inventory or point-in-time evidence is unusable."""


def _integer(value, field, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise InsufficientAccountingData(field + ' requires an exact nonnegative integer')
    return value


def _decimal(value, field, *, positive=False):
    if type(value) not in (Decimal, str, int):
        raise InsufficientAccountingData(field + ' requires an exact decimal, never float')
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise InsufficientAccountingData(field + ' requires a finite decimal') from None
    # Resource limits on malformed inputs, not a trading/price threshold.
    if (not number.is_finite() or len(number.as_tuple().digits) > 256
            or abs(number.adjusted()) > 1000
            or number < 0 or (positive and number == 0)):
        raise InsufficientAccountingData(field + ' is outside the supported decimal domain')
    return number


def _fraction_decimal(value):
    with localcontext() as context:
        context.prec = 80
        return Decimal(value.numerator) / Decimal(value.denominator)


def lamports_to_sol(lamports):
    """Exact integer-to-SOL display conversion, including signed P&L."""
    if type(lamports) is not int:
        raise InsufficientAccountingData('lamports requires an exact integer')
    # Decimal construction from a coefficient/exponent does not round through
    # the process-wide Decimal context, even for an unusually large balance.
    sign = int(lamports < 0)
    digits = tuple(int(character) for character in str(abs(lamports)))
    return Decimal((sign, digits, -9))


@dataclass(frozen=True)
class FxSnapshot:
    rate: Decimal
    source_time_ms: int | None
    received_at_ms: int
    base_currency: str = 'SOL'
    quote_currency: str = 'USD'
    available_at_ms: int | None = None


@dataclass(frozen=True)
class SolFeeBreakdown:
    """Fees outside provider output amounts, with explicit unknowns refused.

    Extra fees cover entry/exit network and other costs NOT already included in
    the provider's input/output amounts. Failed-attempt fees are explicit, even
    when the observed/assumed tuple is empty. An estimate remains an estimate.
    """
    entry_extra_lamports: int | None
    exit_extra_lamports: int | None
    failed_attempt_lamports: tuple[int, ...] | None
    quote_amounts_net_of_pool_fees: bool = True
    extra_fees_exclude_pool_fees: bool = True
    provenance: str = 'estimate'


def validate_fx_as_of(snapshot, *, as_of_ms, max_age_ms):
    """Return an exact SOL/USD rate known and fresh at the requested instant."""
    _integer(as_of_ms, 'as_of_ms')
    _integer(max_age_ms, 'max_age_ms')
    if not isinstance(snapshot, FxSnapshot):
        raise InsufficientAccountingData('SOL/USD snapshot is missing')
    if snapshot.base_currency != 'SOL' or snapshot.quote_currency != 'USD':
        raise InsufficientAccountingData('FX currencies must be SOL/USD; USDC parity is not assumed')
    rate = _decimal(snapshot.rate, 'SOL/USD rate', positive=True)
    received = _integer(snapshot.received_at_ms, 'FX received_at_ms')
    if snapshot.source_time_ms is None:
        raise InsufficientAccountingData('FX source time is unknown')
    source = _integer(snapshot.source_time_ms, 'FX source_time_ms')
    available = received if snapshot.available_at_ms is None else _integer(
        snapshot.available_at_ms, 'FX available_at_ms')
    if not source <= received <= available <= as_of_ms:
        raise InsufficientAccountingData('FX was unavailable or temporally inconsistent at decision time')
    if as_of_ms - source > max_age_ms:
        raise InsufficientAccountingData('FX source observation is stale at decision time')
    return rate


def _fees(fees):
    if not isinstance(fees, SolFeeBreakdown):
        raise InsufficientAccountingData('Explicit fee breakdown is required')
    if (fees.quote_amounts_net_of_pool_fees is not True
            or fees.extra_fees_exclude_pool_fees is not True):
        raise InsufficientAccountingData('Quote fee basis is unknown or pool fees would be counted twice')
    if fees.provenance not in ('estimate', 'observed', 'synthetic'):
        raise InsufficientAccountingData('Fee provenance must be explicit')
    entry = _integer(fees.entry_extra_lamports, 'entry extra fee')
    exit_fee = _integer(fees.exit_extra_lamports, 'exit extra fee')
    if type(fees.failed_attempt_lamports) is not tuple:
        raise InsufficientAccountingData('Failed-attempt fee tuple is unknown')
    failed = tuple(_integer(value, 'failed-attempt fee') for value in fees.failed_attempt_lamports)
    return entry, exit_fee, failed


def _projection(entry, exit_amount, fees, cash):
    entry = _integer(entry, 'entry_spent_lamports', positive=True)
    exit_amount = _integer(exit_amount, 'exit_received_lamports')
    cash = _integer(cash, 'available_cash_lamports')
    entry_fee, exit_fee, failed_fees = _fees(fees)
    total_fees = entry_fee + exit_fee + sum(failed_fees)
    reserved = entry + total_fees
    if reserved > cash:
        raise InsufficientAccountingData('Available cash cannot reserve position and all known extra fees')
    pnl = exit_amount - reserved
    return {
        'status': 'quoted_projection_only',
        'unit': 'SOL',
        'entry_spent_lamports': entry,
        'exit_received_lamports': exit_amount,
        'entry_extra_fee_lamports': entry_fee,
        'exit_extra_fee_lamports': exit_fee,
        'failed_attempt_fee_lamports': failed_fees,
        'total_extra_fee_lamports': total_fees,
        'reserved_cash_lamports': reserved,
        'initial_available_cash_lamports': cash,
        'final_available_cash_lamports': cash + pnl,
        'net_pnl_lamports': pnl,
        'net_pnl_sol': lamports_to_sol(pnl),
        'net_return_on_position': _fraction_decimal(Fraction(pnl, entry)),
        'fee_provenance': fees.provenance,
        'fees_already_in_quote_counted_again': False,
        'execution_verified': False,
        'economic_verdict': 'INSUFFICIENT DATA',
        'model_eligible': False,
        'historical_ledger_mutated': False,
    }


def native_sol_round_trip(*, entry_spent_lamports, exit_received_lamports,
                          acquired_token_atomic, sold_token_atomic, token_mint,
                          fees, available_cash_lamports):
    """Project a full quoted SOL→token→SOL round trip, without any USD rate.

    A missing/failed exit is unknown, not zero proceeds. A partial sale leaves
    inventory and cannot be reported as the complete position's realized P&L.
    Known costs are conservatively reserved up front, preventing borrowing even
    when fees could otherwise be funded by an assumed future exit.
    """
    if not isinstance(token_mint, str) or not token_mint.strip():
        raise InsufficientAccountingData('Token mint identity is missing')
    acquired = _integer(acquired_token_atomic, 'acquired_token_atomic', positive=True)
    sold = _integer(sold_token_atomic, 'sold_token_atomic', positive=True)
    if acquired != sold:
        raise InsufficientAccountingData('Partial or excess token sale cannot close a round-trip projection')
    result = _projection(entry_spent_lamports, exit_received_lamports,
                         fees, available_cash_lamports)
    result.update(valuation_basis='native_SOL_quote_amounts', token_mint=token_mint,
                  acquired_token_atomic=acquired, sold_token_atomic=sold,
                  remaining_token_atomic=0, fx_required_for_sol_pnl=False)
    return result


def usd_marked_round_trip(*, position_lamports, entry_token_usd, exit_token_usd,
                          entry_fx, exit_fx, entry_at_ms, exit_at_ms,
                          max_fx_age_ms, fees, available_cash_lamports):
    """Project USD price returns in SOL using distinct, as-of entry/exit FX.

    Exit lamports are the exact rational result rounded DOWN. The calculation
    never relies on rounding a binary float or an intermediate Decimal quotient
    before flooring; this matters at a one-lamport boundary. Neither USD mark
    nor FX data alone certifies an available buy/sell route.
    """
    position = _integer(position_lamports, 'position_lamports', positive=True)
    start = _integer(entry_at_ms, 'entry_at_ms')
    end = _integer(exit_at_ms, 'exit_at_ms')
    if end < start:
        raise InsufficientAccountingData('Exit time cannot precede entry time')
    entry_price = _decimal(entry_token_usd, 'entry token USD price', positive=True)
    exit_price = _decimal(exit_token_usd, 'exit token USD price')
    entry_rate = validate_fx_as_of(entry_fx, as_of_ms=start, max_age_ms=max_fx_age_ms)
    exit_rate = validate_fx_as_of(exit_fx, as_of_ms=end, max_age_ms=max_fx_age_ms)
    ratio = Fraction(exit_price) * Fraction(entry_rate) / Fraction(entry_price) / Fraction(exit_rate)
    exact_exit = position * ratio
    rounded_exit = exact_exit.numerator // exact_exit.denominator
    result = _projection(position, rounded_exit, fees, available_cash_lamports)
    result.update(
        valuation_basis='USD_token_marks_with_point_in_time_SOL_USD',
        unrounded_gross_return_sol=_fraction_decimal(ratio - 1),
        entry_token_usd=entry_price, exit_token_usd=exit_price,
        entry_sol_usd=entry_rate, exit_sol_usd=exit_rate,
        entry_at_ms=start, exit_at_ms=end,
        rounding_policy='floor_exact_exit_lamports',
        discarded_fractional_lamports=_fraction_decimal(exact_exit - rounded_exit),
        fx_required_for_sol_pnl=True,
    )
    return result


def accounting_json_safe(value, *, _atomic=False):
    """Export Decimals and atomic amounts as strings, avoiding JSON float loss."""
    if isinstance(value, Decimal):
        return str(value)
    if type(value) is int and _atomic:
        return str(value)
    if isinstance(value, dict):
        return {key: accounting_json_safe(item, _atomic=key.endswith(('_lamports', '_atomic')))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [accounting_json_safe(item, _atomic=_atomic) for item in value]
    return value
