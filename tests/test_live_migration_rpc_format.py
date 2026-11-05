"""Raw RPC migration format must not inherit fabricated signer privileges."""
import asyncio
from copy import deepcopy

import pytest

from bot.live.migration_rpc_receipt import read_finalized_migration
from test_live_migration_evidence import migration,SIG,MINT,OLD,NEW
from test_live_migration_rpc_json import _compiled
from test_live_unsigned_preflight import ENDPOINT,GENESIS


class FakeRpc:
    endpoint_sha256=ENDPOINT

    def __init__(self,reply):
        self.reply=deepcopy(reply)
        self.calls=[]

    async def genesis_hash(self):
        self.calls.append('genesis')
        return GENESIS

    async def get_transaction(self,signature):
        assert signature==SIG
        self.calls.append('transaction')
        return deepcopy(self.reply)

    async def send_transaction(self,*args,**kwargs):
        raise AssertionError('read_only_verifier_must_not_send')


def check(payload):
    rpc=FakeRpc(payload)
    result=asyncio.run(read_finalized_migration(
        rpc,signature=SIG,mint=MINT,launchlab_pool=OLD,cpmm_pool=NEW,
        observed_at_slot=101,expected_endpoint_sha256=ENDPOINT,
        expected_genesis_hash=GENESIS))
    assert rpc.calls==['genesis','transaction']
    assert not result['live_execution_allowed']
    return result


@pytest.mark.parametrize('loaded_role',[None,8])
def test_raw_compiled_legacy_and_v0_migration_are_still_accepted(loaded_role):
    raw=_compiled(migration(),loaded_role=loaded_role)
    result=check(raw)
    assert result['status']=='FINALIZED_RPC_STRUCTURAL_MATCH'
    assert result['raw_RPC_response']==raw
    assert not result['cryptographic_signature_bytes_verified']


def test_synthetic_jsonParsed_key_flags_cannot_pose_as_compiled_RPC_response():
    forged=migration()
    # Internal structural test fixtures support dict account keys, but the
    # real getTransaction(encoding=json) service must not trust those flags.
    result=check(forged)
    assert result['status']=='REFUSED'
    assert result['reason']=='RPC_getTransaction_expected_compiled_json_not_jsonParsed'
    assert result['raw_RPC_response']==forged
    assert not result['source_RPC_endpoint_pin_matched'] if 'source_RPC_endpoint_pin_matched' in result else True


@pytest.mark.parametrize('attack',[
    'boolean_version','future_version','boolean_signature_header',
    'missing_header','fabricated_account_dict','mixed_account_formats',
    'string_program_index','boolean_program_index','float_account_index',
    'base58_data_list','missing_instruction_accounts',
])
def test_invalid_compiled_RPC_structure_blocks_migration(attack):
    raw=_compiled(migration())
    message=raw['transaction']['message']
    instruction=message['instructions'][0]
    if attack=='boolean_version':raw['version']=False
    if attack=='future_version':raw['version']=1
    if attack=='boolean_signature_header':
        message['header']['numRequiredSignatures']=True
    if attack=='missing_header':del message['header']
    if attack=='fabricated_account_dict':
        message['accountKeys']=[
            dict(pubkey=k,signer=True,writable=True) for k in message['accountKeys']]
    if attack=='mixed_account_formats':
        message['accountKeys'][1]=dict(pubkey=message['accountKeys'][1],
                                      signer=True,writable=True)
    if attack=='string_program_index':instruction['programIdIndex']='0'
    if attack=='boolean_program_index':instruction['programIdIndex']=True
    if attack=='float_account_index':instruction['accounts'][0]=0.0
    if attack=='base58_data_list':instruction['data']=[instruction['data'],'base58']
    if attack=='missing_instruction_accounts':del instruction['accounts']
    result=check(raw)
    assert result['status']=='REFUSED'
    assert result['reason']=='RPC_getTransaction_expected_compiled_json_not_jsonParsed'
