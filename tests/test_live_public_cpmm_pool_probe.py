"""No-network safety and fail-closed tests for public CPMM bank probe."""
import pytest
from bot.live.public_cpmm_pool_probe import probe_cpmm_pools, MIGRATED_POOLS
from bot.live.readonly_plan import MAINNET_GENESIS

class FakeRpc:
    def __init__(self, network=MAINNET_GENESIS, invalid=False):
        self.network,self.invalid=network,invalid
        self.methods=[]
        self.count=0
    def __call__(self,method,params):
        self.count+=1
        self.methods.append(method)
        if method=="getGenesisHash":
            assert params==[]
            return self.network
        assert method=="getMultipleAccounts"
        assert params[1]["commitment"]=="finalized"
        assert params[1]["encoding"]=="base64"
        assert params[1]["minContextSlot"]>=max(p[2] for p in MIGRATED_POOLS)+1
        return dict(context=dict(slot=params[1]["minContextSlot"]),
                    value=[None]*len(params[0]))

def test_public_pool_probe_rejects_wrong_chain_before_any_account_read():
    rpc=FakeRpc(network="wrong")
    with pytest.raises(ValueError,match="genesis"):
        probe_cpmm_pools(rpc)
    assert rpc.methods==["getGenesisHash"]

def test_public_pool_probe_never_treats_missing_pool_as_valid_liquidity():
    rpc=FakeRpc()
    with pytest.raises((TypeError,ValueError)):
        probe_cpmm_pools(rpc)
    assert rpc.methods==["getGenesisHash","getMultipleAccounts"]
    assert rpc.count==2

def test_public_pool_probe_refuses_unprovided_rpc():
    with pytest.raises(ValueError):
        probe_cpmm_pools(None)
