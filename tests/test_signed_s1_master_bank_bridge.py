"""Signed S1 market-bank bridge is actual data plumbing, never a forced BUY."""
from copy import deepcopy

import pytest

from bot.master_decision import MasterDecisionOrchestrator
from bot.p3.signed_s1_master_bank_bridge import signed_s1_master_bank
from bot.p4.native_asof_signal_bridge import native_asof_bank
from bot.p4_experiment import _bank_for_costs
from test_p3_curve_size_grid import bank

MINT="ChWZ8yNvMh31yHtkZh3fSjWZaQiv62bHr1WPnUPLvuLF"
POOL="EBA8nnnHuFRMHd3Ac9HMMCNTi52E3GXT7HDreXwvhnCu"
CREATOR="HxM1EeyZ9z71m8mu5x9bsUdtTP1f9qtT7mo9D5tB3xwM"
SIG="5qqLenzDgNbLkuN482pPEzoZLyygQYsdLzdMZ2cuKqbpXyXRbXZCASRGw2gWNK91cpBZgorjThhJAhiCtwJk6hUk"
TS=1793500000000

def analysis():
    obj=bank(101,"initial")["payload"]["analysis"]
    obj["evidence_profile"]="published_metadata_v1"
    obj["mint"]=MINT
    obj["pool_address"]=POOL
    obj["facts"]["pool"]["mint_a"]=MINT
    obj["blocking_reasons"]=[
        "execution_not_verified",
        "additional_execution_costs_unknown",
        "creation_transaction_not_verified_by_snapshot",
    ]
    obj["facts"]["identity_certification"]=dict(
        account_discriminators_verified=True,
        program_derived_addresses_verified=True,blocking_reasons=[])
    obj["facts"]["program_derived_addresses_verified"]=True
    obj["facts"]["supply_consistency"]=dict(matches=True,context_slot=101)
    return obj


def transform(source=None,**patch):
    args=dict(analysis=analysis() if source is None else source,
              mint=MINT,pool=POOL,creator=CREATOR,signature=SIG,
              source_slot=101,received_at_ms=TS,
              raw_bank_sha256="e"*64,signed_creation_verified=True)
    args.update(patch)
    return signed_s1_master_bank(**args)


def test_signed_bank_actually_reaches_master_cost_model_but_waits():
    evidence,refusal=transform()
    assert refusal is None
    assert evidence["source_slot"]==101
    assert evidence["fee_rates_ppm"]==[2500,10000,5000]
    assert evidence["pool_state"]["mint_a"]==MINT
    assert evidence["quote_vault_lamports"]==5_003_000_000
    assert evidence["identity_qualified"] is True
    assert evidence["creation_verified"] is True
    assert evidence["supply_verified"] is True
    frame=dict(id="signed-real-bank-test",mint=MINT,pool=POOL,creator=CREATOR,
               detected_at_ms=TS-2000,available_at_ms=TS,
               source_slot=101,slot_available_at_ms=TS,
               data_kind="market_observation",bank_state=evidence,
               features=None,features_available_at_ms=None,independent_buyers=None)
    allowed,reason=_bank_for_costs(frame,TS)
    assert reason is None and allowed==evidence
    decision=MasterDecisionOrchestrator().evaluate(
        frame,[],inventory=None,health=None,capital=None)
    assert decision["action"]=="WAIT"
    assert "source_identity_supply_creation_unqualified" not in decision["reasons"]
    assert "qualified_past_edge_evidence_unavailable" in decision["reasons"]
    assert decision["execution_authorized"] is False
    assert decision["decision_evidence"]["features_available_at_ms"] is None


@pytest.mark.parametrize("override,reason",[
    ({"signed_creation_verified":False},"S1_SIGNED_CONTEXT_OR_PROVENANCE_UNVERIFIED"),
    ({"raw_bank_sha256":"fake"},"S1_SIGNED_CONTEXT_OR_PROVENANCE_UNVERIFIED"),
    ({"source_slot":102},"S1_SIGNED_CONTEXT_OR_PROVENANCE_UNVERIFIED"),
    ({"mint":"other"},"S1_SIGNED_CONTEXT_OR_PROVENANCE_UNVERIFIED"),
])
def test_wrong_or_unverified_source_does_not_create_a_bank(override,reason):
    evidence,refusal=transform(**override)
    assert evidence is None and refusal==reason


@pytest.mark.parametrize("field,value,reason",[
    ("risk_flags",["pool_not_in_active_launch_curve"],"S1_BANK_RISK_OR_UNKNOWN_BLOCKER"),
    ("blocking_reasons",["unverified_authority"],"S1_BANK_RISK_OR_UNKNOWN_BLOCKER"),
    ("facts.identity_certification",{"account_discriminators_verified":True,
         "program_derived_addresses_verified":False,"blocking_reasons":[]},
     "S1_BANK_IDENTITY_NOT_INDEPENDENTLY_CERTIFIED"),
    ("facts.supply_consistency",{"matches":False,"context_slot":101},
     "S1_BANK_SUPPLY_NOT_RECONCILED"),
])
def test_risky_or_ambiguous_account_evidence_cannot_promote_source(field,value,reason):
    obj=analysis()
    parent=obj
    nodes=field.split(".")
    for node in nodes[:-1]:
        parent=parent[node]
    parent[nodes[-1]]=value
    state,refusal=transform(source=obj)
    assert state is None and refusal==reason


def test_missing_reserve_and_fee_fact_stays_unknown():
    obj=analysis()
    obj["facts"]["base_vault"].pop("amount_atomic")
    bank_data,refusal=transform(source=obj)
    assert bank_data is None
    assert refusal=="S1_BANK_FEE_OR_RESERVE_FACTS_UNQUALIFIED"


def test_native_s1_SOL_curve_spot_can_use_nonfinancial_blockers_only():
    a=analysis()
    received=native_asof_bank(analysis=a,mint=MINT,creator=CREATOR,pool=POOL,
                             source_slot=101,available_at_ms=TS)
    assert received["source_native_facts_observed"] is True
    assert received["price_usd"] is None
    assert received["complete_SignalFeatures_available"] is False
    assert received["source_price_is_curve_model_not_executable_quote"] is True
    a["blocking_reasons"].append("vault_authority_PDA_not_certified")
    with pytest.raises(ValueError,match="unqualified_source_curve_bank_flags"):
        native_asof_bank(analysis=a,mint=MINT,creator=CREATOR,pool=POOL,
                         source_slot=101,available_at_ms=TS)


def partial_platform_admin_analysis():
    obj=analysis()
    obj["blocking_reasons"].append("original_platform_admin_seed_not_retained")
    obj["facts"]["program_derived_addresses_verified"]=False
    obj["facts"]["identity_certification"].update(
        program_derived_addresses_verified=False,
        blocking_reasons=["original_platform_admin_seed_not_retained"],
        checks=[{"name":k,"status":"PASS"} for k in (
            "pool_pda","vault_a_pda","vault_b_pda",
            "config_pda","authority_pda")]+[
            {"name":"platform_pda","status":"UNKNOWN",
             "reason":"original_platform_admin_seed_not_retained"}],
    )
    return obj


def test_real_world_platform_admin_seed_unknown_retains_model_but_vetoes_entry():
    obj=partial_platform_admin_analysis()
    source,level=transform(source=obj)
    assert level=="S1_PARTIAL_PLATFORM_ADMIN_UNKNOWN_MODEL_ONLY"
    assert source["identity_qualified"] is False
    assert source["creation_verified"] is True
    assert source["platform_admin_pda_unverified"] is True
    assert source["research_only_no_execution"] is True
    frame=dict(id="signed-partial-platform-s1",mint=MINT,pool=POOL,
               creator=CREATOR,detected_at_ms=TS-2000,
               available_at_ms=TS,source_slot=101,slot_available_at_ms=TS,
               data_kind="market_observation",bank_state=source,
               features=None,features_available_at_ms=None,independent_buyers=None)
    bank_data,error=_bank_for_costs(frame,TS)
    assert bank_data is not None and error is None
    decision=MasterDecisionOrchestrator().evaluate(
        frame,[],inventory=None,health=None,capital=None)
    assert decision["action"]=="WAIT"
    assert "source_identity_supply_creation_unqualified" in decision["reasons"]
    assert "qualified_past_edge_evidence_unavailable" in decision["reasons"]
    assert decision["execution_authorized"] is False
    native=native_asof_bank(analysis=obj,mint=MINT,creator=CREATOR,
                           pool=POOL,source_slot=101,available_at_ms=TS)
    assert native["source_native_facts_observed"] is True
    assert native["platform_admin_seed_independently_certified"] is False
    assert native["price_usd"] is None
    assert native["complete_SignalFeatures_available"] is False


def test_any_additional_unknown_identity_or_risky_account_refuses_partial_mode():
    base=partial_platform_admin_analysis()
    wrong=deepcopy(base)
    wrong["facts"]["identity_certification"]["checks"].append(
        {"name":"unknown_critical_vault","status":"UNKNOWN"})
    assert transform(source=wrong)[0] is None
    bad=deepcopy(base)
    bad["facts"]["identity_certification"]["checks"][0]["status"]="FAIL"
    assert transform(source=bad)[0] is None
    corrupt=deepcopy(base)
    corrupt["facts"]["supply_consistency"]["matches"]=False
    assert transform(source=corrupt)[0] is None
    malicious=deepcopy(base)
    malicious["risk_flags"].append("mint_authority_present")
    assert transform(source=malicious)[0] is None
