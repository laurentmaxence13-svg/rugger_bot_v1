"""Synthetic transport cleanup failures, retained without network access."""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from bot.scanner.supervision import ScannerHealth, _await_paper_cleanup, _raise_paper_failures
from bot.solana import websocket as ws


def error_graph(error):
    pending, found = [error], []
    while pending:
        current = pending.pop()
        if current is None or any(current is previous for previous in found):
            continue
        found.append(current)
        pending.extend((current.__cause__, current.__context__))
        pending.extend(nested for _, nested in getattr(current, 'paper_failures', ()))
    return found


class Socket:
    def __init__(self, *messages):
        self.messages = iter(messages)

    async def send(self, value):
        pass

    async def recv(self):
        value = next(self.messages)
        if isinstance(value, BaseException):
            raise value
        return json.dumps(value)


class Connection:
    def __init__(self, socket=None, close_error=None):
        self.socket = socket or object()
        self.close_error = close_error
        self.close_calls = 0
        self.exit_args = None

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *args):
        self.close_calls += 1
        self.exit_args = args
        if self.close_error is not None:
            raise self.close_error


def good_socket():
    return Socket({'id': 1, 'result': 7}, {
        'method': 'logsNotification', 'params': {'subscription': 7, 'result': {
            'context': {'slot': 10},
            'value': {'signature': 'synthetic-signature', 'err': None, 'logs': []},
        }},
    })


@pytest.mark.parametrize('supervised', [False, True])
def test_body_error_remains_primary_when_transport_close_also_fails(supervised):
    primary = ValueError('synthetic payload failure')
    secondary = RuntimeError('synthetic transport close failure')
    connection = Connection(close_error=secondary)
    notified = []

    async def scenario():
        before = asyncio.all_tasks()
        with patch.object(ws.websockets, 'connect', return_value=connection):
            with pytest.raises(ValueError) as raised:
                async with ws._observed_connection(
                        'synthetic://unused', notified.append if supervised else None):
                    raise primary
        assert raised.value is primary
        assert secondary in error_graph(primary)
        assert connection.close_calls == 1
        assert connection.exit_args[:2] == (ValueError, primary)
        if supervised:
            assert notified == [primary, secondary]
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


def test_reconnection_retains_close_failure_in_supervised_error_graph():
    secondary = RuntimeError('synthetic transport close failure')
    first = Connection(Socket([]), close_error=secondary)
    second = Connection(good_socket())
    health = ScannerHealth()
    states = []

    async def changed(message):
        states.append(message)

    async def scenario():
        before = asyncio.all_tasks()
        stream = ws.stream_program_logs(
            'synthetic://unused', 'synthetic-program', on_state=changed,
            on_failure=lambda error: health.fail('transport', error))
        with patch.object(ws.websockets, 'connect', side_effect=[first, second]), \
                patch.object(ws.asyncio, 'sleep', new_callable=AsyncMock):
            try:
                assert (await anext(stream))['signature'] == 'synthetic-signature'
            finally:
                await stream.aclose()
        primary = health.failures[0][1]
        assert isinstance(primary, ws.SubscriptionRejected)
        assert secondary in error_graph(primary)
        assert any(error is secondary for _, error in health.failures)
        assert health.failed and not health.permits_entries()
        assert first.close_calls == second.close_calls == 1
        assert next(state for state in states if state['state'] == 'disconnected')['reason'] == 'SubscriptionRejected'
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


@pytest.mark.parametrize('supervised', [False, True])
def test_stream_cancellation_is_not_replaced_by_close_error_or_reconnection(supervised):
    primary = asyncio.CancelledError('synthetic first cancellation')
    secondary = RuntimeError('synthetic transport close failure')
    connection = Connection(Socket(primary), close_error=secondary)
    health = ScannerHealth()

    async def scenario():
        before = asyncio.all_tasks()
        callback = (lambda error: health.fail('transport', error)) if supervised else None
        stream = ws.stream_program_logs('synthetic://unused', 'program', on_failure=callback)
        with patch.object(ws.websockets, 'connect', return_value=connection) as connect, \
                patch.object(ws.asyncio, 'sleep', new_callable=AsyncMock,
                             side_effect=AssertionError('Cancellation must not reconnect')) as sleep:
            try:
                with pytest.raises(asyncio.CancelledError) as raised:
                    await anext(stream)
            finally:
                await stream.aclose()
        assert raised.value is primary
        assert secondary in error_graph(primary)
        assert connection.close_calls == connect.call_count == 1
        sleep.assert_not_awaited()
        if supervised:
            assert health.failed and any(error is secondary for _, error in health.failures)
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


@pytest.mark.parametrize('close_fails', [False, True])
def test_repeated_cancellation_finishes_owned_close_and_preserves_first(close_fails):
    secondary = RuntimeError('synthetic close failure')

    async def scenario():
        before = asyncio.all_tasks()
        entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        finished = []
        health = ScannerHealth()

        class DelayedConnection(Connection):
            async def __aexit__(self, *args):
                closing.set()
                await release.wait()
                finished.append(True)
                await super().__aexit__(*args)

        connection = DelayedConnection(close_error=secondary if close_fails else None)

        async def consume():
            async with ws._observed_connection(
                    'synthetic://unused', lambda error: health.fail('transport', error)):
                entered.set()
                await asyncio.Event().wait()

        with patch.object(ws.websockets, 'connect', return_value=connection):
            task = asyncio.create_task(consume())
            await entered.wait()
            task.cancel('first cancellation')
            await closing.wait()
            assert health.failed and not task.done()
            task.cancel('second cancellation')
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError) as raised:
                await task
        assert raised.value.args == ('first cancellation',)
        assert any(isinstance(error, asyncio.CancelledError)
                   and error.args == ('second cancellation',) for error in error_graph(raised.value))
        if close_fails:
            assert secondary in error_graph(raised.value)
        assert finished == [True] and connection.close_calls == 1
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


def test_body_close_and_notification_failures_are_all_retained():
    primary = ValueError('synthetic payload')
    close_error = RuntimeError('synthetic close')
    callback_errors = [LookupError('synthetic notification one'), LookupError('synthetic notification two')]
    notified = []

    def notify(error):
        notified.append(error)
        raise callback_errors[len(notified) - 1]

    async def scenario():
        connection = Connection(close_error=close_error)
        with patch.object(ws.websockets, 'connect', return_value=connection):
            with pytest.raises(ValueError) as raised:
                async with ws._observed_connection('synthetic://unused', notify):
                    raise primary
        assert raised.value is primary
        assert notified == [primary, close_error]
        assert all(error in error_graph(primary) for error in [close_error, *callback_errors])
        assert connection.close_calls == 1

    asyncio.run(scenario())


def test_close_failure_without_body_error_is_notified_and_propagated():
    secondary = RuntimeError('synthetic close')
    notified = []

    async def scenario():
        connection = Connection(close_error=secondary)
        with patch.object(ws.websockets, 'connect', return_value=connection):
            with pytest.raises(RuntimeError) as raised:
                async with ws._observed_connection('synthetic://unused', notified.append):
                    pass
        assert raised.value is secondary and notified == [secondary]
        assert connection.exit_args == (None, None, None)
        assert connection.close_calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize('supervised', [False, True])
def test_generator_shutdown_surfaces_close_error_without_reconnecting(supervised):
    secondary = RuntimeError('synthetic shutdown close failure')
    connection = Connection(good_socket(), close_error=secondary)
    notified = []

    async def scenario():
        before = asyncio.all_tasks()
        stream = ws.stream_program_logs(
            'synthetic://unused', 'program',
            on_failure=notified.append if supervised else None)
        with patch.object(ws.websockets, 'connect', return_value=connection) as connect, \
                patch.object(ws.asyncio, 'sleep', new_callable=AsyncMock,
                             side_effect=AssertionError('Generator shutdown must not reconnect')) as sleep:
            assert (await anext(stream))['signature'] == 'synthetic-signature'
            with pytest.raises(RuntimeError) as raised:
                await stream.aclose()
        assert raised.value is secondary
        assert connection.close_calls == connect.call_count == 1
        sleep.assert_not_awaited()
        if supervised:
            assert any(isinstance(error, GeneratorExit) for error in notified)
            assert secondary in notified
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


@pytest.mark.parametrize('supervised', [False, True])
def test_resource_close_cancellation_does_not_replace_body_error(supervised):
    primary = ValueError('synthetic body failure')
    secondary = asyncio.CancelledError('synthetic transport close cancellation')
    connection = Connection(close_error=secondary)
    notified = []

    async def scenario():
        before = asyncio.all_tasks()
        with patch.object(ws.websockets, 'connect', return_value=connection):
            with pytest.raises(ValueError) as raised:
                async with ws._observed_connection(
                        'synthetic://unused', notified.append if supervised else None):
                    raise primary
        assert raised.value is primary and secondary in error_graph(primary)
        assert connection.close_calls == 1
        if supervised:
            assert notified == [primary, secondary]
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


@pytest.mark.parametrize('initial_cancellation', [False, True])
def test_cleanup_child_cancellation_is_not_reported_as_caller_cancellation(initial_cancellation):
    secondary = asyncio.CancelledError('synthetic cleanup child cancelled')

    async def scenario():
        before = asyncio.all_tasks()
        primary = ValueError('synthetic operation failure')
        if initial_cancellation:
            asyncio.current_task().cancel('initial caller cancellation')
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError as error:
                primary = error
        failures = [('operation', primary)]
        before_cancels = asyncio.current_task().cancelling()

        async def cleanup():
            raise secondary

        await _await_paper_cleanup(cleanup(), failures)
        assert asyncio.current_task().cancelling() == before_cancels
        assert not any(stage == 'cleanup cancellation' for stage, _ in failures)
        with pytest.raises(type(primary)) as raised:
            _raise_paper_failures(failures)
        assert raised.value is primary and secondary in error_graph(primary)
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


def test_real_caller_cancellation_during_child_cleanup_keeps_its_precedence():
    primary = ValueError('synthetic operation failure')
    secondary = asyncio.CancelledError('synthetic cleanup child cancelled')

    async def scenario():
        before = asyncio.all_tasks()
        closing, release = asyncio.Event(), asyncio.Event()
        failures = [('operation', primary)]
        finished = []

        async def cleanup():
            closing.set()
            await release.wait()
            finished.append(True)
            raise secondary

        async def consume():
            await _await_paper_cleanup(cleanup(), failures)
            _raise_paper_failures(failures)

        task = asyncio.create_task(consume())
        await closing.wait()
        task.cancel('real caller cancellation')
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await task
        assert raised.value.args == ('real caller cancellation',)
        assert primary in error_graph(raised.value) and secondary in error_graph(raised.value)
        assert finished == [True]
        assert asyncio.all_tasks() == before

    asyncio.run(scenario())


def test_notification_cancellation_does_not_replace_body_error():
    primary = ValueError('synthetic payload failure')
    secondary = asyncio.CancelledError('synthetic callback cancellation')
    connection = Connection()

    def notify(error):
        raise secondary

    async def scenario():
        with patch.object(ws.websockets, 'connect', return_value=connection):
            with pytest.raises(ValueError) as raised:
                async with ws._observed_connection('synthetic://unused', notify):
                    raise primary
        assert raised.value is primary and secondary in error_graph(primary)
        assert connection.close_calls == 1

    asyncio.run(scenario())
