"""Independent raw-message vectors for Solana legacy/v0 Ed25519 verification.

Test signer is PUBLICLY KNOWN and NEVER FUNDED: 32 copies of byte 23.
The test manually assembles the wire message, signs it with its fixture-only
key, and then challenges the verifier's reconstruction and tamper handling.
"""
from copy import deepcopy
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from bot.p3.certification import _decode,_encode
from bot.live.solana_signatures import compiled_message_bytes,verify_compiled_rpc_signatures


# Fixed dummy key for isolated test vectors, not a real trading wallet.
_TEST_SEED=bytes([23])*32
_TEST_SIGNER=Ed25519PrivateKey.from_private_bytes(_TEST_SEED)
PAYER=_encode(_TEST_SIGNER.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw))
PROGRAM=_encode(bytes([42])*32)
BLOCKHASH=_encode(bytes([7])*32)
LOOKUP_TABLE=_encode(bytes([91])*32)
LOADED_TOKEN=_encode(bytes([92])*32)


def signed_fixture(*,v0=False):
    compiled_data=b'\x01\x02'
    static_bytes=_decode(PAYER)+_decode(PROGRAM)
    head=b'\x01\x00\x01'+b'\x02'+static_bytes+_decode(BLOCKHASH)
    accounts=[0,2] if v0 else [0]
    instruction=(b'\x01'+b'\x01'+bytes([len(accounts)])+
                 bytes(accounts)+b'\x02'+compiled_data)
    lookups=b'\x01'+_decode(LOOKUP_TABLE)+b'\x01\x04\x00' if v0 else b''
    msg=(b'\x80' if v0 else b'')+head+instruction+lookups
    signature=_encode(_TEST_SIGNER.sign(msg))
    tx=dict(version=0 if v0 else 'legacy',slot=1234,
        meta=dict(err=None),
        transaction=dict(signatures=[signature],
            message=dict(
                header=dict(numRequiredSignatures=1,
                            numReadonlySignedAccounts=0,
                            numReadonlyUnsignedAccounts=1),
                accountKeys=[PAYER,PROGRAM],recentBlockhash=BLOCKHASH,
                instructions=[dict(programIdIndex=1,
                    accounts=accounts,data=_encode(compiled_data))],
            )),
    )
    if v0:
        tx['transaction']['message']['addressTableLookups']=[
            dict(accountKey=LOOKUP_TABLE,writableIndexes=[4],
                 readonlyIndexes=[])]
        tx['meta']['loadedAddresses']=dict(
            writable=[LOADED_TOKEN],readonly=[])
    return tx,msg


@pytest.mark.parametrize('v0',[False,True])
def test_independent_reference_ed25519_signatures_match_exact_compiled_message(v0):
    tx,reference=signed_fixture(v0=v0)
    assert compiled_message_bytes(tx)==reference
    attestation=verify_compiled_rpc_signatures(tx)
    assert attestation['result']=='ED25519_MESSAGE_SIGNATURES_VALID'
    assert attestation['exact_message_sha256']==hashlib.sha256(reference).hexdigest()
    assert attestation['required_signatures']==1
    assert attestation['cryptographic_signatures_verified'] is True
    assert not attestation['independent_chain_inclusion_verified']
    assert not attestation['independent_RPC_consensus_verified']
    assert not attestation['live_execution_authorized']
    assert not attestation['live_ready_to_arm']


@pytest.mark.parametrize('attack',[
    'message_data','recent_blockhash','payer_identity','signature',
    'extra_signature','signatures_missing','bool_instruction_index',
    'out_of_range_program_index','v0_loaded_address',
    'v0_lookup_index','v0_lookup_table','noncanonical_data',
])
def test_forged_message_or_signature_cannot_be_cryptographically_verified(attack):
    v0=attack.startswith('v0_')
    tx,_=signed_fixture(v0=v0)
    msg=tx['transaction']['message']
    if attack=='message_data':msg['instructions'][0]['data']=_encode(b'\x01\x03')
    if attack=='recent_blockhash':msg['recentBlockhash']=PROGRAM
    if attack=='payer_identity':msg['accountKeys'][0]=PROGRAM
    if attack=='signature':tx['transaction']['signatures'][0]=_encode(bytes([7])*64)
    if attack=='extra_signature':tx['transaction']['signatures'].append(
        tx['transaction']['signatures'][0])
    if attack=='signatures_missing':tx['transaction']['signatures']=[]
    if attack=='bool_instruction_index':msg['instructions'][0]['programIdIndex']=True
    if attack=='out_of_range_program_index':
        msg['instructions'][0]['programIdIndex']=99
    if attack=='v0_loaded_address':
        tx['meta']['loadedAddresses']['writable'][0]=PROGRAM
    if attack=='v0_lookup_index':
        msg['addressTableLookups'][0]['writableIndexes'][0]=10
    if attack=='v0_lookup_table':
        msg['addressTableLookups'][0]['accountKey']=BLOCKHASH
    if attack=='noncanonical_data':
        msg['instructions'][0]['data']='0!'
    with pytest.raises((ValueError,KeyError)):
        verify_compiled_rpc_signatures(tx)


def test_v0_lookup_table_change_invalidates_original_signature_even_if_target_exists():
    tx,source=signed_fixture(v0=True)
    tx['transaction']['message']['addressTableLookups'][0]['accountKey']=BLOCKHASH
    assert compiled_message_bytes(tx)!=source
    with pytest.raises(ValueError,match='signature_invalid'):
        verify_compiled_rpc_signatures(tx)


def test_raw_transaction_verification_is_pure_and_does_not_rewrite_receipt():
    tx,_=signed_fixture(v0=True)
    copy=deepcopy(tx)
    verify_compiled_rpc_signatures(tx)
    assert tx==copy
