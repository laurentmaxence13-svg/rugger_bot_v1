"""Synthetic same-bank LaunchLab account state and native-SOL curve arithmetic."""
import base64
import copy
from fractions import Fraction
import hashlib
import json
import math
import struct

import pytest

from bot.p3 import launchlab as ll
from bot.p3.quotes import SOL_MINT

ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def encode(raw):
    value=int.from_bytes(raw,'big')
    chars=''
    while value:
        value,digit=divmod(value,58)
        chars=ALPHABET[digit]+chars
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+chars


def decode(value):
    number=0
    for ch in value:
        number=number*58+ALPHABET.index(ch)
    return b'\0'*(len(value)-len(value.lstrip('1')))+number.to_bytes((number.bit_length()+7)//8,'big')


def account(raw, owner):
    return {'owner':owner,'executable':False,'data':[base64.b64encode(raw).decode(),'base64'],'lamports':100000000}


def mutate_account(accounts,address,offset,value,fmt=None):
    item=accounts[address]
    raw=bytearray(base64.b64decode(item['data'][0]))
    if fmt:
        struct.pack_into(fmt,raw,offset,value)
    elif isinstance(value,bytes):
        raw[offset:offset+len(value)]=value
    else:
        raw[offset]=value
    item['data'][0]=base64.b64encode(raw).decode()


def fixture():
    addresses={role:encode(bytes([index])*32) for index,role in enumerate(
        ('mint_a','pool','config','platform','vault_a','vault_b'),1)}
    addresses['mint_b']=SOL_MINT
    creator=encode(bytes([8])*32)
    authority=bytes([7])*32
    p=bytearray(429)
    p[:8]=b'POOLtest'
    p[17:21]=bytes([0,6,9,0])
    values=(10**15,8*10**14,10**15,30*10**9,10**14,5*10**9,100*10**9,10**6,2*10**6,0)
    for i,value in enumerate(values):
        struct.pack_into('<Q',p,21+8*i,value)
    for role,offset in (('config',141),('platform',173),('mint_a',205),('mint_b',237),('vault_a',269),('vault_b',301)):
        p[offset:offset+32]=decode(addresses[role])
    p[333:365]=decode(creator)
    c=bytearray(371)
    c[:8]=b'CONFtest'
    c[16]=0
    struct.pack_into('<Q',c,27,2500)
    struct.pack_into('<Q',c,35,10000)
    c[83:115]=decode(SOL_MINT)
    platform=bytearray(944)
    platform[:8]=b'PLATtest'
    struct.pack_into('<Q',platform,104,10000)
    struct.pack_into('<Q',platform,720,5000)
    base=bytearray(82)
    struct.pack_into('<Q',base,36,10**15)
    base[44:46]=bytes([6,1])
    quote=bytearray(82)
    quote[44:46]=bytes([9,1])
    va=bytearray(165)
    va[:32]=decode(addresses['mint_a'])
    va[32:64]=authority
    struct.pack_into('<Q',va,64,9*10**14)
    va[108]=1
    vb=bytearray(165)
    vb[:32]=decode(SOL_MINT)
    vb[32:64]=authority
    struct.pack_into('<Q',vb,64,5*10**9+3*10**6)
    vb[108]=1
    struct.pack_into('<I',vb,109,1)
    raw={'pool':p,'config':c,'platform':platform,'mint_a':base,'mint_b':quote,'vault_a':va,'vault_b':vb}
    accounts={addresses[role]:account(blob,ll.LAUNCHLAB_PROGRAM if role in ('pool','config','platform') else ll.TOKEN_PROGRAM)
              for role,blob in raw.items()}
    # WSOL token amount must be backed by actual lamports above its native
    # rent reserve; the virtual curve reserve is never that backing.
    struct.pack_into('<Q',vb,113,2_039_280)
    accounts[addresses['vault_b']]=account(vb,ll.TOKEN_PROGRAM)
    accounts[addresses['vault_b']]['lamports']=5*10**9+3*10**6+2_039_280
    return accounts,addresses


def analyze(accounts,addresses,**kwargs):
    return ll.analyze_snapshot(accounts,context_slot=1234,
        expected_mint=addresses['mint_a'],pool_address=addresses['pool'],**kwargs)


def test_addresses_come_from_bound_pool_not_index_metadata():
    accounts,addresses=fixture()
    actual=ll.addresses_from_pool(accounts[addresses['pool']],addresses['mint_a'],addresses['pool'])
    assert actual=={role:addresses[role] for role in ll.ACCOUNT_ROLES}
    assert len(set(actual.values()))==7
    with pytest.raises(ll.SnapshotEvidenceError,match='base_mint_mismatch'):
        ll.addresses_from_pool(accounts[addresses['pool']],SOL_MINT,addresses['pool'])


def test_native_projection_exact_sdk_integer_oracle_and_no_usd_or_execution_claim():
    accounts,addresses=fixture()
    result=analyze(accounts,addresses)
    p=result['conditional_projection']
    assert p is not None and p['buy_input_lamports']=='1000000000'
    fee_in=math.ceil(Fraction(10**9*17500,10**6))
    effective=10**9-fee_in
    output=(effective*9*10**14)//(35*10**9+effective)
    gross_sell=(output*(35*10**9+effective))//(9*10**14)
    fee_out=math.ceil(Fraction(gross_sell*17500,10**6))
    assert int(p['buy_curve_fee_lamports'])==fee_in
    assert int(p['buy_output_atomic'])==output
    assert int(p['sell_input_atomic'])==output
    assert int(p['sell_gross_output_lamports'])==gross_sell
    assert int(p['sell_curve_fee_lamports'])==fee_out
    assert int(p['sell_output_lamports'])==gross_sell-fee_out
    assert int(p['sell_output_lamports'])<int(p['buy_input_lamports'])
    assert int(p['sell_gross_output_lamports'])<=int(p['post_buy_counterfactual_real_b'])
    assert int(p['sell_gross_output_lamports'])<=int(p['post_buy_counterfactual_quote_vault_min_lamports'])
    assert p['sell_state_basis'].startswith('counterfactual')
    assert p['position_acquired'] is p['execution_verified'] is p['additional_execution_costs_known'] is False
    assert p['net_economic_pnl_sol'] is None
    assert result['candidate_eligible'] is result['real_orders_enabled'] is False
    assert result['identity_status']=='owner_layout_relations_checked_discriminator_uncertified'
    assert result['facts']['program_derived_addresses_verified'] is False
    assert 'vault_authority_PDA_not_certified' in result['blocking_reasons']
    assert 'account_discriminators_not_certified' in result['blocking_reasons']
    assert result['creation_transaction_verified'] is False
    assert result['economic_verdict']=='INSUFFICIENT DATA'
    assert 'USD' not in json.dumps(p)
    json.dumps(result,allow_nan=False)
    spot=p['spot_sol_per_whole_token']
    assert Fraction(int(spot['numerator']),int(spot['denominator']))==Fraction(35*10**9*10**6,9*10**14*10**9)


def test_supplied_discriminator_pins_do_not_qualify_execution_or_market_profit():
    accounts,addresses=fixture()
    pins={'pool':b'POOLtest','config':b'CONFtest','platform':b'PLATtest'}
    result=analyze(accounts,addresses,discriminator_pins=pins)
    assert result['conditional_projection'] is not None
    assert result['identity_status']=='owner_layout_relations_and_supplied_pins_checked'
    assert 'account_discriminators_not_certified' not in result['blocking_reasons']
    assert result['candidate_eligible'] is False
    pins['pool']=b'BAD!test'
    bad=analyze(accounts,addresses,discriminator_pins=pins)
    assert bad['conditional_projection'] is None
    assert 'account_discriminator_pin_mismatch' in bad['blocking_reasons']


def test_token2022_keeps_observed_fee_facts_but_never_assumes_extensions_sellable():
    accounts,addresses=fixture()
    accounts[addresses['mint_a']]['owner']=ll.TOKEN_2022_PROGRAM
    result=analyze(accounts,addresses)
    assert result['conditional_projection'] is None
    assert result['facts']['config']['trade_fee_rate_ppm']=='2500'
    assert result['facts']['platform']['creator_fee_rate_ppm']=='5000'
    assert 'base_mint_token2022_extensions_not_certified' in result['blocking_reasons']
    assert result['candidate_eligible'] is False


@pytest.mark.parametrize('role',ll.ACCOUNT_ROLES)
def test_missing_or_foreign_owner_account_blocks_projection(role):
    accounts,addresses=fixture()
    accounts[addresses[role]]=None
    assert analyze(accounts,addresses)['conditional_projection'] is None
    accounts,addresses=fixture()
    accounts[addresses[role]]['owner']=addresses['pool']
    assert analyze(accounts,addresses)['conditional_projection'] is None


@pytest.mark.parametrize('role',ll.ACCOUNT_ROLES)
def test_unsupported_account_length_or_executable_blocks_projection(role):
    accounts,addresses=fixture()
    raw=base64.b64decode(accounts[addresses[role]]['data'][0])+b'extension'
    accounts[addresses[role]]['data'][0]=base64.b64encode(raw).decode()
    assert analyze(accounts,addresses)['conditional_projection'] is None
    accounts,addresses=fixture()
    accounts[addresses[role]]['executable']=True
    assert analyze(accounts,addresses)['conditional_projection'] is None


@pytest.mark.parametrize('role,offset,value,fmt,reason',[
    ('pool',17,2,None,'pool_not_in_active_launch_curve'),
    ('config',16,1,None,'unsupported_curve_type'),
    ('pool',365,1,None,'unsupported_mint_program_flag'),
    ('mint_a',0,1,'<I','base_mint_authority_present'),
    ('mint_a',46,1,'<I','freeze_authority_present'),
    ('vault_a',108,2,None,'vault_uninitialized_or_frozen'),
    ('vault_b',72,1,'<I','vault_delegate_or_close_authority_present'),
    ('vault_a',129,1,'<I','vault_delegate_or_close_authority_present'),
    ('vault_a',109,1,'<I','vault_native_currency_state_mismatch'),
    ('vault_b',109,0,'<I','vault_native_currency_state_mismatch'),
    ('vault_a',64,1,'<Q','observed_reserves_or_vault_inventory_inconsistent'),
    ('vault_b',64,1,'<Q','observed_reserves_or_vault_inventory_inconsistent'),
])
def test_token_permissions_extensions_liquidity_and_curve_risks_are_not_greenwashed(role,offset,value,fmt,reason):
    accounts,addresses=fixture()
    mutate_account(accounts,addresses[role],offset,value,fmt)
    if role == 'vault_a' and offset == 109:
        # Isolate the wrong-native-mint check from missing lamport backing.
        accounts[addresses[role]]['lamports']=9*10**14
    result=analyze(accounts,addresses)
    assert result['conditional_projection'] is None
    assert reason in result['blocking_reasons']
    assert result['candidate_eligible'] is False


@pytest.mark.parametrize('role,offset,value',[
    ('config',83,bytes([9])*32),('pool',237,bytes([9])*32),
    ('vault_a',0,decode(SOL_MINT)),('vault_b',32,bytes([9])*32),
])
def test_quote_currency_and_vault_identity_mismatches_block(role,offset,value):
    accounts,addresses=fixture()
    mutate_account(accounts,addresses[role],offset,value)
    assert analyze(accounts,addresses)['conditional_projection'] is None


def test_supply_decimals_and_fee_rate_bounds_block_without_fabricated_quote():
    for role,offset,value,fmt in [('mint_a',36,2,'<Q'),('pool',19,6,None),
                                  ('config',27,1000000,'<Q')]:
        accounts,addresses=fixture()
        mutate_account(accounts,addresses[role],offset,value,fmt)
        assert analyze(accounts,addresses)['conditional_projection'] is None
    accounts,addresses=fixture()
    assert analyze(accounts,addresses,share_fee_rate_ppm=10001)['conditional_projection'] is None


def test_fundraise_boundary_refuses_instead_of_shrinking_the_requested_budget():
    accounts,addresses=fixture()
    mutate_account(accounts,addresses['pool'],69,5*10**9+100,'<Q')
    result=analyze(accounts,addresses)
    assert result['conditional_projection'] is None
    assert 'buy_crosses_fundraising_or_remaining_boundary' in result['blocking_reasons']


@pytest.mark.parametrize('slot',[None,True,-1,1.5,'1234',float('nan'),float('inf')])
def test_context_slot_is_not_invented_or_coerced(slot):
    accounts,addresses=fixture()
    result=ll.analyze_snapshot(accounts,context_slot=slot,expected_mint=addresses['mint_a'],pool_address=addresses['pool'])
    assert result['conditional_projection'] is None
    assert 'invalid_context_slot' in result['blocking_reasons']
    assert result['context_slot'] is None
    json.dumps(result,allow_nan=False)


def test_fee_rounding_and_same_pool_counterfactual_conserve_budget():
    accounts,addresses=fixture()
    pool=analyze(accounts,addresses)['facts']['pool']
    numeric={k:int(v) if isinstance(v,str) and v.isdigit() else v for k,v in pool.items()}
    for amount in (101,100000007,10**9):
        p=ll.constant_product_projection(numeric,input_lamports=amount,fee_rates_ppm=(1,0,0),
            base_vault_atomic=9*10**14,quote_vault_lamports=5*10**9+3*10**6)
        assert int(p['buy_curve_fee_lamports'])==math.ceil(Fraction(amount,10**6))
        assert int(p['sell_output_lamports'])<=amount-int(p['buy_curve_fee_lamports'])
        assert int(p['sell_curve_fee_lamports'])==math.ceil(Fraction(int(p['sell_gross_output_lamports']),10**6))


def test_parse_is_pure_and_account_hashes_match_input_bytes():
    accounts,addresses=fixture()
    before=copy.deepcopy(accounts)
    result=analyze(accounts,addresses)
    assert accounts==before
    for role,address in addresses.items():
        assert result['facts']['account_data_sha256'][role]==hashlib.sha256(base64.b64decode(accounts[address]['data'][0])).hexdigest()


@pytest.mark.parametrize('lamports',[0,5*10**9+3*10**6+2_039_279,True,None,'999999999999'])
def test_native_liquidity_requires_actual_lamport_backing_and_rent(lamports):
    accounts,addresses=fixture()
    accounts[addresses['vault_b']]['lamports']=lamports
    result=analyze(accounts,addresses)
    assert result['conditional_projection'] is None
    assert any('lamports' in reason or 'backing_insufficient' in reason
               for reason in result['blocking_reasons'])


def test_native_rent_reserve_cannot_exceed_account_lamports():
    accounts,addresses=fixture()
    mutate_account(accounts,addresses['vault_b'],113,2**64-1,'<Q')
    result=analyze(accounts,addresses)
    assert result['conditional_projection'] is None
    assert 'quote_vault_native_backing_insufficient' in result['blocking_reasons']


def test_counterfactual_zero_exit_is_unavailable_not_a_usable_quote():
    pool={'decimals_a':6,'virtual_a':1000,'virtual_b':10,'real_a':0,'real_b':100,
          'total_sell_a':1000,'total_fundraising_b':1000}
    with pytest.raises(ll.SnapshotEvidenceError,match='sell_output_rounds_to_zero'):
        ll.constant_product_projection(pool,input_lamports=2,fee_rates_ppm=(1,0,0),
            base_vault_atomic=1000,quote_vault_lamports=100)
