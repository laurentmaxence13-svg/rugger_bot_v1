"""Owned-resource lifecycle of the standalone PAPER collector, offline only."""
import asyncio
from contextlib import ExitStack, closing
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from bot.analyser import paper_trader as pt


REAL_CONNECT = sqlite3.connect
REAL_SLEEP = asyncio.sleep


class Connection(sqlite3.Connection):
    close_calls = 0
    close_error = None
    execute_error = None

    def execute(self, sql, *args, **kwargs):
        if self.execute_error is not None and sql.startswith('PRAGMA busy_timeout'):
            raise self.execute_error
        return super().execute(sql, *args, **kwargs)

    def close(self):
        self.close_calls += 1
        super().close()
        if self.close_error is not None:
            raise self.close_error


class HTTP:
    def __init__(self):
        self.close_calls = 0
        self.enter_error = self.close_error = None
        self.closing = self.release = None

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        self.close_calls += 1
        if self.closing is not None:
            self.closing.set()
            await self.release.wait()
        if self.close_error is not None:
            raise self.close_error


def errors(error):
    pending, seen = [error], []
    while pending:
        current = pending.pop()
        if current is None or any(current is item for item in seen):
            continue
        seen.append(current)
        pending.extend([current.__cause__, current.__context__])
        pending.extend(value for _stage, value in getattr(current, 'paper_failures', ()))
    return seen


@pytest.mark.parametrize('stage', ['pragma', 'schema', 'http_factory', 'http_enter', 'collection'])
@pytest.mark.parametrize('close_fails', [False, True])
def test_startup_and_collection_failures_close_every_acquired_handle(tmp_path, stage, close_fails):
    primary = RuntimeError('synthetic ' + stage)
    sqlite_error, http_error = ValueError('SQLite close'), ValueError('HTTP close')
    con = REAL_CONNECT(tmp_path / 'synthetic.db', factory=Connection, isolation_level=None)
    http = HTTP()
    con.close_error = sqlite_error if close_fails else None
    http.close_error = http_error if close_fails else None
    if stage == 'pragma':
        con.execute_error = primary
    if stage == 'http_enter':
        http.enter_error = primary

    async def scenario():
        before = asyncio.all_tasks()
        with ExitStack() as stack:
            stack.enter_context(patch.object(pt.sqlite3, 'connect', return_value=con))
            factory = stack.enter_context(patch.object(pt.aiohttp, 'ClientSession', return_value=http))
            stack.enter_context(patch.object(pt, 'recent_signals', side_effect=primary))
            if stage == 'schema':
                stack.enter_context(patch.object(pt, 'setup', side_effect=primary))
            if stage == 'http_factory':
                factory.side_effect = primary
            with pytest.raises(RuntimeError) as raised:
                await pt.run(tmp_path / 'synthetic.db')
        assert raised.value is primary
        assert con.close_calls == 1
        http_acquired = stage in ('http_enter', 'collection')
        assert http.close_calls == int(http_acquired)
        if close_fails:
            assert sqlite_error in errors(raised.value)
            if http_acquired:
                assert http_error in errors(raised.value)
        assert asyncio.all_tasks() == before

    try:
        asyncio.run(scenario())
    finally:
        sqlite3.Connection.close(con)


@pytest.mark.parametrize('http_close_fails', [False, True])
def test_repeated_cancellation_finishes_owned_cleanup_and_preserves_primary(tmp_path, http_close_fails):
    con = REAL_CONNECT(tmp_path / 'synthetic.db', factory=Connection, isolation_level=None)
    http = HTTP()
    secondary = ValueError('HTTP close')
    http.close_error = secondary if http_close_fails else None

    async def scenario():
        before = asyncio.all_tasks()
        http.closing, http.release = asyncio.Event(), asyncio.Event()
        collecting = asyncio.Event()
        async def quote(*args, **kwargs):
            collecting.set()
            await asyncio.Event().wait()
        with patch.object(pt.sqlite3, 'connect', return_value=con), \
                patch.object(pt.aiohttp, 'ClientSession', return_value=http), \
                patch.object(pt, 'recent_signals', return_value=[('mint', 'creator', 1000)]), \
                patch.object(pt, 'fetch_quote', quote):
            task = asyncio.create_task(pt.run(tmp_path / 'synthetic.db'))
            await collecting.wait()
            task.cancel('first cancellation')
            await http.closing.wait()
            task.cancel('second cancellation')
            await REAL_SLEEP(0)
            try:
                assert con.close_calls == 0
                assert not task.done()
            finally:
                http.release.set()
                with pytest.raises(asyncio.CancelledError) as raised:
                    await task
        assert raised.value.args == ('first cancellation',)
        if http_close_fails:
            assert secondary in errors(raised.value)
        assert con.close_calls == http.close_calls == 1
        assert asyncio.all_tasks() == before

    try:
        asyncio.run(scenario())
    finally:
        sqlite3.Connection.close(con)


@pytest.mark.parametrize('collection_cancelled', [False, True])
def test_http_close_cancellation_does_not_replace_collection_primary(tmp_path, collection_cancelled):
    """A close implementation raising CancelledError did not cancel our caller."""
    primary = (asyncio.CancelledError('collection cancelled') if collection_cancelled
               else ValueError('collection failed'))
    secondary = asyncio.CancelledError('HTTP close self-cancelled')
    con = REAL_CONNECT(tmp_path / 'synthetic.db', factory=Connection, isolation_level=None)
    http = HTTP()
    http.close_error = secondary

    async def scenario():
        before = asyncio.all_tasks()
        with patch.object(pt.sqlite3, 'connect', return_value=con), \
                patch.object(pt.aiohttp, 'ClientSession', return_value=http), \
                patch.object(pt, 'recent_signals', side_effect=primary):
            with pytest.raises(type(primary)) as raised:
                await pt.run(tmp_path / 'synthetic.db')
        assert raised.value is primary
        assert secondary in errors(raised.value)
        assert con.close_calls == http.close_calls == 1
        assert asyncio.all_tasks() == before

    try:
        asyncio.run(scenario())
    finally:
        sqlite3.Connection.close(con)


def test_real_caller_cancellation_during_cleanup_stays_cancellation(tmp_path):
    """Unlike a close self-cancellation, task.cancel() must reach the caller."""
    primary = ValueError('collection failed before caller cancellation')
    secondary = asyncio.CancelledError('HTTP close self-cancelled')
    con = REAL_CONNECT(tmp_path / 'synthetic.db', factory=Connection, isolation_level=None)
    http = HTTP()
    http.close_error = secondary

    async def scenario():
        before = asyncio.all_tasks()
        http.closing, http.release = asyncio.Event(), asyncio.Event()
        with patch.object(pt.sqlite3, 'connect', return_value=con), \
                patch.object(pt.aiohttp, 'ClientSession', return_value=http), \
                patch.object(pt, 'recent_signals', side_effect=primary):
            task = asyncio.create_task(pt.run(tmp_path / 'synthetic.db'))
            await http.closing.wait()
            task.cancel('caller cancelled during cleanup')
            await REAL_SLEEP(0)
            try:
                assert con.close_calls == 0
                assert not task.done()
            finally:
                http.release.set()
                with pytest.raises(asyncio.CancelledError) as raised:
                    await task
        assert raised.value.args == ('caller cancelled during cleanup',)
        assert primary in errors(raised.value)
        assert secondary in errors(raised.value)
        assert con.close_calls == http.close_calls == 1
        assert asyncio.all_tasks() == before

    try:
        asyncio.run(scenario())
    finally:
        sqlite3.Connection.close(con)


def test_real_aiohttp_session_and_sqlite_are_closed_after_collection_failure(tmp_path):
    con = REAL_CONNECT(tmp_path / 'synthetic.db', factory=Connection, isolation_level=None)
    sessions = []
    factory = pt.aiohttp.ClientSession
    primary = RuntimeError('collection failed before any network call')
    def session(*args, **kwargs):
        value = factory(*args, **kwargs)
        sessions.append(value)
        return value
    async def scenario():
        with patch.object(pt.sqlite3, 'connect', return_value=con), \
                patch.object(pt.aiohttp, 'ClientSession', session), \
                patch.object(pt, 'recent_signals', side_effect=primary):
            with pytest.raises(RuntimeError) as raised:
                await pt.run(tmp_path / 'synthetic.db')
        assert raised.value is primary
        assert sessions and all(value.closed for value in sessions)
        assert con.close_calls == 1
        with pytest.raises(sqlite3.ProgrammingError):
            con.execute('SELECT 1')
        with closing(REAL_CONNECT(tmp_path / 'synthetic.db', timeout=0)) as reopened:
            reopened.execute('BEGIN EXCLUSIVE')
            assert reopened.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    try:
        asyncio.run(scenario())
    finally:
        sqlite3.Connection.close(con)


def test_normal_collection_records_same_quote_without_creating_trade(tmp_path):
    con = REAL_CONNECT(tmp_path / 'synthetic.db', factory=Connection, isolation_level=None)
    http = HTTP()
    cancelled = asyncio.CancelledError('synthetic stop after one completed cycle')
    quote = pt.MarketQuote(20000, 1.25, 'pair', quote_source='synthetic')
    async def scenario():
        with patch.object(pt.sqlite3, 'connect', return_value=con), \
                patch.object(pt.aiohttp, 'ClientSession', return_value=http), \
                patch.object(pt, 'recent_signals', return_value=[('mint', 'creator', 1000)]), \
                patch.object(pt, 'fetch_quote', AsyncMock(return_value=(quote, 0))), \
                patch.object(pt.time, 'time', return_value=1100), \
                patch.object(pt.asyncio, 'sleep', AsyncMock(side_effect=cancelled)):
            with pytest.raises(asyncio.CancelledError) as raised:
                await pt.run(tmp_path / 'synthetic.db')
        assert raised.value is cancelled
        assert con.close_calls == http.close_calls == 1
        with closing(REAL_CONNECT(tmp_path / 'synthetic.db')) as reopened:
            assert reopened.execute('SELECT mint,timestamp,price_usd,pair_address,liquidity_usd FROM paper_prices').fetchall() == [
                ('mint', 1100, 1.25, 'pair', 20000),
            ]
            assert reopened.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    try:
        asyncio.run(scenario())
    finally:
        sqlite3.Connection.close(con)
