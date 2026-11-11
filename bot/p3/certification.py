"""Offline identity checks against the published Raydium LaunchLab IDL.

Public program-derived addresses (PDAs) are hashes of public seeds, never
wallets or signing keys. These checks certify only the supplied account graph
against this pinned schema, not a deployed binary, transfer policy or fill.
"""
import base64
import hashlib
import struct


PROGRAM = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
TOKEN_PROGRAMS = frozenset((
    'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
    'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'))
ROLES = ('pool', 'config', 'platform', 'mint_a', 'mint_b', 'vault_a', 'vault_b')
DISCRIMINATORS = {
    'pool': bytes.fromhex('f7ede3f5d7c3de46'),
    'config': bytes.fromhex('95089ccaa0fcb0d9'),
    'platform': bytes.fromhex('a04e8000f853e6a0'),
}
SOURCE_PINS = {
    'repository': 'https://github.com/raydium-io/raydium-idl',
    'commit': 'e7e0c96fe77bcf6a020b84a44c47a722aac8e359',
    'path': 'raydium_launchpad/raydium_launchpad.json',
    'git_blob': '70186e3f02c2bead7e5a9a92453104df853683ed',
    'sha256': '963189409945069409f32e345d4adf2892e0b3ca1be504372577fe34a23c6cdb',
}
_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def _decode(address):
    if type(address) is not str or not 32 <= len(address) <= 44:
        raise ValueError('invalid_public_address')
    number = 0
    try:
        for character in address:
            number = number * 58 + _BASE58.index(character)
    except ValueError:
        raise ValueError('invalid_public_address') from None
    leading = len(address) - len(address.lstrip('1'))
    size = (number.bit_length() + 7) // 8
    if leading + size != 32:
        raise ValueError('invalid_public_address')
    return b'\0' * leading + number.to_bytes(size, 'big')


def _encode(raw):
    number, text = int.from_bytes(raw, 'big'), ''
    while number:
        number, index = divmod(number, 58)
        text = _BASE58[index] + text
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + text


def edwards_y_decompresses(encoded):
    """Curve25519-dalek CompressedEdwardsY *existence*, not subgroup validity.

    Solana rejects a PDA hash if this decompression succeeds. The top bit is an
    x sign, irrelevant to existence. Dalek's field decoding reduces the remaining
    y modulo p; it accepts small-order points and noncanonical/negative-zero
    encodings. A strict Ed25519 signature/subgroup validator is unsuitable here.
    Existence is exactly whether (y²-1)/(d*y²+1) has a square root in F_p.
    """
    if type(encoded) is not bytes or len(encoded) != 32:
        raise ValueError('compressed_point_requires_32_bytes')
    y = (int.from_bytes(encoded, 'little') & (2**255 - 1)) % _P
    square = y * y % _P
    denominator = (_D * square + 1) % _P
    if denominator == 0:
        return False
    ratio = (square - 1) * pow(denominator, _P - 2, _P) % _P
    return ratio == 0 or pow(ratio, (_P - 1) // 2, _P) == 1


def find_program_address(seeds, program_id=PROGRAM):
    """Find the canonical descending Solana bump for public seed bytes only."""
    if (type(seeds) not in (list, tuple) or len(seeds) > 15
            or any(type(seed) is not bytes or len(seed) > 32 for seed in seeds)):
        raise ValueError('invalid_public_PDA_seeds')
    program = _decode(program_id)
    for bump in range(255, -1, -1):
        value = hashlib.sha256(b''.join(seeds) + bytes([bump])
                               + program + b'ProgramDerivedAddress').digest()
        if not edwards_y_decompresses(value):
            return _encode(value), bump
    raise ValueError('no_public_PDA_bump')


def certify_snapshot(accounts, addresses):
    """Check discriminators and derivable PDAs without any fetching or mutation.

    GlobalConfig's index is stored LE. The downloaded IDL identifies its PDA
    seeds but does not resolve SDK helper byte order for a nonzero index, so
    only index=0 is certified here. PlatformConfig does not retain an explicit
    original platform_admin field. Its public fee wallet is tested only as a
    candidate seed: exact canonical PDA equality proves the seed for that
    address; a mismatch remains UNKNOWN and never implies an invalid platform.
    """
    checks = []

    def check(name, status, reason=None, **facts):
        item = {'name': name, 'status': status, **facts}
        if reason is not None:
            item['reason'] = reason
        checks.append(item)

    def finish():
        by_name = {item['name']: item['status'] for item in checks}
        pda_names = ('pool_pda', 'vault_a_pda', 'vault_b_pda', 'config_pda', 'authority_pda', 'platform_pda')
        return {
            'schema': 'p3-launchlab-identity-certification-v1',
            'account_discriminators_verified': all(
                by_name.get(role + '_discriminator') == 'PASS' for role in DISCRIMINATORS),
            'program_derived_addresses_verified': all(by_name.get(name) == 'PASS' for name in pda_names),
            'program_derived_addresses_partially_verified': any(
                by_name.get(name) == 'PASS' for name in pda_names),
            'checks': checks,
            'blocking_reasons': [item.get('reason', item['name'] + '_unverified')
                                 for item in checks if item['status'] != 'PASS'],
            'source_pins': dict(SOURCE_PINS),
            'scope': 'pinned account identity only; no transfer, execution or binary certification',
            'execution_verified': False,
        }

    if type(accounts) is not dict or type(addresses) is not dict:
        check('input_graph', 'UNKNOWN', 'account_graph_missing')
        return finish()
    try:
        public = {role: _decode(addresses.get(role)) for role in ROLES}
    except ValueError:
        check('input_graph', 'FAIL', 'account_graph_public_identity_invalid')
        return finish()
    if len(set(public.values())) != len(ROLES):
        check('input_graph', 'FAIL', 'account_graph_identity_duplicated')
        return finish()
    check('input_graph', 'PASS')

    def raw_account(role, owners, *, length=None, minimum=None):
        account = accounts.get(addresses[role])
        if type(account) is not dict:
            check(role + '_layout_owner', 'UNKNOWN', role + '_account_missing')
            return None
        if account.get('owner') not in owners or account.get('executable') is not False:
            check(role + '_layout_owner', 'FAIL', role + '_owner_or_executable_invalid')
            return None
        data = account.get('data')
        if (type(data) not in (list, tuple) or len(data) != 2 or data[1] != 'base64'
                or type(data[0]) is not str or len(data[0]) > 20_000):
            check(role + '_layout_owner', 'FAIL', role + '_encoding_invalid')
            return None
        try:
            raw = base64.b64decode(data[0], validate=True)
        except (ValueError, TypeError):
            check(role + '_layout_owner', 'FAIL', role + '_encoding_invalid')
            return None
        if ((length is not None and len(raw) != length)
                or (minimum is not None and len(raw) < minimum)):
            check(role + '_layout_owner', 'UNKNOWN', role + '_layout_outside_pinned_scope')
            return None
        check(role + '_layout_owner', 'PASS')
        return raw

    data = {}
    for role, length in (('pool', 429), ('config', 371), ('platform', 944)):
        data[role] = raw_account(role, (PROGRAM,), length=length)
        raw = data[role]
        if raw is not None:
            if raw[:8] == DISCRIMINATORS[role]:
                check(role + '_discriminator', 'PASS')
            else:
                check(role + '_discriminator', 'FAIL', role + '_discriminator_mismatch')
                data[role] = None
    if data['platform'] is not None:
        count = struct.unpack_from('<I', data['platform'], 940)[0]
        check('platform_empty_curve_params', 'PASS' if count == 0 else 'FAIL',
              None if count == 0 else 'platform_curve_vector_length_inconsistent')

    if data['pool'] is not None:
        for role, offset in (('config', 141), ('platform', 173), ('mint_a', 205),
                             ('mint_b', 237), ('vault_a', 269), ('vault_b', 301)):
            matches = data['pool'][offset:offset+32] == public[role]
            check('pool_link_' + role, 'PASS' if matches else 'FAIL',
                  None if matches else 'pool_link_' + role + '_mismatch')

    mint_programs = {}
    for role in ('mint_a', 'mint_b'):
        account = accounts.get(addresses[role])
        owner = account.get('owner') if type(account) is dict else None
        valid = type(owner) is str and owner in TOKEN_PROGRAMS and account.get('executable') is False
        check(role + '_program_owner', 'PASS' if valid else 'UNKNOWN',
              None if valid else role + '_program_owner_unverified')
        if valid:
            mint_programs[role] = owner
    for vault, mint in (('vault_a', 'mint_a'), ('vault_b', 'mint_b')):
        owners = (mint_programs[mint],) if mint in mint_programs else ()
        # Exactly 165 bytes, the rule of bot.p3.token2022.decode_vault (R02 O-T1): a vault carrying an
        # account extension (e.g. TransferFeeAmount, 178 bytes) is outside the pinned scope.
        data[vault] = raw_account(vault, owners, length=165)
        if data[vault] is not None:
            matches = data[vault][:32] == public[mint]
            check(vault + '_mint_link', 'PASS' if matches else 'FAIL',
                  None if matches else vault + '_mint_mismatch')

    def derive(name, seeds, expected):
        calculated, bump = find_program_address(seeds)
        matches = calculated == expected
        check(name, 'PASS' if matches else 'FAIL', None if matches else name + '_mismatch',
              derived_address=calculated, bump=bump)
        return calculated, bump

    if data['pool'] is not None:
        derive('pool_pda', (b'pool', public['mint_a'], public['mint_b']), addresses['pool'])
        for vault, mint in (('vault_a', 'mint_a'), ('vault_b', 'mint_b')):
            if data[vault] is not None:
                derive(vault + '_pda', (b'pool_vault', public['pool'], public[mint]), addresses[vault])
        authority, bump = find_program_address((b'vault_auth_seed',))
        vaults = [data['vault_a'], data['vault_b']]
        if any(vault is None for vault in vaults):
            check('authority_pda', 'UNKNOWN', 'vault_authority_data_missing')
        else:
            matches = data['pool'][16] == bump and all(
                vault[32:64] == _decode(authority) for vault in vaults)
            check('authority_pda', 'PASS' if matches else 'FAIL',
                  None if matches else 'vault_authority_or_pool_auth_bump_mismatch',
                  derived_address=authority, bump=bump)
    config = data['config']
    if config is not None:
        quote_matches = config[83:115] == public['mint_b']
        check('config_quote_link', 'PASS' if quote_matches else 'FAIL',
              None if quote_matches else 'config_quote_mint_mismatch')
        index = struct.unpack_from('<H', config, 17)[0]
        if index == 0:
            derive('config_pda', (b'global_config', public['mint_b'], config[16:17], b'\0\0'),
                   addresses['config'])
        else:
            check('config_pda', 'UNKNOWN', 'nonzero_config_index_seed_byte_order_not_certified')
    platform = data['platform']
    if platform is None:
        check('platform_pda', 'UNKNOWN', 'original_platform_admin_seed_not_retained')
    else:
        candidate = platform[16:48]
        calculated, bump = find_program_address((b'platform_config', candidate))
        matches = calculated == addresses['platform']
        check('platform_pda', 'PASS' if matches else 'UNKNOWN',
              None if matches else 'original_platform_admin_seed_not_retained',
              candidate_seed_source='PlatformConfig.platform_fee_wallet',
              candidate_assumed_to_be_admin=False, candidate_public_key=_encode(candidate),
              candidate_hash_matched=matches, verification_basis='canonical_PDA_hash_equality_only',
              derived_address=calculated, bump=bump)
    return finish()
