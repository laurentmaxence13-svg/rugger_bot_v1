"""Phase-correct LaunchLab PAPER: no AMM Trade API mispricing or false exits."""
import asyncio

import pytest

from bot.p3 import prospective_campaign as prospective
from bot.p3.campaign import CampaignSession
from bot.p3.liquidity_smoke import new_smoke_plan
from bot.p3.quotes import RAYDIUM_QUOTE_URL
from bot.p3.store import CaptureStore
from test_p3_prospective_campaign import WholeCampaignTransport,fast_clock


def plan():
    return dict(prospective.CURVE_PHASE_FIXED,
                registered_at_ms=1,source_revision='a'*40)


def test_phase_only_protocol_rejects_unannounced_mode_changes():
    assert len(prospective.validate_plan(plan()))==64
    old=dict(prospective.FIXED,registered_at_ms=1,source_revision='a'*40)
    assert len(prospective.validate_plan(old))==64
    invalid=plan()
    invalid['partial_rule']='allow_retrospective_sells'
    with pytest.raises(ValueError,match='Unsupported prospective protocol'):
        prospective.validate_plan(invalid)
    invalid=plan()
    invalid['new_unbounded_network_calls']=True
    with pytest.raises(ValueError,match='Unsupported prospective plan fields'):
        prospective.validate_plan(invalid)
    assert new_smoke_plan(revision='a'*40,registered_at_ms=1,
                          curve_phase_only=True)['schema']==prospective.CURVE_PHASE_FIXED['schema']


def test_three_native_curve_bank_frames_no_amm_requests_frozen_before_S2(tmp_path,monkeypatch):
    sleeps=fast_clock(monkeypatch)
    transport=WholeCampaignTransport()
    session=CampaignSession(transport,20)
    with CaptureStore(tmp_path/'curve_phase.sqlite') as store:
        transport.store=store
        report=asyncio.run(prospective.collect_prospective(
            store,session,plan(),provenance='synthetic'))
        events=store.events()
        assert report['tail_hash']==store.verify_integrity()
    assert session.requests_used==len(transport.calls)==8
    assert sleeps==[15.0]
    assert not any(url==RAYDIUM_QUOTE_URL for action,url,_ in transport.calls)
    assert report['selected_corpus_size']==3
    assert report['candidates_with_projected_entry']==0
    assert report['projected_entry_observations']==0
    assert report['full_sell_quotes']==report['full_sell_observation_attempts']==0
    assert report['refused_sell_quotes']==0
    assert report['qualified_economic_quote_scenarios']==0
    assert report['settled_positions']==0 and report['net_pnl_sol'] is None
    assert report['frozen_actual_master_reference_candidates']==3
    assert report['shadow_master_action_counts']=={'WAIT':3}
    assert report['shadow_reference_action_counts']=={'WAIT':3}
    assert report['execution_verified'] is False
    banks=[e for e in events if e['kind']=='pool_snapshot'
           and e.get('outcome')=='observed' and e.get('mint') is not None]
    assert sorted({e['source_slot'] for e in banks})==[11,12]
    for case in report['cases']:
        mint=case['mint']
        frozen=[e for e in events if e.get('mint')==mint and
                e.get('outcome')=='initial_curve_size_grid_frozen']
        shadows=[e for e in events if e.get('mint')==mint and
                 e.get('outcome')=='master_reference_frozen_pre_followup']
        followups=[e for e in events if e.get('mint')==mint and
                   e['kind']=='candidate_decision' and
                   e.get('payload',{}).get('probe_phase')=='followup']
        assert len(frozen)==len(shadows)==len(followups)==1
        assert len(frozen[0]['payload']['frozen_buy_models'])==4
        assert frozen[0]['id']<followups[0]['id']
        assert shadows[0]['id']<followups[0]['id']
        assert all(row['status'] in ('S1_MODEL_QUOTED_NOT_FILLED','UNQUALIFIED')
                   for row in frozen[0]['payload']['frozen_buy_models'])
        assert all(row.get('position_acquired') is not True
                   for row in case.get('projected_entries',[]))
    assert events[-1]['outcome']=='prospective_closed'
    assert events[-1]['payload']['requests_used']==8
    assert events[-1]['payload']['position_acquired'] is False


def test_legacy_protocol_kept_separate_from_curve_only():
    assert 'quote_venue' not in prospective.FIXED
    assert 'quote_venue' in prospective.CURVE_PHASE_FIXED
    assert prospective.CURVE_PHASE_FIXED['max_requests']==20
    assert prospective.CURVE_PHASE_FIXED['max_elapsed_ms']==60000
