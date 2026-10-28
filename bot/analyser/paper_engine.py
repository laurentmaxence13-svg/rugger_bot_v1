"""Orchestrateur unique d'observation et de paper trading.

Ce programme regroupe le scanner LaunchLab et la collecte de prix/liquidité.
Il peut observer les comportements déjà présents dans le cache Helius, mais
ne signe jamais, ne détient aucune clé privée et n'envoie aucun ordre.
Sans modèle hors échantillon validé, il collecte uniquement les cotations.
"""

import argparse
import asyncio
import bisect
from contextlib import closing
import json
import math
import os
from dataclasses import asdict
from datetime import datetime
import sqlite3
import tempfile
import time
from pathlib import Path

import aiohttp

from bot.analyser.launchlab_onchain import fetch_onchain_quote
from bot.analyser.behavior_pipeline import classify_creator_behavior
from bot.analyser.behavior_pipeline import load_cached_transactions

_analysis_emit_cache = {}

def _emit_analysis_once(mint, report, now, interval=120):
    signature = (report.get('decision_finale'), report.get('score'), report.get('raison'), tuple(report.get('risques') or ()))
    previous = _analysis_emit_cache.get(mint)
    if previous and previous[0] == signature and int(now) - previous[1] < interval:
        return False
    _analysis_emit_cache[mint] = (signature, int(now))
    return True
from bot.analyser.final_decision_engine import build_features, decide
from bot.analyser.multi_creator_research_engine import (
    AdaptiveRPCGate,
    cache_get,
    cache_put,
    ensure_schema,
    rpc_json,
    signatures,
)
from bot.analyser.paper_trader import (
    entry_allowed,
    eligible_model,
    ensure_paper_portfolio,
    paper_capital,
    fetch_quote,
    record_quote,
    skip_recorded_quote,
    _paper_close_transaction,
    setup,
)
from bot.config import BASE_DIR, get_settings
from bot.scanner.supervision import (
    ScannerHealth, _raise_paper_failures, _await_paper_cleanup, _stop_supervised_tasks,
)
from bot.database.db import Database
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import RAYDIUM_LAUNCHPAD_PROGRAM_ID, find_raydium_launches


class _ScannerEntryGuard:
    """Fail closed on stale/unknown supervised state; not a coverage proof."""
    MAX_STATE_AGE = 120.0  # Two default backfill intervals; not a market limit.

    def __init__(self, db, task, health=None, *, clock=None):
        self.db, self.task, self.health = db, task, health
        self.clock = clock or (lambda: time.time())
        self.started_at = self.clock()
        self.program_id = os.getenv('RAYDIUM_LAUNCHPAD_PROGRAM_ID',
                                    RAYDIUM_LAUNCHPAD_PROGRAM_ID).strip()
        self.initial_checked_at = None
        self.initial_state_readable = False
        try:
            with closing(self._connect()) as con:
                row = con.execute('SELECT checked_at FROM scanner_backfill_state '
                                  'WHERE program_id=?', (self.program_id,)).fetchone()
                if row and isinstance(row[0], (int, float)) and math.isfinite(row[0]):
                    self.initial_checked_at = row[0]
                self.initial_state_readable = True
        except sqlite3.Error:
            pass  # A subsequent fresh, readable state is still required.

    def _connect(self):
        return sqlite3.connect(Path(self.db).resolve().as_uri() + '?mode=ro',
                               uri=True, timeout=0.1)

    def __call__(self):
        # Preserve the zero-argument guard contract for supervisory observers.
        try:
            with closing(self._connect()) as con:
                return self.allows(con)
        except sqlite3.Error:
            return False

    def operational_snapshot(self, con):
        """Read-only P5 snapshot from this lifetime's actual source callbacks."""
        from bot.operations import build_operational_health
        health = self.health or getattr(self.task, 'scanner_health', None)
        observations = health.operational_observations() if health is not None else {}
        if 'scanner' in observations and not self.allows(con):
            observations['scanner']['state'] = 'unavailable'
            observations['scanner']['evidence'] = 'scanner_coverage_or_lifetime_guard_refusal'
        return build_operational_health(con, observations, now_ms=int(self.clock()*1000),
            max_age_ms=int(self.MAX_STATE_AGE*1000),
            emergency_stop=health is None or health.failed)

    def allows(self, con):
        # collect_once uses its own locked connection: no separate stale snapshot.
        health = self.health or getattr(self.task, 'scanner_health', None)
        if (health is None or not health.permits_entries()
                or self.task.done() or self.task.cancelling()):
            return False
        try:
            row = con.execute('SELECT history_status,reason,ws_state,checked_at,'
                              'cursor_signature,cursor_slot FROM scanner_backfill_state '
                              'WHERE program_id=?', (self.program_id,)).fetchone()
            if not row:
                return False
            history, reason, ws, checked, signature, slot = row
            if not self.initial_state_readable:
                # If startup inspection failed, establish a reference first.
                # Even a future-dated old row must be renewed before entry.
                if isinstance(checked, (int, float)) and math.isfinite(checked):
                    self.initial_checked_at = checked
                    self.initial_state_readable = True
                return False
            if history != 'caught_up' or reason is not None or ws != 'subscribed':
                return False
            now = self.clock()
            if (not isinstance(checked, (int, float)) or not math.isfinite(checked)
                    or not self.started_at <= checked <= now
                    or now - checked > self.MAX_STATE_AGE
                    or (self.initial_checked_at is not None and checked <= self.initial_checked_at)):
                return False
            if (not isinstance(signature, str) or not signature
                    or not isinstance(slot, int) or slot < 0):
                return False
            return con.execute('SELECT slot FROM scanner_tx_recovery WHERE signature=?',
                               (signature,)).fetchone() == (slot,)
        except sqlite3.Error:
            return False


def _entry_guard_allows(guard, con):
    if guard is None:  # Explicit standalone mode retains its existing contract.
        return True
    try:
        return bool(guard.allows(con) if isinstance(guard, _ScannerEntryGuard) else guard())
    except sqlite3.Error:
        return False


class LiveBehaviorFetcher:
    """Fetch a small recent creator window with one throttled RPC gate."""

    def __init__(self, db_path, interval=2.5, max_tx=10, refresh_seconds=60,
                 gate=None):
        self.db_path = db_path
        self.interval = max(1.1, float(interval))
        self.max_tx = max(1, int(max_tx))
        self.refresh_seconds = max(10, int(refresh_seconds))
        self.settings = get_settings()
        self.gate = gate or AdaptiveRPCGate(self.interval)
        self.rpc = SolanaRPC(self.settings.rpc_url)
        self.last_refresh = {}

    async def start(self):
        await self.rpc.__aenter__()
        return self

    async def close(self):
        await self.rpc.__aexit__(None, None, None)

    async def refresh(self, creator):
        if not creator:
            return False
        now = time.monotonic()
        if now - self.last_refresh.get(creator, 0.0) < self.refresh_seconds:
            return False
        try:
            recent = await signatures(
                self.rpc, self.settings.rpc_url, self.gate,
                creator, self.max_tx,
            )
            changed = False
            for item in recent:
                signature = item.get('signature') if isinstance(item, dict) else None
                if not signature or cache_get(self.db_path, signature) is not None:
                    continue
                tx = await rpc_json(
                    self.rpc, self.settings.rpc_url, self.gate,
                    'getTransaction', [signature, {
                        'encoding': 'jsonParsed',
                        'maxSupportedTransactionVersion': 1,
                    }],
                )
                if tx is not None:
                    cache_put(self.db_path, signature, tx)
                    changed = True
            self.last_refresh[creator] = now
            return changed
        except Exception as exc:
            # A temporary Helius failure must not stop price collection.
            print(f'[BEHAVIOR] collecte reportée pour {creator[:8]}…', flush=True)
            self.last_refresh[creator] = now
            return False


def _reception_time(value, now):
    """Observation time only; never a substitute for a blockchain time."""
    try:
        date = datetime.fromisoformat(value) if isinstance(value, str) else None
        if date is None or date.tzinfo is None or date.utcoffset() is None:
            return None
        timestamp = date.timestamp()
        return timestamp if 0 < timestamp <= now else None
    except (ValueError, OverflowError, OSError):
        return None


def _verified_launch_time(con, record, now, has_cache):
    value = record['block_time']
    if type(value) is not int or not 0 < value <= now:
        return None
    received = _reception_time(record.get('detected_at'), now)
    if received is not None and value > received:
        return None
    signature = record.get('signature')
    if signature and has_cache:
        suffix = ':' + record['mint']
        raw_signature = signature[:-len(suffix)] if signature.endswith(suffix) else signature
        cached = con.execute('SELECT payload,fetched_ok FROM research_tx_cache WHERE signature=?',
                             (raw_signature,)).fetchone()
        if cached:
            try:
                tx = json.loads(cached[0])
                raw_time = tx.get('blockTime')
                # SQLite INTEGER affinity can hide bool/float/string provenance.
                if cached[1] != 1 or type(raw_time) is not int or raw_time != value:
                    return None
                matching = [launch for launch in find_raydium_launches(tx)
                            if launch['mint'] == record['mint']
                            and launch['creator'] == record['deployer_candidate']
                            and (record.get('pool_state') is None
                                 or launch['pool_state'] == record['pool_state'])]
                if not matching:
                    return None
            except (ValueError, TypeError, AttributeError, KeyError):
                return None
    return value


def _launch_records(con, now, mint=None):
    columns = {r[1] for r in con.execute('PRAGMA table_info(launch_candidates)')}
    names = ('mint', 'deployer_candidate', 'block_time', 'detected_at', 'signature', 'pool_state')
    projection = ','.join(name if name in columns else 'NULL AS ' + name for name in names)
    has_cache = _table_exists(con, 'research_tx_cache')
    records = []
    for values in con.execute('SELECT ' + projection + " FROM launch_candidates "
                              "WHERE status='creator_identified' AND mint IS NOT NULL"
                              + (' AND mint=?' if mint is not None else '') + ' ORDER BY rowid',
                              (mint,) if mint is not None else ()):
        record = dict(zip(names, values))
        record['verified_time'] = _verified_launch_time(con, record, now, has_cache)
        records.append(record)
    return records


def _undated_candidates(con, now, max_age, records):
    """One FIFO item per mint; inactive diagnostics are processed only once."""
    groups = {}
    for record in records:
        if record['verified_time'] is None:
            groups.setdefault(record['mint'], []).append(record)
    audits = dict(con.execute('SELECT mint,report_json FROM paper_mint_audit')) \
        if _table_exists(con, 'paper_mint_audit') else {}
    result = {}
    for mint, group in groups.items():
        # Earliest valid reception is stable and cannot extend the observation
        # window on replay. Conflicting identities are diagnostic-only.
        receptions = [_reception_time(r['detected_at'], now) for r in group]
        received = min((t for t in receptions if t is not None), default=None)
        conflict = len({(r['deployer_candidate'], r['pool_state']) for r in group}) != 1
        queue_state = ('metadata_conflict' if conflict else 'reception_invalid' if received is None
                       else 'reception_expired' if now-received > max(1, int(max_age)) else 'observable')
        record = dict(group[0])
        record.update(received_at=received, queue_state=queue_state,
                      reception_signature=next((r['signature'] for r, t in zip(group, receptions)
                                                if t is not None and t == received), None),
                      identities=[{key: r[key] for key in ('signature', 'mint', 'deployer_candidate',
                                                         'pool_state', 'block_time', 'detected_at')}
                                  for r in group])
        if conflict:
            record.update(deployer_candidate=None, pool_state=None)
        fingerprint = json.dumps((queue_state, record['identities']), sort_keys=True, default=str)
        record['fingerprint'] = fingerprint
        try:
            previous = json.loads(audits.get(mint, '{}')).get('launch_observation', {})
        except (ValueError, TypeError, AttributeError):
            previous = {}
        if queue_state == 'observable' or previous.get('fingerprint') != fingerprint:
            result[mint] = record
    return result


def recent_candidates(con, now, max_age=900, limit=10, *, records=None):
    """Return fresh, strictly parsed launches for the observation loop."""
    records = _launch_records(con, now) if records is None else records
    fresh = [(r['mint'], r['deployer_candidate'], r['verified_time']) for r in records
             if r['verified_time'] is not None
             and int(now)-max(1, int(max_age)) <= r['verified_time'] <= int(now)]
    fresh.sort(key=lambda row: (-row[2], row[0], row[1] or ''))
    return fresh if limit is None else fresh[:max(1, int(limit))]


def _scheduled_candidates(con, now, max_age, limit, *, records=None, undated=None):
    """Persistent FIFO within each lane; reserve capacity for both lanes.

    New mints join the tail, so arrivals cannot jump ahead of waiting work.
    Open positions get all but one slot when both lanes exceed capacity.
    A one-slot budget alternates lanes using the last durable attempt.
    Only scheduling metadata is written here; no transaction spans an await.
    """
    budget = max(1, int(limit))
    records = _launch_records(con, now) if records is None else records
    undated = _undated_candidates(con, now, max_age, records) if undated is None else undated
    with _paper_close_transaction(con):
        con.execute('''CREATE TABLE IF NOT EXISTS paper_collection_schedule (
            mint TEXT PRIMARY KEY, turn INTEGER NOT NULL,
            last_lane TEXT CHECK(last_lane IN ('position','candidate')))''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_paper_collection_turn '
                    'ON paper_collection_schedule(turn)')
        active = dict((mint, (creator, signal_time)) for mint, creator, signal_time
                      in con.execute("SELECT mint,creator,signal_time FROM paper_trades "
                                     "WHERE status='open' ORDER BY entry_time,mint"))
        candidates = dict(active)
        for mint, creator, signal_time in recent_candidates(con, now, max_age=max_age,
                                                          limit=None, records=records):
            candidates[mint] = (creator, signal_time)
        for mint, record in undated.items():
            if mint not in candidates:
                candidates[mint] = (record['deployer_candidate'], None)
        tail = con.execute('SELECT COALESCE(MAX(turn),0) FROM paper_collection_schedule').fetchone()[0]
        for mint in candidates:
            tail += 1
            con.execute('INSERT OR IGNORE INTO paper_collection_schedule(mint,turn) VALUES(?,?)',
                        (mint, tail))
        order = dict(con.execute('SELECT mint,turn FROM paper_collection_schedule'))
        positions = sorted(active, key=order.__getitem__)
        waiting = sorted(candidates.keys() - active.keys(), key=order.__getitem__)
        if positions and waiting and budget == 1:
            previous = con.execute('SELECT last_lane FROM paper_collection_schedule '
                                   'WHERE last_lane IS NOT NULL ORDER BY turn DESC LIMIT 1').fetchone()
            position_slots = 0 if previous == ('position',) else 1
        else:
            position_slots = min(len(positions), budget - int(bool(waiting)))
        selected = positions[:position_slots] + waiting[:budget - position_slots]
        return [(mint, *candidates[mint], 'position' if mint in active else 'candidate')
                for mint in selected]


def _mark_collection_attempt(con, mint, lane):
    """Advance before price I/O, including failures, cooldowns and cancellation."""
    with _paper_close_transaction(con):
        con.execute('UPDATE paper_collection_schedule SET turn='
                    '(SELECT COALESCE(MAX(turn),0)+1 FROM paper_collection_schedule),last_lane=? '
                    'WHERE mint=?', (lane, mint))


def behavior_snapshot(cached, mint, creator, signal_time, now):
    """Summarise creator/relay actions observed up to ``now`` only."""
    timestamps = [row[0] for row in cached]
    left = bisect.bisect_left(timestamps, int(signal_time))
    right = bisect.bisect_right(timestamps, int(now))
    relevant = 0
    dev_sales = 0
    relays = 0
    for tx_time, signature, tx in cached[left:right]:
        if tx_time <= signal_time or mint not in str(tx):
            continue
        result = classify_creator_behavior(tx, mint, creator)
        relevant += 1
        dev_sales += int(result['sale'])
        relays += int(result['relay'])
    return {
        'behavior_known': relevant > 0,
        'relevant_transactions': relevant,
        'dev_sales': dev_sales,
        'relay_transfers': relays,
        'observed_until': int(now),
    }


def prior_creator_launches(con, creator, signal_time):
    """Count distinct launches known before this signal.

    The live scanner writes ``launch_candidates`` while the historical
    multi-creator research writes ``research_launches``.  Both are valid
    sources for creator history, but a launch present in both must count once.
    """
    if signal_time is None:
        return None
    if not creator:
        return 0
    mints = {r['mint'] for r in _launch_records(con, signal_time)
             if r['deployer_candidate'] == creator and r['verified_time'] is not None
             and r['verified_time'] < signal_time}
    # ``collect_once`` is also unit-testable with a minimal in-memory schema;
    # tolerate that schema while the production path creates this table via
    # ensure_schema().
    has_research = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_launches'"
    ).fetchone()
    if has_research:
        for mint, signature, block_time, pool in con.execute(
                'SELECT mint,signature,block_time,pool_state FROM research_launches '
                'WHERE creator=? AND mint IS NOT NULL', (creator,)):
            record = dict(mint=mint, signature=signature, block_time=block_time,
                          pool_state=pool, deployer_candidate=creator)
            verified = _verified_launch_time(con, record, signal_time,
                                            _table_exists(con, 'research_tx_cache'))
            if verified is not None and verified < signal_time:
                mints.add(mint)
    return len(mints)


def price_history(con, mint):
    """Return the observed PAPER series used by the decision engine."""
    return con.execute(
        '''SELECT timestamp,price_usd,liquidity_usd,
                  volume_5m_usd,volume_24h_usd,price_change_5m_pct,
                  price_change_1h_pct,tx_buys_5m,tx_sells_5m,market_cap_usd,
                  fdv_usd,fee_bps,depth_usd,slippage_bps_est
           FROM paper_prices WHERE mint=? ORDER BY timestamp''',
        (mint,),
    ).fetchall()


def record_decision(con, features, decision, strategy_mode='shadow_final',
                    entry_permission=True):
    """Persist one explainable decision snapshot for audit and reporting."""
    con.execute(
        '''INSERT INTO paper_decisions(
             mint,creator,signal_time,decision_time,strategy_mode,enter,
             entry_allowed,score,reasons_json,risk_flags_json,prior_launches,
             behavior_known,dev_sales,relay_transfers,bundle_transactions,
             bundle_wallets,liquidity_usd,price_usd,quote_count,momentum_60s,
             momentum_300s,tp_pct,sl_pct,trailing_stop_pct,hold_seconds,
             volume_5m_usd,volume_24h_usd,price_change_5m_pct,
             price_change_1h_pct,tx_buys_5m,tx_sells_5m,market_cap_usd,
             fdv_usd,fee_bps,depth_usd,slippage_bps_est,market_data_quality,
             holder_count,top_holder_share,holder_data_known,linked_wallets,
             wallet_link_count,same_slot_wallets,wallet_graph_transactions)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (
            features.mint, features.creator, int(features.signal_time),
            int(features.observed_at), str(strategy_mode), int(bool(decision.enter)),
            int(bool(entry_permission)), float(decision.score),
            json.dumps(list(decision.reasons), ensure_ascii=False),
            json.dumps(list(decision.risk_flags), ensure_ascii=False),
            int(features.prior_launches), int(bool(features.behavior_known)),
            int(features.dev_sales), int(features.relay_transfers),
            int(features.bundle_transactions), int(features.bundle_wallets),
            float(features.liquidity_usd), float(features.price_usd),
            int(features.quote_count), features.momentum_60s,
            features.momentum_300s, float(decision.tp_pct),
            float(decision.sl_pct), decision.trailing_stop_pct,
            int(decision.hold_seconds),
            features.volume_5m_usd, features.volume_24h_usd,
            features.price_change_5m_pct, features.price_change_1h_pct,
            features.tx_buys_5m, features.tx_sells_5m,
            features.market_cap_usd, features.fdv_usd, features.fee_bps,
            features.depth_usd, features.slippage_bps_est,
            features.market_data_quality,
            int(features.holder_count), features.top_holder_share,
            int(bool(features.holder_data_known)), int(features.linked_wallets),
            int(features.wallet_link_count), int(features.same_slot_wallets),
            int(features.wallet_graph_transactions),
        ),
    )


def _table_exists(con, name):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _decision_reason_counts(con):
    counts = {}
    if not _table_exists(con, 'paper_decisions'):
        return counts
    rows = con.execute(
        "SELECT risk_flags_json FROM paper_decisions WHERE enter=0"
    ).fetchall()
    for (raw,) in rows:
        try:
            flags = json.loads(raw or '[]')
        except (TypeError, ValueError, json.JSONDecodeError):
            flags = []
        for flag in flags if isinstance(flags, list) else []:
            counts[str(flag)] = counts.get(str(flag), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _realized_metrics(con, started_at=None, ended_at=None):
    """Realized SOL equity only; never compound position-level returns.

    Inclusive session bounds match the existing reporting contract. Unknown
    closure dates invalidate attribution; missing prior PnL invalidates the
    opening capital. Every closed position must have a finite positive size.
    A missing trade return does not invalidate known SOL PnL if its implied
    return is finite and the portfolio reconciles; no trade return is imputed.
    No portfolio is created or repaired by reporting.
    """
    initial, realized = paper_capital(con)
    rows = con.execute(
        "SELECT exit_time,net_return,cost_bps,pnl_sol,position_sol FROM paper_trades "
        "WHERE status='closed' ORDER BY exit_time,mint"
    ).fetchall()
    finite = lambda v: isinstance(v, (int, float)) and math.isfinite(v)
    invalid_positions = sum(not finite(r[4]) or r[4] <= 0 for r in rows)
    unknown_dates = sum(not finite(r[0]) for r in rows)
    prior = [r for r in rows if finite(r[0]) and started_at is not None and r[0] < started_at]
    closed = [r for r in rows if finite(r[0])
              and (started_at is None or r[0] >= started_at)
              and (ended_at is None or r[0] <= ended_at)]
    relevant = prior + closed
    incomplete = sum(not finite(r[3]) for r in relevant) + unknown_dates
    inconsistent = sum(
        finite(r[3]) and finite(r[4]) and finite(r[1])
        and not math.isclose(r[3], r[4] * r[1], rel_tol=1e-9, abs_tol=1e-12)
        for r in relevant
    )
    # SOL PnL alone is usable only with a meaningful position denominator.
    inconsistent += sum(
        r[1] is None and finite(r[3]) and finite(r[4]) and r[4] > 0
        and not finite(r[3] / r[4]) for r in relevant
    )
    reconciled = (finite(initial) and finite(realized)
                  and all(finite(r[3]) for r in rows)
                  and math.isclose(realized, initial + sum(r[3] for r in rows),
                                   rel_tol=1e-9, abs_tol=1e-12))
    from bot.analyser.paper_trader import _inventory_exists, _paper_realization_events
    native = _inventory_exists(con)
    events = []
    if native:
        try:
            events = _paper_realization_events(con)
            reconciled = (finite(initial) and finite(realized) and math.isclose(
                realized,initial+math.fsum(event['pnl_sol'] for event in events),
                rel_tol=0,abs_tol=1e-12))
        except (TypeError,ValueError,OverflowError):
            incomplete += 1
            reconciled = False
    prior_events = [event for event in events if started_at is not None and event['time'] < started_at]
    current_events = [event for event in events
                      if (started_at is None or event['time'] >= started_at)
                      and (ended_at is None or event['time'] <= ended_at)]
    valid = (finite(initial) and initial > 0 and not incomplete
             and not inconsistent and not invalid_positions and reconciled)
    opening = initial + (math.fsum(e['pnl_sol'] for e in prior_events) if native else sum(r[3] for r in prior)) if valid else None
    valid = valid and opening > 0
    equity = peak = opening if valid else None
    drawdown = 0.0
    if valid:
        cashflows = [e['pnl_sol'] for e in current_events] if native else [r[3] for r in closed]
        for pnl in cashflows:
            equity += pnl
            if equity < 0:
                valid = False
                break
            peak = max(peak, equity)
            drawdown = min(drawdown, equity / peak - 1.0)
    pnls = [r[3] for r in closed] if valid else []
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    returns = [r[1] for r in closed if finite(r[1])]
    costs = [r[2] for r in closed]
    return {
        'average_net_return': sum(returns) / len(returns) if returns else None,
        'net_return_after_costs': (equity - opening) / opening if valid else None,
        'max_drawdown': drawdown if valid else None,
        'win_rate': sum(p > 0 for p in pnls) / len(pnls) if pnls else None,
        'assumed_cost_bps_total': sum(costs) if all(finite(c) for c in costs) else None,
        'pnl_sol': (math.fsum(e['pnl_sol'] for e in current_events) if native else sum(pnls)) if valid else None,
        'profit_factor': gains / losses if losses > 0 else None,
        'capital_start_sol': opening if valid else None,
        'capital_end_sol': equity if valid else None,
        'performance_data_complete': bool(valid),
        'capital_reconciled': bool(reconciled),
        'incomplete_closed_trades': incomplete,
        'inconsistent_closed_trades': inconsistent,
        'invalid_position_closed_trades': invalid_positions,
        'closed_trades': len(closed),
        'wins': sum(p > 0 for p in pnls) if valid else None,
        'losses': sum(p <= 0 for p in pnls) if valid else None,
        **({'realization_events':len(current_events),
            'realization_basis':'legacy_closed_positions_plus_native_legs_without_aggregate_double_count',
            'trade_statistics_scope':'fully_closed_positions; native_partial_legs_are_not_independent_trades'} if native else {}),
    }


def _performance_metrics(con):
    if not _table_exists(con, 'paper_trades'):
        return {
            'average_net_return': None,
            'net_return_after_costs': None,
            'max_drawdown': None,
            'win_rate': None,
            'assumed_cost_bps_total': 0.0,
            'pnl_sol': None, 'profit_factor': None,
            'performance_data_complete': False, 'capital_reconciled': False,
        }
    return _realized_metrics(con)


def _market_data_coverage(con):
    """Report which provider fields were actually observed, never imputed."""
    if not _table_exists(con, 'paper_prices'):
        return {}
    total = con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0]
    if not total:
        return {
            'quotes': 0,
            'volume_5m': 0.0,
            'volume_24h': 0.0,
            'price_change_5m': 0.0,
            'price_change_1h': 0.0,
            'txns_5m': 0.0,
        'market_cap': 0.0,
        'fdv': 0.0,
        'fee_bps': 0.0,
        'depth_usd': 0.0,
        'slippage_bps_est': 0.0,
        }
    fields = {
        'volume_5m': 'volume_5m_usd',
        'volume_24h': 'volume_24h_usd',
        'price_change_5m': 'price_change_5m_pct',
        'price_change_1h': 'price_change_1h_pct',
        'txns_5m': 'tx_buys_5m',
        'market_cap': 'market_cap_usd',
        'fdv': 'fdv_usd',
        'fee_bps': 'fee_bps',
        'depth_usd': 'depth_usd',
        'slippage_bps_est': 'slippage_bps_est',
    }
    columns = {row[1] for row in con.execute('PRAGMA table_info(paper_prices)')}
    result = {'quotes': int(total)}
    for name, column in fields.items():
        if column not in columns:
            result[name] = 0.0
            continue
        observed = con.execute(
            f'SELECT COUNT(*) FROM paper_prices WHERE {column} IS NOT NULL'
        ).fetchone()[0]
        result[name] = observed / total
    return result


def _quote_provenance(con):
    """Coverage of stored observations, not a claim of executable prices."""
    columns = {r[1] for r in con.execute('PRAGMA table_info(paper_prices)')}
    total = con.execute('SELECT COUNT(*) FROM paper_prices').fetchone()[0]
    sources = dict(con.execute('''SELECT COALESCE(NULLIF(TRIM(quote_source),''),'unknown'),
        COUNT(*) FROM paper_prices GROUP BY 1''')) if 'quote_source' in columns else (
            {'unknown': total} if total else {})
    funding = con.execute('SELECT COUNT(*) FROM paper_prices WHERE funding_usd IS NOT NULL'
                          ).fetchone()[0] if 'funding_usd' in columns else 0
    conflicts, rejected = con.execute(
        'SELECT COUNT(*),COALESCE(SUM(rejected_observations),0) FROM paper_quote_conflicts'
    ).fetchone() if _table_exists(con, 'paper_quote_conflicts') else (0, 0)
    return {
        'quotes': total,
        'source_counts': sources,
        'unknown_source_quotes': sources.get('unknown', 0),
        'funding_known_quotes': funding,
        'funding_unknown_quotes': total - funding,
        'funding_coverage': funding / total if total else 0.0,
        'collection_time_field': 'timestamp',
        'provider_timestamp_known_quotes': 0,
        'provider_timestamp_unknown_quotes': total,
        'provider_age_measurable_quotes': 0,
        'provider_age_seconds': None,
        'freshness_status': 'unknown_no_provider_quote_timestamp',
        'conflicting_quote_keys': conflicts,
        'rejected_conflicting_observations': rejected,
        'conflict_history_complete': False,
        'duplicate_policy': 'first_observation_retained_repeats_not_processed',
    }


def _write_json_report(output, report, *, allow_nan=True):
    """Publish a complete JSON file in one same-directory replacement."""
    path = Path(output)
    temporary = None
    failures = []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(report, indent=2, allow_nan=allow_nan)
        # Close the handle before replacement, including on Windows.
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        temporary.write_text(payload, encoding='utf-8')
        os.replace(temporary, path)
        temporary = None
    except BaseException as exc:
        failures.append(('report write', exc))
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except BaseException as exc:
                failures.append(('report temporary cleanup', exc))
    _raise_paper_failures(failures)


def _valuation_scope(con=None):
    """Separate ledger reconciliation from an observed economic SOL return."""
    scope = {
        'account_currency': 'SOL',
        'observed_price_currency': 'USD',
        'return_conversion_assumption': 'constant_SOL_USD',
        'fx_observed_at_entry_and_exit': False,
        'economic_pnl_verified': False,
        'execution_prices_verified': False,
    }
    if con is not None and _table_exists(con,'paper_token_inventory'):
        native = con.execute('SELECT COUNT(*) FROM paper_token_inventory').fetchone()[0]
        total = con.execute('SELECT COUNT(*) FROM paper_trades').fetchone()[0]
        if native:
            scope.update(native_inventory_positions=native,legacy_positions_without_atomic_inventory=total-native,
                         native_inventory_acquired=False,native_net_basis='SOL_quote_proceeds_minus_exact_allocated_basis_and_extra_fees')
            if native == total:
                scope.update(return_conversion_assumption='native_SOL_quote_amounts',fx_required_for_sol_pnl=False,
                             usd_marks_scope='exit_triggers_only; not_native_PnL_conversion')
            else:
                scope['return_conversion_assumption']='mixed_native_SOL_quotes_and_legacy_constant_SOL_USD'
    return scope


def paper_report(con, now, cached_count, output=None, strategy_mode='validated',
                 validation_status='not_validated', *, data_kind='unknown',
                 latency_samples_ms=None, operational_health=None):
    """Write an operational report, explicitly marked PAPER ONLY."""
    open_count = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE status='open'"
    ).fetchone()[0]
    closed_count = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE status='closed'"
    ).fetchone()[0]
    quotes = con.execute("SELECT COUNT(*) FROM paper_prices").fetchone()[0]
    shadow_open = con.execute(
        "SELECT COUNT(*) FROM paper_trades "
        "WHERE status='open' AND strategy_mode='shadow_baseline'"
    ).fetchone()[0]
    shadow_closed = con.execute(
        "SELECT COUNT(*) FROM paper_trades "
        "WHERE status='closed' AND strategy_mode='shadow_baseline'"
    ).fetchone()[0]
    # One identity universe for both sides of the coverage fraction.
    launch_mints = set()
    if _table_exists(con, 'launch_candidates'):
        launch_mints.update(row[0] for row in con.execute(
            "SELECT DISTINCT mint FROM launch_candidates "
            "WHERE mint IS NOT NULL AND status='creator_identified'"
        ))
    if _table_exists(con, 'research_launches'):
        launch_mints.update(row[0] for row in con.execute(
            'SELECT DISTINCT mint FROM research_launches WHERE mint IS NOT NULL'
        ))
    quoted_mints = {row[0] for row in con.execute(
        'SELECT DISTINCT mint FROM paper_prices WHERE mint IS NOT NULL'
    )}
    quoted_launches = launch_mints & quoted_mints
    orphan_quoted_mints = quoted_mints - launch_mints
    decisions = con.execute(
        'SELECT COUNT(*) FROM paper_decisions'
    ).fetchone()[0]
    rejected = con.execute(
        'SELECT COUNT(*) FROM paper_decisions WHERE enter=0'
    ).fetchone()[0]
    metrics = _performance_metrics(con)
    initial_capital, realized_capital = paper_capital(con)
    report = {
        'schema': 'paper-engine-report-v1',
        'paper_only': True,
        'real_orders_enabled': False,
        'private_keys_used': False,
        'timestamp': int(now),
        'cached_helius_transactions': int(cached_count),
        'launches_observed': len(launch_mints),
        'quotes_recorded': int(quotes),
        'launches_with_quotes': len(quoted_launches),
        'quote_coverage': (len(quoted_launches) / len(launch_mints) if launch_mints else None),
        'quoted_mints_total': len(quoted_mints),
        'quoted_mints_without_identified_launch': len(orphan_quoted_mints),
        'quote_coverage_scope': 'identified_launch_mints',
        'market_detection_coverage': None,
        'decision_count': int(decisions),
        'rejected_decisions': int(rejected),
        'accepted_decisions': int(decisions - rejected),
        'average_score': con.execute(
            'SELECT AVG(score) FROM paper_decisions'
        ).fetchone()[0],
        'open_paper_positions': int(open_count),
        'closed_paper_positions': int(closed_count),
        'strategy_mode': str(strategy_mode),
        'shadow_open_positions': int(shadow_open),
        'shadow_closed_positions': int(shadow_closed),
        'average_net_return': metrics['average_net_return'],
        'net_return_after_costs': metrics['net_return_after_costs'],
        'max_drawdown': metrics['max_drawdown'],
        'win_rate': metrics['win_rate'],
        'assumed_cost_bps_total': metrics['assumed_cost_bps_total'],
        'initial_capital_sol': initial_capital,
        'realized_capital_sol': realized_capital,
        'pnl_sol': metrics.get('pnl_sol', 0.0),
        'profit_factor': metrics.get('profit_factor'),
        'performance_data_complete': metrics.get('performance_data_complete', False),
        'capital_reconciled': metrics.get('capital_reconciled', False),
        'incomplete_closed_trades': metrics.get('incomplete_closed_trades', 0),
        'inconsistent_closed_trades': metrics.get('inconsistent_closed_trades', 0),
        'invalid_position_closed_trades': metrics.get('invalid_position_closed_trades', 0),
        'equity_basis': 'realized_sol',
        'valuation_scope': _valuation_scope(con),
        'market_data_coverage': _market_data_coverage(con),
        'quote_provenance': _quote_provenance(con),
        'rejection_reasons': _decision_reason_counts(con),
        'validation_status': str(validation_status),
    }
    records = _launch_records(con, now) if _table_exists(con, 'launch_candidates') else []
    dated = {r['mint'] for r in records if r['verified_time'] is not None}
    undated = {r['mint'] for r in records if r['verified_time'] is None}
    observed = {r[0] for r in con.execute('SELECT DISTINCT mint FROM paper_prices')}
    diagnostic_states = {}
    if _table_exists(con, 'paper_mint_audit'):
        for mint, raw in con.execute('SELECT mint,report_json FROM paper_mint_audit'):
            if mint in undated:
                try:
                    state = json.loads(raw).get('launch_observation', {}).get('status', 'pending')
                except (ValueError, TypeError, AttributeError):
                    state = 'unreadable_audit'
                diagnostic_states[state] = diagnostic_states.get(state, 0) + 1
    report['launch_time_diagnostics'] = {
        'dated_mints': len(dated), 'undated_mints': len(undated),
        'dated_candidate_rows': sum(r['verified_time'] is not None for r in records),
        'undated_candidate_rows': sum(r['verified_time'] is None for r in records),
        'undated_only_mints': len(undated-dated),
        'undated_mints_with_quotes': len(undated & observed),
        'undated_mints_excluded_from_new_entries': len(undated-dated),
        'undated_candidate_rows_excluded_from_new_entries': sum(r['verified_time'] is None for r in records),
        'undated_status_counts': diagnostic_states,
        'undated_mints_without_audit': len(undated)-sum(diagnostic_states.values()),
    }
    from bot.analyser.functional_report import build_functional_report
    report['functional_dashboard'] = build_functional_report(
        con, data_kind=data_kind, latency_samples_ms=latency_samples_ms)
    from bot.master_audit import master_report
    master_summary = master_report(con)
    if master_summary is not None:
        report['master_shadow'] = master_summary
    if operational_health is not None:
        report['operational_health'] = operational_health
    if output:
        _write_json_report(output, report)
    return report


def shadow_baseline_model():
    """Diagnostic PAPER model; never eligible for real orders."""
    return {
        'creator_scores': {},
        'fallback_score': 0.01,
        'tp_pct': 10.0,
        'sl_pct': 10.0,
        'hold_seconds': 3600,
        'cost_bps': 200,
    }


def ensure_signal_status_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS paper_signal_status (
      mint TEXT PRIMARY KEY,
      creator TEXT,
      signal_time INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      status TEXT NOT NULL,
      detail TEXT,
      attempts INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_paper_signal_status_updated
      ON paper_signal_status(updated_at);
    ''')


def set_signal_status(con, mint, creator, signal_time, now, status, detail=None):
    """Persist every live signal outcome and return a message on status change."""
    previous = con.execute(
        'SELECT status,detail FROM paper_signal_status WHERE mint=?', (mint,)
    ).fetchone()
    con.execute(
        '''INSERT INTO paper_signal_status(
             mint,creator,signal_time,updated_at,status,detail,attempts)
           VALUES(?,?,?,?,?,?,1)
           ON CONFLICT(mint) DO UPDATE SET
             creator=excluded.creator, signal_time=excluded.signal_time,
             updated_at=excluded.updated_at, status=excluded.status,
             detail=excluded.detail, attempts=paper_signal_status.attempts+1''',
        (mint, creator or '', int(signal_time), int(now), str(status), detail),
    )
    if previous is None or previous[0] != status:
        suffix = f' ({detail})' if detail else ''
        return f'[PIPELINE] {mint[:12]} -> {status}{suffix}'
    return None


def ensure_audit_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS paper_mint_audit (
        mint TEXT PRIMARY KEY, observed_at INTEGER NOT NULL,
        outcome TEXT NOT NULL, report_json TEXT NOT NULL
    )""")


def audit_mint(con, mint, creator, signal_time, now, outcome, *, quote=None,
               features=None, decision=None, pool_state=None, reason=None,
               prior_launches=None, behavior=None, launch_observation=None,
               undated_identities=None):
    """An explicit decision record; missing measurements stay null, never zero."""
    ensure_audit_schema(con)
    report = {
        'mint': mint, 'creator_candidate': creator,
        'signal_time': int(signal_time) if signal_time is not None else None,
        'observed_at': int(now),
        'age_seconds': max(0, int(now) - int(signal_time)) if signal_time is not None else None,
        'pool_state': pool_state, 'decision_finale': outcome,
        'raison': reason, 'prix_usd': getattr(quote, 'price_usd', None),
        'liquidite_usd': getattr(quote, 'liquidity_usd', None),
        'volume_5m_usd': getattr(quote, 'volume_5m_usd', None),
        'quote_source': getattr(quote, 'quote_source', None),
        'funding_usd': getattr(quote, 'funding_usd', None),
        'volume_24h_usd': getattr(quote, 'volume_24h_usd', None),
        'market_cap_usd': getattr(quote, 'market_cap_usd', None),
        'prior_launches': prior_launches,
        'comportement': behavior,
        'features': asdict(features) if features is not None else None,
        'score': decision.score if decision is not None else None,
        'risques': list(decision.risk_flags) if decision is not None else None,
        'motifs': list(decision.reasons) if decision is not None else None,
        'tp_pct': decision.tp_pct if decision is not None and decision.enter else None,
        'sl_pct': decision.sl_pct if decision is not None and decision.enter else None,
    }
    if launch_observation is not None:
        report['launch_observation'] = launch_observation
    if undated_identities is not None:
        report['undated_identities'] = undated_identities
    con.execute("""INSERT INTO paper_mint_audit(mint,observed_at,outcome,report_json)
        VALUES(?,?,?,?) ON CONFLICT(mint) DO UPDATE SET
        observed_at=excluded.observed_at, outcome=excluded.outcome,
        report_json=excluded.report_json""",
        (mint, int(now), outcome, json.dumps(report, ensure_ascii=False, default=str)))
    return report


def audit_message(report):
    def show(v):
        return 'N/D' if v is None else str(v)
    market_label = ('funding' if report.get('quote_source') == 'launchlab_curve' else 'liquidite')
    market_value = (report.get('funding_usd') if market_label == 'funding' else report.get('liquidite_usd'))
    return (f"[ANALYSE] {report['mint'][:12]} | prix=${show(report['prix_usd'])} "
            f"| {market_label}=${show(market_value)} "
            f"| volume5m=${show(report['volume_5m_usd'])} "
            f"| createur_precedents={show(report['prior_launches'])} "
            f"| score={show(report['score'])} "
            f"| DECISION={report['decision_finale']} "
            f"| raison={show(report['raison'])}")


async def _observe_undated(con, session, record, max_age):
    """Price observations only: no features, decision, fake signal or bankroll."""
    mint, creator = record['mint'], record['deployer_candidate']
    quote, wait = None, 0
    if record['queue_state'] == 'observable':
        if record['pool_state']:
            try:
                quote = await fetch_onchain_quote(session, mint, record['pool_state'])
            except Exception as exc:
                print(f'[ONCHAIN] lecture indisponible : {type(exc).__name__}', flush=True)
        if quote is None:
            quote, wait = await fetch_quote(session, mint, min_liquidity=0, include_metrics=True)
    now = int(time.time())
    received = record['received_at']
    state = record['queue_state']
    if state == 'observable' and received is not None:
        if now < received:
            state, quote = 'reception_invalid', None
        elif now-received > max(1, int(max_age)):
            state, quote = 'reception_expired', None
    status = ('NON_DATE_PRIX_EN_ATTENTE' if wait else 'NON_DATE_PRIX_OBSERVE' if quote
              else 'NON_DATE_PRIX_ABSENT' if state == 'observable' else 'NON_DATE_' + state.upper())
    with _paper_close_transaction(con):
        # Another collector may have opened a position during price I/O. Its
        # original signal/model must remain managed by the position lane.
        active = con.execute("SELECT 1 FROM paper_trades WHERE mint=? AND status='open'", (mint,)).fetchone()
        if active:
            return [], wait
        if quote and not wait:
            if skip_recorded_quote(con, mint, now, quote):
                return [], wait
            record_quote(con, mint, creator, None, now, quote, None, allow_entry=False)
        observation = dict(status=status, launch_time_verified=False,
                           entry_allowed=False, reception_timestamp=received,
                           reception_source='launch_candidates.detected_at',
                           reception_signature=record['reception_signature'],
                           queue_age_seconds=now-received if received is not None and now >= received else None,
                           quote_timestamp=now if quote and not wait else None,
                           fingerprint=record['fingerprint'], identities=record['identities'])
        report = audit_mint(con, mint, creator, None, now, 'OBSERVATION_NON_DATEE',
                            quote=quote if not wait else None, pool_state=record['pool_state'],
                            reason='block_time non verifie; nouvelle entree PAPER interdite; ' + status,
                            launch_observation=observation)
    return [audit_message(report)], wait


def _record_runtime_latency(samples, stage, started_ns):
    """Bounded in-memory rolling sample, measured with a monotonic clock."""
    if samples is not None:
        values = samples.setdefault(stage, [])
        values.append((time.perf_counter_ns() - started_ns) / 1_000_000)
        del values[:-1024]


async def collect_once(con, session, cached, now, model=None,
                       max_open=3, max_entries_day=20,
                       max_daily_loss_pct=10.0, max_candidates=10,
                       max_age=7200, live_fetcher=None,
                       min_liquidity=1000, strategy_mode='validated',
                       initial_capital_sol=10.0, position_pct=10.0,
                       entry_guard=None, *, quote_provider=None,
                       onchain_quote_provider=None, clock=None, latency_samples_ms=None,
                       inventory_provider=None, master_shadow=None):
    """Collect one bounded cycle; providers default to the production readers.

    Explicit providers and a clock allow deterministic integration without HTTP.
    Selection, risk guards, persistence and accounting follow the same path.
    """
    quote_reader = quote_provider or fetch_quote
    onchain_reader = onchain_quote_provider or fetch_onchain_quote
    read_clock = clock or (lambda: time.time())
    records = _launch_records(con, now)
    undated = _undated_candidates(con, now, max_age, records)
    candidates = _scheduled_candidates(con, now, max_age, max_candidates,
                                       records=records, undated=undated)
    cache_changed = False
    messages = []
    cooldown = 0
    for mint, creator, signal_time, lane in candidates:
        _mark_collection_attempt(con, mint, lane)
        if signal_time is None:
            observed_messages, wait = await _observe_undated(con, session, undated[mint], max_age)
            messages.extend(observed_messages)
            cooldown = max(cooldown, wait)
            continue
        undated_identities = undated[mint]['identities'] if mint in undated else None
        matching_launches = [r for r in records if r['mint'] == mint
                            and r['deployer_candidate'] == creator
                            and r['verified_time'] == signal_time]
        pool_row = con.execute(
            "SELECT pool_state FROM launch_candidates WHERE mint=? ORDER BY id DESC LIMIT 1",
            (mint,),
        ).fetchone() if "pool_state" in {r[1] for r in con.execute("PRAGMA table_info(launch_candidates)")} else None
        pool_address = (matching_launches[-1]['pool_state'] if matching_launches
                        else pool_row[0] if pool_row else None)
        acquisition_started = time.perf_counter_ns()
        quote = None
        if pool_address:
            try:
                quote = await onchain_reader(session, mint, pool_address)
            except Exception as exc:
                print(f"[ONCHAIN] lecture indisponible : {type(exc).__name__}", flush=True)
        wait_seconds = 0
        if quote is None:
            quote, wait_seconds = await quote_reader(
            session, mint, min_liquidity=min_liquidity, include_metrics=True,
        )
        _record_runtime_latency(latency_samples_ms, 'quote_acquisition', acquisition_started)
        cooldown = max(cooldown, wait_seconds)
        status_now = int(read_clock())
        if wait_seconds:
            msg = set_signal_status(
                con, mint, creator, signal_time, status_now,
                'PRIX_EN_ATTENTE', f'cooldown={int(wait_seconds)}s',
            )
            if msg:
                messages.append(msg)
            # API cooldown is not an entry; record a safe provisional rejection.
            report = audit_mint(con, mint, creator, signal_time, status_now,
                'REJET_PROVISOIRE', pool_state=pool_address,
                reason=f'prix indisponible; cooldown={int(wait_seconds)}s',
                prior_launches=prior_creator_launches(con, creator, signal_time),
                behavior=behavior_snapshot(cached, mint, creator, signal_time, status_now),
                undated_identities=undated_identities)
            if msg:
                messages.append(audit_message(report))
            continue
        if not quote:
            age = max(0, status_now - int(signal_time))
            status = 'PRIX_NON_INDEXE' if age <= max_age else 'PRIX_INDISPONIBLE'
            msg = set_signal_status(
                con, mint, creator, signal_time, status_now, status,
                f'age={age}s; nouvelle tentative automatique',
            )
            if msg:
                messages.append(msg)
            report = audit_mint(con, mint, creator, signal_time, status_now,
                'REJET_PROVISOIRE', pool_state=pool_address,
                reason='aucun prix vérifié; entrée PAPER interdite',
                prior_launches=prior_creator_launches(con, creator, signal_time),
                behavior=behavior_snapshot(cached, mint, creator, signal_time, status_now),
                undated_identities=undated_identities)
            if msg:
                messages.append(audit_message(report))
            continue
        now_quote = status_now
        msg = set_signal_status(
            con, mint, creator, signal_time, now_quote, 'PRIX_OK',
            (f'funding=${quote.funding_usd:.2f}' if getattr(quote, 'quote_source', '') == 'launchlab_curve'
             else f'liq=${quote.liquidity_usd:.0f}'),
        )
        if msg:
            messages.append(msg)
        # Price discovery is latency-sensitive. Enrich creator behaviour only
        # after the mint is actually observable, never before quote discovery.
        if live_fetcher and creator:
            changed = await live_fetcher.refresh(creator)
            cache_changed = changed or cache_changed
            if changed:
                cached = load_cached_transactions(live_fetcher.db_path)
        inventory_context = None
        if inventory_provider is not None:
            from bot.analyser.token_inventory import inventory_state, _lamports
            from bot.analyser.paper_trader import _paper_free_capital
            state_before = inventory_state(con, mint)
            amount = state_before['remaining_atomic'] if state_before else None
            if state_before is None:
                try:
                    if con.execute('SELECT 1 FROM paper_portfolio WHERE id=1').fetchone():
                        capital, free = _paper_free_capital(con)
                    else:
                        capital = free = float(initial_capital_sol)
                    amount = str(_lamports(min(free, capital*float(position_pct)/100)))
                except ValueError:
                    pass  # Unknown liabilities must not invent a buy budget.
            if amount is not None and int(amount) > 0:
                # Providers receive the exact size BEFORE their request. They may
                # explicitly preselect a partial size, never scale a response.
                inventory_context = await inventory_provider(session, mint,
                    side='sell' if state_before else 'buy', amount_atomic=amount,
                    inventory=state_before, decision_at_ms=int(read_clock()*1000))
                if inventory_context is not None:
                    inventory_context = dict(inventory_context)
                    inventory_context['inventory_version'] = state_before['version'] if state_before else 0
                    inventory_context['decision_at_ms'] = int(read_clock()*1000)
            now_quote = int(read_clock())
        # No await inside: serialize the history check, features, decision and ledger.
        with _paper_close_transaction(con):
            if skip_recorded_quote(con, mint, now_quote, quote):
                continue
            existing = con.execute(
                'SELECT status FROM paper_trades WHERE mint=?', (mint,)
            ).fetchone()
            current_records = _launch_records(con, now_quote, mint=mint)
            if not (existing and existing[0] == 'open') and not any(
                    r['verified_time'] == signal_time and r['deployer_candidate'] == creator
                    and r['pool_state'] == pool_address for r in current_records):
                # Source/identity may have changed during quote/enrichment I/O.
                # Refuse before features or strategy; do not reuse a stale date.
                report = audit_mint(con, mint, creator, None, now_quote,
                    'OBSERVATION_NON_DATEE', pool_state=pool_address,
                    reason='identite ou date devenue non verifiee; nouvelle entree PAPER interdite',
                    launch_observation=dict(status='NON_DATE_IDENTITE_OU_DATE_MODIFIEE',
                                            launch_time_verified=False, entry_allowed=False,
                                            quote_timestamp=None))
                messages.append(audit_message(report))
                continue
            decision = None
            features = None
            model_for_quote = model
            force_exit_reason = None
            if strategy_mode == 'shadow_final':
                features = build_features(
                    cached, mint, creator, signal_time, now_quote,
                    price_history(con, mint), quote,
                    prior_launches=prior_creator_launches(con, creator, signal_time),
                )
                decision = decide(features, min_liquidity=min_liquidity)
            # All asynchronous enrichment is finished. The same permission is
            # recorded and passed to the ledger, under the same SQLite lock.
            financial_allowed = bool(existing) or entry_allowed(
                con, now_quote, max_open=max_open,
                max_entries_day=max_entries_day,
                max_daily_loss_pct=max_daily_loss_pct,
            )
            scanner_allowed = _entry_guard_allows(entry_guard, con)
            allowed = financial_allowed and scanner_allowed
            master_event = None
            if master_shadow is not None:
                from bot.master_audit import paper_context, shadow_attempt
                def evaluate_shadow():
                    master_features = features if features is not None else build_features(
                        cached,mint,creator,signal_time,now_quote,price_history(con,mint),quote,
                        prior_launches=prior_creator_launches(con,creator,signal_time))
                    health_snapshot=(entry_guard.operational_snapshot(con)
                        if isinstance(entry_guard,_ScannerEntryGuard) else dict(
                            allow_new_entries=scanner_allowed,blocking_reasons=[],
                            observed_at_ms=int(read_clock()*1000),scope='existing_entry_guard_result_only'))
                    frame,inventory,health_snapshot,capital=paper_context(con,mint=mint,creator=creator,
                        pool=pool_address,signal_time=signal_time,decision_ms=int(read_clock()*1000),
                        features=master_features,inventory_context=inventory_context,health=health_snapshot,
                        financial_allowed=financial_allowed)
                    from bot.master_comparison import reference_position_intent
                    reference_model=decision.to_paper_model() if decision is not None else model
                    ref_action=('BUY' if decision is not None and decision.enter and allowed
                        else 'NO_TRADE' if decision is not None and not decision.enter else 'WAIT')
                    ref_reasons=(list(decision.reasons) if decision is not None else
                        ['legacy_reference_entry_intent_not_reconstructed'])
                    if existing:
                        ref_forced=None
                        if decision is not None and 'vente_developpeur' in decision.risk_flags:ref_forced='DEV_SALE_RISK'
                        elif decision is not None and 'transfert_relais' in decision.risk_flags:ref_forced='RELAY_RISK'
                        ref_action,ref_reason=reference_position_intent(con,mint,int(read_clock()*1000),
                            quote.price_usd,reference_model,forced=ref_forced)
                        ref_reasons=[ref_reason]
                    contemplated=None
                    if ref_action=='BUY':
                        from bot.analyser.paper_trader import _paper_free_capital
                        from bot.analyser.token_inventory import _lamports
                        if con.execute('SELECT 1 FROM paper_portfolio WHERE id=1').fetchone():
                            ref_capital,ref_free=_paper_free_capital(con)
                        else:ref_capital=ref_free=initial_capital_sol
                        contemplated=str(_lamports(min(ref_free,ref_capital*float(position_pct)/100)))
                    reference=dict(action=ref_action,selected_strategy='reference_current',
                        score=decision.score if decision is not None else None,
                        risks=list(decision.risk_flags) if decision is not None else None,
                        input_lamports=contemplated,quantity_atomic=None,
                        costs=frame.get('inventory_context',{}).get('fees'),
                        exit_conditions=reference_model,reasons=ref_reasons,
                        observed_at_ms=frame['available_at_ms'],intent_only=True,
                        funding_and_exact_quote_checks_pending=True,
                        execution_verified=False,promotion_allowed=False)
                    return master_shadow.evaluate(con,frame,inventory=inventory,
                        health=health_snapshot,capital=capital,reference=reference,measure_latency=True)
                shadow_result,shadow_error=shadow_attempt(con,evaluate_shadow)
                if shadow_error is not None:
                    allowed=False
                    messages.append(f'MASTER_SHADOW_UNAVAILABLE {shadow_error}')
                else:
                    master_event,_proposal=shadow_result
            if strategy_mode == 'shadow_final':
                record_decision(
                    con, features, decision, strategy_mode=strategy_mode,
                    entry_permission=allowed,
                )
                report = audit_mint(con, mint, creator, signal_time, now_quote,
                    'ENTRY_PAPER_AUTORISEE' if decision.enter and allowed else 'REJET',
                    quote=quote, features=features, decision=decision,
                    pool_state=pool_address,
                    reason='score et règles de risque' if decision.enter and allowed
                        else 'scanner: entrees PAPER interdites' if not scanner_allowed
                        else '; '.join(decision.reasons) or 'risque ou limites PAPER',
                    prior_launches=features.prior_launches,
                    behavior=behavior_snapshot(cached, mint, creator, signal_time, now_quote),
                    undated_identities=undated_identities)
                if _emit_analysis_once(mint, report, now_quote):
                    messages.append(audit_message(report))
                outcome = 'DECISION_ENTRY' if decision.enter and allowed else 'REJET'
                detail = (
                    f'score={decision.score:.1f}; '
                    f"risk={','.join(decision.risk_flags) or 'none'}"
                )
                msg = set_signal_status(
                    con, mint, creator, signal_time, now_quote, outcome, detail,
                )
                if msg:
                    messages.append(msg)
                # An existing position must still be managed even if the next
                # observation becomes a rejection. New positions require entry.
                if decision.enter or existing:
                    model_for_quote = decision.to_paper_model()
                else:
                    model_for_quote = None
                if existing and 'vente_developpeur' in decision.risk_flags:
                    force_exit_reason = 'DEV_SALE_RISK'
                elif existing and 'transfert_relais' in decision.risk_flags:
                    force_exit_reason = 'RELAY_RISK'
            message = record_quote(
                con, mint, creator, signal_time, now_quote, quote, model_for_quote,
                allow_entry=allowed, strategy_mode=strategy_mode,
                force_exit_reason=force_exit_reason,
                initial_capital_sol=initial_capital_sol, position_pct=position_pct,
                max_open=max_open, max_entries_day=max_entries_day,
                max_daily_loss_pct=max_daily_loss_pct,
                inventory_context=inventory_context,
                require_inventory=inventory_provider is not None,
            )
            if master_event is not None:
                from bot.master_audit import complete_master_reference, shadow_attempt
                def complete_shadow_reference():
                    from bot.analyser.token_inventory import inventory_state
                    after=inventory_state(con,mint)
                    complete_master_reference(con,master_event,dict(proposal_applied=False,
                        reference_engine_result=message,
                        remaining_atomic=after['remaining_atomic'] if after else None,
                        inventory_version=after['version'] if after else None))
                _,shadow_error=shadow_attempt(con,complete_shadow_reference)
                if shadow_error is not None:
                    messages.append(f'MASTER_SHADOW_OUTCOME_PENDING {shadow_error}')
            if undated_identities and strategy_mode != 'shadow_final':
                report = audit_mint(con, mint, creator, signal_time, now_quote,
                    'OBSERVATION_DATEE_AVEC_IDENTITES_NON_DATEES', quote=quote,
                    pool_state=pool_address,
                    reason='seule l identite datee fournit le signal; autres creations non datees',
                    undated_identities=undated_identities)
                messages.append(audit_message(report))
            snapshot = behavior_snapshot(cached, mint, creator, signal_time, now_quote)
            if message and message.startswith('ENTRY '):
                status_msg = set_signal_status(
                    con, mint, creator, signal_time, now_quote,
                    'TRADE_PAPER_OUVERT', 'position virtuelle ouverte',
                )
                if status_msg:
                    messages.append(status_msg)
            elif message and message.startswith('EXIT '):
                status_msg = set_signal_status(
                    con, mint, creator, signal_time, now_quote,
                    'TRADE_PAPER_FERME', message.split(' reason=', 1)[-1][:120],
                )
                if status_msg:
                    messages.append(status_msg)
            if message:
                if decision:
                    message = (
                        f"{message} score={decision.score:.1f}/100 "
                        f"risk={','.join(decision.risk_flags) or 'none'}"
                    )
                messages.append(message)
            if snapshot['dev_sales'] or snapshot['relay_transfers']:
                messages.append(
                    f"BEHAVIOR {mint[:12]} dev_sales={snapshot['dev_sales']} "
                    f"relay={snapshot['relay_transfers']}"
                )
    con.commit()
    return messages, cooldown, cache_changed



def _session_summary(con, started_at, ended_at):
    """Metrics limited to one PAPER validation session."""
    decisions = con.execute(
        "SELECT mint,enter,risk_flags_json FROM paper_decisions WHERE decision_time>=? AND decision_time<=?",
        (int(started_at), int(ended_at)),
    ).fetchall()
    entries = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE entry_time>=? AND entry_time<=?",
        (int(started_at), int(ended_at)),
    ).fetchone()[0]
    open_positions = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE entry_time<=? "
        "AND (status='open' OR (status='closed' AND exit_time>?))",
        (int(ended_at), int(ended_at)),
    ).fetchone()[0]
    metrics = _realized_metrics(con, int(started_at), int(ended_at))
    reasons = {}
    for _mint, enter, raw in decisions:
        if int(enter):
            continue
        try:
            vals = json.loads(raw or '[]')
        except Exception:
            vals = []
        for reason in vals if isinstance(vals, list) else []:
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
    return {
        'session_started_at': int(started_at), 'session_ended_at': int(ended_at),
        'duration_seconds': int(ended_at-started_at),
        'decisions': len(decisions),
        'unique_candidates': len({r[0] for r in decisions}),
        'rejections': sum(1 for r in decisions if not int(r[1])),
        'accepted_decisions': sum(1 for r in decisions if int(r[1])),
        'accepted_candidates': len({r[0] for r in decisions if int(r[1])}),
        'entries': entries, 'open_positions': open_positions,
        **metrics,
        # Legacy key retained for report consumers; now a portfolio return.
        'net_return_compounded': metrics['net_return_after_costs'],
        'equity_basis': 'realized_sol',
        'valuation_scope': _valuation_scope(),
        'rejection_reasons': dict(sorted(reasons.items(), key=lambda x:(-x[1],x[0]))),
    }

def _print_session_summary(summary, initial_capital, final_capital):
    pct = lambda v: 'N/D' if v is None else f'{100*v:.2f}%'
    pf = summary['profit_factor']
    pf_txt = 'N/D' if pf is None else ('inf' if pf == float('inf') else f'{pf:.2f}')
    print('\n' + '='*62, flush=True)
    print('BILAN SESSION PAPER', flush=True)
    print('='*62, flush=True)
    print(f"Duree               : {summary['duration_seconds']} s", flush=True)
    print(f"Evaluations          : {summary['decisions']}", flush=True)
    print(f"Candidats uniques     : {summary['unique_candidates']}", flush=True)
    print(f"Rejets / acceptations: {summary['rejections']} / {summary['accepted_decisions']}", flush=True)
    print(f"Candidats acceptes    : {summary['accepted_candidates']}", flush=True)
    print(f"Entrees PAPER        : {summary['entries']}", flush=True)
    print(f"Trades clos / ouverts: {summary['closed_trades']} / {summary['open_positions']}", flush=True)
    print(f"Gagnants / perdants  : {summary['wins']} / {summary['losses']}", flush=True)
    print(f"Winrate              : {pct(summary['win_rate'])}", flush=True)
    pnl_text = 'N/D' if summary['pnl_sol'] is None else f"{summary['pnl_sol']:+.6f} SOL"
    print(f"PnL net              : {pnl_text}", flush=True)
    print(f"Profit factor        : {pf_txt}", flush=True)
    print(f"Drawdown max         : {pct(summary['max_drawdown'])}", flush=True)
    print(f"Capital              : {initial_capital:.6f} -> {final_capital:.6f} SOL", flush=True)
    top = list(summary['rejection_reasons'].items())[:5]
    print('Top rejets           : ' + (', '.join(f'{k}={v}' for k,v in top) if top else 'N/D'), flush=True)
    if not summary.get('performance_data_complete', True):
        conclusion = 'INSUFFISANT : historique financier incomplet ou incoherent.'
    elif summary['closed_trades'] == 0:
        conclusion = 'INSUFFISANT : aucun trade PAPER cloture pendant la session.'
    elif summary['closed_trades'] < 5:
        conclusion = 'INSUFFISANT : echantillon de trades trop faible pour conclure.'
    elif summary['pnl_sol'] > 0 and (summary['profit_factor'] or 0) > 1:
        conclusion = 'POSITIF EN PAPER : poursuivre la validation, aucun passage en reel.'
    else:
        conclusion = 'A REVOIR : performance PAPER insuffisante sur cette session.'
    print('Conclusion           : ' + conclusion, flush=True)
    print('='*62, flush=True)
    return conclusion

async def run(db, model_path=None, poll=15, report=None, max_open=3,
              max_entries_day=20, max_daily_loss_pct=10.0,
              max_candidates=10, max_age=7200, cache_refresh=60,
              live_behavior=True, rpc_interval=2.5, behavior_max_tx=10,
              rpc_gate=None, min_liquidity=1000, shadow_baseline=False,
              shadow_final=False, initial_capital_sol=10.0, position_pct=10.0,
              session_seconds=0, session_report=None, entry_guard=None, inventory_journal=None,
              master_shadow_enabled=False):
    """Run the paper collector forever; no model means collection only."""
    if shadow_baseline and shadow_final:
        raise ValueError('Choisir un seul mode shadow.')
    strategy_mode = (
        'shadow_final' if shadow_final
        else 'shadow_baseline' if shadow_baseline
        else 'validated'
    )
    if shadow_final:
        model = None
    elif shadow_baseline:
        model = shadow_baseline_model()
    else:
        model = eligible_model(model_path) if model_path else None
    if inventory_journal is not None:
        journal_path = Path(inventory_journal)
        if (journal_path.exists() or journal_path.is_symlink()
                or journal_path.suffix not in ('.sqlite','.db') or journal_path.name.startswith('.env')
                or not 1 <= session_seconds <= 60
                or journal_path.resolve() in {Path(db).resolve(), Path(report or db).resolve(),
                                              Path(session_report or db).resolve()}):
            raise ValueError('Native quotes require a new separate journal and a 1..60 second session')
    con = session = live_fetcher = native_capture = None
    native_provider = None
    session_ready = False
    failures = []
    stage = 'database initialization'
    try:
        Database(db)
        ensure_schema(db)
        con = sqlite3.connect(db, timeout=30.0, isolation_level=None)
        con.execute('PRAGMA busy_timeout=30000')
        setup(con)
        master_shadow=None
        if master_shadow_enabled:
            from bot.master_audit import setup_master_schema,MasterShadow
            setup_master_schema(con)
            master_shadow=MasterShadow()
        ensure_signal_status_schema(con)
        ensure_audit_schema(con)
        ensure_paper_portfolio(con, initial_capital_sol)
        session_started = int(time.time())
        session_initial_capital = float(paper_capital(con)[1] or initial_capital_sol)
        session_ready = True
        if session_seconds:
            print(f'[SESSION] validation PAPER limitee a {int(session_seconds)} secondes.', flush=True)
        cached = []
        latency_samples = {}
        refreshed_at = 0
        if live_behavior:
            stage = 'behavior initialization'
            try:
                live_fetcher = LiveBehaviorFetcher(
                    db, interval=rpc_interval, max_tx=behavior_max_tx,
                    refresh_seconds=cache_refresh, gate=rpc_gate,
                )
            except Exception as exc:
                # Keep the existing optional behavior when settings are absent.
                # The constructor acquires no session; start() does.
                print(f'[BEHAVIOR] désactivé : {type(exc).__name__}', flush=True)
            if live_fetcher is not None:
                await live_fetcher.start()
                print(
                    f'Comportements Helius : actif, cadence minimale {live_fetcher.interval:.2f}s, '
                    f'{live_fetcher.max_tx} transactions/créateur.', flush=True,
                )
        print('PAPER ONLY : aucun ordre réel, aucune clé privée, aucune signature.', flush=True)
        if shadow_final:
            mode_message = 'PAPER final diagnostic (comportements + wallets + marché)'
        elif shadow_baseline:
            mode_message = 'PAPER diagnostic shadow (TP 10% / SL 10% / 1h)'
        else:
            mode_message = 'modèle validé simulé' if model else 'collecte prix/comportements seulement'
        print('Mode : ' + mode_message, flush=True)
        stage = 'HTTP initialization'
        timeout = aiohttp.ClientTimeout(total=12)
        options = {'trust_env':False,'cookie_jar':aiohttp.DummyCookieJar()} if inventory_journal is not None else {}
        session = aiohttp.ClientSession(timeout=timeout,**options)
        await session.__aenter__()
        if inventory_journal is not None:
            from bot.p3.store import CaptureStore
            from bot.p3.inventory_provider import NativeInventoryQuoteProvider
            if type(getattr(session,'_retry_connection',None)) is not bool:
                raise ValueError('Unsupported native quote transport retry policy')
            session._retry_connection = False
            native_capture = CaptureStore(inventory_journal)
            native_provider = NativeInventoryQuoteProvider(session,native_capture,max_requests=20)
        while True:
            now = int(time.time())
            if session_seconds and now - session_started >= int(session_seconds):
                break
            stage = 'cache refresh'
            if now - refreshed_at >= max(1, int(cache_refresh)):
                cached = load_cached_transactions(db)
                refreshed_at = now
            stage = 'collection'
            cycle_started = time.perf_counter_ns()
            try:
                messages, cooldown, cache_changed = await collect_once(
                    con, session, cached, now, model=model,
                    max_open=max_open, max_entries_day=max_entries_day,
                    max_daily_loss_pct=max_daily_loss_pct,
                    max_candidates=max_candidates, max_age=max_age,
                    live_fetcher=live_fetcher,
                    min_liquidity=min_liquidity,
                    strategy_mode=strategy_mode,
                    initial_capital_sol=initial_capital_sol, position_pct=position_pct,
                    entry_guard=entry_guard, latency_samples_ms=latency_samples,
                    inventory_provider=native_provider,
                    master_shadow=master_shadow,
                )
                if cache_changed:
                    cached = load_cached_transactions(db)
                    refreshed_at = now
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                print('[PAPER] source prix temporairement lente; nouvelle tentative automatique.', flush=True)
                cooldown = 3
            else:
                _record_runtime_latency(latency_samples, 'collection_cycle', cycle_started)
                stage = 'periodic report'
                state = paper_report(
                    con, now, len(cached), output=report,
                    strategy_mode=strategy_mode,
                    latency_samples_ms=latency_samples,
                    operational_health=(entry_guard.operational_snapshot(con)
                        if isinstance(entry_guard, _ScannerEntryGuard) else None),
                    validation_status=(
                        'diagnostic_not_validated'
                        if strategy_mode.startswith('shadow_')
                        else 'oos_guard_passed' if model
                        else 'not_validated'
                    ),
                )
                print(
                    f"[PAPER] quotes={state['quotes_recorded']} "
                    f"open={state['open_paper_positions']} "
                    f"cache_tx={state['cached_helius_transactions']}",
                    flush=True,
                )
                for message in messages:
                    print(message, flush=True)

            await asyncio.sleep(max(1, int(poll), int(cooldown)))
    except BaseException as exc:
        failures.append((stage, exc))
    finally:
        async def cleanup():
            # Every acquired handle gets one independent close attempt.
            if session is not None:
                try:
                    await session.close()
                except BaseException as exc:
                    failures.append(('HTTP close', exc))
            if native_capture is not None:
                try:
                    native_capture.close()
                except BaseException as exc:
                    failures.append(('native journal close', exc))
            if live_fetcher is not None:
                try:
                    await live_fetcher.close()
                except BaseException as exc:
                    failures.append(('behavior close', exc))
            summary = None
            if session_seconds and session_ready:
                try:
                    ended = int(time.time())
                    summary = _session_summary(con, session_started, ended)
                    _initial, final_capital = paper_capital(con)
                    final_capital = float(final_capital or 0.0)
                    summary['capital_start_sol'] = session_initial_capital
                    summary['capital_end_sol'] = final_capital
                except BaseException as exc:
                    summary = None
                    failures.append(('session summary', exc))
            if con is not None:
                try:
                    con.close()
                except BaseException as exc:
                    failures.append(('SQLite close', exc))
            # Publish only after the close attempts. Never label a failed run positive.
            if summary is not None:
                try:
                    if failures:
                        cancelled = any(isinstance(e, asyncio.CancelledError) for _, e in failures)
                        conclusion = ('ANNULEE' if cancelled else 'ECHEC') + ': session PAPER interrompue.'
                        print('[SESSION] ' + conclusion, flush=True)
                    else:
                        conclusion = _print_session_summary(summary, session_initial_capital, final_capital)
                    summary['conclusion'] = conclusion
                    out = Path(session_report or (BASE_DIR / 'data' / 'paper_session_report.json'))
                    print(f'[SESSION] rapport: {out}', flush=True)
                    _write_json_report(out, summary, allow_nan=False)
                except BaseException as exc:
                    failures.append(('session report', exc))

        await _await_paper_cleanup(cleanup(), failures)
    _raise_paper_failures(failures)


async def run_with_scanner(args):
    from bot.main import run as scanner_run

    # One gate is shared by the scanner and behavior enrichment so parallel
    # tasks cannot independently burst the same Helius key.
    rpc_gate = AdaptiveRPCGate(max(1.1, float(args.rpc_interval)))

    if args.no_scanner:
        print('[SCANNER] mode autonome explicite; couverture des lancements non garantie.', flush=True)
        await run(
            args.db, model_path=args.model, poll=args.poll,
            report=args.report, max_open=args.max_open,
            max_entries_day=args.max_entries_day,
            max_daily_loss_pct=args.max_daily_loss,
            max_candidates=args.max_candidates, max_age=args.max_age,
            cache_refresh=args.cache_refresh,
            live_behavior=not args.no_live_behavior,
            rpc_interval=args.rpc_interval,
            behavior_max_tx=args.behavior_max_tx,
            rpc_gate=rpc_gate, min_liquidity=args.min_liquidity,
            shadow_baseline=args.shadow_baseline,
            shadow_final=args.shadow_final, initial_capital_sol=args.capital_sol,
            position_pct=args.position_pct, session_seconds=args.session_seconds,
            session_report=args.session_report,
            inventory_journal=getattr(args, 'inventory_journal', None),
            master_shadow_enabled=getattr(args,'master_shadow',False),
        )
        return
    tasks = []
    failures = []
    try:
        health = ScannerHealth(require_observations=True)
        scanner_task = asyncio.create_task(scanner_run(rpc_gate=rpc_gate, db_path=args.db, health=health))
        tasks.append(scanner_task)
        entry_guard = _ScannerEntryGuard(args.db, scanner_task, health=health)
        engine_task = asyncio.create_task(run(
            args.db, model_path=args.model, poll=args.poll,
            report=args.report, max_open=args.max_open,
            max_entries_day=args.max_entries_day,
            max_daily_loss_pct=args.max_daily_loss,
            max_candidates=args.max_candidates, max_age=args.max_age,
            cache_refresh=args.cache_refresh,
            live_behavior=not args.no_live_behavior,
            rpc_interval=args.rpc_interval, behavior_max_tx=args.behavior_max_tx,
            rpc_gate=rpc_gate, min_liquidity=args.min_liquidity,
            shadow_baseline=args.shadow_baseline, shadow_final=args.shadow_final,
            initial_capital_sol=args.capital_sol, position_pct=args.position_pct,
            session_seconds=args.session_seconds, session_report=args.session_report,
            entry_guard=entry_guard,
            inventory_journal=getattr(args, 'inventory_journal', None),
            master_shadow_enabled=getattr(args,'master_shadow',False),
        ))
        tasks.append(engine_task)
        last_scanner_state = None
        while True:
            done, _ = await asyncio.wait(
                (scanner_task, engine_task), timeout=1.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if scanner_task in done:
                print('[SCANNER] ECHEC : scanner arrete; entrees PAPER bloquees, arret du moteur.', flush=True)
                if scanner_task.cancelled():
                    raise RuntimeError('Scanner annule de facon inattendue')
                error = scanner_task.exception()
                if error is not None:
                    raise RuntimeError('Echec du scanner') from error
                raise RuntimeError('Scanner termine sans exception de facon inattendue')
            if engine_task in done:
                await engine_task
                break
            last_scanner_state = _print_scanner_state(args.db, last_scanner_state)
    except BaseException as exc:
        failures.append(('supervision', exc))
    finally:
        observed = []
        for _, error in failures:
            while error is not None and error not in observed:
                observed.append(error)
                error = error.__cause__
        await _await_paper_cleanup(_stop_supervised_tasks(tasks, observed=observed), failures)
    _raise_paper_failures(failures)


def _print_scanner_state(db, previous=None):
    """Observe existing SQLite state only; task liveness is not coverage."""
    try:
        with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True,
                                     timeout=0.1)) as con:
            rows = con.execute(
                'SELECT ws_state,history_status FROM scanner_backfill_state'
            ).fetchall()
    except sqlite3.Error:
        rows = []
    states = ', '.join(f'ws={ws} backfill={history}' for ws, history in rows)
    if states != previous:
        print('[SCANNER] ' + (states or 'etat SQLite inconnu') +
              '; couverture des lancements non garantie.', flush=True)
    return states




def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=BASE_DIR / 'data' / 'rugger_bot.db')
    parser.add_argument('--model', type=Path, help='JSON d’un modèle déjà validé hors échantillon')
    parser.add_argument('--report', type=Path, default=BASE_DIR / 'data' / 'paper_engine_report.json')
    parser.add_argument('--poll', type=int, default=15,
                        help='fréquence de cotation ; 1 s peut provoquer un 429')
    parser.add_argument('--max-open', type=int, default=3)
    parser.add_argument('--max-entries-day', type=int, default=20)
    parser.add_argument('--max-daily-loss', type=float, default=10.0)
    parser.add_argument('--max-candidates', type=int, default=10)
    parser.add_argument('--max-age', type=int, default=7200,
                        help='durée de suivi d’un lancement ; 7200 couvre l’horizon 1 h')
    parser.add_argument('--min-liquidity', type=float, default=1000,
                        help='liquidité minimale observée en USD ; les quotes restent PAPER')
    parser.add_argument('--shadow-baseline', action='store_true',
                        help='simuler des ENTRY/EXIT diagnostics (jamais un modèle validé)')
    parser.add_argument('--shadow-final', action='store_true',
                        help='PAPER diagnostique avec créateur, wallets, bundle et marché')
    parser.add_argument('--cache-refresh', type=int, default=60)
    parser.add_argument('--rpc-interval', type=float, default=2.5,
                        help='cadence minimale des appels Helius comportementaux')
    parser.add_argument('--behavior-max-tx', type=int, default=10,
                        help='transactions récentes observées par créateur')
    parser.add_argument('--capital-sol', type=float, default=10.0,
                        help='capital virtuel initial en SOL')
    parser.add_argument('--position-pct', type=float, default=10.0,
                        help='part du capital virtuel engagée par position')
    parser.add_argument('--session-seconds', type=int, default=0,
                        help='arrete automatiquement la session PAPER apres N secondes')
    parser.add_argument('--session-report', type=Path, default=BASE_DIR / 'data' / 'paper_session_report.json',
                        help='rapport JSON final de la session')
    parser.add_argument('--no-scanner', action='store_true',
                        help='ne pas lancer le scanner Helius dans ce processus')
    parser.add_argument('--no-live-behavior', action='store_true',
                        help='utiliser seulement le cache Helius déjà présent')
    parser.add_argument('--inventory-quotes', action='store_true',
                        help='P3 native SOL inventory quotes, maximum 20 attempts/60 s; never orders')
    parser.add_argument('--inventory-journal', type=Path,
                        help='New dedicated P3 quote journal, separate from the PAPER ledger')
    parser.add_argument('--master-shadow', action='store_true',
                        help='Journal bounded master proposals; active reference policy remains separate')
    args = parser.parse_args(argv)
    if bool(args.inventory_quotes) != bool(args.inventory_journal):
        parser.error('--inventory-quotes and a new --inventory-journal are required together')
    if args.inventory_quotes and not 1 <= args.session_seconds <= 60:
        parser.error('Native inventory quotes require --session-seconds between 1 and 60')
    try:
        asyncio.run(run_with_scanner(args))
    except KeyboardInterrupt:
        print('\nPaper engine arrêté.')


if __name__ == '__main__':
    main()
