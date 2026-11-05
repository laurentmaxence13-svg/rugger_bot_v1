"""Preflight diagnostics are useful but must never reveal remote error bytes."""
import pytest

from bot.live.readonly_diagnostics import safe_refusal_reason
from bot.live.rpc import RpcError


@pytest.mark.parametrize('message',[
    'CPMM_block_time_missing_or_untrusted',
    'CPMM_fee_receipt_noncausal_unknown_or_exceeds_cap',
    'program_code_or_upgrade_pin_mismatch',
    'cpmm_wallet_cannot_fund_rent_and_fee',
    'historical_transaction_Ed25519_signature_invalid',
])
def test_known_nonparametric_internal_errors_keep_specific_reason(message):
    assert safe_refusal_reason(ValueError(message))==message


@pytest.mark.parametrize('leak',[
    'https://api.example?api_key=private-secret',
    'RPC_error: lamports for wallet abc000Secret',
    'program_code_or_upgrade_pin_mismatch: secret-address',
    'CPMM_bank_or_block_time_stale 123456789',
    'unauthorized wallet PRIVATE_KEY',
])
def test_unknown_remote_data_is_never_reflected_to_report(leak):
    assert safe_refusal_reason(ValueError(leak))=='ValueError'
    assert safe_refusal_reason(RpcError(leak))=='RpcError'
    assert safe_refusal_reason(RuntimeError(leak))=='RuntimeError'


def test_nonruntime_exception_cannot_leak_error_text():
    assert safe_refusal_reason(OSError('private-http-target'))=='UNCLASSIFIED_FAILURE'
