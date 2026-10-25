"""Multiple LaunchLab creations: synthetic instructions, SQLite and PAPER only."""
import asyncio
from contextlib import closing
import copy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from bot.database.db import Database
from bot.scanner import transaction_parser as tp
from bot.scanner.launch_detector import parse_launch_candidate
from bot.scanner.tx_recovery import TransactionRecovery, recover_transactions
from bot.analyser.multi_creator_research_engine import ensure_schema
from bot.analyser import paper_engine as pe
from bot.analyser import paper_trader as pt


RECEIVED = datetime.fromtimestamp(101, timezone.utc)
EVENT = dict(signature='synthetic-tx', slot=1, received_at=RECEIVED)
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def b58(data):
    number = int.from_bytes(data, 'big')
    result = ''
    while number:
        number, digit = divmod(number, 58)
        result = ALPHABET[digit] + result
    return '1' * (len(data) - len(data.lstrip(b'\0'))) + result


def instruction(mint='mint-a', creator=None, payer=None, pool=None, name='initialize_v2'):
    return dict(programId=tp.RAYDIUM_LAUNCHPAD_PROGRAM_ID,
                accounts=[payer or 'payer-' + mint, creator or 'creator-' + mint,
                          'account2', 'account3', 'account4', pool or 'pool-' + mint, mint],
                data=b58(hashlib.sha256(('global:' + name).encode()).digest()[:8] + b'fixture'))


def transaction(*instructions, inner=None):
    return dict(blockTime=100,
                transaction=dict(message=dict(accountKeys=[dict(pubkey='fee-payer', signer=True)],
                                              instructions=list(instructions))),
                meta=dict(err=None, innerInstructions=inner or []))


async def events(*items):
    for item in items:
        yield item


class MultipleLaunchParserTests(unittest.TestCase):
    def test_single_creation_preserves_all_legacy_fields(self):
        tx = transaction(instruction())
        parsed = parse_launch_candidate(tx, RECEIVED)
        self.assertEqual({k: v for k, v in parsed.items() if k != 'launches'}, dict(
            block_time=100, mints=['mint-a'], creator='creator-mint-a',
            deployer_candidate='creator-mint-a', fee_payer='fee-payer', signers=['fee-payer'],
            pool_state='pool-mint-a', detection_latency_ms=1000, status='creator_identified'))
        self.assertEqual(parsed['launches'], [dict(mint='mint-a', creator='creator-mint-a',
                                                  payer='payer-mint-a', pool_state='pool-mint-a')])

    def test_two_creations_have_independent_metadata(self):
        parsed = parse_launch_candidate(transaction(instruction('a'), instruction('b')), RECEIVED)
        self.assertEqual(parsed['launches'], [dict(mint=m, creator='creator-' + m,
                                                   payer='payer-' + m, pool_state='pool-' + m)
                                              for m in ('a', 'b')])
        self.assertEqual(parsed['mints'], ['a'])  # Explicit legacy singular view.
        self.assertEqual(parsed['creator'], 'creator-a')

    def test_three_creations_preserve_instruction_order(self):
        self.assertEqual([x['mint'] for x in tp.find_raydium_launches(transaction(
            instruction('c'), instruction('a'), instruction('b')))], ['c', 'a', 'b'])

    def test_mixed_outer_inner_invocation_order_and_legacy_order(self):
        wrapper = dict(programId='synthetic-wrapper', accounts=[])
        tx = transaction(wrapper, instruction('outer'), inner=[
            dict(index=0, instructions=[instruction('inner-first'), instruction('inner-second')]),
            dict(index=1, instructions=[instruction('inner-last')])])
        self.assertEqual([x['mint'] for x in tp.find_raydium_launches(tx)],
                         ['inner-first', 'inner-second', 'outer', 'inner-last'])
        # Historical callers deliberately retain external-first singular order.
        self.assertEqual(tp.find_raydium_launch(tx)['mint'], 'outer')
        self.assertEqual(parse_launch_candidate(tx, RECEIVED)['mints'], ['outer'])

    def test_inner_groups_use_parent_index_not_group_arrival_order(self):
        wrapper = dict(programId='synthetic-wrapper', accounts=[])
        tx = transaction(wrapper, wrapper, inner=[
            dict(index=1, instructions=[instruction('second')]),
            dict(index=0, instructions=[instruction('first')])])
        self.assertEqual([x['mint'] for x in tp.find_raydium_launches(tx)], ['first', 'second'])

    def test_create_and_swap_no_false_creation(self):
        tx = transaction(instruction('a'), instruction('swap', name='sell_exact_in'), instruction('b'))
        self.assertEqual([x['mint'] for x in tp.find_raydium_launches(tx)], ['a', 'b'])

    def test_initialize_mint_alone_not_a_launch(self):
        spl = dict(program='spl-token', programId='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
                   parsed=dict(type='initializeMint2', info=dict(mint='spl-only')))
        self.assertEqual(parse_launch_candidate(transaction(spl), RECEIVED)['launches'], [])
        self.assertEqual(tp.find_initialized_mints(transaction(spl)), ['spl-only'])

    def test_identical_mint_repeated_inner_and_outer_deduplicated(self):
        ix = instruction()
        tx = transaction(ix, inner=[dict(index=0, instructions=[copy.deepcopy(ix)])])
        self.assertEqual(len(tp.find_raydium_launches(tx)), 1)

    def test_conflicting_creator_payer_or_pool_rejects_entire_batch(self):
        for key in ('creator', 'payer', 'pool'):
            with self.subTest(field=key):
                with self.assertRaises(tp.ConflictingLaunchMetadata):
                    parse_launch_candidate(transaction(instruction(), instruction(**{key: 'different'})), RECEIVED)

    def test_verified_discriminators_and_parsed_fallback_preserved(self):
        for discriminator in (bytes([67, 153, 175, 39, 218, 16, 38, 32]),
                              bytes([37, 190, 126, 222, 44, 154, 171, 17])):
            with self.subTest(discriminator=discriminator):
                ix = instruction()
                ix['data'] = b58(discriminator + b'fixture')
                self.assertEqual(len(tp.find_raydium_launches(transaction(ix))), 1)
        ix = instruction()
        del ix['data']
        ix['parsed'] = dict(type='initialize_v2')
        self.assertEqual(len(tp.find_raydium_launches(transaction(ix))), 1)

    def test_invalid_discriminator_program_accounts_and_failed_tx(self):
        for alteration in (dict(data='0-invalid-base58'), dict(data=b58(b'12345678')),
                           dict(programId='other-program'), dict(accounts=['too-short'])):
            with self.subTest(alteration=alteration):
                ix = instruction()
                ix.update(alteration)
                self.assertEqual(tp.find_raydium_launches(transaction(ix)), [])
        tx = transaction(instruction())
        tx['meta']['err'] = dict(InstructionError=[0, 'synthetic'])
        self.assertEqual(tp.find_raydium_launches(tx), [])

    def test_historical_inner_only_shape_still_supported(self):
        tx = transaction(inner=[dict(index=0, instructions=[instruction()])])
        self.assertEqual(tp.find_raydium_launches(tx), [tp.find_raydium_launch(tx)])


class MultipleLaunchRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'synthetic.db'
        Database(self.path)
        ensure_schema(self.path)
        self.store = TransactionRecovery(self.path, retry_base=0)

    def sql(self, query, params=()):
        with closing(sqlite3.connect(self.path, isolation_level=None)) as con:
            return con.execute(query, params).fetchall()

    def job(self):
        self.store.enqueue(EVENT, 100)
        return self.store.claim_due(100)

    async def recover(self, tx, items=(EVENT,), clock=lambda: 1000):
        fetch = AsyncMock(return_value=tx)
        await asyncio.wait_for(recover_transactions(events(*items), self.store, fetch,
                                                    clock=clock, idle_seconds=.001), 3)
        return fetch

    def counts(self):
        return tuple(self.sql('SELECT COUNT(*) FROM ' + name)[0][0]
                     for name in ('research_tx_cache', 'launch_candidates'))

    async def test_two_creations_stored_with_own_creator_and_pool(self):
        await self.recover(transaction(instruction('a'), instruction('b')))
        self.assertEqual(self.sql('SELECT mint,deployer_candidate,pool_state FROM launch_candidates ORDER BY id'),
                         [('a', 'creator-a', 'pool-a'), ('b', 'creator-b', 'pool-b')])
        self.assertEqual(self.sql('SELECT state FROM scanner_tx_recovery'), [('done',)])

    async def test_three_creations_stored_in_order(self):
        await self.recover(transaction(instruction('c'), instruction('a'), instruction('b')))
        self.assertEqual(self.sql('SELECT mint FROM launch_candidates ORDER BY id'), [('c',), ('a',), ('b',)])
        self.assertEqual(self.counts(), (1, 3))

    async def test_mixed_outer_inner_candidates_stored_in_invocation_order(self):
        wrapper = dict(programId='synthetic-wrapper', accounts=[])
        await self.recover(transaction(wrapper, instruction('outer'), inner=[
            dict(index=0, instructions=[instruction('inner')])]))
        self.assertEqual(self.sql('SELECT mint,deployer_candidate,pool_state FROM launch_candidates ORDER BY id'),
                         [('inner', 'creator-inner', 'pool-inner'), ('outer', 'creator-outer', 'pool-outer')])

    async def test_duplicate_instructions_one_candidate_and_id(self):
        await self.recover(transaction(instruction(), instruction()))
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.sql('SELECT signature FROM launch_candidates'), [('synthetic-tx:mint-a',)])

    async def test_each_payer_remains_recoverable_from_persistent_transaction_cache(self):
        import json
        tx = transaction(instruction('a'), instruction('b'))
        await self.recover(tx)
        payload = json.loads(self.sql('SELECT payload FROM research_tx_cache')[0][0])
        self.assertEqual([(x['mint'], x['payer']) for x in tp.find_raydium_launches(payload)],
                         [('a', 'payer-a'), ('b', 'payer-b')])

    async def test_conflict_exhausts_budget_without_cache_candidates_or_done(self):
        self.store = TransactionRecovery(self.path, max_attempts=2, retry_base=0)
        fetch = await self.recover(transaction(instruction(), instruction(creator='conflicting')))
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.sql('SELECT state,attempts,last_error FROM scanner_tx_recovery'),
                         [('exhausted', 2, 'ConflictingLaunchMetadata')])

    async def test_sqlite_error_on_second_insert_rolls_back_all_then_retries(self):
        tx = transaction(instruction('a'), instruction('b'))
        job = self.job()
        before = self.sql('SELECT * FROM scanner_tx_recovery')
        self.sql("CREATE TRIGGER fail_second BEFORE INSERT ON launch_candidates WHEN NEW.mint='b' "
                 "BEGIN SELECT RAISE(ABORT,'synthetic second insert'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 101)
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.sql('SELECT * FROM scanner_tx_recovery'), before)
        self.sql('DROP TRIGGER fail_second')
        self.assertEqual(self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 102), 2)
        self.assertEqual(self.counts(), (1, 2))

    async def test_ignored_second_insert_is_not_marked_done(self):
        tx = transaction(instruction('a'), instruction('b'))
        job = self.job()
        self.sql("CREATE TRIGGER ignore_second BEFORE INSERT ON launch_candidates WHEN NEW.mint='b' "
                 'BEGIN SELECT RAISE(IGNORE); END')
        with self.assertRaises(RuntimeError):
            self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 101)
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.sql('SELECT state FROM scanner_tx_recovery'), [('pending',)])

    async def test_existing_cache_restored_after_failed_batch(self):
        self.sql("INSERT INTO research_tx_cache(signature,payload,fetched_ok,updated_at) VALUES(?, ?, 1, 'old')",
                 (EVENT['signature'], '{"historical":"synthetic"}'))
        cache = self.sql('SELECT * FROM research_tx_cache')
        tx = transaction(instruction('a'), instruction('b'))
        job = self.job()
        self.sql("CREATE TRIGGER fail_second BEFORE INSERT ON launch_candidates WHEN NEW.mint='b' "
                 "BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 101)
        self.assertEqual(self.sql('SELECT * FROM research_tx_cache'), cache)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM launch_candidates'), [(0,)])

    async def test_replay_after_restart_does_not_fetch_or_insert(self):
        tx = transaction(instruction('a'), instruction('b'), instruction('c'))
        await self.recover(tx)
        before = self.sql('SELECT * FROM launch_candidates ORDER BY id')
        self.store = TransactionRecovery(self.path, retry_base=0)
        fetch = await self.recover(tx, items=(EVENT, EVENT))
        fetch.assert_not_awaited()
        self.assertEqual(self.sql('SELECT * FROM launch_candidates ORDER BY id'), before)
        self.assertEqual(self.counts(), (1, 3))

    async def test_interruption_then_restart_recovers_all_creations(self):
        started = asyncio.Event()

        async def unavailable(_signature):
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(recover_transactions(events(EVENT), self.store, unavailable,
                                                        clock=lambda: 100, idle_seconds=.001))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.counts(), (0, 0))
        self.store = TransactionRecovery(self.path, retry_base=0)
        await self.recover(transaction(instruction('a'), instruction('b')), items=())
        self.assertEqual(self.counts(), (1, 2))
        self.assertEqual(self.sql('SELECT state,attempts FROM scanner_tx_recovery'), [('done', 2)])

    async def test_legacy_parsed_result_reparsed_without_scalar_metadata_spread(self):
        tx = transaction(instruction('a'), instruction('b'))
        parsed = parse_launch_candidate(tx, RECEIVED)
        del parsed['launches']
        self.assertEqual(self.store.complete(self.job(), tx, parsed, 101), 2)
        self.assertEqual(self.sql('SELECT mint,deployer_candidate FROM launch_candidates ORDER BY id'),
                         [('a', 'creator-a'), ('b', 'creator-b')])

    async def test_ids_independent_of_creation_count_and_order(self):
        tx = transaction(instruction('a'))
        job = self.job()
        self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 101)
        first_id = self.sql("SELECT signature FROM launch_candidates WHERE mint='a'")[0][0]
        # Artificial replay of an expanded fixture, not a claim that a real
        # immutable chain transaction can acquire instructions after confirmation.
        self.sql("UPDATE scanner_tx_recovery SET state='pending'")
        expanded = transaction(instruction('b'), instruction('a'))
        self.store.complete(job, expanded, parse_launch_candidate(expanded, RECEIVED), 102)
        self.assertEqual(self.sql("SELECT signature FROM launch_candidates WHERE mint='a'"), [(first_id,)])
        self.assertEqual(self.counts(), (1, 2))

    async def test_historical_raw_singleton_identity_reused(self):
        tx = transaction(instruction('a'))
        job = self.job()
        self.sql('''INSERT INTO launch_candidates(protocol,signature,slot,block_time,detected_at,
                    mint,deployer_candidate,status,pool_state) VALUES(?,?,?,?,?,?,?,?,?)''',
                 ('raydium_launchpad', EVENT['signature'], 1, 100, RECEIVED.isoformat(),
                  'a', 'creator-a', 'creator_identified', 'pool-a'))
        expanded = transaction(instruction('a'), instruction('b'))
        self.assertEqual(self.store.complete(job, expanded, parse_launch_candidate(expanded, RECEIVED), 101), 1)
        self.assertEqual(self.sql('SELECT signature FROM launch_candidates ORDER BY id'),
                         [('synthetic-tx',), ('synthetic-tx:b',)])

    async def test_conflicting_existing_identity_rolls_back_cache(self):
        tx = transaction(instruction('a'))
        job = self.job()
        self.sql('''INSERT INTO launch_candidates(protocol,signature,slot,detected_at,
                    mint,deployer_candidate,status,pool_state) VALUES(?,?,?,?,?,?,?,?)''',
                 ('raydium_launchpad', 'synthetic-tx:a', 1, RECEIVED.isoformat(),
                  'a', 'wrong-creator', 'creator_identified', 'pool-a'))
        with self.assertRaises(tp.ConflictingLaunchMetadata):
            self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 101)
        self.assertEqual(self.counts(), (0, 1))
        self.assertEqual(self.sql('SELECT state FROM scanner_tx_recovery'), [('pending',)])

    async def test_candidate_reuse_validates_status_and_transaction_context(self):
        tx = transaction(instruction('a'))
        job = self.job()
        self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 101)
        for field, value in (('status', 'not_launch'), ('block_time', 999), ('protocol', 'other')):
            with self.subTest(field=field):
                self.sql("UPDATE scanner_tx_recovery SET state='pending'")
                self.sql("UPDATE launch_candidates SET status='creator_identified',block_time=100,protocol='raydium_launchpad'")
                self.sql('UPDATE launch_candidates SET ' + field + '=?', (value,))
                with self.assertRaises(tp.ConflictingLaunchMetadata):
                    self.store.complete(job, tx, parse_launch_candidate(tx, RECEIVED), 102)
                self.assertEqual(self.sql('SELECT state FROM scanner_tx_recovery'), [('pending',)])

    async def test_multi_creation_rotation_and_no_duplicate_paper_pnl(self):
        mints = [f'mint-{i:02}' for i in range(12)]
        tx = transaction(*(instruction(mint) for mint in mints))
        await self.recover(tx)
        with closing(sqlite3.connect(self.path, isolation_level=None)) as con:
            pt.setup(con)
            pe.ensure_signal_status_schema(con)
            pe.ensure_audit_schema(con)
            seen = []
            price = 1

            async def fetch(_session, mint, **_kwargs):
                seen.append(mint)
                return pt.MarketQuote(20000, price, 'pair-' + mint, quote_source='dex_market'), 0

            model = dict(creator_scores={}, fallback_score=.1, cost_bps=200, tp_pct=10, sl_pct=10)
            with patch.object(pe, 'fetch_onchain_quote', AsyncMock(return_value=None)), \
                    patch.object(pe, 'fetch_quote', fetch):
                for now in (165, 166):
                    with patch.object(pe.time, 'time', return_value=now):
                        await pe.collect_once(con, None, [], now, model=model)
                self.assertEqual(set(seen), set(mints))
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 3)
                price = 2
                with patch.object(pe.time, 'time', return_value=167):
                    await pe.collect_once(con, None, [], 167, model=model, entry_guard=lambda: False)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'").fetchone()[0], 3)
                self.assertAlmostEqual(pt.paper_capital(con)[1], 12.94)
                self.store = TransactionRecovery(self.path, retry_base=0)
                replay = await self.recover(tx)
                replay.assert_not_awaited()
                for now in (167, 168):
                    with patch.object(pe.time, 'time', return_value=now):
                        await pe.collect_once(con, None, [], now, model=model, entry_guard=lambda: False)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0], 3)
                self.assertAlmostEqual(pt.paper_capital(con)[1], 12.94)


if __name__ == '__main__':
    unittest.main()
