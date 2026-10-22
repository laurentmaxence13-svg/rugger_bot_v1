"""Orchestrateur unique d'observation et de paper trading.

Ce programme regroupe le scanner LaunchLab et la collecte de prix/liquidité.
Il peut observer les comportements déjà présents dans le cache Helius, mais
ne signe jamais, ne détient aucune clé privée et n'envoie aucun ordre.
Sans modèle hors échantillon validé, il collecte uniquement les cotations.
"""

import argparse
import asyncio
import bisect
import json
from dataclasses import asdict
import sqlite3
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
    setup,
)
from bot.config import BASE_DIR, get_settings
from bot.database.db import Database
from bot.solana.rpc import SolanaRPC


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


def recent_candidates(con, now, max_age=900, limit=10):
    """Return fresh, strictly parsed launches for the observation loop."""
    return con.execute(
        '''SELECT mint,deployer_candidate,block_time
           FROM launch_candidates
           WHERE status='creator_identified' AND mint IS NOT NULL
             AND block_time BETWEEN ? AND ?
           ORDER BY block_time DESC LIMIT ?''',
        (int(now) - max(1, int(max_age)), int(now), max(1, int(limit))),
    ).fetchall()


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
    if not creator:
        return 0
    sources = [
        '''SELECT mint FROM launch_candidates
           WHERE deployer_candidate=? AND status='creator_identified'
             AND mint IS NOT NULL AND block_time IS NOT NULL
             AND block_time < ?''',
    ]
    params = [creator, int(signal_time)]
    # ``collect_once`` is also unit-testable with a minimal in-memory schema;
    # tolerate that schema while the production path creates this table via
    # ensure_schema().
    has_research = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_launches'"
    ).fetchone()
    if has_research:
        sources.append(
            '''SELECT mint FROM research_launches
               WHERE creator=? AND mint IS NOT NULL AND block_time IS NOT NULL
                 AND block_time < ?'''
        )
        params.extend([creator, int(signal_time)])
    row = con.execute(
        'SELECT COUNT(*) FROM (' + ' UNION '.join(sources) + ')',
        params,
    ).fetchone()
    return int(row[0] if row else 0)


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


def _performance_metrics(con):
    if not _table_exists(con, 'paper_trades'):
        return {
            'average_net_return': None,
            'net_return_after_costs': 0.0,
            'max_drawdown': 0.0,
            'win_rate': None,
            'assumed_cost_bps_total': 0.0,
            'pnl_sol': 0.0, 'profit_factor': None,
        }
    rows = con.execute(
        '''SELECT exit_time,net_return,cost_bps,pnl_sol
           FROM paper_trades
           WHERE status='closed' AND net_return IS NOT NULL
           ORDER BY exit_time,mint'''
    ).fetchall()
    if not rows:
        return {
            'average_net_return': None,
            'net_return_after_costs': 0.0,
            'max_drawdown': 0.0,
            'win_rate': None,
            'assumed_cost_bps_total': 0.0,
            'pnl_sol': 0.0, 'profit_factor': None,
        }
    returns = [float(row[1]) for row in rows]
    pnl_sol = [float(row[3] or 0.0) for row in rows]
    gross_profit = sum(v for v in pnl_sol if v > 0)
    gross_loss = -sum(v for v in pnl_sol if v < 0)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else None)
    equity = peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    return {
        'average_net_return': sum(returns) / len(returns),
        'net_return_after_costs': equity - 1.0,
        'max_drawdown': max_drawdown,
        'win_rate': sum(value > 0 for value in returns) / len(returns),
        'assumed_cost_bps_total': sum(float(row[2] or 0) for row in rows),
        'pnl_sol': sum(pnl_sol),
        'profit_factor': profit_factor,
    }


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


def paper_report(con, now, cached_count, output=None, strategy_mode='validated',
                 validation_status='not_validated'):
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
    launches = 0
    if _table_exists(con, 'launch_candidates'):
        launches += con.execute(
            "SELECT COUNT(DISTINCT mint) FROM launch_candidates "
            "WHERE mint IS NOT NULL AND status='creator_identified'"
        ).fetchone()[0]
    if _table_exists(con, 'research_launches'):
        launches += con.execute(
            "SELECT COUNT(DISTINCT mint) FROM research_launches "
            "WHERE mint IS NOT NULL AND mint NOT IN "
            "(SELECT mint FROM launch_candidates "
            "WHERE mint IS NOT NULL AND status='creator_identified')"
        ).fetchone()[0]
    quoted_mints = con.execute(
        'SELECT COUNT(DISTINCT mint) FROM paper_prices'
    ).fetchone()[0]
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
        'launches_observed': int(launches),
        'quotes_recorded': int(quotes),
        'launches_with_quotes': int(quoted_mints),
        'quote_coverage': (quoted_mints / launches if launches else None),
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
        'market_data_coverage': _market_data_coverage(con),
        'rejection_reasons': _decision_reason_counts(con),
        'validation_status': str(validation_status),
    }
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
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
               prior_launches=None, behavior=None):
    """An explicit decision record; missing measurements stay null, never zero."""
    ensure_audit_schema(con)
    report = {
        'mint': mint, 'creator_candidate': creator,
        'signal_time': int(signal_time), 'observed_at': int(now),
        'age_seconds': max(0, int(now) - int(signal_time)),
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


async def collect_once(con, session, cached, now, model=None,
                       max_open=3, max_entries_day=20,
                       max_daily_loss_pct=10.0, max_candidates=10,
                       max_age=7200, live_fetcher=None,
                       min_liquidity=1000, strategy_mode='validated',
                       initial_capital_sol=10.0, position_pct=10.0):
    """Collect one bounded cycle; return messages and cooldown seconds."""
    signals = recent_candidates(con, now, max_age=max_age, limit=max_candidates)
    cache_changed = False
    active = con.execute(
        "SELECT mint,creator,signal_time FROM paper_trades WHERE status='open'"
    ).fetchall()
    candidates = {}
    for mint, creator, signal_time in active + signals:
        candidates[mint] = (creator, signal_time)
    messages = []
    cooldown = 0
    for mint, (creator, signal_time) in list(candidates.items())[:max(1, max_candidates)]:
        pool_row = con.execute(
            "SELECT pool_state FROM launch_candidates WHERE mint=? ORDER BY id DESC LIMIT 1",
            (mint,),
        ).fetchone() if "pool_state" in {r[1] for r in con.execute("PRAGMA table_info(launch_candidates)")} else None
        pool_address = pool_row[0] if pool_row else None
        quote = None
        if pool_address:
            try:
                quote = await fetch_onchain_quote(session, mint, pool_address)
            except Exception as exc:
                print(f"[ONCHAIN] lecture indisponible : {type(exc).__name__}", flush=True)
        wait_seconds = 0
        if quote is None:
            quote, wait_seconds = await fetch_quote(
            session, mint, min_liquidity=min_liquidity, include_metrics=True,
        )
        cooldown = max(cooldown, wait_seconds)
        status_now = int(time.time())
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
                behavior=behavior_snapshot(cached, mint, creator, signal_time, status_now))
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
                behavior=behavior_snapshot(cached, mint, creator, signal_time, status_now))
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
        existing = con.execute(
            'SELECT 1 FROM paper_trades WHERE mint=?', (mint,)
        ).fetchone()
        allowed = bool(existing) or entry_allowed(
            con, now_quote, max_open=max_open,
            max_entries_day=max_entries_day,
            max_daily_loss_pct=max_daily_loss_pct,
        )
        decision = None
        model_for_quote = model
        force_exit_reason = None
        if strategy_mode == 'shadow_final':
            features = build_features(
                cached, mint, creator, signal_time, now_quote,
                price_history(con, mint), quote,
                prior_launches=prior_creator_launches(con, creator, signal_time),
            )
            decision = decide(features, min_liquidity=min_liquidity)
            record_decision(
                con, features, decision, strategy_mode=strategy_mode,
                entry_permission=allowed,
            )
            report = audit_mint(con, mint, creator, signal_time, now_quote,
                'ENTRY_PAPER_AUTORISEE' if decision.enter and allowed else 'REJET',
                quote=quote, features=features, decision=decision,
                pool_state=pool_address,
                reason='score et règles de risque' if decision.enter and allowed
                    else '; '.join(decision.reasons) or 'risque ou limites PAPER',
                prior_launches=features.prior_launches,
                behavior=behavior_snapshot(cached, mint, creator, signal_time, now_quote))
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
        )
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
        "SELECT mint,enter,reasons_json FROM paper_decisions WHERE decision_time>=? AND decision_time<=?",
        (int(started_at), int(ended_at)),
    ).fetchall()
    trades = con.execute(
        "SELECT status,net_return,pnl_sol,cost_bps FROM paper_trades WHERE entry_time>=? AND entry_time<=?",
        (int(started_at), int(ended_at)),
    ).fetchall()
    closed = [r for r in trades if r[0] == 'closed' and r[1] is not None]
    returns = [float(r[1]) for r in closed]
    pnls = [float(r[2] or 0.0) for r in closed]
    wins = sum(v > 0 for v in returns)
    losses = sum(v <= 0 for v in returns)
    gp = sum(v for v in pnls if v > 0)
    gl = -sum(v for v in pnls if v < 0)
    pf = gp / gl if gl > 0 else None
    equity = peak = 1.0
    max_dd = 0.0
    for v in returns:
        equity *= 1.0 + v
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
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
        'entries': len(trades), 'open_positions': sum(r[0]=='open' for r in trades),
        'closed_trades': len(closed), 'wins': wins, 'losses': losses,
        'win_rate': wins/len(closed) if closed else None,
        'pnl_sol': sum(pnls), 'net_return_compounded': equity-1.0 if closed else 0.0,
        'profit_factor': pf, 'max_drawdown': max_dd,
        'assumed_cost_bps_total': sum(float(r[3] or 0.0) for r in closed),
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
    print(f"PnL net              : {summary['pnl_sol']:+.6f} SOL", flush=True)
    print(f"Profit factor        : {pf_txt}", flush=True)
    print(f"Drawdown max         : {pct(summary['max_drawdown'])}", flush=True)
    print(f"Capital              : {initial_capital:.6f} -> {final_capital:.6f} SOL", flush=True)
    top = list(summary['rejection_reasons'].items())[:5]
    print('Top rejets           : ' + (', '.join(f'{k}={v}' for k,v in top) if top else 'N/D'), flush=True)
    if summary['closed_trades'] == 0:
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
              session_seconds=0, session_report=None):
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
    Database(db)
    ensure_schema(db)
    con = sqlite3.connect(db, timeout=30.0, isolation_level=None)
    con.execute('PRAGMA busy_timeout=30000')
    setup(con)
    ensure_signal_status_schema(con)
    ensure_audit_schema(con)
    ensure_paper_portfolio(con, initial_capital_sol)
    session_started = int(time.time())
    session_initial_capital = float(paper_capital(con)[1] or initial_capital_sol)
    if session_seconds:
        print(f'[SESSION] validation PAPER limitee a {int(session_seconds)} secondes.', flush=True)
    cached = []
    refreshed_at = 0
    live_fetcher = None
    if live_behavior:
        try:
            live_fetcher = await LiveBehaviorFetcher(
                db, interval=rpc_interval, max_tx=behavior_max_tx,
                refresh_seconds=cache_refresh,
                gate=rpc_gate,
            ).start()
            print(
                f'Comportements Helius : actif, cadence minimale {live_fetcher.interval:.2f}s, '
                f'{live_fetcher.max_tx} transactions/créateur.', flush=True,
            )
        except Exception as exc:
            print(f'[BEHAVIOR] désactivé : {type(exc).__name__}', flush=True)
    print('PAPER ONLY : aucun ordre réel, aucune clé privée, aucune signature.', flush=True)
    if shadow_final:
        mode_message = 'PAPER final diagnostic (comportements + wallets + marché)'
    elif shadow_baseline:
        mode_message = 'PAPER diagnostic shadow (TP 10% / SL 10% / 1h)'
    else:
        mode_message = 'modèle validé simulé' if model else 'collecte prix/comportements seulement'
    print('Mode : ' + mode_message, flush=True)
    timeout = aiohttp.ClientTimeout(total=12)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                now = int(time.time())
                if session_seconds and now - session_started >= int(session_seconds):
                    break
                if now - refreshed_at >= max(1, int(cache_refresh)):
                    cached = load_cached_transactions(db)
                    refreshed_at = now
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
                    )
                    if cache_changed:
                        cached = load_cached_transactions(db)
                        refreshed_at = now
                    state = paper_report(
                        con, now, len(cached), output=report,
                        strategy_mode=strategy_mode,
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
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    print('[PAPER] source prix temporairement lente; nouvelle tentative automatique.', flush=True)
                    cooldown = 3
                await asyncio.sleep(max(1, int(poll), int(cooldown)))
    finally:
        if session_seconds:
            ended = int(time.time())
            summary = _session_summary(con, session_started, ended)
            _initial, final_capital = paper_capital(con)
            conclusion = _print_session_summary(summary, session_initial_capital, float(final_capital or 0.0))
            summary['capital_start_sol'] = session_initial_capital
            summary['capital_end_sol'] = float(final_capital or 0.0)
            summary['conclusion'] = conclusion
            out = Path(session_report or (BASE_DIR / 'data' / 'paper_session_report.json'))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')
            print(f'[SESSION] rapport: {out}', flush=True)
        if live_fetcher:
            await live_fetcher.close()
        con.close()


async def run_with_scanner(args):
    from bot.main import run as scanner_run

    # One gate is shared by the scanner and behavior enrichment so parallel
    # tasks cannot independently burst the same Helius key.
    rpc_gate = AdaptiveRPCGate(max(1.1, float(args.rpc_interval)))

    if args.no_scanner:
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
        )
        return
    scanner_task = asyncio.create_task(scanner_run(rpc_gate=rpc_gate, db_path=args.db))
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
    ))
    try:
        await engine_task
    finally:
        scanner_task.cancel()
        try:
            await scanner_task
        except asyncio.CancelledError:
            pass


def main():
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
    args = parser.parse_args()
    try:
        asyncio.run(run_with_scanner(args))
    except KeyboardInterrupt:
        print('\nPaper engine arrêté.')


if __name__ == '__main__':
    main()
