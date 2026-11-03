"""DETERMINISTIC, UNFUNDED test-only Ed25519 migration signatures.

The synthetic LaunchLab historical transaction needs TWO signer keys: the
payer and a random CPMM pool account. Both have fixed, publicly exposed
test-only seeds in this module. No API key, wallet seed or real balance
is ever used. These fixtures are unsuitable for signing financial orders.
"""
from copy import deepcopy

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from bot.p3.certification import _encode
from bot.live.solana_signatures import compiled_message_bytes,verify_compiled_rpc_signatures
from test_live_migration_rpc_json import _compiled
from test_live_cpmm_exit import POOL


_TEST_PAYER=Ed25519PrivateKey.from_private_bytes(bytes([83])*32)
_TEST_POOL=Ed25519PrivateKey.from_private_bytes(bytes([84])*32)


def signed_rpc_migration(parsed):
    tx=_compiled(deepcopy(parsed))
    keys=tx['transaction']['message']['accountKeys']
    payer=_encode(_TEST_PAYER.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw))
    pool=_encode(_TEST_POOL.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw))
    assert pool==POOL
    assert keys[1]==POOL, 'noncanonical CPMM pool must be the second signer'
    assert tx['transaction']['message']['header']['numRequiredSignatures']==2
    keys[0]=payer
    tx['transaction']['message']['recentBlockhash']=_encode(bytes([7])*32)
    message=compiled_message_bytes(tx)
    first=_encode(_TEST_PAYER.sign(message))
    second=_encode(_TEST_POOL.sign(message))
    tx['transaction']['signatures']=[first,second]
    assert verify_compiled_rpc_signatures(tx)['cryptographic_signatures_verified']
    return tx,first
