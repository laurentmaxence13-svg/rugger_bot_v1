"""Pinned LaunchLab migrate_to_cpswap transaction-link evidence tests.

Only synthetic public addresses and a synthetic getTransaction-like JSON body.
Transport and cryptographic signature verification deliberately remain separate.
"""
from copy import deepcopy
import pytest

from bot.p3.certification import PROGRAM,_decode,_encode,find_program_address
from bot.p3.quotes import SOL_MINT
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.migration_evidence import (
    MIGRATE_TO_CPSWAP_DISC,ROLES,REQUIRED_WRITABLE_ROLES,FIXED_PROGRAMS,
    validate_migrate_to_cpswap_transaction,
)


MINT=_encode(bytes([55])*32)
OLD=find_program_address((b'pool',_decode(MINT),_decode(SOL_MINT)))[0]
from test_live_cpmm_exit import POOL as NEW  # same synthetic signable migration target
PAYER=_encode(bytes([22])*32)
SIG=_encode(bytes([77])*64)


def migration():
    addresses={name:_encode(bytes([i+41])*32) for i,name in enumerate(ROLES)}
    addresses.update(
        payer=PAYER,base_mint=MINT,quote_mint=SOL_MINT,
        cpswap_program=CPMM_PROGRAM,cpswap_pool=NEW,
        cpswap_config=find_program_address((b'amm_config',b'\0\0'),
            program_id=CPMM_PROGRAM)[0],
        pool_state=OLD,
        cpswap_authority=find_program_address((b'vault_and_lp_mint_auth_seed',),
                                             program_id=CPMM_PROGRAM)[0],
        cpswap_lp_mint=find_program_address(
            (b'pool_lp_mint',_decode(NEW)),program_id=CPMM_PROGRAM)[0],
        cpswap_base_vault=find_program_address(
            (b'pool_vault',_decode(NEW),_decode(MINT)),program_id=CPMM_PROGRAM)[0],
        cpswap_quote_vault=find_program_address(
            (b'pool_vault',_decode(NEW),_decode(SOL_MINT)),program_id=CPMM_PROGRAM)[0],
        cpswap_observation=find_program_address(
            (b'observation',_decode(NEW)),program_id=CPMM_PROGRAM)[0],
    )
    addresses.update(FIXED_PROGRAMS)
    addresses.update(
        authority=find_program_address((b'vault_auth_seed',))[0],
        base_vault=find_program_address((b'pool_vault',_decode(OLD),_decode(MINT)))[0],
        quote_vault=find_program_address((b'pool_vault',_decode(OLD),_decode(SOL_MINT)))[0],
        lock_authority=find_program_address((b'lock_cp_authority_seed',),
            program_id=FIXED_PROGRAMS['lock_program'])[0],
    )
    ordered=[PAYER,NEW]
    for k in addresses.values():
        if k not in ordered:
            ordered.append(k)
    ordered.append(PROGRAM)
    keys=[dict(pubkey=k,signer=(i<2),writable=False) for i,k in enumerate(ordered)]
    refs=[ordered.index(addresses[role]) for role in ROLES]
    for r in REQUIRED_WRITABLE_ROLES:
        keys[refs[r]]['writable']=True
    keys[0]['writable']=True
    transaction=dict(
        slot=100,meta={'err':None},
        transaction={
            'signatures':[SIG,_encode(bytes([78])*64)],
            'message':{
                'header':{'numRequiredSignatures':2},
                'accountKeys':keys,
                'instructions':[dict(programIdIndex=ordered.index(PROGRAM),
                     accounts=refs,data=_encode(MIGRATE_TO_CPSWAP_DISC))],
            },
        },
    )
    return transaction


def check(tx,**kw):
    params=dict(signature=SIG,mint=MINT,launchlab_pool=OLD,
                cpmm_pool=NEW,observed_at_slot=101)
    params.update(kw)
    return validate_migrate_to_cpswap_transaction(tx,**params)


def test_transaction_idl_exact_evidence_links_previous_pool_and_actual_random_cpmm_pool():
    tx=migration();clone=deepcopy(tx)
    result=check(tx)
    assert tx==clone
    assert result['status']=='STRUCTURAL_MIGRATION_RECEIPT',result
    assert result['migration_instruction_matches']
    assert result['migration_signature']==SIG
    assert result['migration_slot']==100
    assert len(result['retained_transaction_sha256'])==64
    assert len(result['normalized_role_sha256'])==64
    assert not result['live_execution_authorized']
    assert not result['source_transport_authenticated']
    assert not result['cryptographic_signatures_verified']
    assert not result['cpmm_pool_state_account_decoded']


def test_wrong_history_or_source_identity_refused():
    tx=migration()
    for kwargs in (dict(signature=_encode(bytes([41])*64)),dict(mint=NEW),
                   dict(launchlab_pool=NEW),dict(cpmm_pool=OLD),
                   dict(observed_at_slot=99)):
        assert check(tx,**kwargs)['status']=='UNKNOWN'


@pytest.mark.parametrize('change',[
    'failed_meta','missing_meta_err','future_slot','wrong_disc',
    'extra_args','not_launchlab_program','missing_role','wrong_pool',
    'wrong_quote','wrong_cpmm_program','forged_authority',
    'forged_vault','forged_observation','missing_payer_signature',
    'missing_pool_writable','duplicate_account_keys',
])
def test_forged_migration_instruction_never_qualifies(change):
    tx=migration()
    ix=tx['transaction']['message']['instructions'][0]
    keys=tx['transaction']['message']['accountKeys']
    roles=ix['accounts']
    if change=='failed_meta':tx['meta']['err']={'InstructionError':[0,'Custom']}
    if change=='missing_meta_err':del tx['meta']['err']
    if change=='future_slot':tx['slot']=102
    if change=='wrong_disc':ix['data']=_encode(bytes(8))
    if change=='extra_args':ix['data']=_encode(MIGRATE_TO_CPSWAP_DISC+b'\x00')
    if change=='not_launchlab_program':
        ix['programIdIndex']=roles[4]
    if change=='missing_role':ix['accounts']=roles[:-1]
    if change=='wrong_pool':ix['accounts'][5]=roles[3]
    if change=='wrong_quote':ix['accounts'][2]=roles[1]
    if change=='wrong_cpmm_program':ix['accounts'][4]=roles[3]
    if change=='forged_authority':ix['accounts'][6]=roles[3]
    if change=='forged_vault':ix['accounts'][8]=roles[3]
    if change=='forged_observation':ix['accounts'][12]=roles[3]
    if change=='missing_payer_signature':keys[0]['signer']=False
    if change=='missing_pool_writable':keys[roles[5]]['writable']=False
    if change=='duplicate_account_keys':keys[2]['pubkey']=keys[3]['pubkey']
    assert check(tx)['status']=='UNKNOWN',change


def test_migration_json_with_string_account_keys_requires_authenticated_signer_flags():
    tx=migration()
    tx['transaction']['message']['accountKeys']=[
        k['pubkey'] for k in tx['transaction']['message']['accountKeys']]
    assert check(tx)['status']=='UNKNOWN'


def test_full_instruction_is_required_not_forged_inner_accounts():
    tx=migration()
    tx['transaction']['message']['instructions'][0]['accounts']=[
        tx['transaction']['message']['instructions'][0]['accounts'][0]]
    assert check(tx)['status']=='UNKNOWN'
