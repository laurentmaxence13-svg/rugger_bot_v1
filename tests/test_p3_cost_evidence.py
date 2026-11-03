"""Public transaction costs remain a reference, never our projected fees."""
from copy import deepcopy
import struct

import pytest

from bot.p3.cost_evidence import classify_reference_transaction, COMPUTE_BUDGET_PROGRAM
from test_p3_launchlab import encode


def observation(*, parsed=False):
    signature=encode(bytes([2])*64)
    if parsed:
        instructions=[{'programId':COMPUTE_BUDGET_PROGRAM,'parsed':{'type':'setComputeUnitLimit','info':{'units':200000}}},
                      {'programId':COMPUTE_BUDGET_PROGRAM,'parsed':{'type':'setComputeUnitPrice','info':{'microLamports':5000}}}]
    else:
        instructions=[{'programIdIndex':0,'data':encode(bytes([2])+struct.pack('<I',200000))},
                      {'programIdIndex':0,'data':encode(bytes([3])+struct.pack('<Q',5000))}]
    tx=dict(slot=1234,blockTime=100,meta={'fee':6000,'err':None},transaction={
        'signatures':[signature],'message':{'accountKeys':[COMPUTE_BUDGET_PROGRAM],'instructions':instructions}})
    return dict(kind='transaction',outcome='observed',provenance='synthetic',signature=signature,
        source_slot=1234,source_time_ms=100000,received_at_ms=100010,available_at_ms=100020,
        payload={'raw_transaction':tx})


@pytest.mark.parametrize('parsed',[False,True])
def test_total_reference_fee_and_explicit_budget_are_not_our_costs(parsed):
    event=observation(parsed=parsed);before=deepcopy(event)
    result=classify_reference_transaction(event)
    assert result['known_reference_fee'] is True
    assert result['known_reference_fee_lamports']==6000
    assert result['compute_budget']['compute_unit_limit']==200000
    assert result['compute_budget']['compute_unit_price_micro_lamports']==5000
    assert result['compute_budget']['derived_requested_priority_fee_lamports']==1000
    assert result['compute_budget']['residual_network_fee_lamports']==5000
    assert result['applicability_to_our_scenario']=='UNPROVEN'
    assert result['our_network_fee_lamports'] is result['our_priority_fee_lamports'] is None
    assert result['our_account_rent_lamports'] is result['net_economic_pnl_sol'] is None
    assert result['our_additional_costs_known'] is result['execution_verified'] is False
    assert event==before


@pytest.mark.parametrize('field,value',[('fee',None),('fee',0),('fee',True),('fee',1.5),('blockTime',None),('slot',True)])
def test_missing_or_nonexact_reference_proof_never_becomes_known_cost(field,value):
    event=observation();tx=event['payload']['raw_transaction']
    (tx['meta'] if field=='fee' else tx)[field]=value
    result=classify_reference_transaction(event)
    assert result['known_reference_fee'] is False
    assert result['known_reference_fee_lamports'] is None and result['reasons']


def test_signature_slot_and_chronology_bind_the_captured_reference():
    for altered in ('signature','source_slot','available_at_ms'):
        event=observation()
        event[altered]={'signature':encode(bytes([3])*64),'source_slot':1235,'available_at_ms':100009}[altered]
        assert classify_reference_transaction(event)['known_reference_fee'] is False


def test_failed_transaction_fee_is_observed_but_priority_split_stays_unproven():
    event=observation();event['payload']['raw_transaction']['meta']['err']={'InstructionError':[2,'Custom']}
    result=classify_reference_transaction(event)
    assert result['known_reference_fee_lamports']==6000
    assert result['reference_transaction_succeeded'] is False
    assert result['compute_budget']['derived_requested_priority_fee_lamports'] is None
    assert result['applicability_to_our_scenario']=='UNPROVEN'


def test_duplicate_unknown_or_absent_budget_does_not_invent_zero_priority():
    for shape in ('duplicate','unknown','absent'):
        event=observation();message=event['payload']['raw_transaction']['transaction']['message']
        if shape=='duplicate':message['instructions'].append(deepcopy(message['instructions'][0]))
        elif shape=='unknown':message['instructions'][0]['data']=encode(b'\x09\x00')
        else:message['instructions']=[]
        result=classify_reference_transaction(event)
        assert result['known_reference_fee_lamports']==6000
        assert result['compute_budget']['derived_requested_priority_fee_lamports'] is None
        assert result['our_priority_fee_lamports'] is None


def test_priority_request_above_observed_total_does_not_create_negative_base_fee():
    event=observation();event['payload']['raw_transaction']['meta']['fee']=1
    result=classify_reference_transaction(event)
    assert result['known_reference_fee_lamports']==1
    assert result['compute_budget']['residual_network_fee_lamports'] is None
    assert result['compute_budget']['reasons']==['requested_priority_exceeds_observed_total_fee']
