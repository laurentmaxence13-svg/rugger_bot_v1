"""Read-only mainnet simulation attestation of actual BUY/SELL wire messages.

These are intentionally fixture RPCs. No network, signed transaction, wallet,
user database or capital is involved. Real mainnet receipts must be separately
acquired, persisted and reviewed before claiming execution readiness.
"""
import asyncio
import hashlib
import json

import pytest

from bot.live.unsigned_preflight import check_unsigned_order
from bot.live.route import build_launchlab_order
from test_live_wire_route import route_request
from test_live_evidence import GENESIS, ENDPOINT


class SimulationRpc:
    endpoint_sha256=ENDPOINT

    def __init__(self):
        self.calls=[]
        self.genesis=GENESIS
        self.height=4999
        self.slot=1300
        self.error=None
        self.units=100000

    async def genesis_hash(self):
        self.calls.append('getGenesisHash')
        return self.genesis

    async def get_block_height(self):
        self.calls.append('getBlockHeight')
        return self.height

    async def simulate_transaction(self, raw, *, sig_verify, min_context_slot):
        assert type(raw) is bytes
        assert sig_verify is False
        assert min_context_slot==1234
        self.calls.append('simulateTransaction')
        self.simulated_raw=raw
        return dict(context_slot=self.slot,err=self.error,
                    unitsConsumed=self.units,logs=['Program log: offline test'])

    async def send_transaction(self,*_args,**_kwargs):
        raise AssertionError('sendTransaction_is_forbidden_in_unsigned_probe')


def run(rpc,order,**changes):
    params=dict(expected_genesis_hash=GENESIS,expected_endpoint_sha256=ENDPOINT,
                now_ms=1100)
    params.update(changes)
    return asyncio.run(check_unsigned_order(rpc,order,**params))


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_buy_and_sell_are_exact_unsigned_messages_and_never_sent(side):
    order=build_launchlab_order(**route_request(side))
    rpc=SimulationRpc()
    result=run(rpc,order)
    assert result['result']=='SIMULATION_SUCCEEDED_UNSENT'
    assert result['side']==side
    assert result['message_sha256']==hashlib.sha256(order.transaction.message).hexdigest()
    assert result['unsigned_transaction_sha256']==hashlib.sha256(
        order.transaction.unsigned_transaction()).hexdigest()
    assert rpc.simulated_raw==order.transaction.unsigned_transaction()
    assert rpc.calls==['getGenesisHash','getBlockHeight','simulateTransaction']
    assert result['simulation_slot']>=result['source_slot']
    raw=result['parsed_RPC_simulation_result']
    assert raw['logs']==['Program log: offline test']
    assert result['original_HTTP_RPC_envelope_retained'] is False
    assert result['parsed_RPC_simulation_sha256']==hashlib.sha256(json.dumps(
        raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert result['route_executed'] is False
    assert result['live_ready_to_arm'] is False
    assert result['economic_edge_validated'] is False


def test_wrong_genesis_aborts_before_any_blockheight_or_simulation():
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc()
    rpc.genesis='wrong_chain'
    result=run(rpc,order)
    assert result['result']=='REFUSED'
    assert result['reason']=='unexpected_cluster_genesis'
    assert rpc.calls==['getGenesisHash']


def test_wrong_endpoint_refuses_before_any_rpc():
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc()
    result=run(rpc,order,expected_endpoint_sha256='f'*64)
    assert result['reason']=='RPC_endpoint_not_pinned'
    assert rpc.calls==[]


@pytest.mark.parametrize('now',[999,6001,True])
def test_stale_future_or_invalid_receipt_clock_never_simulates(now):
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc()
    if now is True:
        with pytest.raises(ValueError,match='explicit_genesis_endpoint_clock_and_freshness_required'):
            run(rpc,order,now_ms=now)
        return
    result=run(rpc,order,now_ms=now)
    assert result['reason']=='stale_or_future_source_bank'
    assert rpc.calls==[]


def test_expired_blockhash_prevents_simulation():
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc(); rpc.height=5001
    assert run(rpc,order)['reason']=='blockhash_expired_before_simulation'
    assert rpc.calls==['getGenesisHash','getBlockHeight']


def test_rpc_failure_is_retained_as_failure_never_a_fake_pass():
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc();rpc.error={'InstructionError':[4,{'Custom':1}]}
    result=run(rpc,order)
    assert result['result']=='REFUSED'
    assert result['reason']=='simulation_returned_error'
    assert result['simulation_error_class']=='dict'
    assert result['parsed_RPC_simulation_result']['err']==rpc.error
    assert len(result['parsed_RPC_simulation_sha256'])==64


@pytest.mark.parametrize('slot,compute',[(1233,100000),(1300,None),(1300,200001),(True,1)])
def test_invalid_causal_slot_or_compute_never_qualifies(slot,compute):
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc();rpc.slot=slot;rpc.units=compute
    result=run(rpc,order)
    assert result['result']=='REFUSED'


@pytest.mark.parametrize('field,bad',[
    ('expected_genesis_hash',''),
    ('expected_endpoint_sha256','notsha'),
    ('max_bank_age_ms',5001),
    ('max_bank_age_ms',True),
])
def test_missing_or_unsafe_operator_proof_refused(field,bad):
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc()
    with pytest.raises(ValueError):
        run(rpc,order,**{field:bad})
    assert rpc.calls==[]


def test_full_cpmm_exit_uses_exact_same_unsigned_RPC_boundary():
    from bot.live.cpmm_exit import build_cpmm_exit
    from bot.live.cpmm_swap import CPMM_PROGRAM
    from test_live_cpmm_exit import fixture_bank
    order=build_cpmm_exit(**fixture_bank())
    rpc=SimulationRpc()
    result=run(rpc,order)
    assert result['result']=='SIMULATION_SUCCEEDED_UNSENT'
    assert result['program_id']==CPMM_PROGRAM
    assert result['side']=='SELL'
    assert result['message_sha256']==hashlib.sha256(order.transaction.message).hexdigest()
    assert rpc.simulated_raw==order.transaction.unsigned_transaction()
    assert rpc.calls==['getGenesisHash','getBlockHeight','simulateTransaction']
    assert result['migration_provenance_verified'] is False
    assert result['live_ready_to_arm'] is False
    assert not result['route_executed']


def test_invalid_cpmm_order_cannot_reach_RPC():
    from dataclasses import replace
    from bot.live.cpmm_exit import build_cpmm_exit
    from test_live_cpmm_exit import fixture_bank
    order=build_cpmm_exit(**fixture_bank())
    rpc=SimulationRpc()
    with pytest.raises(ValueError,match='modified'):
        run(rpc,replace(order,expected_output=order.expected_output+100))
    assert rpc.calls==[]



def test_noncanonical_simulation_payload_refused_without_promoting_success():
    order=build_launchlab_order(**route_request())
    rpc=SimulationRpc()
    rpc.error={'bad_nan':float('nan')}
    result=run(rpc,order)
    assert result['result']=='REFUSED'
    assert result['reason']=='noncanonical_simulation_response'
    assert rpc.calls==['getGenesisHash','getBlockHeight','simulateTransaction']
