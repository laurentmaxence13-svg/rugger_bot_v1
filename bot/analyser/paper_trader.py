"""Prix en direct et carnet simulé. Aucun portefeuille, signature ou envoi d'ordre."""
import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import sqlite3
import time
import uuid
from pathlib import Path

import aiohttp

from bot.config import BASE_DIR
from bot.scanner.supervision import _await_paper_cleanup, _raise_paper_failures

# DexScreener exposes both endpoints below.  The token-pairs endpoint is
# generally faster, while the latest/dex endpoint is a useful fallback for a
# brand-new pair that has just been indexed.
API = 'https://api.dexscreener.com/token-pairs/v1/solana/'
FALLBACK_API = 'https://api.dexscreener.com/latest/dex/tokens/'
SLIPPAGE_NOTIONAL_USD = 100.0


@dataclass(frozen=True)
class MarketQuote:
    """One observed quote plus provider fields available at that instant.

    The first three fields deliberately keep the legacy ``(liquidity, price,
    pair)`` contract.  The remaining fields are nullable because DexScreener
    does not guarantee volume, transaction counts or pool fees for every
    newly-indexed pair.  Unknown is kept as ``None`` rather than fabricated.
    """

    liquidity_usd: float
    price_usd: float
    pair_address: str
    volume_5m_usd: float | None = None
    volume_24h_usd: float | None = None
    price_change_5m_pct: float | None = None
    price_change_1h_pct: float | None = None
    tx_buys_5m: int | None = None
    tx_sells_5m: int | None = None
    market_cap_usd: float | None = None
    fdv_usd: float | None = None
    fee_bps: float | None = None
    depth_usd: float | None = None
    slippage_bps_est: float | None = None
    slippage_notional_usd: float | None = None
    quote_source: str | None = None
    funding_usd: float | None = None

    def __iter__(self):
        # Compatibility with the existing paper and test code.
        return iter((self.liquidity_usd, self.price_usd, self.pair_address))

    def legacy_tuple(self):
        return (self.liquidity_usd, self.price_usd, self.pair_address)


def _finite_number(value, minimum=None):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        return None
    return number


def _optional_int(value, minimum=0):
    number = _finite_number(value, minimum)
    return int(number) if number is not None else None


def _pair_metric(pair, group, key, minimum=None):
    values = pair.get(group) or {}
    if not isinstance(values, dict):
        return None
    return _finite_number(values.get(key), minimum)


def _constant_product_estimate(pair, price):
    """Estimate one-sided depth/price impact when raw pool reserves exist.

    This is deliberately labelled an estimate: it assumes a constant-product
    pool, ignores pool fees, and uses a fixed 100 USD notional.  Concentrated
    liquidity or missing reserves returns unknown instead of a fabricated
    number.
    """
    liquidity = pair.get('liquidity') or {}
    base = _finite_number(liquidity.get('base'), 0)
    quote = _finite_number(liquidity.get('quote'), 0)
    if base is None or quote is None or base <= 0 or quote <= 0 or price <= 0:
        return None, None
    quote_reserve_usd = base * price
    if quote_reserve_usd <= 0 or not math.isfinite(quote_reserve_usd):
        return None, None
    # The quote-side reserve is inferred from the observed mid price.  It is
    # not used if the pair does not expose both raw reserves.
    notional = min(SLIPPAGE_NOTIONAL_USD, quote_reserve_usd * 0.25)
    if notional <= 0 or notional >= quote_reserve_usd:
        return quote_reserve_usd, None
    k = quote_reserve_usd * base
    output_base = base - k / (quote_reserve_usd + notional)
    if output_base <= 0:
        return quote_reserve_usd, None
    average_price = notional / output_base
    impact = (average_price / price - 1.0) * 10000.0
    return quote_reserve_usd, max(0.0, impact) if math.isfinite(impact) else None


def _market_quote_from_pair(pair):
    """Parse provider metadata without assigning values to missing fields."""
    liquidity = _finite_number(((pair.get('liquidity') or {}).get('usd')), 0)
    price = _finite_number(pair.get('priceUsd'), 0)
    pair_address = pair.get('pairAddress')
    if liquidity is None or price is None or price <= 0 or not pair_address:
        return None
    depth_usd, slippage_bps_est = _constant_product_estimate(pair, price)
    return MarketQuote(
        liquidity_usd=liquidity,
        price_usd=price,
        pair_address=str(pair_address),
        quote_source='dex_market',
        volume_5m_usd=_pair_metric(pair, 'volume', 'm5', 0),
        volume_24h_usd=_pair_metric(pair, 'volume', 'h24', 0),
        price_change_5m_pct=_pair_metric(pair, 'priceChange', 'm5'),
        price_change_1h_pct=_pair_metric(pair, 'priceChange', 'h1'),
        tx_buys_5m=_optional_int(
            (((pair.get('txns') or {}).get('m5') or {}).get('buys'))
        ),
        tx_sells_5m=_optional_int(
            (((pair.get('txns') or {}).get('m5') or {}).get('sells'))
        ),
        market_cap_usd=_finite_number(pair.get('marketCap'), 0),
        fdv_usd=_finite_number(pair.get('fdv'), 0),
        fee_bps=_finite_number(pair.get('feeBps'), 0),
        # These are optional provider extensions.  We do not infer pool depth
        # or execution slippage from liquidity alone.
        depth_usd=_finite_number(pair.get('depthUsd'), 0) or depth_usd,
        slippage_bps_est=(
            _finite_number(pair.get('slippageBps'), 0)
            if pair.get('slippageBps') is not None else slippage_bps_est
        ),
        slippage_notional_usd=(
            SLIPPAGE_NOTIONAL_USD if slippage_bps_est is not None else None
        ),
    )


def setup(con):
    from bot.analyser.token_inventory import setup_inventory_schema
    setup_inventory_schema(con)
    con.executescript('''
    CREATE TABLE IF NOT EXISTS paper_quote_conflicts (
      mint TEXT NOT NULL, timestamp INTEGER NOT NULL,
      rejected_observations INTEGER NOT NULL,
      differing_fields_json TEXT NOT NULL,
      PRIMARY KEY(mint,timestamp));
    CREATE TABLE IF NOT EXISTS paper_prices (
      mint TEXT NOT NULL, timestamp INTEGER NOT NULL, price_usd REAL NOT NULL,
      pair_address TEXT NOT NULL, liquidity_usd REAL NOT NULL,
      volume_5m_usd REAL, volume_24h_usd REAL,
      price_change_5m_pct REAL, price_change_1h_pct REAL,
      tx_buys_5m INTEGER, tx_sells_5m INTEGER,
      market_cap_usd REAL, fdv_usd REAL, fee_bps REAL,
      depth_usd REAL, slippage_bps_est REAL, slippage_notional_usd REAL,
      PRIMARY KEY(mint,timestamp));
    CREATE TABLE IF NOT EXISTS paper_trades (
      mint TEXT PRIMARY KEY, creator TEXT NOT NULL, signal_time INTEGER NOT NULL,
      entry_time INTEGER NOT NULL, entry_price REAL NOT NULL,
      exit_time INTEGER, exit_price REAL, net_return REAL, exit_reason TEXT,
      peak_price REAL, last_price REAL, last_quote_time INTEGER,
      cost_bps REAL,
      strategy_mode TEXT NOT NULL DEFAULT 'validated',
      position_sol REAL, pnl_sol REAL, capital_after_sol REAL,
      status TEXT NOT NULL CHECK(status IN ('open','closed')));
    CREATE TABLE IF NOT EXISTS paper_portfolio (
      id INTEGER PRIMARY KEY CHECK(id=1),
      initial_capital_sol REAL NOT NULL,
      realized_capital_sol REAL NOT NULL,
      updated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS paper_decisions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      mint TEXT NOT NULL, creator TEXT NOT NULL,
      signal_time INTEGER NOT NULL, decision_time INTEGER NOT NULL,
      strategy_mode TEXT NOT NULL, enter INTEGER NOT NULL,
      entry_allowed INTEGER NOT NULL, score REAL NOT NULL,
      reasons_json TEXT NOT NULL, risk_flags_json TEXT NOT NULL,
      prior_launches INTEGER NOT NULL, behavior_known INTEGER NOT NULL,
      dev_sales INTEGER NOT NULL, relay_transfers INTEGER NOT NULL,
      bundle_transactions INTEGER NOT NULL, bundle_wallets INTEGER NOT NULL,
      liquidity_usd REAL NOT NULL, price_usd REAL NOT NULL,
      quote_count INTEGER NOT NULL, momentum_60s REAL,
      momentum_300s REAL, tp_pct REAL, sl_pct REAL,
      trailing_stop_pct REAL, hold_seconds INTEGER NOT NULL,
      volume_5m_usd REAL, volume_24h_usd REAL,
      price_change_5m_pct REAL, price_change_1h_pct REAL,
      tx_buys_5m INTEGER, tx_sells_5m INTEGER,
      market_cap_usd REAL, fdv_usd REAL, fee_bps REAL,
      depth_usd REAL, slippage_bps_est REAL,
      market_data_quality TEXT,
      holder_count INTEGER, top_holder_share REAL,
      holder_data_known INTEGER, linked_wallets INTEGER,
      wallet_link_count INTEGER, same_slot_wallets INTEGER,
      wallet_graph_transactions INTEGER);
    CREATE INDEX IF NOT EXISTS idx_paper_decisions_mint_time
      ON paper_decisions(mint, decision_time);
    ''')
    # Existing user databases were created before dynamic exits existed.
    # Migrate them in place without deleting any paper-trading history.
    columns = {row[1] for row in con.execute('PRAGMA table_info(paper_trades)')}
    for name, definition in (
        ('exit_reason', 'TEXT'),
        ('peak_price', 'REAL'),
        ('last_price', 'REAL'),
        ('last_quote_time', 'INTEGER'),
        ('cost_bps', 'REAL'),
        ('strategy_mode', "TEXT NOT NULL DEFAULT 'validated'"),
        ('position_sol', 'REAL'), ('pnl_sol', 'REAL'), ('capital_after_sol', 'REAL'),
    ):
        if name not in columns:
            con.execute(f'ALTER TABLE paper_trades ADD COLUMN {name} {definition}')
    price_columns = {
        row[1] for row in con.execute('PRAGMA table_info(paper_prices)')
    }
    for name, definition in (
        ('volume_5m_usd', 'REAL'),
        ('volume_24h_usd', 'REAL'),
        ('price_change_5m_pct', 'REAL'),
        ('price_change_1h_pct', 'REAL'),
        ('tx_buys_5m', 'INTEGER'),
        ('tx_sells_5m', 'INTEGER'),
        ('market_cap_usd', 'REAL'),
        ('fdv_usd', 'REAL'),
        ('fee_bps', 'REAL'),
        ('depth_usd', 'REAL'),
        ('slippage_bps_est', 'REAL'),
        ('slippage_notional_usd', 'REAL'),
        ('quote_source', 'TEXT'),
        ('funding_usd', 'REAL'),
    ):
        if name not in price_columns:
            con.execute(f'ALTER TABLE paper_prices ADD COLUMN {name} {definition}')
    decision_columns = {
        row[1] for row in con.execute('PRAGMA table_info(paper_decisions)')
    }
    for name, definition in (
        ('volume_5m_usd', 'REAL'),
        ('volume_24h_usd', 'REAL'),
        ('price_change_5m_pct', 'REAL'),
        ('price_change_1h_pct', 'REAL'),
        ('tx_buys_5m', 'INTEGER'),
        ('tx_sells_5m', 'INTEGER'),
        ('market_cap_usd', 'REAL'),
        ('fdv_usd', 'REAL'),
        ('fee_bps', 'REAL'),
        ('depth_usd', 'REAL'),
        ('slippage_bps_est', 'REAL'),
        ('slippage_notional_usd', 'REAL'),
        ('market_data_quality', 'TEXT'),
        ('holder_count', 'INTEGER'),
        ('top_holder_share', 'REAL'),
        ('holder_data_known', 'INTEGER'),
        ('linked_wallets', 'INTEGER'),
        ('wallet_link_count', 'INTEGER'),
        ('same_slot_wallets', 'INTEGER'),
        ('wallet_graph_transactions', 'INTEGER'),
    ):
        if name not in decision_columns:
            con.execute(f'ALTER TABLE paper_decisions ADD COLUMN {name} {definition}')


def ensure_paper_portfolio(con, initial_capital_sol=10.0, now=None):
    """Create the simulated SOL bankroll once; never reset existing history."""
    now = int(time.time()) if now is None else int(now)
    initial = max(0.000001, float(initial_capital_sol))
    con.execute("INSERT OR IGNORE INTO paper_portfolio(id,initial_capital_sol,realized_capital_sol,updated_at) VALUES(1,?,?,?)", (initial, initial, now))
    return con.execute("SELECT initial_capital_sol,realized_capital_sol FROM paper_portfolio WHERE id=1").fetchone()

def paper_capital(con):
    row = con.execute("SELECT initial_capital_sol,realized_capital_sol FROM paper_portfolio WHERE id=1").fetchone()
    return (float(row[0]), float(row[1])) if row else (None, None)


def model_risk(model, hold=3600, cost_bps=200):
    """Read paper-only risk parameters from a model.

    TP, SL and trailing-stop values are percentage points: ``12.0`` means
    twelve percent.  ``None`` keeps the trailing stop disabled for older
    models that do not contain this optional field.
    """
    model = model or {}
    try:
        hold = max(1, int(model.get('hold_seconds', hold)))
    except (TypeError, ValueError):
        hold = max(1, int(hold))
    try:
        cost_bps = max(0, int(model.get('cost_bps', cost_bps)))
    except (TypeError, ValueError):
        cost_bps = max(0, int(cost_bps))
    def percent(name):
        try:
            value = float(model[name])
        except (KeyError, TypeError, ValueError):
            return None
        return value if math.isfinite(value) and value > 0 else None
    return (hold, cost_bps, percent('tp_pct'), percent('sl_pct'),
            percent('trailing_stop_pct'))


def entry_allowed(con, now, max_open=3, max_entries_day=20,
                  max_daily_loss_pct=10.0):
    """Limites PAPER sur positions, entrees et pertes realisees."""
    open_count = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE status='open'"
    ).fetchone()[0]
    if open_count >= max(0, int(max_open)):
        return False
    if _inventory_exists(con) and con.execute(
            "SELECT 1 FROM paper_token_inventory i JOIN paper_trades t ON t.mint=i.mint "
            "WHERE t.status='open' AND i.cost_basis_remaining_lamports IS NULL LIMIT 1").fetchone():
        return False

    day_start = int(now) - int(now) % 86400
    entries_today = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE entry_time >= ? AND entry_time <= ?",
        (day_start, int(now)),
    ).fetchone()[0]
    if entries_today >= max(0, int(max_entries_day)):
        return False

    if max_daily_loss_pct is not None and float(max_daily_loss_pct) > 0:
        # Validate all closures before filtering by day: an unknown date must
        # never make a realized loss disappear. Read only; do not repair history.
        for entry_time, exit_time, pnl_sol in con.execute(
                "SELECT entry_time,exit_time,pnl_sol FROM paper_trades WHERE status='closed'"):
            if not all(isinstance(value, (int, float)) and math.isfinite(value)
                       for value in (entry_time, exit_time, pnl_sol)):
                return False
            if not 0 <= entry_time <= exit_time <= int(now):
                return False
        pnl_today, missing = con.execute(
            """SELECT COALESCE(SUM(pnl_sol), 0),
                      COALESCE(SUM(CASE WHEN pnl_sol IS NULL THEN 1 ELSE 0 END), 0)
               FROM paper_trades
               WHERE status='closed' AND exit_time >= ? AND exit_time <= ?""",
            (day_start, int(now)),
        ).fetchone()

        if _inventory_exists(con):
            try:
                events = _paper_realization_events(con)
            except (TypeError,ValueError):
                return False
            if any(event['time'] > int(now) for event in events):
                return False
            pnl_today = math.fsum(event['pnl_sol'] for event in events if day_start <= event['time'] <= int(now))
            missing = 0
        if missing:
            return False

        ensure_paper_portfolio(con, 10.0, now)
        _initial, capital_now = paper_capital(con)
        capital_day_start = float(capital_now) - float(pnl_today)

        if capital_day_start <= 0:
            return False

        limite = capital_day_start * float(max_daily_loss_pct) / 100.0
        if float(pnl_today) <= -limite:
            return False

    return True


def eligible_model(path):
    if not path:
        return None
    model = json.loads(Path(path).read_text(encoding='utf-8'))
    if model.get('validation_status') != 'single_split_oos':
        raise ValueError(
            'Modèle refusé : il manque une validation hors échantillon explicite.'
        )
    if (model.get('train', 0) < 30 or model.get('test', 0) < 15
            or model.get('selected', 0) < 5 or model.get('mean_return', 0) <= 0):
        raise ValueError('Modèle non validé hors échantillon : simulation des entrées désactivée.')
    return model


def choose_quote(pairs, mint, min_liquidity=10000):
    """Return the legacy three-field quote tuple for callers not needing metadata."""
    quote = choose_quote_details(pairs, mint, min_liquidity)
    return quote.legacy_tuple() if quote else None


def choose_quote_details(pairs, mint, min_liquidity=10000):
    """Choose the deepest usable pair and preserve observable market fields."""
    usable = []
    for pair in pairs if isinstance(pairs, list) else []:
        try:
            if (pair.get('chainId') != 'solana'
                    or pair['baseToken']['address'] != mint):
                continue
            quote = _market_quote_from_pair(pair)
            if quote and quote.liquidity_usd >= max(0, float(min_liquidity)):
                usable.append(quote)
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
    return max(usable, key=lambda item: item.liquidity_usd) if usable else None


async def _fetch_quote_endpoint(session, endpoint, mint, min_liquidity,
                                include_metrics=False):
    """Read one DexScreener endpoint without turning an unindexed token into
    a failed collection cycle.

    A new LaunchLab mint can exist on-chain before DexScreener has indexed its
    pair.  HTTP 400/404 therefore mean "not observable yet" here, not a fatal
    scanner error.  429 is propagated as a cooldown so the caller slows down.
    """
    async with session.get(endpoint + mint) as resp:
        if resp.status == 429:
            return None, 60, True
        if resp.status in (400, 404):
            return None, 0, False
        resp.raise_for_status()
        payload = await resp.json(content_type=None)
        pairs = payload.get('pairs') if isinstance(payload, dict) else payload
        # Always collect an observable pair, even below the strategy liquidity
        # threshold. Liquidity belongs in the decision engine; filtering it here
        # made fresh launches disappear before a REJET could be recorded.
        quote = choose_quote_details(pairs, mint, 0)
        return (quote if include_metrics and quote else
                quote.legacy_tuple() if quote else None), 0, False


async def fetch_quote(session, mint, min_liquidity=10000, include_metrics=False):
    """Return a usable quote, trying both public DexScreener shapes.

    ``min_liquidity`` is deliberately configurable for PAPER collection.  A
    low-liquidity quote is still recorded with its liquidity value so research
    can reject it later; silently discarding it here made the collector look
    dead and prevented complete observation series.
    """
    cooldown = 0
    for endpoint in (API, FALLBACK_API):
        try:
            quote, wait_seconds, rate_limited = await _fetch_quote_endpoint(
                session, endpoint, mint, min_liquidity, include_metrics=include_metrics,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # One public endpoint being slow must not abort the PAPER cycle.
            cooldown = max(cooldown, 3)
            continue
        if wait_seconds or rate_limited:
            cooldown = max(cooldown, int(wait_seconds or 60))
            continue
        if quote:
            return quote, 0
    return None, cooldown


def recent_signals(con, now, max_age=3660):
    # Un signal provenant du scanner live, confirmé par son parseur strict.
    return con.execute('''SELECT mint,deployer_candidate,block_time FROM launch_candidates
      WHERE status='creator_identified' AND mint IS NOT NULL AND block_time BETWEEN ? AND ?
      ORDER BY block_time DESC LIMIT 10''', (now-max_age, now)).fetchall()


def _quote_values(quote):
    """Return a stable mapping for a rich quote or a legacy three-tuple."""
    if isinstance(quote, MarketQuote):
        return quote
    try:
        liquidity, price, pair = quote
    except (TypeError, ValueError):
        raise ValueError('Quote invalide : liquidité, prix et paire requis.')
    return MarketQuote(float(liquidity),
                       _financial_number(price, 'price_usd', nonnegative=True), str(pair))


@contextmanager
def _paper_close_transaction(con):
    """Serialize PAPER accounting; preserve any caller-owned transaction."""
    nested = con.in_transaction
    savepoint = 'paper_close_' + uuid.uuid4().hex
    con.execute(f'SAVEPOINT {savepoint}' if nested else 'BEGIN IMMEDIATE')
    try:
        yield
        con.execute(f'RELEASE SAVEPOINT {savepoint}' if nested else 'COMMIT')
    except BaseException:
        if con.in_transaction:
            if nested:
                con.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
                con.execute(f'RELEASE SAVEPOINT {savepoint}')
            else:
                con.rollback()
        raise


def _financial_number(value, name, positive=False, nonnegative=False):
    if (not isinstance(value, (int, float)) or not math.isfinite(value)
            or (positive and value <= 0) or (nonnegative and value < 0)):
        raise ValueError(f'Invalid PAPER financial field: {name}')
    return float(value)


def record_quote(con, mint, creator, signal_time, now, quote, model,
                 hold=3600, cost_bps=200, allow_entry=True,
                 strategy_mode='validated', force_exit_reason=None,
                 initial_capital_sol=10.0, position_pct=10.0, *,
                 max_open=3, max_entries_day=20, max_daily_loss_pct=10.0,
                 inventory_context=None, require_inventory=False):
    # Entries must read free capital and reserve it under the same write lock.
    # Closing and opening positions therefore share one serialization boundary.
    args = (con, mint, creator, signal_time, now, quote, model, hold, cost_bps,
            allow_entry, strategy_mode, force_exit_reason, initial_capital_sol, position_pct)
    with _paper_close_transaction(con):
        return _record_quote(
            con, *args[1:], _close_locked=True, max_open=max_open,
            max_entries_day=max_entries_day, max_daily_loss_pct=max_daily_loss_pct,
            inventory_context=inventory_context, require_inventory=require_inventory,
        )


def _inventory_decision_ms(context, now):
    value = context.get('decision_at_ms',int(now*1000)) if isinstance(context,dict) else int(now*1000)
    if type(value) is not int or not int(now)*1000 <= value < (int(now)+1)*1000:
        raise ValueError('Atomic inventory decision time disagrees with quote collection second')
    return value


def _inventory_exists(con):
    table = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_token_inventory'").fetchone()
    return bool(table and con.execute('SELECT 1 FROM paper_token_inventory LIMIT 1').fetchone())


def _inventory_int(value, name, *, nonnegative=True):
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError('Invalid atomic inventory field: '+name)
    try:
        number = int(value)
    except ValueError:
        raise ValueError('Invalid atomic inventory field: '+name) from None
    if str(number) != value or (nonnegative and number < 0):
        raise ValueError('Invalid atomic inventory field: '+name)
    return number


def _paper_realization_events(con):
    """One economic event stream; aggregate native closures are never credited twice.

    Native leg integers remain authoritative. Bookkeeping seconds preserve the
    legacy inclusive session/day API; exact decision milliseconds remain stored.
    """
    native = {}
    if _inventory_exists(con):
        for mint, acquired, remaining, total, basis_left, pnl in con.execute(
                'SELECT mint,acquired_atomic,remaining_atomic,cost_basis_total_lamports,'
                'cost_basis_remaining_lamports,realized_pnl_lamports FROM paper_token_inventory'):
            native[mint] = dict(acquired=_inventory_int(acquired,'acquired'),
                remaining=_inventory_int(remaining,'remaining'), total=total, basis_left=basis_left,
                pnl=_inventory_int(pnl,'realized_pnl',nonnegative=False), sold=0, allocated=0, leg_pnl=0)
            if not 0 <= native[mint]['remaining'] <= native[mint]['acquired'] or native[mint]['acquired'] <= 0:
                raise ValueError('Inconsistent native inventory quantity')
    events = []
    for mint, entry, exit_at, pnl, size in con.execute(
            "SELECT mint,entry_time,exit_time,pnl_sol,position_sol FROM paper_trades WHERE status='closed'"):
        size = _financial_number(size,'position_sol',positive=True)
        if mint in native:
            continue
        entry = _financial_number(entry,'entry_time',nonnegative=True)
        exit_at = _financial_number(exit_at,'exit_time',nonnegative=True)
        pnl = _financial_number(pnl,'historical pnl_sol')
        if exit_at < entry:
            raise ValueError('Legacy realization predates entry')
        events.append(dict(time=exit_at,time_ms=exit_at*1000,pnl_sol=pnl,mint=mint,
                           order=(0,mint),kind='legacy_position'))
    if native:
        for rowid, leg_id, mint, at, quantity, proceeds, fee, basis, pnl in con.execute(
                'SELECT rowid,id,mint,decision_ms,quantity_atomic,proceeds_lamports,extra_fee_lamports,'
                'allocated_basis_lamports,pnl_lamports FROM paper_token_legs'):
            if mint not in native or type(at) is not int or at < 0:
                raise ValueError('Orphan or undated native realization')
            quantity = _inventory_int(quantity,'leg quantity')
            proceeds = _inventory_int(proceeds,'leg proceeds')
            fee = _inventory_int(fee,'leg fee')
            basis = _inventory_int(basis,'leg basis')
            pnl = _inventory_int(pnl,'leg pnl',nonnegative=False)
            if quantity <= 0 or pnl != proceeds-fee-basis:
                raise ValueError('Native realization does not reconcile')
            item = native[mint]
            item['sold'] += quantity; item['allocated'] += basis; item['leg_pnl'] += pnl
            events.append(dict(time=at//1000,time_ms=at,pnl_sol=pnl/1_000_000_000,
                               mint=mint,order=(1,rowid),kind='native_leg',leg_id=leg_id))
        for mint, item in native.items():
            trade = con.execute('SELECT status,pnl_sol,entry_time FROM paper_trades WHERE mint=?',(mint,)).fetchone()
            if trade is None or item['sold'] != item['acquired']-item['remaining'] or item['leg_pnl'] != item['pnl']:
                raise ValueError('Native position aggregate does not reconcile')
            if any(e['time'] < trade[2] for e in events if e['mint'] == mint):
                raise ValueError('Native realization predates entry')
            if item['total'] is None or item['basis_left'] is None:
                if item['sold']:
                    raise ValueError('Unknown native basis cannot have settled legs')
            else:
                total = _inventory_int(item['total'],'total basis')
                left = _inventory_int(item['basis_left'],'remaining basis')
                if total-left != item['allocated'] or left < 0 or (item['remaining'] == 0 and left != 0):
                    raise ValueError('Native remaining basis does not reconcile')
            if trade[0] == 'closed':
                if item['remaining'] != 0 or not math.isclose(
                        _financial_number(trade[1],'native aggregate pnl'),item['pnl']/1_000_000_000,
                        rel_tol=0,abs_tol=1e-12):
                    raise ValueError('Closed native position retains inventory or inconsistent PnL')
            elif item['remaining'] == 0:
                raise ValueError('Open native position has no remaining inventory')
    return sorted(events,key=lambda e:(e['time_ms'],e['order']))


def _paper_reconciled_capital(con):
    row = con.execute('SELECT initial_capital_sol,realized_capital_sol FROM paper_portfolio WHERE id=1').fetchone()
    if row is None:
        raise ValueError('Missing PAPER portfolio')
    initial = _financial_number(row[0],'initial_capital_sol',positive=True)
    capital = _financial_number(row[1],'realized_capital_sol')
    native = _inventory_exists(con)
    pnls = ([e['pnl_sol'] for e in _paper_realization_events(con)] if native else
            [_financial_number(row[0],'historical pnl_sol') for row in
             con.execute("SELECT pnl_sol FROM paper_trades WHERE status='closed'")])
    expected = _financial_number(initial+math.fsum(pnls),'ledger capital')
    if not math.isclose(capital,expected,rel_tol=0 if native else 1e-9,abs_tol=1e-12):
        raise ValueError('Unreconciled PAPER portfolio')
    return capital


def _paper_free_capital(con):
    """Reserve remaining native basis or the unchanged legacy position amount."""
    capital = _paper_reconciled_capital(con)
    native = {}
    if _inventory_exists(con):
        native = dict(con.execute('SELECT mint,cost_basis_remaining_lamports FROM paper_token_inventory'))
    sizes = []
    for mint, size, pnl, exit_time, capital_after in con.execute(
            "SELECT mint,position_sol,pnl_sol,exit_time,capital_after_sol FROM paper_trades WHERE status='open'"):
        size = _financial_number(size,'reserved position_sol',positive=True)
        if any(value is not None for value in (pnl,exit_time,capital_after)):
            raise ValueError('PAPER open position contains closure accounting')
        sizes.append(_inventory_int(native[mint],'reserved native basis')/1_000_000_000 if mint in native else size)
    committed = _financial_number(math.fsum(sizes),'committed capital')
    return capital,_financial_number(capital-committed,'free capital')


PRICE_FIELDS = (
    'price_usd', 'pair_address', 'liquidity_usd', 'volume_5m_usd',
    'volume_24h_usd', 'price_change_5m_pct', 'price_change_1h_pct',
    'tx_buys_5m', 'tx_sells_5m', 'market_cap_usd', 'fdv_usd', 'fee_bps',
    'depth_usd', 'slippage_bps_est', 'slippage_notional_usd',
    'quote_source', 'funding_usd',
)


def _price_values(mint, now, market_quote):
    return (
        mint, now, market_quote.price_usd, market_quote.pair_address,
        market_quote.liquidity_usd, market_quote.volume_5m_usd,
        market_quote.volume_24h_usd, market_quote.price_change_5m_pct,
        market_quote.price_change_1h_pct, market_quote.tx_buys_5m,
        market_quote.tx_sells_5m, market_quote.market_cap_usd,
        market_quote.fdv_usd, market_quote.fee_bps,
        market_quote.depth_usd, market_quote.slippage_bps_est,
        market_quote.slippage_notional_usd,
        (market_quote.quote_source.strip() or None)
        if isinstance(market_quote.quote_source, str) else None,
        _finite_number(market_quote.funding_usd, 0),
    )


def skip_recorded_quote(con, mint, now, quote):
    """Under the caller's write transaction, reject repeats before decisions.

    First observation wins, including unknown metadata. Never merge NULLs.
    Identical repeats do nothing; contradictions are counted without revaluation.
    """
    incoming = _price_values(mint, now, _quote_values(quote))[2:]
    stored = con.execute('SELECT ' + ','.join(PRICE_FIELDS) +
                         ' FROM paper_prices WHERE mint=? AND timestamp=?',
                         (mint, now)).fetchone()
    if stored is None:
        return False
    differences = [name for name, old, new in zip(PRICE_FIELDS, stored, incoming)
                   if old != new]
    if differences:
        con.execute("""INSERT INTO paper_quote_conflicts VALUES(?,?,1,?)
            ON CONFLICT(mint,timestamp) DO UPDATE SET
            rejected_observations=rejected_observations+1,
            differing_fields_json=excluded.differing_fields_json""",
            (mint, now, json.dumps(differences)))
        print('[PAPER PRICES] doublon contradictoire : premiere cotation conservee; '
              'observation rejetee avant decision et traitement PAPER.', flush=True)
    return True


def _record_quote(con, mint, creator, signal_time, now, quote, model,
                 hold=3600, cost_bps=200, allow_entry=True,
                 strategy_mode='validated', force_exit_reason=None,
                 initial_capital_sol=10.0, position_pct=10.0, _close_locked=False,
                 max_open=3, max_entries_day=20, max_daily_loss_pct=10.0,
                 inventory_context=None, require_inventory=False):
    if not _close_locked:
        with _paper_close_transaction(con):
            return _record_quote(
                con, mint, creator, signal_time, now, quote, model,
                hold, cost_bps, allow_entry, strategy_mode, force_exit_reason,
                initial_capital_sol, position_pct, _close_locked=True,
                max_open=max_open, max_entries_day=max_entries_day,
                max_daily_loss_pct=max_daily_loss_pct,
                inventory_context=inventory_context, require_inventory=require_inventory,
            )
    market_quote = _quote_values(quote)
    liquidity, price, pair = market_quote
    # Validate before persisting a quote or creating any bankroll/reservation.
    # Zero remains valid for an existing position's total-loss observation.
    _financial_number(price, 'price_usd', nonnegative=True)
    trade = con.execute('''SELECT entry_time,entry_price,status,peak_price
                           FROM paper_trades WHERE mint=?''', (mint,)).fetchone()
    if trade is None:
        _financial_number(price, 'entry_price', positive=True)
    if skip_recorded_quote(con, mint, now, market_quote):
        return None
    price_values = _price_values(mint, now, market_quote)
    con.execute(
        '''INSERT INTO paper_prices(
             mint,timestamp,price_usd,pair_address,liquidity_usd,
             volume_5m_usd,volume_24h_usd,price_change_5m_pct,
             price_change_1h_pct,tx_buys_5m,tx_sells_5m,market_cap_usd,
             fdv_usd,fee_bps,depth_usd,slippage_bps_est,
             slippage_notional_usd,quote_source,funding_usd)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', price_values,
    )
    if trade and trade[2] == 'open':
        entry_time, entry_price, _status, previous_peak = trade
        _financial_number(entry_price, 'entry_price', positive=True)
        _financial_number(price, 'exit_price', nonnegative=True)
        _financial_number(entry_time, 'entry_time', nonnegative=True)
        _financial_number(now, 'exit_time', nonnegative=True)
        if now < entry_time:
            raise ValueError('PAPER closure cannot precede entry')
        if previous_peak is not None:
            _financial_number(previous_peak, 'peak_price', positive=True)
        _financial_number((model or {}).get('cost_bps', cost_bps),
                          'cost_bps', nonnegative=True)
        peak = max(float(previous_peak or entry_price), price)
        gross_return = price / entry_price - 1
        hold_s, cost, tp_pct, sl_pct, trailing_pct = model_risk(
            model, hold, cost_bps
        )
        reason = None
        if force_exit_reason:
            reason = str(force_exit_reason)
        elif tp_pct is not None and gross_return >= tp_pct / 100:
            reason = 'TP'
        elif sl_pct is not None and gross_return <= -sl_pct / 100:
            reason = 'SL'
        elif (trailing_pct is not None and peak > entry_price
              and price <= peak * (1.0 - trailing_pct / 100.0)):
            reason = 'TRAILING_STOP'
        elif now >= entry_time + hold_s:
            reason = 'TIMEOUT'
        native_position = (_inventory_exists(con) and con.execute(
            'SELECT 1 FROM paper_token_inventory WHERE mint=?',(mint,)).fetchone())
        if native_position:
            if reason:
                from bot.analyser.token_inventory import settle_exit
                return settle_exit(con,mint,inventory_context,_inventory_decision_ms(inventory_context,now),reason,price,peak)
            con.execute("UPDATE paper_trades SET peak_price=?,last_price=?,last_quote_time=? WHERE mint=? AND status='open'",
                        (peak,price,now,mint))
            return None
        if reason:
            result = gross_return - cost / 10000
            position_row = con.execute('SELECT position_sol,pnl_sol,exit_time,capital_after_sol '
                                       'FROM paper_trades WHERE mint=?', (mint,)).fetchone()
            if any(value is not None for value in position_row[1:]):
                raise ValueError('PAPER open position contains closure accounting')
            position_sol = _financial_number(position_row[0], 'position_sol', positive=True)
            result = _financial_number(result, 'net_return')
            pnl_sol = _financial_number(position_sol * result, 'pnl_sol')
            portfolio = con.execute('SELECT initial_capital_sol,realized_capital_sol '
                                    'FROM paper_portfolio WHERE id=1').fetchone()
            if portfolio is None:
                raise ValueError('Missing PAPER portfolio for closure')
            initial = _financial_number(portfolio[0], 'initial_capital_sol', positive=True)
            capital_before = _financial_number(portfolio[1], 'realized_capital_sol')
            _paper_reconciled_capital(con)
            # Keep the full liability, including negative equity after extreme
            # simulated costs. Never silently clip capital or alter trade PnL.
            capital_after = _financial_number(capital_before + pnl_sol, 'capital_after_sol')
            # The active decision recalculates the cost assumption on every
            # quote. Persist the exact assumption charged here, rather than the
            # entry estimate, so a restarted reporter can reconcile gross/net.
            # It remains a PAPER assumption, never an observed execution fee.
            updated = con.execute('''UPDATE paper_trades
                           SET exit_time=?,exit_price=?,net_return=?,exit_reason=?,
                               peak_price=?,last_price=?,last_quote_time=?,pnl_sol=?,
                               capital_after_sol=?,cost_bps=?,status='closed'
                           WHERE mint=? AND status='open' ''',
                        (now, price, result, reason, peak, price, now, pnl_sol, capital_after, cost, mint))
            if updated.rowcount != 1:
                raise RuntimeError('PAPER open-to-closed transition failed')
            updated = con.execute('UPDATE paper_portfolio SET realized_capital_sol=?,updated_at=? WHERE id=1',
                                  (capital_after, now))
            if updated.rowcount != 1:
                raise RuntimeError('PAPER portfolio update failed')
            return (f'EXIT {mint} reason={reason} simulated net={result:+.2%} '
                    f'PnL={pnl_sol:+.6f} SOL capital={capital_after:.6f} SOL')
        con.execute('''UPDATE paper_trades
                       SET peak_price=?,last_price=?,last_quote_time=?
                       WHERE mint=? AND status='open' ''', (peak, price, now, mint))
        return None
    if trade or model is None or not allow_entry:
        return None

    if strategy_mode == 'shadow_final':
        # The final decision engine has already assessed the candidate.
        # It must explicitly approve the entry; the old 60-900 s window
        # and legacy creator score must not silently veto that decision.
        if model.get('decision_approved') is not True:
            return None
        try:
            score = float(model['decision_score'])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(score) or score <= 0:
            return None
    else:
        # Retain all legacy baseline/validated behavior unchanged.
        if now < signal_time + 60 or now > signal_time + 900:
            return None
        score = model['creator_scores'].get(creator, model['fallback_score'])
        if score <= 0:
            return None
    hold_s, cost, _tp_pct, _sl_pct, _trailing_pct = model_risk(
        model, hold, cost_bps
    )
    if con.execute('SELECT 1 FROM paper_portfolio WHERE id=1').fetchone() is None:
        if con.execute('SELECT 1 FROM paper_trades LIMIT 1').fetchone() is not None:
            raise ValueError('Missing PAPER portfolio with existing trades')
        _financial_number(initial_capital_sol, 'initial_capital_sol', positive=True)
        ensure_paper_portfolio(con, initial_capital_sol, now)
    capital, free_capital = _paper_free_capital(con)
    _financial_number(position_pct, 'position_pct', nonnegative=True)
    position_sol = max(0.0, float(capital or 0.0) * max(0.0, min(100.0, float(position_pct))) / 100.0)
    _financial_number(position_sol, 'position_sol', nonnegative=True)
    if position_sol <= 0 or position_sol > free_capital:
        return None
    # The caller's earlier check is advisory: recheck the configured limits
    # while holding the same SQLite write transaction as the reservation.
    if not entry_allowed(con, now, max_open=max_open,
                         max_entries_day=max_entries_day,
                         max_daily_loss_pct=max_daily_loss_pct):
        return None
    prepared = None
    if inventory_context is not None or require_inventory:
        from bot.analyser.token_inventory import prepare_entry
        prepared = prepare_entry(con,mint,inventory_context,_inventory_decision_ms(inventory_context,now),position_sol,free_capital)
        if not prepared.get('accepted'):
            return 'INVENTORY ENTRY REFUSED '+mint+' reason='+str(prepared.get('reason','unqualified_inventory'))
    inserted = con.execute('''INSERT OR IGNORE INTO paper_trades
        (mint,creator,signal_time,entry_time,entry_price,peak_price,last_price,
         last_quote_time,cost_bps,strategy_mode,position_sol,status) VALUES(?,?,?,?,?,?,?,?,?,?,?, 'open')''',
        (mint, creator, signal_time, now, price, price, price, now, cost,
         str(strategy_mode or 'validated'), position_sol))
    if inserted.rowcount != 1:
        return None
    if prepared is not None:
        from bot.analyser.token_inventory import persist_entry
        persist_entry(con,mint,prepared)
    score_label = (f'{score:.1f}/100' if strategy_mode == 'shadow_final'
                   else f'{score:+.2%}')
    return (f'ENTRY {mint} simulated price={price:.10g} USD score={score_label} '
            f'size={position_sol:.6f} SOL capital={float(capital):.6f} SOL')


async def run(db, model_path=None, poll=15, max_open=3,
              max_entries_day=20, max_candidates=10,
              max_daily_loss_pct=10.0):
    model = eligible_model(model_path)
    con = session = None
    failures = []
    stage = 'database initialization'
    try:
        con = sqlite3.connect(db, timeout=30.0, isolation_level=None)
        con.execute('PRAGMA busy_timeout=30000')
        setup(con)
        print('PAPER ONLY : prix observés ; aucun ordre réel. Modèle :',
              'validé' if model else 'absent, collecte seule')
        print(f'Limites paper : {max_open} positions ouvertes, '
              f'{max_entries_day} entrées/jour, perte journalière maximale '
              f'{max_daily_loss_pct:.2f}%, {max_candidates} candidats/cycle')
        stage = 'HTTP initialization'
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
        await session.__aenter__()
        while True:
            stage = 'collection'
            now = int(time.time())
            signals = recent_signals(con, now)
            active = con.execute("SELECT mint,creator,signal_time FROM paper_trades WHERE status='open'").fetchall()
            candidates = {mint: (creator, ts) for mint, creator, ts in active + signals}
            cooldown = 0
            for mint, (creator, ts) in list(candidates.items())[:max(1, max_candidates)]:
                try:
                    quote, cooldown = await fetch_quote(
                        session, mint, include_metrics=True
                    )
                    if cooldown:
                        break
                    if quote:
                        now = int(time.time())
                        existing = con.execute(
                            'SELECT 1 FROM paper_trades WHERE mint=?', (mint,)
                        ).fetchone()
                        allowed = bool(existing) or entry_allowed(
                            con, now, max_open=max_open,
                            max_entries_day=max_entries_day,
                            max_daily_loss_pct=max_daily_loss_pct,
                        )
                        message = record_quote(
                            con, mint, creator, ts, now, quote, model,
                            allow_entry=allowed,
                            max_open=max_open, max_entries_day=max_entries_day,
                            max_daily_loss_pct=max_daily_loss_pct,
                        )
                        con.commit()
                        if message:
                            print(message, flush=True)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    print(f'Prix indisponible pour {mint[:8]} : {type(exc).__name__}', flush=True)
            stage = 'poll wait'
            await asyncio.sleep(max(poll, cooldown))
    except BaseException as exc:
        failures.append((stage, exc))
    finally:
        async def cleanup():
            # Keep every acquired handle, including one whose __aenter__ failed.
            # Independent attempts preserve the primary collection error and
            # still release SQLite when HTTP cleanup itself raises or cancels.
            if session is not None:
                try:
                    await session.close()
                except BaseException as exc:
                    failures.append(('HTTP close', exc))
            if con is not None:
                try:
                    con.close()
                except BaseException as exc:
                    failures.append(('SQLite close', exc))
        await _await_paper_cleanup(cleanup(), failures)
    _raise_paper_failures(failures)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, default=BASE_DIR / 'data' / 'rugger_bot.db')
    p.add_argument('--model', type=Path, help='JSON produit par le backtest chronologique validé')
    p.add_argument('--poll', type=int, default=15,
                   help='intervalle de cotation en secondes (1 possible en paper, avec risque de 429)')
    p.add_argument('--max-open', type=int, default=3,
                   help='nombre maximum de positions paper ouvertes')
    p.add_argument('--max-entries-day', type=int, default=20,
                   help='nombre maximum d entrées paper par jour')
    p.add_argument('--max-daily-loss', type=float, default=10.0,
                   help='perte paper cumulée maximale sur une journée en pourcentage')
    p.add_argument('--max-candidates', type=int, default=10,
                   help='nombre maximum de tokens interrogés à chaque cycle')
    args = p.parse_args()
    asyncio.run(run(
        args.db, args.model, max(1, args.poll),
        max_open=max(0, args.max_open),
        max_entries_day=max(0, args.max_entries_day),
        max_candidates=max(1, args.max_candidates),
        max_daily_loss_pct=max(0.0, args.max_daily_loss),
    ))


if __name__ == '__main__':
    main()
