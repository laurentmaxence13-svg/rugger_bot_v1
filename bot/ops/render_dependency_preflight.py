"""Fail-closed Render build preflight for the signed, read-only Helius source.

This module imports/verifies dependencies only. It never requests market data,
starts a trading worker, signs transactions, or reads an API key.
"""
from __future__ import annotations

import importlib

SOURCE_MODULE = "bot.live.helius_signed_master_paper"


def verify_readonly_source(*, load_module=None, verify_signature=None):
    """Require the independent Ed25519 verifier and genuine source pipeline.

    Do not substitute experimental DexScreener data when Helius prerequisites
    are missing. The source function is imported but never executed.
    """
    if load_module is None:
        load_module = importlib.import_module
    if verify_signature is None:
        from bot.ops.render_readonly_service import require_signed_source_ed25519
        verify_signature = require_signed_source_ed25519
    verifier = verify_signature()
    if verifier is None:
        raise RuntimeError("missing_signed_receipt_verifier")
    module = load_module(SOURCE_MODULE)
    if not callable(getattr(module, "run_pipeline", None)):
        raise RuntimeError("missing_readonly_signed_source_pipeline")
    return True


def main():
    try:
        verify_readonly_source()
    except Exception as error:
        # Exception text may contain a provider URL or secret. Never emit it.
        print("READONLY_RENDER_BUILD_PREFLIGHT_REFUSED:" + type(error).__name__)
        return 1
    print("READONLY_RENDER_BUILD_PREFLIGHT_OK:NO_NETWORK_NO_ORDERS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
