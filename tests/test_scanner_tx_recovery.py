"""Recovery scenarios on synthetic SQLite files, with no live RPC/WS."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from bot.analyser.multi_creator_research_engine import ensure_schema
from bot.database.db import Database
from bot.scanner.tx_recovery import RecoveryQueueFull, TransactionRecovery, recover_transactions


EVENT = {'signature': 'synthetic-signature', 'slot': 1,
         'received_at': datetime.fromtimestamp(101, timezone.utc)}
TX = {'blockTime': 100, 'meta': {'err': None}, 'transaction': {'message': {
    'instructions': [{'programId': 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj',
                      'accounts': ['payer', 'creator', 'a', 'b', 'c', 'pool', 'mint'],
                      'parsed': {'type': 'initialize_v2'}}]}}}


async def notifications(*events):
    for event in events:
        yield event


class ScannerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'synthetic.db'
        Database(self.path)
        ensure_schema(self.path)
        self.store = TransactionRecovery(self.path, retry_base=0)

    def read(self, sql):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute(sql).fetchall()

    async def run_recovery(self, fetch, events=None, clock=lambda: 1000):
        await asyncio.wait_for(recover_transactions(
            notifications(EVENT) if events is None else events,
            self.store, fetch, clock=clock, idle_seconds=.001,
        ), timeout=3)

    def assert_done_once(self, attempts):
        self.assertEqual(self.read('SELECT state,attempts FROM scanner_tx_recovery'), [('done', attempts)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM launch_candidates'), [(1,)])
        self.assertEqual(self.read('SELECT fetched_ok FROM research_tx_cache'), [(1,)])
        self.assertEqual(self.read('SELECT slot,detected_at FROM launch_candidates'),
                         [(1, EVENT['received_at'].isoformat())])

    async def test_null_then_valid_transaction(self):
        fetch = AsyncMock(side_effect=[None, TX])
        await self.run_recovery(fetch)
        self.assertEqual(fetch.await_count, 2)
        self.assert_done_once(2)

    async def test_temporary_exception_then_success(self):
        fetch = AsyncMock(side_effect=[TimeoutError(), TX])
        await self.run_recovery(fetch)
        self.assert_done_once(2)

    async def test_duplicate_notification_processed_once(self):
        fetch = AsyncMock(return_value=TX)
        await self.run_recovery(fetch, notifications(EVENT, EVENT, EVENT))
        fetch.assert_awaited_once_with(EVENT['signature'])
        self.assert_done_once(1)

    async def test_retry_runs_while_stream_is_quiet(self):
        second_try = asyncio.Event()
        count = 0

        async def fetch(_signature):
            nonlocal count
            count += 1
            if count == 1:
                return None
            second_try.set()
            return TX

        async def quiet_stream():
            yield EVENT
            await second_try.wait()  # no new notification can trigger the retry

        await self.run_recovery(fetch, quiet_stream())
        self.assert_done_once(2)

    async def test_exhausted_budget_is_persisted_and_not_reset_by_duplicates(self):
        self.store = TransactionRecovery(self.path, max_attempts=3, retry_base=0)
        fetch = AsyncMock(side_effect=TimeoutError)
        await self.run_recovery(fetch)
        self.assertEqual(fetch.await_count, 3)
        self.assertEqual(self.read('SELECT state,attempts,last_error FROM scanner_tx_recovery'),
                         [('exhausted', 3, 'TimeoutError')])
        await self.run_recovery(fetch, notifications(EVENT, EVENT))
        self.assertEqual(fetch.await_count, 3)
        self.assertEqual(self.read('SELECT COUNT(*) FROM launch_candidates'), [(0,)])

    async def test_restart_recovers_pending_work_without_notifications(self):
        self.store.enqueue(EVENT, 100)
        job = self.store.claim_due(100)  # interruption after reserving attempt 1
        self.assertEqual(job['attempts'], 1)
        self.store = TransactionRecovery(self.path, retry_base=0)
        fetch = AsyncMock(return_value=TX)
        await self.run_recovery(fetch, notifications(), clock=lambda: 1000)
        self.assert_done_once(2)

    async def test_restart_does_not_reprocess_completed_transaction(self):
        await self.run_recovery(AsyncMock(return_value=TX))
        self.store = TransactionRecovery(self.path)
        fetch = AsyncMock()
        await self.run_recovery(fetch, notifications(EVENT))
        fetch.assert_not_awaited()
        self.assert_done_once(1)

    async def test_interrupted_final_attempt_becomes_exhausted(self):
        self.store = TransactionRecovery(self.path, max_attempts=1)
        self.store.enqueue(EVENT, 100)
        self.store.claim_due(100)
        fetch = AsyncMock()
        await self.run_recovery(fetch, notifications())
        fetch.assert_not_awaited()
        self.assertEqual(self.read('SELECT state,last_error FROM scanner_tx_recovery'),
                         [('exhausted', 'InterruptedAttemptBudget')])

    async def test_queue_capacity_fails_explicitly_without_deleting_pending(self):
        self.store = TransactionRecovery(self.path, max_pending=1)
        self.assertTrue(self.store.enqueue(EVENT, 100))
        self.assertFalse(self.store.enqueue(EVENT, 100))
        with self.assertRaises(RecoveryQueueFull):
            self.store.enqueue({**EVENT, 'signature': 'another-signature'}, 100)
        self.assertEqual(self.read('SELECT signature,state FROM scanner_tx_recovery'),
                         [(EVENT['signature'], 'pending')])

    async def test_nonlaunch_transaction_is_completed_without_candidate(self):
        tx = {'meta': {'err': None}, 'transaction': {'message': {'instructions': []}}}
        fetch = AsyncMock(return_value=tx)
        await self.run_recovery(fetch, notifications(EVENT, EVENT))
        fetch.assert_awaited_once()
        self.assertEqual(self.read('SELECT state FROM scanner_tx_recovery'), [('done',)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM launch_candidates'), [(0,)])

    async def test_failure_after_cache_write_rolls_back_entire_completion(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON launch_candidates "
                        "BEGIN SELECT RAISE(ABORT, 'injected'); END")
        self.store = TransactionRecovery(self.path, max_attempts=1, retry_base=0)
        await self.run_recovery(AsyncMock(return_value=TX))
        self.assertEqual(self.read('SELECT COUNT(*) FROM research_tx_cache'), [(0,)])
        self.assertEqual(self.read('SELECT COUNT(*) FROM launch_candidates'), [(0,)])
        self.assertEqual(self.read('SELECT state FROM scanner_tx_recovery'), [('exhausted',)])

    async def test_cancellation_retains_recoverable_attempt(self):
        started = asyncio.Event()

        async def stuck(_signature):
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(recover_transactions(notifications(EVENT), self.store, stuck,
                                                       clock=lambda: 100, idle_seconds=.001))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.read('SELECT state,attempts FROM scanner_tx_recovery'), [('pending', 1)])
        await self.run_recovery(AsyncMock(return_value=TX), notifications())
        self.assert_done_once(2)

    async def test_attempt_timeout_is_bounded(self):
        self.store = TransactionRecovery(self.path, max_attempts=2, retry_base=0)

        async def stuck(_signature):
            await asyncio.Event().wait()

        await asyncio.wait_for(recover_transactions(notifications(EVENT), self.store, stuck,
                                                    clock=lambda: 1000, idle_seconds=.001,
                                                    attempt_timeout=.01), timeout=1)
        self.assertEqual(self.read('SELECT state,attempts FROM scanner_tx_recovery'), [('exhausted', 2)])

    async def test_backoff_and_lease_prevent_immediate_retry(self):
        self.store = TransactionRecovery(self.path, retry_base=2)
        self.store.enqueue(EVENT, 100)
        first = self.store.claim_due(100)
        self.assertIsNone(self.store.claim_due(101))
        self.store.fail(first, TimeoutError(), 101)
        self.assertIsNone(self.store.claim_due(102))
        self.assertEqual(self.store.claim_due(103)['attempts'], 2)

    async def test_parser_failure_is_not_marked_complete(self):
        self.store = TransactionRecovery(self.path, max_attempts=2, retry_base=0)
        from bot.scanner.tx_recovery import parse_launch_candidate
        with patch('bot.scanner.tx_recovery.parse_launch_candidate',
                   side_effect=[ValueError('temporary'), parse_launch_candidate(TX, EVENT['received_at'])]):
            await self.run_recovery(AsyncMock(return_value=TX))
        self.assert_done_once(2)

    async def test_malformed_transaction_retries_instead_of_completing(self):
        fetch = AsyncMock(side_effect=[{}, TX])
        await self.run_recovery(fetch)
        self.assert_done_once(2)

    async def test_main_wires_durable_recovery_and_one_rpc_round(self):
        from bot import main as scanner
        settings = SimpleNamespace(db_path=self.path, rpc_url='https://rpc.invalid',
                                   ws_url='wss://ws.invalid', raydium_launchpad_program_id='synthetic')
        rpc = AsyncMock()
        fetch = AsyncMock(side_effect=[None, TX])
        with patch.object(scanner, 'get_settings', return_value=settings), \
                patch.object(scanner, 'SolanaRPC', return_value=rpc), \
                patch.object(scanner, 'stream_program_logs', return_value=notifications(EVENT, EVENT)), \
                patch.object(scanner, 'TransactionRecovery', return_value=self.store), \
                patch.object(scanner, 'rpc_json', fetch):
            await asyncio.wait_for(scanner.run(db_path=self.path), timeout=3)
        self.assert_done_once(2)
        self.assertEqual(fetch.await_count, 2)
        for call in fetch.await_args_list:
            self.assertEqual(call.args[3], 'getTransaction')
            self.assertEqual(call.args[4][0], EVENT['signature'])
            self.assertEqual(call.args[4][1]['commitment'], 'confirmed')
            self.assertEqual(call.kwargs['max_attempts'], 1)
