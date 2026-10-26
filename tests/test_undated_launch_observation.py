"""Synthetic LaunchLab recovery/observation, without external services."""
import asyncio
from contextlib import closing
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from bot.analyser import paper_engine as pe, paper_trader as pt
from bot.analyser.multi_creator_research_engine import ensure_schema
from bot.database.db import Database
from bot.scanner.launch_detector import parse_launch_candidate
from bot.scanner.tx_recovery import TransactionRecovery, recover_transactions
from test_multiple_launches import transaction, instruction, events

NOW = 1100
RECEIVED = datetime.fromtimestamp(1001, timezone.utc)
QUOTE = pt.MarketQuote(20000, 1, 'pair', quote_source='dex_market')


@pytest.fixture
def db(tmp_path):
    path = tmp_path/'synthetic.db'
    Database(path)
    ensure_schema(path)
    with closing(sqlite3.connect(path, isolation_level=None, timeout=0)) as con:
        pt.setup(con)
        pe.ensure_signal_status_schema(con)
        pe.ensure_audit_schema(con)
        yield path, con


def recover(path, tx, signature='synthetic-tx', received=RECEIVED):
    store = TransactionRecovery(path)
    async def fetch(signature):
        return copy.deepcopy(tx)
    event = dict(signature=signature, slot=7, received_at=received)
    asyncio.run(recover_transactions(events(event), store, fetch, clock=lambda:1002,
                                    idle_seconds=.001))
    return store


def collect(con, now=NOW, quote=QUOTE, **kwargs):
    seen = []
    async def fetch(session, mint, *a, **k):
        seen.append(mint)
        return quote, 0
    with patch.object(pe, 'fetch_quote', fetch), \
            patch.object(pe, 'fetch_onchain_quote', return_value=None), \
            patch.object(pe.time, 'time', return_value=now):
        result = asyncio.run(pe.collect_once(con, None, [], now,
                            strategy_mode='shadow_final', **kwargs))
    return seen, result


def test_null_payload_recovery_storage_observation_audit_without_entry(db):
    path, con = db
    tx = transaction(instruction('mint-a'))
    tx['blockTime'] = None
    recover(path, tx)
    assert con.execute('SELECT mint,block_time FROM launch_candidates').fetchall() == [('mint-a', None)]
    assert pe.recent_candidates(con, NOW) == []
    collect(con)
    audit = con.execute('SELECT report_json FROM paper_mint_audit').fetchone()
    assert audit is not None
    report = json.loads(audit[0])
    assert report['signal_time'] is None
    assert report['age_seconds'] is None
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


@pytest.mark.parametrize('invalid', [0, -1, True, 1000.5, '1000', 999999999999999])
def test_invalid_parser_dates_remain_unknown(invalid):
    tx = transaction(instruction('mint-a'))
    tx['blockTime'] = invalid
    parsed = parse_launch_candidate(tx, RECEIVED)
    assert parsed['block_time'] is None
    assert parsed['detection_latency_ms'] is None
    assert parsed['launches'][0]['mint'] == 'mint-a'


def undated(*mints, when=None):
    tx = transaction(*(instruction(mint) for mint in mints))
    tx['blockTime'] = when
    return tx


def audit(con, mint='mint-a'):
    return json.loads(con.execute('SELECT report_json FROM paper_mint_audit WHERE mint=?', (mint,)).fetchone()[0])


@pytest.mark.parametrize('when', [None, 0, -1, True, False, 1000.0, 1000.5,
                                 '1000', {}, [], 1002, 999999999999999])
def test_unusable_dates_end_to_end_without_latency_trade_or_fake_signal(db, when):
    path, con = db
    tx = undated('mint-a', when=when)
    recover(path, tx)
    stored = con.execute('SELECT block_time,detection_latency_ms FROM launch_candidates').fetchone()
    assert stored == (None, None)
    assert con.execute('SELECT state FROM scanner_tx_recovery').fetchone() == ('done',)
    raw = json.loads(con.execute('SELECT payload FROM research_tx_cache').fetchone()[0])
    assert raw['blockTime'] == when
    with patch.object(pe, 'decide', side_effect=AssertionError('undated strategy call')), \
            patch.object(pe, 'build_features', side_effect=AssertionError('undated features call')):
        seen, _ = collect(con)
    assert seen == ['mint-a']
    report = audit(con)
    assert report['signal_time'] is None and report['age_seconds'] is None
    assert report['prior_launches'] is None and report['features'] is None
    assert report['launch_observation']['entry_allowed'] is False
    assert report['launch_observation']['reception_timestamp'] == 1001
    assert report['launch_observation']['quote_timestamp'] == NOW
    assert report['launch_observation']['queue_age_seconds'] == 99
    assert con.execute('SELECT COUNT(*) FROM paper_prices').fetchone() == (1,)
    for table in ('paper_trades', 'paper_decisions', 'paper_signal_status', 'paper_portfolio'):
        assert con.execute(f'SELECT COUNT(*) FROM {table}').fetchone() == (0,)


def test_multiple_null_creations_preserve_each_identity_and_pool(db):
    path, con = db
    recover(path, undated('mint-a', 'mint-b', 'mint-c'))
    pools = []
    async def onchain(session, mint, pool):
        pools.append((mint, pool))
        return pt.MarketQuote(0, 1, pool, quote_source='launchlab_curve', funding_usd=10)
    with patch.object(pe, 'fetch_onchain_quote', onchain), \
            patch.object(pe.time, 'time', return_value=NOW), \
            patch.object(pe, 'fetch_quote', side_effect=AssertionError('unexpected fallback')):
        asyncio.run(pe.collect_once(con, None, [], NOW))
    assert set(pools) == {(mint, 'pool-'+mint) for mint in ('mint-a', 'mint-b', 'mint-c')}
    for mint in ('mint-a', 'mint-b', 'mint-c'):
        report = audit(con, mint)
        assert report['creator_candidate'] == 'creator-'+mint
        assert report['pool_state'] == 'pool-'+mint
        assert report['quote_source'] == 'launchlab_curve'
        assert report['launch_observation']['identities'][0]['signature'] == 'synthetic-tx:'+mint
    assert con.execute('SELECT COUNT(*) FROM paper_prices').fetchone() == (3,)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


def test_replay_and_sqlite_restart_preserve_null_and_do_not_duplicate(db):
    path, con = db
    tx = undated('mint-a', 'mint-b')
    recover(path, tx)
    collect(con)
    before = con.execute('SELECT * FROM launch_candidates').fetchall()
    recover(path, tx)
    with closing(sqlite3.connect(path, isolation_level=None)) as restarted:
        collect(restarted)
        assert restarted.execute('SELECT * FROM launch_candidates').fetchall() == before
        assert restarted.execute('SELECT COUNT(*) FROM paper_prices').fetchone() == (2,)
        assert restarted.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM scanner_tx_recovery').fetchone() == (1,)


@pytest.mark.parametrize('reception', ['', 'malformed', '1970-01-01T00:16:41',
                                       '1970-01-01T00:00:00+00:00',
                                       '1970-01-01T00:30:00+00:00'])
def test_invalid_reception_is_diagnostic_only_not_silently_replaced(db, reception):
    path, con = db
    recover(path, undated('mint-a'))
    con.execute('UPDATE launch_candidates SET detected_at=?', (reception,))
    seen, _ = collect(con)
    assert seen == []
    report = audit(con)
    assert report['signal_time'] is None
    assert report['launch_observation']['reception_timestamp'] is None
    assert report['launch_observation']['status'] == 'NON_DATE_RECEPTION_INVALID'
    assert pe._scheduled_candidates(con, NOW+1, 7200, 10) == []


def test_missing_reception_column_is_visible_without_a_fake_time():
    with closing(sqlite3.connect(':memory:', isolation_level=None)) as con:
        pt.setup(con)
        con.execute('CREATE TABLE launch_candidates(mint,deployer_candidate,block_time,status)')
        con.execute("INSERT INTO launch_candidates VALUES('mint-a','creator',NULL,'creator_identified')")
        seen, _ = collect(con)
        assert seen == []
        assert audit(con)['launch_observation']['reception_timestamp'] is None


def test_undated_observation_window_uses_reception_and_eventually_stops(db):
    path, con = db
    recover(path, undated('mint-a'))
    assert collect(con, now=1101, max_age=100)[0] == ['mint-a']
    assert collect(con, now=1102, max_age=100)[0] == []
    assert audit(con)['launch_observation']['status'] == 'NON_DATE_RECEPTION_EXPIRED'
    assert pe._scheduled_candidates(con, 1103, 100, 10) == []
    with closing(sqlite3.connect(path, isolation_level=None)) as restarted:
        assert pe._scheduled_candidates(restarted, 1104, 100, 10) == []


@pytest.mark.parametrize('raw,stored', [(True, 1), (1000.0, 1000), ('1000', 1000)])
def test_old_stored_affinity_is_detected_using_original_payload(db, raw, stored):
    path, con = db
    recover(path, undated('mint-a', when=raw))
    con.execute('UPDATE launch_candidates SET block_time=?', (stored,))
    assert pe.recent_candidates(con, NOW, max_age=2000) == []
    collect(con, max_age=2000)
    assert audit(con)['signal_time'] is None
    assert pe.prior_creator_launches(con, 'creator-mint-a', 1200) == 0
    assert con.execute('SELECT block_time FROM launch_candidates').fetchone() == (stored,)


def test_unknown_launches_do_not_inflate_creator_history(db):
    path, con = db
    tx = transaction(instruction('dated', creator='creator'))
    tx['blockTime'] = 1000
    recover(path, tx, 'dated-signature')
    tx = transaction(instruction('unknown', creator='creator'))
    tx['blockTime'] = None
    recover(path, tx, 'unknown-signature')
    assert pe.prior_creator_launches(con, 'creator', 1100) == 1
    assert pe.prior_creator_launches(con, 'creator', None) is None


def test_later_cached_time_is_not_reconciled_into_candidate_or_receipt(db):
    path, con = db
    tx = undated('mint-a')
    recover(path, tx)
    receipt = con.execute('SELECT * FROM scanner_tx_recovery').fetchall()
    tx['blockTime'] = 1000
    con.execute('UPDATE research_tx_cache SET payload=?', (json.dumps(tx),))
    assert pe.recent_candidates(con, NOW) == []
    collect(con)
    assert audit(con)['signal_time'] is None
    assert con.execute('SELECT block_time FROM launch_candidates').fetchone() == (None,)
    assert con.execute('SELECT * FROM scanner_tx_recovery').fetchall() == receipt


def test_other_transaction_date_cannot_date_current_creation(db):
    path, con = db
    recover(path, undated('mint-a'))
    tx = undated('other', when=1000)
    recover(path, tx, 'different-transaction')
    collect(con)
    assert audit(con)['signal_time'] is None
    assert ('mint-a', None) in con.execute('SELECT mint,block_time FROM launch_candidates').fetchall()


def test_identical_mint_duplicates_are_one_observation(db):
    path, con = db
    recover(path, undated('mint-a', 'mint-a'))
    recover(path, undated('mint-a'), 'another-signature')
    seen, _ = collect(con)
    assert seen == ['mint-a']
    assert len(audit(con)['launch_observation']['identities']) == 2
    assert con.execute('SELECT COUNT(*) FROM paper_prices').fetchone() == (1,)


def test_metadata_conflict_is_visible_without_mixing_or_quoting(db):
    path, con = db
    recover(path, undated('mint-a'))
    tx = transaction(instruction('mint-a', creator='different', pool='different-pool'))
    tx['blockTime'] = None
    recover(path, tx, 'another-signature')
    assert collect(con)[0] == []
    report = audit(con)
    assert report['launch_observation']['status'] == 'NON_DATE_METADATA_CONFLICT'
    assert len(report['launch_observation']['identities']) == 2


@pytest.mark.parametrize('kind', ['swap', 'spl'])
def test_non_creations_do_not_become_undated_candidates(db, kind):
    path, con = db
    ix = instruction('swap-mint', name='sell_exact_in') if kind == 'swap' else dict(
        program='spl-token', programId='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
        parsed=dict(type='initializeMint2', info=dict(mint='spl-only')))
    tx = transaction(ix)
    tx['blockTime'] = None
    recover(path, tx)
    assert collect(con)[0] == []
    assert con.execute('SELECT COUNT(*) FROM launch_candidates').fetchone() == (0,)


def test_fifo_bounded_cycles_include_dated_undated_and_new_arrivals(db):
    path, con = db
    recover(path, undated(*(f'u{i:02}' for i in range(12))))
    recover(path, undated(*(f'd{i:02}' for i in range(12)), when=1000), 'dated')
    first = collect(con, max_candidates=10, entry_guard=lambda:False)[0]
    recover(path, undated('new'), 'new-signature')
    second = collect(con, now=1101, max_candidates=10, entry_guard=lambda:False)[0]
    third = collect(con, now=1102, max_candidates=10, entry_guard=lambda:False)[0]
    fourth = collect(con, now=1103, max_candidates=10, entry_guard=lambda:False)[0]
    assert (len(first), len(second), len(third), len(fourth)) == (10, 10, 10, 10)
    assert {f'u{i:02}' for i in range(12)} | {f'd{i:02}' for i in range(12)} | {'new'} <= set(first+second+third+fourth)
    assert 'new' not in second[:4]  # Arrivals do not jump the existing waiters.


@pytest.mark.parametrize('exit_price,expected_pnl', [(1.2, .18), (.8, -.22)])
def test_open_position_priority_tp_sl_and_no_undated_trade(db, exit_price, expected_pnl):
    path, con = db
    recover(path, undated('open', when=1000), 'dated')
    collect(con)
    recover(path, undated(*(f'u{i:02}' for i in range(25))))
    seen, _ = collect(con, now=1101, max_candidates=2, entry_guard=lambda:False,
                      quote=pt.MarketQuote(20000, exit_price, 'pair', quote_source='dex_market'))
    assert seen[0] == 'open'
    assert len(seen) == 2
    assert con.execute('SELECT status,pnl_sol FROM paper_trades').fetchone()[0] == 'closed'
    assert con.execute('SELECT pnl_sol FROM paper_trades').fetchone()[0] == pytest.approx(expected_pnl)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (1,)
    assert pt.paper_capital(con)[0] == 10


def test_one_slot_persisted_rotation_cannot_starve_open_positions(db):
    path, con = db
    recover(path, undated('open', when=1000), 'dated')
    collect(con)
    recover(path, undated('mint-a', 'mint-b'))
    seen = [collect(con, now=1101, max_candidates=1)[0]]
    with closing(sqlite3.connect(path, isolation_level=None)) as restarted:
        seen.append(collect(restarted, now=1102, max_candidates=1)[0])
        seen.append(collect(restarted, now=1103, max_candidates=1)[0])
        seen.append(collect(restarted, now=1104, max_candidates=1)[0])
    assert {row[0] for row in seen} == {'open', 'mint-a', 'mint-b'}
    assert all(len(row) == 1 for row in seen)


def test_quotes_keep_original_conflict_and_replay_policy(db):
    path, con = db
    recover(path, undated('mint-a'))
    collect(con)
    before = con.execute('SELECT * FROM paper_prices').fetchall()
    collect(con)
    assert con.execute('SELECT * FROM paper_prices').fetchall() == before
    collect(con, quote=pt.MarketQuote(20000, 2, 'pair', quote_source='dex_market'))
    assert con.execute('SELECT * FROM paper_prices').fetchall() == before
    assert con.execute('SELECT rejected_observations FROM paper_quote_conflicts').fetchone() == (1,)
    assert audit(con)['prix_usd'] == 1


def test_undated_observation_does_not_call_financial_or_strategic_guards(db):
    path, con = db
    recover(path, undated('mint-a'))
    pt.ensure_paper_portfolio(con, 10, 1000)
    before = con.execute('SELECT * FROM paper_portfolio').fetchall()
    with patch.object(pe, 'entry_allowed', side_effect=AssertionError('no entry evaluation')), \
            patch.object(pe, 'record_quote', wraps=pe.record_quote) as called:
        collect(con, entry_guard=lambda:False)
    assert called.call_args.args[3] is None
    assert called.call_args.args[6] is None
    assert called.call_args.kwargs['allow_entry'] is False
    assert con.execute('SELECT * FROM paper_portfolio').fetchall() == before


def test_report_separates_dated_and_undated_from_permission(db):
    path, con = db
    recover(path, undated('mint-a'))
    recover(path, undated('dated', when=1000), 'dated-tx')
    collect(con, entry_guard=lambda:False)
    report = pe.paper_report(con, NOW, 0)
    assert report['launch_time_diagnostics']['dated_mints'] == 1
    assert report['launch_time_diagnostics']['undated_mints'] == 1
    assert report['launch_time_diagnostics']['undated_mints_with_quotes'] == 1
    assert report['launch_time_diagnostics']['undated_mints_excluded_from_new_entries'] == 1
    assert report['launch_time_diagnostics']['undated_status_counts'] == {'NON_DATE_PRIX_OBSERVE':1}
    assert report['open_paper_positions'] == 0


def test_sqlite_audit_error_rolls_back_observation_and_never_creates_signal(db):
    path, con = db
    recover(path, undated('mint-a'))
    con.execute("CREATE TRIGGER synthetic_fail BEFORE INSERT ON paper_mint_audit BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic'):
        collect(con)
    for table in ('paper_prices', 'paper_trades', 'paper_decisions', 'paper_mint_audit'):
        assert con.execute(f'SELECT COUNT(*) FROM {table}').fetchone() == (0,)


def test_null_multi_recovery_atomic_rollback_on_second_creation(db):
    path, con = db
    tx = undated('mint-a', 'mint-b')
    store = TransactionRecovery(path)
    store.enqueue(dict(signature='synthetic', slot=7, received_at=RECEIVED), 1002)
    job = store.claim_due(1002)
    con.execute("CREATE TRIGGER synthetic_fail BEFORE INSERT ON launch_candidates WHEN NEW.mint='mint-b' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic'):
        store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 1002)
    assert con.execute('SELECT COUNT(*) FROM launch_candidates').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM research_tx_cache').fetchone() == (0,)
    assert con.execute('SELECT state FROM scanner_tx_recovery').fetchone() == ('pending',)
    con.execute('DROP TRIGGER synthetic_fail')
    assert TransactionRecovery(path).complete(job, tx, parse_launch_candidate(tx, RECEIVED), 1003) == 2
    assert con.execute('SELECT state FROM scanner_tx_recovery').fetchone() == ('done',)


def test_undated_candidates_never_create_exported_block_time(db, tmp_path):
    from bot.analyser.research_pipeline import export_dataset
    path, con = db
    recover(path, undated('mint-a', 'mint-b'))
    collect(con)
    assert export_dataset(path, tmp_path/'dataset.csv') == (0, 0)
    assert (tmp_path/'dataset.csv').read_text().splitlines() == ['block_time,signature,creator,mint,pool_state,prior_launches']


@pytest.mark.parametrize('strategy_mode', ['shadow_final', 'validated'])
def test_mixed_dated_and_undated_same_mint_never_borrow_metadata_or_date(db, strategy_mode):
    path, con = db
    recover(path, undated('mint-a', when=1000), 'dated-signature')
    tx = transaction(instruction('mint-a', creator='other-creator', pool='other-pool'))
    tx['blockTime'] = None
    recover(path, tx, 'undated-signature')
    pools = []
    async def onchain(session, mint, pool):
        pools.append(pool)
        return QUOTE
    with patch.object(pe, 'fetch_onchain_quote', onchain), patch.object(pe.time, 'time', return_value=NOW):
        asyncio.run(pe.collect_once(con, None, [], NOW, strategy_mode=strategy_mode))
    assert pools == ['pool-mint-a']
    report = audit(con)
    assert report['creator_candidate'] == 'creator-mint-a'
    assert report['signal_time'] == 1000
    assert report['undated_identities'][0]['block_time'] is None
    assert report['undated_identities'][0]['signature'] == 'undated-signature:mint-a'
    diagnostics = pe.paper_report(con, NOW, 0)['launch_time_diagnostics']
    assert diagnostics['dated_candidate_rows'] == diagnostics['undated_candidate_rows'] == 1
    assert diagnostics['undated_mints'] == 1 and diagnostics['undated_only_mints'] == 0


@pytest.mark.parametrize('wait,quote', [(0, None), (60, None), (60, QUOTE)])
def test_missing_quote_or_cooldown_never_creates_price_or_entry(db, wait, quote):
    path, con = db
    recover(path, undated('mint-a'))
    async def fetch(*a, **k):
        return quote, wait
    with patch.object(pe, 'fetch_onchain_quote', return_value=None), \
            patch.object(pe, 'fetch_quote', fetch), patch.object(pe.time, 'time', return_value=NOW):
        _, cooldown, _ = asyncio.run(pe.collect_once(con, None, [], NOW))
    assert cooldown == wait
    assert audit(con)['prix_usd'] is None
    assert con.execute('SELECT COUNT(*) FROM paper_prices').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


@pytest.mark.parametrize('price', [0, -1, float('inf'), float('nan')])
def test_invalid_new_observation_price_cannot_create_financial_data(db, price):
    path, con = db
    recover(path, undated('mint-a'))
    with pytest.raises(ValueError):
        collect(con, quote=pt.MarketQuote(20000, price, 'pair', quote_source='dex_market'))
    for table in ('paper_prices', 'paper_trades', 'paper_decisions'):
        assert con.execute(f'SELECT COUNT(*) FROM {table}').fetchone() == (0,)


def test_observation_window_is_rechecked_after_quote_await(db):
    path, con = db
    recover(path, undated('mint-a'))
    async def fetch(*a, **k):
        await asyncio.sleep(0)
        return QUOTE, 0
    with patch.object(pe, 'fetch_onchain_quote', return_value=None), \
            patch.object(pe, 'fetch_quote', fetch), patch.object(pe.time, 'time', return_value=1102):
        asyncio.run(pe.collect_once(con, None, [], 1101, max_age=100))
    assert audit(con)['launch_observation']['status'] == 'NON_DATE_RECEPTION_EXPIRED'
    assert con.execute('SELECT COUNT(*) FROM paper_prices').fetchone() == (0,)


def test_scanner_integrity_gate_remains_active_for_dated_entries_with_undated_observations(db):
    from types import SimpleNamespace
    path, con = db
    recover(path, undated('unknown'))
    recover(path, undated('dated', when=1000), 'dated')
    con.execute('CREATE TABLE scanner_backfill_state(program_id PRIMARY KEY,history_status,reason,ws_state,checked_at,cursor_signature,cursor_slot)')
    con.execute("INSERT INTO scanner_backfill_state VALUES(?,'degraded','synthetic','subscribed',1099,'anchor',7)",
                (pe.RAYDIUM_LAUNCHPAD_PROGRAM_ID,))
    with patch.object(pe.time, 'time', return_value=1098):
        guard = pe._ScannerEntryGuard(path, SimpleNamespace(done=lambda:False, cancelling=lambda:0))
    seen, _ = collect(con, entry_guard=guard)
    assert set(seen) == {'unknown', 'dated'}
    assert con.execute('SELECT enter,entry_allowed FROM paper_decisions').fetchone() == (1, 0)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


def test_loss_history_integrity_still_blocks_dated_entry_while_undated_is_observable(db):
    path, con = db
    model = pe.shadow_baseline_model()
    pt.record_quote(con, 'old', 'creator', 1000, 1065, QUOTE, model)
    pt.record_quote(con, 'old', 'creator', 1000, 1090,
                    pt.MarketQuote(20000, .8, 'pair', quote_source='dex_market'), model)
    con.execute('UPDATE paper_trades SET exit_time=NULL')
    before = con.execute('SELECT * FROM paper_trades').fetchall(), pt.paper_capital(con)
    recover(path, undated('unknown'))
    recover(path, undated('dated', when=1000), 'dated')
    collect(con)
    assert con.execute("SELECT entry_allowed FROM paper_decisions WHERE mint='dated'").fetchone() == (0,)
    assert (con.execute('SELECT * FROM paper_trades').fetchall(), pt.paper_capital(con)) == before
    assert audit(con, 'unknown')['signal_time'] is None


def test_sqlite_lock_is_not_a_positive_observation_or_entry(db):
    path, con = db
    recover(path, undated('mint-a'))
    # ensure_schema uses WAL; EXCLUSIVE is a writer lock, readable by others.
    with closing(sqlite3.connect(path, isolation_level=None, timeout=0)) as other:
        other.execute('BEGIN EXCLUSIVE')
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                collect(con)
        finally:
            other.rollback()
    assert con.execute('SELECT COUNT(*) FROM paper_mint_audit').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)


def test_missing_block_time_key_is_not_replaced_by_reception(db):
    path, con = db
    tx = undated('mint-a')
    del tx['blockTime']
    recover(path, tx)
    collect(con)
    assert audit(con)['signal_time'] is None
    assert con.execute('SELECT block_time FROM launch_candidates').fetchone() == (None,)
    assert 'blockTime' not in json.loads(con.execute('SELECT payload FROM research_tx_cache').fetchone()[0])


def test_null_outer_and_inner_creations_are_both_observed(db):
    path, con = db
    tx = undated('outer')
    tx['meta']['innerInstructions'] = [dict(index=0, instructions=[instruction('inner')])]
    recover(path, tx)
    assert set(collect(con)[0]) == {'outer', 'inner'}
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    assert audit(con, 'inner')['creator_candidate'] == 'creator-inner'


def test_repeated_mint_cannot_extend_window_with_a_later_reception(db):
    path, con = db
    recover(path, undated('mint-a'))
    recover(path, undated('mint-a'), 'later-signature', datetime.fromtimestamp(1100, timezone.utc))
    assert collect(con, now=1102, max_age=100)[0] == []
    report = audit(con)['launch_observation']
    assert report['status'] == 'NON_DATE_RECEPTION_EXPIRED'
    assert report['reception_timestamp'] == 1001
    assert report['reception_signature'] == 'synthetic-tx:mint-a'


def test_date_source_change_during_quote_cannot_feed_strategy_or_entry(db):
    path, con = db
    recover(path, undated('mint-a', when=1000))
    async def fetch(*a, **k):
        await asyncio.sleep(0)
        con.execute('UPDATE research_tx_cache SET payload=?', (json.dumps(undated('mint-a')),))
        return QUOTE, 0
    with patch.object(pe, 'fetch_onchain_quote', return_value=None), \
            patch.object(pe, 'fetch_quote', fetch), patch.object(pe.time, 'time', return_value=NOW), \
            patch.object(pe, 'build_features', side_effect=AssertionError('stale launch time')):
        asyncio.run(pe.collect_once(con, None, [], NOW, strategy_mode='shadow_final'))
    assert audit(con)['signal_time'] is None
    assert audit(con)['launch_observation']['entry_allowed'] is False
    assert con.execute('SELECT COUNT(*) FROM paper_trades').fetchone() == (0,)
    assert con.execute('SELECT COUNT(*) FROM paper_decisions').fetchone() == (0,)
