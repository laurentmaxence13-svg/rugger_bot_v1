import asyncio

from bot.analyser.multi_creator_research_engine import (
    AdaptiveRPCGate,
    ensure_schema,
    rpc_json,
)
from bot.config import get_settings
from bot.database.db import Database
from bot.solana.rpc import SolanaRPC
from bot.solana.websocket import stream_program_logs
from bot.scanner.tx_recovery import TransactionRecovery, recover_transactions


# Protection du RPC Helius. Une porte adaptative ralentit encore après un 429.
RPC_DELAY_SECONDS = 1.10


async def run(rpc_gate=None, db_path=None):
    settings = get_settings()
    db = Database(db_path or settings.db_path)
    # Keep live scanner transactions in the same research cache used by the
    # historical dataset builder.  Without this bridge, paper_prices from a
    # live launch could never be matched to a research event later.
    ensure_schema(db.path)

    print("=" * 62)
    print("RUGGER BOT V1 - OBSERVATION UNIQUEMENT / AUCUN TRADE REEL")
    print("Protocole V1 : Raydium Launchpad / LaunchLab")
    print(f"Base SQLite  : {settings.db_path}")
    print("=" * 62)

    store = TransactionRecovery(db.path)
    gate = rpc_gate or AdaptiveRPCGate(RPC_DELAY_SECONDS)
    async with SolanaRPC(settings.rpc_url) as rpc:
        async def fetch_transaction(signature):
            # One provider round per durable attempt: at most two HTTP calls.
            # The queue owns the retry budget, including process restarts.
            return await rpc_json(
                rpc, settings.rpc_url, gate, 'getTransaction',
                [signature, {'commitment': 'confirmed', 'encoding': 'jsonParsed',
                             'maxSupportedTransactionVersion': 1}],
                max_attempts=1,
            )

        await recover_transactions(
            stream_program_logs(settings.ws_url, settings.raydium_launchpad_program_id),
            store, fetch_transaction,
        )


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nBot arrete.")


if __name__ == "__main__":
    main()
