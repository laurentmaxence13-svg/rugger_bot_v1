"""No-network public holder scan contract tests."""
import pytest
from bot.live.public_holder_probe import find_public_ata_holder,MINT
from bot.live.readonly_plan import MAINNET_GENESIS

class Fake:
    def __init__(self,wrong=False,empty=False):
        self.wrong,self.empty=wrong,empty
        self.methods=[]
    def __call__(self,method,params):
        self.methods.append(method)
        if method=="getGenesisHash":return "wrong" if self.wrong else MAINNET_GENESIS
        assert method=="getTokenLargestAccounts"
        assert params==[MINT,dict(commitment="finalized")]
        return dict(context=dict(slot=458932586),value=[] if self.empty else [dict(address=MINT)])

def test_holders_never_read_account_data_on_wrong_chain():
    rpc=Fake(wrong=True)
    with pytest.raises(ValueError,match="mainnet"):
        find_public_ata_holder(rpc)
    assert rpc.methods==["getGenesisHash"]

def test_empty_holder_page_never_claims_spendable_wallet():
    rpc=Fake(empty=True)
    with pytest.raises(ValueError,match="page"):
        find_public_ata_holder(rpc)
    assert rpc.methods==["getGenesisHash","getTokenLargestAccounts"]

def test_missing_rpc_is_not_accepted():
    with pytest.raises(ValueError):
        find_public_ata_holder(None)
