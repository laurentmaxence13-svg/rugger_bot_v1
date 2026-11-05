"""Read-only Solana upgradeable Program/ProgramData pin verification.

No private keys, transaction send, wallet arming or trading authorization.
Uses loader-v3 Program=36-byte and ProgramData=45-byte header layouts.
"""
import base64
import hashlib
import struct

from bot.p3.certification import _decode, _encode, find_program_address

LOADER="BPFLoaderUpgradeab1e11111111111111111111111"


def _raw(item, *, executable, size=None):
    if (type(item) is not dict or item.get("owner") != LOADER
            or item.get("executable") is not executable
            or type(item.get("lamports")) is not int or item["lamports"]<=0):
        raise ValueError("program_owner_or_executable_invalid")
    encoded=item.get("data")
    if (type(encoded) is not list or len(encoded)!=2 or encoded[1]!="base64"
            or type(encoded[0]) is not str or len(encoded[0])>5_400_000):
        raise ValueError("program_data_encoding_invalid")
    try:
        data=base64.b64decode(encoded[0],validate=True)
    except (ValueError,base64.binascii.Error):
        raise ValueError("invalid_program_base64") from None
    if (len(data)>4_000_000 or
            base64.b64encode(data).decode()!=encoded[0] or
            size is not None and len(data)!=size):
        raise ValueError("program_data_size_or_encoding_invalid")
    if item.get("space",len(data))!=len(data):
        raise ValueError("program_reported_space_mismatch")
    return data


def _programdata_address(raw,program_id):
    if raw[:4]!=struct.pack("<I",2):
        raise ValueError("program_variant_invalid")
    actual=_encode(raw[4:])
    expected,_=find_program_address((_decode(program_id),),program_id=LOADER)
    if actual!=expected:
        raise ValueError("programdata_PDA_mismatch")
    return actual


def _details(raw,bank_slot):
    if len(raw)<=49 or raw[:4]!=struct.pack("<I",3):
        raise ValueError("programdata_variant_missing")
    upgraded=struct.unpack_from("<Q",raw,4)[0]
    if not 0<upgraded<bank_slot:
        raise ValueError("program_upgrade_slot_not_active")
    if raw[12]==0 and raw[13:45]==bytes(32):
        authority=None
    elif raw[12]==1:
        authority=_encode(raw[13:45])
    else:
        raise ValueError("programdata_authority_tag_invalid")
    if raw[45:49]!=b"\x7fELF":
        raise ValueError("programdata_ELF_missing")
    return dict(deployment_slot=upgraded,upgrade_authority=authority,
        programdata_sha256=hashlib.sha256(raw).hexdigest(),
        elf_sha256=hashlib.sha256(raw[45:]).hexdigest())


async def attest_program_pin(rpc, *, program_id, expected_endpoint_sha256,
        expected_genesis_hash, min_context_slot, expected_deployment_slot,
        expected_programdata_sha256, expected_elf_sha256,
        expected_upgrade_authority):
    """Confirm two banks agree on immutable pointer and a full explicit pin."""
    _decode(program_id);_decode(expected_genesis_hash)
    if expected_upgrade_authority is not None:
        _decode(expected_upgrade_authority)
    pins=(expected_endpoint_sha256,expected_programdata_sha256,expected_elf_sha256)
    if (any(type(p) is not str or len(p)!=64
            or any(c not in "0123456789abcdef" for c in p) for p in pins)
            or type(min_context_slot) is not int or min_context_slot<=0
            or type(expected_deployment_slot) is not int or expected_deployment_slot<=0):
        raise ValueError("complete_explicit_program_pins_required")
    if getattr(rpc,"endpoint_sha256",None)!=expected_endpoint_sha256:
        raise ValueError("program_endpoint_changed")
    if await rpc.genesis_hash()!=expected_genesis_hash:
        raise ValueError("program_cluster_changed")
    first=await rpc.get_multiple_accounts([program_id],min_context_slot=min_context_slot)
    slot_a=first["context"]["slot"]
    if type(slot_a) is not int or slot_a<min_context_slot:
        raise ValueError("first_bank_slot_invalid")
    program_a=_raw(first["value"][0],executable=True,size=36)
    pd_addr=_programdata_address(program_a,program_id)
    second=await rpc.get_multiple_accounts([program_id,pd_addr],
        min_context_slot=slot_a)
    slot_b=second["context"]["slot"]
    if type(slot_b) is not int or slot_b<slot_a:
        raise ValueError("joint_bank_slot_invalid")
    program_b=_raw(second["value"][0],executable=True,size=36)
    if program_a!=program_b or _programdata_address(program_b,program_id)!=pd_addr:
        raise ValueError("program_pointer_changed")
    pd=_raw(second["value"][1],executable=False)
    actual=_details(pd,slot_b)
    if actual!=dict(deployment_slot=expected_deployment_slot,
            upgrade_authority=expected_upgrade_authority,
            programdata_sha256=expected_programdata_sha256,
            elf_sha256=expected_elf_sha256):
        raise ValueError("program_code_or_upgrade_pin_mismatch")
    return dict(result="PIN_MATCHED_READ_ONLY",program_id=program_id,
        programdata_address=pd_addr,first_bank_slot=slot_a,joint_bank_slot=slot_b,
        **actual,live_execution_authorized=False,source_build_verified=False,
        independent_RPC_consensus_verified=False,live_ready_to_arm=False)
