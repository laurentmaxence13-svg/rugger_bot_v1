"""Entire011 pipeline on decoded synthetic banks, never live market data."""
import asyncio
from copy import deepcopy
import time

import pytest

from bot.p3 import research_campaign as research
from bot.p3.campaign import CampaignSession,INDEX_URL
from bot.p3.collect import CANONICAL_RPC_URL,now_ms
from bot.p3.quotes import SOL_MINT,RAYDIUM_QUOTE_URL
from bot.p3.store import CaptureStore
from test_p3_campaign import indexed,payload
from test_p3_collection import rpc,Transport
from test_p3_quotes import Response,quote_payload
from test_p3_research_integration import research_snapshot
from test_p3_cost_evidence import observation


def plan():return research.make_plan(registered_at_ms=1,source_revision='a'*40)


def clock(monkeypatch):
    real_ns=time.time_ns;real_mono=time.monotonic_ns;offset=[0];sleeps=[]
    monkeypatch.setattr(time,'time_ns',lambda:real_ns()+offset[0])
    monkeypatch.setattr(time,'monotonic_ns',lambda:real_mono()+offset[0])
    async def wait(seconds):
        sleeps.append(seconds);offset[0]+=int(seconds*1000000000)
    monkeypatch.setattr(research.asyncio,'sleep',wait)
    return sleeps


class SyntheticMarket:
    _retry_connection=False
    def __init__(self,*,error=False,refuse_sells=False,omit_context=False):
        self.accounts={};self.rows=[];self.calls=[];self.bank=0
        self.error=error;self.refuse_sells=refuse_sells;self.omit_context=omit_context
        for index in range(2):
            accounts,addresses,analysis,screen=research_snapshot(index,return_accounts=True)
            self.accounts.update(accounts)
            self.rows.append(indexed(mint=addresses['mint_a'],pool=addresses['pool']))
    def post(self,url,**kwargs):
        self.calls.append(('POST',url,deepcopy(kwargs)))
        method,params=kwargs['json']['method'],kwargs['json']['params']
        if method=='getMultipleAccounts':
            self.bank+=1
            return rpc(dict(context=dict(slot=100+self.bank),value=[self.accounts[a] for a in params[0]]))
        if method=='getBlockTime':return rpc(now_ms()//1000)
        tx=observation()['payload']['raw_transaction']
        if method=='getSignaturesForAddress':return rpc([dict(signature=tx['transaction']['signatures'][0],slot=tx['slot'],err=None)])
        assert method=='getTransaction';return rpc(tx)
    def get(self,url,**kwargs):
        self.calls.append(('GET',url,deepcopy(kwargs)))
        if url==INDEX_URL:
            assert kwargs['params']=={'sort':'lastTrade'}
            return Response(payload(*self.rows))
        assert url==RAYDIUM_QUOTE_URL
        if self.error:return Response(status=429)
        p=kwargs['params'];buy=p['inputMint']==SOL_MINT
        if not buy and self.refuse_sells:return Response({'success':False,'msg':'INSUFFICIENT_LIQUIDITY'})
        amount=p['amount']
        output=('1000' if amount=='100000000' else '10000') if buy else ('99000000' if amount=='1000' else '980000000')
        body=quote_payload(p['inputMint'],p['outputMint'],amount,output,str(int(output)*99//100))
        if self.omit_context:
            for field in ('actualInputAmount','sourceTimeMs','contextSlot'):body['data'].pop(field,None)
        else:body['data'].update(sourceTimeMs=now_ms(),contextSlot=100+self.bank)
        return Response(body)


def session(fake):return CampaignSession(fake,20,rpc_url=CANONICAL_RPC_URL,bounded_phases=True,discovery_sort='lastTrade')


def test_full_pipeline_has_separate_sizes_known_Q_causal_exits_and_no_strict_admission(tmp_path,monkeypatch):
    sleeps=clock(monkeypatch);fake=SyntheticMarket()
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        report=asyncio.run(research.collect_research_cohort(store,session(fake),plan(),provenance='synthetic'))
        assert report['requests_used']==len(fake.calls)==20
        assert report['stop_reason'] is None and sleeps==[15.0]
        assert report['selection']['selected_count']==2 and report['strict_selection']['selected_count']==0
        economics=report['economics']
        assert len(economics['projected_inventories'])==4
        assert economics['complete_receipt_linked_indicative_pairs']==8
        assert economics['complete_receipt_linked_live_market_pairs']==0
        assert economics['complete_receipt_linked_synthetic_pairs']==8
        assert economics['prospective_economic_cycles_usable']==economics['strict_market_cycles']==0
        assert report['net_market_pnl_sol'] is None
        events=store.events();fixed=next(e for e in events if e['outcome']=='research_quote_intents_fixed')
        quotes=[e for e in events if e['kind']=='quote_attempt' and e['payload'].get('provider')=='raydium_trade_api']
        assert all(fixed['id']<e['id'] for e in quotes)
        assert {i['budget_lamports']:i['acquired_atomic'] for i in economics['projected_inventories']}=={'100000000':'1000','1000000000':'10000'}
        for row in economics['research_cycles']:
            assert row['trade_allowed'] is row['execution_verified'] is False
            assert row['curve_or_route_fees_already_in_quote_counted_again'] is False
            if row['exit_phase']=='followup':assert row['elapsed_after_inventory_decision_ms']>=15000
        assert research.build_report(store,plan())==report


def test_missing_actual_input_and_provider_clocks_do_not_stop_research_but_stay_unknown(tmp_path,monkeypatch):
    clock(monkeypatch);fake=SyntheticMarket(omit_context=True)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        report=asyncio.run(research.collect_research_cohort(store,session(fake),plan(),provenance='synthetic'))
    assert report['requests_used']==20
    assert report['economics']['complete_receipt_linked_indicative_pairs']==8
    assert all(not r['source_timing_qualified'] and not r['actual_inputs_explicit'] for r in report['economics']['research_cycles'])
    assert report['qualified_economic_cycles']==0 and report['net_market_pnl_sol'] is None


def test_http_failure_stops_before_any_other_quote_or_followup(tmp_path,monkeypatch):
    sleeps=clock(monkeypatch);fake=SyntheticMarket(error=True)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        report=asyncio.run(research.collect_research_cohort(store,session(fake),plan(),provenance='synthetic'))
    assert report['requests_used']==len(fake.calls)==5 and sleeps==[]
    assert report['stop_reason']=='source_error_after_persisted_receipt'
    assert report['selection']['selected_count']==2 and report['strict_selection']['selected_count']==0


def test_logical_refusals_keep_full_inventory_and_every_fixed_horizon_without_replacement(tmp_path,monkeypatch):
    clock(monkeypatch);fake=SyntheticMarket(refuse_sells=True)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        report=asyncio.run(research.collect_research_cohort(store,session(fake),plan(),provenance='synthetic'))
    assert report['requests_used']==20 and report['stop_reason'] is None
    assert len(report['economics']['research_cycles'])==8
    assert report['economics']['complete_receipt_linked_indicative_pairs']==0
    assert all(r['status']=='REFUSED' and r['retained_projected_quantity_atomic'] in ('1000','10000') for r in report['economics']['research_cycles'])


@pytest.mark.parametrize('status',[402,403,429,500])
def test_discovery_failure_keeps_universe_unknown_and_one_global_attempt(tmp_path,status):
    fake=Transport(gets=[Response(status=status)]);fake._retry_connection=False
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        report=asyncio.run(research.collect_research_cohort(store,session(fake),plan(),provenance='synthetic'))
    assert report['requests_used']==1 and report['discovery_universe_known'] is False
    assert len(fake.calls)==1 and report['economics']['complete_receipt_linked_indicative_pairs']==0


def test_direct_cli_refuses_private_named_plan_before_reading_or_network(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('Forbidden plan was read')
    monkeypatch.setattr(research.Path,'read_text',forbidden)
    with pytest.raises(SystemExit) as error:
        research.main(['--network','--plan',str(tmp_path/'.env.json'),'--db',str(tmp_path/'new.sqlite'),'--output',str(tmp_path/'new.json')])
    assert error.value.code==2
