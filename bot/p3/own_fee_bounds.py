"""Explicit native-SOL hypothetical fee bounds for legacy/v0 PAPER routes.

Not an observed fee or a generated transaction. Caller supplies signed-message
limits and the priority price range; no network access and no signing. Route
fees already included in buy/sell quote output must NEVER be subtracted again.
Solana legacy/v0: base fee = 5000 per signature (current documented rate),
priority = ceil(CU price micro-lamports * requested CU limit / 1e6).
Does not apply to Solana v1 messages (different fee structure).
"""


def _int(v, name, *, positive=False, maximum=2**64-1):
    if type(v) is not int or not (1 if positive else 0) <= v <= maximum:
        raise ValueError(name)
    return v


def _tx_fee(signatures, cu_limit, price_micro_lamports, base_lamports):
    return (signatures * base_lamports
            + (cu_limit * price_micro_lamports + 999999) // 1000000)


def legacy_v0_roundtrip_fee_bounds(*, buy_signatures, sell_signatures,
                                   buy_cu_limit, sell_cu_limit,
                                   priority_price_min_micro_lamports,
                                   priority_price_max_micro_lamports,
                                   extra_failed_transactions_max,
                                   worst_failed_transaction_fee_lamports,
                                   ata_rent_locked_lamports=None,
                                   ata_recovered_at_horizon=None,
                                   base_lamports_per_signature=5000):
    """Return separate fee and locked-capital bounds from explicit parameters.

    If ATA rent/recovery is unknown, the economic upper bound is unknown. An
    explicit recovery status is conditional, never proof it would occur.
    Failed attempts are upper bounded; no failures are assumed below.
    """
    for name, val, positive, maximum in (
            ('buy_signatures_invalid',buy_signatures,True,256),
            ('sell_signatures_invalid',sell_signatures,True,256),
            ('buy_cu_limit_invalid',buy_cu_limit,True,1400000),
            ('sell_cu_limit_invalid',sell_cu_limit,True,1400000),
            ('priority_min_invalid',priority_price_min_micro_lamports,False,2**64-1),
            ('priority_max_invalid',priority_price_max_micro_lamports,False,2**64-1),
            ('failed_attempts_max_invalid',extra_failed_transactions_max,False,1000),
            ('failed_attempt_fee_max_invalid',worst_failed_transaction_fee_lamports,False,2**64-1),
            ('base_fee_invalid',base_lamports_per_signature,True,2**64-1)):
        _int(val,name,positive=positive,maximum=maximum)
    if priority_price_min_micro_lamports > priority_price_max_micro_lamports:
        raise ValueError('priority_price_bounds_reversed')
    if type(ata_recovered_at_horizon) not in (bool,type(None)):
        raise ValueError('ata_recovery_must_be_boolean_or_unknown')
    if ata_rent_locked_lamports is not None:
        _int(ata_rent_locked_lamports,'ATA_rent_locked_invalid')
    if extra_failed_transactions_max>0 and worst_failed_transaction_fee_lamports==0:
        raise ValueError('failed_attempts_require_nonzero_explicit_fee_bound')
    low = _tx_fee(buy_signatures,buy_cu_limit,priority_price_min_micro_lamports,
                  base_lamports_per_signature) + _tx_fee(
                  sell_signatures,sell_cu_limit,priority_price_min_micro_lamports,
                  base_lamports_per_signature)
    high = _tx_fee(buy_signatures,buy_cu_limit,priority_price_max_micro_lamports,
                   base_lamports_per_signature) + _tx_fee(
                   sell_signatures,sell_cu_limit,priority_price_max_micro_lamports,
                   base_lamports_per_signature)
    high += extra_failed_transactions_max*worst_failed_transaction_fee_lamports
    rent_cost_upper = None
    if ata_rent_locked_lamports is not None:
        rent_cost_upper = 0 if ata_recovered_at_horizon is True else ata_rent_locked_lamports
    return dict(schema='p3-own-v0-conditional-fee-bounds-v1',
                status='ESTIMATED_BOUND_NOT_OBSERVED',unit='lamports',
                fee_version_scope='Solana_legacy_or_v0_only',
                base_fee_formula_source='https://solana.com/docs/core/fees/fee-structure',
                source_time_or_priority_market_observed=False,
                assumed_base_lamports_per_signature=str(base_lamports_per_signature),
                buy_fee_lower_lamports=str(_tx_fee(buy_signatures,buy_cu_limit,
                    priority_price_min_micro_lamports,base_lamports_per_signature)),
                sell_fee_lower_lamports=str(_tx_fee(sell_signatures,sell_cu_limit,
                    priority_price_min_micro_lamports,base_lamports_per_signature)),
                buy_fee_upper_lamports=str(_tx_fee(buy_signatures,buy_cu_limit,
                    priority_price_max_micro_lamports,base_lamports_per_signature)),
                sell_fee_upper_lamports=str(_tx_fee(sell_signatures,sell_cu_limit,
                    priority_price_max_micro_lamports,base_lamports_per_signature)),
                hypothetical_failed_attempts_max=extra_failed_transactions_max,
                cost_lower_lamports=str(low),
                cost_upper_lamports=None if rent_cost_upper is None else str(high+rent_cost_upper),
                cost_upper_excluding_unknown_ATA_lamports=str(high),
                ata_rent_locked_lamports=(None if ata_rent_locked_lamports is None
                                          else str(ata_rent_locked_lamports)),
                ata_recovered_at_horizon_hypothesis=ata_recovered_at_horizon,
                rent_nonrecoverable_upper_lamports=(None if rent_cost_upper is None
                                                  else str(rent_cost_upper)),
                all_applicable_costs_known=False,
                route_fees_already_in_quote_not_counted_twice=True,
                not_a_profitability_or_fill_certificate=True)
