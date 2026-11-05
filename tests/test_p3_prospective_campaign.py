"""Whole prospective pipeline on three synthetic graphs and one wire budget."""
import asyncio
from copy import deepcopy
import time

import pytest

from bot.p3 import prospective_campaign as prospective
from bot.p3.campaign import CampaignSession
from bot.p3.quotes import RAYDIUM_QUOTE_URL, SOL_MINT
from bot.p3.store import CaptureStore
from test_p3_campaign import indexed, payload
from test_p3_cost_evidence import observation
from test_p3_launchlab import fixture, encode, decode, mutate_account
from test_p3_quotes import Response, quote_payload
from test_p3_collection import rpc


def plan():
    return dict(prospective.FIXED, registered_at_ms=1, source_revision='a'*40)


def three_graphs():
    """Separate synthetic pools/vaults, shared WSOL mint, same creator claim."""
    accounts, rows = {}, []
    for n in range(3):
        original, old = fixture()
        new = {role: SOL_MINT if role == 'mint_b' else encode(bytes([1+n*40+i])*32)
               for i, role in enumerate(old)}
        for role, offset in (('config',141),('platform',173),('mint_a',205),
                             ('mint_b',237),('vault_a',269),('vault_b',301)):
            mutate_account(original,old['pool'],offset,decode(new[role]))
        mutate_account(original,old['vault_a'],0,decode(new['mint_a']))
        for role, address in old.items():
            accounts[new[role]] = deepcopy(original[address])
        rows.append(indexed(mint=new['mint_a'],pool=new['pool']))
    return accounts, rows


class WholeCampaignTransport:
    """Answer from requested public identities, with no external I/O or retries."""
    _retry_connection = False

    def __init__(self, *, stale_followup=False, partial_refused=False):
        self.accounts,self.rows = three_graphs()
        self.outputs = {row['mint']: str(value) for row,value in
                        zip(self.rows,(25_000_000,40_000_000,60_000_000))}
        self.full_seen = {mint:0 for mint in self.outputs}
        self.calls = []
        self.bank_calls = 0
        self.stale_followup = stale_followup
        self.partial_refused = partial_refused
        self.store = None

    def post(self,url,**kwargs):
        self.calls.append(('POST',url,deepcopy(kwargs)))
        method,params = kwargs['json']['method'],kwargs['json']['params']
        if method == 'getMultipleAccounts':
            self.bank_calls += 1
            slot = {1:10,2:11,3:11 if self.stale_followup else 12}[self.bank_calls]
            assert len(params[0]) == (3 if self.bank_calls == 1 else 19)
            if self.bank_calls == 2: assert params[1]['minContextSlot'] == 10
            if self.bank_calls == 3: assert params[1]['minContextSlot'] == 12
            return rpc({'context':{'slot':slot},'value':[self.accounts[a] for a in params[0]]})
        if method == 'getBlockTime':
            assert params[0] in (11,12)
            return rpc(100+params[0])
        reference = observation()['payload']['raw_transaction']
        if method == 'getSignaturesForAddress':
            assert params == [self.rows[0]['poolId'],{'limit':1,'commitment':'confirmed'}]
            return rpc([dict(signature=reference['transaction']['signatures'][0],
                             slot=reference['slot'],err=None,blockTime=reference['blockTime'])])
        assert method == 'getTransaction'
        assert params[0] == reference['transaction']['signatures'][0]
        return rpc(reference)

    def get(self,url,**kwargs):
        self.calls.append(('GET',url,deepcopy(kwargs)))
        if url != RAYDIUM_QUOTE_URL:
            assert len(self.calls) == 1
            return Response(payload(*self.rows))
        request = kwargs['params']
        if request['inputMint'] == SOL_MINT:
            mint = request['outputMint']; output = self.outputs[mint]
            assert request['amount'] == '1000000000'
            return Response(quote_payload(output_mint=mint,output=output,
                minimum=str(int(output)*99//100)))
        mint,amount = request['inputMint'],request['amount']
        fixed = [e for e in self.store.events() if e.get('mint') == mint
                 and e.get('outcome') == 'projected_inventory_fixed']
        assert len(fixed) == 1  # Exact size and quarter fixed before ANY sell.
        assert fixed[0]['payload']['acquired_atomic'] == self.outputs[mint]
        quarter = str(int(self.outputs[mint])//4)
        assert fixed[0]['payload']['partial_diagnostic_atomic'] == quarter
        if amount == self.outputs[mint]:
            self.full_seen[mint] += 1
            if self.full_seen[mint] == 1:
                return Response({'success':False,'msg':'INSUFFICIENT_LIQUIDITY'})
            assert self.bank_calls == 3
            return Response(quote_payload(input_mint=mint,output_mint=SOL_MINT,
                amount=amount,output='1100000000',minimum='1089000000'))
        assert amount == quarter and self.full_seen[mint] == 1
        if self.partial_refused:
            return Response({'success':False,'msg':'INSUFFICIENT_LIQUIDITY'})
        return Response(quote_payload(input_mint=mint,output_mint=SOL_MINT,
            amount=amount,output='200000000',minimum='198000000'))


def fast_clock(monkeypatch):
    ticks = [time.monotonic_ns()]
    sleeps = []
    monkeypatch.setattr(prospective.time,'monotonic_ns',lambda:ticks[0])
    monkeypatch.setattr(prospective.time,'monotonic',lambda:ticks[0]/1_000_000_000)
    async def advance(seconds):
        sleeps.append(seconds)
        ticks[0] += int(seconds*1_000_000_000)
    monkeypatch.setattr(prospective.asyncio,'sleep',advance)
    return sleeps


def run_whole(tmp_path,monkeypatch,**transport_options):
    sleeps=fast_clock(monkeypatch)
    transport=WholeCampaignTransport(**transport_options)
    session=CampaignSession(transport,20)
    with CaptureStore(tmp_path/'whole.sqlite') as store:
        transport.store=store
        report=asyncio.run(prospective.collect_prospective(store,session,plan(),provenance='synthetic'))
        events=store.events()
        assert report['tail_hash']==store.verify_integrity()
    return transport,session,report,events,sleeps


@pytest.mark.parametrize('partial_refused',[False,True])
def test_three_candidates_full_partial_followup_and_fee_share_exact_global_budget(tmp_path,monkeypatch,partial_refused):
    transport,session,report,events,sleeps=run_whole(tmp_path,monkeypatch,partial_refused=partial_refused)
    assert len(transport.calls)==session.requests_used==20
    assert sleeps==[15.0]
    assert events[-1]['payload']['stop_reason'] is None
    assert events[-1]['payload']['elapsed_ms']==15_000
    assert [row['mint'] for row in next(e for e in events if e['outcome']=='prospective_prefix_fixed')['payload']['candidates']]==list(transport.outputs)
    assert report['selected_corpus_size']==report['candidates_analyzed']==report['candidates_with_projected_entry']==3
    assert report['full_sell_observation_attempts']==6
    assert report['partial_sell_observation_attempts']==3
    assert report['full_sell_quotes']==3
    assert report['partial_sell_quotes']==(0 if partial_refused else 3)
    assert report['refused_sell_quotes']==(6 if partial_refused else 3)
    assert report['qualified_economic_quote_scenarios']==report['settled_positions']==0
    assert report['net_pnl_sol'] is None
    assert report['execution_verified'] is False
    assert report['creator_groups_observed']==1 and report['effective_independent_sample_size'] is None
    assert report['p4']['assignment_preregistered'] is True
    assert report['p4']['holdout_candidates']==0 and report['p4']['model_selected'] is False
    provider_quotes=[e for e in events if e['kind']=='quote_attempt'
                     and e['payload'].get('provider')=='raydium_trade_api']
    assert len(provider_quotes)==12
    assert all(e['source_time_ms'] is e['source_slot'] is None for e in provider_quotes)
    for case in report['cases']:
        assert case['distinct_bank_slots']==[11,12]
        assert case['max_quoted_inventory_fraction_by_phase']==({'followup':'1'} if partial_refused else {'followup':'1','initial':'1/4'})
        assert case['additional_fees_applicable'] is False
        assert case['quote_source_times_unknown']==case['quote_source_slots_unknown']==4
    bank_times=[e for e in events if e['outcome']=='onchain_bank_time']
    assert [e['source_slot'] for e in bank_times]==[11,12]
    assert all(e['payload']['time_basis']=='estimated_block_production_time_not_provider_quote_time' for e in bank_times)
    reference=next(e for e in events if e['outcome']=='additional_fee_reference')['payload']
    assert reference['classification']['known_reference_fee_lamports']==6000
    assert reference['classification']['our_network_fee_lamports'] is None
    assert reference['applicability_to_our_scenario']=='UNPROVEN'
    assert reference['our_additional_costs_known'] is False


def test_nonadvancing_followup_bank_stops_without_followup_quotes_or_fee_request(tmp_path,monkeypatch):
    transport,session,report,events,_=run_whole(tmp_path,monkeypatch,stale_followup=True)
    assert len(transport.calls)==session.requests_used==14
    assert events[-1]['payload']['stop_reason']=='source_error_after_persisted_receipt'
    assert report['selected_corpus_size']==report['candidates_with_projected_entry']==3
    assert report['full_sell_quotes']==0 and report['partial_sell_quotes']==3
    assert report['full_sell_observation_attempts']==3
    assert all(case['distinct_bank_slots']==[11] for case in report['cases'])
    assert not any(call[0]=='POST' and call[2]['json']['method'] in
                   ('getSignaturesForAddress','getTransaction') for call in transport.calls)
    assert not any(e['kind']=='quote_attempt' and e['payload'].get('probe_phase')=='followup'
                   for e in events)
