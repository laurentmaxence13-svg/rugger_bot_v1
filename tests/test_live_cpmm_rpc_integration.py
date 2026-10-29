"""Full read-only mainnet-interface integration through REAL SolanaRpc methods.

The Solana blockchain bank is synthetic and all signatures are made using
a public fixed test-only key. Unlike isolated mocked readiness tests, NO
program-pin, migration evidence, signature verifier, CPMM bank builder,
fee receipt, or transaction simulation function is monkeypatched.

This proves the end-to-end interfaces agree. It does NOT prove actual
mainnet inclusion, profitability, a wallet holding real funds, or live safety.
"""
import asyncio
import base64
from collections import Counter
import hashlib
import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from bot.p3.certification import PROGRAM, _decode, _encode, find_program_address
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.cpmm_readiness import preflight_migrated_sell
from bot.live.program_pin import LOADER
from bot.live.rpc import SolanaRpc
from bot.live.solana_signatures import compiled_message_bytes

from test_live_cpmm_exit import fixture_bank, MINT, WALLET, POOL
from test_live_migration_evidence import migration, OLD
from test_live_migration_rpc_json import _compiled
from test_live_unsigned_preflight import GENESIS, ENDPOINT


def loader_pair(program_id):
    address,_=find_program_address((_decode(program_id),),program_id=LOADER)
    program=struct.pack('<I',2)+_decode(address)
    # Fixed synthetic ELF bytes, deliberately NOT the deployed mainnet bytes.
    pd=struct.pack('<IQB',3,90,0)+bytes(32)+b'\x7fELF'+bytes([10,11,12])*30
    def rpc_account(raw,*,executable):
        return dict(owner=LOADER,executable=executable,lamports=20000000,
            space=len(raw),data=[base64.b64encode(raw).decode(),'base64'])
    return address,rpc_account(program,executable=True),rpc_account(pd,executable=False),dict(
        expected_deployment_slot=90,
        expected_programdata_sha256=hashlib.sha256(pd).hexdigest(),
        expected_elf_sha256=hashlib.sha256(pd[45:]).hexdigest(),
        expected_upgrade_authority=None)


def signed_migration():
    # Publicly known fixture secret. NEVER a live trading wallet.
    signer=Ed25519PrivateKey.from_private_bytes(bytes([23])*32)
    signer_pub=_encode(signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw))
    tx=migration()
    tx['transaction']['message']['accountKeys'][0]['pubkey']=signer_pub
    tx['slot']=111
    tx=_compiled(tx)
    tx['transaction']['message']['recentBlockhash']=_encode(bytes([7])*32)
    signature=_encode(signer.sign(compiled_message_bytes(tx)))
    tx['transaction']['signatures']=[signature]
    return tx,signature


class SyntheticSolanaTransport:
    endpoint='https://synthetic.rpc.test'
    def __init__(self):
        self.calls=[]
        self.pool=fixture_bank()
        self.migration,self.signature=signed_migration()
        self.programs={}
        self.program_pins={}
        for program in (PROGRAM,CPMM_PROGRAM):
            address,program_account,pd_account,pins=loader_pair(program)
            self.programs[program]=(address,program_account,pd_account)
            self.program_pins[program]=pins
        self.source_blockhash=self.pool['recent_blockhash']

    async def __call__(self,method,params):
        self.calls.append((method,params))
        if method=='getGenesisHash':
            return GENESIS
        if method=='getMultipleAccounts':
            keys=params[0]
            assert params[1]['commitment']=='confirmed'
            if len(keys)==1 and keys[0] in self.programs:
                return dict(context=dict(slot=1234),
                    value=[self.programs[keys[0]][1]])
            if len(keys)==2 and keys[0] in self.programs:
                addr,p,pd=self.programs[keys[0]]
                assert keys==[keys[0],addr]
                return dict(context=dict(slot=1234),value=[p,pd])
            if keys==[POOL]:
                return dict(context=dict(slot=1234),
                    value=[self.pool['accounts'][POOL]])
            if len(keys)==10 and keys[0]==POOL:
                assert params[1]['minContextSlot']>=1234
                return dict(context=dict(slot=1235),
                    value=[self.pool['accounts'][k] for k in keys])
            raise AssertionError('unexpected public account request')
        if method=='getTransaction':
            assert params[0]==self.signature
            assert params[1]['encoding']=='json'
            assert params[1]['commitment']=='finalized'
            return self.migration
        if method=='getLatestBlockhash':
            return dict(context=dict(slot=1236),
                value=dict(blockhash=self.source_blockhash,
                    lastValidBlockHeight=5000))
        if method=='getMinimumBalanceForRentExemption':
            assert params[0]==165
            return 2039280
        if method=='getBlockTime':
            assert params[0]==1235
            return 1
        if method=='getFeeForMessage':
            assert params[1]['minContextSlot']==1236
            assert params[1]['commitment']=='confirmed'
            raw=base64.b64decode(params[0],validate=True)
            assert len(raw)>=32
            return dict(context=dict(slot=1237),value=5002)
        if method=='getBlockHeight':
            return 4999
        if method=='simulateTransaction':
            raw=base64.b64decode(params[0],validate=True)
            assert raw[1:65]==bytes(64)
            assert params[1]['sigVerify'] is False
            assert params[1]['replaceRecentBlockhash'] is False
            assert params[1]['minContextSlot']==1235
            return dict(context=dict(slot=1238),
                value=dict(err=None,unitsConsumed=100000,
                           logs=['Program log: synthetic CPMM simulation']))
        raise AssertionError('unexpected RPC method: '+method)


def test_complete_unsigned_migration_sale_uses_real_rpc_adapter_and_all_18_read_calls():
    transport=SyntheticSolanaTransport()
    rpc=SolanaRpc(transport)
    ticks=iter((1050,1070,1100,1120,1140))
    r=asyncio.run(preflight_migrated_sell(
        rpc,
        program_pins=transport.program_pins,
        original_launchlab_pool=OLD,
        migrated_cpmm_pool=POOL,
        migration_signature=transport.signature,
        mint=MINT,wallet=WALLET,
        decision_id=transport.pool['decision_id'],
        expected_endpoint_sha256=rpc.endpoint_sha256,
        expected_genesis_hash=GENESIS,min_context_slot=1234,
        clock_ms=lambda:next(ticks),
        amount_in=transport.pool['amount_in'],
        slippage_bps=transport.pool['slippage_bps'],
        max_slippage_bps=transport.pool['max_slippage_bps'],
        max_price_impact_bps=transport.pool['max_price_impact_bps'],
        compute_unit_limit=transport.pool['compute_unit_limit'],
        priority_fee_micro_lamports=transport.pool['priority_fee_micro_lamports'],
        max_priority_fee_lamports=transport.pool['max_priority_fee_lamports'],
    ))
    assert r['status']=='UNSIGNED_CPMM_ROUTE_SIMULATED'
    assert r['historical_signature_cryptographically_verified']
    assert r['historical_migration_signatures']['result']=='ED25519_MESSAGE_SIGNATURES_VALID'
    assert r['simulation']['parsed_RPC_simulation_result']['logs']==[
        'Program log: synthetic CPMM simulation']
    assert r['bank']['fee_source_context_slot']==1237
    assert r['bank']['message_fee_lamports']==5002
    assert r['exact_prepared_order'].transaction.required_signers==(WALLET,)
    assert not r['live_execution_authorized']
    assert not r['live_ready_to_arm']
    assert not r['financial_order_submitted']
    methods=Counter(method for method,_ in transport.calls)
    assert methods==Counter(dict(
        getGenesisHash=5,getMultipleAccounts=6,getTransaction=1,
        getLatestBlockhash=1,getMinimumBalanceForRentExemption=1,
        getBlockTime=1,getFeeForMessage=1,getBlockHeight=1,
        simulateTransaction=1))
    assert sum(methods.values())==18
    assert 'sendTransaction' not in methods
