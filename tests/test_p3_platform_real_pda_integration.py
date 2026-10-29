"""Historical platform-admin proof with the *real* canonical PDA derivation.

No RPC is executed. An internally constructed signed historical envelope is
only a deterministic integration fixture; it cannot certify a real platform.
"""
from copy import deepcopy

from bot.p3.certification import PROGRAM,find_program_address
from bot.p3.platform_admin_history import verify_historical_platform_creation
from test_p3_launchlab import encode
from test_p3_research_integration import research_snapshot


DISC=bytes([176,90,196,175,253,113,220,20])


def _full_args():
    number=(0).to_bytes(8,'little')
    def bor(s):
        b=s.encode()
        return len(b).to_bytes(4,'little')+b
    return DISC+number*4+bor('LaunchLab')+bor('')+bor('')+number*2


def _record():
    _,addresses,analysis,_=research_snapshot(platform_verified=True,return_accounts=True)
    admin=encode(bytes([61])*32)
    expected,_=find_program_address((b'platform_config',bytes([61])*32))
    assert addresses['platform']==expected
    return addresses,analysis,admin,{
        'slot':analysis['context_slot']-1,
        'meta':{'err':None},
        'transaction':{
            'signatures':['synthetic_signature_not_a_chain_proof'],
            'message':{'accountKeys':[
                {'pubkey':admin,'signer':True,'writable':True},
                {'pubkey':encode(bytes([82])*32),'signer':False},
                {'pubkey':encode(bytes([83])*32),'signer':False},
                {'pubkey':expected,'signer':False},
                {'pubkey':PROGRAM,'signer':False},
                {'pubkey':encode(bytes([84])*32),'signer':False},
                {'pubkey':'11111111111111111111111111111111','signer':False},
                {'pubkey':encode(bytes([85])*32),'signer':False},
                {'pubkey':encode(bytes([86])*32),'signer':False}],
                'instructions':[{
                    'programIdIndex':4,
                    'accounts':[0,1,2,3,5,6,7,8],
                    'data':encode(_full_args())
                }]}}}


def test_offline_pinned_idl_signer_recovers_canonical_platform_seed():
    addresses,analysis,admin,tx=_record();saved=deepcopy(tx)
    result=verify_historical_platform_creation(tx,platform_config=addresses['platform'],
        signature=tx['transaction']['signatures'][0],
        snapshot_context_slot=analysis['context_slot'])
    assert result['status']=='PASS',result
    assert result['historical_platform_admin']==admin
    assert result['historical_seed_certified'] is True
    assert result['strict_snapshot_identity_promoted'] is False
    assert result['source_tx_provenance_certified_by_this_function'] is False
    assert tx==saved


def test_tampered_real_pda_historical_tx_rejected():
    addresses,analysis,admin,tx=_record()
    tx['transaction']['message']['accountKeys'][0]['signer']=False
    result=verify_historical_platform_creation(tx,platform_config=addresses['platform'],
        signature=tx['transaction']['signatures'][0],
        snapshot_context_slot=analysis['context_slot'])
    assert result['status']=='UNKNOWN'
    assert not result['historical_seed_certified']


def test_incomplete_historical_platform_params_rejected_even_if_pda_matches():
    addresses,analysis,admin,tx=_record()
    tx['transaction']['message']['instructions'][0]['data']=encode(DISC+b'foo')
    result=verify_historical_platform_creation(tx,platform_config=addresses['platform'],
        signature=tx['transaction']['signatures'][0],
        snapshot_context_slot=analysis['context_slot'])
    assert result['status']=='UNKNOWN'
    assert result['historical_seed_certified'] is False
