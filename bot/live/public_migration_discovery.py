"""Bounded real mainnet search for ONE historical SOL-paired LaunchLab->CPMM migration.

Reads only 1 genesis, 1 finalized signature page, up to 8 finalized transactions
from a public Raydium migration payer. No wallet funding or user account query,
no signing, send, simulation, retry, fallback, storage or trading permission.
A positive result is a provider claim + verified Ed25519 bytes and canonical
migration graph, NOT independent chain consensus or strategy profitability.
"""
import json
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError
import ssl
import sys

from bot.live.readonly_plan import MAINNET_GENESIS, PUBLIC_MAINNET_RPC
from bot.live.public_program_observer import SECONDARY_RPC
from bot.p3.certification import PROGRAM
from bot.p3.quotes import SOL_MINT
from bot.p3.platform_admin_history import _signature, _b58_bytes
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.migration_evidence import (
    MIGRATE_TO_CPSWAP_DISC, validate_migrate_to_cpswap_transaction)
from bot.live.solana_signatures import verify_compiled_rpc_signatures

PUBLIC_MIGRATION_PAYER = "2RAYpQbFNq9i3mu6cKpTKKRwwHFDeK5AuZz8xvxUrCgw"
MAX_SIGNATURES = 8
MAX_CALLS = 2 + MAX_SIGNATURES


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("public_migration_redirect_forbidden")


class MigrationReadOnlyRpc:
    def __init__(self, *, endpoint=PUBLIC_MAINNET_RPC):
        if endpoint not in (PUBLIC_MAINNET_RPC, SECONDARY_RPC):
            raise ValueError('unapproved_readonly_rpc_endpoint')
        self.endpoint = endpoint
        self.count = 0
        self.started = time.monotonic()
        self.opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
            NoRedirect())

    def __call__(self, method, params):
        if method not in ("getGenesisHash", "getSignaturesForAddress",
                          "getTransaction"):
            raise ValueError("historical_migration_read_methods_only")
        if self.count >= MAX_CALLS or time.monotonic()-self.started > 65:
            raise ValueError("migration_public_rpc_budget_exceeded")
        self.count += 1
        payload = json.dumps(dict(jsonrpc="2.0", id=self.count,
            method=method, params=params), separators=(",", ":")).encode()
        request = Request(self.endpoint, data=payload,
            headers={"Content-Type":"application/json"}, method="POST")
        with self.opener.open(request, timeout=8) as response:
            if response.status != 200 or response.geturl()!=self.endpoint:
                raise ValueError("public_migration_RPC_refused")
            raw=response.read(6_000_001)
            if len(raw)>6_000_000:
                raise ValueError("public_migration_RPC_response_too_large")
        body=json.loads(raw)
        if (type(body) is not dict or body.get("jsonrpc")!="2.0"
                or type(body.get("id")) is not int
                or body["id"]!=self.count or "error" in body
                or "result" not in body):
            raise ValueError("public_migration_RPC_response_invalid")
        return body["result"]


def candidate_role_mapping(raw):
    """Decode exact top-level migration instruction; no role inference by name."""
    normalized=normalized_compiled_transaction(raw)
    message=normalized["transaction"]["message"]
    keys=message["accountKeys"]
    matches=[]
    for instruction in message["instructions"]:
        idx=instruction.get("programIdIndex")
        indices=instruction.get("accounts")
        if (type(idx) is not int or not 0<=idx<len(keys)
                or keys[idx]["pubkey"]!=PROGRAM or type(indices) is not list
                or len(indices) not in (28, 38)):
            continue
        try:
            if _b58_bytes(instruction["data"])!=MIGRATE_TO_CPSWAP_DISC:
                continue
            role_keys=[keys[i]["pubkey"] for i in indices]
        except (ValueError,KeyError,TypeError,IndexError):
            raise ValueError("malformed_mainnet_migration_instruction") from None
        if role_keys[2] == SOL_MINT:
            matches.append(dict(mint=role_keys[1],original_pool=role_keys[17],
                                cpmm_pool=role_keys[5]))
    if len(matches)>1:
        raise ValueError("multiple_distinct_historical_migration_instructions")
    return matches[0] if matches else None


def discover_one_qualified_migration(rpc):
    if not callable(rpc):
        raise ValueError("public_migration_rpc_required")
    if rpc("getGenesisHash",[])!=MAINNET_GENESIS:
        raise ValueError("public_migration_wrong_network")
    results=rpc("getSignaturesForAddress",[
        PUBLIC_MIGRATION_PAYER,dict(limit=MAX_SIGNATURES,commitment="finalized")])
    if type(results) is not list or len(results)>MAX_SIGNATURES:
        raise ValueError("unexpected_migration_signature_page")
    inspected=0
    for candidate in results:
        if (type(candidate) is not dict or
                type(candidate.get("slot")) is not int or candidate["slot"]<=0
                or "err" not in candidate):
            raise ValueError("malformed_finalized_signature_entry")
        signature=_signature(candidate.get("signature"))
        if candidate["err"] is not None:
            continue
        inspected+=1
        raw=rpc("getTransaction",[signature,
             dict(encoding="json",commitment="finalized",
                  maxSupportedTransactionVersion=0)])
        if raw is None:
            continue
        if type(raw) is not dict or type(raw.get("slot")) is not int:
            raise ValueError("malformed_finalized_historical_transaction")
        if raw["slot"]!=candidate["slot"] or raw.get("meta",{}).get("err") is not None:
            raise ValueError("public_migration_signature_slot_or_result_mismatch")
        role=candidate_role_mapping(raw)
        if role is None:
            continue
        structural=validate_migrate_to_cpswap_transaction(
            raw,signature=signature,mint=role["mint"],
            launchlab_pool=role["original_pool"],cpmm_pool=role["cpmm_pool"],
            observed_at_slot=candidate["slot"])
        if structural["status"]!="STRUCTURAL_MIGRATION_RECEIPT":
            raise ValueError("mainnet_migration_structural_graph_refused")
        signed=verify_compiled_rpc_signatures(raw)
        if signed.get("cryptographic_signatures_verified") is not True:
            raise ValueError("mainnet_migration_signature_bytes_unverified")
        return dict(schema="rugger-public-historical-spl-sol-migration-v1",
                    status="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED",
                    signature=signature,slot=candidate["slot"],**role,
                    structural_role_sha256=structural["normalized_role_sha256"],
                    signed_message_sha256=signed["exact_message_sha256"],
                    signatures_sha256=signed["signatures_sha256"],
                    signature_count=signed["required_signatures"],
                    quote_mint=SOL_MINT,
                    calls_used=getattr(rpc,"count",None),
                    histories_checked=inspected,
                    source=PUBLIC_MAINNET_RPC,
                    source_RPC_claim_finalized=True,
                    signed_message_Ed25519_verified=True,
                    independent_RPC_consensus_verified=False,
                    source_program_build_audited=False,
                    individual_wallet_inventory_verified=False,
                    actual_sell_simulated=False, live_ready_to_arm=False,
                    financial_order_submitted=False, economic_edge_validated=False)
    return dict(schema="rugger-public-historical-spl-sol-migration-v1",
                status="NO_QUALIFIED_MIGRATION_IN_FIXED_BOUNDED_PAGE",
                histories_checked=inspected,calls_used=getattr(rpc,"count",None),
                live_ready_to_arm=False,financial_order_submitted=False,
                economic_edge_validated=False)


def main():
    try:
        report=discover_one_qualified_migration(MigrationReadOnlyRpc())
    except Exception as error:
        report=dict(status="REFUSED",error_type=type(error).__name__,
                    http_status_code=error.code if isinstance(error,HTTPError) else None,
                    live_ready_to_arm=False,financial_order_submitted=False,
                    economic_edge_validated=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report["status"]=="FINALIZED_RPC_MIGRATION_CRYPTOGRAPHICALLY_MATCHED" else 2


if __name__=="__main__":
    sys.exit(main())
