"""Independent ABI/causality regressions; all accounts/RPCs are synthetic."""
import asyncio
from copy import deepcopy
import struct

import pytest

from bot.live.cpmm_exit import build_cpmm_exit
from bot.live.migration_evidence import validate_migrate_to_cpswap_transaction
from bot.live.unsigned_preflight import check_unsigned_order
from bot.live.route import build_launchlab_order
from bot.p3.certification import _encode
from test_live_cpmm_exit import fixture_bank,mutate_raw
from test_live_migration_evidence import migration,SIG,MINT,OLD,NEW
from test_live_unsigned_preflight import SimulationRpc,GENESIS,ENDPOINT
from test_live_wire_route import route_request
from test_live_migration_rpc_json import _compiled


def _check(tx):
    return validate_migrate_to_cpswap_transaction(tx,signature=SIG,mint=MINT,
        launchlab_pool=OLD,cpmm_pool=NEW,observed_at_slot=101)


@pytest.mark.parametrize('role',[1,11,15,16,19,20,21])
def test_all_IDL_required_writable_migration_accounts_are_required(role):
    tx=migration();message=tx['transaction']['message'];ix=message['instructions'][0]
    message['accountKeys'][ix['accounts'][role]]['writable']=False
    assert _check(tx)['status']=='UNKNOWN'


@pytest.mark.parametrize('role',[13,22,23,24,25,26,27])
def test_migration_fixed_program_addresses_are_not_arbitrary_lookalikes(role):
    tx=migration();message=tx['transaction']['message'];ix=message['instructions'][0]
    # All corresponding references are distinct from this fresh public key.
    message['accountKeys'][ix['accounts'][role]]['pubkey']=_encode(bytes([200])*32)
    assert _check(tx)['status']=='UNKNOWN'


def test_newly_migrated_pool_oracle_before_first_swap_is_not_missing_liquidity():
    value=fixture_bank()
    raw_pool=value['accounts'][value['pool_address']]['data'][0]
    import base64
    from bot.p3.certification import _encode
    pool=base64.b64decode(raw_pool);observation=_encode(pool[8+9*32:8+10*32])
    # Official initialize.rs sets pool_id, leaving initialized=false until
    # Oracle::update in the first actual swap. Reserves remain fully present.
    mutate_raw(value['accounts'][observation],8,b'\0')
    result=build_cpmm_exit(**value)
    assert result.expected_output>0


def test_boolean_transaction_version_cannot_alias_v0():
    value=_compiled(migration());value['version']=False
    assert _check(value)['status']=='UNKNOWN'


def test_noncanonical_cpmm_pool_must_be_a_real_transaction_signer():
    value=migration();message=value['transaction']['message'];refs=message['instructions'][0]['accounts']
    index=refs[5]
    message['accountKeys'][index]['signer']=False
    # Reorder the remaining signer prefix correctly, so this refusal tests
    # random-pool authorization as well as the general signer-vector gate.
    value['transaction']['signatures']=value['transaction']['signatures'][:1]
    message['header']['numRequiredSignatures']=1
    assert _check(value)['status']=='UNKNOWN'


@pytest.mark.parametrize('stage',['genesis','height','simulation'])
def test_unsigned_preflight_cannot_accept_a_bank_that_expires_during_RPC(stage):
    order=build_launchlab_order(**route_request())
    clock=[1100];rpc=SimulationRpc()
    if stage=='genesis':
        original=rpc.genesis_hash
        async def delayed():
            result=await original();clock[0]=6001;return result
        rpc.genesis_hash=delayed
    elif stage=='height':
        original=rpc.get_block_height
        async def delayed():
            result=await original();clock[0]=6001;return result
        rpc.get_block_height=delayed
    else:
        original=rpc.simulate_transaction
        async def delayed(*args,**kwargs):
            result=await original(*args,**kwargs);clock[0]=6001;return result
        rpc.simulate_transaction=delayed
    result=asyncio.run(check_unsigned_order(rpc,order,expected_genesis_hash=GENESIS,
        expected_endpoint_sha256=ENDPOINT,now_ms=1100,clock_ms=lambda:clock[0]))
    assert result['result']=='REFUSED'
    assert 'stale' in result['reason'] or 'expired' in result['reason']
    if stage in ('genesis','height'):assert 'simulateTransaction' not in rpc.calls
