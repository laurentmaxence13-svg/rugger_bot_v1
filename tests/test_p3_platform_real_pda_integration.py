"""Historical platform-admin proof with the *real* canonical PDA derivation.

No RPC is executed. An internally constructed signed historical envelope is
only a deterministic integration fixture; it cannot certify a real platform.
"""
from copy import deepcopy

from bot.p3.certification import PROGRAM,find_program_address
from bot.p3.platform_admin_history import verify_historical_platform_creation,refine_snapshot_with_platform_history
from bot.p3.launchlab import analyze_snapshot
from bot.p3.cohort import classify_snapshot
from test_p3_launchlab import encode,mutate_account
from test_p3_research_integration import research_snapshot
from test_p3_platform_admin_history import create_params,SIGNATURE


DISC=bytes([176,90,196,175,253,113,220,20])


def _record(*,unknown_original_seed=False):
    accounts,addresses,analysis,_=research_snapshot(platform_verified=True,return_accounts=True)
    if unknown_original_seed:
        # Current fee wallet differs from the historicaladmin. Re-decode actual
        # synthetic account bytes; never replace a PASS flag by hand.
        mutate_account(accounts,addresses['platform'],16,bytes([90])*32)
        analysis=analyze_snapshot(accounts,context_slot=1234,expected_mint=addresses['mint_a'],
            pool_address=addresses['pool'],input_lamports=100000000,evidence_profile='published_metadata_v1')
    admin=encode(bytes([61])*32)
    expected,_=find_program_address((b'platform_config',bytes([61])*32))
    assert addresses['platform']==expected
    return addresses,analysis,admin,{
        'slot':analysis['context_slot']-1,
        'meta':{'err':None},
        'transaction':{
            'signatures':[SIGNATURE],
            'message':{'accountKeys':[
                {'pubkey':admin,'signer':True,'writable':True},
                {'pubkey':encode(bytes([82])*32),'signer':False},
                {'pubkey':encode(bytes([83])*32),'signer':False},
                {'pubkey':expected,'signer':False,'writable':True},
                {'pubkey':encode(bytes([84])*32),'signer':False},
                {'pubkey':'11111111111111111111111111111111','signer':False},
                {'pubkey':encode(bytes([85])*32),'signer':False},
                {'pubkey':encode(bytes([86])*32),'signer':False},
                {'pubkey':PROGRAM,'signer':False}],
                'instructions':[{
                    'programIdIndex':8,
                    'accounts':[0,1,2,3,4,5,6,7],
                    'data':encode(create_params())
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


def test_before_decision_history_refines_only_platform_identity_and_preserves_financial_flags():
    addresses,analysis,admin,tx=_record(unknown_original_seed=True);original=deepcopy(analysis)
    before=classify_snapshot(analysis,available_at_ms=1000,decision_at_ms=1100,
        expected_mint=analysis['mint'],expected_pool=analysis['pool_address'])
    assert before['screen_eligible'] is False
    assert analysis['facts']['identity_certification']['blocking_reasons']==['original_platform_admin_seed_not_retained']
    refined=refine_snapshot_with_platform_history(analysis,tx,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)
    assert analysis==original
    assert refined['facts']['account_data_sha256']==original['facts']['account_data_sha256']
    assert refined['facts']['identity_certification']['program_derived_addresses_verified'] is True
    before_checks={c['name']:c for c in original['facts']['identity_certification']['checks']}
    after_checks={c['name']:c for c in refined['facts']['identity_certification']['checks']}
    assert all(after_checks[name]==check for name,check in before_checks.items() if name!='platform_pda')
    after=classify_snapshot(refined,available_at_ms=1000,decision_at_ms=1100,
        expected_mint=analysis['mint'],expected_pool=analysis['pool_address'])
    assert after['screen_eligible'] is True
    assert refined['candidate_eligible'] is original['candidate_eligible'] is False
    assert refined['economic_verdict']==original['economic_verdict']=='INSUFFICIENT DATA'
    assert refined['conditional_projection']==original['conditional_projection']
    assert refined['risk_flags']==original['risk_flags']==[]
    metadata=refined['facts']['historical_platform_refinement']
    assert metadata['historical_platform_admin']==admin
    assert not metadata['cryptographic_signature_verified']
    assert not metadata['trade_allowed']


def test_late_history_never_upgrades_an_earlier_decision():
    _,analysis,_,tx=_record(unknown_original_seed=True)
    assert refine_snapshot_with_platform_history(analysis,tx,signature=SIGNATURE,
        proof_available_at_ms=1101,decision_at_ms=1100)==analysis


def test_invalid_history_and_existing_safety_failures_remain_unchanged():
    _,analysis,_,tx=_record(unknown_original_seed=True)
    broken=deepcopy(tx);broken['transaction']['message']['accountKeys'][0]['signer']=False
    assert refine_snapshot_with_platform_history(analysis,broken,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==analysis
    unsafe=deepcopy(analysis);unsafe['risk_flags']=['freeze_authority_present']
    assert refine_snapshot_with_platform_history(unsafe,tx,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==unsafe
    unsafe=deepcopy(analysis);unsafe['facts']['supply_consistency']['matches']=False
    assert refine_snapshot_with_platform_history(unsafe,tx,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==unsafe


def test_wrong_platform_or_historical_future_slot_cannot_refine():
    _,analysis,_,tx=_record(unknown_original_seed=True)
    broken=deepcopy(tx);broken['slot']=analysis['context_slot']+1
    assert refine_snapshot_with_platform_history(analysis,broken,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==analysis
    broken=deepcopy(tx);broken['transaction']['message']['instructions'][0]['accounts'][3]=1
    assert refine_snapshot_with_platform_history(analysis,broken,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==analysis


def test_future_source_time_and_unpublished_identity_pins_cannot_refine():
    _,analysis,_,tx=_record(unknown_original_seed=True)
    tx['blockTime']=2
    assert refine_snapshot_with_platform_history(analysis,tx,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==analysis
    tx.pop('blockTime')
    broken=deepcopy(analysis);broken['facts']['identity_certification']['source_pins']['commit']='0'*40
    assert refine_snapshot_with_platform_history(broken,tx,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==broken


def test_missing_other_identity_relation_or_conflicting_success_flags_cannot_refine():
    _,analysis,_,tx=_record(unknown_original_seed=True)
    broken=deepcopy(analysis)
    broken['facts']['identity_certification']['checks']=[c for c in broken['facts']['identity_certification']['checks'] if c['name']!='pool_link_vault_a']
    assert refine_snapshot_with_platform_history(broken,tx,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==broken
    broken=deepcopy(analysis)
    broken['facts']['identity_certification']['program_derived_addresses_verified']=True
    assert refine_snapshot_with_platform_history(broken,tx,signature=SIGNATURE,
        proof_available_at_ms=1050,decision_at_ms=1100)==broken
