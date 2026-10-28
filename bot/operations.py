"""Local PAPER supervision and consistent backups; no source/network polling.

Health observations are supplied by the supervisor. A recently detected token is
not a connection heartbeat. The gate plugs into collect_once's existing
entry_guard and never suppresses management of an existing position.
"""
import hashlib
from contextlib import closing
import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SOURCE_STATES = {'scanner': 'ready', 'rpc': 'healthy', 'websocket': 'subscribed'}


def build_operational_health(con, observations, *, now_ms, max_age_ms=30000,
                             emergency_stop=False):
    """Read one consistent SQLite snapshot, preserving any caller transaction.

    Standalone reporters acquire a read transaction and release only that read
    snapshot. Inside collect_once, all checks reuse its existing locked book.
    """
    owns_snapshot = not con.in_transaction
    if owns_snapshot:
        con.execute('BEGIN')
    try:
        return _build_operational_health(con, observations, now_ms=now_ms,
            max_age_ms=max_age_ms, emergency_stop=emergency_stop)
    finally:
        if owns_snapshot:
            con.rollback()


def _build_operational_health(con, observations, *, now_ms, max_age_ms,
                              emergency_stop):
    """Inspect the same PAPER book without migration, repair, or reset.

    A green result is permission for PAPER *admission checks*, not permission to
    bypass strategy, scanner, daily-loss, or inventory/quote guards.
    """
    if (type(now_ms) is not int or now_ms < 0 or type(max_age_ms) is not int
            or max_age_ms <= 0):
        raise ValueError('An explicit nonnegative clock and positive age limit are required')
    from bot.analyser.functional_report import _atomic_inventory_report
    from bot.analyser.paper_trader import _paper_free_capital, _paper_realization_events

    reasons, sources = [], {}
    if type(emergency_stop) is not bool or emergency_stop:
        reasons.append('emergency_stop_or_invalid_stop_state')
    for source, required_state in SOURCE_STATES.items():
        observation = observations.get(source) if type(observations) is dict else None
        at = observation.get('observed_at_ms') if type(observation) is dict else None
        state = observation.get('state') if type(observation) is dict else None
        valid_time = type(at) is int and 0 <= at <= now_ms
        fresh = valid_time and now_ms-at <= max_age_ms
        healthy = fresh and state == required_state
        sources[source] = {'healthy': healthy, 'age_ms': now_ms-at if valid_time else None,
                           'state': state if state == required_state else 'unknown_or_unhealthy'}
        if not healthy:
            reasons.append(source+'_unhealthy_stale_or_unknown')

    capital = free = None
    inventory, opened = None, []
    try:
        inventory = _atomic_inventory_report(con)
        if inventory.get('inventory_consistent') is not True:
            raise ValueError('Inventory unavailable or inconsistent')
        if any(position['remaining_atomic'] != '0' and (position['entry_extra_lamports'] is None
                   or position['cost_basis_remaining_lamports'] is None)
               for position in inventory['positions']):
            reasons.append('open_inventory_costs_unknown')
        # The existing reconciliation checks legs, quantities, remaining basis
        # and aggregate PnL, excluding native aggregate closures from re-credit.
        capital, free = _paper_free_capital(con)
        events = _paper_realization_events(con)
        if any(event['time_ms'] > now_ms for event in events):
            raise ValueError('Future realization')
        if not math.isfinite(free) or free < 0:
            raise ValueError('Negative or invalid free capital')
        native = {position['mint']: position for position in inventory['positions']}
        for mint, entry_time in con.execute("SELECT mint,entry_time FROM paper_trades WHERE status='open' ORDER BY mint"):
            if (type(entry_time) not in (int, float) or not math.isfinite(entry_time)
                    or not 0 <= entry_time*1000 <= now_ms):
                raise ValueError('Invalid open-position chronology')
            position = native.get(mint)
            if position is None:
                reasons.append('open_legacy_inventory_unknown')
                opened.append({'mint': mint, 'remaining_atomic': None, 'version': None})
                continue
            entry = position['entry_decision_ms']
            settled = position['last_settlement_ms']
            if (type(entry) is not int or not 0 <= entry <= now_ms
                    or (settled is not None and (type(settled) is not int or not entry <= settled <= now_ms))):
                raise ValueError('Invalid inventory chronology')
            if position['entry_extra_lamports'] is None or position['cost_basis_remaining_lamports'] is None:
                reasons.append('open_inventory_costs_unknown')
            opened.append({'mint': mint, 'remaining_atomic': position['remaining_atomic'],
                           'version': position['version'],
                           'last_settlement_ms': position['last_settlement_ms']})
    except (sqlite3.Error, ValueError, TypeError, KeyError, OverflowError):
        reasons.append('ledger_integrity_or_available_cash_unproven')
        capital = free = None

    reasons = sorted(set(reasons))
    return {'schema': 'rugger-paper-operational-health-v1', 'paper_only': True,
            'observed_at_ms': now_ms, 'max_source_age_ms': max_age_ms,
            'allow_new_entries': not reasons, 'blocking_reasons': reasons,
            'source_health': sources, 'capital_sol': capital, 'available_cash_sol': free,
            'remaining_positions': opened,
            'native_ledger_summary': ({key: inventory.get(key) for key in (
                'realized_pnl_lamports', 'recognized_extra_fee_lamports',
                'positions_fully_settled', 'positions_open_partial',
                'positions_with_remaining_inventory')} if inventory else None),
            'restart_action': 'resume_existing_positions_without_reentry_or_capital_reset',
            'inventory_preserved': inventory is not None and inventory.get('inventory_consistent') is True,
            'real_orders_enabled': False, 'economic_pnl_verified': False,
            'scope': 'local_paper_preflight; observed_heartbeats_are_caller_attestations'}


class OperationalEntryGuard:
    """Compose health/emergency checks with the engine's existing entry guard.

    The caller must bind the same connection passed to collect_once. No background
    worker or separate SQLite snapshot can override its locked admission check.
    """
    def __init__(self, con, observations_provider, *, emergency_stop_provider=lambda: False,
                 clock_ms=lambda: time.time_ns()//1000000, max_age_ms=30000, scanner_guard=None):
        self.con, self.observations_provider = con, observations_provider
        self.emergency_stop_provider, self.clock_ms = emergency_stop_provider, clock_ms
        self.max_age_ms, self.scanner_guard, self.last_health = max_age_ms, scanner_guard, None

    def __call__(self):
        try:
            self.last_health = build_operational_health(self.con, self.observations_provider(),
                now_ms=self.clock_ms(), max_age_ms=self.max_age_ms,
                emergency_stop=self.emergency_stop_provider())
            if not self.last_health['allow_new_entries']:
                return False
            if self.scanner_guard is None:
                return True
            if hasattr(self.scanner_guard, 'allows'):
                return bool(self.scanner_guard.allows(self.con))
            return bool(self.scanner_guard())
        except Exception:
            # A failing supervisor must never become admission permission.
            return False


def make_read_only_handler(snapshot_provider):
    """HTTP adapter for a local supervisor; no orders or database write routes.

    Returns a handler class, without binding a socket or starting a background
    service. The caller supplies a fresh read-only snapshot for every request.
    """
    class ReadOnlyHandler(BaseHTTPRequestHandler):
        timeout = 5
        def log_message(self, _format, *args):
            pass

        def _json(self, status, value):
            raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path not in ('/health', '/portfolio', '/positions'):
                self._json(404, {'error': 'unknown_read_only_route'})
                return
            try:
                snapshot = snapshot_provider()
                if type(snapshot) is not dict or snapshot.get('schema') != 'rugger-paper-operational-health-v1':
                    raise ValueError('Invalid operational snapshot')
                if self.path == '/portfolio':
                    snapshot = {key: snapshot[key] for key in (
                        'paper_only','economic_pnl_verified','capital_sol','available_cash_sol','native_ledger_summary')}
                elif self.path == '/positions':
                    snapshot = {'paper_only': True, 'remaining_positions': snapshot['remaining_positions']}
                self._json(200, snapshot)
            except Exception:
                self._json(503, {'error': 'operational_snapshot_unavailable', 'allow_new_entries': False})

        def do_POST(self):
            self._json(405, {'error': 'read_only_api'})

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST
    return ReadOnlyHandler


def backup_paper_database(source, destination, *, max_elapsed_seconds=10):
    """SQLite's online backup copies committed WAL content to a NEW local file.

    It never copies .env files or uploads data. No source schema is initialized.
    The destination must be reviewed/preflighted before a manual restore; this
    function does not replace a database or reset the running process.
    """
    source, destination = Path(source), Path(destination)
    if (not source.is_file() or source.is_symlink() or source.name.startswith('.env')
            or source.resolve() == destination.resolve() or destination.exists()
            or destination.is_symlink() or destination.suffix not in ('.sqlite', '.db')
            or type(max_elapsed_seconds) not in (int, float)
            or not math.isfinite(max_elapsed_seconds) or not 0 < max_elapsed_seconds <= 60):
        raise ValueError('Existing regular PAPER DB and new separate local SQLite destination required')
    start = time.monotonic()
    pages_copied = 0
    def progress(_status, remaining, total):
        nonlocal pages_copied
        pages_copied = total-remaining
        if time.monotonic()-start > max_elapsed_seconds:
            raise TimeoutError('Bounded SQLite backup deadline exceeded')
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)) as reader:
            with closing(sqlite3.connect(destination, timeout=.1)) as writer:
                reader.backup(writer, pages=64, progress=progress, sleep=.01)
                if writer.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('Backup integrity unproven')
        digest = hashlib.sha256()
        with destination.open('rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        return {'schema': 'rugger-paper-backup-v1', 'backup_sha256': digest.hexdigest(),
                'bytes': destination.stat().st_size, 'pages_copied': pages_copied,
                'elapsed_ms': int((time.monotonic()-start)*1000), 'quick_check': 'ok',
                'source_modified': False, 'restore_performed': False,
                'scope': 'consistent_committed_SQLite_snapshot_not_market_or_strategy_validation'}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main(argv=None):
    """Offline commands; neither command starts a scanner or performs polling."""
    import sys
    from bot.__main__ import _offline_policy
    from bot.analyser.artifacts import atomic_write_json
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    health = sub.add_parser('health', help='Read-only preflight from explicit observed heartbeats')
    health.add_argument('--db', type=Path, required=True)
    health.add_argument('--observations', type=Path, required=True)
    health.add_argument('--output', type=Path, required=True)
    health.add_argument('--max-age-ms', type=int, default=30000)
    health.add_argument('--emergency-stop', action='store_true')
    serve = sub.add_parser('serve', help='Manual localhost read-only API; no scanner or polling')
    serve.add_argument('--db', type=Path, required=True)
    serve.add_argument('--observations', type=Path, required=True)
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--max-age-ms', type=int, default=30000)
    serve.add_argument('--emergency-stop', action='store_true')
    backup = sub.add_parser('backup', help='New consistent local SQLite backup; never restore automatically')
    backup.add_argument('--db', type=Path, required=True)
    backup.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command != 'backup' and args.max_age_ms <= 0:
        parser.error('Positive source age limit required')
    os.environ['RUGGER_NO_DOTENV'] = '1'
    # Serving binds only loopback when explicitly requested; neither mode has
    # an outbound client. Health/backup forbid even accidental socket connects.
    if args.command != 'serve':
        sys.addaudithook(_offline_policy)
    if args.command == 'backup':
        print(json.dumps(backup_paper_database(args.db, args.output), sort_keys=True))
        return
    if args.command == 'serve':
        if (not args.db.is_file() or args.db.is_symlink() or args.db.name.startswith('.env')
                or not args.observations.is_file() or args.observations.is_symlink()
                or args.observations.name.startswith('.env') or args.observations.suffix != '.json'
                or args.observations.stat().st_size > 65536
                or args.db.resolve() == args.observations.resolve() or not 1024 <= args.port <= 65535):
            parser.error('Explicit regular database/heartbeat JSON and unprivileged localhost port required')
        def snapshot():
            # Revalidate heartbeat path on every request, including rotation.
            if (args.observations.is_symlink() or args.observations.stat().st_size > 65536
                    or args.db.is_symlink()):
                raise ValueError('Unsafe replaced input')
            data = json.loads(args.observations.read_text())
            with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)) as con:
                return build_operational_health(con, data, now_ms=time.time_ns()//1000000,
                    max_age_ms=args.max_age_ms, emergency_stop=args.emergency_stop)
        with ThreadingHTTPServer(('127.0.0.1', args.port), make_read_only_handler(snapshot)) as server:
            server.serve_forever(poll_interval=.5)
        return
    if (not args.db.is_file() or args.db.is_symlink() or args.db.name.startswith('.env')
            or not args.observations.is_file() or args.observations.is_symlink()
            or args.observations.name.startswith('.env') or args.observations.suffix != '.json'
            or args.observations.stat().st_size > 65536
            or args.output.exists() or args.output.is_symlink() or args.output.suffix != '.json'
            or len({p.resolve() for p in (args.db,args.observations,args.output)}) != 3):
        parser.error('Existing distinct database/heartbeat JSON and new separate JSON output required')
    data = json.loads(args.observations.read_text())
    with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)) as con:
        result = build_operational_health(con, data, now_ms=time.time_ns()//1000000,
            max_age_ms=args.max_age_ms, emergency_stop=args.emergency_stop)
    atomic_write_json(args.output, result, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps({'allow_new_entries': result['allow_new_entries'], 'report': str(args.output)}))


if __name__ == '__main__':
    main()
