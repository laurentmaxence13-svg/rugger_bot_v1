"""Read-only LaunchLab account facts and conditional native-SOL curve arithmetic.

No account is fetched, transaction built, wallet used, or ledger mutated here.
SDK layout/rounding sources are pinned by content hash below. Account
discriminator names are NOT certified by that SDK (it skips the first 8 bytes):
without independently audited pins identity remains partial and admission blocked.
"""
import base64
from fractions import Fraction
import hashlib
import struct

from bot.p3.quotes import SOL_MINT, _mint
from bot.p3.token2022 import decode_mint, decode_vault, TokenEvidenceError
from bot.p3.certification import certify_snapshot, DISCRIMINATORS

LAUNCHLAB_PROGRAM = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022_PROGRAM = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
FEE_DENOMINATOR = 1_000_000
_U64_MAX = (1 << 64) - 1
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
ACCOUNT_ROLES = ('pool', 'config', 'platform', 'mint_a', 'mint_b', 'vault_a', 'vault_b')
SOURCE_SHA256 = {
    'layout.ts': 'a422af7572b3b0f567ff7ad39f4b099eaf8a551257a77f89a61a3fe603ec2256',
    'curve/curve.ts': '2b5019678a8a4970f0f11645e2c15ea2d969b3b17f94d136191a952ea3ee2dfa',
    'curve/constantProductCurve.ts': 'd8004455490cf3742472889a1c981e9f3faeda03c74f27bdc789b88e2831dc66',
    'common/fee.ts': 'a4ee15c1375f8470824b81418c19c1656f52ce9db1c9116076018159efab6551',
    'common/bignumber.ts': 'a879be4768e747cff2465a85262136bfb9cb046eab4f32893bc571bf31705f11',
}
SOURCE_REPOSITORY = 'https://github.com/raydium-io/raydium-sdk-V2'


class SnapshotEvidenceError(ValueError):
    pass


def _uint(value, name, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= _U64_MAX:
        raise SnapshotEvidenceError('invalid_' + name)
    return value


def _b58(raw):
    number = int.from_bytes(raw, 'big')
    value = ''
    while number:
        number, digit = divmod(number, 58)
        value = _B58[digit] + value
    return '1' * (len(raw)-len(raw.lstrip(b'\0'))) + value


def _u64(data, offset):
    return struct.unpack_from('<Q', data, offset)[0]


def _key(data, offset):
    return _b58(data[offset:offset+32])


def _account(account, owner, span, kind):
    if (not isinstance(account, dict) or account.get('owner') != owner
            or account.get('executable') is not False):
        raise SnapshotEvidenceError(kind + '_owner_or_executable_invalid')
    data = account.get('data')
    if (not isinstance(data, (list, tuple)) or len(data) != 2 or data[1] != 'base64'
            or not isinstance(data[0], str) or len(data[0]) > 20_000):
        raise SnapshotEvidenceError(kind + '_encoding_invalid')
    try:
        raw = base64.b64decode(data[0], validate=True)
    except (ValueError, TypeError):
        raise SnapshotEvidenceError(kind + '_encoding_invalid') from None
    if len(raw) != span:
        raise SnapshotEvidenceError(kind + '_unsupported_layout_length')
    return raw


def _pool(account):
    data = _account(account, LAUNCHLAB_PROGRAM, 429, 'pool')
    result = {'discriminator_hex': data[:8].hex(), 'status': data[17],
              'decimals_a': data[18], 'decimals_b': data[19],
              'migrate_type': data[20], 'mint_program_flag': data[365],
              'cpmm_creator_fee_on': data[366]}
    for index, name in enumerate(('supply', 'total_sell_a', 'virtual_a', 'virtual_b',
                                  'real_a', 'real_b', 'total_fundraising_b',
                                  'protocol_fee_accrued', 'platform_fee_accrued', 'migrate_fee')):
        result[name] = _u64(data, 21+index*8)
    result['locked_base_amount'] = _u64(data, 101)
    for role, offset in (('config',141), ('platform',173), ('mint_a',205),
                         ('mint_b',237), ('vault_a',269), ('vault_b',301), ('creator',333)):
        result[role] = _key(data, offset)
    return result, data


def addresses_from_pool(raw_account, expected_mint, pool_address):
    """Discover addresses only; this does not certify account discriminator."""
    try:
        _mint(expected_mint)
        _mint(pool_address)
    except ValueError:
        raise SnapshotEvidenceError('invalid_public_address') from None
    pool, _ = _pool(raw_account)
    if pool['mint_a'] != expected_mint:
        raise SnapshotEvidenceError('pool_base_mint_mismatch')
    addresses = {role: pool[role] for role in ACCOUNT_ROLES if role != 'pool'}
    addresses['pool'] = pool_address
    return {role: addresses[role] for role in ACCOUNT_ROLES}


def _config(account):
    data = _account(account, LAUNCHLAB_PROGRAM, 371, 'config')
    return {'discriminator_hex': data[:8].hex(), 'curve_type': data[16],
            'trade_fee_rate_ppm': _u64(data,27), 'max_share_fee_rate_ppm': _u64(data,35),
            'quote_mint': _key(data,83)}, data


def _platform(account):
    data = _account(account, LAUNCHLAB_PROGRAM, 944, 'platform')
    return {'discriminator_hex': data[:8].hex(), 'platform_fee_rate_ppm': _u64(data,104),
            'creator_fee_rate_ppm': _u64(data,720)}, data


def _mint_state(account, kind, *, metadata_only=False, expected_address=None):
    if isinstance(account,dict) and account.get('owner') == TOKEN_2022_PROGRAM:
        if metadata_only:
            try:
                return decode_mint(account, expected_address)
            except TokenEvidenceError as error:
                raise SnapshotEvidenceError(kind + '_' + str(error)) from None
        raise SnapshotEvidenceError(kind + '_token2022_extensions_not_certified')
    raw = _account(account, TOKEN_PROGRAM, 82, kind)
    mint_option = struct.unpack_from('<I', raw, 0)[0]
    freeze_option = struct.unpack_from('<I', raw,46)[0]
    if mint_option not in (0,1) or freeze_option not in (0,1) or raw[45] != 1:
        raise SnapshotEvidenceError(kind + '_mint_state_invalid')
    return {'supply_atomic': _u64(raw,36), 'decimals': raw[44], 'initialized': True,
            'mint_authority_present': bool(mint_option),
            'mint_authority': _key(raw,4) if mint_option else None,
            'freeze_authority_present': bool(freeze_option),
            'freeze_authority': _key(raw,50) if freeze_option else None}, raw


def _vault(account, kind, *, metadata_only=False):
    if metadata_only and isinstance(account, dict) and account.get('owner') == TOKEN_2022_PROGRAM:
        try:
            return decode_vault(account)
        except TokenEvidenceError as error:
            raise SnapshotEvidenceError(kind + '_' + str(error)) from None
    raw = _account(account, TOKEN_PROGRAM, 165, kind)
    delegate = struct.unpack_from('<I',raw,72)[0]
    native = struct.unpack_from('<I',raw,109)[0]
    close = struct.unpack_from('<I',raw,129)[0]
    if delegate not in (0,1) or native not in (0,1) or close not in (0,1):
        raise SnapshotEvidenceError(kind + '_token_state_invalid')
    lamports = _uint(account.get('lamports'), kind + '_account_lamports')
    native_reserve = _u64(raw,113) if native else None
    amount = _u64(raw,64)
    if native and (native_reserve > lamports or amount > lamports-native_reserve):
        raise SnapshotEvidenceError(kind + '_native_backing_insufficient')
    return {'mint': _key(raw,0), 'authority': _key(raw,32),
            'amount_atomic': amount, 'account_lamports': lamports,
            'native_rent_reserve_lamports': native_reserve, 'state': raw[108],
            'delegate_present': bool(delegate), 'close_authority_present': bool(close),
            'is_native': bool(native)}, raw


def _json_safe(value):
    if type(value) is int:
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key,item in value.items()}
    if isinstance(value, (tuple,list)):
        return [_json_safe(item) for item in value]
    return value


def _fraction(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def constant_product_projection(pool, *, input_lamports, fee_rates_ppm, base_vault_atomic,
                                quote_vault_lamports, share_fee_rate_ppm=0):
    """SDK integer arithmetic only; hypothetical immediate reversal after own buy.

    Uses ceil fees and floor outputs. Refuses capped buys/migration boundaries.
    The sell state is explicitly counterfactual: reserves include the hypothetical
    buy; no transaction occurred and observed vault balances are not rewritten.
    No network/priority/account-creation fee or economic net P&L is inferred.
    """
    amount = _uint(input_lamports,'input_lamports',positive=True)
    if type(pool.get('decimals_a')) is not int or not 0 <= pool['decimals_a'] <= 18:
        raise SnapshotEvidenceError('invalid_base_decimals')
    base_vault = _uint(base_vault_atomic,'base_vault_atomic')
    quote_vault = _uint(quote_vault_lamports,'quote_vault_lamports')
    if not isinstance(fee_rates_ppm,(list,tuple)) or len(fee_rates_ppm) != 3:
        raise SnapshotEvidenceError('three_explicit_fee_rates_required')
    rates = [_uint(value,'fee_rate') for value in fee_rates_ppm]
    rates.append(_uint(share_fee_rate_ppm,'share_fee_rate'))
    total_rate = sum(rates)
    if total_rate >= FEE_DENOMINATOR:
        raise SnapshotEvidenceError('fee_rate_not_below_denominator')
    names = ('virtual_a','virtual_b','real_a','real_b','total_sell_a','total_fundraising_b')
    values = {name:_uint(pool.get(name),name) for name in names}
    x = values['virtual_a'] - values['real_a']
    y = values['virtual_b'] + values['real_b']
    remaining = values['total_sell_a'] - values['real_a']
    if x <= 0 or y <= 0 or y > _U64_MAX or remaining <= 0:
        raise SnapshotEvidenceError('invalid_curve_reserves')
    fee_in = (amount*total_rate + FEE_DENOMINATOR-1)//FEE_DENOMINATOR
    net_in = amount - fee_in
    if net_in <= 0:
        raise SnapshotEvidenceError('input_consumed_by_fee')
    bought = net_in*x//(y+net_in)
    if bought <= 0:
        raise SnapshotEvidenceError('buy_output_rounds_to_zero')
    if bought > remaining or values['real_b'] + net_in >= values['total_fundraising_b']:
        raise SnapshotEvidenceError('buy_crosses_fundraising_or_remaining_boundary')
    if bought > base_vault:
        raise SnapshotEvidenceError('base_vault_cannot_cover_buy')
    if (values['real_a'] + bought > _U64_MAX or values['real_b'] + net_in > _U64_MAX
            or quote_vault + net_in > _U64_MAX):
        raise SnapshotEvidenceError('post_buy_reserves_out_of_bounds')
    # Counterfactual bank after this buy, not an observed later state.
    post_x, post_y = x-bought, y+net_in
    gross_sell = bought*post_y//(post_x+bought)
    if gross_sell > values['real_b']+net_in or gross_sell > quote_vault+net_in:
        raise SnapshotEvidenceError('counterfactual_quote_vault_cannot_cover_sell')
    fee_out = (gross_sell*total_rate+FEE_DENOMINATOR-1)//FEE_DENOMINATOR
    net_sell = gross_sell-fee_out
    if net_sell <= 0:
        raise SnapshotEvidenceError('sell_output_rounds_to_zero')
    return {
        'kind': 'conditional_constant_product_projection',
        'buy_input_lamports': str(amount), 'buy_curve_fee_lamports': str(fee_in),
        'buy_effective_input_lamports': str(net_in), 'buy_output_atomic': str(bought),
        'sell_input_atomic': str(bought), 'sell_gross_output_lamports': str(gross_sell),
        'sell_curve_fee_lamports': str(fee_out), 'sell_output_lamports': str(net_sell),
        'fee_rate_total_ppm': str(total_rate), 'fee_denominator': str(FEE_DENOMINATOR),
        'rounding': 'ceil_curve_fee_floor_output',
        'spot_sol_per_whole_token': _fraction(Fraction(y*10**pool['decimals_a'],x*10**9)),
        'buy_output_shortfall_vs_spot_without_fees': _fraction(Fraction(net_in*x-bought*y,net_in*x)),
        'observed_vault_base_atomic': str(base_vault),
        'observed_vault_quote_lamports': str(quote_vault),
        'post_buy_counterfactual_real_a': str(values['real_a']+bought),
        'post_buy_counterfactual_real_b': str(values['real_b']+net_in),
        'post_buy_counterfactual_quote_vault_min_lamports': str(quote_vault+net_in),
        'sell_state_basis': 'counterfactual_after_hypothetical_buy_no_intervening_activity',
        'observed_future_exit_quote': False, 'position_acquired': False,
        'additional_execution_costs_known': False, 'net_economic_pnl_sol': None,
        'execution_verified': False,
    }


def analyze_snapshot(accounts, *, context_slot, expected_mint, pool_address,
                     input_lamports=1_000_000_000, share_fee_rate_ppm=0,
                     discriminator_pins=None, evidence_profile='legacy'):
    """Interpret one caller-supplied getMultipleAccounts bank snapshot.

    accounts maps public address to the RPC account value. All seven accounts
    must be from the SAME response context.slot. The caller retains the response
    and timestamps; this function neither fetches nor proves that acquisition.
    Pins must originate in an independent audited account schema, not sampled
    from the very accounts being validated.
    The opt-in published_metadata_v1 profile applies independent IDL/PDA checks
    and the audited metadata-only Token-2022 subset. Legacy campaign replays keep
    their original interpretation by default; new analyses never rewrite them.
    """
    report = {
        'schema':'p3-launchlab-native-snapshot-v1',
        'context_slot':context_slot if type(context_slot) is int and 0 <= context_slot <= _U64_MAX else None,
        'pool_address':pool_address, 'mint':expected_mint,
        'source_repository':SOURCE_REPOSITORY, 'source_sha256':dict(SOURCE_SHA256),
        'identity_status':'unverified', 'creation_transaction_verified':False,
        'facts':{}, 'conditional_projection':None, 'risk_flags':[],
        'blocking_reasons':['execution_not_verified','additional_execution_costs_unknown',
                            'creation_transaction_not_verified_by_snapshot',
                            'vault_authority_PDA_not_certified'],
        'candidate_eligible':False, 'economic_verdict':'INSUFFICIENT DATA',
        'real_orders_enabled':False,
    }
    try:
        if evidence_profile not in ('legacy', 'published_metadata_v1'):
            raise SnapshotEvidenceError('unsupported_evidence_profile')
        qualified = evidence_profile == 'published_metadata_v1'
        _uint(context_slot,'context_slot')
        _uint(input_lamports,'input_lamports',positive=True)
        _uint(share_fee_rate_ppm,'share_fee_rate')
        if not isinstance(accounts,dict):
            raise SnapshotEvidenceError('accounts_must_be_address_mapping')
        addresses = addresses_from_pool(accounts.get(pool_address),expected_mint,pool_address)
        if len(set(addresses.values())) != len(ACCOUNT_ROLES):
            raise SnapshotEvidenceError('duplicate_snapshot_account_identity')
        pool, pool_raw = _pool(accounts.get(pool_address))
        config, config_raw = _config(accounts.get(addresses['config']))
        platform, platform_raw = _platform(accounts.get(addresses['platform']))
        # Keep independently decoded facts even when a later mint/vault is
        # unsupported. Missing permissions must not erase the observed fees.
        report['facts'] = {
            'addresses':addresses, 'pool':_json_safe(pool),
            'config':_json_safe(config), 'platform':_json_safe(platform),
            'account_data_sha256':{role:hashlib.sha256(raw).hexdigest()
                                   for role,raw in (('pool',pool_raw),('config',config_raw),('platform',platform_raw))},
            'account_context_basis':'caller_supplied_single_getMultipleAccounts_response',
            'program_derived_addresses_verified':False,
        }
        if qualified:
            identity = certify_snapshot(accounts, addresses)
            report['evidence_profile'] = evidence_profile
            report['facts']['identity_certification'] = identity
            report['facts']['program_derived_addresses_verified'] = identity['program_derived_addresses_verified']
            report['blocking_reasons'].extend(identity['blocking_reasons'])
            authority_checked = any(check['name'] == 'authority_pda' and check['status'] == 'PASS'
                                    for check in identity['checks'])
            if authority_checked:
                report['blocking_reasons'].remove('vault_authority_PDA_not_certified')
            if any(check['status'] == 'FAIL' for check in identity['checks']):
                raise SnapshotEvidenceError('published_identity_check_failed')
            if discriminator_pins is None:
                discriminator_pins = DISCRIMINATORS
        if pool['mint_b'] != SOL_MINT or config['quote_mint'] != SOL_MINT:
            raise SnapshotEvidenceError('quote_currency_is_not_native_SOL')
        if qualified:
            quote_account = accounts.get(addresses['mint_b'])
            if type(quote_account) is not dict or quote_account.get('owner') != TOKEN_PROGRAM:
                raise SnapshotEvidenceError('native_SOL_quote_program_mismatch')
        base, base_raw = _mint_state(accounts.get(addresses['mint_a']),'base_mint',
            metadata_only=qualified, expected_address=addresses['mint_a'])
        quote, quote_raw = _mint_state(accounts.get(addresses['mint_b']),'quote_mint',
            metadata_only=qualified, expected_address=addresses['mint_b'])
        vault_a, vault_a_raw = _vault(accounts.get(addresses['vault_a']),'base_vault', metadata_only=qualified)
        vault_b, vault_b_raw = _vault(accounts.get(addresses['vault_b']),'quote_vault', metadata_only=qualified)
        raw_by_role = dict(zip(ACCOUNT_ROLES,
            (pool_raw,config_raw,platform_raw,base_raw,quote_raw,vault_a_raw,vault_b_raw)))
        decoded_facts = {
            'base_mint':_json_safe(base),
            'quote_mint':_json_safe(quote), 'base_vault':_json_safe(vault_a),
            'quote_vault':_json_safe(vault_b),
            'account_data_sha256':{role:hashlib.sha256(raw).hexdigest() for role,raw in raw_by_role.items()},
        }
        if qualified:
            # A failed relation must not erase independently decoded evidence.
            # These are observations, not a burn explanation or reconciliation.
            # Keep the legacy report shape unchanged for historical replays.
            report['facts'].update(decoded_facts)
            supply_matches = base['supply_atomic'] == pool['supply']
            report['facts']['supply_consistency'] = {
                'context_slot':context_slot,
                'mint_supply_atomic':str(base['supply_atomic']),
                'pool_supply_atomic':str(pool['supply']),
                'mint_minus_pool_atomic':str(base['supply_atomic']-pool['supply']),
                'matches':supply_matches,
                'reconciliation_status':'not_required' if supply_matches else 'unresolved',
            }
        if (pool['decimals_a'] != base['decimals'] or pool['decimals_b'] != 9
                or quote['decimals'] != 9 or pool['decimals_a'] > 18
                or base['supply_atomic'] != pool['supply']):
            raise SnapshotEvidenceError('mint_supply_or_decimals_mismatch')
        if (vault_a['mint'] != addresses['mint_a'] or vault_b['mint'] != SOL_MINT
                or vault_a['authority'] != vault_b['authority']):
            raise SnapshotEvidenceError('vault_mint_or_authority_mismatch')
        report['facts'].update(decoded_facts)
        if discriminator_pins is None:
            report['identity_status']='owner_layout_relations_checked_discriminator_uncertified'
            report['blocking_reasons'].append('account_discriminators_not_certified')
        else:
            if (not isinstance(discriminator_pins,dict) or
                    any(type(discriminator_pins.get(role)) is not bytes
                        or len(discriminator_pins[role]) != 8
                        or discriminator_pins[role] != raw_by_role[role][:8]
                        for role in ('pool','config','platform'))):
                raise SnapshotEvidenceError('account_discriminator_pin_mismatch')
            report['identity_status']='owner_layout_relations_and_supplied_pins_checked'
        flags = report['risk_flags']
        if pool['status'] != 0:
            flags.append('pool_not_in_active_launch_curve')
        if config['curve_type'] != 0:
            flags.append('unsupported_curve_type')
        expected_program_flag = (1 if accounts[addresses['mint_a']].get('owner') == TOKEN_2022_PROGRAM else 0) if qualified else 0
        if pool['mint_program_flag'] != expected_program_flag:
            flags.append('unsupported_mint_program_flag')
        if base['mint_authority_present']:
            flags.append('base_mint_authority_present')
        if base['freeze_authority_present'] or quote['freeze_authority_present']:
            flags.append('freeze_authority_present')
        if any(vault['state'] != 1 for vault in (vault_a,vault_b)):
            flags.append('vault_uninitialized_or_frozen')
        if any(vault['delegate_present'] or vault['close_authority_present']
               for vault in (vault_a,vault_b)):
            flags.append('vault_delegate_or_close_authority_present')
        if vault_a['is_native'] or not vault_b['is_native']:
            flags.append('vault_native_currency_state_mismatch')
        if (pool['real_a'] > pool['total_sell_a'] or pool['total_sell_a'] > pool['supply']
                or vault_a['amount_atomic'] < pool['total_sell_a']-pool['real_a']
                or vault_b['amount_atomic'] < pool['real_b']+pool['protocol_fee_accrued']+pool['platform_fee_accrued']):
            flags.append('observed_reserves_or_vault_inventory_inconsistent')
        if share_fee_rate_ppm > config['max_share_fee_rate_ppm']:
            flags.append('share_fee_exceeds_configured_maximum')
        report['facts']['share_fee_assumption_ppm']=str(share_fee_rate_ppm)
        if flags:
            report['blocking_reasons'].extend(flags)
            return report
        report['conditional_projection']=constant_product_projection(
            pool,input_lamports=input_lamports,
            fee_rates_ppm=(config['trade_fee_rate_ppm'],platform['platform_fee_rate_ppm'],
                           platform['creator_fee_rate_ppm']),
            base_vault_atomic=vault_a['amount_atomic'], quote_vault_lamports=vault_b['amount_atomic'],
            share_fee_rate_ppm=share_fee_rate_ppm)
    except (SnapshotEvidenceError,ValueError,TypeError,KeyError,struct.error) as error:
        # Errors are categorical; never echo raw account data or credentials.
        reason = str(error) if isinstance(error,SnapshotEvidenceError) else 'malformed_snapshot'
        report['blocking_reasons'].append(reason)
        report['risk_flags'].append(reason)
        report['conditional_projection']=None
    return report


def observed_sell_projection(pool, *, input_token_atomic, fee_rates_ppm,
                             quote_vault_lamports, curve_type, share_fee_rate_ppm=0):
    """Estimate selling a FIXED quantity against an observed native-SOL state.

    Unlike constant_product_projection, this never inserts our hypothetical buy
    into the supplied reserves. A caller must retain the earlier quantity and
    the later bank context. A refusal here does not prove a position would have
    been unsellable after a real buy, which would have changed those reserves.
    No network/priority/account costs, acquired inventory, execution or P&L.
    """
    amount = _uint(input_token_atomic, 'input_token_atomic', positive=True)
    if type(pool) is not dict:
        raise SnapshotEvidenceError('pool_facts_required')
    if (type(curve_type) is not int or curve_type != 0
            or type(pool.get('status')) is not int or pool['status'] != 0
            or pool.get('mint_b') != SOL_MINT):
        raise SnapshotEvidenceError('active_constant_product_native_SOL_required')
    required = ('virtual_a', 'virtual_b', 'real_a', 'real_b',
                'protocol_fee_accrued', 'platform_fee_accrued')
    values = {key: _uint(pool.get(key), key) for key in required}
    vault = _uint(quote_vault_lamports, 'quote_vault_lamports')
    if type(fee_rates_ppm) not in (tuple, list) or len(fee_rates_ppm) != 3:
        raise SnapshotEvidenceError('three_explicit_fee_rates_required')
    rate = sum(_uint(value, 'fee_rate') for value in fee_rates_ppm) + _uint(share_fee_rate_ppm, 'share_fee_rate')
    if rate >= FEE_DENOMINATOR:
        raise SnapshotEvidenceError('fee_rate_not_below_denominator')
    x, y = values['virtual_a']-values['real_a'], values['virtual_b']+values['real_b']
    if x <= 0 or y <= 0 or y > _U64_MAX:
        raise SnapshotEvidenceError('invalid_curve_reserves')
    if amount > values['real_a']:
        raise SnapshotEvidenceError('sell_exceeds_observed_outstanding_curve_tokens')
    gross = amount*y//(x+amount)
    spendable = vault-values['protocol_fee_accrued']-values['platform_fee_accrued']
    if gross > values['real_b'] or gross > spendable:
        raise SnapshotEvidenceError('observed_exit_liquidity_insufficient')
    fee = (gross*rate + FEE_DENOMINATOR-1)//FEE_DENOMINATOR
    if gross-fee <= 0:
        raise SnapshotEvidenceError('sell_output_rounds_to_zero')
    return {'kind': 'observed_state_conditional_sell_estimate',
            'input_token_atomic': str(amount), 'gross_output_lamports': str(gross),
            'curve_fee_lamports': str(fee), 'output_lamports': str(gross-fee),
            'fee_rate_total_ppm': str(rate), 'spendable_quote_vault_lamports': str(spendable),
            'hypothetical_entry_impact_applied': False, 'additional_execution_costs_known': False,
            'position_acquired': False, 'execution_verified': False, 'net_economic_pnl_sol': None}
