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
from bot.scanner.backfill import ProgramBackfill
from bot.scanner.supervision import (
    ScannerHealth, _raise_paper_failures, _await_paper_cleanup, _stop_supervised_tasks,
)


# Protection du RPC Helius. Une porte adaptative ralentit encore après un 429.
RPC_DELAY_SECONDS = 1.10


async def run(rpc_gate=None, db_path=None, *, health=None):
    health = health or ScannerHealth(require_observations=True)
    asyncio.current_task().scanner_health = health
    tasks, failures = [], []
    rpc = backfill = None
    stop_reason = 'stream_ended'
    try:
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
        rpc = SolanaRPC(settings.rpc_url)
        await rpc.__aenter__()
        async def observed_rpc(method, params):
            try:
                result = await rpc_json(rpc, settings.rpc_url, gate, method, params, max_attempts=1)
            except BaseException:
                health.observe_rpc(False)
                raise
            health.observe_rpc(type(result) in (dict, list))
            return result

        async def fetch_transaction(signature):
            # One provider round per durable attempt: at most two HTTP calls.
            # The queue owns the retry budget, including process restarts.
            return await observed_rpc(
                'getTransaction',
                [signature, {'commitment': 'confirmed', 'encoding': 'jsonParsed',
                             'maxSupportedTransactionVersion': 1}],
            )

        async def fetch_page(program_id, options):
            # Same Helius gate and fallback as transaction recovery; bounded
            # to one provider round per page (at most two HTTP requests).
            return await observed_rpc('getSignaturesForAddress', [program_id, options])

        backfill = ProgramBackfill(store, settings.raydium_launchpad_program_id, fetch_page)
        async def publish_state(message):
            try:
                health.observe_websocket(message['state'])
                await backfill.on_state(message)
            except BaseException as error:
                health.fail('scanner live state publication', error)
                raise

        def transport_failed(error):
            health.fail('scanner WebSocket failure',
                        None if isinstance(error, GeneratorExit) else error)
            health.observe_websocket('disconnected')

        tasks.append(health.start_task(backfill.run(), 'scanner-backfill'))
        async def observed_notifications():
            source = stream_program_logs(settings.ws_url, settings.raydium_launchpad_program_id,
                                         on_state=publish_state, on_failure=transport_failed)
            try:
                async for notification in source:
                    health.observe_websocket('notification')
                    yield notification
            finally:
                close = getattr(source, 'aclose', None)
                if close is not None:
                    await close()

        tasks.append(health.start_task(recover_transactions(
            observed_notifications(), store, fetch_transaction,
            health=health,
        ), 'scanner-recovery'))
        watcher = asyncio.create_task(health.failure_event.wait(), name='scanner-failure-watch')
        tasks.append(watcher)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in tasks:
            if task in done:
                await task
        health.append_errors(failures)
        if not failures and health.failures:
            failures.append(health.failures[0])  # An unexpected child cancellation remains cancellation.
    except BaseException as error:
        stop_reason = type(error).__name__
        failures.append(('scanner', error))
        health.fail('scanner', error)
    finally:
        if failures:
            stop_reason = type(failures[0][1]).__name__
        health.fail('scanner stopping')  # No await, no SQLite, no reset.
        async def cleanup():
            try:
                observed = [error for _, error in failures]
                await _stop_supervised_tasks(tasks, observed=observed)
            except BaseException as error:
                failures.append(('scanner child cleanup', error))
            if backfill is not None:
                try:
                    # Publish after children so their interruption cannot overwrite
                    # the terminal cause. Entry denial already holds in memory.
                    await backfill.on_state({'state': 'disconnected', 'reason': stop_reason})
                except BaseException as error:
                    failures.append(('scanner state publication', error))
            if rpc is not None:
                try:
                    await rpc.__aexit__(None, None, None)
                except BaseException as error:
                    failures.append(('scanner RPC close', error))
            health.append_errors(failures)
        await _await_paper_cleanup(cleanup(), failures)
    _raise_paper_failures(failures)


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nBot arrete.")


if __name__ == "__main__":
    main()
