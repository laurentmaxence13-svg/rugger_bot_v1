"""P1.6i coverage partitions on synthetic SQLite and mocked observations."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from bot.analyser import paper_engine as pe
from bot.analyser.paper_trader import MarketQuote, ensure_paper_portfolio, setup
from bot.database.db import Database
from test_multiple_launches import transaction, instruction, events
from bot.scanner.tx_recovery import TransactionRecovery, recover_transactions


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / 'synthetic.db'
    Database(path)
    pe.ensure_schema(path)
    with closing(sqlite3.connect(path, isolation_level=None)) as con:
        setup(con)
        pe.ensure_signal_status_schema(con)
        pe.ensure_audit_schema(con)
        ensure_paper_portfolio(con, 10, 1000)
        yield path, con


def populate(con, launches=(), research=(), prices=(), *, when=980, status='creator_identified'):
    for index, mint in enumerate(launches):
        con.execute('INSERT INTO launch_candidates(protocol,signature,slot,block_time,detected_at,'
                    'mint,deployer_candidate,status) VALUES(?,?,?,?,?,?,?,?)',
                    ('ray', 'sig-' + str(index), index, when, '1970-01-01T00:16:30+00:00',
                     mint, 'synthetic-creator', status))
    for index, mint in enumerate(research):
        con.execute('INSERT INTO research_launches(signature,creator,mint,block_time,updated_at) '
                    'VALUES(?,?,?,?,?)', ('research-' + str(index), 'creator', mint, when, 'synthetic'))
    for index, mint in enumerate(prices):
        con.execute('INSERT INTO paper_prices(mint,timestamp,price_usd,pair_address,liquidity_usd) '
                    'VALUES(?,?,?,?,?)', (mint, 1000 + index, .001, 'synthetic-pair', 20000))


def assert_partition(report, expected):
    launches, quoted, matched, orphans, rows = expected
    assert report['launches_observed'] == launches
    assert report['quotes_recorded'] == rows
    assert report['quoted_mints_total'] == quoted
    assert report['launches_with_quotes'] == matched
    assert report['quoted_mints_without_identified_launch'] == orphans
    assert matched + orphans == quoted
    assert 0 <= matched <= launches
    if launches:
        assert report['quote_coverage'] == pytest.approx(matched / launches)
        assert 0 <= report['quote_coverage'] <= 1
    else:
        assert report['quote_coverage'] is None
    assert report['quote_coverage_scope'] == 'identified_launch_mints'
    assert report['market_detection_coverage'] is None
    assert report['paper_only'] and not report['real_orders_enabled']
    json.dumps(report, allow_nan=False)


CASES = [
    ('empty', (), (), (), (0, 0, 0, 0, 0)),
    ('orphans_without_launches', (), (), ('x', 'y'), (0, 2, 0, 2, 2)),
    ('one_quoted', ('a',), (), ('a',), (1, 1, 1, 0, 1)),
    ('one_unquoted', ('a',), (), (), (1, 0, 0, 0, 0)),
    ('two_launches_one_quote', ('a', 'b'), (), ('a',), (2, 1, 1, 0, 1)),
    ('repeated_prices', ('a',), (), ('a', 'a', 'a'), (1, 1, 1, 0, 3)),
    ('many_orphans', ('a',), (), ('a', 'x', 'y', 'z'), (1, 4, 1, 3, 4)),
    ('partial_with_orphans_not_a_cap', ('a', 'b'), (), ('a', 'x', 'y'), (2, 3, 1, 2, 3)),
    ('union_overlap', ('a',), ('a',), ('a',), (1, 1, 1, 0, 1)),
    ('research_only', (), ('a', 'b'), ('b',), (2, 1, 1, 0, 1)),
    ('candidates_only', ('a', 'b'), (), ('a', 'b'), (2, 2, 2, 0, 2)),
    ('duplicate_creation_identities', ('a', 'a', 'b'), (), ('a',), (2, 1, 1, 0, 1)),
    ('duplicate_research_identities', (), ('a', 'a', 'b'), ('a', 'b'), (2, 2, 2, 0, 2)),
    ('mixed_union', ('a', 'b', 'a'), ('b', 'c', 'c'), ('a', 'c', 'x', 'x'), (3, 3, 2, 1, 4)),
    ('null_launch_keys', (None, 'a', None), ('a',), ('a', 'x'), (1, 2, 1, 1, 2)),
    ('orphans_only_with_known_launch', ('a',), (), ('x', 'y'), (1, 2, 0, 2, 2)),
]


@pytest.mark.parametrize('_name,launches,research,prices,expected', CASES, ids=[c[0] for c in CASES])
def test_distinct_mint_partitions(ledger, _name, launches, research, prices, expected):
    _, con = ledger
    populate(con, launches, research, prices)
    before = list(con.iterdump())
    report = pe.paper_report(con, 1100, 0)
    assert_partition(report, expected)
    assert list(con.iterdump()) == before  # Reporting cannot mutate any ledger/audit row.


def test_reproduced_orphans_do_not_inflate_coverage(ledger):
    _, con = ledger
    populate(con, ('known',), (), ('known', 'orphan-one', 'orphan-two'))
    report = pe.paper_report(con, 1100, 0)
    assert report['launches_with_quotes'] == 1
    assert report['quote_coverage'] == 1.0  # Reference incorrectly reports 3.0.


@pytest.mark.parametrize('absent', ['launch_candidates', 'research_launches', 'both'])
def test_each_launch_source_can_be_absent(ledger, absent):
    _, con = ledger
    populate(con, ('a',), ('b',), ('a', 'b', 'orphan'))
    for table in ('launch_candidates', 'research_launches'):
        if absent == table or absent == 'both':
            con.execute('DROP TABLE ' + table)
    report = pe.paper_report(con, 1100, 0)
    assert_partition(report, (0, 3, 0, 3, 3) if absent == 'both' else (1, 3, 1, 2, 3))


def test_unidentified_candidate_is_orphan_until_research_identifies_it(ledger):
    _, con = ledger
    populate(con, ('a',), (), ('a',), status='not_launch')
    assert_partition(pe.paper_report(con, 1100, 0), (0, 1, 0, 1, 1))
    populate(con, research=('a',))
    assert_partition(pe.paper_report(con, 1100, 0), (1, 1, 1, 0, 1))


def test_legacy_nullable_quote_mints_are_not_invented_identities(ledger):
    _, con = ledger
    # Only this synthetic legacy fixture removes the NOT NULL constraint.
    schema = con.execute("SELECT sql FROM sqlite_master WHERE name='paper_prices'").fetchone()[0]
    con.execute('DROP TABLE paper_prices')
    con.execute(schema.replace('mint TEXT NOT NULL', 'mint TEXT'))
    populate(con, (None, 'a'), (), (None, 'a', None, 'x'))
    assert_partition(pe.paper_report(con, 1100, 0), (1, 2, 1, 1, 4))


def test_active_research_schema_rejects_null_mint(ledger):
    _, con = ledger
    with pytest.raises(sqlite3.IntegrityError, match='NOT NULL'):
        populate(con, research=(None,))
    assert_partition(pe.paper_report(con, 1100, 0), (0, 0, 0, 0, 0))


@pytest.mark.parametrize('launch_time', [None, 980])
def test_multicreation_receipts_and_undated_observation(ledger, launch_time):
    path, con = ledger
    tx = transaction(instruction('a'), instruction('b'))
    tx['blockTime'] = launch_time
    store = TransactionRecovery(path)
    async def fetch(_signature):
        return tx
    asyncio.run(recover_transactions(events(dict(signature='synthetic-batch', slot=7,
        received_at=datetime.fromtimestamp(1001, timezone.utc))), store, fetch,
        clock=lambda: 1002, idle_seconds=.001))
    if launch_time is None:
        with patch.object(pe, 'fetch_quote', AsyncMock(return_value=(MarketQuote(20000, .001, 'pair'), 0))), \
                patch.object(pe, 'fetch_onchain_quote', AsyncMock(return_value=None)), \
                patch.object(pe.time, 'time', return_value=1100):
            asyncio.run(pe.collect_once(con, None, [], 1100, strategy_mode='shadow_final'))
        expected = (2, 2, 2, 0, 2)
    else:
        populate(con, prices=('a', 'orphan'))
        expected = (2, 2, 1, 1, 2)
    report = pe.paper_report(con, 1100, 0)
    assert_partition(report, expected)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    assert con.execute('SELECT realized_capital_sol FROM paper_portfolio').fetchone() == (10,)
    assert report['launch_time_diagnostics']['undated_mints'] == (2 if launch_time is None else 0)
    if launch_time is None:
        assert report['launch_time_diagnostics']['undated_mints_with_quotes'] == 2
        assert con.execute("SELECT COUNT(*) FROM paper_mint_audit WHERE report_json LIKE '%NON_DATE%'").fetchone()[0] == 2


@pytest.mark.parametrize('mask', range(16))
def test_bounded_partition_for_overlapping_sources_and_quotes(ledger, mask):
    _, con = ledger
    # Four independent identities may be known, quoted, both, or neither.
    # Fixed research overlap and duplicates exercise the union, not row counts.
    known = [mint for bit, mint in enumerate('abcd') if mask & (1 << bit)]
    quoted = list('acxy')
    populate(con, known + known, ['a', 'c'], quoted + quoted)
    expected_known = len(set(known) | {'a', 'c'})
    assert_partition(pe.paper_report(con, 1100, 0), (expected_known, 4, 2, 2, 8))


@pytest.mark.parametrize('fault', ['json', 'write', 'replace'])
def test_corrected_report_retains_atomic_publication(ledger, tmp_path, fault):
    _, con = ledger
    populate(con, ('a',), (), ('a', 'orphan'))
    output = tmp_path / 'report.json'
    previous = b'{"previous_valid":true}\n'
    output.write_bytes(previous)
    error = OSError('synthetic ' + fault)
    from contextlib import ExitStack
    with ExitStack() as stack:
        if fault == 'json':
            stack.enter_context(patch.object(pe.json, 'dumps', side_effect=error))
        elif fault == 'replace':
            stack.enter_context(patch.object(pe.os, 'replace', side_effect=error))
        else:
            original = Path.write_text
            def partial(path, text, *args, **kwargs):
                original(path, text[:12], *args, **kwargs)
                raise error
            stack.enter_context(patch.object(Path, 'write_text', partial))
        with pytest.raises(OSError) as raised:
            pe.paper_report(con, 1100, 0, output)
    assert raised.value is error
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob('.*.tmp'))
    pe.paper_report(con, 1100, 0, output)
    assert_partition(json.loads(output.read_text()), (1, 2, 1, 1, 2))
