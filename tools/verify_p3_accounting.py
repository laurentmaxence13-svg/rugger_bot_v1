#!/usr/bin/env python3
"""Independent synthetic cash-flow/FX oracle; no ledger, credentials or network.

Run from any directory with ``python -B tools/verify_p3_accounting.py``.
This verifies arithmetic and rejection rules, not market observations, executable
quotes, the historical ledger, real costs or strategy profitability.
"""
import json
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
import random
import sys


def _guard(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('Accounting oracle prohibits network access')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0])
        if path.name.startswith('.env') or path.suffix in ('.db', '.sqlite', '.sqlite3'):
            raise RuntimeError('Accounting oracle prohibits secrets and database files')


sys.addaudithook(_guard)
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.p3.accounting import (  # noqa: E402
    FxSnapshot, InsufficientAccountingData, SolFeeBreakdown,
    native_sol_round_trip, usd_marked_round_trip,
)


def require(condition, detail):
    if not condition:
        raise RuntimeError('Independent accounting check failed: ' + detail)


def rejected(call):
    try:
        call()
    except InsufficientAccountingData:
        return
    raise RuntimeError('Incomplete or unsafe accounting input was accepted')


def verify_cash(result, *, spent, proceeds, opening_cash, costs):
    # Independent cash flow: start - entry - extra costs + sale. Pool fees
    # are already reflected in sale proceeds; no pool fee is subtracted here.
    closing_cash = opening_cash - spent - costs + proceeds
    require(result['final_available_cash_lamports'] == closing_cash, 'cash conservation')
    require(result['net_pnl_lamports'] == closing_cash - opening_cash, 'cash vs P&L')
    require(Fraction(result['net_pnl_sol']) == Fraction(closing_cash - opening_cash, 10**9),
            'exact SOL display')
    require(result['reserved_cash_lamports'] == spent + costs, 'reservation')
    require(result['total_extra_fee_lamports'] == costs, 'costs charged once')
    require(result['execution_verified'] is False and result['model_eligible'] is False,
            'projection must remain ineligible for executed performance')
    require(result['economic_verdict'] == 'INSUFFICIENT DATA', 'economic uncertainty')
    require(result['historical_ledger_mutated'] is False, 'no ledger mutation')


def main():
    rng = random.Random(20261027)
    rejected_count = 0
    # Changing Decimal context must not affect integer lamports or exact display.
    for index in range(1000):
        spent = (1, 10**9, 2**53 + 1, 2**63 - 1)[index % 4] if index < 16 else rng.randrange(1, 2**63)
        entry_fee, exit_fee = rng.randrange(100_000), rng.randrange(100_000)
        failed = tuple(rng.randrange(10_000) for _ in range(index % 4))
        costs = entry_fee + exit_fee + sum(failed)
        cash = spent + costs + rng.randrange(10**10)
        fees = SolFeeBreakdown(entry_fee, exit_fee, failed, provenance='synthetic')
        with localcontext() as context:
            context.prec = 6 if index % 2 else 28
            if index < 500:
                proceeds = 0 if index % 17 == 0 else rng.randrange(2**64)
                inventory = rng.randrange(1, 2**63)
                kwargs = dict(entry_spent_lamports=spent, exit_received_lamports=proceeds,
                              acquired_token_atomic=inventory, sold_token_atomic=inventory,
                              token_mint='synthetic-oracle-mint', fees=fees,
                              available_cash_lamports=cash)
                result = native_sol_round_trip(**kwargs)
                call = native_sol_round_trip
            else:
                # All four prices have the SAME scale. The oracle computes exit
                # directly by integer cross-products and divmod; no production
                # helper, intermediate return or FX quotient is reused.
                entry_price, exit_price, entry_fx, exit_fx = (
                    rng.randrange(1, 10**10), rng.randrange(0, 10**10),
                    rng.randrange(1, 10**10), rng.randrange(1, 10**10))
                numerator = spent * exit_price * entry_fx
                denominator = entry_price * exit_fx
                proceeds, remainder = divmod(numerator, denominator)
                require(0 <= remainder < denominator, 'floor rounding oracle')
                def decimal_units(value):
                    return Decimal(f'{value // 10**6}.{value % 10**6:06d}')
                kwargs = dict(position_lamports=spent,
                              entry_token_usd=decimal_units(entry_price),
                              exit_token_usd=decimal_units(exit_price),
                              entry_fx=FxSnapshot(decimal_units(entry_fx), 900, 950, available_at_ms=990),
                              exit_fx=FxSnapshot(decimal_units(exit_fx), 1900, 1950, available_at_ms=1990),
                              entry_at_ms=1000, exit_at_ms=2000, max_fx_age_ms=100,
                              fees=fees, available_cash_lamports=cash)
                result = usd_marked_round_trip(**kwargs)
                call = usd_marked_round_trip
                require(result['exit_received_lamports'] == proceeds, 'FX integer cross-products')
            verify_cash(result, spent=spent, proceeds=proceeds, opening_cash=cash, costs=costs)
            # At one lamport below the complete reservation, even a large assumed
            # sale may not fund an entry that could not have been afforded.
            bad = dict(kwargs, available_cash_lamports=spent + costs - 1)
            rejected(lambda: call(**bad))
            rejected_count += 1

    baseline = dict(entry_spent_lamports=10**9, exit_received_lamports=10**9,
                    acquired_token_atomic=100, sold_token_atomic=100,
                    token_mint='synthetic-oracle-mint',
                    fees=SolFeeBreakdown(0, 0, (), provenance='synthetic'),
                    available_cash_lamports=10**10)
    for field, value in (('entry_extra_lamports', None), ('exit_extra_lamports', None),
                         ('failed_attempt_lamports', None),
                         ('quote_amounts_net_of_pool_fees', False),
                         ('extra_fees_exclude_pool_fees', False), ('provenance', 'unknown')):
        bad = dict(baseline, fees=replace(baseline['fees'], **{field: value}))
        rejected(lambda: native_sol_round_trip(**bad))
        rejected_count += 1
    for change in ({'exit_received_lamports': None}, {'sold_token_atomic': 99},
                   {'sold_token_atomic': 101}):
        bad = dict(baseline, **change)
        rejected(lambda: native_sol_round_trip(**bad))
        rejected_count += 1
    # A boundary case below one lamport must floor to zero, even under a small
    # ambient Decimal context. This checks the danger hidden by rounded ratios.
    near = usd_marked_round_trip(
        position_lamports=1, entry_token_usd=Decimal('1'),
        exit_token_usd=Decimal('0.999999999999999999999999999999999999'),
        entry_fx=FxSnapshot(Decimal('1'), 900, 950),
        exit_fx=FxSnapshot(Decimal('1'), 1900, 1950),
        entry_at_ms=1000, exit_at_ms=2000, max_fx_age_ms=100,
        fees=baseline['fees'], available_cash_lamports=10)
    require(near['exit_received_lamports'] == 0, 'sub-lamport boundary')
    print(json.dumps(dict(schema='p3-independent-accounting-check-v1',
                          synthetic_cases=1000, native_cases=500, fx_cases=500,
                          sub_lamport_boundary_cases=1, rejected_unsafe_inputs=rejected_count,
                          seed=20261027, status='PASS', ledger_access=False,
                          network_access=False, economic_verdict='INSUFFICIENT DATA'),
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
