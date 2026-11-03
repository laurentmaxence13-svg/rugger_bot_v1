"""Decode LaunchLab create candidates from the EXACT compiled RPC message.

Use this only after independent Ed25519 verification of that message. A
jsonParsed transaction can corroborate, but never invent, a candidate that
is absent from the signed compiled instruction stream. Inner instructions
are execution metadata of the same receipt and remain RPC-attested, not
part of the Ed25519-signed message.
"""
from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.scanner.transaction_parser import find_raydium_launches


def compiled_launchlab_creations(tx):
    if type(tx) is not dict or type(tx.get("meta")) is not dict:
        raise ValueError("compiled_creation_transaction_required")
    if tx["meta"].get("err") is not None:
        return []
    normalized = normalized_compiled_transaction(tx)
    keys = [k["pubkey"] for k in
            normalized["transaction"]["message"]["accountKeys"]]
    msg = tx["transaction"]["message"]
    outer = msg.get("instructions")
    if type(outer) is not list or len(outer) > 1024:
        raise ValueError("compiled_creation_outer_instructions_invalid")

    def reconstruct(ix):
        if type(ix) is not dict:
            raise ValueError("compiled_creation_instruction_invalid")
        program = ix.get("programIdIndex")
        refs = ix.get("accounts")
        data = ix.get("data")
        if (type(program) is not int or not 0 <= program < len(keys) or
                type(refs) is not list or len(refs) > 255 or
                any(type(i) is not int or not 0 <= i < len(keys)
                    for i in refs) or type(data) is not str):
            raise ValueError("compiled_creation_indices_invalid")
        return dict(programId=keys[program],
                    accounts=[keys[i] for i in refs], data=data)

    inner = tx["meta"].get("innerInstructions") or []
    if type(inner) is not list or len(inner) > 1024:
        raise ValueError("compiled_creation_inner_instructions_invalid")
    converted = []
    for group in inner:
        if (type(group) is not dict or
                type(group.get("index")) is not int or
                not 0 <= group["index"] < len(outer) or
                type(group.get("instructions")) is not list or
                len(group["instructions"]) > 1024):
            raise ValueError("compiled_creation_inner_group_invalid")
        converted.append(dict(index=group["index"],
                              instructions=[reconstruct(i)
                                            for i in group["instructions"]]))
    frame = dict(transaction=dict(message=dict(
                     instructions=[reconstruct(i) for i in outer])),
                 meta=dict(err=None, innerInstructions=converted))
    return find_raydium_launches(frame)
