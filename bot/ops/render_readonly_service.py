"""Render-compatible health/status plus opt-in Helius Master PAPER observer.

This service never imports or instantiates the live trading executor, signer
or any wallet. All optional network calls are bounded PUBLIC read-only Helius
captures. Financial execution cannot be activated by an environment variable.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import tempfile
import threading
import time

SCHEMA = "rugger-render-observer-status-v1"
ALLOWED_ORIGIN = "https://rugger-wallet-master.vercel.app"
ALLOWED_SUMMARY = frozenset((
    "capture_status", "log_events_retained", "crypto_signed_creation_transactions",
    "selected_independent_signed_creators", "supported_native_SOL_graphs",
    "frozen_S1_decisions", "actual_signed_policy_frozen_paper_cases",
    "actual_verification_rpc_calls_used", "actual_bank_rpc_calls_used",
    "trade_fills_simulated", "qualified_economic_cycles", "financial_order_submitted",
    "execution_verified", "live_ready_to_arm", "exact_profitability_demonstrated",
    "paper_portfolio_open_positions", "paper_portfolio_closed_positions",
))


def parse_settings(env):
    enabled = env.get("RUGGER_OBSERVATION_ENABLED", "0")
    interval = env.get("RUGGER_INTERVAL_SECONDS", "300")
    seconds = env.get("RUGGER_CAPTURE_SECONDS", "30")
    if enabled not in ("0", "1"):
        raise ValueError("observation_flag_must_be_0_or_1")
    if not re.fullmatch(r"[0-9]{1,4}", interval or "") or not re.fullmatch(r"[0-9]{1,2}", seconds or ""):
        raise ValueError("invalid_observation_interval")
    interval, seconds = int(interval), int(seconds)
    if not 180 <= interval <= 3600 or not 10 <= seconds <= 45:
        raise ValueError("observation_budget_out_of_bounds")
    return dict(enabled=enabled == "1", interval_seconds=interval,
                capture_seconds=seconds)


class Observer:
    def __init__(self, *, env=None, runner=None, clock=None):
        self._env = os.environ if env is None else env
        self.settings = parse_settings(self._env)
        self._runner = runner
        self._clock = clock if clock is not None else time.time
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._worker = None
        self._state = dict(
            schema=SCHEMA, mode="READ_ONLY_MASTER_PAPER_EVIDENCE",
            live_trading_enabled=False, wallet_connected=False,
            no_signing_or_order_submission=True,
            is_24_7_guaranteed=False,
            historical_or_live_trade_fill_confirmed=False,
            observer_status="STARTING", started_at_utc_ms=int(self._clock()*1000),
            last_started_at_utc_ms=None, last_completed_at_utc_ms=None,
            cycle_count=0, last_safe_error_class=None, last_summary=None,
        )
        self._update_status()

    def _update_status(self):
        if not self.settings["enabled"]:
            status = "DISABLED_EXPLICITLY"
        elif not self._env.get("HELIUS_API_KEY"):
            status = "WAITING_FOR_HELIUS_API_KEY"
        else:
            status = "READY_TO_CAPTURE"
        with self._lock:
            self._state["observer_status"] = status

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._state, sort_keys=True, allow_nan=False))

    def capture_once(self):
        self._update_status()
        if not self.settings["enabled"] or not self._env.get("HELIUS_API_KEY"):
            return False
        with self._lock:
            self._state["observer_status"] = "CAPTURING_HELIUS_READ_ONLY"
            self._state["last_started_at_utc_ms"] = int(self._clock()*1000)
        try:
            if self._runner is None:
                from bot.live.helius_signed_master_paper import run_pipeline
                run = run_pipeline
            else:
                run = self._runner
            with tempfile.TemporaryDirectory(prefix="rugger-helius-") as folder:
                output = Path(folder)/"capture"
                result = run(seconds=self.settings["capture_seconds"],
                             output_dir=output, api_key=self._env["HELIUS_API_KEY"])
            if type(result) is not dict:
                raise ValueError("observer_result_must_be_mapping")
            if (result.get("financial_order_submitted") is not False
                    or result.get("live_ready_to_arm") is not False
                    or result.get("execution_verified") is not False
                    or result.get("trade_fills_simulated") != 0):
                raise ValueError("unexpected_financial_claim_in_paper_observer")
            sanitized = {key: result[key] for key in ALLOWED_SUMMARY if key in result}
            with self._lock:
                self._state["observer_status"] = "CAPTURE_COMPLETED_READ_ONLY"
                self._state["cycle_count"] += 1
                self._state["last_completed_at_utc_ms"] = int(self._clock()*1000)
                self._state["last_summary"] = sanitized
                self._state["last_safe_error_class"] = None
            return True
        except Exception as error:
            # Exception text may include a key-bearing RPC URL: never print it.
            with self._lock:
                self._state["observer_status"] = "CAPTURE_REFUSED"
                self._state["cycle_count"] += 1
                self._state["last_completed_at_utc_ms"] = int(self._clock()*1000)
                self._state["last_safe_error_class"] = type(error).__name__
                self._state["last_summary"] = None
            return False

    def _loop(self):
        while not self._stopped.is_set():
            self.capture_once()
            if self._stopped.wait(self.settings["interval_seconds"]):
                break

    def start(self):
        if self._worker is not None:
            raise RuntimeError("single_observer_only")
        self._worker = threading.Thread(
            target=self._loop, name="helius-paper-readonly", daemon=True)
        self._worker.start()

    def stop(self):
        self._stopped.set()
        if self._worker is not None:
            self._worker.join(timeout=2)


def handler_factory(observer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RuggerPaperReadOnly/1"
        sys_version = ""

        def do_GET(self):
            if self.path in ("/health", "/healthz"):
                payload = dict(status="ok", schema=SCHEMA,
                               financial_orders_enabled=False)
            elif self.path in ("/api/status", "/api/v1/status"):
                payload = observer.snapshot()
            else:
                self.send_error(404)
                return
            data = json.dumps(payload,separators=(",",":"),allow_nan=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Content-Length",str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            # No API credentials, untrusted request paths or headers in logs.
            return
    return Handler


def main():
    os.environ["RUGGER_NO_DOTENV"] = "1"
    os.environ["RUGGER_LIVE_ENABLED"] = "0"
    observer = Observer()
    raw_port = os.environ.get("PORT", "10000")
    if not re.fullmatch(r"[0-9]{2,5}", raw_port):
        raise ValueError("invalid_render_port")
    server = ThreadingHTTPServer(("0.0.0.0",int(raw_port)),
                                 handler_factory(observer))
    observer.start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        observer.stop()
        server.server_close()


if __name__ == "__main__":
    main()
