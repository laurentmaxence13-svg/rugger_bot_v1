"""Bounded recovery of program signatures; coverage is relative to a saved anchor."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import time


class ProgramBackfill:
    def __init__(self, store, program_id, fetch_page, *, page_size=100, max_pages=5,
                 interval=60.0, page_timeout=30.0, clock=time.time):
        if not 1 <= page_size <= 100 or not 1 <= max_pages <= 10 or interval <= 0 or page_timeout <= 0:
            raise ValueError('Invalid backfill bounds')
        self.store, self.program_id, self.fetch_page = store, program_id, fetch_page
        self.page_size, self.max_pages = page_size, max_pages
        self.interval, self.page_timeout, self.clock = interval, page_timeout, clock
        self.requested = asyncio.Event()
        with closing(store.connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS scanner_backfill_state (
                program_id TEXT PRIMARY KEY, cursor_signature TEXT, cursor_slot INTEGER,
                history_status TEXT NOT NULL, reason TEXT,
                ws_state TEXT NOT NULL, checked_at REAL NOT NULL,
                scan_before TEXT, scan_head_signature TEXT, scan_head_slot INTEGER,
                coverage_start_signature TEXT)''')
            con.execute("INSERT OR IGNORE INTO scanner_backfill_state "
                        "(program_id,history_status,reason,ws_state,checked_at) "
                        "VALUES(?,'uninitialized','no_previous_cursor','disconnected',?)", (program_id, clock()))
            con.execute("UPDATE scanner_backfill_state SET ws_state='disconnected' WHERE program_id=?", (program_id,))

    def state(self):
        with closing(self.store.connect()) as con:
            return con.execute('SELECT cursor_signature,cursor_slot,history_status,reason,ws_state '
                               'FROM scanner_backfill_state WHERE program_id=?', (self.program_id,)).fetchone()

    def degraded(self, reason):
        with closing(self.store.connect()) as con:
            con.execute("UPDATE scanner_backfill_state SET history_status='degraded',reason=?,checked_at=? "
                        'WHERE program_id=?', (reason, self.clock(), self.program_id))
        print(f'[BACKFILL] DEGRADED {reason}; cursor retained.', flush=True)

    async def on_state(self, message):
        ws_state = message['state']
        with closing(self.store.connect()) as con:
            con.execute('UPDATE scanner_backfill_state SET ws_state=? WHERE program_id=?',
                        (ws_state, self.program_id))
        if ws_state == 'subscribed':
            self.requested.set()
        elif ws_state in ('subscription_refused', 'disconnected'):
            reason = message.get('reason')
            self.degraded(f'{ws_state}:{reason}' if reason else ws_state)

    async def once(self):
        anchor, anchor_slot, *_ = self.state()
        with closing(self.store.connect()) as con:
            resume_before, head_signature, head_slot = con.execute(
                'SELECT scan_before,scan_head_signature,scan_head_slot FROM scanner_backfill_state WHERE program_id=?',
                (self.program_id,)).fetchone()
            con.execute("UPDATE scanner_backfill_state SET history_status='catching_up',reason=NULL "
                        'WHERE program_id=?', (self.program_id,))
        before, newest, found, reason = resume_before, None, False, None
        saved_head = (head_signature, head_slot) if head_signature else None
        events, seen = [], set()
        discovered_at = datetime.fromtimestamp(self.clock(), timezone.utc)
        previous_slot = None
        try:
            # With no prior anchor, establish a bounded recent baseline only.
            pages = 1 if anchor is None else self.max_pages
            for _ in range(pages):
                options = {'limit': self.page_size, 'commitment': 'confirmed'}
                if before is not None:
                    options['before'] = before
                page = await asyncio.wait_for(self.fetch_page(self.program_id, options), self.page_timeout)
                if not isinstance(page, list) or len(page) > self.page_size:
                    raise ValueError('invalid_signature_page')
                if not page:
                    reason = 'anchor_not_found' if anchor else 'bootstrap_empty_no_anchor'
                    break
                for row in page:
                    if (not isinstance(row, dict) or not isinstance(row.get('signature'), str)
                            or not row['signature'] or not isinstance(row.get('slot'), int)
                            or row['slot'] < 0 or 'err' not in row):
                        raise ValueError('invalid_signature_row')
                    signature, slot = row['signature'], row['slot']
                    if previous_slot is not None and slot > previous_slot:
                        raise ValueError('unordered_signature_page')
                    previous_slot = slot
                    if signature == anchor:
                        if row['err'] is not None or slot != anchor_slot:
                            raise ValueError('inconsistent_anchor')
                        found = True
                        break
                    if signature in seen:
                        continue
                    seen.add(signature)
                    if row['err'] is not None:
                        continue
                    if newest is None:
                        newest = (signature, slot)
                    events.append({'signature': signature, 'slot': slot, 'received_at': discovered_at})
                if found or anchor is None:
                    break
                tail = page[-1]['signature']
                if tail == before:
                    raise ValueError('pagination_not_progressing')
                before = tail
                if len(page) < self.page_size:
                    reason = 'anchor_not_found'
                    break
            if anchor and not found:
                reason = reason or 'page_limit_anchor_not_found'
            elif anchor is None:
                reason = 'bootstrap_recent_window_only' if newest else (reason or 'bootstrap_no_successful_signature')
        except asyncio.CancelledError:
            self.degraded('interrupted')
            raise
        except Exception as error:
            # Do not store provider messages which may contain endpoint secrets.
            reason = 'rpc_or_history_' + type(error).__name__

        can_advance = reason is None and found
        baseline = anchor is None and newest is not None and reason == 'bootstrap_recent_window_only'
        try:
            with closing(self.store.connect()) as con, con:
                con.execute('BEGIN IMMEDIATE')
                current = con.execute('SELECT cursor_signature FROM scanner_backfill_state WHERE program_id=?',
                                      (self.program_id,)).fetchone()[0]
                if current != anchor:
                    raise RuntimeError('Concurrent backfill changed the anchor')
                self.store.enqueue_batch(events, self.clock(), con=con)
                scan_head = saved_head or newest
                target = scan_head if can_advance and scan_head else (newest if baseline else (anchor, anchor_slot))
                if target[0] is not None:
                    receipt = con.execute('SELECT slot FROM scanner_tx_recovery WHERE signature=?', (target[0],)).fetchone()
                    if receipt != (target[1],):
                        raise RuntimeError('Coverage cursor has no matching recovery receipt')
                status = 'caught_up' if can_advance else ('baseline' if baseline else 'degraded')
                recorded_slot = con.execute('SELECT MAX(slot) FROM scanner_tx_recovery').fetchone()[0]
                if (can_advance or baseline) and target[1] is not None and recorded_slot > target[1]:
                    # A provider may index more slowly than the live stream.
                    # The covered prefix is safe, but the newer gap is not.
                    status, reason = 'degraded', 'rpc_head_behind_recorded_slot'
                # Each page checkpoint covers only signatures already enqueued
                # in this transaction. Final coverage still requires the anchor.
                checkpoint = reason == 'page_limit_anchor_not_found'
                con.execute('UPDATE scanner_backfill_state SET cursor_signature=?,cursor_slot=?,history_status=?,reason=?,checked_at=?, '
                            'scan_before=?,scan_head_signature=?,scan_head_slot=?, '
                            'coverage_start_signature=COALESCE(coverage_start_signature,?) WHERE program_id=?',
                            (*target, status, reason, self.clock(), before if checkpoint else resume_before if not can_advance else None,
                             scan_head[0] if scan_head and not (can_advance or baseline) else None,
                             scan_head[1] if scan_head and not (can_advance or baseline) else None,
                             newest[0] if baseline else None, self.program_id))
            print(f'[BACKFILL] {status.upper()} enqueued_window={len(events)} reason={reason}', flush=True)
        except Exception as error:
            self.degraded('enqueue_or_commit_' + type(error).__name__)

    async def run(self):
        # First pass follows an ACK; thereafter also scan while notifications
        # are quiet. The live receiver and P1.1 worker never wait for RPC pages.
        await self.requested.wait()
        while True:
            self.requested.clear()
            await self.once()
            try:
                await asyncio.wait_for(self.requested.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
