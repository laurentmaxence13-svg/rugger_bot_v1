"""Economic evidence reporting must not confuse fixtures or models with P&L."""
from copy import deepcopy
from pathlib import Path
import importlib.util

import pytest

spec = importlib.util.spec_from_file_location(
    'profitability_audit', Path(__file__).resolve().parents[1] / 'tools' / 'profitability_audit.py')
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)
audit = audit_module.audit


def fixtures():
    positions = {
        'schema': 'p3-archived-position-size-study-v1',
        'initial_bank_rows': [
            {'entry_lamports': '1000000000', 'immediate_sell_net_of_curve_lamports': '888306249'},
            {'entry_lamports': '100000000', 'immediate_sell_net_of_curve_lamports': '97515624'},
        ],
        'strict_economic_cycles': 0, 'net_market_pnl_sol': None,
        'admissible_model_cases': 32, 'distinct_mints': 4, 'capture_sessions': 2,
    }
    economic = {'schema': 'rugger-atomic-market-evaluation-v1', 'qualified_economic_cycles': 0}
    ab = {'schema': 'master-v2-fixture-measurements-v1', 'data_kind': 'synthetic',
          'market_advantage_verified': False, 'promotion_allowed': False}
    p3_009 = {'schema': 'p3-active-cohort-result-v1', 'requests_used': 1, 'provider_quotes': 0,
              'discovery_universe_known': False}
    return positions, economic, ab, p3_009


def test_model_losses_arithmetic_exact_and_never_prove_market_profit():
    src = fixtures();before = deepcopy(src)
    result = audit(*src)
    assert result['economic_conclusion'] == 'NOT_DEMONSTRATED'
    assert result['market_net_pnl_sol'] is None
    assert result['model']['negative_initial_rows'] == 2
    assert result['model']['minimum_conditional_roundtrip_net_sol'] == '-0.111693751'
    assert result['model']['maximum_conditional_roundtrip_net_sol'] == '-0.002484376'
    assert result['real_trading_authorized'] is False
    assert src == before


def test_010_manifest_presence_alone_never_proves_profit():
    result = audit(*fixtures(), p3_010_evidence_present=True)
    assert 'P3_010_EVIDENCE_NOT_PUBLISHED' not in result['blockers']
    assert result['economic_conclusion'] == 'NOT_DEMONSTRATED'
    assert not result['master_market_advantage_verified']


def test_positive_synthetic_claim_does_not_promote():
    src = list(fixtures());src[2]['market_advantage_verified'] = True
    src[2]['promotion_allowed'] = True
    result = audit(*src)
    assert result['economic_conclusion'] == 'NOT_DEMONSTRATED'
    assert result['master_market_advantage_verified'] is False
    assert result['real_trading_authorized'] is False


def test_mismatched_cycles_rejected():
    src = list(fixtures());src[1]['qualified_economic_cycles'] = 1
    with pytest.raises(ValueError, match='disagrees'):
        audit(*src)


def test_noncanonical_money_input_rejected():
    src = list(fixtures());src[0]['initial_bank_rows'][0]['entry_lamports'] = '01000000000'
    with pytest.raises(ValueError, match='canonical'):
        audit(*src)


def test_unverified_pnl_claim_cannot_become_proof():
    src = list(fixtures());src[0]['net_market_pnl_sol'] = '99.0'
    result = audit(*src)
    assert result['market_net_pnl_sol'] is None
    assert 'MARKET_NET_PNL_UNKNOWN' in result['blockers']


def test_provisional_market_evidence_still_requires_independent_review():
    src = list(fixtures());src[0]['strict_economic_cycles'] = 2
    src[0]['net_market_pnl_sol'] = '0.125'
    src[1]['qualified_economic_cycles'] = 2
    src[2]['data_kind'] = 'market_observation';src[2]['market_advantage_verified'] = True
    result = audit(*src, p3_010_evidence_present=True)
    assert result['economic_conclusion'] == 'REQUIRES_INDEPENDENT_REVIEW'
    assert result['real_trading_authorized'] is False
    assert result['market_net_pnl_sol'] == '0.125'
