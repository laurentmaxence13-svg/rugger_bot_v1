"""Itemised dry-run cost model, in lamports, integers only.

These are parameters of a rehearsal, not measurements: no fee was paid, no
priority-fee market was observed and no transaction failed on chain.
"""
from dataclasses import dataclass

# One required signature and no precompile: the constant the frozen builder
# adds in bot/live/route.py (``network_fee = 5000 + priority``).
BASE_FEE_LAMPORTS = 5000


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError('invalid_' + name)
    return value


@dataclass(frozen=True)
class CostModel:
    priority_fee_micro_lamports: int = 0  # per compute unit; a parameter, not an estimate
    compute_unit_limit: int = 200_000
    failed_attempts_per_order: int = 0    # landed-and-reverted attempts before each fill

    def __post_init__(self):
        _count(self.priority_fee_micro_lamports, 'priority_fee_micro_lamports')
        _count(self.failed_attempts_per_order, 'failed_attempts_per_order')
        if _count(self.compute_unit_limit, 'compute_unit_limit') == 0:
            raise ValueError('invalid_compute_unit_limit')

    @property
    def priority_fee_lamports(self):
        """Same ceiling as the frozen builder applies to the compute budget."""
        return (self.compute_unit_limit * self.priority_fee_micro_lamports + 999_999) // 1_000_000

    @property
    def attempt_fee_lamports(self):
        return BASE_FEE_LAMPORTS + self.priority_fee_lamports

    def order_costs(self, *, rent_opened_lamports):
        """What one filled order takes from the wallet besides its curve input."""
        failed = self.failed_attempts_per_order
        return dict(base_fee_lamports=BASE_FEE_LAMPORTS,
                    priority_fee_lamports=self.priority_fee_lamports,
                    failed_attempts=failed,
                    # A reverted transaction still pays its base and priority fee.
                    failed_attempts_lamports=failed * self.attempt_fee_lamports,
                    rent_opened_lamports=rent_opened_lamports)


def total(costs):
    return (costs['base_fee_lamports'] + costs['priority_fee_lamports']
            + costs['failed_attempts_lamports'] + costs['rent_opened_lamports'])


def close_pnl(position, *, sell_gross_lamports, sell_curve_fee_lamports, sell_costs, rent_recovered_lamports=0):
    """Net P&L of a closed shadow position; every line below is additive.

    net = curve_move - curve_fees - base_fees - priority_fees
          - failed_attempts_lamports - rent_written_off

    ``rent_recovered_lamports`` is what the built SELL transaction itself returns by
    closing the base token account (0 when it holds no such instruction: the
    rent opened by the BUY is then written off).
    """
    into_curve = position.principal_lamports - position.curve_fee_lamports
    curve_fees = position.curve_fee_lamports + sell_curve_fee_lamports
    base_fees = position.base_fee_lamports + sell_costs['base_fee_lamports']
    priority_fees = position.priority_fee_lamports + sell_costs['priority_fee_lamports']
    failed_lamports = position.failed_attempts_lamports + sell_costs['failed_attempts_lamports']
    rent_recovered = rent_recovered_lamports
    rent_written_off = position.rent_opened_lamports - rent_recovered
    curve_move = sell_gross_lamports - into_curve
    return dict(
        buy_principal_lamports=position.principal_lamports,
        sell_proceeds_lamports=sell_gross_lamports - sell_curve_fee_lamports,
        quote_into_curve_lamports=into_curve,
        quote_out_of_curve_lamports=sell_gross_lamports,
        curve_move_lamports=curve_move,
        curve_fees_lamports=curve_fees,
        base_fees_lamports=base_fees,
        priority_fees_lamports=priority_fees,
        failed_attempts=position.failed_attempts + sell_costs['failed_attempts'],
        failed_attempts_lamports=failed_lamports,
        rent_opened_lamports=position.rent_opened_lamports,
        rent_recovered_lamports=rent_recovered,
        rent_written_off_lamports=rent_written_off,
        net_pnl_lamports=(curve_move - curve_fees - base_fees - priority_fees
                          - failed_lamports - rent_written_off))
