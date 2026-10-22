"""Prix en direct et carnet simulé. Aucun portefeuille, signature ou envoi d'ordre."""
import argparse
import asyncio
from dataclasses import dataclass
import json
import math
import sqlite3
import time
from pathlib import Path

import aiohttp

from bot.config import BASE_DIR

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
    quote_source: str = 'dex_market'
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
    if liquidity is None or price is None or not pair_address:
        return None
    depth_usd, slippage_bps_est = _constant_product_estimate(pair, price)
    return MarketQuote(
        liquidity_usd=liquidity,
        price_usd=price,
        pair_address=str(pair_address),
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
    con.executescript('''
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

    day_start = int(now) - int(now) % 86400
    entries_today = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE entry_time >= ? AND entry_time <= ?",
        (day_start, int(now)),
    ).fetchone()[0]
    if entries_today >= max(0, int(max_entries_day)):
        return False

    if max_daily_loss_pct is not None and float(max_daily_loss_pct) > 0:
        pnl_today, missing = con.execute(
            """SELECT COALESCE(SUM(pnl_sol), 0),
                      COALESCE(SUM(CASE WHEN pnl_sol IS NULL THEN 1 ELSE 0 END), 0)
               FROM paper_trades
               WHERE status='closed' AND exit_time >= ? AND exit_time <= ?""",
            (day_start, int(now)),
        ).fetchone()

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
    return MarketQuote(float(liquidity), float(price), str(pair))


def record_quote(con, mint, creator, signal_time, now, quote, model,
                 hold=3600, cost_bps=200, allow_entry=True,
                 strategy_mode='validated', force_exit_reason=None,
                 initial_capital_sol=10.0, position_pct=10.0):
    market_quote = _quote_values(quote)
    liquidity, price, pair = market_quote
    con.execute(
        '''INSERT OR IGNORE INTO paper_prices(
             mint,timestamp,price_usd,pair_address,liquidity_usd,
             volume_5m_usd,volume_24h_usd,price_change_5m_pct,
             price_change_1h_pct,tx_buys_5m,tx_sells_5m,market_cap_usd,
             fdv_usd,fee_bps,depth_usd,slippage_bps_est,
             slippage_notional_usd)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (
            mint, now, market_quote.price_usd, market_quote.pair_address,
            market_quote.liquidity_usd, market_quote.volume_5m_usd,
            market_quote.volume_24h_usd, market_quote.price_change_5m_pct,
            market_quote.price_change_1h_pct, market_quote.tx_buys_5m,
            market_quote.tx_sells_5m, market_quote.market_cap_usd,
            market_quote.fdv_usd, market_quote.fee_bps,
            market_quote.depth_usd, market_quote.slippage_bps_est,
            market_quote.slippage_notional_usd,
        ),
    )
    trade = con.execute('''SELECT entry_time,entry_price,status,peak_price
                           FROM paper_trades WHERE mint=?''', (mint,)).fetchone()
    if trade and trade[2] == 'open':
        entry_time, entry_price, _status, previous_peak = trade
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
        if reason:
            result = gross_return - cost / 10000
            ensure_paper_portfolio(con, initial_capital_sol, now)
            position_row = con.execute('SELECT position_sol FROM paper_trades WHERE mint=?', (mint,)).fetchone()
            position_sol = float((position_row or [0.0])[0] or 0.0)
            pnl_sol = position_sol * result
            _initial, capital_before = paper_capital(con)
            capital_after = max(0.0, float(capital_before or 0.0) + pnl_sol)
            con.execute('UPDATE paper_portfolio SET realized_capital_sol=?,updated_at=? WHERE id=1', (capital_after, now))
            con.execute('''UPDATE paper_trades
                           SET exit_time=?,exit_price=?,net_return=?,exit_reason=?,
                               peak_price=?,last_price=?,last_quote_time=?,pnl_sol=?,
                               capital_after_sol=?,status='closed'
                           WHERE mint=? AND status='open' ''',
                        (now, price, result, reason, peak, price, now, pnl_sol, capital_after, mint))
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
    ensure_paper_portfolio(con, initial_capital_sol, now)
    _initial, capital = paper_capital(con)
    position_sol = max(0.0, float(capital or 0.0) * max(0.0, min(100.0, float(position_pct))) / 100.0)
    if position_sol <= 0:
        return None
    con.execute('''INSERT OR IGNORE INTO paper_trades
        (mint,creator,signal_time,entry_time,entry_price,peak_price,last_price,
         last_quote_time,cost_bps,strategy_mode,position_sol,status) VALUES(?,?,?,?,?,?,?,?,?,?,?, 'open')''',
        (mint, creator, signal_time, now, price, price, price, now, cost,
         str(strategy_mode or 'validated'), position_sol))
    score_label = (f'{score:.1f}/100' if strategy_mode == 'shadow_final'
                   else f'{score:+.2%}')
    return (f'ENTRY {mint} simulated price={price:.10g} USD score={score_label} '
            f'size={position_sol:.6f} SOL capital={float(capital):.6f} SOL')


async def run(db, model_path=None, poll=15, max_open=3,
              max_entries_day=20, max_candidates=10,
              max_daily_loss_pct=10.0):
    model = eligible_model(model_path)
    con = sqlite3.connect(db, timeout=30.0, isolation_level=None)
    con.execute('PRAGMA busy_timeout=30000')
    setup(con)
    print('PAPER ONLY : prix observés ; aucun ordre réel. Modèle :',
          'validé' if model else 'absent, collecte seule')
    print(f'Limites paper : {max_open} positions ouvertes, '
          f'{max_entries_day} entrées/jour, perte journalière maximale '
          f'{max_daily_loss_pct:.2f}%, {max_candidates} candidats/cycle')
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
        while True:
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
                        )
                        con.commit()
                        if message:
                            print(message, flush=True)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    print(f'Prix indisponible pour {mint[:8]} : {type(exc).__name__}', flush=True)
            await asyncio.sleep(max(poll, cooldown))


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
