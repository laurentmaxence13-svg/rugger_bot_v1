"""Causal signed-creator native SOL signals and fail-closed scorer bridge.

Never invent USD prices, verified prior-creator history, transaction
wallet profiles or holder counts from a LaunchLab reserve bank.
Native SOL spot/funding is derived only from a pinned seven-account S1 bank.
A full SignalFeatures frame requires independently certified SOL/USD evidence,
verified source transaction receipts and a bounded history audit.
Unknowns stay unknown; Master WAIT is an authentic admission result.
"""
import math
from fractions import Fraction

from bot.analyser.final_decision_engine import build_features
from bot.p3.curve_size_grid import _s1_inputs


def native_asof_bank(*,analysis,mint,creator,pool,source_slot,available_at_ms):
    if (type(analysis) is not dict or type(mint) is not str or not mint
            or type(creator) is not str or not creator
            or type(pool) is not str or not pool
            or type(source_slot) is not int or source_slot<=0
            or type(available_at_ms) is not int or available_at_ms<=0
            or analysis.get("context_slot")!=source_slot):
        raise ValueError("causal_signed_creation_bank_required")
    # The analyzer correctly preserves three NON-TRADING unknowns even on a
    # safe, source-qualified bank: no onchain order, unknown network costs,
    # and creation unverified BY THE SNAPSHOT (the outer signed receipt was
    # separately checked). These do not invalidate the observed SOL curve
    # reserves. Any unrecognized security/identity blocker still refuses.
    non_trade_unknowns={
        "execution_not_verified",
        "additional_execution_costs_unknown",
        "creation_transaction_not_verified_by_snapshot",
    }
    blockers=analysis.get("blocking_reasons")
    if (type(analysis.get("risk_flags")) is not list
            or analysis["risk_flags"]
            or type(blockers) is not list
            or any(type(x) is not str or x not in non_trade_unknowns
                   for x in blockers)):
        raise ValueError("unqualified_source_curve_bank_flags")
    facts=_s1_inputs(analysis)
    bank=facts["pool"]
    if bank.get("mint_a")!=mint:
        raise ValueError("source_mint_identity_mismatch")
    x=bank["virtual_a"]-bank["real_a"]
    y=bank["virtual_b"]+bank["real_b"]
    if x<=0 or y<=0:
        raise ValueError("invalid_native_sol_curve_price")
    decimal=bank.get("decimals_a")
    if type(decimal) is not int or not 0<=decimal<=18:
        raise ValueError("source_base_decimals_required")
    spot=Fraction(y*10**decimal,x*1_000_000_000)
    funding=Fraction(bank["real_b"],1_000_000_000)
    return dict(schema="rugger-native-signed-asof-curve-signal-v1",
        mint=mint,pool=pool,creator=creator,
        source_slot=source_slot,available_at_ms=available_at_ms,
        spot_sol_per_token_fraction=dict(numerator=str(spot.numerator),
                                         denominator=str(spot.denominator)),
        funding_sol_fraction=dict(numerator=str(funding.numerator),
                                  denominator=str(funding.denominator)),
        price_usd=None,liquidity_usd=None,sol_usd_proof_missing=True,
        historical_creator_behavior_unknown=True,
        independent_buyers_unknown=True,verified_holder_concentration_unknown=True,
        complete_SignalFeatures_available=False,
        source_price_is_curve_model_not_executable_quote=True,
        source_native_facts_observed=True,
        financial_order_submitted=False)


class NativeQuote:
    def __init__(self,*,price_usd,liquidity_usd):
        self.price_usd=price_usd
        self.liquidity_usd=liquidity_usd
        self.quote_source="launchlab_curve"
        self.funding_usd=liquidity_usd

    def __iter__(self):
        return iter((self.liquidity_usd,self.price_usd,None))


def verified_full_asof_features(*,native,creation,sol_usd,creator_history,
                                verified_transactions,market_price_history,
                                decision_at_ms):
    """Return a fully typed scorer input or explicit missing reasons.

    Each claimed source proof must be independently validated upstream;
    boolean source claims alone do not perform cryptographic verification.
    """
    failures=[]
    if (type(native) is not dict
            or native.get("schema")!="rugger-native-signed-asof-curve-signal-v1"
            or native.get("source_native_facts_observed") is not True):
        raise ValueError("native_source_bank_required")
    if type(decision_at_ms) is not int or decision_at_ms<native["available_at_ms"]:
        raise ValueError("decision_must_follow_native_bank")
    if (type(creation) is not dict
            or creation.get("mint")!=native["mint"]
            or creation.get("pool")!=native["pool"]
            or creation.get("creator")!=native["creator"]
            or creation.get("cryptographic_creation") is not True
            or type(creation.get("verified_at_ms")) is not int
            or creation["verified_at_ms"]>decision_at_ms):
        failures.append("signed_creator_finalized_proof_not_available_asof")
    if (type(sol_usd) is not dict
            or sol_usd.get("source")!="certified_onchain_SOL_USD_oracle"
            or sol_usd.get("source_chain_verified") is not True
            or type(sol_usd.get("available_at_ms")) is not int
            or not 0<=decision_at_ms-sol_usd["available_at_ms"]<=5000
            or type(sol_usd.get("value")) not in (int,float)
            or not math.isfinite(sol_usd["value"])
            or sol_usd["value"]<=0):
        failures.append("fresh_verified_SOL_USD_oracle_missing")
    if (type(creator_history) is not dict
            or creator_history.get("creator")!=native["creator"]
            or creator_history.get("complete_prior_creation_coverage") is not True
            or type(creator_history.get("prior_launches")) is not int
            or creator_history["prior_launches"]<0
            or type(creator_history.get("available_at_ms")) is not int
            or creator_history["available_at_ms"]>decision_at_ms):
        failures.append("full_prior_signed_creator_history_unavailable")
    verified_rows=[]
    if type(verified_transactions) is not list:
        failures.append("historical_signed_transaction_receipts_missing")
    else:
        for row in verified_transactions:
            if (type(row) is not dict
                    or type(row.get("timestamp_sec")) is not int
                    or row["timestamp_sec"]*1000>decision_at_ms
                    or type(row.get("available_at_ms")) is not int
                    or row["available_at_ms"]>decision_at_ms
                    or type(row.get("source_slot")) is not int
                    or row["source_slot"]>native["source_slot"]
                    or row.get("signed_receipt_verified") is not True
                    or type(row.get("transaction")) is not dict
                    or type(row.get("signature")) is not str):
                failures.append("unverified_or_future_transaction_in_feature_tape")
                break
            verified_rows.append((row["timestamp_sec"],row["signature"],row["transaction"]))
    price_rows=[]
    if type(market_price_history) is not list:
        failures.append("historical_source_price_series_missing")
    else:
        for row in market_price_history:
            if (type(row) is not dict or type(row.get("observed_at_sec")) is not int
                    or row["observed_at_sec"]*1000>decision_at_ms
                    or type(row.get("available_at_ms")) is not int
                    or row["available_at_ms"]>decision_at_ms
                    or type(row.get("price_usd")) not in (int,float)
                    or not math.isfinite(row["price_usd"]) or row["price_usd"]<=0
                    or type(row.get("liquidity_usd")) not in (int,float)
                    or not math.isfinite(row["liquidity_usd"]) or row["liquidity_usd"]<0):
                failures.append("unverified_or_future_price_history")
                break
            price_rows.append((row["observed_at_sec"],row["price_usd"],row["liquidity_usd"]))
    if failures:
        return dict(status="INSUFFICIENT_CAUSAL_FEATURE_EVIDENCE",
                    missing=sorted(set(failures)),features=None,
                    eligible_for_actual_master_entry=False)
    native_price=native["spot_sol_per_token_fraction"]
    native_funding=native["funding_sol_fraction"]
    spot=float(Fraction(int(native_price["numerator"]),int(native_price["denominator"]))*
               sol_usd["value"])
    funding=float(Fraction(int(native_funding["numerator"]),int(native_funding["denominator"]))*
                  sol_usd["value"])
    if not all(math.isfinite(x) and x>0 for x in (spot,funding)):
        raise ValueError("unrepresentable_positive_USD_market_quote")
    observed_sec=decision_at_ms//1000
    features=build_features(verified_rows,native["mint"],native["creator"],
        creation["detected_at_ms"]//1000,observed_sec,
        price_rows,NativeQuote(price_usd=spot,liquidity_usd=funding),
        prior_launches=creator_history["prior_launches"])
    if features.observed_at*1000>decision_at_ms:
        raise ValueError("features_were_computed_in_future")
    return dict(status="COMPLETE_TYPED_ASOF_FEATURES",
        features=features.to_dict(),available_at_ms=decision_at_ms,
        native_source_slot=native["source_slot"],
        verified_creator=True,sol_usd_observation_is_externally_certified=True,
        still_requires_master_health_capital_fee_and_past_edge_gates=True,
        order_submitted=False)
