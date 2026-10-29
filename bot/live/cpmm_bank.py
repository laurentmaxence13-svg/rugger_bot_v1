"""Read-only CPMM bank acquisition; builds a non-signed SELL, never sends."""
from bot.p3.certification import _decode
from bot.p3.quotes import SOL_MINT
from .cpmm_exit import (
    POOL_ACCOUNT_SIZE, POOL_DISCRIMINATOR, _account, _pool, build_cpmm_exit,
)
from .route import associated_token_address, ephemeral_wsol_address


async def prepare_cpmm_sell_from_rpc(rpc, *, pool_address, mint, wallet,
        decision_id, min_context_slot, observed_block_time_seconds, clock_ms,
        expected_genesis_hash, expected_endpoint_sha256,
        amount_in, slippage_bps, max_slippage_bps, max_price_impact_bps,
        compute_unit_limit=200000, priority_fee_micro_lamports=0,
        max_priority_fee_lamports=0, max_bank_age_ms=5000):
    """Five bounded read-only RPC requests; no signer, wallet key or trade.

    A caller must independently verify migration and block-time provenance.
    The transport must enforce its own request and elapsed-time budgets.
    """
    for addr in (pool_address,mint,wallet,expected_genesis_hash):
        _decode(addr)
    if (type(expected_endpoint_sha256) is not str
            or len(expected_endpoint_sha256)!=64
            or any(c not in "0123456789abcdef" for c in expected_endpoint_sha256)
            or type(min_context_slot) is not int or min_context_slot<=0
            or type(max_bank_age_ms) is not int or not 0<max_bank_age_ms<=5000
            or type(observed_block_time_seconds) is not int
            or observed_block_time_seconds<=0
            or not callable(clock_ms)):
        raise ValueError("explicit_RPC_bank_clock_limits_required")
    start=clock_ms()
    if type(start) is not int or start<=0:
        raise ValueError("exact_local_clock_required")
    if getattr(rpc,"endpoint_sha256",None)!=expected_endpoint_sha256:
        raise ValueError("RPC_endpoint_not_pinned")
    if await rpc.genesis_hash()!=expected_genesis_hash:
        raise ValueError("RPC_genesis_not_pinned")
    first=await rpc.get_multiple_accounts([pool_address],
        min_context_slot=min_context_slot)
    slot_a=first["context"]["slot"]
    if type(slot_a) is not int or slot_a<min_context_slot:
        raise ValueError("first_bank_slot_invalid")
    raw_pool=first["value"][0]
    pool=_pool(_account(raw_pool,name="pool",size=POOL_ACCOUNT_SIZE,
                        discriminator=POOL_DISCRIMINATOR))
    if {pool["token_0_mint"],pool["token_1_mint"]}!={mint,SOL_MINT}:
        raise ValueError("CPMM_pool_pair_invalid")
    i=0 if pool["token_0_mint"]==mint else 1
    wsol,_=ephemeral_wsol_address(wallet,decision_id)
    addresses=(pool_address,pool["amm_config"],pool["observation_key"],
        pool["token_"+str(i)+"_vault"],pool["token_"+str(1-i)+"_vault"],
        mint,SOL_MINT,wallet,associated_token_address(wallet,mint),wsol)
    if len(set(addresses))!=10:
        raise ValueError("CPMM_duplicate_bank_accounts")
    joint=await rpc.get_multiple_accounts(list(addresses),
        min_context_slot=slot_a)
    slot_b=joint["context"]["slot"]
    if type(slot_b) is not int or slot_b<slot_a:
        raise ValueError("joint_bank_slot_invalid")
    values=joint["value"]
    if type(values) is not list or len(values)!=10:
        raise ValueError("CPMM_incomplete_joint_bank")
    accounts=dict(zip(addresses,values,strict=True))
    if accounts[pool_address]!=raw_pool:
        raise ValueError("CPMM_pool_changed_between_reads")
    received=clock_ms()
    if type(received) is not int or not 0<=received-start<=max_bank_age_ms:
        raise ValueError("CPMM_bank_acquisition_stale")
    latest=await rpc.get_latest_blockhash()
    if (type(latest) is not dict or
            type(latest.get("context_slot")) is not int or
            latest["context_slot"]<slot_b):
        raise ValueError("CPMM_blockhash_bank_precedes_account_bank")
    rent=await rpc.rent_exemption(165)
    decision=clock_ms()
    if (type(decision) is not int or
            not 0<=decision-start<=max_bank_age_ms or
            not 0<=decision-received<=max_bank_age_ms or
            abs(decision//1000-observed_block_time_seconds)>120):
        raise ValueError("CPMM_bank_or_block_time_stale")
    order=build_cpmm_exit(
        accounts=accounts,pool_address=pool_address,mint=mint,wallet=wallet,
        context_slot=slot_b,available_at_ms=received,
        decision_at_ms=decision,
        observed_block_time_seconds=observed_block_time_seconds,
        amount_in=amount_in,slippage_bps=slippage_bps,
        max_slippage_bps=max_slippage_bps,
        max_price_impact_bps=max_price_impact_bps,
        recent_blockhash=latest["blockhash"],
        last_valid_block_height=latest["last_valid_block_height"],
        rent_exempt_lamports=rent,decision_id=decision_id,
        compute_unit_limit=compute_unit_limit,
        priority_fee_micro_lamports=priority_fee_micro_lamports,
        max_priority_fee_lamports=max_priority_fee_lamports)
    return dict(order=order,source_bank_slot=slot_b,
        initial_pool_bank_slot=slot_a,blockhash_bank_slot=latest["context_slot"],
        read_only_RPC_calls=5,bank_received_at_ms=received,
        decision_at_ms=decision,
        observed_block_time_independently_verified=False,
        onchain_program_pin_verified_by_this_module=False,
        migration_provenance_verified_by_this_module=False,
        transaction_sent=False,live_execution_authorized=False)
