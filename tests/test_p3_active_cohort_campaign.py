"""New active-cohort schedule shares one budget, with synthetic transports only."""
import asyncio
from copy import deepcopy
import time

import pytest

from bot.p3 import active_cohort_campaign as active
from bot.p3.campaign import CampaignSession
from bot.p3.collect import CANONICAL_RPC_URL,_rpc,now_ms
from bot.p3.store import CaptureStore
from bot.p3.quotes import RAYDIUM_QUOTE_URL,SOL_MINT
from test_p3_campaign import payload,indexed
from test_p3_collection import Transport,rpc
from test_p3_cohort import snapshot
from test_p3_cost_evidence import observation
from test_p3_launchlab import fixture,encode,decode,mutate_account
from test_p3_quotes import Response,quote_payload


def plan():return active.make_plan(registered_at_ms=1,source_revision='a'*40)


def test_plan_canonical_endpoint_is_fixed_before_capture_and_old_criteria_unchanged():
    registered=plan()
    assert registered['effective_rpc_endpoint']==CANONICAL_RPC_URL
    assert registered['acquisition']['criteria']['max_requests']==20
    assert registered['acquisition']['criteria']['research_input_lamports']==100000000
    assert len(active.validate_plan(registered,first_observation_at_ms=2))==64
    registered['effective_rpc_endpoint']='https://api.mainnet-beta.solana.com'
    with pytest.raises(ValueError,match='Exact active'):active.validate_plan(registered)


@pytest.mark.parametrize('status',[403,429,500])
def test_first_http_failure_stops_globally_after_its_receipt(tmp_path,status):
    transport=Transport(gets=[Response(status=status)]);transport._retry_connection=False
    session=CampaignSession(transport,20,rpc_url=CANONICAL_RPC_URL)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(active.collect_active_cohort(store,session,plan(),provenance='synthetic'))
        assert result['requests_used']==1 and len(transport.calls)==1
        assert result['stop_reason']=='source_error_after_persisted_receipt'
        assert result['selection']['universe_size']==0
        assert result['observation_categories']['OBSERVED']['retained_RPC_account_responses']==0
        assert result['qualified_economic_cycles']==0 and result['net_pnl_sol'] is None
        assert store.events(kind='request')[0]['payload']['http_status']==status


def test_rpc_failure_keeps_discovered_universe_and_never_tries_quotes(tmp_path):
    rows=[indexed(),indexed(mint=encode(bytes([42])*32),pool=encode(bytes([43])*32))]
    transport=Transport(gets=[Response(payload(*rows))],posts=[Response(status=429)])
    transport._retry_connection=False
    session=CampaignSession(transport,20,rpc_url=CANONICAL_RPC_URL)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(active.collect_active_cohort(store,session,plan(),provenance='synthetic'))
        assert result['requests_used']==2
        assert result['selection']['universe_size']==2
        assert result['selection']['selected_count']==0
        assert result['acquisition']['universe_size']==2
        assert not store.events(kind='quote_attempt')
        assert store.events(kind='discovery')[0]['payload']['raw_response_retained'] is True


def graphs(count=7):
    all_accounts={};rows=[]
    for n in range(count):
        accounts,old=fixture()
        new={role:SOL_MINT if role=='mint_b' else encode(bytes([n*30+i+1])*32)
             for i,role in enumerate(old)}
        for role,offset in (('config',141),('platform',173),('mint_a',205),
                             ('mint_b',237),('vault_a',269),('vault_b',301)):
            mutate_account(accounts,old['pool'],offset,decode(new[role]))
        mutate_account(accounts,old['vault_a'],0,decode(new['mint_a']))
        for role,address in old.items():all_accounts[new[role]]=deepcopy(accounts[address])
        rows.append(indexed(mint=new['mint_a'],pool=new['pool']))
    return all_accounts,rows


class WholeTransport:
    _retry_connection=False
    def __init__(self,*,buy_error=False):
        self.accounts,self.rows=graphs();self.calls=[];self.bank=0;self.full={};self.store=None;self.buy_error=buy_error
    def post(self,url,**kwargs):
        self.calls.append(('POST',url,deepcopy(kwargs)))
        method,params=kwargs['json']['method'],kwargs['json']['params']
        if method=='getMultipleAccounts':
            self.bank+=1
            return rpc(dict(context={'slot':9+self.bank},value=[self.accounts[a] for a in params[0]]))
        if method=='getBlockTime':return rpc(100)
        tx=observation()['payload']['raw_transaction']
        if method=='getSignaturesForAddress':
            return rpc([dict(signature=tx['transaction']['signatures'][0],slot=tx['slot'],err=None)])
        assert method=='getTransaction';return rpc(tx)
    def get(self,url,**kwargs):
        self.calls.append(('GET',url,deepcopy(kwargs)))
        if url!=RAYDIUM_QUOTE_URL:return Response(payload(*self.rows))
        p=kwargs['params']
        if p['inputMint']==SOL_MINT:
            assert p['amount']=='100000000'
            if self.buy_error:return Response(error=OSError('synthetic'))
            return Response(quote_payload(output_mint=p['outputMint'],amount=p['amount'],output='1000',minimum='990'))
        mint=p['inputMint']
        fixed=[e for e in self.store.events() if e.get('mint')==mint and e.get('outcome')=='projected_inventory_fixed']
        assert len(fixed)==1 and fixed[0]['payload']['partial_diagnostic_atomic']=='250'
        if p['amount']=='1000':
            self.full[mint]=self.full.get(mint,0)+1
            if self.full[mint]==1:return Response({'success':False,'msg':'INSUFFICIENT_LIQUIDITY'})
        else:assert p['amount']=='250'
        return Response(quote_payload(input_mint=mint,output_mint=SOL_MINT,amount=p['amount'],
            output='110000000' if p['amount']=='1000' else '20000000',minimum='1'))


def fake_banks(monkeypatch,*,eligible=True):
    ticks=[time.monotonic_ns()];sleeps=[]
    monkeypatch.setattr(active.time,'monotonic_ns',lambda:ticks[0])
    monkeypatch.setattr(active.time,'monotonic',lambda:ticks[0]/1e9)
    async def wait(delay):sleeps.append(delay);ticks[0]+=int(delay*1e9)
    monkeypatch.setattr(active.asyncio,'sleep',wait)
    async def grouped(store,session,append,rows,graphs,minimum_slot,phase,*,input_lamports):
        assert input_lamports==100000000
        raw,received,request,_=await _rpc(session,append,'getMultipleAccounts',
            [[r['pool'] for r in rows],{'encoding':'base64','commitment':'confirmed','minContextSlot':minimum_slot}])
        slot=raw['context']['slot'];await _rpc(session,append,'getBlockTime',[slot])
        result={}
        for i,row in enumerate(rows):
            facts=snapshot(i,active=eligible);facts['mint']=row['mint'];facts['pool_address']=row['pool']
            facts['facts']['addresses'].update(mint_a=row['mint'],pool=row['pool'])
            facts['facts']['pool']['mint_a']=row['mint']
            identity=append('pool_snapshot',received_at_ms=received,source_slot=slot,mint=row['mint'],
                outcome='observed',payload=dict(raw_rpc_result=raw))
            result[row['mint']]=dict(context_slot=slot,snapshot_observation_id=identity,analysis=facts)
        return slot,result
    monkeypatch.setattr(active.prospective,'_grouped_snapshot',grouped)
    return sleeps


def test_complete_schedule_is_exactly_twenty_calls_and_selection_precedes_provider_outcomes(tmp_path,monkeypatch):
    sleeps=fake_banks(monkeypatch);transport=WholeTransport()
    session=CampaignSession(transport,20,rpc_url=CANONICAL_RPC_URL)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        transport.store=store
        report=asyncio.run(active.collect_active_cohort(store,session,plan(),provenance='synthetic'))
        assert report['requests_used']==len(transport.calls)==20
        assert report['elapsed_ms']==15000 and sleeps==[15.0]
        assert report['selection']['universe_size']==7 and report['selection']['screened_prefix_count']==6
        assert report['selection']['selected_count']==2
        assert report['provider_quote_attempts']==8 and report['provider_refusals']==2
        assert report['projected_positions']==2 and report['qualified_economic_cycles']==0
        assert report['own_additional_costs_known'] is report['independent_buyers_known'] is False
        assert report['acquisition']['unknown_candidate_count']==2
        fixed=next(e for e in store.events() if e['outcome']=='active_cohort_fixed')
        first_quote=store.events(kind='quote_attempt')[0]
        assert fixed['id']<first_quote['id']
        assert report['tail_hash']==store.verify_integrity()


def test_no_active_case_retains_seven_rows_and_does_not_quote_or_extend_prefix(tmp_path,monkeypatch):
    fake_banks(monkeypatch,eligible=False);transport=WholeTransport()
    session=CampaignSession(transport,20,rpc_url=CANONICAL_RPC_URL)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        transport.store=store
        report=asyncio.run(active.collect_active_cohort(store,session,plan(),provenance='synthetic'))
        assert report['requests_used']==4 and report['selection']['selected_count']==0
        assert report['selection']['universe_size']==7 and report['selection']['screened_prefix_count']==6
        assert report['provider_quote_attempts']==0


def test_buy_transport_error_stops_all_later_sources_after_receipt(tmp_path,monkeypatch):
    fake_banks(monkeypatch);transport=WholeTransport(buy_error=True)
    session=CampaignSession(transport,20,rpc_url=CANONICAL_RPC_URL)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        transport.store=store
        report=asyncio.run(active.collect_active_cohort(store,session,plan(),provenance='synthetic'))
        assert report['requests_used']==len(transport.calls)==5
        assert report['stop_reason']=='source_error_after_persisted_receipt'
        assert report['provider_refusals']==0 and report['provider_unavailable_or_errors']==1
        assert report['selection']['selected_count']==2 and report['acquisition']['universe_size']==7


def test_wrong_endpoint_and_retry_transport_refuse_before_any_request(tmp_path):
    for unsafe in ('endpoint','retry'):
        transport=Transport();transport._retry_connection=unsafe=='retry'
        session=CampaignSession(transport,20,rpc_url=CANONICAL_RPC_URL if unsafe=='retry' else active.cp.RPC_URL)
        with CaptureStore(tmp_path/(unsafe+'.sqlite')) as store:
            with pytest.raises(ValueError,match='anonymous transport'):
                asyncio.run(active.collect_active_cohort(store,session,plan(),provenance='synthetic'))
            assert store.events()==[] and session.requests_used==0 and transport.calls==[]
