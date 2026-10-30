"""Source-causal LIVE fee checks. No external RPC, signer or wallet."""
import json

import pytest

from test_live_engine import configured, run
from test_live_cpmm_engine import configured_cpmm


@pytest.mark.parametrize('route', ('launchlab_buy', 'cpmm_sell'))
@pytest.mark.parametrize('fault', (
    'missing_adapter', 'stale_bank', 'missing_context', 'null_fee',
    'boolean_fee', 'string_fee', 'fee_over_cap', 'missing_fee',
))
def test_live_engine_refuses_uncausal_or_unpriced_fee_before_signing(
        tmp_path, route, fault):
    if route == 'launchlab_buy':
        engine, order, rpc, signer, _clock = configured(tmp_path)
    else:
        engine, _old, order, rpc, _clock, _binding = configured_cpmm(tmp_path)
        signer = engine.signer
    decision = json.loads(order.rebuild_request_json)['decision_id']
    prior_signatures = signer.calls
    observed = []

    if fault == 'missing_adapter':
        rpc.get_fee_for_message_receipt = None
    else:
        async def untrusted_fee_receipt(message, *, min_context_slot):
            observed.append((message, min_context_slot))
            receipt = dict(value=5002, context_slot=min_context_slot)
            if fault == 'stale_bank':
                receipt['context_slot'] -= 1
            elif fault == 'missing_context':
                receipt.pop('context_slot')
            elif fault == 'null_fee':
                receipt['value'] = None
            elif fault == 'boolean_fee':
                receipt['value'] = True
            elif fault == 'string_fee':
                receipt['value'] = '5002'
            elif fault == 'fee_over_cap':
                receipt['value'] = order.network_fee_upper_lamports + 1
            elif fault == 'missing_fee':
                receipt.pop('value')
            return receipt
        rpc.get_fee_for_message_receipt = untrusted_fee_receipt

    try:
        with pytest.raises(ValueError, match='causal_message_fee'):
            run(engine.execute(decision, order))
        assert not rpc.send_calls
        assert signer.calls == prior_signatures
        assert engine.journal.get(decision)['reserved_lamports'] == 0
        assert engine.journal.get(decision)['state'] == 'SIMULATED'
        if fault != 'missing_adapter':
            assert observed == [(order.transaction.message, order.source_slot)]
        assert engine.journal.verify_audit()
    finally:
        engine.journal.close()


@pytest.mark.parametrize('route', ('launchlab_buy', 'cpmm_sell'))
def test_live_engine_accepts_source_causal_bounded_fee_receipt(tmp_path, route):
    if route == 'launchlab_buy':
        engine, order, rpc, signer, _clock = configured(tmp_path)
    else:
        engine, _old, order, rpc, _clock, _binding = configured_cpmm(tmp_path)
        signer = engine.signer
    decision = json.loads(order.rebuild_request_json)['decision_id']
    prior_signatures = signer.calls
    try:
        result = run(engine.execute(decision, order))
        assert result['state'] == 'SUBMITTED'
        assert len(rpc.send_calls) == 1 and signer.calls == prior_signatures + 1
        assert engine.journal.verify_audit()
    finally:
        engine.journal.close()
