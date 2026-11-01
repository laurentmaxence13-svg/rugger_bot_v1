"""Full-horizon, bounded Helius discovery before Master PAPER source verification.

Unlike taking the first 100 LaunchLab program notifications, this collector
samples eligible *public log hints* across the entire observation horizon (or
an explicit 4,000-notification cap). Selection happens before looking up any
finalized transactions, buy/sell quotes, or future outcomes.

It cannot sign, submit an order, derive a real wallet, or authorize LIVE.
A log hint is NEVER proof of a signed creation. Missing/gap data stay visible.
"""
import asyncio
import json
import re
import time

from bot.live.helius_ws_forward_paper import (
    ReadOnlyLogAudit, _ENDPOINT_HOST, _hash, _percentile,
    parse_subscription_ack, subscribe_request,
)

RAW_CAP = 4000
CHUNK_CAP = 200


def _spread(rows, take):
    """Deterministic whole-horizon strata, no post-outcome or price selection."""
    if type(take) is not int or take < 0:
        raise ValueError("invalid_spread_count")
    if not rows or take == 0:
        return []
    if len(rows) <= take:
        return list(rows)
    return [rows[(2*i+1)*len(rows)//(2*take)] for i in range(take)]


def select_horizon_events(all_events, maximum):
    """Pre-RPC selection prioritizes untrusted Initialize logs, then spans time.

    Retain at least half the places for general successful program logs when
    these exist: a genuine LaunchLab creation need not print Initialize.
    This is a *bounded research sample*, not a complete launch universe.
    """
    if (type(all_events) is not list or type(maximum) is not int
            or not 1 <= maximum <= 100 or len(all_events) > RAW_CAP):
        raise ValueError("bounded_horizon_source_required")
    seen = set()
    for event in all_events:
        if (type(event) is not dict or type(event.get("signature")) is not str
                or event["signature"] in seen
                or type(event.get("untrusted_initialize_log_hint")) is not bool
                or type(event.get("on_chain_transaction_failed")) is not bool):
            raise ValueError("deduplicated_log_evidence_required")
        seen.add(event["signature"])
    successful = [e for e in all_events if not e["on_chain_transaction_failed"]]
    hints = [e for e in successful if e["untrusted_initialize_log_hint"]]
    others = [e for e in successful if not e["untrusted_initialize_log_hint"]]
    hint_slots = min(len(hints), (maximum + 1)//2) if others else min(len(hints), maximum)
    selected = _spread(hints, hint_slots)
    selected += _spread(others, maximum-len(selected))
    if len(selected) < maximum:
        already = {e["signature"] for e in selected}
        selected += _spread([e for e in hints if e["signature"] not in already],
                            maximum-len(selected))
    selected.sort(key=lambda e:(e["reception_monotonic_ns"], e["signature"]))
    if len(selected) != len({e["signature"] for e in selected}):
        raise ValueError("horizon_sample_duplicate")
    return selected


def capture_report(selected, all_events, *, handshake_ms, duration_ms,
                   raw_cap_reached, subscription, duplicates, invalid):
    """Hash exactly what the downstream finalized-signature verifier receives."""
    if (type(duration_ms) is not int or duration_ms < 0
            or type(handshake_ms) is not int or handshake_ms < 0):
        raise ValueError("invalid_horizon_timing")
    maximum=max(1,min(200,len(selected)))
    report=ReadOnlyLogAudit(subscription,maximum).report(
        duration_ms=duration_ms,handshake_ms=handshake_ms)
    chain="0"*64
    for event in selected:
        chain=_hash(dict(previous=chain,event=event))
    failed=sum(bool(e["on_chain_transaction_failed"]) for e in all_events)
    report.update(
        status="LOGS_OBSERVED" if selected else "NO_LOGS_OBSERVED",
        events_received_unique=len(selected),
        signature_ledger_sha256=chain,
        scoped_launchlab_initialize_observations=sum(
            bool(e["untrusted_initialize_log_hint"]) for e in selected),
        legacy_initialize_prefix_observations=sum(
            bool(e["untrusted_legacy_initialize_prefix_hint"]) for e in selected),
        launchlab_invocation_trace_observations=sum(
            bool(e["untrusted_launchlab_invocation_trace_present"]) for e in selected),
        retention_policy="whole_horizon_pre_RPC_stratified_hint_and_nonhint_sample",
        unique_valid_notifications_seen=len(all_events),
        onchain_failed_transactions_in_notifications=failed,
        discarded_failed_notifications=failed,
        unretained_successful_notifications=(
            len(all_events)-failed-len(selected)),
        duplicates_ignored=duplicates,
        invalid_notifications=invalid,
        bounded_raw_notification_cap=RAW_CAP,
        raw_cap_reached=raw_cap_reached,
        retention_hit_100_before_horizon=False,
        captured_raw_unique_notifications=len(all_events),
        sampled_successful_hints=sum(
            bool(e["untrusted_initialize_log_hint"]) for e in selected),
        unretained_successful_hint_count=sum(
            bool(e["untrusted_initialize_log_hint"])
            and not e["on_chain_transaction_failed"] for e in all_events)
            -sum(bool(e["untrusted_initialize_log_hint"]) for e in selected),
        whole_horizon_sample_not_complete_creation_universe=True,
        source_signed_creator_cryptography_checked_only_after_sample=True,
        no_orders=True, financial_order_submitted=False,
        local_parse_p50_ms=_percentile([
            e["local_parse_elapsed_ns"] for e in selected],50),
        local_parse_p95_ms=_percentile([
            e["local_parse_elapsed_ns"] for e in selected],95),
        local_parse_p99_ms=_percentile([
            e["local_parse_elapsed_ns"] for e in selected],99),
    )
    return report


async def observe_horizon(seconds, maximum, api_key, *, successful_only=False):
    """Sample 10-45 seconds of real Helius data, never stop at first 100 logs.

    The only intentional early stop is the explicit RAW_CAP; gaps are not
    backfilled or declared complete. No RPC lookups happen during capture.
    """
    from websockets.asyncio.client import connect
    if (type(seconds) is not int or not 10 <= seconds <= 45
            or type(maximum) is not int or not 1 <= maximum <= 100
            or successful_only is not False
            or type(api_key) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{16,160}",api_key) is None):
        raise ValueError("bounded_readonly_horizon_required")
    started=time.monotonic_ns()
    endpoint="wss://"+_ENDPOINT_HOST+"/?api-key="+api_key
    async with connect(endpoint,open_timeout=10,close_timeout=3,
                       ping_interval=15,max_size=262144,compression=None) as socket:
        await socket.send(json.dumps(subscribe_request(),separators=(",",":")))
        ack=await asyncio.wait_for(socket.recv(),timeout=8)
        subscription=parse_subscription_ack(ack)
        handshake=max(0,(time.monotonic_ns()-started)//1_000_000)
        deadline=time.monotonic_ns()+seconds*1_000_000_000
        seen=set()
        raw=[]
        invalid=duplicates=0
        audit=ReadOnlyLogAudit(subscription,CHUNK_CAP,successful_only=False)
        while len(raw)<RAW_CAP:
            remaining=(deadline-time.monotonic_ns())/1_000_000_000
            if remaining<=0:break
            try:
                message=await asyncio.wait_for(socket.recv(),timeout=min(5,remaining))
            except asyncio.TimeoutError:
                continue
            if len(audit.events)>=CHUNK_CAP:
                audit=ReadOnlyLogAudit(subscription,CHUNK_CAP,successful_only=False)
            received_mono=time.monotonic_ns()
            retained=audit.accept(message,received_mono_ns=received_mono,
                                  received_utc_ns=time.time_ns(),
                                  parsed_mono_ns=time.monotonic_ns())
            if not retained:
                invalid+=audit.invalid
                audit.invalid=0
                duplicates+=audit.duplicates
                audit.duplicates=0
                continue
            event=dict(audit.events[-1])
            if event["signature"] in seen:
                duplicates+=1
                continue
            seen.add(event["signature"])
            raw.append(event)
    selected=select_horizon_events(raw,maximum)
    report=capture_report(selected,raw,subscription=subscription,
        handshake_ms=handshake,
        duration_ms=max(0,(time.monotonic_ns()-started)//1_000_000),
        raw_cap_reached=len(raw)>=RAW_CAP,
        duplicates=duplicates+audit.duplicates,
        invalid=invalid+audit.invalid)
    return report,selected
