"""No-network guards for historically unrelated WSOL BUY and SELL legs."""
import pytest
from bot.live import public_sample_wsol_legs as mod
from bot.live.readonly_plan import MAINNET_GENESIS
from bot.p3.quotes import SOL_MINT

def test_sample_cannot_be_misrepresented_as_one_owner_trade():
    assert len(mod.LEGS)==2
    assert mod.LEGS[0]["pool"]==mod.LEGS[1]["pool"]
    assert mod.LEGS[0]["payer"]!=mod.LEGS[1]["payer"]
    assert mod.LEGS[1]["slot"]<mod.LEGS[0]["slot"]
    assert all(SOL_MINT not in x["payer"] for x in mod.LEGS)

def test_wrong_genesis_rejected_before_gettransaction():
    methods=[]
    def fake(method,params):
        methods.append(method)
        return "wrong"
    with pytest.raises(ValueError,match="mainnet"):
        mod.verify_two_wsol_legs(fake)
    assert methods==["getGenesisHash"]

def test_no_transaction_does_not_prove_a_cycle():
    def fake(method,params):
        return MAINNET_GENESIS if method=="getGenesisHash" else None
    with pytest.raises(ValueError,match="slot"):
        mod.verify_two_wsol_legs(fake)
