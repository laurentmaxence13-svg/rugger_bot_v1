"""Fail-closed, quote-only screen for a proposed PAPER inventory.

This is an *initial*, full-size Raydium route check, not a fill, a sale,
an execution guarantee, a liquidity-reserve measurement, or a P&L.
Only observations available during the initial phase are usable; later
follow-ups and smaller diagnostic sales must never retroactively admit entries.
"""
import re

from bot.p3.quotes import SOL_MINT


def _positive_atomic(value):
    if type(value) is str and re.fullmatch(r"[0-9]{1,40}", value):
        value = int(value)
    return value if type(value) is int and value > 0 else None


def initial_full_exit_liquidity_screen(*, mint, acquired_atomic,
                                      buy_observation_id, sell_event):
    """Evaluate one linked full-inventory sell quote; fail closed on missing data.

    The result deliberately never marks an entry as executed or economically
    admitted. A quoteable route is only one prerequisite of a later PAPER gate.
    """
    acquired = _positive_atomic(acquired_atomic)
    if not isinstance(mint, str) or not mint or acquired is None or (
            type(buy_observation_id) is not int or buy_observation_id < 1):
        raise ValueError("Invalid immutable projected inventory identity")
    result = dict(
        schema="p3-initial-full-exit-liquidity-screen-v1",
        buy_observation_id=buy_observation_id,
        acquired_atomic=str(acquired),
        full_sell_observation_id=None,
        initial_full_exit_route_quoted=False,
        rejection_code=None,
        reason="initial_full_sell_not_observed",
        quote_only=True,
        exit_execution_verified=False,
        position_acquired=False,
        paper_entry_admitted=False,
        net_pnl_lamports=None,
    )
    if sell_event is None:
        return result
    if type(sell_event) is not dict:
        result["reason"] = "invalid_full_sell_observation"
        return result
    payload = sell_event.get("payload")
    if (type(payload) is not dict
            or sell_event.get("kind") != "quote_attempt"
            or sell_event.get("mint") != mint
            or payload.get("probe_phase") != "initial"
            or payload.get("exit_scope") != "full_expected"
            or payload.get("quote_side") != "sell"
            or payload.get("inventory_buy_observation_id") != buy_observation_id
            or payload.get("input_mint") != mint
            or payload.get("output_mint") != SOL_MINT
            or _positive_atomic(payload.get("input_amount_atomic")) != acquired):
        result["reason"] = "invalid_full_sell_observation"
        return result
    quote_id = sell_event.get("id")
    if type(quote_id) is not int or quote_id < 1:
        result["reason"] = "invalid_full_sell_observation"
        return result
    result["full_sell_observation_id"] = quote_id
    if sell_event.get("outcome") != "quoted":
        raw = payload.get("retained_sanitized_response")
        code = raw.get("msg") if type(raw) is dict else None
        if (type(code) is str and re.fullmatch(r"[A-Z0-9_]{1,100}", code)):
            result["rejection_code"] = code
        result["reason"] = "full_exit_quote_unavailable"
        return result
    if (payload.get("http_status") != 200
            or _positive_atomic(payload.get("output_amount_atomic")) is None
            or _positive_atomic(payload.get("min_output_amount_atomic")) is None
            or _positive_atomic(payload.get("min_output_amount_atomic"))
                    > _positive_atomic(payload.get("output_amount_atomic"))
            or type(payload.get("route")) is not list or not payload["route"]):
        result["reason"] = "full_exit_quote_unqualified"
        return result
    result["initial_full_exit_route_quoted"] = True
    result["reason"] = "full_size_route_quoted_not_executed"
    return result


def recorded_initial_full_exit_route_passed(screen):
    """Only a recorded initial full-size quote passes this *route* prerequisite.

    This must never be interpreted as PAPER entry admission or an executed sale.
    """
    return (type(screen) is dict
            and screen.get("gate_recorded") is True
            and screen.get("initial_full_exit_route_quoted") is True
            and screen.get("quote_only") is True
            and screen.get("paper_entry_admitted") is False
            and screen.get("exit_execution_verified") is False)
