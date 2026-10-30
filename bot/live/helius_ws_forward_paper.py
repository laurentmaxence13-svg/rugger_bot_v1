"""Bounded Helius mainnet LaunchLab log stream; NO orders or trade claims.

A logsSubscribe notification is *not* necessarily a token creation. The local
monotonic observation clocks quantify receiver/processing overhead, NOT Solana
event-to-client latency, confirmation latency, execution or profitability.
No wallet, signing, payment or RPC transaction submission exists in this file.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from bot.p3.certification import PROGRAM

_BASE58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
_ENDPOINT_HOST = "mainnet.helius-rpc.com"


def subscribe_request():
    return {"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
            "params": [{"mentions": [PROGRAM]}, {"commitment": "confirmed"}]}


def parse_subscription_ack(message):
    value = json.loads(message) if type(message) is str else message
    if (type(value) is not dict or value.get("jsonrpc") != "2.0"
            or type(value.get("id")) is not int or value["id"] != 1
            or type(value.get("result")) is not int or value["result"] < 0
            or "error" in value):
        raise ValueError("logs_subscription_ack_invalid")
    return value["result"]


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _percentile(values, percent):
    if not values:
        return None
    ranked = sorted(values)
    index = (len(ranked) - 1) * percent // 100
    return round(ranked[index] / 1_000_000, 4)


class ReadOnlyLogAudit:
    """Bounded, deterministic parser; signature IDs are public, not wallets."""
    def __init__(self, subscription, maximum):
        if type(subscription) is not int or subscription < 0:
            raise ValueError("invalid_subscription")
        if type(maximum) is not int or not 1 <= maximum <= 200:
            raise ValueError("invalid_event_cap")
        self.subscription = subscription
        self.maximum = maximum
        self.events = []
        self.seen = set()
        self.duplicates = 0
        self.invalid = 0
        self.failed_on_chain = 0
        self.processing_ns = []
        self.chain = "0" * 64
        self.last_receiver_mono_ns = None
        self.first_receiver_mono_ns = None

    def accept(self, message, *, received_mono_ns, received_utc_ns,
               parsed_mono_ns):
        if (any(type(v) is not int or v < 0 for v in
                (received_mono_ns, received_utc_ns, parsed_mono_ns))
                or parsed_mono_ns < received_mono_ns):
            raise ValueError("invalid_local_clock_order")
        try:
            value = json.loads(message) if type(message) is str else message
            if (type(value) is not dict or value.get("method") != "logsNotification"
                    or type(value.get("params")) is not dict
                    or value["params"].get("subscription") != self.subscription):
                raise ValueError()
            result = value["params"]["result"]
            slot = result["context"]["slot"]
            tx = result["value"]
            signature = tx["signature"]
            if (type(slot) is not int or slot <= 0
                    or type(signature) is not str
                    or not 64 <= len(signature) <= 90
                    or any(c not in _BASE58 for c in signature)
                    or "err" not in tx
                    or type(tx.get("logs")) is not list
                    or len(tx["logs"]) > 2000):
                raise ValueError()
        except (ValueError, TypeError, KeyError, IndexError):
            self.invalid += 1
            return False
        if signature in self.seen:
            self.duplicates += 1
            return False
        if len(self.events) >= self.maximum:
            raise ValueError("bounded_event_cap_reached")
        self.seen.add(signature)
        event = dict(signature=signature, slot=slot,
                     on_chain_transaction_failed=tx["err"] is not None,
                     reception_utc_ns=received_utc_ns,
                     reception_monotonic_ns=received_mono_ns,
                     local_parse_elapsed_ns=None,
                     classification="UNCLASSIFIED_PROGRAM_LOG_NOT_LAUNCH_PROOF",
                     filled=False)
        event["local_parse_elapsed_ns"] = max(0, time.monotonic_ns()-received_mono_ns)
        self.events.append(event)
        self.chain = _hash(dict(previous=self.chain, event=event))
        self.processing_ns.append(event['local_parse_elapsed_ns'])
        self.failed_on_chain += int(event["on_chain_transaction_failed"])
        if self.first_receiver_mono_ns is None:
            self.first_receiver_mono_ns = received_mono_ns
        self.last_receiver_mono_ns = received_mono_ns
        return True

    def report(self, *, duration_ms, handshake_ms):
        if type(duration_ms) is not int or duration_ms < 0:
            raise ValueError("invalid_probe_duration")
        return dict(
            schema="rugger-helius-program-log-forward-paper-v1",
            status="LOGS_OBSERVED" if self.events else "NO_LOGS_OBSERVED",
            source_program=PROGRAM, source_commitment="confirmed",
            observation_scope="program_logs_not_verified_new_token_creations",
            events_received_unique=len(self.events),
            duplicates_ignored=self.duplicates, invalid_notifications=self.invalid,
            onchain_failed_transactions_in_notifications=self.failed_on_chain,
            signature_ledger_sha256=self.chain,
            stream_wall_duration_ms=duration_ms,
            websocket_handshake_ms=handshake_ms,
            local_parse_p50_ms=_percentile(self.processing_ns, 50),
            local_parse_p95_ms=_percentile(self.processing_ns, 95),
            local_parse_p99_ms=_percentile(self.processing_ns, 99),
            chain_event_to_reception_latency_ms=None,
            decision_to_execution_latency_ms=None,
            economically_qualified_cycles=0,
            independent_verified_creators=0,
            capital_sol_traded=0, financial_order_submitted=False,
            execution_verified=False, live_ready_to_arm=False,
            master_edge_validated=False,
            limitations=["No transaction parsing/creation classification",
                         "No websocket-gap or backfill completeness proof",
                         "Local parse duration is not chain-to-client latency",
                         "No hypothetical BUY/SELL fill or PnL"])


async def observe(seconds, maximum, api_key):
    """One bounded subscription, public message only, no secret emitted."""
    from websockets.asyncio.client import connect
    if type(seconds) is not int or not 10 <= seconds <= 60:
        raise ValueError("invalid_duration")
    if type(maximum) is not int or not 1 <= maximum <= 200:
        raise ValueError("invalid_maximum")
    if type(api_key) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{10,256}", api_key):
        raise ValueError("invalid_provider_secret")
    # Fixed official host; secret never printed or embedded in reports.
    endpoint = "wss://" + _ENDPOINT_HOST + "/?api-key=" + api_key
    start = time.monotonic_ns()
    async with connect(endpoint, open_timeout=10, close_timeout=3,
                       ping_interval=15, max_size=262144,
                       compression=None) as socket:
        await socket.send(json.dumps(subscribe_request(), separators=(",", ":")))
        ack = await asyncio.wait_for(socket.recv(), timeout=8)
        subscription = parse_subscription_ack(ack)
        handshake = max(0, (time.monotonic_ns()-start)//1_000_000)
        audit = ReadOnlyLogAudit(subscription, maximum)
        deadline = time.monotonic_ns() + seconds*1_000_000_000
        while len(audit.events) < maximum:
            remaining = (deadline-time.monotonic_ns())/1_000_000_000
            if remaining <= 0:
                break
            try:
                message = await asyncio.wait_for(socket.recv(),
                                                 timeout=min(5, remaining))
            except asyncio.TimeoutError:
                continue
            received_mono_ns = time.monotonic_ns()
            received_utc_ns = time.time_ns()
            audit.accept(message, received_mono_ns=received_mono_ns,
                         received_utc_ns=received_utc_ns,
                         parsed_mono_ns=time.monotonic_ns())
    return audit.report(duration_ms=(time.monotonic_ns()-start)//1_000_000,
                        handshake_ms=handshake), audit.events


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=25)
    parser.add_argument("--max-events", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        report, events = asyncio.run(observe(
            args.seconds, args.max_events, os.environ.get("HELIUS_API_KEY")))
        # Persist bounded public IDs and timestamps, never provider credentials.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
            target = root / "paper_artifacts" / "paper_helius_log_stream.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.resolve().is_relative_to(root):
                raise ValueError("artifact_path_refused")
            target.write_text(json.dumps(dict(report=report, events=events),
                                         sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as error:
        # Error text may contain an authenticated URL: NEVER output it.
        print(json.dumps(dict(schema="rugger-helius-program-log-forward-paper-v1",
            status="REFUSED", safe_error_class=type(error).__name__,
            financial_order_submitted=False, live_ready_to_arm=False,
            master_edge_validated=False)))
        return 2


if __name__ == "__main__":
    sys.exit(main())
