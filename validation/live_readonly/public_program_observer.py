"""Public-mainnet code observation ONLY (not independent code approval).

Exactly five Solana JSON-RPC reads: genesis and two same-bank account
observations per program. No wallet address, private key, transaction, quote,
signature, submission, retry, alternate RPC or mutable mainnet trade mode.

The observed hashes are unapproved claims from ONE public RPC. They cannot
be used as the external program pins required by the financial preflight.
"""
import json
import ssl
import sys
import time
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler

from bot.p3.certification import PROGRAM
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.readonly_plan import MAINNET_GENESIS, PUBLIC_MAINNET_RPC
from bot.live.program_pin import _raw, _programdata_address, _details


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("public_rpc_redirect_forbidden")


class PublicReadOnlyRpc:
    def __init__(self):
        self.count = 0
        self.started = time.monotonic()
        self.opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
            NoRedirect())

    def __call__(self, method, params):
        if method not in ("getGenesisHash", "getMultipleAccounts"):
            raise ValueError("public_observer_read_methods_only")
        if self.count >= 5 or time.monotonic() - self.started > 50:
            raise ValueError("public_observer_budget_exceeded")
        self.count += 1
        body = json.dumps(dict(jsonrpc="2.0", id=self.count,
            method=method, params=params), separators=(",", ":")).encode("utf-8")
        request = Request(PUBLIC_MAINNET_RPC, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with self.opener.open(request, timeout=8) as response:
            if response.status != 200 or response.geturl() != PUBLIC_MAINNET_RPC:
                raise ValueError("unexpected_public_rpc_http_response")
            raw = response.read(6_000_001)
            if len(raw) > 6_000_000:
                raise ValueError("public_rpc_body_too_large")
        reply = json.loads(raw)
        if (type(reply) is not dict or reply.get("jsonrpc") != "2.0"
                or type(reply.get("id")) is not int
                or reply["id"] != self.count or "error" in reply
                or "result" not in reply):
            raise ValueError("invalid_public_rpc_reply")
        return reply["result"]


def _bank(reply, expected_count, minimum_slot):
    if type(reply) is not dict:
        raise ValueError("public_program_bank_missing")
    context = reply.get("context")
    slot = context.get("slot") if type(context) is dict else None
    values = reply.get("value")
    if (type(slot) is not int or slot < minimum_slot
            or type(values) is not list or len(values) != expected_count):
        raise ValueError("public_program_bank_incoherent")
    return slot, values


def observe_public_programs(rpc):
    """Pure financial-disarmed observation; never grants an execution pin."""
    if not callable(rpc):
        raise ValueError("explicit_readonly_rpc_required")
    if rpc("getGenesisHash", []) != MAINNET_GENESIS:
        raise ValueError("mainnet_genesis_not_verified")
    observations = {}
    for program_id in (PROGRAM, CPMM_PROGRAM):
        options = dict(encoding="base64", commitment="finalized", minContextSlot=1)
        first = rpc("getMultipleAccounts", [[program_id], options])
        first_slot, first_items = _bank(first, 1, 1)
        first_raw = _raw(first_items[0], executable=True, size=36)
        programdata_id = _programdata_address(first_raw, program_id)
        options = dict(encoding="base64", commitment="finalized",
                       minContextSlot=first_slot)
        second = rpc("getMultipleAccounts",
                     [[program_id, programdata_id], options])
        second_slot, second_items = _bank(second, 2, first_slot)
        second_raw = _raw(second_items[0], executable=True, size=36)
        if first_raw != second_raw or (
                _programdata_address(second_raw, program_id) != programdata_id):
            raise ValueError("public_program_pointer_changed")
        programdata_raw = _raw(second_items[1], executable=False)
        details = _details(programdata_raw, second_slot)
        observations[program_id] = dict(
            programdata_address=programdata_id,
            first_slot=first_slot, joint_slot=second_slot, **details)
    if getattr(rpc, "count", 5) != 5:
        raise ValueError("public_program_expected_five_reads")
    return dict(schema="rugger-public-mainnet-program-observation-v1",
                status="OBSERVED_UNAPPROVED",
                rpc_source=PUBLIC_MAINNET_RPC, genesis_hash=MAINNET_GENESIS,
                rpc_requests=5, programs=observations,
                source_build_verified=False,
                independent_rpc_consensus_verified=False,
                operator_pins_independently_approved=False,
                live_ready_to_arm=False, live_execution_verified=False,
                economic_edge_validated=False, financial_order_submitted=False)


def main():
    try:
        report = observe_public_programs(PublicReadOnlyRpc())
    except Exception as error:
        # Never print raw provider content, URL headers or internal exception.
        print(json.dumps(dict(status="REFUSED",
            diagnostic_error_type=type(error).__name__,
            live_ready_to_arm=False, financial_order_submitted=False),
            sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
