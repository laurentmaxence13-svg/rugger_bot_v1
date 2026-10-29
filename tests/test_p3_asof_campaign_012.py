"""Causal012 runner on actual decoded SYNTHETIC banks; zero external traffic."""
import asyncio
from copy import deepcopy
import time

import pytest

from bot.p3 import asof_campaign_012 as capture
from bot.p3.asof_protocol_012 import make_plan
from bot.p3.campaign import CampaignSession, INDEX_URL
from bot.p3.collect import now_ms
from bot.p3.store import CaptureStore
from test_p3_asof_real_decoder_integration import _advance_accounts
from test_p3_campaign import indexed, payload
from test_p3_collection import Transport, rpc
from test_p3_quotes import Response
from test_p3_research_integration import research_snapshot
from test_p3_platform_real_pda_integration import _record
from test_p3_launchlab import mutate_account


def plan():return make_plan(registered_at_ms=1,source_revision='a'*40)


def clock(monkeypatch):
    wall=time.time_ns;mono=time.monotonic_ns;offset=[0];sleeps=[]
    monkeypatch.setattr(time,'time_ns',lambda:wall()+offset[0])
    monkeypatch.setattr(time,'monotonic_ns',lambda:mono()+offset[0])
    async def wait(seconds):
        sleeps.append(seconds);offset[0]+=int(seconds*1000000000)
    monkeypatch.setattr(capture.asyncio,'sleep',wait)
    return sleeps


class Market:
    _retry_connection=False
    def __init__(self,*,moving=True,same_slot=False,error_at=None):
        self.rows=[];self.s0={};self.s1={};self.s2={};self.calls=[];self.bank=0
        self.same_slot=same_slot;self.error_at=error_at
        for index in range(12):
            accounts,addresses,_,_=research_snapshot(index,return_accounts=True)
            self.rows.append(indexed(mint=addresses['mint_a'],pool=addresses['pool']))
            advanced=(_advance_accounts(accounts,addresses,token_atomic=1000000,sol_lamports=1000000)
                if moving and index in (7,10) else deepcopy(accounts))
            future=(_advance_accounts(advanced,addresses,token_atomic=2000000,sol_lamports=2000000)
                if moving and index in (7,10) else deepcopy(advanced))
            self.s0.update(accounts);self.s1.update(advanced);self.s2.update(future)
    def get(self,url,**kwargs):
        self.calls.append(('GET',url,deepcopy(kwargs)))
        assert url==INDEX_URL and kwargs['params']=={'sort':'lastTrade'}
        return Response(payload(*self.rows,self.rows[7],{'mint':'invalid'}))
    def post(self,url,**kwargs):
        self.calls.append(('POST',url,deepcopy(kwargs)))
        if self.error_at==len(self.calls):return Response(status=429)
        method,params=kwargs['json']['method'],kwargs['json']['params']
        if method=='getMultipleAccounts':
            self.bank+=1
            accounts=self.s0 if self.bank<=2 else (self.s1 if self.bank==3 else self.s2)
            slot=100+self.bank if not self.same_slot or self.bank<3 else 102
            return rpc(dict(context=dict(slot=slot),value=[accounts[a] for a in params[0]]))
        if method=='getBlockTime':return rpc(now_ms()//1000)
        assert method=='getSignaturesForAddress' and params[1]['limit']==1000
        return rpc([])


def session(market):return CampaignSession(market,20,rpc_url=plan()['rpc_source'],
    bounded_phases=True,discovery_sort='lastTrade')


def test_real_parser_wide_causal_capture_replay_sizes_and_fee_unknowns(tmp_path,monkeypatch):
    sleeps=clock(monkeypatch);market=Market()
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(capture.collect_asof_012(store,session(market),plan(),provenance='synthetic'))
        assert result['stop_reason'] is None,result
        assert result['requests_used']==len(market.calls)==10
        assert len(sleeps)==2
        assert result['universe_size']==14
        selection=result['selection']
        assert selection['selected_count']==2
        assert [s['universe_index'] for s in selection['selected']]==[7,10]
        assert selection['assessments'][12]['reason']=='duplicate_mint_or_pool'
        assert selection['assessments'][13]['reason']=='invalid_or_outside_native_SOL_scope'
        assert result['replayed_raw_analyses']==26
        assert len(result['markouts'])==12
        for mark in result['markouts']:
            assert mark['status']=='CONDITIONAL_BANK_MARKOUT',mark
            assert mark['modeled_unliquidated_quantity_atomic']=='0'
            assert mark['economic_cycle_qualified'] is False
            assert mark['net_market_pnl_sol'] is None
            if mark['cost_scenario']=='unknown_ATA':
                assert mark['full_cost_conditional_lower_lamports'] is None
                assert mark['cost_bounds']['cost_upper_lamports'] is None
        quantities={m['entry_budget_lamports']:int(m['projected_entry_quantity_atomic']) for m in result['markouts']}
        assert quantities['1000000000']!=quantities['100000000']*10
        events=store.events()
        assert all(e['payload']['elapsed_ms']>=15000 for e in events
                   if e['outcome']=='asof_interval_completed')
        fixed=next(e for e in events if e['outcome']=='asof_selection_fixed')
        ab=next(e for e in events if e['outcome']=='asof_master_reference_fixed')
        s2=next(e for e in events if e['payload'].get('phase')=='S2')
        assert fixed['id']<ab['id']<s2['id']
        assert capture.build_report(store,plan())==result
        assert result['qualified_economic_cycles']==0


def test_static_prefix_never_triggers_outcome_collection(tmp_path,monkeypatch):
    sleeps=clock(monkeypatch);market=Market(moving=False)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(capture.collect_asof_012(store,session(market),plan(),provenance='synthetic'))
    assert result['stop_reason'] is None
    assert result['selection']['selected_count']==0
    assert result['requests_used']==8 and len(sleeps)==1
    assert result['markouts']==[]


@pytest.mark.parametrize('status',[402,403,429,500])
def test_first_source_error_stops_without_retry_or_fallback(tmp_path,status):
    market=Transport(gets=[Response(status=status)]);market._retry_connection=False
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(capture.collect_asof_012(store,session(market),plan(),provenance='synthetic'))
    assert result['requests_used']==len(market.calls)==1
    assert result['stop_reason']=='source_error_after_persisted_receipt'
    assert result['discovery_universe_known'] is False
    assert result['qualified_economic_cycles']==0


def test_same_slot_S1_is_a_blocking_source_error(tmp_path,monkeypatch):
    sleeps=clock(monkeypatch);market=Market(same_slot=True)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(capture.collect_asof_012(store,session(market),plan(),provenance='synthetic'))
    assert result['stop_reason']=='malformed_or_out_of_order_group_bank'
    assert result['selection'] is None and result['markouts']==[]
    assert result['requests_used']==7 and len(sleeps)==1


def test_history_transport_error_stops_before_S1(tmp_path,monkeypatch):
    sleeps=clock(monkeypatch);market=Market(error_at=5)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(capture.collect_asof_012(store,session(market),plan(),provenance='synthetic'))
    assert result['requests_used']==5 and sleeps==[]
    assert result['stop_reason']=='source_error_after_persisted_receipt'
    assert result['replayed_raw_analyses']==12


def test_interrupted_prefix_can_only_be_replayed_and_never_resumed(tmp_path):
    p=plan()
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        store.append('checkpoint',received_at_ms=now_ms(),provenance='synthetic',outcome='asof_plan_registered',
            payload=dict(plan=p,plan_sha256=capture.validate_plan(p)))
        with pytest.raises(ValueError,match='interrupted'):capture.build_report(store,p)
        result=capture.build_report(store,p,allow_interrupted=True)
        assert not result['closed'] and not result['network_resume_permitted']
        assert result['stop_reason'].startswith('interrupted_committed_prefix')
        with pytest.raises(ValueError,match='Fresh bounded'):
            asyncio.run(capture.collect_asof_012(store,session(Market()),p,provenance='synthetic'))


def test_existing_capture_cli_refuses_before_read_or_network(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('Forbidden plan read')
    monkeypatch.setattr(capture.Path,'read_text',forbidden)
    with pytest.raises(SystemExit) as error:
        capture.main(['--network','--plan',str(tmp_path/'.env.json'),'--db',str(tmp_path/'new.sqlite'),
            '--output',str(tmp_path/'new.json')])
    assert error.value.code==2


def test_costs_separate_hypothetical_network_fees_from_unknown_ATA():
    costs=capture.cost_scenarios(plan())
    for cost in costs.values():
        assert cost['economic_fee_cost_lower_lamports']=='10000'
        assert cost['economic_fee_cost_upper_lamports']=='25600'
        assert not cost['all_applicable_costs_known']
    assert costs['unknown_ATA']['cost_upper_lamports'] is None
    assert costs['hypothetical_existing_ATA']['cost_upper_lamports']=='25600'
    assert costs['hypothetical_new_classic_ATA']['cash_commitment_upper_lamports']=='2064880'


class HistoricalMarket(Market):
    def __init__(self,*,malformed=False):
        self.calls=[];self.bank=0;self.same_slot=False;self.error_at=None
        self.malformed=malformed
        accounts,addresses,_,_=research_snapshot(platform_verified=True,return_accounts=True)
        mutate_account(accounts,addresses['platform'],16,bytes([90])*32)
        self.s0=accounts
        self.s1=_advance_accounts(accounts,addresses,token_atomic=1000000,sol_lamports=1000000)
        self.s2=_advance_accounts(self.s1,addresses,token_atomic=1000000,sol_lamports=1000000)
        self.rows=[indexed(mint=addresses['mint_a'],pool=addresses['pool'])]
        self.tx=_record(unknown_original_seed=True)[3]
        self.platform=addresses['platform']
    def get(self,url,**kwargs):
        self.calls.append(('GET',url,deepcopy(kwargs)))
        assert url==INDEX_URL
        return Response(payload(*self.rows))
    def post(self,url,**kwargs):
        method,params=kwargs['json']['method'],kwargs['json']['params']
        if method in ('getSignaturesForAddress','getTransaction'):
            self.calls.append(('POST',url,deepcopy(kwargs)))
            if method=='getSignaturesForAddress':
                assert params[0]==self.platform
                return rpc([dict(signature=self.tx['transaction']['signatures'][0],slot=self.tx['slot'],err=None)])
            tx=deepcopy(self.tx)
            if self.malformed:tx['slot']+=1
            return rpc(tx)
        response=super().post(url,**kwargs)
        # The historical slot1233 must precede every bank, not merely receipt.
        if method=='getMultipleAccounts':
            accounts=self.s0 if self.bank<=2 else (self.s1 if self.bank==3 else self.s2)
            return rpc(dict(context=dict(slot=1234+self.bank),value=[accounts[a] for a in params[0]]))
        return response


def test_retained_historical_source_binding_refines_only_canonical_platform_seed(tmp_path,monkeypatch):
    clock(monkeypatch);market=HistoricalMarket()
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(capture.collect_asof_012(store,session(market),plan(),provenance='synthetic'))
        assert result['stop_reason'] is None,result
        assert result['requests_used']==10
        assert result['selection']['selected'][0]['admission_lane']=='STRICT_OBSERVATION'
        # Original raw analyses preserve their UNKNOWN; the frozen copy alone
        # has a bounded, causally available historical PDA refinement.
        raw=[e for e in store.events() if e['kind']=='candidate_decision' and e['payload'].get('probe_phase')=='S1'][0]
        assert raw['payload']['analysis']['facts']['identity_certification']['program_derived_addresses_verified'] is False
        bank=result['selection']['original_strict_selection']['records'][0]['source_row']['snapshot']
        refinement=bank['facts']['historical_platform_refinement']
        assert refinement['proof_available_at_ms']<=result['selection']['decision_at_ms']
        assert not refinement['cryptographic_signature_verified']
        assert result['qualified_economic_cycles']==0 and result['net_market_pnl_sol'] is None
        assert capture.build_report(store,plan())==result


def test_historical_body_slot_disagreement_stops_global_capture(tmp_path,monkeypatch):
    sleeps=clock(monkeypatch);market=HistoricalMarket(malformed=True)
    with CaptureStore(tmp_path/'capture.sqlite') as store:
        result=asyncio.run(capture.collect_asof_012(store,session(market),plan(),provenance='synthetic'))
    assert result['requests_used']==6 and sleeps==[]
    assert result['stop_reason']=='historical_transaction_identity_or_shape_invalid'
    assert result['selection'] is None
