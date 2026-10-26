"""Synthetic subscription, reconnection and durable backfill scenarios."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from bot.scanner.backfill import ProgramBackfill
from bot.scanner.tx_recovery import TransactionRecovery
from bot.solana import websocket as ws_module


def row(signature, slot, err=None):
    return {'signature': signature, 'slot': slot, 'err': err, 'blockTime': slot}


def event(signature, slot):
    return {'signature': signature, 'slot': slot,
            'received_at': datetime.fromtimestamp(1000, timezone.utc)}


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'synthetic.db'
        self.store = TransactionRecovery(self.path)
        self.fetch = AsyncMock()
        self.backfill = ProgramBackfill(self.store, 'program', self.fetch, page_size=2,
                                        max_pages=3, clock=lambda: 1000)

    def execute(self, sql, args=()):
        with closing(sqlite3.connect(self.path, isolation_level=None)) as con:
            return con.execute(sql, args).fetchall()

    def anchor(self, signature='old', slot=1):
        self.store.enqueue(event(signature, slot), 1000)
        self.execute("UPDATE scanner_backfill_state SET cursor_signature=?,cursor_slot=?,history_status='caught_up'",
                     (signature, slot))

    def signatures(self):
        return {r[0] for r in self.execute('SELECT signature FROM scanner_tx_recovery')}

    async def test_bootstrap_is_explicitly_a_limited_baseline(self):
        self.fetch.return_value = [row('new', 3), row('older', 2)]
        await self.backfill.once()
        self.assertEqual(self.backfill.state()[:4], ('new', 3, 'baseline', 'bootstrap_recent_window_only'))
        self.assertEqual(self.signatures(), {'new', 'older'})
        self.fetch.assert_awaited_once_with('program', {'limit': 2, 'commitment': 'confirmed'})
        self.assertEqual(self.execute('SELECT coverage_start_signature FROM scanner_backfill_state'), [('new',)])

    async def test_disconnect_gap_pagination_and_duplicate_boundary(self):
        self.anchor()
        self.fetch.side_effect = [[row('new', 4), row('middle', 3)],
                                  [row('middle', 3), row('gap', 2)], [row('old', 1)]]
        await self.backfill.on_state({'state': 'disconnected'})
        self.assertEqual(self.backfill.state()[2], 'degraded')
        await self.backfill.on_state({'state': 'subscribed'})
        await self.backfill.once()
        self.assertEqual(self.signatures(), {'old', 'new', 'middle', 'gap'})
        self.assertEqual(self.backfill.state()[:3], ('new', 4, 'caught_up'))
        self.assertEqual(self.fetch.await_args_list[1].args[1]['before'], 'middle')
        self.assertEqual(self.fetch.await_args_list[2].args[1]['before'], 'gap')

    async def test_live_history_overlap_does_not_reset_receipts(self):
        self.anchor()
        self.store.enqueue(event('live', 3), 900)
        self.execute("UPDATE scanner_tx_recovery SET state='done',attempts=2 WHERE signature='live'")
        self.fetch.return_value = [row('live', 3), row('old', 1)]
        await self.backfill.once()
        self.assertEqual(self.execute("SELECT state,attempts,received_at FROM scanner_tx_recovery WHERE signature='live'"),
                         [('done', 2, event('live', 3)['received_at'].isoformat())])
        self.assertEqual(self.backfill.state()[:3], ('live', 3, 'caught_up'))

    async def test_restart_preserves_cursor_and_recovers_gap(self):
        self.anchor()
        restarted = ProgramBackfill(TransactionRecovery(self.path), 'program', self.fetch,
                                    page_size=2, clock=lambda: 1000)
        self.fetch.return_value = [row('after-restart', 2), row('old', 1)]
        await restarted.once()
        self.assertEqual(restarted.state()[:3], ('after-restart', 2, 'caught_up'))
        self.assertIn('after-restart', self.signatures())

    async def test_page_limit_checkpoint_continues_without_advancing_cursor(self):
        self.anchor()
        bounded = ProgramBackfill(self.store, 'program', self.fetch, page_size=2,
                                  max_pages=1, clock=lambda: 1000)
        self.fetch.side_effect = [[row('head', 5), row('four', 4)],
                                  [row('three', 3), row('two', 2)], [row('old', 1)]]
        await bounded.once()
        self.assertEqual(bounded.state()[:3], ('old', 1, 'degraded'))
        self.assertEqual(self.execute('SELECT scan_before FROM scanner_backfill_state'), [('four',)])
        restarted = ProgramBackfill(self.store, 'program', self.fetch, page_size=2,
                                    max_pages=1, clock=lambda: 1000)
        await restarted.once()
        self.assertEqual(restarted.state()[0], 'old')
        await restarted.once()
        self.assertEqual(restarted.state()[:3], ('head', 5, 'caught_up'))
        self.assertEqual(self.signatures(), {'old', 'head', 'four', 'three', 'two'})
        self.assertEqual(self.execute('SELECT scan_before,scan_head_signature FROM scanner_backfill_state'), [(None, None)])

    async def test_failed_transactions_skipped_without_skipping_valid_creation_candidates(self):
        self.anchor()
        self.fetch.side_effect = [[row('failed', 4, {'InstructionError': []}), row('valid', 3)], [row('old', 1)]]
        await self.backfill.once()
        self.assertEqual(self.signatures(), {'old', 'valid'})
        self.assertEqual(self.backfill.state()[:3], ('valid', 3, 'caught_up'))

    async def test_truncated_history_does_not_advance_cursor(self):
        self.anchor()
        self.fetch.side_effect = [[row('head', 4), row('three', 3)], []]
        await self.backfill.once()
        self.assertEqual(self.backfill.state()[:4], ('old', 1, 'degraded', 'anchor_not_found'))
        self.assertEqual(self.signatures(), {'old', 'head', 'three'})

    async def test_rpc_head_behind_live_is_not_presented_as_caught_up(self):
        self.anchor()
        self.store.enqueue(event('live', 4), 1000)
        self.fetch.return_value = [row('indexed', 3), row('old', 1)]
        await self.backfill.once()
        self.assertEqual(self.backfill.state()[:4], ('indexed', 3, 'degraded', 'rpc_head_behind_recorded_slot'))
        self.fetch.return_value = [row('live', 4), row('indexed', 3)]
        await self.backfill.once()
        self.assertEqual(self.backfill.state()[:3], ('live', 4, 'caught_up'))

    async def test_rpc_429_or_timeout_does_not_advance_cursor(self):
        self.anchor()
        for error in (RuntimeError('synthetic HTTP 429'), TimeoutError()):
            with self.subTest(error=type(error).__name__):
                self.fetch.side_effect = error
                await self.backfill.once()
                self.assertEqual(self.backfill.state()[0], 'old')
                self.assertEqual(self.backfill.state()[2], 'degraded')
                self.assertNotIn('429', self.backfill.state()[3])  # only error classes are stored

    async def test_history_429_respects_existing_gate_and_fallback(self):
        from bot.analyser.multi_creator_research_engine import rpc_json
        self.anchor()
        class Response:
            def __init__(self, status):
                self.status, self.headers = status, {'Retry-After': '2'}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                pass
        post = Mock(side_effect=[Response(429), Response(503)])
        rpc = SimpleNamespace(session=SimpleNamespace(post=post))
        gate = SimpleNamespace(wait_turn=AsyncMock(), on_429=Mock())
        async def fetch(program, options):
            return await rpc_json(rpc, 'https://synthetic.invalid', gate,
                                  'getSignaturesForAddress', [program, options], max_attempts=1)
        self.backfill.fetch_page = fetch
        await self.backfill.once()
        self.assertEqual(post.call_count, 2)
        gate.wait_turn.assert_awaited_once()
        gate.on_429.assert_called_once_with(2.0)
        self.assertEqual(self.backfill.state()[:3], ('old', 1, 'degraded'))

    async def test_timeout_of_stuck_page_is_bounded(self):
        self.anchor()
        async def stuck(*_args):
            await asyncio.Event().wait()
        limited = ProgramBackfill(self.store, 'program', stuck, page_timeout=.01, clock=lambda: 1000)
        await asyncio.wait_for(limited.once(), timeout=1)
        self.assertEqual(limited.state()[0], 'old')
        self.assertEqual(limited.state()[2], 'degraded')

    async def test_queue_full_rolls_back_entire_batch_and_cursor(self):
        self.anchor()
        limited_store = TransactionRecovery(self.path, max_pending=2)
        limited = ProgramBackfill(limited_store, 'program', self.fetch, page_size=3, clock=lambda: 1000)
        self.fetch.return_value = [row('new', 3), row('middle', 2), row('old', 1)]
        await limited.once()
        self.assertEqual(self.signatures(), {'old'})
        self.assertEqual(limited.state()[:3], ('old', 1, 'degraded'))
        self.assertIn('RecoveryQueueFull', limited.state()[3])

    async def test_sqlite_failure_after_enqueue_rolls_back_cursor_and_queue(self):
        self.anchor()
        self.execute("CREATE TRIGGER injected_failure BEFORE UPDATE OF cursor_signature ON scanner_backfill_state "
                     "BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        self.fetch.return_value = [row('new', 2), row('old', 1)]
        await self.backfill.once()
        self.assertEqual(self.signatures(), {'old'})
        self.assertEqual(self.backfill.state()[:3], ('old', 1, 'degraded'))

    async def test_ignored_insert_cannot_advance_cursor(self):
        self.anchor()
        self.execute("CREATE TRIGGER ignore_signature BEFORE INSERT ON scanner_tx_recovery "
                     "BEGIN SELECT RAISE(IGNORE); END")
        self.fetch.return_value = [row('new', 2), row('old', 1)]
        await self.backfill.once()
        self.assertEqual(self.signatures(), {'old'})
        self.assertEqual(self.backfill.state()[:3], ('old', 1, 'degraded'))

    async def test_live_is_persisted_while_history_rpc_is_waiting(self):
        self.anchor()
        rpc_started = asyncio.Event()
        live_persisted = asyncio.Event()

        async def fetch(*_args):
            rpc_started.set()
            await live_persisted.wait()
            return [row('live', 3), row('gap', 2)]

        async def page(program, options):
            if 'before' in options:
                return [row('old', 1)]
            return await fetch(program, options)

        self.backfill.fetch_page = page
        task = asyncio.create_task(self.backfill.once())
        await asyncio.wait_for(rpc_started.wait(), timeout=1)
        self.store.enqueue(event('live', 3), 1000)
        live_persisted.set()
        await asyncio.wait_for(task, timeout=1)
        self.assertEqual(self.signatures(), {'old', 'live', 'gap'})
        self.assertEqual(self.backfill.state()[:3], ('live', 3, 'caught_up'))

    async def test_repeating_pagination_is_explicitly_degraded(self):
        self.anchor()
        self.fetch.return_value = [row('x', 3), row('y', 2)]
        await self.backfill.once()
        self.assertEqual(self.backfill.state()[0], 'old')
        self.assertEqual(self.backfill.state()[2], 'degraded')
        self.assertLessEqual(self.fetch.await_count, self.backfill.max_pages)

    async def test_interruption_preserves_coverage_cursor(self):
        self.anchor()
        started = asyncio.Event()
        async def stuck(*_args):
            started.set()
            await asyncio.Event().wait()
        self.backfill.fetch_page = stuck
        task = asyncio.create_task(self.backfill.once())
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.backfill.state()[:4], ('old', 1, 'degraded', 'interrupted'))

    async def test_malformed_or_repeating_pages_do_not_claim_completion(self):
        self.anchor()
        for page in ([{'signature': 'bad'}], {'not': 'a page'}, [row('x', 2), row('y', 3)]):
            with self.subTest(page=page):
                self.fetch.side_effect = None
                self.fetch.return_value = page
                await self.backfill.once()
                self.assertEqual(self.backfill.state()[0], 'old')
                self.assertEqual(self.backfill.state()[2], 'degraded')

    async def test_refusal_is_persisted_and_reconnect_requests_a_pass(self):
        self.anchor()
        await self.backfill.on_state({'state': 'subscription_refused'})
        self.assertEqual(self.backfill.state()[2:], ('degraded', 'subscription_refused', 'subscription_refused'))
        self.assertFalse(self.backfill.requested.is_set())
        await self.backfill.on_state({'state': 'subscribed'})
        self.assertTrue(self.backfill.requested.is_set())

    async def test_periodic_backfill_runs_without_new_live_notifications(self):
        self.anchor()
        calls = 0
        second = asyncio.Event()
        async def fetch(*_args):
            nonlocal calls
            calls += 1
            if calls == 2:
                second.set()
            return [row('old', 1)]
        periodic = ProgramBackfill(self.store, 'program', fetch, interval=.01, clock=lambda: 1000)
        task = asyncio.create_task(periodic.run())
        try:
            await periodic.on_state({'state': 'subscribed'})
            await asyncio.wait_for(second.wait(), timeout=1)
            self.assertGreaterEqual(calls, 2)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_main_uses_one_shared_gate_for_live_and_backfill(self):
        from bot import main as scanner
        settings = SimpleNamespace(db_path=self.path, rpc_url='https://synthetic.invalid',
                                   ws_url='wss://synthetic.invalid', raydium_launchpad_program_id='program')
        gate = object()
        calls = []
        async def rpc(_rpc, _url, used_gate, method, params, **kwargs):
            calls.append((used_gate, method, params, kwargs))
            if method == 'getSignaturesForAddress':
                return [row('live', 3)]
            return {'blockTime': 1, 'meta': {'err': None}, 'transaction': {'message': {'instructions': []}}}
        async def stream(*_args, on_state, on_failure=None):
            await on_state({'state': 'subscribed'})
            yield event('live', 3)
            await asyncio.sleep(.02)
        with patch.object(scanner, 'get_settings', return_value=settings), \
                patch.object(scanner, 'SolanaRPC', return_value=AsyncMock()), \
                patch.object(scanner, 'stream_program_logs', side_effect=stream), \
                patch.object(scanner, 'rpc_json', side_effect=rpc):
            await asyncio.wait_for(scanner.run(rpc_gate=gate), timeout=2)
        self.assertEqual({call[1] for call in calls}, {'getTransaction', 'getSignaturesForAddress'})
        self.assertTrue(all(call[0] is gate and call[3]['max_attempts'] == 1 for call in calls))
        self.assertEqual(self.signatures(), {'live'})

    async def test_live_queue_saturation_persists_degraded_state(self):
        from bot import main as scanner
        from bot.scanner.tx_recovery import RecoveryQueueFull
        settings = SimpleNamespace(db_path=self.path, rpc_url='https://synthetic.invalid',
                                   ws_url='wss://synthetic.invalid', raydium_launchpad_program_id='program')
        limited = TransactionRecovery(self.path, max_pending=1)
        async def stream(*_args, on_state, on_failure=None):
            await on_state({'state': 'subscribed'})
            yield event('one', 1)
            yield event('two', 2)
        async def stuck_rpc(*_args, **_kwargs):
            await asyncio.Event().wait()
        with patch.object(scanner, 'get_settings', return_value=settings), \
                patch.object(scanner, 'SolanaRPC', return_value=AsyncMock()), \
                patch.object(scanner, 'stream_program_logs', side_effect=stream), \
                patch.object(scanner, 'TransactionRecovery', return_value=limited), \
                patch.object(scanner, 'rpc_json', side_effect=stuck_rpc), \
                self.assertRaises(RecoveryQueueFull):
            await asyncio.wait_for(scanner.run(), timeout=2)
        self.assertEqual(self.backfill.state()[2:], ('degraded', 'disconnected:RecoveryQueueFull', 'disconnected'))
        self.assertIsNone(self.backfill.state()[0])
        self.assertEqual(self.signatures(), {'one'})


class FakeSocket:
    def __init__(self, *messages):
        self.messages = iter(messages)
        self.send = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def recv(self):
        value = next(self.messages)
        if isinstance(value, BaseException):
            raise value
        return json.dumps(value)


def notification(signature, subscription=7, err=None):
    return {'method': 'logsNotification', 'params': {'subscription': subscription,
            'result': {'context': {'slot': 10}, 'value': {'signature': signature, 'err': err, 'logs': []}}}}


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_refused_subscription_is_not_reported_operational(self):
        states = []
        async def changed(message):
            states.append(message['state'])
        stream = ws_module.stream_program_logs('wss://synthetic.invalid', 'program', on_state=changed)
        first = FakeSocket({'id': 1, 'error': {'code': -32602}})
        second = FakeSocket({'id': 1, 'result': 7}, notification('valid'))
        with patch.object(ws_module.websockets, 'connect', side_effect=[first, second]), \
                patch.object(ws_module.asyncio, 'sleep', new_callable=AsyncMock):
            received = await anext(stream)
            await stream.aclose()
        self.assertEqual(received['signature'], 'valid')
        self.assertEqual(states, ['subscribing', 'subscription_refused', 'disconnected', 'subscribing', 'subscribed'])

    async def test_disconnect_then_reconnect_requires_another_ack(self):
        states = []
        async def changed(message):
            states.append(message['state'])
        stream = ws_module.stream_program_logs('wss://synthetic.invalid', 'program', on_state=changed)
        first = FakeSocket({'id': 1, 'result': 7}, notification('before'), ConnectionError())
        second = FakeSocket({'id': 1, 'result': 8}, notification('after', subscription=8))
        with patch.object(ws_module.websockets, 'connect', side_effect=[first, second]), \
                patch.object(ws_module.asyncio, 'sleep', new_callable=AsyncMock):
            self.assertEqual((await anext(stream))['signature'], 'before')
            self.assertEqual((await anext(stream))['signature'], 'after')
            await stream.aclose()
        self.assertEqual(states.count('subscribed'), 2)
        self.assertIn('disconnected', states)

    async def test_wrong_subscription_and_failed_transaction_are_ignored(self):
        socket = FakeSocket({'id': 1, 'result': 7}, notification('wrong', subscription=8),
                            notification('failed', err={'InstructionError': []}), notification('good'))
        stream = ws_module.stream_program_logs('wss://synthetic.invalid', 'program')
        with patch.object(ws_module.websockets, 'connect', return_value=socket):
            self.assertEqual((await anext(stream))['signature'], 'good')
            await stream.aclose()

    async def test_ack_timeout_reconnects_without_false_confirmation(self):
        states = []
        async def changed(message):
            states.append(message['state'])
        stream = ws_module.stream_program_logs('wss://synthetic.invalid', 'program', on_state=changed)
        first = FakeSocket(TimeoutError())
        second = FakeSocket({'id': 1, 'result': 7}, notification('good'))
        with patch.object(ws_module.websockets, 'connect', side_effect=[first, second]), \
                patch.object(ws_module.asyncio, 'sleep', new_callable=AsyncMock):
            self.assertEqual((await anext(stream))['signature'], 'good')
            await stream.aclose()
        self.assertEqual(states.count('subscribed'), 1)
        self.assertEqual(states[:2], ['subscribing', 'disconnected'])

    async def test_subscription_429_uses_public_fallback_after_refusal(self):
        first = FakeSocket({'id': 1, 'error': {'code': 429}})
        second = FakeSocket({'id': 1, 'result': 7}, notification('good'))
        stream = ws_module.stream_program_logs('wss://synthetic.invalid', 'program')
        with patch.object(ws_module.websockets, 'connect', side_effect=[first, second]) as connect, \
                patch.object(ws_module.asyncio, 'sleep', new_callable=AsyncMock):
            self.assertEqual((await anext(stream))['signature'], 'good')
            await stream.aclose()
        self.assertEqual(connect.call_args_list[1].args[0], ws_module.PUBLIC_SOLANA_WS)

    async def test_notification_before_ack_is_not_reported_as_operational(self):
        states = []
        async def changed(message):
            states.append(message['state'])
        first = FakeSocket(notification('unconfirmed-subscription'))
        second = FakeSocket({'id': 1, 'result': 7}, notification('confirmed'))
        stream = ws_module.stream_program_logs('wss://synthetic.invalid', 'program', on_state=changed)
        with patch.object(ws_module.websockets, 'connect', side_effect=[first, second]), \
                patch.object(ws_module.asyncio, 'sleep', new_callable=AsyncMock):
            self.assertEqual((await anext(stream))['signature'], 'confirmed')
            await stream.aclose()
        self.assertEqual(states.count('subscribed'), 1)
