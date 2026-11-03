"""Adversarial finalized RPC token metadata, no network or real wallet.

Token balance accountIndex is part of the exact signed transaction's account
array. Invalid *unrelated* entries must not be ignored while settling a
perfectly plausible position token delta.
"""
import json
from copy import deepcopy

import pytest

from bot.live.engine import reconcile_transaction
from test_live_engine import configured, finalized_payload, run
from test_live_cpmm_engine import configured_cpmm


@pytest.mark.parametrize('route', ['launchlab_buy', 'cpmm_sell'])
@pytest.mark.parametrize('damage', [
    'duplicate_foreign_index',
    'out_of_range_index',
    'negative_index',
    'boolean_index',
    'string_index',
    'malformed_record',
    'invalid_pre_index',
    'missing_pre_array',
])
def test_financial_reconciliation_rejects_malformed_token_metadata(
        tmp_path, route, damage):
    if route == 'launchlab_buy':
        engine, order, rpc, _signer, _clock = configured(tmp_path)
    else:
        engine, _old, order, rpc, _clock, _binding = configured_cpmm(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    try:
        result = run(engine.execute(decision, order))
        assert result['state'] == 'SUBMITTED'
        row = engine.journal.get(decision)
        original_reservation = row['reserved_atomic']
        payload = finalized_payload(order, result['signature'])
        if route == 'cpmm_sell':
            payload['slot'] = 1600
        meta = payload['meta']
        keys = payload['transaction']['message']['accountKeys']
        base_index = keys.index(order.base_token_account)
        foreign_index = next(i for i in range(len(keys)) if i != base_index)

        if damage == 'duplicate_foreign_index':
            extra = deepcopy(meta['postTokenBalances'][0])
            extra['accountIndex'] = foreign_index
            meta['postTokenBalances'].extend([extra, deepcopy(extra)])
        elif damage == 'out_of_range_index':
            extra = deepcopy(meta['postTokenBalances'][0])
            extra['accountIndex'] = len(keys)
            meta['postTokenBalances'].append(extra)
        elif damage == 'negative_index':
            extra = deepcopy(meta['postTokenBalances'][0])
            extra['accountIndex'] = -1
            meta['postTokenBalances'].append(extra)
        elif damage == 'boolean_index':
            extra = deepcopy(meta['postTokenBalances'][0])
            extra['accountIndex'] = True
            meta['postTokenBalances'].append(extra)
        elif damage == 'string_index':
            extra = deepcopy(meta['postTokenBalances'][0])
            extra['accountIndex'] = str(foreign_index)
            meta['postTokenBalances'].append(extra)
        elif damage == 'malformed_record':
            meta['postTokenBalances'].append(None)
        elif damage == 'invalid_pre_index':
            extra = deepcopy(meta['postTokenBalances'][0])
            extra['accountIndex'] = -1
            meta['preTokenBalances'].append(extra)
        elif damage == 'missing_pre_array':
            meta.pop('preTokenBalances')

        with pytest.raises(ValueError, match='token_balance'):
            reconcile_transaction(row, payload)
        assert engine.journal.get(decision)['reserved_atomic'] == original_reservation
        assert engine.journal.verify_audit()
        assert len(rpc.send_calls) == 1
    finally:
        engine.journal.close()
