"""One independently reverified *historical* signed LaunchLab receipt.

One bounded public Solana RPC getTransaction (never an order), no Helius key,
no wallet, no paid provider, and no retry that could mask provider quotas.
This corroborates a *past* signed creation, NOT current SOL quote liquidity,
entry timing, executable swap, Master PAPER fill or profitability.
"""
from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen

from bot.live.compiled_launchlab import compiled_launchlab_creations
from bot.live.solana_signatures import verify_compiled_rpc_signatures

PUBLIC_RPC = "https://api.mainnet.solana.com"
SOURCE_RUN_ID = 41316007232
EXPECTED_SIGNATURE = "3TEheZgrLKhD3s1nTnae6wHp8cKuJCr67QBJc1dDMNdLdNn4HSsa3SkbWNF2M28iY5RwBMgrFxqsvFqmkYYmKAew"
EXPECTED_SLOT = 464124955
EXPECTED_MESSAGE_SHA256 = "a4e81e4c6620e2aaa4be3d98e76224f43cebdddc24e49e32122bd3bc772f29b7"
EXPECTED_CREATOR = "24L1tRQfEfc6yRCVocnJisprJ2qEfEuC7ApnSC7ADgiU"
EXPECTED_MINT = "EUcMrcmVJPLyeH9xw7NSGsdHyzLTVywvNNieP4FcYq2X"
EXPECTED_POOL = "AHHBr6UkNtjxKuiGKuLdRi1kA1w2sDZsHGjJRDEaMXef"
MAX_RESPONSE_BYTES = 1_500_000
SCHEMA = "rugger-independent-historical-signed-creation-proof-v1"

# Only predefined local error identifiers may be shown. Never print raw RPC
# JSON, provider exception messages or a credential-bearing URL.
SAFE_REFUSALS = frozenset((
    "free_public_rpc_not_available",
    "unbounded_public_rpc_reply",
    "invalid_public_rpc_reply",
    "historical_receipt_unavailable_on_free_rpc",
    "independent_signed_receipt_identity_mismatch",
    "independent_signed_message_hash_mismatch",
    "independent_signed_launch_creation_not_matched",
    "unsupported_transaction_message_or_header",
    "historical_transaction_Ed25519_signature_invalid",
    "compiled_signer_count_invalid",
    "compiled_instruction_index_invalid",
    "compiled_instruction_data_noncanonical",
    "exact_compiled_signer_vector_required",
    "invalid_v0_lookup_table_indices",
))


def _reject(reason):
    raise ValueError(reason)


def fetch_one_public_transaction(*, opener=urlopen):
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
        "params": [EXPECTED_SIGNATURE, {"encoding": "json",
                    "commitment": "finalized", "maxSupportedTransactionVersion": 0}],
    }, separators=(",", ":")).encode("utf-8")
    request = Request(PUBLIC_RPC, data=body, headers={
        "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": "RuggerIndependentSignedReadOnly/1.0"},
        method="POST")
    with opener(request, timeout=15) as response:
        if response.status != 200:
            _reject("free_public_rpc_not_available")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        _reject("unbounded_public_rpc_reply")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        _reject("invalid_public_rpc_reply")
    if (type(envelope) is not dict or
            envelope.get("jsonrpc") != "2.0" or
            envelope.get("id") != 1 or
            envelope.get("error") is not None or
            type(envelope.get("result")) is not dict):
        _reject("historical_receipt_unavailable_on_free_rpc")
    return envelope["result"]


def check_pinned_public_receipt(tx):
    """Independently verify actual Ed25519 compiled message and LaunchLab identity."""
    if (type(tx) is not dict or tx.get("slot") != EXPECTED_SLOT
            or type(tx.get("meta")) is not dict
            or tx["meta"].get("err") is not None
            or type(tx.get("transaction")) is not dict
            or type(tx["transaction"].get("signatures")) is not list
            or not tx["transaction"]["signatures"]
            or tx["transaction"]["signatures"][0] != EXPECTED_SIGNATURE):
        _reject("independent_signed_receipt_identity_mismatch")
    crypto = verify_compiled_rpc_signatures(tx)
    if (crypto.get("cryptographic_signatures_verified") is not True or
            crypto.get("exact_message_sha256") != EXPECTED_MESSAGE_SHA256):
        _reject("independent_signed_message_hash_mismatch")
    launches = compiled_launchlab_creations(tx)
    if type(launches) is not list or not any(
            type(item) is dict and
            item.get("creator") == EXPECTED_CREATOR and
            item.get("mint") == EXPECTED_MINT and
            item.get("pool") == EXPECTED_POOL
            for item in launches):
        _reject("independent_signed_launch_creation_not_matched")
    return {
        "schema": SCHEMA,
        "status": "INDEPENDENT_ED25519_RECEIPT_VERIFIED",
        "source_gitHub_run_id": SOURCE_RUN_ID,
        "public_rpc_endpoint": PUBLIC_RPC,
        "verified_source_slot": EXPECTED_SLOT,
        "creation_signature": EXPECTED_SIGNATURE,
        "creation_mint": EXPECTED_MINT,
        "creation_pool": EXPECTED_POOL,
        "ed25519_message_verified": True,
        "same_exact_message_sha256_as_archived_helius": True,
        "independent_provider_rpc_consensus_verified": False,
        "sol_native_pool_graph_verified": False,
        "source_quote_clock_verified": False,
        "master_paper_buy_sell_verified": False,
        "master_net_pnl_lamports": None,
        "financial_order_submitted": False,
        "live_trading_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true",
                        help="Explicit single free public RPC read only")
    args = parser.parse_args(argv)
    if not args.network:
        print("INDEPENDENT_SOURCE_PROBE_REFUSED:EXPLICIT_NETWORK_OPT_IN_REQUIRED")
        return 2
    try:
        result = check_pinned_public_receipt(fetch_one_public_transaction())
    except Exception as error:
        # Do not echo network response or exception details.
        safe = str(error) if type(error) is ValueError and str(error) in SAFE_REFUSALS else None
        print(json.dumps(dict(schema=SCHEMA, status="REFUSED",
            safe_error_class=type(error).__name__, safe_reason_code=safe,
            financial_order_submitted=False), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
