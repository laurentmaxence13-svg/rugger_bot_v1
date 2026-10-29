"""Read-only RPC migration retrieval with strict finalized transaction checks.

Fixture RPC mocks only. The tests assert that no transaction submission can
occur and a mismatch never yields a migration claim.
"""
import asyncio
from copy import deepcopy
import hashlib
import json

import pytest

from bot.live.migration_rpc_receipt import read_finalized_migration
from test_live_migration_rpc_json import _compiled
from test_live_migration_evidence import migration,SIG,MINT,OLD,NEW
from test_live_unsigned_preflight import GENESIS,ENDPOINT


class Rpc:
    endpoint_sha256=ENDPOINT

    def __init__(self, response):
        self.response=response
        self.calls=[]
        self.genesis=GENESIS

    async def genesis_hash(self):
        self.calls.append('getGenesisHash')
        return self.genesis

    async def get_transaction(self, signature):
        assert signature==SIG
        self.calls.append('getTransaction')
        return deepcopy(self.response)

    async def send_transaction(self,*args,**kwargs):
        raise AssertionError('migration_read_only_may_never_send')

    async def sign_message(self,*args,**kwargs):
        raise AssertionError('migration_read_only_may_never_sign')


def run(rpc,**changes):
    fields=dict(signature=SIG,mint=MINT,launchlab_pool=OLD,cpmm_pool=NEW,
        expected_endpoint_sha256=ENDPOINT,expected_genesis_hash=GENESIS,
        observed_at_slot=101)
    fields.update(changes)
    return asyncio.run(read_finalized_migration(rpc,**fields))


def test_finalized_compiled_RPC_reply_matches_source_pool_and_migrated_pool_without_funds():
    raw=_compiled(migration())
    rpc=Rpc(raw)
    response=run(rpc)
    assert response['status']=='FINALIZED_RPC_STRUCTURAL_MATCH'
    assert response['raw_response_sha256']==hashlib.sha256(
        json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert response['source_RPC_genesis_pin_matched']
    assert response['source_RPC_endpoint_pin_matched']
    assert response['source_signature_appeared_in_finalized_RPC_transaction']
    assert response['actual_RPC_response_retained']
    assert response['rpc_calls']==2
    assert rpc.calls==['getGenesisHash','getTransaction']
    assert not response['live_execution_allowed']
    assert not response['cryptographic_signature_bytes_verified']
    assert not response['network_consensus_independently_verified']


@pytest.mark.parametrize('change',[
    'wrong_endpoint','wrong_genesis','missing_receipt','failed_receipt',
    'wrong_mint','wrong_source_pool','wrong_migration_pool','future_migration',
])
def test_wrong_transport_or_history_never_promotes_migration(change):
    rpc=Rpc(_compiled(migration()))
    overrides={}
    if change=='wrong_endpoint':overrides['expected_endpoint_sha256']='f'*64
    if change=='wrong_genesis':rpc.genesis=OLD
    if change=='missing_receipt':rpc.response=None
    if change=='failed_receipt':rpc.response['meta']['err']={'InstructionError':[0,'Custom']}
    if change=='wrong_mint':overrides['mint']=OLD
    if change=='wrong_source_pool':overrides['launchlab_pool']=NEW
    if change=='wrong_migration_pool':overrides['cpmm_pool']=OLD
    if change=='future_migration':overrides['observed_at_slot']=99
    result=run(rpc,**overrides)
    assert result['status']!='FINALIZED_RPC_STRUCTURAL_MATCH'
    assert not result['live_execution_allowed']
    assert 'sendTransaction' not in rpc.calls
    assert rpc.calls in (
        [],['getGenesisHash'],['getGenesisHash','getTransaction'])


def test_getTransaction_receipt_is_not_assumed_source_code_or_signature_audit():
    rpc=Rpc(_compiled(migration()))
    r=run(rpc)
    assert not r['transport_beyond_pinned_endpoint_independently_verified']
    assert not r['cryptographic_signature_bytes_verified']
    assert not r['network_consensus_independently_verified']
