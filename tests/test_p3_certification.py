"""Synthetic identity graphs and published program/RFC curve vectors only."""
import base64
import copy
import json
import struct

import pytest

from bot.p3 import certification as cert


def encode(raw):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number, chars = int.from_bytes(raw, 'big'), ''
    while number:
        number, digit = divmod(number, 58)
        chars = alphabet[digit] + chars
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + chars


def fixture():
    # Synthetic mint identifiers. No captured token, ledger or network fixture.
    mint_a, mint_b = encode(bytes([1])*32), encode(bytes([2])*32)
    pool, _ = cert.find_program_address((b'pool', bytes([1])*32, bytes([2])*32))
    config, _ = cert.find_program_address((b'global_config', bytes([2])*32, b'\0', b'\0\0'))
    pool_raw = cert._decode(pool)
    vault_a, _ = cert.find_program_address((b'pool_vault', pool_raw, bytes([1])*32))
    vault_b, _ = cert.find_program_address((b'pool_vault', pool_raw, bytes([2])*32))
    platform = encode(bytes([3])*32)
    addresses = dict(pool=pool, config=config, platform=platform, mint_a=mint_a,
                     mint_b=mint_b, vault_a=vault_a, vault_b=vault_b)
    authority, bump = cert.find_program_address((b'vault_auth_seed',))
    pool_data, config_data, platform_data = bytearray(429), bytearray(371), bytearray(944)
    for role, data in (('pool', pool_data), ('config', config_data), ('platform', platform_data)):
        data[:8] = cert.DISCRIMINATORS[role]
    pool_data[16] = bump
    for role, offset in (('config',141), ('platform',173), ('mint_a',205),
                         ('mint_b',237), ('vault_a',269), ('vault_b',301)):
        pool_data[offset:offset+32] = cert._decode(addresses[role])
    config_data[83:115] = bytes([2])*32
    va, vb = bytearray(165), bytearray(165)
    for raw, mint in ((va, bytes([1])*32), (vb, bytes([2])*32)):
        raw[:32], raw[32:64], raw[108] = mint, cert._decode(authority), 1
    raws = dict(pool=pool_data, config=config_data, platform=platform_data,
                mint_a=bytearray(82), mint_b=bytearray(82), vault_a=va, vault_b=vb)
    accounts = {}
    token = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
    for role, raw in raws.items():
        accounts[addresses[role]] = {'owner':cert.PROGRAM if role in cert.DISCRIMINATORS else token,
            'executable':False,'data':[base64.b64encode(raw).decode(),'base64']}
    return accounts, addresses


def replace(accounts, address, offset, replacement):
    raw = bytearray(base64.b64decode(accounts[address]['data'][0]))
    raw[offset:offset+len(replacement)] = replacement
    accounts[address]['data'][0] = base64.b64encode(raw).decode()


def statuses(report):
    return {item['name']:item['status'] for item in report['checks']}


def test_published_authority_PDA_matches_independent_source_observation():
    # Published-program address, not a user wallet or captured market fixture.
    assert cert.find_program_address((b'vault_auth_seed',)) == (
        'WLHv2UAZm6z4KyaaELi5pjdbJh6RESMva1Rnn8pJVVh', 250)


def test_curve_decompression_accepts_RFC8032_and_small_order_dalek_encodings():
    assert cert.edwards_y_decompresses(bytes.fromhex(
        'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'))
    assert cert.edwards_y_decompresses(bytes(32))  # small-order point
    assert cert.edwards_y_decompresses((1).to_bytes(32,'little'))  # identity
    assert cert.edwards_y_decompresses((1 + 2**255).to_bytes(32,'little'))  # negative zero
    assert cert.edwards_y_decompresses((2**255-18).to_bytes(32,'little'))  # noncanonical y=p+1
    assert not cert.edwards_y_decompresses((2).to_bytes(32,'little'))


def test_valid_synthetic_graph_certifies_known_roles_but_never_invents_platform_seed():
    accounts, addresses = fixture()
    retained = copy.deepcopy(accounts)
    report = cert.certify_snapshot(accounts, addresses)
    assert report['account_discriminators_verified'] is True
    assert report['program_derived_addresses_partially_verified'] is True
    assert report['program_derived_addresses_verified'] is False
    assert report['blocking_reasons'] == ['original_platform_admin_seed_not_retained']
    for name in ('pool_pda','config_pda','vault_a_pda','vault_b_pda','authority_pda'):
        assert statuses(report)[name] == 'PASS'
    assert statuses(report)['platform_pda'] == 'UNKNOWN'
    assert accounts == retained
    assert report['execution_verified'] is False
    json.dumps(report, allow_nan=False)


def test_platform_fee_wallet_candidate_certifies_only_on_exact_canonical_hash_match():
    accounts, addresses = fixture()
    candidate = bytes([9])*32
    platform, _ = cert.find_program_address((b'platform_config', candidate))
    accounts[platform] = accounts.pop(addresses['platform'])
    addresses['platform'] = platform
    replace(accounts, platform, 16, candidate)
    replace(accounts, addresses['pool'], 173, cert._decode(platform))
    report = cert.certify_snapshot(accounts, addresses)
    platform_check = next(c for c in report['checks'] if c['name'] == 'platform_pda')
    assert report['program_derived_addresses_verified'] is True
    assert report['blocking_reasons'] == []
    assert platform_check['status'] == 'PASS'
    assert platform_check['candidate_seed_source'] == 'PlatformConfig.platform_fee_wallet'
    assert platform_check['candidate_assumed_to_be_admin'] is False
    assert platform_check['candidate_hash_matched'] is True
    # A different fee wallet is allowed by the platform schema; it cannot
    # disprove the original administrator or make an otherwise valid PDA FAIL.
    replace(accounts, platform, 16, bytes([7])*32)
    report = cert.certify_snapshot(accounts, addresses)
    platform_check = next(c for c in report['checks'] if c['name'] == 'platform_pda')
    assert report['program_derived_addresses_verified'] is False
    assert platform_check['status'] == 'UNKNOWN'
    assert platform_check['candidate_hash_matched'] is False
    assert report['blocking_reasons'] == ['original_platform_admin_seed_not_retained']


def test_owner_and_discriminator_are_independent_of_matching_public_PDA():
    accounts, addresses = fixture()
    accounts[addresses['pool']]['owner'] = addresses['mint_a']
    report = cert.certify_snapshot(accounts, addresses)
    assert not report['account_discriminators_verified']
    assert 'pool_owner_or_executable_invalid' in report['blocking_reasons']
    accounts, addresses = fixture()
    replace(accounts, addresses['config'], 0, b'BAD!TYPE')
    report = cert.certify_snapshot(accounts, addresses)
    assert not report['account_discriminators_verified']
    assert statuses(report)['config_discriminator'] == 'FAIL'


def test_raw_pool_links_cannot_be_substituted_even_if_other_PDA_inputs_match():
    accounts, addresses = fixture()
    replace(accounts, addresses['pool'], 269, bytes([9])*32)
    assert statuses(cert.certify_snapshot(accounts, addresses))['pool_link_vault_a'] == 'FAIL'


def test_vault_authority_and_pool_bump_both_need_canonical_PDA():
    accounts, addresses = fixture()
    replace(accounts, addresses['vault_a'], 32, bytes([7])*32)
    assert statuses(cert.certify_snapshot(accounts, addresses))['authority_pda'] == 'FAIL'
    accounts, addresses = fixture()
    replace(accounts, addresses['pool'], 16, bytes([249]))
    assert statuses(cert.certify_snapshot(accounts, addresses))['authority_pda'] == 'FAIL'


def test_nonzero_config_index_remains_unknown_and_malformed_platform_vec_fails():
    accounts, addresses = fixture()
    replace(accounts, addresses['config'], 17, struct.pack('<H', 1))
    report = cert.certify_snapshot(accounts, addresses)
    assert statuses(report)['config_pda'] == 'UNKNOWN'
    assert 'nonzero_config_index_seed_byte_order_not_certified' in report['blocking_reasons']
    replace(accounts, addresses['platform'], 940, struct.pack('<I', 1))
    report = cert.certify_snapshot(accounts, addresses)
    assert statuses(report)['platform_empty_curve_params'] == 'FAIL'


def test_missing_invalid_and_duplicate_graph_identities_never_certify():
    assert not cert.certify_snapshot(None, {})['account_discriminators_verified']
    accounts, addresses = fixture()
    addresses['mint_a'] = addresses['mint_b']
    report = cert.certify_snapshot(accounts, addresses)
    assert report['blocking_reasons'] == ['account_graph_identity_duplicated']
    addresses['mint_a'] = 'not a public key'
    assert not cert.certify_snapshot(accounts, addresses)['program_derived_addresses_verified']
    accounts, addresses = fixture()
    accounts[addresses['mint_a']]['owner'] = {'invalid': 'owner'}
    assert statuses(cert.certify_snapshot(accounts, addresses))['mint_a_program_owner'] == 'UNKNOWN'


def test_wrong_vault_program_or_mint_link_cannot_claim_authority_certification():
    accounts, addresses = fixture()
    accounts[addresses['vault_a']]['owner'] = cert.PROGRAM
    report = cert.certify_snapshot(accounts, addresses)
    assert statuses(report)['vault_a_layout_owner'] == 'FAIL'
    assert statuses(report)['authority_pda'] == 'UNKNOWN'
    accounts, addresses = fixture()
    replace(accounts, addresses['vault_b'], 0, bytes([9])*32)
    assert statuses(cert.certify_snapshot(accounts, addresses))['vault_b_mint_link'] == 'FAIL'


def test_public_seed_limits_and_wrong_compressed_length_refuse():
    for seeds in ((b'x'*33,), (b'',)*16, ('string',), b'wrong-container'):
        with pytest.raises(ValueError):
            cert.find_program_address(seeds)
    with pytest.raises(ValueError):
        cert.edwards_y_decompresses(b'wrong')
