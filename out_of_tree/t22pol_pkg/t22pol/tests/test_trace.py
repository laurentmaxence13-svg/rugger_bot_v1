"""t22pol.trace: synthetic creation transactions shaped like the archived ones (raw json, base58 data)."""
import json
import struct

import pytest

from t22pol import policy, trace

ALPH = trace._B58
SYSTEM, LAUNCHLAB = '11111111111111111111111111111111', 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
MINT, POOL, AUTH = 'Mint1111111111111111111111111111111111111111', 'PooL1111111111111111111111111111111111111111', \
    'Auth1111111111111111111111111111111111111111'


def b58(raw):
    n, out = int.from_bytes(raw, 'big'), ''
    while n:
        n, d = divmod(n, 58)
        out = ALPH[d] + out
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + out


def creation(inner, *, program=policy.TOKEN_2022_PROGRAM, err=None, loaded=False):
    """``inner``: (program, [accounts], data bytes) of the inner instructions of the LaunchLab call."""
    keys = [AUTH, MINT, POOL, SYSTEM, LAUNCHLAB, policy.TOKEN_PROGRAM]
    extra = [policy.TOKEN_2022_PROGRAM]
    all_keys = keys + extra
    if not loaded:
        keys = all_keys
    ix = lambda prog, accounts, data: dict(programIdIndex=all_keys.index(prog),
                                           accounts=[all_keys.index(a) for a in accounts], data=b58(data))
    meta = dict(err=err, innerInstructions=[dict(index=0, instructions=[ix(*one) for one in inner])],
                loadedAddresses=dict(writable=[], readonly=extra if loaded else []))
    return dict(slot=1, transaction=dict(message=dict(accountKeys=keys, instructions=[ix(LAUNCHLAB, [AUTH], b'\xe4')])),
                meta=meta)


T22 = policy.TOKEN_2022_PROGRAM
POINTER = (T22, [MINT], bytes([39, 0]) + bytes(64))
INIT2 = (T22, [MINT], bytes([20, 6]) + bytes(32) + b'\x00')
INIT2_FREEZE = (T22, [MINT], bytes([20, 6]) + bytes(32) + b'\x01' + bytes(32))
METADATA = (T22, [MINT, AUTH, MINT, AUTH], trace.METADATA_INITIALIZE + bytes(20))
MINT_TO = (T22, [MINT, POOL, AUTH], bytes([7]) + struct.pack('<Q', 10**15))
REVOKE = (T22, [MINT, AUTH], bytes([6, 0, 0]))


def fee(bps, with_keys=True):
    option = (b'\x01' + bytes(32)) if with_keys else b'\x00'
    return (T22, [MINT], bytes([26, 0]) + option + option + struct.pack('<HQ', bps, 10**12))


def test_the_archived_shape_is_allowlisted():
    row = trace.classify_trace(creation([POINTER, INIT2, METADATA, MINT_TO, REVOKE]), MINT)
    assert row['class_'] == 'token2022_allowlisted' and row['reasons'] == []
    assert row['extensions'] == ['MetadataPointer', 'TokenMetadata'] and row['our_account_rent_lamports'] == 2_074_080


def test_addresses_from_a_lookup_table_resolve():
    row = trace.classify_trace(creation([POINTER, INIT2, METADATA, MINT_TO, REVOKE], loaded=True), MINT)
    assert row['class_'] == 'token2022_allowlisted'


@pytest.mark.parametrize('bps,with_keys', [(300, True), (50, False)])
def test_transfer_fee_is_refused_and_its_rate_reported(bps, with_keys):
    row = trace.classify_trace(creation([POINTER, fee(bps, with_keys), INIT2, METADATA, MINT_TO, REVOKE]), MINT)
    assert row['class_'] == 'refused' and row['reasons'] == ['extension_refused:TransferFeeConfig']
    assert row['transfer_fee_bps'] == bps


@pytest.mark.parametrize('ix,name', [((T22, [MINT], bytes([35]) + bytes(32)), 'PermanentDelegate'),
                                     ((T22, [MINT], bytes([36, 0]) + bytes(64)), 'TransferHook'),
                                     ((T22, [MINT], bytes([28, 0, 2])), 'DefaultAccountState'),
                                     ((T22, [MINT], bytes([44, 0]) + bytes(32)), 'Pausable'),
                                     ((T22, [MINT], bytes([32])), 'NonTransferable'),
                                     ((T22, [MINT], bytes([25]) + bytes(33)), 'MintCloseAuthority')])
def test_dangerous_extensions_are_refused_by_name(ix, name):
    row = trace.classify_trace(creation([POINTER, ix, INIT2, METADATA, MINT_TO, REVOKE]), MINT)
    assert row['reasons'] == [f'extension_refused:{name}']


def test_authorities_and_unexpected_instructions_refuse():
    assert trace.classify_trace(creation([POINTER, INIT2_FREEZE, METADATA, MINT_TO, REVOKE]), MINT)['reasons'] == \
        ['freeze_authority_present']
    assert trace.classify_trace(creation([POINTER, INIT2, METADATA, MINT_TO]), MINT)['reasons'] == \
        ['mint_authority_not_revoked_at_creation']
    batch = (T22, [MINT], bytes([255, 1]))
    assert 'unexpected_instruction_on_mint:Batch' in trace.classify_trace(
        creation([POINTER, INIT2, METADATA, MINT_TO, REVOKE, batch]), MINT)['reasons']
    late = (T22, [MINT], bytes([39, 0]) + bytes(64))
    assert 'extension_after_mint_initialisation:MetadataPointer' in trace.classify_trace(
        creation([INIT2, late, METADATA, MINT_TO, REVOKE]), MINT)['reasons']


def test_classic_mint_is_executable_now():
    spl = policy.TOKEN_PROGRAM
    row = trace.classify_trace(creation([(spl, [MINT], bytes([20, 6]) + bytes(32) + b'\x00'),
                                         (spl, [MINT, POOL, AUTH], bytes([7]) + bytes(8)),
                                         (spl, [MINT, AUTH], bytes([6, 0, 0]))]), MINT)
    assert row['class_'] == 'executable_now' and row['our_account_rent_lamports'] == 2_039_280


def test_missing_failed_or_unreadable_traces_refuse():
    assert trace.classify_trace(None, MINT)['reasons'] == ['creation_transaction_missing']
    assert trace.classify_trace(creation([INIT2], err={'x': 1}), MINT)['reasons'] == ['creation_transaction_failed']
    no_inner = creation([INIT2])
    no_inner['meta']['innerInstructions'] = None
    assert trace.classify_trace(no_inner, MINT)['reasons'][0].startswith('creation_trace_unreadable')
    assert trace.classify_trace(creation([POINTER]), MINT)['reasons'] == ['mint_initialisation_not_in_creation_trace']


def test_census_output_feeds_the_scenarios(tmp_path, capsys):
    pools = [dict(pool='p1', mint=MINT, creation_transaction=creation([POINTER, INIT2, METADATA, MINT_TO, REVOKE])),
             dict(pool='p2', mint=MINT, creation_transaction=creation([POINTER, fee(100), INIT2, METADATA, MINT_TO,
                                                                       REVOKE]))]
    path = tmp_path / 'p.json'
    path.write_text(json.dumps(dict(pools=pools)))
    assert trace.main([str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['schema'] == 't22pol-census-v1' and out['source'] == 'creation_trace'
    assert out['classes'] == {'refused': 1, 'token2022_allowlisted': 1}
    assert out['extension_sets'] == {'MetadataPointer + TokenMetadata': 1,
                                     'MetadataPointer + TransferFeeConfig + TokenMetadata': 1}
