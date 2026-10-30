"""Hypothetical public-wallet CPMM test is always capped, unsigned, non-financial."""
import pytest
from bot.live.helius_unsigned_sell_probe import (
    bounded_public_hypothesis, HeliusAsyncReadOnlyTransport,
    MAX_HYPOTHETICAL_INPUT_ATOMIC)
from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc
from test_live_helius_readonly_rpc import KEY, Opener


@pytest.mark.parametrize("amount", [None,True,-1,0,1,1999999,1.2,"100"])
def test_hypothesis_does_not_use_unqualified_balance(amount):
    with pytest.raises(ValueError):
        bounded_public_hypothesis(amount)


def test_hypothesis_is_always_less_than_public_balance():
    for balance in [2_000_000,5_000_000,100_000_000_000,
                    500_000_000_000,2**64-1]:
        output=bounded_public_hypothesis(balance)
        assert 0<output<balance
        assert output<=MAX_HYPOTHETICAL_INPUT_ATOMIC


def test_async_adapter_refuses_rpc_without_unsigned_preflight():
    r=HeliusReadOnlyRpc(KEY,opener=Opener())
    with pytest.raises(ValueError,match="unsigned"):
        HeliusAsyncReadOnlyTransport(r)
    assert r.count==0
