"""Fixture inputs taken from the frozen tree's own offline tests.

Everything here is synthetic: the wallet is thirty-two repeated bytes (nobody
holds a key for it), the pool, mint and vaults are generated account bytes and
not market observations, and the balances are simulated, not funds.
"""
import importlib
from pathlib import Path
import sys

import bot
from bot.p3.certification import _encode

from .bank import SyntheticBank
from .fixture_rpc import FixtureRpc
from .harness import HarnessConfig

GENESIS_HASH = _encode(bytes([12]) * 32)  # same synthetic value as tests/test_live_engine.py
ENDPOINT_SHA256 = 'a' * 64                # same synthetic value as tests/test_live_engine.py
BLOCK_HEIGHT = 4900                       # below the fixtures' last_valid_block_height (5000)


def _frozen_test_helper(module, name):
    """Import one helper of the frozen tests without writing into that tree."""
    tests = str(Path(bot.__file__).resolve().parents[1] / 'tests')
    bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    sys.path.append(tests)
    try:
        return getattr(importlib.import_module(module), name)
    finally:
        sys.path.remove(tests)
        sys.dont_write_bytecode = bytecode


def launchlab_fixture():
    """``(bank, request)`` from tests/test_live_wire_route.py:route_request."""
    request = _frozen_test_helper('test_live_wire_route', 'route_request')('BUY')
    bank = SyntheticBank(request['accounts'], pool_address=request['pool_address'],
                         mint=request['mint'], context_slot=request['context_slot'])
    return bank, request


def cpmm_fixture_request():
    """The CPMM bank of tests/test_live_cpmm_exit.py:fixture_bank, unchanged."""
    return _frozen_test_helper('test_live_cpmm_exit', 'fixture_bank')()


def fixture_rpc():
    return FixtureRpc(genesis_hash=GENESIS_HASH, endpoint_sha256=ENDPOINT_SHA256,
                      block_height=BLOCK_HEIGHT)


def fixture_config(request, **overrides):
    values = dict(
        wallet=request['wallet'],
        simulated_wallet_lamports=request['accounts'][request['wallet']]['lamports'],
        max_exposure_lamports=500_000_000, max_loss_lamports=100_000_000,
        genesis_hash=GENESIS_HASH, endpoint_sha256=ENDPOINT_SHA256,
        recent_blockhash=request['recent_blockhash'],
        last_valid_block_height=request['last_valid_block_height'],
        token_account_rent_lamports=request['rent_exempt_lamports'])
    values.update(overrides)
    return HarnessConfig(**values)
