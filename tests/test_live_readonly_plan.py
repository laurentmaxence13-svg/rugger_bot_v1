"""Strict, no-send mainnet preflight plan and private evidence tests."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from bot.p3.certification import PROGRAM,_encode
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.readonly_plan import (
    validate_readonly_plan,readonly_plan_sha256,
    MAINNET_GENESIS,PUBLIC_MAINNET_RPC,
)
from bot.live.readonly_report import make_private_report,save_private_report
from test_live_cpmm_exit import fixture_bank,MINT,WALLET,POOL


ORIGINAL=_encode(bytes([90])*32)
SIG=_encode(bytes([66])*64)


def _plan():
    fixture=fixture_bank()
    return dict(schema="rugger-cpmm-readonly-mainnet-plan-v1",
        rpc_endpoint=PUBLIC_MAINNET_RPC,
        expected_genesis_hash=MAINNET_GENESIS,
        send_allowed=False,signature_allowed=False,
        financial_execution_allowed=False,
        operator_confirmed_readonly=True,
        program_pins={
            PROGRAM:dict(expected_deployment_slot=1,
                expected_programdata_sha256='a'*64,
                expected_elf_sha256='b'*64,
                expected_upgrade_authority=None),
            CPMM_PROGRAM:dict(expected_deployment_slot=2,
                expected_programdata_sha256='c'*64,
                expected_elf_sha256='d'*64,
                expected_upgrade_authority=None),
        },
        original_launchlab_pool=ORIGINAL,migrated_cpmm_pool=POOL,
        migration_signature=SIG,mint=MINT,wallet=WALLET,
        decision_id=fixture["decision_id"],
        min_context_slot=1234,amount_in=1000,
        slippage_bps=100,max_slippage_bps=200,
        max_price_impact_bps=500,compute_unit_limit=200000,
        priority_fee_micro_lamports=0,max_priority_fee_lamports=0,
        max_bank_age_ms=5000,max_rpc_requests=18,
        max_transport_elapsed_seconds=40)


def test_complete_mainnet_plan_validates_without_rpc_or_approval():
    p=_plan()
    copy=validate_readonly_plan(p)
    assert copy==p and copy is not p
    assert len(readonly_plan_sha256(p))==64
    assert read_only_example_does_not_pretend_to_certify_balance(p)


def read_only_example_does_not_pretend_to_certify_balance(p):
    assert p["send_allowed"] is False
    assert p["financial_execution_allowed"] is False
    assert p["signature_allowed"] is False
    return True


@pytest.mark.parametrize('key,bad',[
    ('rpc_endpoint','https://api.example.com/token'),
    ('rpc_endpoint','http://api.mainnet.solana.com'),
    ('expected_genesis_hash',POOL),
    ('send_allowed',True),('signature_allowed',True),
    ('financial_execution_allowed',True),
    ('operator_confirmed_readonly',False),
    ('max_rpc_requests',19),('max_rpc_requests',0),
    ('max_rpc_requests',True),
    ('max_transport_elapsed_seconds',61),
    ('min_context_slot',True),
    ('amount_in',0),('amount_in',1.0),
    ('max_bank_age_ms',5001),
    ('slippage_bps',10000),
    ('max_slippage_bps',99999),
    ('compute_unit_limit',1400001),
])
def test_dangerous_plan_or_unauthorized_network_settings_refused(key,bad):
    p=_plan();p[key]=bad
    with pytest.raises(ValueError):
        validate_readonly_plan(p)


def test_missing_or_extra_fields_and_program_pins_fail_closed():
    p=_plan();del p['program_pins'][CPMM_PROGRAM]
    with pytest.raises(ValueError):validate_readonly_plan(p)
    p=_plan();p['private_key']="forbidden"
    with pytest.raises(ValueError):validate_readonly_plan(p)
    p=_plan();p['program_pins'][PROGRAM]['expected_elf_sha256']="unapproved"
    with pytest.raises(ValueError):validate_readonly_plan(p)


def test_private_evidence_is_created_once_without_wallet_private_material(tmp_path):
    p=_plan()
    result=dict(status="REFUSED",reason="simulation_failed")
    report,h=make_private_report(p,result)
    assert report['trade_sent'] is False
    assert report['wallet_armed'] is False
    assert report['live_ready_to_arm'] is False
    assert report['source_wallet_public_key']==WALLET
    path=tmp_path/"read-only-private-evidence.json"
    sha=save_private_report(path,report)
    assert sha==hashlib.sha256(path.read_bytes()).hexdigest()
    assert sha!=h  # Digest of canonical compact JSON differs from indented disk format.
    assert os.stat(path).st_mode & 0o077==0
    assert json.loads(path.read_text())==report
    with pytest.raises(ValueError,match="new_private"):
        save_private_report(path,report)


def test_private_report_rejects_symlink_or_broken_parent(tmp_path):
    p=_plan()
    report,_=make_private_report(p,dict(status="REFUSED"))
    link=tmp_path/"link.json"
    link.symlink_to(tmp_path/"target.json")
    with pytest.raises(ValueError):save_private_report(link,report)
    with pytest.raises(ValueError):
        save_private_report(tmp_path/"not_a_parent"/"report.json",report)
