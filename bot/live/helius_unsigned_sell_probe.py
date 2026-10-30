"""Mainnet Helius UNSIGNED CPMM SELL hypothesis for an unrelated public ATA.

This verifies only a hypothetical sell's on-chain simulation, NOT any owner
authorization, trade fill, executable profitability, or go-live readiness.
Zero signing capability or send method exists in the strict Helius transport.
"""
import asyncio
import hashlib
import json
import sys
import time

from bot.live.helius_readonly_rpc import HeliusReadOnlyRpc, HELIUS_RPC_ID
from bot.live.public_holder_probe import find_public_ata_holder, MINT, MIGRATION_SLOT
from bot.live.public_cpmm_pool_probe import MIGRATED_POOLS
from bot.live.cpmm_bank import prepare_cpmm_sell_from_rpc
from bot.live.unsigned_preflight import check_unsigned_order
from bot.live.rpc import SolanaRpc
from bot.live.readonly_plan import MAINNET_GENESIS

POOL = "DeUJRynHqYre7qDvsv2X7ohH4nCm32xB8AHJ8hs4m4Ck"
assert any(p[0] == POOL and p[1] == MINT
           for p in MIGRATED_POOLS)

MAX_HYPOTHETICAL_INPUT_ATOMIC = 100_000_000_000


def bounded_public_hypothesis(public_amount):
    """At most half the public ATA balance; never source from user credentials."""
    if type(public_amount) is not int or public_amount < 2_000_000:
        raise ValueError("public_holder_inventory_too_small")
    amount = min(MAX_HYPOTHETICAL_INPUT_ATOMIC, public_amount // 2)
    if amount <= 0 or amount >= public_amount:
        raise ValueError("unbounded_public_sell_hypothesis")
    return amount


class HeliusAsyncReadOnlyTransport:
    """Adapter; the inner RPC still rejects sendTransaction and signed payloads."""
    endpoint = HELIUS_RPC_ID
    def __init__(self, rpc):
        if type(rpc) is not HeliusReadOnlyRpc or not rpc._preflight:
            raise ValueError("explicit_unsigned_helius_preflight_required")
        self.rpc = rpc

    async def __call__(self, method, params):
        return self.rpc(method, params)


async def simulate_public_cpmm_sell():
    # Separate limited discovery and simulation budgets, no env files loaded.
    holder_rpc = HeliusReadOnlyRpc.from_environment(max_calls=4)
    holder = find_public_ata_holder(holder_rpc)
    if holder.get("status") != "PUBLIC_CANDIDATE_WALLET_AND_ATA_IDENTIFIED":
        return dict(status="REFUSED", phase="public_inventory",
                    reason=holder.get("status","unknown"), actual_sell_simulated=False,
                    financial_order_submitted=False, live_ready_to_arm=False)
    amount = bounded_public_hypothesis(holder["public_token_amount_atomic"])
    bank_rpc = HeliusReadOnlyRpc.from_environment(
        max_calls=10, allow_unsigned_preflight=True)
    solana = SolanaRpc(HeliusAsyncReadOnlyTransport(bank_rpc))
    clock_ms = lambda: time.time_ns()//1_000_000
    expected_endpoint_hash = hashlib.sha256(HELIUS_RPC_ID.encode()).hexdigest()
    bank = await prepare_cpmm_sell_from_rpc(
        solana, pool_address=POOL, mint=MINT,
        wallet=holder["wallet"], decision_id="public-unsigned-cpmm-sell-test-v1",
        min_context_slot=MIGRATION_SLOT+1, clock_ms=clock_ms,
        expected_genesis_hash=MAINNET_GENESIS,
        expected_endpoint_sha256=expected_endpoint_hash,
        amount_in=amount, slippage_bps=100, max_slippage_bps=200,
        max_price_impact_bps=500, compute_unit_limit=250000,
        priority_fee_micro_lamports=0, max_priority_fee_lamports=0,
        max_bank_age_ms=5000)
    order = bank["order"]
    simulated = await check_unsigned_order(
        solana,order,expected_genesis_hash=MAINNET_GENESIS,
        expected_endpoint_sha256=expected_endpoint_hash,
        now_ms=clock_ms(),max_bank_age_ms=5000,clock_ms=clock_ms)
    return dict(schema="rugger-helius-unsigned-public-cpmm-v1",
        status=("UNSIGNED_SELL_SIMULATED" if
                simulated.get("result")=="SIMULATION_SUCCEEDED_UNSENT"
                else "REFUSED"),
        phase="simulation", reason=simulated.get("reason"),
        mint=MINT,cpmm_pool=POOL,public_wallet=holder["wallet"],
        public_wallet_owned_by_user=False,
        public_token_ata=holder["ata"],
        amount_in_atomic=amount,expected_output_lamports=order.expected_output,
        minimum_out_lamports=order.minimum_out,
        source_bank_slot=order.source_slot,
        simulation_slot=simulated.get("simulation_slot"),
        simulation_compute_units=simulated.get("simulation_units"),
        price_impact_bps=order.price_impact_bps,
        network_fee_upper_lamports=order.network_fee_upper_lamports,
        expected_message_sha256=simulated.get("message_sha256"),
        parsed_simulation_sha256=(simulated.get("parsed_RPC_simulation_sha256")
                if simulated.get("result")=="SIMULATION_SUCCEEDED_UNSENT" else None),
        rpc_calls_used=holder_rpc.count+bank_rpc.count,
        signatures_are_all_zero=True,financial_order_submitted=False,
        route_executed=False,live_ready_to_arm=False,
        economic_edge_validated=False,
        source_program_operator_approved=False)


def main():
    try:
        report=asyncio.run(simulate_public_cpmm_sell())
    except Exception as exc:
        # Catch errors without displaying key-bearing HTTP URLs or inputs.
        report=dict(status="REFUSED",phase="read_only_preflight",
            diagnostic_type=type(exc).__name__,
            financial_order_submitted=False,live_ready_to_arm=False,
            economic_edge_validated=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report.get("status")=="UNSIGNED_SELL_SIMULATED" else 2


if __name__=="__main__":
    sys.exit(main())
