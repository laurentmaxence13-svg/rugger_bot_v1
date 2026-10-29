"""Private, durable execution journal. Never opens a pre-existing user database.

Reservations precede signing/submission and survive ambiguous outcomes. Chain
finality plus exact balance reconciliation, rather than a quote or confirmation
alone, mutates inventory. This database is separate from the PAPER portfolio.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

APPLICATION_ID = 0x524C5631
ACTIVE = ('RESERVED', 'SIGNED', 'SUBMITTING', 'SUBMITTED', 'CONFIRMED',
          'UNCERTAIN', 'REORG_PENDING', 'EXPIRED_UNKNOWN')
UNRESOLVED = ('UNCERTAIN', 'REORG_PENDING', 'EXPIRED_UNKNOWN')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def uint(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**63:
        raise ValueError('bounded_integer_required')
    return value


class ExecutionJournal:
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink() or not path.parent.is_dir():
            raise ValueError('private_execution_journal_path_required')
        existed = path.exists()
        if existed:
            if path.stat().st_mode & 0o077:
                raise ValueError('execution_journal_must_be_private')
        else:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        self.con = sqlite3.connect(str(path), isolation_level=None)
        self.con.row_factory = sqlite3.Row
        if existed and self.con.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            self.con.close()
            raise ValueError('not_a_rugger_live_execution_journal')
        self.con.execute('PRAGMA synchronous=FULL')
        self.con.execute('PRAGMA journal_mode=DELETE')
        self.con.executescript('''
          CREATE TABLE IF NOT EXISTS execution_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS orders(
            decision_id TEXT PRIMARY KEY, semantic_digest TEXT NOT NULL,
            state TEXT NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
            order_json TEXT NOT NULL, reserved_lamports INTEGER NOT NULL DEFAULT 0,
            reserved_atomic INTEGER NOT NULL DEFAULT 0, signature TEXT,
            signed_raw BLOB, reconciliation_json TEXT, failure_type TEXT);
          CREATE UNIQUE INDEX IF NOT EXISTS execution_signature ON orders(signature) WHERE signature IS NOT NULL;
          CREATE TABLE IF NOT EXISTS positions(
            mint TEXT NOT NULL,pool TEXT NOT NULL,quantity_atomic INTEGER NOT NULL,
            entry_cost_lamports INTEGER NOT NULL,locked_rent_lamports INTEGER NOT NULL,
            PRIMARY KEY(mint,pool));
          CREATE TABLE IF NOT EXISTS audit(
            sequence INTEGER PRIMARY KEY,event_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS daily(
            day TEXT PRIMARY KEY,spent INTEGER NOT NULL DEFAULT 0,
            realized_loss INTEGER NOT NULL DEFAULT 0,realized_pnl INTEGER NOT NULL DEFAULT 0);
        ''')
        self.con.execute(f'PRAGMA application_id={APPLICATION_ID}')

    def close(self):
        self.con.close()

    @contextmanager
    def atomic(self):
        self.con.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.con.execute('COMMIT')
        except BaseException:
            self.con.execute('ROLLBACK')
            raise

    def _audit(self, kind, at, **fields):
        uint(at)
        previous = self.con.execute('SELECT event_hash FROM audit ORDER BY sequence DESC LIMIT 1').fetchone()
        previous = previous[0] if previous else '0' * 64
        event = canonical(dict(kind=kind, at_ms=at, **fields))
        digest = hashlib.sha256((previous + event).encode()).hexdigest()
        self.con.execute('INSERT INTO audit(event_json,previous_hash,event_hash) VALUES(?,?,?)',
                         (event, previous, digest))

    def verify_audit(self):
        previous = '0' * 64
        expected = {}
        ledger_digest = None
        kill_reason = None
        for row in self.con.execute('SELECT * FROM audit ORDER BY sequence'):
            digest = hashlib.sha256((previous + row['event_json']).encode()).hexdigest()
            if row['previous_hash'] != previous or row['event_hash'] != digest:
                raise ValueError('execution_audit_chain_corrupt')
            previous = digest
            event = json.loads(row['event_json'])
            decision = event.get('decision_id')
            kind = event['kind']
            if kind == 'kill':
                kill_reason = event['reason']
            elif kind == 'prepared':
                expected[decision] = dict(state='PREPARED', order_sha256=event['order_sha256'],
                    semantic_digest=event['semantic_digest'], reserved_lamports=0,
                    reserved_atomic=0, signature=None, signed_raw_sha256=None,
                    reconciliation_json=None)
            elif decision in expected:
                current = expected[decision]
                if kind == 'state':
                    if current['state'] != event['before']:
                        raise ValueError('execution_audit_transition_corrupt')
                    current['state'] = event['after']
                    if event.get('signature') is not None:
                        current['signature'] = event['signature']
                    if event.get('signed_raw_sha256') is not None:
                        current['signed_raw_sha256'] = event['signed_raw_sha256']
                elif kind == 'reserved':
                    current.update(state='RESERVED', reserved_lamports=event['native_lamports'],
                                   reserved_atomic=event['quantity_atomic'])
                elif kind == 'unsent_released':
                    current.update(state=event['target'], reserved_lamports=0, reserved_atomic=0)
                elif kind == 'reconciled':
                    current.update(state='RECONCILED', reserved_lamports=0, reserved_atomic=0,
                                   reconciliation_json=canonical(event['reconciliation']))
                    ledger_digest = event['ledger_sha256']
        rows = list(self.con.execute('SELECT * FROM orders'))
        if len(rows) != len(expected):
            raise ValueError('execution_journal_rows_not_bound_to_audit')
        for row in rows:
            current = expected.get(row['decision_id'])
            if current is None or any(row[k] != current[k] for k in (
                    'state', 'semantic_digest', 'reserved_lamports', 'reserved_atomic',
                    'signature', 'reconciliation_json')):
                raise ValueError('execution_journal_rows_not_bound_to_audit')
            if hashlib.sha256(row['order_json'].encode()).hexdigest() != current['order_sha256']:
                raise ValueError('execution_order_not_bound_to_audit')
            raw_digest = hashlib.sha256(row['signed_raw']).hexdigest() if row['signed_raw'] else None
            if raw_digest != current['signed_raw_sha256']:
                raise ValueError('execution_signed_wire_not_bound_to_audit')
        kill = self.con.execute("SELECT value FROM execution_meta WHERE key='kill'").fetchone()
        if (kill[0] if kill else None) != kill_reason:
            raise ValueError('persistent_kill_not_bound_to_audit')
        if ledger_digest is not None and self._ledger_digest() != ledger_digest:
            raise ValueError('execution_inventory_not_bound_to_audit')
        if ledger_digest is None and (self.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
                                      or self.con.execute('SELECT COUNT(*) FROM daily').fetchone()[0]):
            raise ValueError('unreconciled_inventory_in_execution_journal')
        return previous

    def _ledger_digest(self):
        rows = dict(positions=[dict(r) for r in self.con.execute('SELECT * FROM positions ORDER BY mint,pool')],
                    daily=[dict(r) for r in self.con.execute('SELECT * FROM daily ORDER BY day')],
                    failures=[dict(r) for r in self.con.execute("SELECT * FROM execution_meta WHERE key='consecutive_failures'")])
        return hashlib.sha256(canonical(rows).encode()).hexdigest()

    def get(self, decision_id):
        row = self.con.execute('SELECT * FROM orders WHERE decision_id=?', (decision_id,)).fetchone()
        return dict(row) if row else None

    def create(self, decision_id, order, at):
        if (type(decision_id) is not str or not 1 <= len(decision_id) <= 128
                or any(ord(c) < 33 or ord(c) > 126 for c in decision_id)):
            raise ValueError('stable_printable_decision_id_required')
        uint(at)
        encoded = canonical(order)
        with self.atomic():
            old = self.get(decision_id)
            if old:
                if old['order_json'] != encoded:
                    raise ValueError('decision_id_reused_with_different_order')
                return False
            self.con.execute('INSERT INTO orders(decision_id,semantic_digest,state,created_at_ms,updated_at_ms,order_json) VALUES(?,?,?,?,?,?)',
                             (decision_id, order['semantic_digest'], 'PREPARED', at, at, encoded))
            self._audit('prepared', at, decision_id=decision_id,
                        semantic_digest=order['semantic_digest'],
                        order_sha256=hashlib.sha256(encoded.encode()).hexdigest())
        return True

    def transition(self, decision_id, expected, target, at, *, signature=None,
                   signed_raw=None, failure_type=None, final_admission=None):
        uint(at)
        with self.atomic():
            row = self.get(decision_id)
            if not row or row['state'] not in expected:
                raise ValueError('execution_state_transition_conflict')
            if target == 'SUBMITTING':
                if self.killed:
                    raise ValueError('persistent_kill_switch_active')
                if final_admission is None:
                    raise ValueError('atomic_final_submission_admission_required')
                # Synchronous pure admission is evaluated while holding the
                # same write lock as the pre-send state transition. No await
                # can make its clocks/financial state stale in this section.
                final_admission()
            self.con.execute('UPDATE orders SET state=?,updated_at_ms=?,signature=COALESCE(?,signature),signed_raw=COALESCE(?,signed_raw),failure_type=? WHERE decision_id=?',
                             (target, at, signature, signed_raw, failure_type, decision_id))
            self._audit('state', at, decision_id=decision_id, before=row['state'], after=target,
                        signature=signature, failure_type=failure_type,
                        signed_raw_sha256=hashlib.sha256(signed_raw).hexdigest() if signed_raw else None)

    @property
    def killed(self):
        row = self.con.execute("SELECT value FROM execution_meta WHERE key='kill'").fetchone()
        return row is not None

    def kill(self, reason, at):
        if type(reason) is not str or not reason:
            raise ValueError('explicit_kill_reason_required')
        with self.atomic():
            self.con.execute("INSERT OR REPLACE INTO execution_meta VALUES('kill',?)", (reason,))
            self._audit('kill', at, reason=reason)

    def reserve(self, decision_id, at, *, wallet_balance_lamports,
                max_capital_lamports, max_open_positions, max_in_flight_orders,
                max_daily_spend_lamports, max_daily_loss_lamports):
        """Atomic financial recheck; engine admission adds all other risk bounds."""
        for value in (wallet_balance_lamports, max_capital_lamports,
                      max_open_positions, max_in_flight_orders,
                      max_daily_spend_lamports, max_daily_loss_lamports):
            uint(value)
        with self.atomic():
            if self.killed:
                raise ValueError('persistent_kill_switch_active')
            row = self.get(decision_id)
            if not row or row['state'] != 'SIMULATED':
                raise ValueError('reservation_requires_simulated_order')
            order = json.loads(row['order_json'])
            pending = list(self.con.execute('SELECT * FROM orders WHERE state IN (%s)' % ','.join('?' for _ in ACTIVE), ACTIVE))
            reserved = sum(x['reserved_lamports'] for x in pending)
            if len(pending) >= max_in_flight_orders:
                raise ValueError('in_flight_order_limit')
            native = order['network_fee_upper_lamports'] + order['rent_deposit_lamports']
            quantity = 0
            all_positions = list(self.con.execute('SELECT * FROM positions'))
            positions = [p for p in all_positions if p['quantity_atomic'] > 0]
            if order['side'] == 'BUY':
                native += order['input_amount']
                entry_at_risk = sum(p['entry_cost_lamports'] + p['locked_rent_lamports'] for p in all_positions)
                if entry_at_risk + reserved + native > max_capital_lamports:
                    raise ValueError('capital_reservation_limit')
                pending_mints = {json.loads(x['order_json'])['mint'] for x in pending
                                 if json.loads(x['order_json'])['side'] == 'BUY'}
                position_mints = {p['mint'] for p in positions}
                if order['mint'] not in pending_mints | position_mints and len(pending_mints | position_mints) >= max_open_positions:
                    raise ValueError('open_position_limit')
            else:
                quantity = order['input_amount']
                position = next((p for p in positions if p['mint'] == order['mint'] and p['pool'] == order['pool']), None)
                pending_quantity = sum(x['reserved_atomic'] for x in pending
                                       if json.loads(x['order_json'])['mint'] == order['mint'])
                if not position or quantity + pending_quantity > position['quantity_atomic']:
                    raise ValueError('unowned_or_already_reserved_inventory')
            uint(native)
            if native + reserved > wallet_balance_lamports:
                raise ValueError('insufficient_free_lamports_including_fees_and_rent')
            day = datetime.fromtimestamp(at / 1000, timezone.utc).date().isoformat()
            daily = self.con.execute('SELECT * FROM daily WHERE day=?', (day,)).fetchone()
            if (daily['spent'] if daily else 0) + reserved + native > max_daily_spend_lamports:
                raise ValueError('daily_spend_reservation_limit')
            pending_fees = sum(json.loads(x['order_json'])['network_fee_upper_lamports'] for x in pending)
            if order['side'] == 'BUY' and (daily['realized_loss'] if daily else 0) + pending_fees + order['network_fee_upper_lamports'] >= max_daily_loss_lamports:
                raise ValueError('daily_loss_reservation_limit')
            self.con.execute("UPDATE orders SET state='RESERVED',reserved_lamports=?,reserved_atomic=?,updated_at_ms=? WHERE decision_id=?",
                             (native, quantity, at, decision_id))
            self._audit('reserved', at, decision_id=decision_id,
                        native_lamports=native, quantity_atomic=quantity)

    def release_unsent(self, decision_id, at, reason):
        with self.atomic():
            row = self.get(decision_id)
            if not row or row['state'] not in ('PREPARED', 'SIMULATED', 'RESERVED', 'SIGNED'):
                raise ValueError('uncertain_submission_cannot_release_reservation')
            target = 'EXPIRED' if 'expired' in reason else 'UNSENT_CANCELLED'
            self.con.execute("UPDATE orders SET state=?,reserved_lamports=0,reserved_atomic=0,updated_at_ms=?,failure_type=? WHERE decision_id=?",
                             (target, at, reason, decision_id))
            self._audit('unsent_released', at, decision_id=decision_id, reason=reason, target=target)

    def risk_snapshot(self, *, at, wallet_balance_lamports, exclude_decision_id=None):
        from .safety import InventoryPosition, RiskSnapshot
        active = [r for r in self.con.execute('SELECT * FROM orders WHERE state IN (%s)' % ','.join('?' for _ in ACTIVE), ACTIVE)
                  if r['decision_id'] != exclude_decision_id]
        all_positions = list(self.con.execute('SELECT * FROM positions'))
        positions = [p for p in all_positions if p['quantity_atomic'] > 0]
        day = datetime.fromtimestamp(at / 1000, timezone.utc).date().isoformat()
        daily = self.con.execute('SELECT * FROM daily WHERE day=?', (day,)).fetchone()
        items = []
        for pos in positions:
            reserved = sum(r['reserved_atomic'] for r in active
                           if json.loads(r['order_json'])['mint'] == pos['mint'])
            items.append(InventoryPosition(pos['mint'], pos['pool'], pos['quantity_atomic'], reserved))
        failures = self.con.execute("SELECT value FROM execution_meta WHERE key='consecutive_failures'").fetchone()
        return RiskSnapshot(observed_at_ms=at, wallet_balance_lamports=wallet_balance_lamports,
            reserved_lamports=sum(x['reserved_lamports'] for x in active),
            capital_at_risk_lamports=sum(x['entry_cost_lamports'] + x['locked_rent_lamports'] for x in all_positions),
            day_spent_lamports=daily['spent'] if daily else 0,
            realized_daily_loss_lamports=daily['realized_loss'] if daily else 0,
            pending_loss_lamports=sum(json.loads(x['order_json'])['network_fee_upper_lamports'] for x in active),
            open_positions=len(positions), in_flight_orders=len(active),
            consecutive_failures=int(failures[0]) if failures else 0,
            unresolved_orders=sum(x['state'] in UNRESOLVED for x in active),
            kill_switch=self.killed, positions=tuple(items))

    def finalize(self, decision_id, reconciliation, at):
        """Apply a verified finalized transaction exactly once."""
        with self.atomic():
            row = self.get(decision_id)
            if not row:
                raise ValueError('unknown_execution')
            if row['state'] == 'RECONCILED':
                if row['reconciliation_json'] != canonical(reconciliation):
                    raise ValueError('conflicting_finalized_reconciliation')
                return
            if row['state'] not in ACTIVE:
                raise ValueError('reconciliation_requires_submitted_execution')
            order = json.loads(row['order_json'])
            fee = uint(reconciliation['fee_lamports'])
            day = datetime.fromtimestamp(at / 1000, timezone.utc).date().isoformat()
            spent, pnl = fee, 0
            failed = reconciliation['chain_error'] is not None
            if failed:
                # A reverted instruction set still irreversibly pays the fee.
                pnl = -fee
            if not failed:
                delta = reconciliation['token_delta_atomic']
                position = self.con.execute('SELECT * FROM positions WHERE mint=? AND pool=?', (order['mint'], order['pool'])).fetchone()
                if order['side'] == 'BUY':
                    if type(delta) is not int or delta <= 0:
                        raise ValueError('buy_requires_positive_reconciled_inventory')
                    quantity = uint(delta + (position['quantity_atomic'] if position else 0))
                    cost = uint(order['input_amount'] + fee + (position['entry_cost_lamports'] if position else 0))
                    rent = uint(reconciliation['rent_locked_lamports'] + (position['locked_rent_lamports'] if position else 0))
                    self.con.execute('INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?)', (order['mint'], order['pool'], quantity, cost, rent))
                    spent += order['input_amount'] + reconciliation['rent_locked_lamports']
                else:
                    sold = -delta
                    if not position or sold != order['input_amount'] or sold > position['quantity_atomic']:
                        raise ValueError('sell_reconciliation_inventory_mismatch')
                    allocated = position['entry_cost_lamports'] * sold // position['quantity_atomic']
                    pnl = reconciliation['gross_output_lamports'] - fee - allocated
                    self.con.execute('UPDATE positions SET quantity_atomic=?,entry_cost_lamports=? WHERE mint=? AND pool=?',
                                     (position['quantity_atomic'] - sold, position['entry_cost_lamports'] - allocated, order['mint'], order['pool']))
            self.con.execute('INSERT INTO daily(day,spent,realized_loss,realized_pnl) VALUES(?,?,?,?) ON CONFLICT(day) DO UPDATE SET spent=spent+excluded.spent,realized_loss=realized_loss+excluded.realized_loss,realized_pnl=realized_pnl+excluded.realized_pnl',
                             (day, spent, max(0, -pnl), pnl))
            previous_failures = self.con.execute("SELECT value FROM execution_meta WHERE key='consecutive_failures'").fetchone()
            failures = (int(previous_failures[0]) if previous_failures else 0) + 1 if failed else 0
            self.con.execute("INSERT OR REPLACE INTO execution_meta VALUES('consecutive_failures',?)", (str(failures),))
            self.con.execute("UPDATE orders SET state='RECONCILED',reserved_lamports=0,reserved_atomic=0,reconciliation_json=?,updated_at_ms=? WHERE decision_id=?",
                             (canonical(reconciliation), at, decision_id))
            self._audit('reconciled', at, decision_id=decision_id, reconciliation=reconciliation,
                        ledger_sha256=self._ledger_digest())
