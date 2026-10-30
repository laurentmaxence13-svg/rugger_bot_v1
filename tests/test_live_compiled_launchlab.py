"""Compiled outer/inner instruction decoding from RPC account indices."""
from copy import deepcopy
import pytest

from bot.live import compiled_launchlab as mod
from bot.p3.certification import PROGRAM, _encode
from bot.scanner.transaction_parser import _CREATE_DISCRIMINATORS

def key(n):
    return _encode(bytes([n]) * 32)

K = [PROGRAM] + [key(n) for n in range(11, 20)]

def fixture(monkeypatch, *, inner=False, program=0):
    monkeypatch.setattr(mod, "normalized_compiled_transaction",
        lambda _: dict(transaction=dict(message=dict(
            accountKeys=[dict(pubkey=k) for k in K]))))
    discriminator=sorted(_CREATE_DISCRIMINATORS)[0]
    instruction=dict(programIdIndex=program,
        accounts=[1, 2, 3, 4, 5, 6, 7],
        data=_encode(discriminator + b"\x00" * 10))
    return dict(meta=dict(err=None, innerInstructions=[
            dict(index=0, instructions=[instruction])] if inner else []),
        transaction=dict(message=dict(instructions=[
            dict(programIdIndex=8, accounts=[], data="") if inner else
            instruction])))

def test_compiled_signed_outer_creation(monkeypatch):
    tx=fixture(monkeypatch)
    launches=mod.compiled_launchlab_creations(tx)
    assert launches==[dict(payer=K[1],creator=K[2],
                          pool_state=K[6], mint=K[7])]

def test_inner_rpc_only_creation_can_be_found(monkeypatch):
    tx=fixture(monkeypatch,inner=True)
    assert len(mod.compiled_launchlab_creations(tx))==1
    tx["meta"]["innerInstructions"]=[]
    assert mod.compiled_launchlab_creations(tx)==[]

def test_non_launch_program_not_classified_as_creation(monkeypatch):
    tx=fixture(monkeypatch, program=8)
    assert mod.compiled_launchlab_creations(tx)==[]

def test_invalid_index_or_metadata_rejected(monkeypatch):
    tx=fixture(monkeypatch)
    tx["transaction"]["message"]["instructions"][0]["accounts"]=[1000]
    with pytest.raises(ValueError):
        mod.compiled_launchlab_creations(tx)
    tx=fixture(monkeypatch, inner=True)
    tx["meta"]["innerInstructions"][0]["index"]=9
    with pytest.raises(ValueError):
        mod.compiled_launchlab_creations(tx)

def test_failed_transaction_has_no_successful_creations(monkeypatch):
    tx=fixture(monkeypatch)
    tx["meta"]["err"]={"InstructionError":[0]}
    assert mod.compiled_launchlab_creations(tx)==[]
