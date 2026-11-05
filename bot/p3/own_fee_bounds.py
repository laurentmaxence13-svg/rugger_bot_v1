"""Explicit native-SOL hypothetical fee bounds for legacy/v0 PAPER routes.

Not an observed fee or a generated transaction. Caller supplies hypothetical
charged-signature counts (including precompiles), CU limits and priority range;
no network access and no signing. Route
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
    fee = (signatures * base_lamports
           + (cu_limit * price_micro_lamports + 999999) // 1000000)
    return _int(fee,'transaction_fee_overflow')


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

    The original cost bounds conservatively include a potentially unrecovered
    deposit. Separate fee-only and cash-commitment fields prevent treating that
    refundable balance as a proven irreversible loss. If rent is unknown, its
    capital/cost upper bound stays unknown, including when recovery is assumed.
    Recovery is a caller hypothesis, never proof. Failed attempts are assumed
    to use the declared buy/sell fee configurations; their fee ceiling must
    cover either route. No extra failures are assumed in the lower bound.
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
    buy_low = _tx_fee(buy_signatures,buy_cu_limit,
                      priority_price_min_micro_lamports,base_lamports_per_signature)
    sell_low = _tx_fee(sell_signatures,sell_cu_limit,
                       priority_price_min_micro_lamports,base_lamports_per_signature)
    buy_high = _tx_fee(buy_signatures,buy_cu_limit,
                       priority_price_max_micro_lamports,base_lamports_per_signature)
    sell_high = _tx_fee(sell_signatures,sell_cu_limit,
                        priority_price_max_micro_lamports,base_lamports_per_signature)
    low = _int(buy_low+sell_low,'roundtrip_fee_lower_overflow')
    high = _int(buy_high+sell_high,'roundtrip_fee_upper_overflow')
    if (extra_failed_transactions_max > 0
            and worst_failed_transaction_fee_lamports < max(buy_high,sell_high)):
        raise ValueError('failed_attempt_fee_bound_below_route_ceiling')
    failed_high = _int(extra_failed_transactions_max*worst_failed_transaction_fee_lamports,
                       'failed_attempt_fee_bound_overflow')
    high = _int(high+failed_high,'roundtrip_fee_and_failure_upper_overflow')
    rent_cost_upper = None
    cash_commitment_lower = cash_commitment_upper = None
    locked_lower = locked_upper = None
    if ata_rent_locked_lamports is not None:
        rent_cost_upper = 0 if ata_recovered_at_horizon is True else ata_rent_locked_lamports
        cash_commitment_lower = _int(low+ata_rent_locked_lamports,
                                     'cash_commitment_lower_overflow')
        cash_commitment_upper = _int(high+ata_rent_locked_lamports,
                                     'cash_commitment_upper_overflow')
        locked_lower = ata_rent_locked_lamports if ata_recovered_at_horizon is False else 0
        locked_upper = 0 if ata_recovered_at_horizon is True else ata_rent_locked_lamports
    bounded_cost_upper = (None if rent_cost_upper is None else
                          _int(high+rent_cost_upper,'horizon_cost_upper_overflow'))
    return dict(schema='p3-own-v0-conditional-fee-bounds-v1',
                status='ESTIMATED_BOUND_NOT_OBSERVED',unit='lamports',
                fee_version_scope='Solana_legacy_or_v0_only',
                base_fee_formula_source='https://solana.com/docs/core/fees/fee-structure',
                storage_balance_source='https://solana.com/docs/core/accounts',
                signature_count_scope='all_charged_transaction_and_precompile_signature_units',
                source_time_or_priority_market_observed=False,
                input_scope='explicit_caller_hypotheses_not_a_constructed_or_observed_message',
                assumed_base_lamports_per_signature=str(base_lamports_per_signature),
                buy_fee_lower_lamports=str(buy_low),
                sell_fee_lower_lamports=str(sell_low),
                buy_fee_upper_lamports=str(buy_high),
                sell_fee_upper_lamports=str(sell_high),
                hypothetical_failed_attempts_max=extra_failed_transactions_max,
                failed_attempt_fee_upper_lamports=str(failed_high),
                failed_attempt_scope='declared_buy_or_sell_fee_configuration_only',
                cost_lower_lamports=str(low),
                cost_upper_lamports=None if bounded_cost_upper is None else str(bounded_cost_upper),
                cost_upper_excluding_unknown_ATA_lamports=str(high),
                cost_bound_scope='conservative_horizon_range; refundable_deposit_not_certified_loss',
                economic_fee_cost_lower_lamports=str(low),
                economic_fee_cost_upper_lamports=str(high),
                cash_commitment_lower_lamports=(None if cash_commitment_lower is None
                                               else str(cash_commitment_lower)),
                cash_commitment_upper_lamports=(None if cash_commitment_upper is None
                                               else str(cash_commitment_upper)),
                cash_commitment_includes_temporary_deposit=True,
                ata_locked_at_horizon_lower_lamports=(None if locked_lower is None
                                                    else str(locked_lower)),
                ata_locked_at_horizon_upper_lamports=(None if locked_upper is None
                                                    else str(locked_upper)),
                ata_rent_locked_lamports=(None if ata_rent_locked_lamports is None
                                          else str(ata_rent_locked_lamports)),
                ata_recovered_at_horizon_hypothesis=ata_recovered_at_horizon,
                rent_nonrecoverable_upper_lamports=(None if rent_cost_upper is None
                                                  else str(rent_cost_upper)),
                rent_irrecoverability_observed=False,
                unrecovered_deposit_is_not_proven_irreversible_cost=True,
                all_applicable_costs_known=False,
                route_fees_already_in_quote_not_counted_twice=True,
                not_a_profitability_or_fill_certificate=True)
