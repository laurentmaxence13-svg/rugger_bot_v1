import argparse
import asyncio
import json
import math
import aiohttp
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import find_raydium_launch

PAGE_SIZE = 100
DEFAULT_INTERVAL = 1.10          # ~0.9 requête/s : volontairement conservateur
MAX_INTERVAL = 12.0
MIN_INTERVAL = 0.65
BACKOFF_FACTOR = 1.8


def db_connect(path):
    con = sqlite3.connect(path)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    return con


def ensure_schema(path):
    con = db_connect(path)
    con.executescript('''
    CREATE TABLE IF NOT EXISTS research_creators (
        creator TEXT PRIMARY KEY,
        launches_found INTEGER NOT NULL DEFAULT 0,
        tx_scanned INTEGER NOT NULL DEFAULT 0,
        first_launch_time INTEGER,
        last_launch_time INTEGER,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_launches (
        signature TEXT PRIMARY KEY,
        creator TEXT NOT NULL,
        mint TEXT NOT NULL,
        pool_state TEXT,
        block_time INTEGER,
        source TEXT NOT NULL DEFAULT 'history',
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS research_tx_cache (
        signature TEXT PRIMARY KEY,
        payload TEXT,
        fetched_ok INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_research_launches_creator_time
        ON research_launches(creator, block_time);
    CREATE INDEX IF NOT EXISTS idx_research_launches_mint
        ON research_launches(mint);
    ''')
    con.commit()
    con.close()


def seed_creators(path, limit):
    con = db_connect(path)
    rows = con.execute('''
        SELECT creator, COUNT(*) AS n FROM (
            SELECT deployer_candidate AS creator FROM launch_candidates
            WHERE status='creator_identified' AND deployer_candidate IS NOT NULL
            UNION ALL
            SELECT creator FROM research_launches WHERE creator IS NOT NULL
        )
        GROUP BY creator
        ORDER BY n DESC, creator
        LIMIT ?
    ''', (limit,)).fetchall()
    con.close()
    return [(r[0], r[1]) for r in rows]


class AdaptiveRPCGate:
    """Une SEULE porte pour tous les appels RPC du moteur."""
    def __init__(self, interval=DEFAULT_INTERVAL):
        self.interval = max(MIN_INTERVAL, float(interval))
        self.last_call = 0.0
        self.cooldown_until = 0.0
        self.lock = asyncio.Lock()
        self.calls = 0
        self.rate_limits = 0

    async def wait_turn(self):
        async with self.lock:
            now = time.monotonic()
            wait = max(self.interval - (now - self.last_call), self.cooldown_until - now)
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_call = time.monotonic()
            self.calls += 1

    def on_429(self, retry_after=None):
        self.rate_limits += 1
        self.interval = min(MAX_INTERVAL, max(self.interval + 0.5, self.interval * BACKOFF_FACTOR))
        self.cooldown_until = max(self.cooldown_until, time.monotonic() + max(self.interval, retry_after or 0))


def retry_after_seconds(value):
    if not value:
        return None
    try:
        number = float(value)
        return max(0.0, number) if math.isfinite(number) else None
    except (TypeError, ValueError):
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


async def rpc_json(rpc, rpc_url, gate, method, params, max_attempts=8):
    delay = 2.0
    for attempt in range(1, max_attempts + 1):
        await gate.wait_turn()
        try:
            async with rpc.session.post(
                rpc_url,
                json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
            ) as resp:
                status = resp.status
                if status == 429:
                    sleep_for = max(delay, retry_after_seconds(resp.headers.get('Retry-After')) or 0)
                    gate.on_429(sleep_for)
                    print(f'\n[HELIUS 429] pause {sleep_for:.1f}s | cadence -> 1 requête / {gate.interval:.2f}s')
                    delay = min(30.0, delay * 2.0)
                    continue
                if status >= 500:
                    gate.cooldown_until = max(gate.cooldown_until, time.monotonic() + delay)
                    delay = min(30.0, delay * 2.0)
                    continue
                if status >= 400:
                    raise RuntimeError(f'RPC HTTP {status} pour {method}')
                data = await resp.json(content_type=None)
        except (asyncio.TimeoutError, OSError, aiohttp.ClientError, ValueError):
            gate.cooldown_until = max(gate.cooldown_until, time.monotonic() + delay)
            delay = min(30.0, delay * 2.0)
            continue

        if isinstance(data, dict) and data.get('error'):
            err = data['error']
            if isinstance(err, dict) and err.get('code') == 429:
                gate.on_429(delay)
                delay = min(30.0, delay * 2.0)
                continue
            raise RuntimeError(f"RPC {method}: code {err.get('code') if isinstance(err, dict) else 'inconnu'}")
        if not isinstance(data, dict) or 'result' not in data:
            raise RuntimeError(f'RPC {method}: réponse invalide')
        return data['result']
    raise RuntimeError(f'RPC {method}: échec après {max_attempts} tentatives (429={gate.rate_limits})')


async def signatures(rpc, rpc_url, gate, address, max_tx):
    out, before = [], None
    while len(out) < max_tx:
        opts = {'limit': min(PAGE_SIZE, max_tx - len(out))}
        if before:
            opts['before'] = before
        page = await rpc_json(rpc, rpc_url, gate, 'getSignaturesForAddress', [address, opts])
        if not isinstance(page, list):
            raise RuntimeError('Liste de signatures invalide')
        if not page:
            break
        out.extend(page)
        if len(page) < opts['limit']:
            break
        before = page[-1].get('signature')
        if not before:
            break
    return out[:max_tx]


def cache_get(path, signature):
    con = db_connect(path)
    row = con.execute(
        'SELECT payload, fetched_ok FROM research_tx_cache WHERE signature=?',
        (signature,)
    ).fetchone()
    con.close()
    if not row or not row[1] or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def cache_put(path, signature, tx):
    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(tx, separators=(',', ':')) if tx is not None else None
    con = db_connect(path)
    con.execute('''
        INSERT INTO research_tx_cache(signature, payload, fetched_ok, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(signature) DO UPDATE SET
          payload=excluded.payload, fetched_ok=excluded.fetched_ok, updated_at=excluded.updated_at
    ''', (signature, payload, 1 if tx is not None else 0, now))
    con.commit()
    con.close()


async def get_transaction_cached(path, rpc, rpc_url, gate, signature):
    cached = cache_get(path, signature)
    if cached is not None:
        return cached, True
    tx = await rpc_json(
        rpc, rpc_url, gate, 'getTransaction',
        [signature, {'encoding': 'jsonParsed', 'maxSupportedTransactionVersion': 1}]
    )
    if tx is not None:
        cache_put(path, signature, tx)
    return tx, False


def save_result(path, creator, tx_count, launches):
    now = datetime.now(timezone.utc).isoformat()
    times = [x['block_time'] for x in launches if x['block_time'] is not None]
    con = db_connect(path)
    con.execute('''
        INSERT INTO research_creators(creator, launches_found, tx_scanned, first_launch_time, last_launch_time, updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(creator) DO UPDATE SET
          launches_found=excluded.launches_found, tx_scanned=excluded.tx_scanned,
          first_launch_time=excluded.first_launch_time, last_launch_time=excluded.last_launch_time,
          updated_at=excluded.updated_at
    ''', (creator, len(launches), tx_count, min(times) if times else None, max(times) if times else None, now))
    for x in launches:
        con.execute('''
            INSERT INTO research_launches(signature, creator, mint, pool_state, block_time, source, updated_at)
            VALUES(?,?,?,?,?,'history',?)
            ON CONFLICT(signature) DO UPDATE SET
              creator=excluded.creator, mint=excluded.mint, pool_state=excluded.pool_state,
              block_time=excluded.block_time, updated_at=excluded.updated_at
        ''', (x['signature'], creator, x['mint'], x['pool_state'], x['block_time'], now))
    # Recalcul cumulatif : une petite collecte ne doit pas effacer les totaux.
    con.execute('''UPDATE research_creators SET
      launches_found=(SELECT COUNT(DISTINCT mint) FROM research_launches WHERE creator=?),
      first_launch_time=(SELECT MIN(block_time) FROM research_launches WHERE creator=?),
      last_launch_time=(SELECT MAX(block_time) FROM research_launches WHERE creator=?)
      WHERE creator=?''', (creator, creator, creator, creator))
    con.commit()
    con.close()


async def analyse_creator(settings, rpc, gate, creator, max_tx):
    sigs = await signatures(rpc, settings.rpc_url, gate, creator, max_tx)
    launches = []
    cached_count = 0
    for i, item in enumerate(sigs, 1):
        sig = item.get('signature')
        if not sig:
            continue
        tx, cached = await get_transaction_cached(settings.db_path, rpc, settings.rpc_url, gate, sig)
        cached_count += int(cached)
        if tx:
            launch = find_raydium_launch(tx)
            if launch and launch.get('creator') == creator and launch.get('mint'):
                launches.append({
                    'signature': sig,
                    'creator': creator,
                    'mint': launch['mint'],
                    'pool_state': launch.get('pool_state'),
                    'block_time': item.get('blockTime') or tx.get('blockTime'),
                })
        if i % 20 == 0 or i == len(sigs):
            print(
                f'  {creator[:8]}… {i}/{len(sigs)} tx | {len(launches)} launches | cache {cached_count} | 429 {gate.rate_limits}',
                end='\r'
            )
    print(' ' * 120, end='\r')
    save_result(settings.db_path, creator, len(sigs), launches)
    return len(sigs), launches, cached_count


def report(path, min_launches, gate):
    con = db_connect(path)
    creators = con.execute('''
        SELECT creator, launches_found, tx_scanned, first_launch_time, last_launch_time
        FROM research_creators WHERE launches_found >= ?
        ORDER BY launches_found DESC, last_launch_time DESC
    ''', (min_launches,)).fetchall()
    total_launches = con.execute('SELECT COUNT(*) FROM research_launches').fetchone()[0]
    distinct_mints = con.execute('SELECT COUNT(DISTINCT mint) FROM research_launches').fetchone()[0]
    cached = con.execute('SELECT COUNT(*) FROM research_tx_cache WHERE fetched_ok=1').fetchone()[0]
    con.close()
    print('\n' + '=' * 110)
    print('MULTI-CREATOR RESEARCH ENGINE — CORPUS ON-CHAIN')
    print('=' * 110)
    print(f'Creators récurrents (>= {min_launches} launches): {len(creators)}')
    print(f'Launches historiques stockés                 : {total_launches}')
    print(f'Mints uniques                                : {distinct_mints}')
    print(f'Transactions en cache                        : {cached}')
    print(f'Appels RPC cette exécution                    : {gate.calls}')
    print(f'Réponses 429                                  : {gate.rate_limits}')
    print(f'Cadence finale                                : 1 requête / {gate.interval:.2f}s')
    print('\nTOP CREATORS')
    print(f"{'Creator':46} {'Launches':>9} {'Tx scan':>9}")
    for creator, n, txc, _, _ in creators[:30]:
        print(f'{creator:46} {n:>9} {txc:>9}')
    if total_launches < 100:
        print('\nSTATUT : corpus encore trop petit pour rechercher sérieusement un edge généralisable.')
    else:
        print('\nSTATUT : vérifier couverture des prix, diversité et validation hors échantillon ; le volume seul ne suffit pas.')


async def main():
    p = argparse.ArgumentParser(description='Corpus multi-creator Raydium LaunchLab avec limitation RPC Helius centralisée.')
    p.add_argument('--max-creators', type=int, default=50)
    p.add_argument('--max-tx', type=int, default=100)
    p.add_argument('--min-launches', type=int, default=2)
    p.add_argument('--rpc-interval', type=float, default=DEFAULT_INTERVAL)
    args = p.parse_args()

    settings = get_settings()
    ensure_schema(settings.db_path)
    seeds = seed_creators(settings.db_path, args.max_creators)
    if not seeds:
        print('Aucun créateur confirmé. Lance d’abord le scanner live pour alimenter la base.')
        return

    gate = AdaptiveRPCGate(args.rpc_interval)
    print('=' * 110)
    print('MULTI-CREATOR RESEARCH ENGINE — HELIUS SAFE')
    print('=' * 110)
    print(f'Creators candidats : {len(seeds)} | max tx/creator : {args.max_tx}')
    print(f'RPC centralisé : OUI | concurrence RPC : 1 | cadence initiale : 1 requête / {gate.interval:.2f}s')
    print('Cache/reprise SQLite : OUI — une transaction déjà téléchargée ne consomme plus de RPC.\n')

    completed = 0
    try:
        async with SolanaRPC(settings.rpc_url) as rpc:
            for creator, _ in seeds:
                completed += 1
                try:
                    tx_count, launches, cached_count = await analyse_creator(settings, rpc, gate, creator, args.max_tx)
                    print(f'[{completed}/{len(seeds)}] {creator[:12]}… -> {len(launches)} launches / {tx_count} tx | cache={cached_count} | 429={gate.rate_limits}')
                except Exception as exc:
                    print(f'[{completed}/{len(seeds)}] erreur {creator[:12]}… : {type(exc).__name__}: {exc}')
    except KeyboardInterrupt:
        print('\nArrêt demandé. Les creators terminés et transactions en cache sont conservés.')

    report(settings.db_path, args.min_launches, gate)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\nArrêt propre.')
