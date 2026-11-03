"""Causal regressions for the observed P3 blockers, using synthetic bytes only."""
import asyncio
import base64
import copy
from fractions import Fraction
import struct

import pytest

from bot.p3 import launchlab as ll, certification as cert, campaign as cp
from bot.p3.collect import now_ms
from bot.p3.quotes import SOL_MINT
from bot.p3.store import CaptureStore
from test_p3_launchlab import fixture, decode, mutate_account
from test_p3_token2022 import metadata
from test_p3_campaign import plan_v2, indexed, payload, append_for
from test_p3_collection import Transport
from test_p3_quotes import Response, quote_payload


def qualified_fixture():
    original, old = fixture()
    a = dict(old)
    a['pool'], _ = cert.find_program_address((b'pool', decode(a['mint_a']), decode(SOL_MINT)))
    a['config'], _ = cert.find_program_address((b'global_config', decode(SOL_MINT), b'\0', b'\0\0'))
    for role, mint in (('vault_a', 'mint_a'), ('vault_b', 'mint_b')):
        a[role], _ = cert.find_program_address((b'pool_vault', decode(a['pool']), decode(a[mint])))
    accounts = {a[role]: copy.deepcopy(original[old[role]]) for role in ll.ACCOUNT_ROLES}
    for role in cert.DISCRIMINATORS:
        mutate_account(accounts, a[role], 0, cert.DISCRIMINATORS[role])
    for role, offset in (('config',141), ('platform',173), ('mint_a',205),
                         ('mint_b',237), ('vault_a',269), ('vault_b',301)):
        mutate_account(accounts, a['pool'], offset, decode(a[role]))
    authority, bump = cert.find_program_address((b'vault_auth_seed',))
    mutate_account(accounts, a['pool'], 16, bump)
    mutate_account(accounts, a['pool'], 365, 1)
    for role in ('vault_a', 'vault_b'):
        mutate_account(accounts, a[role], 32, decode(authority))
    base = accounts[a['mint_a']]
    raw = base64.b64decode(base['data'][0])
    extension = metadata(mint=decode(a['mint_a']))
    raw += bytes(83) + b'\1' + struct.pack('<HH',18,64) + bytes(32) + decode(a['mint_a'])
    raw += struct.pack('<HH',19,len(extension)) + extension
    base['data'][0] = base64.b64encode(raw).decode()
    base['owner'] = ll.TOKEN_2022_PROGRAM
    accounts[a['vault_a']]['owner'] = ll.TOKEN_2022_PROGRAM
    return accounts, a


def qualify(accounts, a):
    return ll.analyze_snapshot(accounts, context_slot=1234, expected_mint=a['mint_a'],
        pool_address=a['pool'], evidence_profile='published_metadata_v1')


def test_metadata_only_profile_qualifies_arithmetic_without_rewriting_legacy_interpretation():
    accounts, a = qualified_fixture()
    legacy = ll.analyze_snapshot(accounts, context_slot=1234, expected_mint=a['mint_a'], pool_address=a['pool'])
    assert 'base_mint_token2022_extensions_not_certified' in legacy['blocking_reasons']
    assert legacy['conditional_projection'] is None
    report = qualify(accounts, a)
    assert report['conditional_projection'] is not None
    assert report['facts']['base_mint']['extension_types'] == ['18','19']
    assert report['facts']['supply_consistency']['matches'] is True
    assert report['facts']['supply_consistency']['reconciliation_status'] == 'not_required'
    assert report['facts']['identity_certification']['account_discriminators_verified'] is True
    assert report['facts']['identity_certification']['program_derived_addresses_verified'] is False
    assert 'original_platform_admin_seed_not_retained' in report['blocking_reasons']
    assert report['candidate_eligible'] is report['real_orders_enabled'] is False
    assert report['conditional_projection']['net_economic_pnl_sol'] is None


def test_profile_never_relaxes_freeze_unknown_extensions_or_observed_supply_mismatch():
    accounts, a = qualified_fixture()
    mutate_account(accounts, a['mint_a'], 46, 1, '<I')
    assert 'freeze_authority_present' in qualify(accounts,a)['blocking_reasons']
    accounts, a = qualified_fixture()
    raw = base64.b64decode(accounts[a['mint_a']]['data'][0]) + struct.pack('<HH',14,0)
    accounts[a['mint_a']]['data'][0] = base64.b64encode(raw).decode()
    assert qualify(accounts,a)['conditional_projection'] is None
    accounts, a = qualified_fixture()
    mutate_account(accounts, a['mint_a'], 36, 10**15-1, '<Q')
    assert 'mint_supply_or_decimals_mismatch' in qualify(accounts,a)['blocking_reasons']
    accounts, a = qualified_fixture()
    accounts[a['mint_b']]['owner'] = ll.TOKEN_2022_PROGRAM
    accounts[a['vault_b']]['owner'] = ll.TOKEN_2022_PROGRAM
    assert 'native_SOL_quote_program_mismatch' in qualify(accounts,a)['blocking_reasons']
    accounts, a = qualified_fixture()
    accounts[a['mint_b']] = accounts[a['vault_b']] = None
    assert qualify(accounts,a)['conditional_projection'] is None


def test_forged_pinned_identity_blocks_the_new_profile_even_when_curve_math_is_defined():
    accounts, a = qualified_fixture()
    mutate_account(accounts, a['config'], 0, b'BAD!TYPE')
    report = qualify(accounts,a)
    assert report['conditional_projection'] is None
    assert 'published_identity_check_failed' in report['blocking_reasons']


def test_later_state_sell_uses_fixed_quantity_and_exact_fees_without_inserting_our_buy():
    accounts, a = fixture()
    pool, _ = ll._pool(accounts[a['pool']])
    amount, rates = 10**12, (2500,10000,5000)
    result = ll.observed_sell_projection(pool, input_token_atomic=amount, fee_rates_ppm=rates,
        quote_vault_lamports=5*10**9+3*10**6, curve_type=0)
    exact = Fraction(amount*(pool['virtual_b']+pool['real_b']),
                     pool['virtual_a']-pool['real_a']+amount)
    gross = exact.numerator//exact.denominator
    fee = (gross*sum(rates)+999999)//1000000
    assert int(result['gross_output_lamports']) == gross
    assert int(result['curve_fee_lamports']) == fee
    assert int(result['output_lamports']) == gross-fee
    assert result['hypothetical_entry_impact_applied'] is result['position_acquired'] is False
    assert result['execution_verified'] is False and result['net_economic_pnl_sol'] is None


def test_virtual_reserves_and_accrued_fees_cannot_pay_a_later_exit():
    accounts, a = fixture(); pool, _ = ll._pool(accounts[a['pool']])
    for changed, vault, reason in ((dict(pool,real_b=0),10**10,'liquidity'),
            (pool,3*10**6,'liquidity')):
        with pytest.raises(ll.SnapshotEvidenceError, match=reason):
            ll.observed_sell_projection(changed,input_token_atomic=10**12,
                fee_rates_ppm=(2500,10000,5000),quote_vault_lamports=vault,curve_type=0)
    with pytest.raises(ll.SnapshotEvidenceError,match='outstanding'):
        ll.observed_sell_projection(pool,input_token_atomic=pool['real_a']+1,
            fee_rates_ppm=(2500,10000,5000),quote_vault_lamports=10**10,curve_type=0)
    with pytest.raises(ll.SnapshotEvidenceError,match='native_SOL'):
        ll.observed_sell_projection(pool,input_token_atomic=1,fee_rates_ppm=(0,0,0),
            quote_vault_lamports=10**10,curve_type=1)


def test_future_capture_retains_selection_inputs_signature_page_and_quote_bodies(tmp_path, monkeypatch):
    _, a = fixture()
    original = payload(None, indexed(metadata={'api_key':'irrelevant-not-retained'}))
    page = [{'signature':'1'*64,'slot':10,'err':None,'blockTime':100}]
    async def rpc(_session,_append,method,_params):
        return (page if method=='getSignaturesForAddress' else None, now_ms(), 'synthetic', 'observed')
    monkeypatch.setattr(cp,'_rpc',rpc)
    buy = quote_payload(output_mint=a['mint_a'],output='1000000',minimum='990000')
    sell = quote_payload(input_mint=a['mint_a'],output_mint=SOL_MINT,amount='1000000',output='900000000',minimum='891000000')
    transport = Transport(gets=[Response(original),Response(buy),Response(sell)])
    with CaptureStore(tmp_path/'p3.sqlite') as store:
        asyncio.run(cp.collect_campaign(store,cp.CampaignSession(transport,20),plan_v2(),provenance='synthetic'))
        discovery = store.events(kind='discovery')[0]['payload']
        replayed = cp.select_rows(discovery['replay_selection_input'])[0]
        assert [r['selection_reason'] for r in replayed] == [r['selection_reason'] for r in discovery['rows']]
        assert [r['mint'] for r in replayed] == [r['mint'] for r in discovery['rows']]
        assert discovery['selection_input_retained'] is True
        assert 'metadata' not in discovery['replay_selection_input']['data']['rows'][1]
        evidence = next(e['payload'] for e in store.events(kind='checkpoint') if e['outcome']=='pool_signature_page')
        assert evidence['raw_signature_page'] == page
        quotes = [e for e in store.events(kind='quote_attempt') if e['payload'].get('provider')=='raydium_trade_api']
        assert [e['payload']['retained_sanitized_response'] for e in quotes] == [buy,sell]


def test_supply_rejection_retains_exact_independent_facts_without_reconciliation_claim():
    accounts, a = qualified_fixture()
    observed = 999_020_457_494_200
    mutate_account(accounts, a['mint_a'], 36, observed, '<Q')
    report = qualify(accounts, a)
    assert report['conditional_projection'] is None
    assert 'mint_supply_or_decimals_mismatch' in report['blocking_reasons']
    assert report['facts']['base_mint']['supply_atomic'] == str(observed)
    assert report['facts']['pool']['supply'] == '1000000000000000'
    assert set(report['facts']['account_data_sha256']) == set(ll.ACCOUNT_ROLES)
    consistency = report['facts']['supply_consistency']
    assert consistency == {
        'context_slot': 1234,
        'mint_supply_atomic': str(observed),
        'pool_supply_atomic': '1000000000000000',
        'mint_minus_pool_atomic': '-979542505800',
        'matches': False,
        'reconciliation_status': 'unresolved',
    }
    assert report['candidate_eligible'] is report['real_orders_enabled'] is False
    # Existing default-profile archives retain their historical shape.
    classic, addresses = fixture()
    mutate_account(classic, addresses['mint_a'], 36, observed, '<Q')
    legacy = ll.analyze_snapshot(classic, context_slot=1234,
        expected_mint=addresses['mint_a'], pool_address=addresses['pool'])
    assert 'base_mint' not in legacy['facts']
    assert 'supply_consistency' not in legacy['facts']
