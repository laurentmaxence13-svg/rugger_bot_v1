"""Instrumental sell inventory, independent from an unexecuted buy."""
import asyncio
import copy

import pytest

from bot.p3 import active_exit_campaign as ac
from bot.p3 import campaign as cp
from bot.p3.store import CaptureStore
from bot.p3.launchlab import analyze_snapshot, SnapshotEvidenceError
from test_p3_qualification import qualified_fixture
from test_p3_launchlab import mutate_account, encode
from test_p3_campaign import indexed, payload, bank, no_sleep
from test_p3_collection import Transport, rpc
from test_p3_quotes import Response, quote_payload


def plan():
    return dict(schema='p3-active-exit-control-v1',plan_id='active-exit-007',
        max_requests=20,max_elapsed_ms=60000,screen_pool_limit=20,graph_limit=3,
        sample_size=1,followup_delay_ms=15000,input_lamports=1000000000,
        slippage_bps=100,observed_inventory_divisor=100,index_sort='new',
        evidence_profile='published_metadata_v1',rpc_endpoint=ac.RPC_URL,
        selection='first_arithmetic_safe_active_bank_in_first_three_active_pools',
        inventory_basis='one_percent_observed_outstanding_not_acquired_inventory',
        registered_at_ms=1,source_revision='a'*40)


def setup():
    accounts,addresses=qualified_fixture()
    row=indexed(mint=addresses['mint_a'],pool=addresses['pool'])
    return accounts,addresses,row


def analyze(accounts,a):
    return analyze_snapshot(accounts,context_slot=1234,expected_mint=a['mint_a'],
        pool_address=a['pool'],evidence_profile='published_metadata_v1')


def test_plan_and_screen_prefix_are_fixed_before_quotes():
    assert len(ac.validate_plan(plan()))==64
    with pytest.raises(ValueError):ac.validate_plan(dict(plan(),observed_inventory_divisor=1000))
    rows=[indexed(mint=encode(bytes([i])*32),pool=encode(bytes([i+50])*32)) for i in range(1,23)]
    retained,screen,total=ac.screening_rows(payload(*rows))
    assert len(screen)==20 and total==22
    assert retained[2]['selection_reason']=='selected_for_pool_screening'
    assert retained[-1]['selection_reason']=='outside_screening_prefix'


def test_bank_selection_requires_outstanding_inventory_not_virtual_reserves():
    accounts,a,row=setup()
    retained,rows,_=ac.screening_rows(payload(row))
    slot,chosen,decisions=ac.active_pool_rows(rows,{'context':{'slot':1234},'value':[accounts[a['pool']]]})
    assert chosen==rows
    mutate_account(accounts,a['pool'],53,0,'<Q')
    assert ac.active_pool_rows(rows,{'context':{'slot':1234},'value':[accounts[a['pool']]]})[1]==[]


def test_unknown_platform_is_only_diagnostic_and_no_other_unknown_is_allowed():
    accounts,a,_=setup();analysis=analyze(accounts,a)
    assert ac.diagnostic_bank_mode(analysis)=='diagnostic_unknown_platform'
    altered=copy.deepcopy(analysis)
    altered['facts']['identity_certification']['checks'][0]['status']='UNKNOWN'
    assert ac.diagnostic_bank_mode(altered) is None
    altered=copy.deepcopy(analysis)
    altered['facts']['identity_certification']['checks']=[{'name':'platform_pda','status':'UNKNOWN',
        'reason':'original_platform_admin_seed_not_retained'}]
    assert ac.diagnostic_bank_mode(altered) is None


def test_current_bank_sell_guard_is_stricter_than_own_buy_counterfactual():
    accounts,a,_=setup()
    mutate_account(accounts,a['pool'],61,1,'<Q')
    analysis=analyze(accounts,a)
    assert analysis['conditional_projection'] is not None
    q=int(analysis['facts']['pool']['real_a'])//100
    with pytest.raises(SnapshotEvidenceError,match='observed_exit_liquidity_insufficient'):
        ac.observed_inventory_sell(analysis,q)


def run_transport(tmp_path,monkeypatch,*,followup_shrinks=False,buy_error=None,followup_slot=1274):
    accounts,a,row=setup();later=copy.deepcopy(accounts)
    if followup_shrinks:mutate_account(later,a['pool'],53,1,'<Q')
    ordered=cp.addresses_from_pool(accounts[a['pool']],a['mint_a'],a['pool'])
    # Creation lookup remains explicitly unverified with an empty page.
    transport=Transport(posts=[rpc({'context':{'slot':1230},'value':[accounts[a['pool']]]}),
        rpc(bank(accounts,ordered,1234)),rpc(100),rpc([]),rpc(bank(later,ordered,followup_slot)),rpc(115)],
        gets=[Response(payload(row)),buy_error or Response(quote_payload(output_mint=a['mint_a'])),
              Response({'success':False,'msg':'INSUFFICIENT_LIQUIDITY'}),
              Response(quote_payload(output_mint=a['mint_a'])),
              Response({'success':False,'msg':'INSUFFICIENT_LIQUIDITY'})])
    monkeypatch.setattr(ac.asyncio,'sleep',no_sleep)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(ac.collect_active_exit(store,cp.CampaignSession(transport,20),
                                                plan(),provenance='synthetic'))
        events=store.events()
    return result,events,transport


def test_fixed_sell_quantity_is_not_buy_output_and_survives_followup(tmp_path,monkeypatch):
    report,events,transport=run_transport(tmp_path,monkeypatch)
    q=report['fixed_sell_quantity_atomic'];assert q=='1000000000000'
    quotes=[e for e in events if e['kind']=='quote_attempt' and e['payload'].get('provider')=='raydium_trade_api']
    assert [e['payload']['quote_side'] for e in quotes]==['buy','sell','buy','sell']
    assert [e['payload']['input_amount_atomic'] for e in (quotes[1],quotes[3])]==[q,q]
    fixed=next(e for e in events if e['outcome']=='fixed_diagnostic_sell_quantity')
    assert fixed['available_at_ms']<=quotes[0]['payload']['requested_at_ms']
    assert report['strict_exit_qualified'] is report['position_acquired'] is False
    assert report['net_pnl_lamports'] is None
    assert report['requests_used']==len(transport.calls)==11


def test_followup_loss_of_inventory_is_retained_without_resizing_or_provider_call(tmp_path,monkeypatch):
    report,events,transport=run_transport(tmp_path,monkeypatch,followup_shrinks=True)
    assert report['fixed_sell_quantity_atomic']=='1000000000000'
    assert report['sell_prechecks'][-1]['status']=='rejected'
    quotes=[e for e in events if e['kind']=='quote_attempt' and e['payload'].get('provider')=='raydium_trade_api']
    assert len(quotes)==2
    assert report['requests_used']==len(transport.calls)==9


def test_http429_stops_after_receipt_without_followup_or_other_endpoint(tmp_path,monkeypatch):
    report,events,transport=run_transport(tmp_path,monkeypatch,buy_error=Response(status=429))
    assert report['requests_used']==len(transport.calls)==6
    assert len(report['snapshots'])==1
    assert any(e['reason']=='active_exit_stopped_after_source_error' for e in events if e['kind']=='gap')


def test_same_slot_followup_is_retained_as_stale_not_a_new_confirmation(tmp_path,monkeypatch):
    report,events,transport=run_transport(tmp_path,monkeypatch,followup_slot=1234)
    assert report['snapshots'][-1]['new_bank'] is False
    assert len([e for e in events if e['kind']=='quote_attempt'
                and e['payload'].get('provider')=='raydium_trade_api'])==2
    assert any(e['reason']=='followup_slot_not_advanced' for e in events if e['kind']=='gap')
