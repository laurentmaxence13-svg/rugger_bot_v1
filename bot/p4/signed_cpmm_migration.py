"""Strict LaunchLab MigrateToCpswap outer signed-instruction proof.

Uses the 2026 published LaunchLab IDL account positions and the canonical
Anchor discriminator sha256("global:migrate_to_cpswap")[:8]. Verifies exact
transaction Ed25519 message via existing source primitive, and matches
LaunchLab old pool, mint, SOL quote and CPMM new pool *inside the signed
outer instruction*. A pool address from an index or string hint is not proof.

This proves transaction *message* authenticity against a provider result,
not independent chain inclusion/finality; obtain separate chain/account
consensus before representing the new market as economically executable.
"""
import hashlib

from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.live.solana_signatures import verify_compiled_rpc_signatures
from bot.p3.certification import PROGRAM,_encode
from bot.p3.platform_admin_history import _b58_bytes
from bot.p3.quotes import SOL_MINT
from bot.p4.cpmm_quote_adapter import CPMM_MAINNET
from bot.p4.live_like_paper_ledger import migration_proof

DISC=hashlib.sha256(b"global:migrate_to_cpswap").digest()[:8]
# Helius/Raydium LaunchLab 2026 instruction account list, fixed prefix:
# payer, base_mint, quote_mint, platform_config, cpswap_program,
# cpswap_pool, ... authority, pool_state, ...
ACCOUNT_POSITIONS=dict(payer=0,mint=1,quote_mint=2,
                       cpmm_program=4,cpmm_pool=5,launchlab_pool=17)


def signed_cpswap_mapping(*,transaction,expected_mint,expected_curve_pool,
                          expected_cpmm_pool):
    if (type(transaction) is not dict
            or type(transaction.get("slot")) is not int
            or transaction["slot"]<=0
            or type(transaction.get("meta")) is not dict
            or transaction["meta"].get("err") is not None):
        raise ValueError("successful_source_transaction_required")
    exact=verify_compiled_rpc_signatures(transaction)
    if exact.get("cryptographic_signatures_verified") is not True:
        raise ValueError("signed_launchlab_migration_message_required")
    normalized=normalized_compiled_transaction(transaction)
    msg=normalized["transaction"]["message"]
    keys=msg["accountKeys"]
    outer=transaction["transaction"]["message"]["instructions"]
    candidates=[]
    for instruction in outer:
        if type(instruction) is not dict:
            continue
        program_index=instruction.get("programIdIndex")
        accounts=instruction.get("accounts")
        if (type(program_index) is not int or not 0<=program_index<len(keys)
                or keys[program_index]["pubkey"]!=PROGRAM
                or type(accounts) is not list or len(accounts)<28):
            continue
        encoded=instruction.get("data")
        if type(encoded) is not str:
            continue
        raw=_b58_bytes(encoded)
        if _encode(raw)!=encoded or raw[:8]!=DISC:
            continue
        if any(type(index) is not int or not 0<=index<len(keys)
               for index in accounts):
            raise ValueError("migration_compiled_account_indices_invalid")
        public={name:keys[accounts[position]]["pubkey"]
                for name,position in ACCOUNT_POSITIONS.items()}
        signer=keys[accounts[ACCOUNT_POSITIONS["payer"]]]["signer"]
        writable=keys[accounts[ACCOUNT_POSITIONS["cpmm_pool"]]]["writable"]
        if (not signer or not writable
                or public["mint"]!=expected_mint
                or public["quote_mint"]!=SOL_MINT
                or public["launchlab_pool"]!=expected_curve_pool
                or public["cpmm_program"]!=CPMM_MAINNET
                or public["cpmm_pool"]!=expected_cpmm_pool):
            raise ValueError("signed_migration_pool_identity_disagreement")
        candidates.append(public)
    if len(candidates)!=1:
        raise ValueError("exactly_one_signed_outer_launchlab_migration_required")
    proof=dict(mint=expected_mint,from_pool=expected_curve_pool,
        to_pool=expected_cpmm_pool,source_slot=transaction["slot"],
        signed_transaction_verified=True,
        transaction_sha256=exact["exact_message_sha256"])
    migration_proof(proof,mint=expected_mint,from_pool=expected_curve_pool,
                    to_pool=expected_cpmm_pool,slot=transaction["slot"])
    return dict(proof=proof,
        source="onchain_finalized_receipt_suppled_compiled_outer_instruction",
        anchor_migrate_to_cpswap_discriminator=DISC.hex(),
        program_id=PROGRAM,cpmm_program_id=CPMM_MAINNET,
        message_ed25519_verified=True,
        independently_verified_chain_inclusion=False,
        cpmm_live_vault_accounts_not_yet_queried=True,
        economic_cpmm_exit_quote_not_yet_qualified=True,
        financial_order_submitted=False)
