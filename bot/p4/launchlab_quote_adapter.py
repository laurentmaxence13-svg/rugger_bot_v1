"""Strict LaunchLab source-bank => exact-lot PAPER quote envelope adapter.

The SDK arithmetic is backed by an already observed seven-account LaunchLab
bank, not an AMM Trade API lot and not an actual independently executable
provider quote. Fees on-chain are included in the model output once; other
costs must be separately supplied from authenticated cost evidence.

A missing on-chain verified source/fee cost prevents a PAPER fill. This module
does not send transactions, mock trades, infer future migration, or insert
hypothetical buy inventory into a later observed on-chain bank.
"""
from bot.p3.curve_size_grid import _s1_inputs,_u64
from bot.p3.launchlab import (
    SnapshotEvidenceError,constant_product_projection,observed_sell_projection)
from bot.p4.live_like_paper_ledger import source_quote


def _u64(value,name):
    if type(value) is not int or value<0 or value>=2**64:
        raise ValueError(name+"_invalid")
    return value


def asof_launchlab_quote(*,analysis,source_event,mint,pool,side,
                         amount_atomic,network_and_priority_fee_lamports=None,
                         account_creation_fee_lamports=None,
                         failed_attempt_fee_lamports=None):
    """Model quote with source-provenance and conservatively known extra costs."""
    if (type(analysis) is not dict or type(source_event) is not dict
            or type(mint) is not str or not mint or type(pool) is not str or not pool):
        raise ValueError("trusted_source_bank_required")
    if side not in ("BUY","SELL"):
        raise ValueError("model_quote_side_invalid")
    amount=_u64(amount_atomic,"amount_atomic")
    if not amount:
        raise ValueError("empty_quote_lot")
    fees=[network_and_priority_fee_lamports,account_creation_fee_lamports,
          failed_attempt_fee_lamports]
    if any(x is None for x in fees):
        raise ValueError("extra_source_network_fee_evidence_missing")
    for value in fees:_u64(value,"extra_fee_lamports")
    slot=source_event.get("source_slot")
    at=source_event.get("available_at_ms")
    digest=source_event.get("source_observation_sha256")
    if (type(slot) is not int or slot<=0 or analysis.get("context_slot")!=slot
            or type(at) is not int or at<=0
            or type(digest) is not str or len(digest)!=64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("causal_source_receipt_missing")
    inputs=_s1_inputs(analysis)
    source_pool=inputs["pool"]
    # Account decoding retains its original decimal-string status, whereas
    # the SDK sell primitive accepts a normalized numeric enum.
    status=int(source_pool.get("status")) if str(source_pool.get("status")).isdecimal() else None
    if source_pool.get("mint_a")!=mint or status!=0:
        raise ValueError("active_source_mint_and_curve_required")
    source_pool["status"]=status
    for key in ("protocol_fee_accrued","platform_fee_accrued"):
        raw=source_pool.get(key)
        if type(raw) is str and raw.isdecimal():
            raw=int(raw)
        value=_u64(raw,key)
        if value is None:
            raise ValueError("observed_curve_accrued_fee_invalid")
        source_pool[key]=value
    if side=="BUY":
        model=constant_product_projection(
            source_pool,input_lamports=amount,
            fee_rates_ppm=inputs["fee_rates_ppm"],
            base_vault_atomic=inputs["base_vault_atomic"],
            quote_vault_lamports=inputs["quote_vault_lamports"],
            share_fee_rate_ppm=inputs["share_fee_rate_ppm"])
        out=int(model["buy_output_atomic"])
    else:
        model=observed_sell_projection(
            source_pool,input_token_atomic=amount,
            fee_rates_ppm=inputs["fee_rates_ppm"],
            quote_vault_lamports=inputs["quote_vault_lamports"],
            curve_type=0,share_fee_rate_ppm=inputs["share_fee_rate_ppm"])
        out=int(model["output_lamports"])
    quote=dict(id=str(source_event.get("id",digest))+":"+side+":"+str(amount),
        mint=mint,pool=pool,venue="LAUNCHLAB_CURVE",side=side,
        input_atomic=amount,output_atomic=out,
        source_slot=slot,available_at_ms=at,
        source_produced_at_ms=at,
        source_observation_sha256=digest,
        provenance="OBSERVED_CHAIN_MODEL",
        network_and_priority_fee_lamports=network_and_priority_fee_lamports,
        account_creation_fee_lamports=account_creation_fee_lamports,
        failed_attempt_fee_lamports=failed_attempt_fee_lamports,
        migration_proof=None)
    source_quote(quote)
    return dict(
        paper_quote=quote,curve_model=model,
        onchain_price_quote_independently_executable=False,
        hypothetical_fill_not_actual=True,
        models_liquidity_in_observed_bank_only=True,
        unknown_future_price_or_route_not_imputed=True)
