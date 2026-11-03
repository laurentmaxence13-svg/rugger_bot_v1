"""Bounded no-key PUBLIC Solana LaunchLab signed forward PAPER observation.

One free rate-limited mainnet WebSocket window, at most 10 transaction
verification RPC calls + 5 bank calls. No Helius credits, wallet, keys,
transaction simulation or send. All results stay PAPER evidence/WAIT; native
curve prices are conditional, not independently executable BUY/SELL fills.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from bot.analyser.artifacts import atomic_write_json
from bot.live.helius_ws_forward_paper import (
    ReadOnlyLogAudit, subscribe_request, parse_subscription_ack)
from bot.live.helius_ws_signed_creation_probe import inspect_forward_creations
from bot.p3.signed_creation_forward_bank import signed_creator_asof_paper
from bot.live.readonly_plan import MAINNET_GENESIS

HTTP_RPC = "https://api.mainnet.solana.com"
WS_RPC = "wss://api.mainnet.solana.com"
SCHEMA = "rugger-public-solana-forward-signed-paper-v1"
MAX_RPC = 15
MAX_EVENTS = 100
MAX_BODY_BYTES = 1_500_000


def _refuse(code):
    raise ValueError(code)


def _sha(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class PublicReadOnlyRpc:
    """Restricted free public RPC, no secrets and hard upper call cap."""
    def __init__(self, key=None, *, max_calls=10, opener=urlopen):
        if key is not None or type(max_calls) is not int or not 1 <= max_calls <= 10:
            _refuse("public_rpc_requires_no_key_and_bounded_calls")
        self.count = 0
        self.max_calls = max_calls
        self.last_rpc_error_code = None
        self._opener = opener

    def __call__(self, method, params):
        if method == "getGenesisHash":
            valid = params == []
        elif method == "getTransaction":
            valid = (type(params) is list and len(params) == 2
                     and type(params[0]) is str
                     and 64 <= len(params[0]) <= 90
                     and type(params[1]) is dict
                     and params[1].get("commitment") == "finalized"
                     and params[1].get("encoding") in ("json", "base64")
                     and params[1].get("maxSupportedTransactionVersion") in (0, 1))
        elif method == "getMultipleAccounts":
            valid = (type(params) is list and len(params) == 2
                     and type(params[0]) is list and 1 <= len(params[0]) <= 21
                     and all(type(key) is str and 32 <= len(key) <= 44
                             for key in params[0])
                     and type(params[1]) is dict
                     and params[1].get("encoding") == "base64"
                     and params[1].get("commitment") == "confirmed"
                     and type(params[1].get("minContextSlot")) is int
                     and params[1]["minContextSlot"] > 0)
        else:
            valid = False
        if not valid:
            _refuse("non_readonly_or_malformed_public_rpc_refused")
        if self.count >= self.max_calls:
            _refuse("public_rpc_call_budget_exhausted")
        self.count += 1
        body = json.dumps(dict(jsonrpc="2.0",id=self.count,
            method=method,params=params),separators=(",", ":")).encode()
        request = Request(HTTP_RPC,data=body,method="POST",headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "RuggerNoKeySignedSourcePaper/1.0"})
        with self._opener(request,timeout=12) as response:
            if response.status != 200:
                _refuse("public_rpc_http_unavailable")
            raw = response.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            _refuse("public_rpc_reply_too_large")
        try:
            result = json.loads(raw)
        except (ValueError,UnicodeDecodeError):
            _refuse("public_rpc_invalid_json")
        if type(result) is dict and type(result.get("error")) is dict:
            code = result["error"].get("code")
            if type(code) is int:
                self.last_rpc_error_code = code
        if (type(result) is not dict or result.get("jsonrpc") != "2.0"
                or result.get("id") != self.count or "error" in result
                or "result" not in result):
            # Existing signed inspector uses this categorical receipt refusal.
            _refuse("helius_rpc_envelope_refused")
        return result["result"]


async def observe_public_window(*, seconds=75, socket_factory=None):
    if type(seconds) is not int or not 30 <= seconds <= 90:
        _refuse("bounded_public_observation_seconds_required")
    if socket_factory is None:
        from websockets.asyncio.client import connect
        socket_factory = connect
    start_ns = time.monotonic_ns()
    async with socket_factory(WS_RPC,open_timeout=10,close_timeout=3,
                              ping_interval=15,max_size=262144,
                              compression=None) as websocket:
        await websocket.send(json.dumps(subscribe_request(),separators=(",", ":")))
        sub = parse_subscription_ack(await asyncio.wait_for(websocket.recv(),timeout=8))
        handshake_ms = max(0,(time.monotonic_ns()-start_ns)//1_000_000)
        audit = ReadOnlyLogAudit(sub,MAX_EVENTS,successful_only=False)
        deadline = time.monotonic()+seconds
        while len(audit.events)<MAX_EVENTS:
            remaining = deadline-time.monotonic()
            if remaining<=0:
                break
            try:
                message = await asyncio.wait_for(websocket.recv(),
                                                  timeout=min(2,remaining))
            except asyncio.TimeoutError:
                continue
            received=time.monotonic_ns()
            audit.accept(message,received_mono_ns=received,
                         received_utc_ns=time.time_ns(),
                         parsed_mono_ns=time.monotonic_ns())
    report = audit.report(duration_ms=max(0,(time.monotonic_ns()-start_ns)//1_000_000),
                          handshake_ms=handshake_ms)
    report["transport"] = "SOLANA_PUBLIC_MAINNET_FREE_RATE_LIMITED_WEBSOCKET"
    report["source_is_not_helius_authenticated"] = True
    report["complete_market_tape_verified"] = False
    return report,audit.events


def run_one_public_paper_capture(*,seconds,output_dir,observer=observe_public_window,
                                 rpc_factory=PublicReadOnlyRpc,
                                 strategy=signed_creator_asof_paper):
    if type(seconds) is not int or not 30 <= seconds <= 90:
        _refuse("bounded_public_observation_seconds_required")
    folder = Path(output_dir)
    if folder.exists() or folder.is_symlink():
        _refuse("new_public_evidence_directory_required")
    folder.mkdir(parents=True,exist_ok=False)
    # Transport and source are explicitly PUBLIC, not authenticated Helius.
    report,events=asyncio.run(observer(seconds=seconds))
    if (type(report) is not dict or type(events) is not list
            or len(events)>MAX_EVENTS
            or report.get("financial_order_submitted") is not False):
        _refuse("unqualified_public_log_report")
    captured=dict(report=report,events=events)
    verifier_rpc=rpc_factory(None,max_calls=10)
    verified=inspect_forward_creations(report,events,verifier_rpc)
    bank_rpc=rpc_factory(None,max_calls=5)
    paired=strategy(captured,verified,bank_rpc)
    if (type(paired) is not dict
            or paired.get("financial_order_submitted") is not False
            or paired.get("execution_verified") is not False
            or paired.get("live_ready_to_arm") is not False
            or paired.get("master_net_pnl_lamports") is not None
            or paired.get("reference_net_pnl_lamports") is not None):
        _refuse("unqualified_paper_or_financial_claim")
    for name,doc in (("public_log_capture.json",captured),
                     ("finalized_creation_proof.json",verified),
                     ("paired_master_source_shadow.json",paired)):
        atomic_write_json(folder/name,doc,sort_keys=True,allow_nan=False)
    summary=dict(schema=SCHEMA,
        source="FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS",
        log_events=len(events),
        signed_creation_transactions=verified.get("signed_creation_candidate_transactions"),
        selected_independent_creators=paired.get("signed_creation_candidates_selected"),
        frozen_master_S1_decisions=sum(
            "frozen_decision_before_S2" in x for x in paired.get("observations",[])),
        native_sol_graphs=sum(type(x) is dict and type(x.get("graph")) is dict
            for x in paired.get("observations",[])),
        verification_rpc_calls=verifier_rpc.count,bank_rpc_calls=bank_rpc.count,
        max_rpc_requests=MAX_RPC,
        complete_market_tape_verified=False,
        independent_executable_quotes_verified=False,
        genuine_master_paper_buys=0,genuine_master_paper_sells=0,
        qualified_economic_cycles=0,master_net_pnl_lamports=None,
        original_master_policy_modified=False,
        financial_order_submitted=False,live_trading_enabled=False,
        artifact_sha256=dict(
            public_log_capture=_sha(captured),
            finalized_creation_proof=_sha(verified),
            paired_master_source_shadow=_sha(paired)))
    atomic_write_json(folder/"summary.json",summary,sort_keys=True,allow_nan=False)
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--seconds",type=int,default=75)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.network:
        print("PUBLIC_SIGNED_PAPER_REFUSED:NETWORK_OPT_IN_REQUIRED")
        return 2
    try:
        result=run_one_public_paper_capture(seconds=args.seconds,
                                            output_dir=args.output_dir)
    except Exception as error:
        print(json.dumps(dict(schema=SCHEMA,status="REFUSED",
              safe_error_class=type(error).__name__,
              financial_order_submitted=False),sort_keys=True))
        return 2
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
