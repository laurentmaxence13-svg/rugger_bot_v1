"""Raydium current LaunchLab migration ABI (2026-08/09) tested without funds.

Current deployment requires 28 core + 10 permissioned CPMM remaining roles;
the token-program slots are SPL classic then Token-2022, regardless of mint.
Historical 28-account receipts must not be treated as current post-upgrade.
"""
from copy import deepcopy

import pytest

from bot.p3.certification import _decode, _encode, find_program_address, PROGRAM
from bot.p3.quotes import SOL_MINT
from bot.live.cpmm_swap import CPMM_PROGRAM
from bot.live.migration_evidence import (
    CURRENT_MIGRATION_FROM_SLOT, TOKEN_2022_PROGRAM,
    validate_migrate_to_cpswap_transaction)
from test_live_migration_evidence import migration, SIG, MINT, OLD, NEW
from test_live_signed_migration_reference import signed_rpc_migration
from bot.live.solana_signatures import verify_compiled_rpc_signatures


def modern_migration():
    tx = migration()
    tx["slot"] = CURRENT_MIGRATION_FROM_SLOT + 1
    body = tx["transaction"]["message"]
    keys = body["accountKeys"]
    ix = body["instructions"][0]
    role_refs = ix["accounts"]

    def ensure(key, *, writable=False):
        for i, item in enumerate(keys):
            if item["pubkey"] == key:
                if writable:
                    item["writable"] = True
                return i
        keys.append(dict(pubkey=key, signer=False, writable=writable))
        return len(keys) - 1

    # Current fixed slot 23 is the token-2022 program, not a second
    # copy of classic SPL Token. The legacy role label is retained for ABI
    # index compatibility but no longer describes semantic ownership.
    ensure(TOKEN_2022_PROGRAM)
    keys[role_refs[23]]["writable"] = False
    role_refs[23] = ensure(TOKEN_2022_PROGRAM)

    authority = keys[role_refs[16]]["pubkey"]
    permission = find_program_address(
        (b"permission", _decode(authority)), program_id=CPMM_PROGRAM)[0]
    support = [
        find_program_address((b"support_mint", _decode(m)),
                             program_id=CPMM_PROGRAM)[0]
        for m in sorted((MINT, SOL_MINT), key=_decode)]
    filler = [_encode(bytes([x])*32) for x in range(150, 156)]
    remaining = [
        filler[0], filler[1], filler[2], filler[3], filler[4],
        filler[5], permission, _encode(bytes([170])*32),
        support[0], support[1]]
    role_refs.extend(ensure(key, writable=i<5) for i, key in enumerate(remaining))
    assert len(role_refs) == 38
    return tx


def assess(tx):
    return validate_migrate_to_cpswap_transaction(
        tx, signature=tx["transaction"]["signatures"][0],
        mint=MINT, launchlab_pool=OLD, cpmm_pool=NEW,
        observed_at_slot=tx["slot"]+1)


def test_current_38_roles_with_two_support_mint_pdas_and_token_2022_qualify():
    tx = modern_migration()
    before = deepcopy(tx)
    result = assess(tx)
    assert result["status"] == "STRUCTURAL_MIGRATION_RECEIPT", result
    assert result["migration_abi"] == "permissioned_cpmm_2026"
    assert result["current_permissioned_accounts_verified"] is True
    assert len(result["normalized_roles"]) == 38
    assert tx == before
    assert result["live_execution_authorized"] is False


def test_pre_upgrade_28_roles_never_qualify_after_current_deployment():
    tx = migration()
    tx["slot"] = CURRENT_MIGRATION_FROM_SLOT + 2
    result = assess(tx)
    assert result["status"] == "UNKNOWN"
    assert not result["live_execution_authorized"]


@pytest.mark.parametrize("change", [
    "missing_extra", "missing_support0", "missing_support1",
    "writable_support0", "writable_support1",
    "wrong_permission", "wrong_token_program",
    "duplicate_account", "unrecognized_fourty_accounts",
])
def test_current_permissioned_abi_invalid_accounts_fail_closed(change):
    tx = modern_migration()
    ix = tx["transaction"]["message"]["instructions"][0]
    keys = tx["transaction"]["message"]["accountKeys"]
    refs = ix["accounts"]
    if change == "missing_extra":
        refs.pop()
    elif change == "missing_support0":
        refs[36] = refs[0]
    elif change == "missing_support1":
        refs[37] = refs[0]
    elif change == "writable_support0":
        keys[refs[36]]["writable"] = True
    elif change == "writable_support1":
        keys[refs[37]]["writable"] = True
    elif change == "wrong_permission":
        refs[34] = refs[0]
    elif change == "wrong_token_program":
        refs[23] = refs[22]
    elif change == "duplicate_account":
        keys[refs[36]]["pubkey"] = keys[refs[37]]["pubkey"]
    elif change == "unrecognized_fourty_accounts":
        refs.extend((refs[0], refs[1]))
    assert assess(tx)["status"] == "UNKNOWN", change


def test_current_permissioned_rpc_signature_binding_remains_cryptographic():
    tx, signature = signed_rpc_migration(modern_migration())
    assert assess(tx)["status"] == "STRUCTURAL_MIGRATION_RECEIPT"
    assert verify_compiled_rpc_signatures(tx)["cryptographic_signatures_verified"]
    mutated = deepcopy(tx)
    mutated["transaction"]["message"]["recentBlockhash"] = PROGRAM
    with pytest.raises(ValueError):
        verify_compiled_rpc_signatures(mutated)
