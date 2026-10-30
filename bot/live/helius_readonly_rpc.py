"""Restricted Helius mainnet JSON-RPC client for PUBLIC, READ-ONLY evidence.

The GitHub Actions secret is consumed only at request construction time; the
key and authenticated URL are never reported or persisted. No env/.env loading,
private keys, transaction signing, simulation or send method is supported.
Other callers supply only public addresses and transaction signatures.
"""
import base64
import json
import os
import re
import ssl
import time
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.certification import PROGRAM

HELIUS_RPC_ID = "https://mainnet.helius-rpc.com/"
READ_METHODS = frozenset(("getGenesisHash", "getTransaction",
                          "getTokenLargestAccounts", "getMultipleAccounts"))
UNSIGNED_PREFLIGHT_METHODS = frozenset((
    "getLatestBlockhash", "getBlockHeight", "getBlockTime",
    "getMinimumBalanceForRentExemption", "getFeeForMessage",
    "simulateTransaction"))
_API_KEY = re.compile(r"[A-Za-z0-9_-]{16,160}\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("helius_redirect_forbidden")


class HeliusReadOnlyRpc:
    """Maximum ten calls in 50 seconds; never emits a secret in any diagnostic."""

    endpoint = HELIUS_RPC_ID

    def __init__(self, key, *, max_calls=10, opener=None,
                 allow_unsigned_preflight=False, allow_launch_discovery=False):
        if (type(key) is not str or key == "COLLE_TA_CLE_ICI"
                or _API_KEY.fullmatch(key) is None):
            raise ValueError("helius_api_key_missing_or_invalid")
        if type(max_calls) is not int or not 1 <= max_calls <= 10:
            raise ValueError("helius_readonly_call_budget_invalid")
        # Authenticated endpoint is deliberately private. No repr or diagnostic
        # exposes this value. The public .endpoint is always key-free.
        self._key = key
        self._url = HELIUS_RPC_ID + "?api-key=" + quote(key, safe="")
        if type(allow_unsigned_preflight) is not bool:
            raise ValueError("explicit_unsigned_preflight_flag_required")
        if type(allow_launch_discovery) is not bool:
            raise ValueError('explicit_launch_discovery_flag_required')
        self._discovery = allow_launch_discovery
        self._preflight = allow_unsigned_preflight
        self._max_calls = max_calls
        self.count = 0
        self.last_method = None
        self.last_rpc_error_code = None
        self.started = time.monotonic()
        self._opener = opener or build_opener(
            ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
            NoRedirect())

    @classmethod
    def from_environment(cls, *, max_calls=10, allow_unsigned_preflight=False,
                         allow_launch_discovery=False):
        # Never fall back to any key read from a local .env.
        return cls(os.environ.get("HELIUS_API_KEY"), max_calls=max_calls,
                   allow_unsigned_preflight=allow_unsigned_preflight,
                   allow_launch_discovery=allow_launch_discovery)

    def __repr__(self):
        return "HeliusReadOnlyRpc(endpoint='mainnet.helius-rpc.com',key='REDACTED')"

    def __call__(self, method, params):
        if method not in READ_METHODS and not (
                self._preflight and method in UNSIGNED_PREFLIGHT_METHODS) and not (
                self._discovery and method=="getSignaturesForAddress"):
            raise ValueError("helius_only_explicit_allowlisted_read_methods")
        if method == "getSignaturesForAddress":
            if (not self._discovery or type(params) is not list or len(params)!=2
                    or params[0]!=PROGRAM or type(params[1]) is not dict
                    or set(params[1])!={"limit","commitment"}
                    or params[1].get("commitment")!="finalized"
                    or type(params[1].get("limit")) is not int
                    or not 1<=params[1]["limit"]<=20):
                raise ValueError("helius_launch_discovery_requires_exact_bounded_program_page")
        if method == "simulateTransaction":
            if (type(params) is not list or len(params)!=2
                    or type(params[0]) is not str or type(params[1]) is not dict):
                raise ValueError("helius_unsigned_simulation_shape_invalid")
            options=params[1]
            if (options.get("sigVerify") is not False
                    or options.get("replaceRecentBlockhash") is not False
                    or options.get("encoding")!="base64"
                    or options.get("commitment")!="confirmed"
                    or type(options.get("minContextSlot")) is not int
                    or options["minContextSlot"]<=0):
                raise ValueError("helius_simulation_must_be_unsigned_nonreplacing")
            try:
                wire=base64.b64decode(params[0],validate=True)
            except (ValueError,base64.binascii.Error):
                raise ValueError("helius_unsigned_wire_encoding_invalid") from None
            # One legacy signature slot, all zero: never simulate signed orders.
            if not 65<=len(wire)<=1232 or wire[:65] != bytes([1])+bytes(64):
                raise ValueError("helius_unsigned_wire_only_zero_signature_required")
        if self.count >= self._max_calls or time.monotonic() - self.started > 50:
            raise ValueError("helius_readonly_budget_exceeded")
        self.count += 1
        self.last_method = method
        self.last_rpc_error_code = None
        payload = json.dumps(
            dict(jsonrpc="2.0", id=self.count, method=method, params=params),
            sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = Request(self._url, data=payload, method="POST",
                          headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=8) as response:
                if response.status != 200 or response.geturl() != self._url:
                    raise ValueError("helius_status_or_redirect_refused")
                raw = response.read(6_000_001)
                if len(raw) > 6_000_000:
                    raise ValueError("helius_response_exceeded")
        except HTTPError as exc:
            raise ValueError("helius_http_status_" + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError("helius_network_unavailable") from None
        try:
            reply = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("helius_json_invalid") from None
        if type(reply) is dict and type(reply.get("error")) is dict:
            code=reply["error"].get("code")
            if type(code) is int and -100_000<=code<=100_000:
                self.last_rpc_error_code=code
        if (type(reply) is not dict or reply.get("jsonrpc") != "2.0"
                or type(reply.get("id")) is not int or reply["id"] != self.count
                or "error" in reply or "result" not in reply):
            raise ValueError("helius_rpc_envelope_refused")
        return reply["result"]
