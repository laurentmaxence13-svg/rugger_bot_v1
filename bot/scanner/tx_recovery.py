"""Bounded recovery of notified transactions; no historical scan or orders."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
import time

from bot.scanner.launch_detector import parse_launch_candidate


class RecoveryQueueFull(RuntimeError):
    pass


class TransactionRecovery:
    """One live worker; SQLite stores retries and durable completion receipts.

    Attempts are reserved before RPC. A crash consumes that attempt and its
    lease expires after 90 seconds. No restart resets the attempt budget.
    Completed/exhausted records are retained; only pending work is capped.
    """

    def __init__(self, path, max_pending=1000, max_attempts=5,
                 retry_base=2.0, lease_seconds=90.0):
        if max_pending < 1 or max_attempts < 1 or retry_base < 0 or lease_seconds <= 0:
            raise ValueError('Invalid transaction recovery limits')
        self.path = path
        self.max_pending = max_pending
        self.max_attempts = max_attempts
        self.retry_base = retry_base
        self.lease_seconds = lease_seconds
        with closing(self.connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS scanner_tx_recovery (
                signature TEXT PRIMARY KEY, slot INTEGER NOT NULL,
                received_at TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','done','exhausted')),
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL, last_error TEXT,
                updated_at REAL NOT NULL)''')
            con.execute('CREATE INDEX IF NOT EXISTS idx_scanner_recovery_due '
                        'ON scanner_tx_recovery(state,next_attempt_at)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=1.0, isolation_level=None)

    def enqueue(self, event, now):
        return bool(self.enqueue_batch([event], now))

    def enqueue_batch(self, events, now, *, con=None):
        """The backfill cursor may share the exact transaction of this batch."""
        if con is None:
            with closing(self.connect()) as owned, owned:
                owned.execute('BEGIN IMMEDIATE')
                return self.enqueue_batch(events, now, con=owned)
        if not con.in_transaction:
            raise ValueError('Recovery batch requires a transaction')
        count = con.execute("SELECT COUNT(*) FROM scanner_tx_recovery WHERE state='pending'").fetchone()[0]
        inserted = 0
        for event in events:
            signature, slot, received = event['signature'], event['slot'], event['received_at']
            if not isinstance(signature, str) or not signature or not isinstance(slot, int) or slot < 0:
                raise ValueError('Invalid scanner event identity')
            if not isinstance(received, datetime) or received.tzinfo is None:
                raise ValueError('Scanner reception time must include timezone')
            if con.execute('SELECT 1 FROM scanner_tx_recovery WHERE signature=?', (signature,)).fetchone():
                continue
            if count >= self.max_pending:
                print(f'[TX RECOVERY] QUEUE_FULL {signature[:12]}: '
                      'scanner stopped; pending work retained.', flush=True)
                raise RecoveryQueueFull('Scanner recovery queue capacity reached')
            written = con.execute("INSERT INTO scanner_tx_recovery VALUES(?,?,?,'pending',0,?,NULL,?)",
                                  (signature, slot, received.isoformat(), now, now))
            if written.rowcount != 1:
                raise RuntimeError('Recovery signature was not inserted')
            count += 1
            inserted += 1
        return inserted

    def claim_due(self, now):
        with closing(self.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            expired = con.execute(
                "UPDATE scanner_tx_recovery SET state='exhausted',last_error='InterruptedAttemptBudget',updated_at=? "
                "WHERE state='pending' AND attempts>=? AND next_attempt_at<=?",
                (now, self.max_attempts, now),
            ).rowcount
            if expired:
                print(f'[TX RECOVERY] EXHAUSTED after interrupted attempts: {expired}', flush=True)
            row = con.execute(
                "SELECT signature,slot,received_at,attempts FROM scanner_tx_recovery "
                "WHERE state='pending' AND next_attempt_at<=? AND attempts<? "
                "ORDER BY next_attempt_at,signature LIMIT 1", (now, self.max_attempts),
            ).fetchone()
            if row is None:
                return None
            signature, slot, received, attempts = row
            attempts += 1
            con.execute('UPDATE scanner_tx_recovery SET attempts=?,next_attempt_at=?,updated_at=? WHERE signature=?',
                        (attempts, now + self.lease_seconds, now, signature))
        return {'signature': signature, 'slot': slot,
                'received_at': datetime.fromisoformat(received), 'attempts': attempts}

    def has_pending(self):
        with closing(self.connect()) as con:
            return con.execute("SELECT 1 FROM scanner_tx_recovery WHERE state='pending' LIMIT 1").fetchone() is not None

    def fail(self, job, error, now):
        state = 'exhausted' if job['attempts'] >= self.max_attempts else 'pending'
        delay = min(30.0, self.retry_base * 2 ** (job['attempts'] - 1))
        with closing(self.connect()) as con:
            con.execute("UPDATE scanner_tx_recovery SET state=?,next_attempt_at=?,last_error=?,updated_at=? "
                        "WHERE signature=? AND state='pending' AND attempts=?",
                        (state, now + delay, type(error).__name__, now, job['signature'], job['attempts']))
        print(f"[TX RECOVERY] {state.upper()} {job['signature'][:12]} "
              f"attempt={job['attempts']}/{self.max_attempts} error={type(error).__name__}", flush=True)

    def complete(self, job, tx, parsed, now):
        """Commit cache, all candidates and completion together, or none of them."""
        signature = job['signature']
        inserted = 0
        with closing(self.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT state,attempts FROM scanner_tx_recovery WHERE signature=?',
                              (signature,)).fetchone()
            if row != ('pending', job['attempts']):
                return 0
            con.execute('''INSERT INTO research_tx_cache(signature,payload,fetched_ok,updated_at)
                VALUES(?,?,1,?) ON CONFLICT(signature) DO UPDATE SET
                payload=excluded.payload,fetched_ok=1,updated_at=excluded.updated_at''',
                (signature, json.dumps(tx, separators=(',', ':')), datetime.fromtimestamp(now, timezone.utc).isoformat()))
            mints = parsed['mints']
            for mint in mints:
                candidate_signature = signature if len(mints) == 1 else f'{signature}:{mint}'
                inserted += con.execute('''INSERT INTO launch_candidates
                    (protocol,signature,slot,block_time,detected_at,mint,deployer_candidate,
                     detection_latency_ms,status,pool_state) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(signature) DO NOTHING''',
                    ('raydium_launchpad', candidate_signature, job['slot'], parsed['block_time'],
                     job['received_at'].isoformat(), mint, parsed['deployer_candidate'],
                     parsed['detection_latency_ms'], parsed['status'], parsed.get('pool_state'))).rowcount
            con.execute("UPDATE scanner_tx_recovery SET state='done',last_error=NULL,updated_at=? WHERE signature=?",
                        (now, signature))
        print(f'[TX RECOVERY] DONE {signature[:12]} candidates={inserted}', flush=True)
        return inserted


async def recover_transactions(events, store, fetch_transaction, *, clock=time.time,
                               idle_seconds=.5, attempt_timeout=60.0):
    """Receive independently of retries; a quiet WebSocket cannot stall recovery.

    A caller-owned live stream runs indefinitely; a finite stream drains pending
    work and exits. On cancellation, persisted attempts survive the restart.
    """
    if attempt_timeout <= 0 or attempt_timeout >= store.lease_seconds or idle_seconds <= 0:
        raise ValueError('Recovery timeout must be shorter than its lease')
    finished = False

    async def receive():
        nonlocal finished
        async for event in events:
            store.enqueue(event, clock())
            await asyncio.sleep(0)
        finished = True

    async def work():
        while True:
            job = store.claim_due(clock())
            if job is None:
                if finished and not store.has_pending():
                    return
                await asyncio.sleep(idle_seconds)
                continue
            try:
                tx = await asyncio.wait_for(fetch_transaction(job['signature']), timeout=attempt_timeout)
                if (not isinstance(tx, dict) or not isinstance(tx.get('meta'), dict)
                        or not isinstance(tx.get('transaction'), dict)
                        or not isinstance(tx['transaction'].get('message'), dict)):
                    raise ValueError('Transaction temporarily unavailable or malformed')
                parsed = parse_launch_candidate(tx, job['received_at'])
                store.complete(job, tx, parsed, clock())
            except asyncio.CancelledError:
                raise
            except Exception as error:
                store.fail(job, error, clock())

    tasks = [asyncio.create_task(receive()), asyncio.create_task(work())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
