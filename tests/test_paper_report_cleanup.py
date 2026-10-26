"""P1.6h: synthetic owned resources and deterministic fault injection only."""
import asyncio
from contextlib import ExitStack, closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bot.analyser import paper_engine as pe

REAL_CONNECT = sqlite3.connect
REAL_SLEEP = asyncio.sleep


class InjectedError(RuntimeError):
    pass


class Connection(sqlite3.Connection):
    def close(self):
        self.events.append('sqlite.close')
        self.close_calls += 1
        if self.fail_close:
            raise self.fail_close
        super().close()


class Fetcher:
    interval = 2.5
    max_tx = 10

    def __init__(self, events, start_error=None, close_error=None):
        self.events = events
        self.start_error = start_error
        self.close_error = close_error
        self.close_calls = 0
        self.acquired = False

    async def start(self):
        self.events.append('fetcher.start')
        self.acquired = True  # Deliberately acquire BEFORE start raises.
        if self.start_error:
            raise self.start_error
        return self

    async def close(self):
        self.events.append('fetcher.close')
        self.close_calls += 1
        if self.close_error:
            raise self.close_error
        self.acquired = False


class HTTP:
    def __init__(self, events, enter_error=None, close_error=None):
        self.events = events
        self.enter_error = enter_error
        self.close_error = close_error
        self.close_calls = 0
        self.closed = False

    async def __aenter__(self):
        self.events.append('http.enter')
        if self.enter_error:
            raise self.enter_error
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        self.events.append('http.close')
        self.close_calls += 1
        if self.close_error:
            raise self.close_error
        self.closed = True


class Rig:
    def __init__(self, tmp):
        self.events = []
        self.con = REAL_CONNECT(':memory:', factory=Connection, isolation_level=None)
        self.con.events = self.events
        self.con.close_calls = 0
        self.con.fail_close = None
        self.fetcher = Fetcher(self.events)
        self.http = HTTP(self.events)
        self.tmp = tmp
        self.report = tmp / 'session.json'
        self.periodic = tmp / 'periodic.json'
        self.collect = AsyncMock(return_value=([], 0, False))
        self.cache_error = None
        self.http_create_error = None
        self.previous = b'{"previous_valid_report":true}\n'
        self.report.write_bytes(self.previous)
        self.periodic.write_bytes(self.previous)

    async def run(self, stack, **kwargs):
        now = 1000
        async def collect(*args, **kwargs):
            nonlocal now
            try:
                return await self.collect(*args, **kwargs)
            finally:
                now = 1002
        stack.enter_context(patch.object(pe, 'Database'))
        stack.enter_context(patch.object(pe, 'ensure_schema'))
        stack.enter_context(patch.object(pe.sqlite3, 'connect', return_value=self.con))
        stack.enter_context(patch.object(pe, 'LiveBehaviorFetcher', return_value=self.fetcher))
        stack.enter_context(patch.object(pe.aiohttp, 'ClientSession', return_value=self.http,
                                        side_effect=self.http_create_error))
        stack.enter_context(patch.object(pe, 'load_cached_transactions', return_value=[],
                                        side_effect=self.cache_error))
        stack.enter_context(patch.object(pe, 'collect_once', collect))
        stack.enter_context(patch.object(pe.time, 'time', side_effect=lambda: now))
        stack.enter_context(patch.object(pe.asyncio, 'sleep', new=AsyncMock()))
        options = dict(session_seconds=1, session_report=self.report, report=self.periodic)
        options.update(kwargs)
        await pe.run(self.tmp / 'synthetic.db', **options)

    def release(self):
        sqlite3.Connection.close(self.con)


@pytest.fixture
def rig(tmp_path):
    value = Rig(tmp_path)
    try:
        yield value
    finally:
        value.release()


def failure_objects(error):
    """Traverse explicit diagnostics as well as native exception chains."""
    result, pending = [], [error]
    while pending:
        item = pending.pop()
        if item is None or any(item is old for old in result):
            continue
        result.append(item)
        pending.extend([item.__cause__, item.__context__])
        pending.extend(e for _stage, e in getattr(item, 'paper_failures', ()))
    return result


def inject_report(stack, target, kind):
    error = InjectedError(kind)
    if kind == 'mkdir':
        original = Path.mkdir
        def mkdir(path, *args, **kwargs):
            if path == target.parent:
                raise error
            return original(path, *args, **kwargs)
        stack.enter_context(patch.object(Path, 'mkdir', mkdir))
    elif kind == 'json':
        original = json.dumps
        def dumps(value, *args, **kwargs):
            if isinstance(value, dict) and (('session_started_at' in value) == (target.name == 'session.json')):
                raise error
            return original(value, *args, **kwargs)
        stack.enter_context(patch.object(pe.json, 'dumps', dumps))
    elif kind == 'write':
        original = Path.write_text
        def write(path, value, *args, **kwargs):
            if path == target or path.name.startswith('.' + target.name + '.'):
                original(path, value[:12], *args, **kwargs)
                raise error
            return original(path, value, *args, **kwargs)
        stack.enter_context(patch.object(Path, 'write_text', write))
    elif kind == 'replace':
        original = pe.os.replace
        def replace(source, destination):
            if Path(destination) == target:
                raise error
            return original(source, destination)
        stack.enter_context(patch.object(pe.os, 'replace', replace))
    return error


@pytest.mark.parametrize('kind', ['mkdir', 'json', 'write', 'replace', 'summary', 'print'])
def test_session_report_failure_closes_every_resource(rig, kind):
    async def scenario():
        with ExitStack() as stack:
            if kind in ('summary', 'print'):
                error = InjectedError(kind)
                method = '_session_summary' if kind == 'summary' else '_print_session_summary'
                stack.enter_context(patch.object(pe, method, side_effect=error))
            else:
                error = inject_report(stack, rig.report, kind)
            with pytest.raises(InjectedError) as raised:
                await rig.run(stack)
        assert raised.value is error
        assert rig.fetcher.close_calls == rig.con.close_calls == rig.http.close_calls == 1
        assert rig.http.closed
        assert rig.report.read_bytes() == rig.previous
        assert not list(rig.tmp.glob('.*.tmp'))
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['mkdir', 'json', 'write', 'replace'])
def test_periodic_report_failure_preserves_file_and_closes(rig, kind):
    async def scenario():
        with ExitStack() as stack:
            error = inject_report(stack, rig.periodic, kind)
            with pytest.raises(InjectedError) as raised:
                await rig.run(stack)
        assert raised.value is error
        assert rig.fetcher.close_calls == rig.con.close_calls == rig.http.close_calls == 1
        assert rig.periodic.read_bytes() == rig.previous
        assert not list(rig.tmp.glob('.*.tmp'))
        if kind == 'mkdir':  # Both reports share the directory whose mkdir fails.
            assert rig.report.read_bytes() == rig.previous
        else:
            assert 'ECHEC' in json.loads(rig.report.read_text())['conclusion']
    asyncio.run(scenario())


@pytest.mark.parametrize('which', ['fetcher', 'sqlite', 'both', 'http'])
def test_close_failures_are_visible_and_do_not_skip_other_closes(rig, which):
    errors = []
    for name, obj, attr in [('fetcher', rig.fetcher, 'close_error'),
                            ('sqlite', rig.con, 'fail_close'), ('http', rig.http, 'close_error')]:
        if which == name or (which == 'both' and name != 'http'):
            error = InjectedError(name + ' close')
            setattr(obj, attr, error)
            errors.append(error)
    async def scenario():
        with ExitStack() as stack:
            with pytest.raises(InjectedError) as raised:
                await rig.run(stack)
        assert all(error in failure_objects(raised.value) for error in errors)
        assert rig.fetcher.close_calls == rig.con.close_calls == rig.http.close_calls == 1
        assert 'ECHEC' in json.loads(rig.report.read_text())['conclusion']
    asyncio.run(scenario())


@pytest.mark.parametrize('secondary', ['summary', 'fetcher', 'sqlite', 'http', 'print'])
def test_collection_error_remains_primary(rig, secondary):
    primary, other = InjectedError('collection'), InjectedError(secondary)
    rig.collect.side_effect = primary
    async def scenario():
        with ExitStack() as stack:
            if secondary in ('summary', 'print'):
                method = '_session_summary' if secondary == 'summary' else '_print_session_summary'
                stack.enter_context(patch.object(pe, method, side_effect=other))
            else:
                obj, attr = {'fetcher': (rig.fetcher, 'close_error'),
                             'sqlite': (rig.con, 'fail_close'),
                             'http': (rig.http, 'close_error')}[secondary]
                setattr(obj, attr, other)
            with pytest.raises(InjectedError) as raised:
                await rig.run(stack)
        assert raised.value is primary
        if secondary != 'print':  # Failed sessions must not print a positive financial conclusion.
            assert other in failure_objects(raised.value)
        assert rig.fetcher.close_calls == rig.con.close_calls == rig.http.close_calls == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('stage', ['setup', 'portfolio', 'capital', 'cache', 'fetcher_start', 'http_enter', 'http_create'])
def test_partial_initialization_is_cleaned(rig, stage):
    error = InjectedError(stage)
    async def scenario():
        with ExitStack() as stack:
            if stage in ('setup', 'portfolio', 'capital', 'cache'):
                method = {'setup': 'setup', 'portfolio': 'ensure_paper_portfolio',
                          'capital': 'paper_capital', 'cache': 'load_cached_transactions'}[stage]
                if stage == 'cache':
                    rig.cache_error = error
                else:
                    stack.enter_context(patch.object(pe, method, side_effect=error))
            elif stage == 'fetcher_start':
                rig.fetcher.start_error = error
            elif stage == 'http_enter':
                rig.http.enter_error = error
            else:
                rig.http_create_error = error
            with pytest.raises(InjectedError) as raised:
                await rig.run(stack)
        assert raised.value is error
        assert rig.con.close_calls == 1
        if rig.fetcher.acquired or rig.fetcher.close_calls:
            assert rig.fetcher.close_calls == 1
        if stage in ('cache', 'http_enter'):
            assert rig.http.close_calls == 1
        rig.collect.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('live', [False, True])
def test_normal_session_has_no_orphans_and_finances_unchanged(rig, live):
    async def scenario():
        before = asyncio.all_tasks()
        with ExitStack() as stack:
            await rig.run(stack, live_behavior=live)
        assert asyncio.all_tasks() == before
        assert rig.con.close_calls == rig.http.close_calls == 1
        assert rig.fetcher.close_calls == int(live)
        summary = json.loads(rig.report.read_text())
        assert summary['capital_start_sol'] == summary['capital_end_sol'] == 10
        assert summary['entries'] == summary['closed_trades'] == 0
        periodic = json.loads(rig.periodic.read_text())
        assert periodic['realized_capital_sol'] == 10
        assert periodic['paper_only'] and not periodic['real_orders_enabled']
        assert not list(rig.tmp.glob('.*.tmp'))
    asyncio.run(scenario())


def test_cancellation_is_preserved_even_when_summary_and_close_fail(rig):
    primary = asyncio.CancelledError('synthetic cancellation')
    rig.collect.side_effect = primary
    rig.fetcher.close_error = InjectedError('fetcher close')
    async def scenario():
        before = asyncio.all_tasks()
        with ExitStack() as stack:
            stack.enter_context(patch.object(pe, '_session_summary', side_effect=InjectedError('summary')))
            with pytest.raises(asyncio.CancelledError) as raised:
                await rig.run(stack)
        assert raised.value is primary
        assert rig.fetcher.close_error in failure_objects(raised.value)
        assert rig.con.close_calls == rig.fetcher.close_calls == rig.http.close_calls == 1
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_report_timeout_is_not_retried_as_quote_failure(rig):
    error = asyncio.TimeoutError('synthetic report')
    async def scenario():
        with ExitStack() as stack:
            stack.enter_context(patch.object(pe, 'paper_report', side_effect=error))
            with pytest.raises(asyncio.TimeoutError) as raised:
                await rig.run(stack)
        assert raised.value is error
        rig.collect.assert_awaited_once()
        assert rig.con.close_calls == rig.fetcher.close_calls == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('point', ['pragma', 'journal', 'schema', 'commit'])
@pytest.mark.parametrize('close_error', [False, True])
def test_research_initialization_closes_its_own_connection(point, close_error):
    from bot.analyser import multi_creator_research_engine as research
    error, cleanup = InjectedError(point), InjectedError('research close')
    from unittest.mock import Mock
    con = Mock()
    if point in ('pragma', 'journal'):
        def execute(sql):
            if ('busy_timeout' in sql) == (point == 'pragma'):
                raise error
        con.execute.side_effect = execute
    elif point == 'schema':
        con.executescript.side_effect = error
    else:
        con.commit.side_effect = error
    if close_error:
        con.close.side_effect = cleanup
    with patch.object(research.sqlite3, 'connect', return_value=con):
        with pytest.raises(InjectedError) as raised:
            research.ensure_schema('synthetic.db')
    assert raised.value is error
    con.close.assert_called_once_with()
    if close_error:
        assert cleanup in failure_objects(raised.value)


def test_research_success_returns_open_connection_to_caller(tmp_path):
    from bot.analyser import multi_creator_research_engine as research
    path = tmp_path / 'synthetic.db'
    pe.Database(path)
    research.ensure_schema(path)
    with closing(research.db_connect(path)) as con:
        assert con.execute('SELECT COUNT(*) FROM research_launches').fetchone() == (0,)
        pe.setup(con)
        pe.paper_report(con, 1000, 0, tmp_path / 'report.json')
        # Reporting borrows this connection and must never close it.
        assert con.execute('SELECT 42').fetchone() == (42,)


@pytest.mark.parametrize('kind', ['write', 'replace', 'json'])
def test_failed_new_periodic_report_never_publishes_partial_json(rig, kind):
    rig.periodic.unlink()
    async def scenario():
        with ExitStack() as stack:
            inject_report(stack, rig.periodic, kind)
            with pytest.raises(InjectedError):
                await rig.run(stack)
        assert not rig.periodic.exists()
        assert not list(rig.tmp.glob('.*.tmp'))
        assert rig.con.close_calls == rig.http.close_calls == rig.fetcher.close_calls == 1
    asyncio.run(scenario())


def test_actual_aiohttp_session_closed_on_collection_failure(tmp_path):
    created = []
    factory = pe.aiohttp.ClientSession
    def session(*args, **kwargs):
        value = factory(*args, **kwargs)
        created.append(value)
        return value
    async def scenario():
        before = asyncio.all_tasks()
        with patch.object(pe.aiohttp, 'ClientSession', session), \
                patch.object(pe, 'collect_once', AsyncMock(side_effect=InjectedError('collect'))):
            with pytest.raises(InjectedError):
                await pe.run(tmp_path / 'synthetic.db', live_behavior=False)
        assert created and all(value.closed for value in created)
        assert asyncio.all_tasks() == before
        with closing(REAL_CONNECT(tmp_path / 'synthetic.db', timeout=0)) as con:
            con.execute('BEGIN EXCLUSIVE')
            assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    asyncio.run(scenario())


def test_repeated_external_cancellation_does_not_cancel_cleanup(rig):
    async def scenario():
        entered, closing_fetcher, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def collect(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        rig.collect.side_effect = collect
        async def close_fetcher():
            rig.fetcher.close_calls += 1
            closing_fetcher.set()
            await release.wait()
        rig.fetcher.close = close_fetcher
        before = asyncio.all_tasks()
        with ExitStack() as stack:
            task = asyncio.create_task(rig.run(stack))
            await entered.wait()
            task.cancel('first cancellation')
            await closing_fetcher.wait()
            task.cancel('second cancellation')
            await REAL_SLEEP(0)
            assert rig.con.close_calls == 0  # Cleanup is still running, never claimed complete.
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert rig.con.close_calls == rig.fetcher.close_calls == rig.http.close_calls == 1
        assert 'ANNULEE' in json.loads(rig.report.read_text())['conclusion']
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def supervision_args(tmp):
    return SimpleNamespace(db=tmp / 'synthetic.db', model=None, poll=15, report=None,
        max_open=3, max_entries_day=20, max_daily_loss=10, max_candidates=10,
        max_age=7200, cache_refresh=60, no_live_behavior=True, rpc_interval=2.5,
        behavior_max_tx=10, min_liquidity=1000, shadow_baseline=False,
        shadow_final=False, capital_sol=10, position_pct=10, session_seconds=1,
        session_report=tmp / 'session.json', no_scanner=False)


def test_simultaneous_scanner_and_engine_failures_are_both_diagnosable(tmp_path):
    scanner_error, engine_error = InjectedError('scanner'), InjectedError('engine')
    async def scenario():
        before = asyncio.all_tasks()
        with patch('bot.main.run', AsyncMock(side_effect=scanner_error)), \
                patch.object(pe, 'run', AsyncMock(side_effect=engine_error)):
            with pytest.raises(RuntimeError) as raised:
                await pe.run_with_scanner(supervision_args(tmp_path))
        assert scanner_error in failure_objects(raised.value)
        assert engine_error in failure_objects(raised.value)
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_supervised_engine_cancellation_retains_cleanup_failure(tmp_path):
    close_error = InjectedError('engine resource close')
    async def engine(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            exc.paper_failures = (('engine close', close_error),)
            raise
    async def scenario():
        before = asyncio.all_tasks()
        with patch('bot.main.run', AsyncMock(side_effect=InjectedError('scanner'))), \
                patch.object(pe, 'run', engine):
            with pytest.raises(RuntimeError) as raised:
                await pe.run_with_scanner(supervision_args(tmp_path))
        assert close_error in failure_objects(raised.value)
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_supervisor_partial_acquisition_cancels_scanner(tmp_path):
    tasks = []
    create = asyncio.create_task
    def capture(coro, **kwargs):
        task = create(coro, **kwargs)
        tasks.append(task)
        return task
    async def scanner(**kwargs):
        await asyncio.Event().wait()
    async def scenario():
        before = asyncio.all_tasks()
        with patch('bot.main.run', scanner), patch.object(pe.asyncio, 'create_task', capture), \
                patch.object(pe, '_ScannerEntryGuard', side_effect=InjectedError('guard init')):
            with pytest.raises(InjectedError):
                await pe.run_with_scanner(supervision_args(tmp_path))
        assert tasks and all(t.done() for t in tasks)
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_outer_supervision_preserves_nested_engine_diagnostics(tmp_path):
    error, secondary = InjectedError('engine'), InjectedError('HTTP close')
    async def engine(*args, **kwargs):
        pe._raise_paper_failures([('collection', error), ('HTTP close', secondary)])
    async def scanner(**kwargs):
        await asyncio.Event().wait()
    async def scenario():
        with patch('bot.main.run', scanner), patch.object(pe, 'run', engine):
            with pytest.raises(InjectedError) as raised:
                await pe.run_with_scanner(supervision_args(tmp_path))
        assert raised.value is error
        assert secondary in failure_objects(raised.value)
    asyncio.run(scenario())


def synthetic_session(tmp, mode):
    """Same real collection, ledger, report and export code on both revisions."""
    from bot.analyser.paper_trader import MarketQuote
    from bot.analyser.final_decision_engine import Decision
    from bot.analyser.research_pipeline import export_dataset, export_prices
    from datetime import datetime, timezone
    from test_multiple_launches import transaction, instruction
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / 'synthetic.db'
    pe.Database(db)
    pe.ensure_schema(db)
    with closing(REAL_CONNECT(db, isolation_level=None)) as con:
        if mode != 'empty':
            con.execute('INSERT INTO launch_candidates(protocol,signature,slot,block_time,'
                'detected_at,mint,deployer_candidate,status) VALUES(?,?,?,?,?,?,?,?)',
                ('ray', 'synthetic-sig', 1, None if mode == 'undated' else 980,
                 datetime.fromtimestamp(990, timezone.utc).isoformat(),
                 'synthetic-mint', 'synthetic-creator', 'creator_identified'))
            payload = transaction(instruction('synthetic-mint', creator='synthetic-creator'))
            payload['blockTime'] = None if mode == 'undated' else 980
            con.execute('INSERT INTO research_tx_cache(signature,payload,fetched_ok,updated_at) '
                        'VALUES(?,?,1,?)', ('synthetic-sig', json.dumps(payload), 'synthetic-time'))
    now = 1000
    events = []
    http = HTTP(events)
    async def quote(*args, **kwargs):
        price = .001 if now == 1000 else (.0008 if mode == 'sl' else .0012)
        return MarketQuote(20000, price, 'synthetic-pair'), 0
    async def sleep(*args):
        nonlocal now
        now += 20
    decision = Decision(enter=mode != 'reject', score=56, reasons=('synthetic',),
        risk_flags=(), tp_pct=10, sl_pct=8, hold_seconds=300,
        trailing_stop_pct=None, cost_bps=200)
    pe._analysis_emit_cache.clear()
    output = io.StringIO()
    async def session():
        before = asyncio.all_tasks()
        with patch.object(pe.aiohttp, 'ClientSession', return_value=http), \
                patch.object(pe, 'fetch_quote', quote), \
                patch.object(pe, 'fetch_onchain_quote', AsyncMock(return_value=None)), \
                patch.object(pe, 'decide', return_value=decision), \
                patch.object(pe.time, 'time', side_effect=lambda: now), \
                patch.object(pe.asyncio, 'sleep', sleep), \
                redirect_stdout(output):
            await pe.run(db, live_behavior=False, shadow_final=True, session_seconds=40,
                session_report=tmp / 'session.json', report=tmp / 'periodic.json',
                entry_guard=(lambda: False) if mode == 'guard_blocked' else None)
        assert asyncio.all_tasks() == before
    asyncio.run(session())
    with closing(REAL_CONNECT(db)) as con:
        tables = {name: con.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for name, in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
        schema = con.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    export_prices(db, tmp / 'prices.csv')
    export_dataset(db, tmp / 'dataset.csv')
    return dict(periodic=(tmp / 'periodic.json').read_text(encoding='utf-8'),
                session=(tmp / 'session.json').read_text(encoding='utf-8'),
                periodic_bytes=(tmp / 'periodic.json').read_bytes().hex(),
                session_bytes=(tmp / 'session.json').read_bytes().hex(),
                tables=tables, schema=schema,
                prices=(tmp / 'prices.csv').read_text(encoding='utf-8'),
                dataset=(tmp / 'dataset.csv').read_text(encoding='utf-8'),
                prices_bytes=(tmp / 'prices.csv').read_bytes().hex(),
                dataset_bytes=(tmp / 'dataset.csv').read_bytes().hex(),
                stdout='\n'.join(line for line in output.getvalue().splitlines()
                                 if not line.startswith('[SESSION] rapport:')))


@pytest.mark.parametrize('mode', ['empty', 'tp', 'sl', 'reject', 'guard_blocked', 'undated'])
def test_synthetic_normal_sessions(tmp_path, mode):
    result = synthetic_session(tmp_path, mode)
    report = json.loads(result['session'])
    expected = 10.18 if mode == 'tp' else 9.78 if mode == 'sl' else 10
    assert report['capital_end_sol'] == pytest.approx(expected)
    assert report['closed_trades'] == int(mode in ('tp', 'sl'))
    if mode in ('tp', 'sl'):
        trades = result['tables']['paper_trades']
        assert len(trades) == 1
        assert mode.upper() in trades[0]
    assert json.loads(result['periodic'])['paper_only']
    if mode in ('tp', 'sl', 'reject', 'guard_blocked'):
        assert 'synthetic-mint' in result['dataset']  # Compare actual CSV rows too.
    assert not list(tmp_path.glob('.*.tmp'))


def test_real_fetcher_partial_start_closes_acquired_http_session(tmp_path):
    sessions = []
    error = InjectedError('RPC start after HTTP acquisition')
    class RPC:
        def __init__(self, url):
            self.session = None
        async def __aenter__(self):
            self.session = pe.aiohttp.ClientSession()
            sessions.append(self.session)
            raise error
        async def __aexit__(self, *args):
            await self.session.close()
    async def scenario():
        before = asyncio.all_tasks()
        with patch.object(pe, 'get_settings', return_value=SimpleNamespace(rpc_url='synthetic://unused')), \
                patch.object(pe, 'SolanaRPC', RPC), \
                patch.object(pe, 'collect_once', AsyncMock()) as collect:
            with pytest.raises(InjectedError) as raised:
                await pe.run(tmp_path / 'synthetic.db')
        assert raised.value is error
        assert sessions and all(s.closed for s in sessions)
        collect.assert_not_awaited()
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


def test_cancellation_during_fetcher_start_closes_partial_resource(rig):
    error = asyncio.CancelledError('cancel during start')
    rig.fetcher.start_error = error
    async def scenario():
        with ExitStack() as stack:
            with pytest.raises(asyncio.CancelledError) as raised:
                await rig.run(stack)
        assert raised.value is error
        assert rig.fetcher.close_calls == rig.con.close_calls == 1
        assert rig.http.close_calls == 0  # Never acquired by the engine.
        rig.collect.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('method', ['ensure_signal_status_schema', 'ensure_audit_schema'])
def test_schema_initialization_failure_closes_main_sqlite(rig, method):
    async def scenario():
        with ExitStack() as stack:
            stack.enter_context(patch.object(pe, method, side_effect=InjectedError(method)))
            with pytest.raises(InjectedError):
                await rig.run(stack)
        assert rig.con.close_calls == 1
        assert rig.http.close_calls == rig.fetcher.close_calls == 0
        assert rig.report.read_bytes() == rig.previous
    asyncio.run(scenario())


def test_report_failure_stops_before_next_paper_entry(tmp_path):
    from bot.analyser.paper_trader import MarketQuote
    from bot.analyser.final_decision_engine import Decision
    db = tmp_path / 'synthetic.db'
    pe.Database(db)
    pe.ensure_schema(db)
    with closing(REAL_CONNECT(db, isolation_level=None)) as con:
        for index in (1, 2):
            con.execute('INSERT INTO launch_candidates(protocol,signature,slot,block_time,'
                'detected_at,mint,deployer_candidate,status) VALUES(?,?,?,?,?,?,?,?)',
                ('ray', 'sig' + str(index), index, 980, '1970-01-01T00:16:30+00:00',
                 'mint' + str(index), 'creator' + str(index), 'creator_identified'))
    now = 1000
    async def quote(*args, **kwargs):
        return MarketQuote(20000, .001, 'synthetic-pair'), 0
    async def sleep(*args):
        nonlocal now
        now += 20
    decision = Decision(enter=True, score=56, reasons=('synthetic',), risk_flags=(),
        tp_pct=10, sl_pct=8, hold_seconds=300, trailing_stop_pct=None, cost_bps=200)
    async def scenario():
        before = asyncio.all_tasks()
        with patch.object(pe, 'fetch_quote', AsyncMock(side_effect=quote)) as quotes, \
                patch.object(pe, 'fetch_onchain_quote', AsyncMock(return_value=None)), \
                patch.object(pe, 'decide', return_value=decision), \
                patch.object(pe, 'paper_report', side_effect=asyncio.TimeoutError('report timeout')), \
                patch.object(pe.time, 'time', side_effect=lambda: now), \
                patch.object(pe.asyncio, 'sleep', sleep):
            with pytest.raises(asyncio.TimeoutError):
                await pe.run(db, live_behavior=False, shadow_final=True, max_candidates=1,
                    session_seconds=40, session_report=tmp_path / 'session.json')
        quotes.assert_awaited_once()
        assert asyncio.all_tasks() == before
        with closing(REAL_CONNECT(db)) as con:
            assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)
        assert 'ECHEC' in json.loads((tmp_path / 'session.json').read_text())['conclusion']
    asyncio.run(scenario())


def test_stubborn_supervised_task_is_reported_and_late_failure_observed():
    async def scenario():
        before = asyncio.all_tasks()
        started, release = asyncio.Event(), asyncio.Event()
        late_error = InjectedError('late supervised failure')
        async def stubborn():
            started.set()
            for _ in range(2):
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass
            await release.wait()
            raise late_error
        task = asyncio.create_task(stubborn(), name='synthetic-stubborn')
        await started.wait()
        diagnoses = []
        loop = asyncio.get_running_loop()
        handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: diagnoses.append(context))
        try:
            with pytest.raises(RuntimeError, match='synthetic-stubborn'):
                await pe._stop_supervised_tasks((task,), timeout=.01)
            await REAL_SLEEP(0)
            assert not task.done()
            release.set()
            with pytest.raises(InjectedError):
                await task
            await REAL_SLEEP(0)
            assert any(d.get('exception') is late_error for d in diagnoses)
        finally:
            loop.set_exception_handler(handler)
        assert asyncio.all_tasks() == before
    asyncio.run(scenario())


@pytest.mark.parametrize('point', ['pragma', 'query', 'fetchall'])
@pytest.mark.parametrize('close_error', [False, True])
def test_cache_read_failure_closes_its_separate_sqlite(point, close_error):
    from bot.analyser import behavior_pipeline as behavior
    from unittest.mock import Mock
    con = Mock()
    error, secondary = InjectedError(point), InjectedError('cache close')
    if point == 'fetchall':
        con.execute.return_value.fetchall.side_effect = error
    else:
        def execute(sql):
            if ('busy_timeout' in sql) == (point == 'pragma'):
                raise error
            return con
        con.execute.side_effect = execute
    if close_error:
        con.close.side_effect = secondary
    with patch.object(behavior.sqlite3, 'connect', return_value=con):
        with pytest.raises(InjectedError) as raised:
            behavior.load_cached_transactions('synthetic.db')
    assert raised.value is error
    con.close.assert_called_once_with()
    if close_error:
        assert secondary in failure_objects(raised.value)


def test_caller_owned_gate_is_never_closed(rig):
    from unittest.mock import Mock
    gate = Mock()
    async def scenario():
        with ExitStack() as stack:
            await rig.run(stack, rpc_gate=gate)
        gate.close.assert_not_called()
    asyncio.run(scenario())


def test_final_console_error_preserves_previous_session_report(rig):
    original = print
    error = InjectedError('console report location')
    def fail_location(*args, **kwargs):
        if args and str(args[0]).startswith('[SESSION] rapport:'):
            raise error
        return original(*args, **kwargs)
    async def scenario():
        with ExitStack() as stack:
            stack.enter_context(patch('builtins.print', fail_location))
            with pytest.raises(InjectedError) as raised:
                await rig.run(stack)
        assert raised.value is error
        assert rig.report.read_bytes() == rig.previous
        assert rig.con.close_calls == rig.fetcher.close_calls == rig.http.close_calls == 1
    asyncio.run(scenario())


def test_final_capital_read_error_never_skips_closes(rig):
    original = pe.paper_capital
    calls = 0
    error = InjectedError('final capital read')
    def capital(con):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise error
        return original(con)
    async def scenario():
        with ExitStack() as stack:
            stack.enter_context(patch.object(pe, 'paper_capital', capital))
            with pytest.raises(InjectedError) as raised:
                await rig.run(stack)
        assert raised.value is error
        assert rig.con.close_calls == rig.fetcher.close_calls == rig.http.close_calls == 1
        assert rig.report.read_bytes() == rig.previous
    asyncio.run(scenario())


def test_python310_error_chaining_keeps_original_cause_and_secondary():
    class LegacyError(InjectedError):
        @property
        def add_note(self):
            raise AttributeError('simulate Python 3.10')
    primary, original_cause = LegacyError('engine'), InjectedError('initial cause')
    primary.__cause__ = original_cause
    secondary = InjectedError('close failure')
    with pytest.raises(LegacyError) as raised:
        pe._raise_paper_failures([('collection', primary), ('SQLite close', secondary)])
    assert raised.value is primary
    assert original_cause in failure_objects(primary)
    assert secondary in failure_objects(primary)
    assert 'SQLite close' in str(primary.__cause__)


def test_late_cancelled_supervised_task_keeps_its_cleanup_error():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        cleanup_error = InjectedError('late cancelled task close')
        async def stubborn():
            started.set()
            for _ in range(2):
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass
            await release.wait()
            error = asyncio.CancelledError('late cancellation')
            error.paper_failures = (('SQLite close', cleanup_error),)
            raise error
        task = asyncio.create_task(stubborn(), name='late-cancelled-cleanup')
        await started.wait()
        loop = asyncio.get_running_loop()
        original = loop.get_exception_handler()
        diagnoses = []
        loop.set_exception_handler(lambda _loop, context: diagnoses.append(context))
        try:
            with pytest.raises(RuntimeError, match='late-cancelled-cleanup'):
                await pe._stop_supervised_tasks((task,), timeout=.01)
            await REAL_SLEEP(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            await REAL_SLEEP(0)
            assert any(item.get('exception') is cleanup_error for item in diagnoses)
        finally:
            loop.set_exception_handler(original)
        assert not (asyncio.all_tasks() - {asyncio.current_task()})
    asyncio.run(scenario())
