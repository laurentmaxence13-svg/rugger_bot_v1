"""Corrections O-T1, O-T2, O-T3 of the RUGGER 02 audit of the Token-2022 chain (c85de553), owner GO 11/11."""
import base64
from copy import deepcopy

import pytest

from bot.live.cleanup import build_base_account_cleanup, reconcile_cleanup
from bot.live.route import TOKEN_PROGRAM
from bot.p3 import certification
from bot.p3.token2022 import TOKEN_2022_PROGRAM

from test_live_cleanup_base_account import cleanup_payload, cleanup_request, run
from test_live_cleanup_engine import sold
from test_p3_research_integration import research_snapshot


# ---- O-T1: the pool vaults are exactly 165 bytes, as bot.p3.token2022.decode_vault requires

def _vault_check(accounts, addresses, role):
    result = certification.certify_snapshot(accounts, addresses)
    return next(c for c in result['checks'] if c['name'] == role + '_layout_owner')


def _resize(account, size):
    raw = base64.b64decode(account['data'][0])
    out = dict(account, data=[base64.b64encode((raw + bytes(size))[:size]).decode(), 'base64'])
    return out


@pytest.mark.parametrize('size,status', [(165, 'PASS'), (166, 'UNKNOWN'), (170, 'UNKNOWN'), (178, 'UNKNOWN')])
def test_vault_layout_is_exactly_165_bytes(size, status):
    accounts, addresses, _, _ = research_snapshot(return_accounts=True)
    accounts[addresses['vault_a']] = _resize(accounts[addresses['vault_a']], size)
    check = _vault_check(accounts, addresses, 'vault_a')
    assert check['status'] == status
    if status != 'PASS':
        assert check['reason'] == 'vault_a_layout_outside_pinned_scope'


# ---- O-T3: the SPL cleanup reconciliation checks the token program of the balances

def _prepared():
    return build_base_account_cleanup(**cleanup_request(0))


def test_spl_cleanup_reconciliation_refuses_balances_of_another_token_program():
    prepared = _prepared()
    payload = cleanup_payload(prepared, 'sig-1')
    assert reconcile_cleanup(prepared, 'sig-1', deepcopy(payload))['account_closed'] is True
    named = deepcopy(payload)
    named['meta']['preTokenBalances'][0]['programId'] = TOKEN_PROGRAM
    assert reconcile_cleanup(prepared, 'sig-1', named)['account_closed'] is True
    foreign = deepcopy(payload)
    foreign['meta']['preTokenBalances'][0]['programId'] = TOKEN_2022_PROGRAM
    with pytest.raises(ValueError, match='cleanup_token_balance_entry_invalid'):
        reconcile_cleanup(prepared, 'sig-1', foreign)


# ---- O-T2: the cleanup route is checked before anything is journaled

def test_unknown_cleanup_route_leaves_no_intent_and_no_row(tmp_path):
    engine, buy, _sell, _rpc, signer = sold(tmp_path)
    built = []
    with pytest.raises(ValueError, match='unknown_cleanup_route'):
        run(engine.cleanup('t22-cleanup-x', mint=buy.mint, wallet=buy.user,
                           build=lambda bound: built.append(bound), kind='BASE_ACCOUNT_CLEANUP_TOKEN2022'))
    assert built == [] and engine.journal.cleanup('t22-cleanup-x') is None
    assert engine.journal.get('t22-cleanup-x') is None


def test_built_object_of_another_type_is_refused_before_the_lifecycle(tmp_path):
    """The bound must be journaled before the build (R02 D-a), so a wrong-type object can only be refused after
    the intent: it never reaches reserve, signing or sending, and the intent is settled NOT_SENT."""
    engine, buy, _sell, rpc, signer = sold(tmp_path)
    with pytest.raises(ValueError, match='builder_generated_cleanup_required'):
        run(engine.cleanup('wrong-type', mint=buy.mint, wallet=buy.user, build=lambda bound: object()))
    assert engine.journal.cleanup('wrong-type')['outcome'] == 'NOT_SENT'
    assert engine.journal.get('wrong-type') is None
