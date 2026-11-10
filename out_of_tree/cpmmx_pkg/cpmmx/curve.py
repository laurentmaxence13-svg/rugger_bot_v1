"""Exact integer arithmetic of a cp-swap pool (transcribed from the pinned official source).

Reserves are the pool's ``vault_amount_without_fee``: the vault balance minus the protocol, fund
and creator fees accrued and not yet collected (states/pool.rs). A swap changes them as follows
(instructions/swap_base_input.rs + PoolState::update_fees):
  input side : + input_amount - protocol_fee - fund_fee - (creator_fee when it is taken on the input)
  output side: - output_amount - (creator_fee when it is taken on the output)
"""
from dataclasses import dataclass

FEE_DENOMINATOR = 1_000_000


class CurveError(ValueError):
    pass


@dataclass(frozen=True)
class Fees:
    """AmmConfig rates in 10^-6; protocol and fund rates are shares OF THE TRADE FEE."""
    trade_fee_rate: int
    creator_fee_rate: int = 0
    protocol_fee_rate: int = 0
    fund_fee_rate: int = 0

    def __post_init__(self):
        for name in ('trade_fee_rate', 'creator_fee_rate', 'protocol_fee_rate', 'fund_fee_rate'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value < FEE_DENOMINATOR:
                raise CurveError(f'invalid_{name}')
        if self.trade_fee_rate + self.creator_fee_rate >= FEE_DENOMINATOR:
            raise CurveError('fees_take_everything')


@dataclass(frozen=True)
class SwapResult:
    input_amount: int        # what the trader sends (after any token transfer fee)
    output_amount: int       # what the trader receives (before any token transfer fee)
    trade_fee: int
    protocol_fee: int
    fund_fee: int
    creator_fee: int
    creator_fee_on_input: bool


def _ceil_div(amount, numerator, denominator):
    return (amount * numerator + denominator - 1) // denominator


def _uint(value, name):
    if type(value) is not int or value < 0:
        raise CurveError(f'invalid_{name}')
    return value


def _pre_fee(post_fee_amount, rate):
    """Fees::calculate_pre_fee_amount."""
    if rate == 0:
        return post_fee_amount
    denominator = FEE_DENOMINATOR - rate
    return (post_fee_amount * FEE_DENOMINATOR + denominator - 1) // denominator


def swap_base_input(input_amount, input_vault, output_vault, fees, creator_fee_on_input):
    """CurveCalculator::swap_base_input: exact input, the output is computed."""
    for name, value in (('input_amount', input_amount), ('input_vault', input_vault), ('output_vault', output_vault)):
        _uint(value, name)
    if input_amount == 0 or input_vault == 0 or output_vault == 0:
        raise CurveError('zero_trading_tokens')
    creator_fee = 0
    if creator_fee_on_input:
        total = _ceil_div(input_amount, fees.trade_fee_rate + fees.creator_fee_rate, FEE_DENOMINATOR)
        if fees.creator_fee_rate:
            creator_fee = total * fees.creator_fee_rate // (fees.trade_fee_rate + fees.creator_fee_rate)
        trade_fee = total - creator_fee
        less_fees = input_amount - total
    else:
        trade_fee = _ceil_div(input_amount, fees.trade_fee_rate, FEE_DENOMINATOR)
        less_fees = input_amount - trade_fee
    if less_fees <= 0:
        raise CurveError('input_consumed_by_fees')
    swapped = less_fees * output_vault // (input_vault + less_fees)
    if creator_fee_on_input:
        output_amount = swapped
    else:
        creator_fee = _ceil_div(swapped, fees.creator_fee_rate, FEE_DENOMINATOR)
        output_amount = swapped - creator_fee
    if output_amount <= 0:
        raise CurveError('zero_output')
    return SwapResult(input_amount, output_amount, trade_fee, trade_fee * fees.protocol_fee_rate // FEE_DENOMINATOR,
                      trade_fee * fees.fund_fee_rate // FEE_DENOMINATOR, creator_fee, bool(creator_fee_on_input))


def swap_base_output(output_amount, input_vault, output_vault, fees, creator_fee_on_input):
    """CurveCalculator::swap_base_output: exact output, the input is computed."""
    for name, value in (('output_amount', output_amount), ('input_vault', input_vault), ('output_vault', output_vault)):
        _uint(value, name)
    if output_amount == 0 or input_vault == 0 or output_vault == 0:
        raise CurveError('zero_trading_tokens')
    creator_fee = 0
    actual_output = output_amount
    if not creator_fee_on_input:
        actual_output = _pre_fee(output_amount, fees.creator_fee_rate)
        creator_fee = actual_output - output_amount
    if actual_output >= output_vault:
        raise CurveError('output_exceeds_vault')
    swapped = -(-(input_vault * actual_output) // (output_vault - actual_output))      # checked_ceil_div
    if creator_fee_on_input:
        with_fee = _pre_fee(swapped, fees.trade_fee_rate + fees.creator_fee_rate)
        total = with_fee - swapped
        if fees.creator_fee_rate:
            creator_fee = total * fees.creator_fee_rate // (fees.trade_fee_rate + fees.creator_fee_rate)
        trade_fee = total - creator_fee
    else:
        with_fee = _pre_fee(swapped, fees.trade_fee_rate)
        trade_fee = with_fee - swapped
    return SwapResult(with_fee, output_amount, trade_fee, trade_fee * fees.protocol_fee_rate // FEE_DENOMINATOR,
                      trade_fee * fees.fund_fee_rate // FEE_DENOMINATOR, creator_fee, bool(creator_fee_on_input))


def reserves_after(input_vault, output_vault, result):
    """(input reserve, output reserve) the pool holds, fees excluded, once ``result`` is applied."""
    on_input = result.creator_fee_on_input
    new_input = (input_vault + result.input_amount - result.protocol_fee - result.fund_fee
                 - (result.creator_fee if on_input else 0))
    new_output = output_vault - result.output_amount - (0 if on_input else result.creator_fee)
    if new_output <= 0:
        raise CurveError('output_vault_emptied')
    return new_input, new_output
