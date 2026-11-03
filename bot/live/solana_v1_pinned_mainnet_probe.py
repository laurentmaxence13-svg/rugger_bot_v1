"""Reproduce exactly two observed v1 mainnet receipt decoding failures.

Pinned from read-only GitHub run 41097829050 on 2026-10-30; public
signatures/slots only. Never use a wallet, private key, signature production,
transaction submission, financial order or automatic promotion.
"""
import json
import os
import sys

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.live.solana_v1_readonly import verify_v1_base64_receipt

PINNED = (
    ("4Yw2ELT4p6Y9HX7Mmw9Vp732vRuAqjX82oUqgHc15AciG4FtNzdb6cnvhTYPYuJFPBxZsN8sfAgEQhwmG3iNC9QD", 463367104),
    ("51Z1gUtu6fTehdi5LBheyp8wcNFTuTxobV7P2wNCKUqRxXqoPt78u6y2GXtXMzLmaS6Z9cLEGErz7zkC1oxHJ4vH", 463367176),
)
OPTS = dict(encoding="base64", commitment="finalized",
            maxSupportedTransactionVersion=1)


def verify_pinned_v1(rpc):
    if not callable(rpc) or rpc("getGenesisHash", []) != MAINNET_GENESIS:
        raise ValueError("wrong_mainnet_genesis")
    results = []
    for sig, slot in PINNED:
        try:
            raw = rpc("getTransaction", [sig, OPTS])
            result = verify_v1_base64_receipt(
                raw, expected_signature=sig, expected_slot=slot)
            results.append(dict(signature=sig, slot=slot,
                status="V1_SIGNED_RECEIPT_VERIFIED",
                exact_message_sha256=result["exact_message_sha256"],
                signed_outer_creation_count=len(result["launched_candidates"])))
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            code = str(exc)
            safe = (code if type(exc) is ValueError
                    and code.startswith("v1_") and len(code) < 100
                    and code.replace("_", "").isalnum()
                    else "OTHER_" + type(exc).__name__)
            results.append(dict(signature=sig, slot=slot,
                status="V1_RECEIPT_REFUSED", reason=safe))
    return dict(schema="rugger-reproduce-two-v1-mainnet-errors-v1",
        status="ALL_VERIFIED" if all(
            item["status"] == "V1_SIGNED_RECEIPT_VERIFIED"
            for item in results) else "V1_PARSER_STILL_NOT_VERIFIED",
        results=results, rpc_calls=getattr(rpc, "count", None),
        live_ready_to_arm=False, economic_edge_validated=False,
        financial_order_submitted=False)


def main():
    try:
        rpc=HeliusReadOnlyRpc.from_environment(max_calls=3)
        report=verify_pinned_v1(rpc)
    except Exception as exc:
        report=dict(status="READ_ONLY_RPC_REFUSED",
            safe_error_class=type(exc).__name__,
            financial_order_submitted=False, live_ready_to_arm=False)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"]=="ALL_VERIFIED" else 2


if __name__=="__main__":
    sys.exit(main())
