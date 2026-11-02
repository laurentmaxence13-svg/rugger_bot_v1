"""Explicit, bounded, read-only post-deploy verification of genuine Master NO-GO.

Never calls Helius, DexScreener, Solana RPC, financial routes, wallets or
private endpoints. No secret is required or read.
"""
from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen

from bot.ops.render_master_readiness import assess_master_paper_readiness

RENDER_ORIGIN = "https://rugger-master-readonly.onrender.com"
PATHS = ("/healthz", "/api/helius", "/api/master-readiness")
MAX_BYTES = 65_536


def fetch_public_json(path, *, opener=urlopen):
    if path not in PATHS:
        raise ValueError("unapproved_readonly_smoke_path")
    req = Request(RENDER_ORIGIN + path, headers={
        "Accept": "application/json",
        "User-Agent": "RuggerMasterReadOnlySmoke/1.0",
    }, method="GET")
    with opener(req, timeout=30) as response:
        if response.status != 200:
            raise ValueError("readonly_service_not_200")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("readonly_response_too_large")
    result = json.loads(raw)
    if type(result) is not dict:
        raise ValueError("readonly_response_not_mapping")
    return result


def validate_readiness(health, signed, readiness):
    """Reject claims of Master execution or cross-feed substitution."""
    if (type(health) is not dict or
            health.get("status") != "up" or
            health.get("financial_order_submitted") is not False):
        raise ValueError("unsafe_readonly_health")
    if (type(signed) is not dict or
            signed.get("live_trading_enabled") is not False or
            signed.get("wallet_connected") is not False or
            signed.get("no_signing_or_order_submission") is not True):
        raise ValueError("unsafe_signed_source")
    expected = assess_master_paper_readiness(signed)
    if type(readiness) is not dict:
        raise ValueError("master_readiness_missing")
    for field in ("schema", "source", "mode", "status", "next_blocker",
                  "signed_evidence_fresh", "master_buy_sell_paper_verified",
                  "master_net_pnl_sol", "master_reference_edge_sol",
                  "experimental_dexscreener_excluded",
                  "financial_order_submitted", "live_trading_enabled",
                  "requires_explicit_new_evidence_to_advance"):
        if field not in readiness or readiness.get(field) != expected[field] or (
                type(readiness.get(field)) is not type(expected[field])):
            raise ValueError("inconsistent_master_readiness")
    return {
        "status": "POST_DEPLOY_READONLY_SMOKE_OK",
        "master_paper_status": "NO_GO",
        "next_blocker": expected["next_blocker"],
        "master_buy_sell_paper_verified": False,
        "financial_order_submitted": False,
    }


def smoke_once(*, fetcher=fetch_public_json):
    health, signed, readiness = (fetcher(path) for path in PATHS)
    return validate_readiness(health, signed, readiness)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true",
                        help="Explicit one-shot HTTPS GET authorization")
    args = parser.parse_args(argv)
    if not args.network:
        print("READONLY_SMOKE_REFUSED:EXPLICIT_NETWORK_OPT_IN_REQUIRED")
        return 2
    try:
        outcome = smoke_once()
    except Exception as error:
        # Never print exception text: a proxy may echo sensitive inputs.
        print("READONLY_SMOKE_REFUSED:" + type(error).__name__)
        return 2
    print(json.dumps(outcome, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
