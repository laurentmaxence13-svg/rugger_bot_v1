"""Prix en direct et carnet simulé. Aucun portefeuille, signature ou envoi d'ordre."""
import argparse
import asyncio
import json
import math
import sqlite3
import time
from pathlib import Path

import aiohttp

from bot.config import BASE_DIR

API = 'https://api.dexscreener.com/token-pairs/v1/solana/'


def setup(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS paper_prices (
      mint TEXT NOT NULL, timestamp INTEGER NOT NULL, price_usd REAL NOT NULL,
      pair_address TEXT NOT NULL, liquidity_usd REAL NOT NULL,
      PRIMARY KEY(mint,timestamp));
    CREATE TABLE IF NOT EXISTS paper_trades (
      mint TEXT PRIMARY KEY, creator TEXT NOT NULL, signal_time INTEGER NOT NULL,
      entry_time INTEGER NOT NULL, entry_price REAL NOT NULL,
      exit_time INTEGER, exit_price REAL, net_return REAL, exit_reason TEXT,
      peak_price REAL, last_price REAL, last_quote_time INTEGER,
      status TEXT NOT NULL CHECK(status IN ('open','closed')));
    ''')
    # Existing user databases were created before dynamic exits existed.
    # Migrate them in place without deleting any paper-trading history.
    columns = {row[1] for row in con.execute('PRAGMA table_info(paper_trades)')}
    for name, definition in (
        ('exit_reason', 'TEXT'),
        ('peak_price', 'REAL'),
        ('last_price', 'REAL'),
        ('last_quote_time', 'INTEGER'),
    ):
        if name not in columns:
            con.execute(f'ALTER TABLE paper_trades ADD COLUMN {name} {definition}')


def model_risk(model, hold=3600, cost_bps=200):
    """Read optional paper-only risk parameters from a validated model."""
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
    return hold, cost_bps, percent('tp_pct'), percent('sl_pct')


def entry_allowed(con, now, max_open=3, max_entries_day=20,
                  max_daily_loss_pct=10.0):
    """Hard paper-only limits; return False before creating a new position."""
    open_count = con.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE status='open'"
    ).fetchone()[0]
    if open_count >= max(0, int(max_open)):
        return False
    day_start = int(now) - (int(now) % 86400)
    entries_today = con.execute(
        'SELECT COUNT(*) FROM paper_trades WHERE entry_time >= ?',
        (day_start,),
    ).fetchone()[0]
    if entries_today >= max(0, int(max_entries_day)):
        return False
    if max_daily_loss_pct is not None and float(max_daily_loss_pct) > 0:
        pnl_today = con.execute(
            '''SELECT COALESCE(SUM(net_return), 0) FROM paper_trades
               WHERE entry_time >= ? AND status='closed' ''',
            (day_start,),
        ).fetchone()[0] or 0.0
        if pnl_today <= -float(max_daily_loss_pct) / 100.0:
            return False
    return True


def eligible_model(path):
    if not path:
        return None
    model = json.loads(Path(path).read_text(encoding='utf-8'))
    if (model.get('train', 0) < 30 or model.get('test', 0) < 15
            or model.get('selected', 0) < 5 or model.get('mean_return', 0) <= 0):
        raise ValueError('Modèle non validé hors échantillon : simulation des entrées désactivée.')
    return model


def choose_quote(pairs, mint, min_liquidity=10000):
    usable = []
    for pair in pairs if isinstance(pairs, list) else []:
        try:
            if pair.get('chainId') != 'solana' or pair['baseToken']['address'] != mint:
                continue
            price = float(pair['priceUsd'])
            liquidity = float(pair['liquidity']['usd'])
            if price > 0 and math.isfinite(price) and liquidity >= min_liquidity:
                usable.append((liquidity, price, pair['pairAddress']))
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return max(usable) if usable else None


async def fetch_quote(session, mint):
    async with session.get(API + mint) as resp:
        if resp.status == 429:
            return None, 60
        resp.raise_for_status()
        return choose_quote(await resp.json(content_type=None), mint), 0


def recent_signals(con, now, max_age=3660):
    # Un signal provenant du scanner live, confirmé par son parseur strict.
    return con.execute('''SELECT mint,deployer_candidate,block_time FROM launch_candidates
      WHERE status='creator_identified' AND mint IS NOT NULL AND block_time BETWEEN ? AND ?
      ORDER BY block_time DESC LIMIT 10''', (now-max_age, now)).fetchall()


def record_quote(con, mint, creator, signal_time, now, quote, model,
                 hold=3600, cost_bps=200, allow_entry=True):
    liquidity, price, pair = quote
    con.execute('INSERT OR IGNORE INTO paper_prices VALUES(?,?,?,?,?)',
                (mint, now, price, pair, liquidity))
    trade = con.execute('''SELECT entry_time,entry_price,status,peak_price
                           FROM paper_trades WHERE mint=?''', (mint,)).fetchone()
    if trade and trade[2] == 'open':
        entry_time, entry_price, _status, previous_peak = trade
        peak = max(float(previous_peak or entry_price), price)
        gross_return = price / entry_price - 1
        hold_s, cost, tp_pct, sl_pct = model_risk(model, hold, cost_bps)
        reason = None
        if tp_pct is not None and gross_return >= tp_pct / 100:
            reason = 'TP'
        elif sl_pct is not None and gross_return <= -sl_pct / 100:
            reason = 'SL'
        elif now >= entry_time + hold_s:
            reason = 'TIMEOUT'
        if reason:
            result = gross_return - cost / 10000
            con.execute('''UPDATE paper_trades
                           SET exit_time=?,exit_price=?,net_return=?,exit_reason=?,
                               peak_price=?,last_price=?,last_quote_time=?,status='closed'
                           WHERE mint=? AND status='open' ''',
                        (now, price, result, reason, peak, price, now, mint))
            return f'EXIT {mint} reason={reason} simulated net={result:+.2%}'
        con.execute('''UPDATE paper_trades
                       SET peak_price=?,last_price=?,last_quote_time=?
                       WHERE mint=? AND status='open' ''', (peak, price, now, mint))
        return None
    if (trade or model is None or not allow_entry
            or now < signal_time + 60 or now > signal_time + 180):
        return None
    score = model['creator_scores'].get(creator, model['fallback_score'])
    if score <= 0:
        return None
    hold_s, cost, _tp_pct, _sl_pct = model_risk(model, hold, cost_bps)
    con.execute('''INSERT OR IGNORE INTO paper_trades
        (mint,creator,signal_time,entry_time,entry_price,peak_price,last_price,
         last_quote_time,status) VALUES(?,?,?,?,?,?,?,?, 'open')''',
        (mint, creator, signal_time, now, price, price, price, now))
    return f'ENTRY {mint} simulated price={price:.10g} USD score={score:+.2%}'


async def run(db, model_path=None, poll=15, max_open=3,
              max_entries_day=20, max_candidates=10,
              max_daily_loss_pct=10.0):
    model = eligible_model(model_path)
    con = sqlite3.connect(db)
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
                    quote, cooldown = await fetch_quote(session, mint)
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
