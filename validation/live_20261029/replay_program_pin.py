"""Replay the original public LaunchLab ProgramData snapshot without network.

The program code was captured under the existing registered two-call plan.
This replay verifies that the new loader-v3 pin parser matches the retained
raw program/ELF bytes; pins are derived from that historical snapshot ONLY
for offline regression, not newly approved for financial submission.
"""
import asyncio
import base64
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parent

def block_outbound(event,args):
    if event in ('socket.connect','socket.bind','socket.getaddrinfo','sqlite3.connect'):
        raise AssertionError('historical_ProgramData_replay_is_strictly_offline')
sys.addaudithook(block_outbound)

from bot.live.program_pin import attest_program_pin


async def replay():
    plan=json.loads((BASE/'PROGRAM_PROBE_PLAN.json').read_text())
    result=json.loads(gzip.decompress((BASE/'program-probe.json.gz').read_bytes()))
    assert result['stop_reason'] is None and result['requests_used']==2
    assert result['plan']==plan
    record=result['records'][1]
    assert record['method']=='getMultipleAccounts'
    assert record['params'][0]==plan['addresses']
    original=record['response']
    program,programdata=original['value']
    slot=original['context']['slot']
    raw=base64.b64decode(programdata['data'][0],validate=True)
    assert raw[45:49]==b'\x7fELF'
    observation=result['code_observation']
    assert observation['observed_slot']==slot
    assert observation['ELF_sha256']==hashlib.sha256(raw[45:]).hexdigest()
    assert observation['independently_approved'] is False

    class RetainedBank:
        endpoint_sha256=hashlib.sha256(plan['rpc_source'].encode()).hexdigest()
        def __init__(self):
            self.calls=[]
        async def genesis_hash(self):
            self.calls.append('getGenesisHash')
            return result['genesis_hash']
        async def get_multiple_accounts(self,keys,*,min_context_slot):
            assert min_context_slot<=slot
            self.calls.append(('getMultipleAccounts',tuple(keys),min_context_slot))
            if list(keys)==plan['addresses'][:1]:
                return {'context':dict(original['context']),
                        'value':[program]}
            assert list(keys)==plan['addresses']
            return original
        async def send_transaction(self,*a,**kw):
            raise AssertionError('archive_replay_can_never_submit')

    rpc=RetainedBank()
    pinned=await attest_program_pin(rpc,
        program_id=plan['addresses'][0],
        expected_endpoint_sha256=rpc.endpoint_sha256,
        expected_genesis_hash=plan['expected_genesis_hash'],
        min_context_slot=plan['minimum_context_slot'],
        expected_deployment_slot=observation['deployment_slot'],
        expected_programdata_sha256=hashlib.sha256(raw).hexdigest(),
        expected_elf_sha256=observation['ELF_sha256'],
        expected_upgrade_authority=observation['upgrade_authority'])
    assert pinned['result']=='PIN_MATCHED_READ_ONLY'
    assert pinned['programdata_address']==plan['addresses'][1]
    assert pinned['joint_bank_slot']==slot
    assert pinned['source_build_verified'] is False
    assert pinned['live_execution_authorized'] is False
    assert len(rpc.calls)==3
    return dict(historical_mainnet_ProgramData_replay='PASS',
        original_RPC_requests_replayed=2,new_RPC_requests=0,
        old_slot=slot,ELF_sha256=pinned['elf_sha256'],
        programdata_sha256=pinned['programdata_sha256'],
        independently_approved=False,live_ready_to_arm=False)


if __name__=='__main__':
    print(json.dumps(asyncio.run(replay()),sort_keys=True,indent=2))
