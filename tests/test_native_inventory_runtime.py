"""Active run wires the native reader and closes its journal on success/cancel."""
import asyncio
from contextlib import closing
import sqlite3

import pytest

from bot.analyser import paper_engine as pe
from bot.p3 import inventory_provider as providers


@pytest.mark.parametrize('cancel', [False, True])
def test_active_runtime_connects_native_provider_and_closes_all_handles(tmp_path, monkeypatch, cancel):
    acquired, seen = {}, []
    clock = [1_700_000_000.0]
    class Session:
        _retry_connection = True
        closed = False
        def __init__(self, **kwargs):
            acquired['session'] = self
            acquired['transport_options'] = kwargs
        async def __aenter__(self):
            return self
        async def close(self):
            self.closed = True
    class Reader:
        def __init__(self, session, store, **kwargs):
            acquired['store'], acquired['reader'] = store, self
            assert session._retry_connection is False
            assert kwargs['max_requests'] == 20
    async def collect(*args, **kwargs):
        seen.append(kwargs['inventory_provider'])
        if cancel:
            raise asyncio.CancelledError('synthetic cancellation during active collection')
        return [], 0, False
    async def wait(_delay):
        clock[0] += 2
    monkeypatch.setattr(pe.aiohttp, 'ClientSession', Session)
    monkeypatch.setattr(providers, 'NativeInventoryQuoteProvider', Reader)
    monkeypatch.setattr(pe, 'collect_once', collect)
    monkeypatch.setattr(pe.time, 'time', lambda: clock[0])
    monkeypatch.setattr(pe.asyncio, 'sleep', wait)
    journal = tmp_path/'capture.sqlite'
    coroutine = pe.run(tmp_path/'paper.sqlite', live_behavior=False, shadow_final=True,
        report=tmp_path/'engine.json', session_report=tmp_path/'session.json',
        session_seconds=1, inventory_journal=journal)
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(coroutine)
    else:
        asyncio.run(coroutine)
    assert seen == [acquired['reader']]
    assert acquired['session'].closed
    assert acquired['transport_options']['trust_env'] is False
    assert acquired['store']._con is None
    with closing(sqlite3.connect(journal, timeout=0)) as con:
        con.execute('BEGIN EXCLUSIVE')


def test_invalid_native_session_refuses_before_touching_existing_data(tmp_path):
    database = tmp_path/'existing.sqlite'
    database.write_bytes(b'synthetic file that must remain unopened')
    with pytest.raises(ValueError, match='new separate journal'):
        asyncio.run(pe.run(database, session_seconds=0, inventory_journal=tmp_path/'quotes.sqlite'))
    assert database.read_bytes() == b'synthetic file that must remain unopened'
    assert not (tmp_path/'quotes.sqlite').exists()
