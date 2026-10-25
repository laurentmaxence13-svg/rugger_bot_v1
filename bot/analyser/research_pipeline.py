"""Corpus vérifié, évaluation chronologique et simulation sans transactions signées."""
import argparse
import csv
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections import Counter
from itertools import groupby
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # La dépendance reste recommandée pour l'exécution avec .env.
    def load_dotenv(*_args, **_kwargs):
        return False

from bot.config import BASE_DIR
from bot.scanner.transaction_parser import ConflictingLaunchMetadata, find_raydium_launches


def fetch_birdeye_history(mint, block_time, api_key, session=None):
    """Fetch 1-minute historical prices without inventing missing values."""
    if not api_key or not block_time:
        return []
    params = urllib.parse.urlencode({'address': mint, 'address_type': 'token',
                                     'type': '1m', 'time_from': block_time,
                                     'time_to': block_time + 86400})
    request = urllib.request.Request(
        f'https://public-api.birdeye.so/defi/history_price?{params}',
        headers={'X-API-KEY': api_key, 'x-chain': 'solana'},
    )
    opener = session or urllib.request
    with opener.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    items = ((payload.get('data') or {}).get('items') or [])
    return sorted((int(x['unixTime']), float(x['value'])) for x in items
                  if x.get('unixTime') is not None and x.get('value') is not None
                  and float(x['value']) > 0 and math.isfinite(float(x['value'])))


def backfill_historical_prices(db_path, destination, delay=1.1, api_key=None,
                               session=None):
    """Create timestamped 1m quotes for every grid horizon.

    Keeping all horizons in one CSV lets the backtest grid evaluate 1m, 5m,
    15m and 1h exits without pretending that a missing quote exists.
    """
    load_dotenv()
    api_key = api_key or os.getenv('BIRDEYE_API_KEY')
    if not api_key:
        raise ValueError('BIRDEYE_API_KEY absente du fichier .env.')
    events = verified_launches(db_path)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    rows, missing = [], 0
    for index, (timestamp, _signature, _creator, mint, _pool) in enumerate(events, 1):
        try:
            history = fetch_birdeye_history(mint, timestamp, api_key, session=session)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TypeError, KeyError) as exc:
            print(f'[{index}/{len(events)}] {mint}: erreur {exc}')
            history = []
        # Entry is one minute after launch; exits are 5m, 15m and 1h later.
        # Birdeye returns 1-minute candles, so a two-minute tolerance handles
        # small timestamp alignment differences without forward filling.
        for target in (timestamp + 60, timestamp + 300,
                       timestamp + 900, timestamp + 3660):
            candidates = [(ts, price) for ts, price in history if target <= ts <= target + 120]
            if candidates:
                rows.append((mint, candidates[0][0], candidates[0][1]))
            else:
                missing += 1
        if delay > 0 and index < len(events):
            time.sleep(delay)
    with open(destination, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['mint', 'timestamp', 'price_usd'])
        writer.writerows(rows)
    return len(events), len(rows), missing


def verified_launches(db_path):
    """All cached LaunchLab creations; retain the earliest event per mint."""
    con = sqlite3.connect(db_path)
    result = {}
    try:
        rows = con.execute('''SELECT c.signature,c.payload,l.block_time
        FROM research_tx_cache c LEFT JOIN research_launches l ON l.signature=c.signature
        WHERE c.fetched_ok=1 AND c.payload IS NOT NULL''')
        for signature, raw, saved_time in rows:
            try:
                tx = json.loads(raw)
                launches = find_raydium_launches(tx)
                timestamp = tx.get('blockTime') or saved_time
                if type(timestamp) is not int or timestamp <= 0:
                    continue
                for launch in launches:
                    mint = launch['mint']
                    event = (timestamp, signature, launch['creator'], mint, launch['pool_state'])
                    if mint not in result or event[:2] < result[mint][:2]:
                        result[mint] = event
            except ConflictingLaunchMetadata:
                warnings.warn(f'LaunchLab metadata conflict; transaction excluded: {signature}',
                              RuntimeWarning, stacklevel=2)
            except (ValueError, TypeError, AttributeError, KeyError):
                continue
    finally:
        con.close()
    return sorted(result.values())


def export_dataset(db_path, destination):
    events = verified_launches(db_path)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    previous = Counter()
    with open(destination, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['block_time', 'signature', 'creator', 'mint', 'pool_state', 'prior_launches'])
        for _timestamp, batch in groupby(events, key=lambda event: event[0]):
            batch = list(batch)
            for timestamp, signature, creator, mint, pool in batch:
                writer.writerow([timestamp, signature, creator, mint, pool, previous[creator]])
            # Same-time creations are not evidence of strictly prior launches.
            previous.update(event[2] for event in batch)
    return len(events), len(previous)


def export_prices(db_path, destination):
    con = sqlite3.connect(db_path)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    with open(destination, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['mint', 'timestamp', 'price_usd'])
        writer.writerows(con.execute('SELECT mint,timestamp,price_usd FROM paper_prices ORDER BY mint,timestamp'))
    con.close()


def load_prices(path):
    """CSV de prix capturés au fil de l'eau : mint,timestamp,price_usd."""
    prices = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                ts, price = int(row['timestamp']), float(row['price_usd'])
                if price > 0 and math.isfinite(price):
                    prices.setdefault(row['mint'], []).append((ts, price))
            except (KeyError, ValueError, TypeError):
                continue
    for series in prices.values():
        series.sort()
    return prices


def _quote_at_or_after(series, target, max_gap=120):
    """Return the first valid quote in a bounded time window."""
    return next(((ts, price) for ts, price in series
                 if target <= ts <= target + max_gap), None)


def momentum_observation(event, prices, entry_delay=300, exit_delay=900,
                         cost_bps=200, max_gap=120):
    """Build one no-lookahead observation using early price momentum.

    The +60s quote is only a reference.  The simulated entry is at +300s,
    after the momentum from +60s to +300s is observable.  The exit is at the
    requested later horizon.  Missing quotes are rejected rather than
    forward-filled.  This function is research-only; it does not place an
    order and does not activate a paper model.
    """
    timestamp, _signature, _creator, mint, _pool = event
    series = prices.get(mint, [])
    reference = _quote_at_or_after(series, timestamp + 60, max_gap)
    entry = _quote_at_or_after(series, timestamp + entry_delay, max_gap)
    exit_quote = _quote_at_or_after(series, timestamp + exit_delay, max_gap)
    if reference is None or entry is None or exit_quote is None:
        return None
    reference_time, reference_price = reference
    entry_time, entry_price = entry
    exit_time, exit_price = exit_quote
    if entry_price <= 0 or exit_price <= 0:
        return None
    momentum = entry_price / reference_price - 1.0
    net_return = (exit_price / entry_price - 1.0) - cost_bps / 10000
    return {
        'mint': mint,
        'creator': event[2],
        'reference_time': reference_time,
        'entry_time': entry_time,
        'exit_time': exit_time,
        'momentum': momentum,
        'net_return': net_return,
    }


def momentum_backtest(db_path, price_csv, exit_delay=900,
                      thresholds=(0.0, 0.05, 0.10, 0.20),
                      train_fraction=.7, min_train=30, min_test=15,
                      costs=(200, 500, 1000)):
    """Evaluate an early-momentum rule chronologically, without lookahead.

    A threshold is selected from the training period only, using the highest
    requested cost.  The same threshold is then evaluated on the untouched
    test period at every requested cost.  The result is diagnostic and is not
    accepted by the paper trader automatically.
    """
    events = verified_launches(db_path)
    split = int(len(events) * train_fraction)
    prices = load_prices(price_csv)
    observations = [momentum_observation(e, prices, exit_delay=exit_delay,
                                         cost_bps=0)
                    for e in events]
    complete = [o for o in observations if o is not None]
    complete_ids = {o['mint'] for o in complete}
    train_events = [e for e in events[:split] if e[3] in complete_ids]
    test_events = [e for e in events[split:] if e[3] in complete_ids]
    by_mint = {o['mint']: o for o in complete}
    if len(train_events) < min_train or len(test_events) < min_test:
        raise ValueError(
            f'Observations momentum insuffisantes : {len(train_events)} '
            f'entraînement et {len(test_events)} test ; '
            f'{len(events) - len(complete)} lancements incomplets.'
        )

    selection_cost = max(costs)
    candidate_scores = []
    for threshold in thresholds:
        selected = [by_mint[e[3]] for e in train_events
                    if by_mint[e[3]]['momentum'] >= threshold]
        if len(selected) < 5:
            continue
        mean = sum(o['net_return'] - selection_cost / 10000
                   for o in selected) / len(selected)
        candidate_scores.append((mean, len(selected), threshold))
    if not candidate_scores:
        return {
            'status': 'no_signal',
            'exit_delay': exit_delay,
            'entry_delay': 300,
            'train': len(train_events),
            'test': len(test_events),
            'complete': len(complete),
            'missing': len(events) - len(complete),
            'message': 'Aucun seuil momentum avec au moins 5 observations d’entraînement.',
        }

    # Prefer the strongest training mean; use the lowest threshold only as a
    # deterministic tie-breaker so the rule is reproducible.
    best_train_mean, best_count, threshold = max(
        candidate_scores, key=lambda item: (item[0], item[1], -item[2])
    )
    runs = []
    for cost in costs:
        selected_test = [by_mint[e[3]] for e in test_events
                         if by_mint[e[3]]['momentum'] >= threshold]
        returns = [o['net_return'] - cost / 10000 for o in selected_test]
        runs.append({
            'status': 'no_signal' if not returns else 'evaluated',
            'exit_delay': exit_delay,
            'entry_delay': 300,
            'threshold': threshold,
            'assumed_cost_bps': cost,
            'train': len(train_events),
            'test': len(test_events),
            'selected': len(returns),
            'missing': len(events) - len(complete),
            'train_mean_return': best_train_mean,
            'mean_return': sum(returns) / len(returns) if returns else None,
            'win_rate': (sum(value > 0 for value in returns) / len(returns)
                         if returns else None),
        })
    eligible = (best_train_mean > 0 and
                all(r['selected'] >= 5 and r['mean_return'] is not None
                    and r['mean_return'] > 0 for r in runs))
    return {
        'status': 'validated_momentum' if eligible else 'no_signal',
        'exit_delay': exit_delay,
        'entry_delay': 300,
        'threshold': threshold,
        'train': len(train_events),
        'test': len(test_events),
        'complete': len(complete),
        'missing': len(events) - len(complete),
        'selected_train': best_count,
        'train_mean_return': best_train_mean,
        'runs': runs,
        'message': ('Seuil momentum positif et robuste à tous les coûts.'
                    if eligible else
                    'Aucun seuil momentum positif hors échantillon à tous les coûts.'),
    }


def momentum_grid(db_path, price_csv, exit_delays=(900, 3660),
                  costs=(200, 500, 1000)):
    """Run the momentum diagnostic on the available 15m and 1h exits."""
    runs = []
    for exit_delay in exit_delays:
        try:
            result = momentum_backtest(db_path, price_csv,
                                       exit_delay=exit_delay, costs=costs)
        except ValueError as exc:
            result = {
                'status': 'insufficient_data',
                'exit_delay': exit_delay,
                'error': str(exc),
            }
        runs.append(result)
    eligible = [r['exit_delay'] for r in runs
                if r.get('status') == 'validated_momentum']
    return {
        'schema': 'momentum-grid-v1',
        'status': 'validated_momentum_found' if eligible else 'no_validated_momentum',
        'eligible_exit_delays': eligible,
        'runs': runs,
        'message': ('Au moins un seuil momentum reste positif à tous les coûts.'
                    if eligible else
                    'Aucun seuil momentum robuste ; aucun modèle activable.'),
    }


def outcome(event, prices, entry_delay=60, hold_seconds=3600, max_gap=120, cost_bps=200):
    timestamp, _, _, mint, _ = event
    series = prices.get(mint, [])
    entry_target, exit_target = timestamp + entry_delay, timestamp + entry_delay + hold_seconds
    entry = next(((t, p) for t, p in series if entry_target <= t <= entry_target + max_gap), None)
    exit_price = next(((t, p) for t, p in series if exit_target <= t <= exit_target + max_gap), None)
    if entry is None or exit_price is None:
        return None  # Aucune extrapolation sur une cotation manquante.
    return (exit_price[1] / entry[1] - 1) - cost_bps / 10000


def backtest(db_path, price_csv, train_fraction=.7, min_train=30, min_test=15,
             hold_seconds=3600, cost_bps=200):
    events = verified_launches(db_path)
    split = int(len(events) * train_fraction)
    if split < min_train or len(events) - split < min_test:
        raise ValueError(f'Corpus insuffisant : {len(events)} lancements ; requis >= {min_train} entraînement et {min_test} test.')
    prices = load_prices(price_csv)
    # Les prix manquants sont exclus, jamais transformés en gain, perte ou zéro.
    # verified_launches returns one event per mint, but signatures can repeat.
    outcomes = {e[3]: outcome(e, prices, hold_seconds=hold_seconds,
                               cost_bps=cost_bps) for e in events}
    missing = sum(v is None for v in outcomes.values())
    train = [e for e in events[:split] if outcomes[e[3]] is not None]
    test = [e for e in events[split:] if outcomes[e[3]] is not None]
    if len(train) < min_train or len(test) < min_test:
        raise ValueError(f'Observations complètes insuffisantes : {len(train)} entraînement et '
                         f'{len(test)} test ; {missing} lancements exclus faute de prix.')
    by_creator = {}
    for e in train:
        by_creator.setdefault(e[2], []).append(outcomes[e[3]])
    global_mean = sum(outcomes[e[3]] for e in train) / len(train)
    # Lissage vers la moyenne d'entraînement pour éviter un score extrême après 1 trade.
    scores = {c: (sum(v) + 5 * global_mean) / (len(v) + 5) for c, v in by_creator.items()}
    test_scored = [(e, outcomes[e[3]], scores.get(e[2], global_mean)) for e in test]
    ranked = sorted(test_scored, key=lambda item: item[2], reverse=True)
    top_n = max(1, math.ceil(len(ranked) * 0.2))
    top_ranked = ranked[:top_n]
    diagnostics = {
        'train_mean_return': global_mean,
        'test_mean_all': sum(item[1] for item in test_scored) / len(test_scored),
        'test_known_creator': sum(item[2] != global_mean for item in test_scored),
        'test_positive_score': sum(item[2] > 0 for item in test_scored),
        'top_20pct_count': len(top_ranked),
        'top_20pct_mean_return': sum(item[1] for item in top_ranked) / len(top_ranked),
    }
    scored = [(e, outcomes[e[3]]) for e in test if scores.get(e[2], global_mean) > 0]
    if not scored:
        return {'status': 'no_signal', 'train': len(train), 'test': len(test),
                'selected': 0, 'excluded_missing_prices': missing,
                'train_end': train[-1][0], 'test_start': test[0][0],
                'mean_return': None, 'win_rate': None,
                'assumed_cost_bps': cost_bps, 'hold_seconds': hold_seconds,
                'creator_scores': scores,
                'fallback_score': global_mean, 'diagnostics': diagnostics,
                'message': 'Aucun signal positif hors échantillon ; aucune performance annoncée.'}
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for _, pnl in sorted(scored, key=lambda item: item[0][0]):
        equity *= 1.0 + pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    diagnostics['selected_max_drawdown'] = max_drawdown
    diagnostics['selected_equity_multiple'] = equity
    return {'train': len(train), 'test': len(test), 'selected': len(scored),
            'excluded_missing_prices': missing,
            'train_end': train[-1][0], 'test_start': test[0][0],
            'mean_return': sum(p for _, p in scored) / len(scored),
            'win_rate': sum(p > 0 for _, p in scored) / len(scored),
            'assumed_cost_bps': cost_bps, 'hold_seconds': hold_seconds,
            'creator_scores': scores, 'fallback_score': global_mean,
            'diagnostics': diagnostics}


def backtest_grid(db_path, price_csv, horizons=(300, 900, 3600),
                  costs=(200, 500, 1000), train_fraction=.7,
                  min_train=30, min_test=15):
    """Compare predefined horizons/costs without selecting on a single split.

    The grid is diagnostic only: a model is considered eligible only when its
    out-of-sample mean is positive at every requested cost for one horizon.
    """
    runs = []
    for horizon in horizons:
        for cost in costs:
            try:
                result = backtest(db_path, price_csv, train_fraction, min_train,
                                  min_test, horizon, cost)
            except ValueError as exc:
                result = {
                    'status': 'insufficient_data',
                    'hold_seconds': horizon,
                    'assumed_cost_bps': cost,
                    'error': str(exc),
                }
            runs.append(result)
    by_horizon = {}
    for result in runs:
        by_horizon.setdefault(str(result.get('hold_seconds')), []).append(result)
    eligible = []
    for horizon, results in by_horizon.items():
        if len(results) == len(costs) and all(r.get('selected', 0) >= 5
               and r.get('mean_return') is not None
               and r['mean_return'] > 0 for r in results):
            eligible.append(horizon)
    return {
        'status': 'validated_horizon_found' if eligible else 'no_validated_horizon',
        'eligible_horizons': [int(h) for h in eligible],
        'runs': runs,
        'message': ('Au moins un horizon reste positif à tous les coûts testés.'
                    if eligible else
                    'Aucun horizon robuste positif après coûts ; aucun modèle activable.')
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['dataset', 'prices', 'historical-prices',
                                       'backtest', 'backtest-grid',
                                       'momentum-grid', 'behavior-grid'])
    p.add_argument('--db', type=Path, default=BASE_DIR / 'data' / 'rugger_bot.db')
    p.add_argument('--output', type=Path, default=BASE_DIR / 'data' / 'verified_launches.csv')
    p.add_argument('--prices', type=Path)
    p.add_argument('--delay', type=float, default=1.1,
                   help='pause entre requêtes Birdeye (secondes)')
    p.add_argument('--hold-seconds', type=int, default=3600)
    p.add_argument('--cost-bps', type=int, default=200)
    args = p.parse_args()
    if args.command == 'dataset':
        n, creators = export_dataset(args.db, args.output)
        print(f'{n} lancements vérifiés ; {creators} créateurs ; {args.output}')
    elif args.command == 'prices':
        export_prices(args.db, args.output)
        print(f'Prix exportés : {args.output}')
    elif args.command == 'historical-prices':
        n, rows, missing = backfill_historical_prices(args.db, args.output, args.delay)
        print(f'{rows} cotations historiques écrites pour {n} lancements ; '
              f'{missing} points manquants ; {args.output}')
    elif args.command == 'backtest':
        if not args.prices:
            p.error('--prices requis : historique horodaté, pas de backtest sur les prix actuels')
        result = backtest(args.db, args.prices, hold_seconds=args.hold_seconds,
                          cost_bps=args.cost_bps)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    elif args.command == 'backtest-grid':
        if not args.prices:
            p.error('--prices requis : historique horodaté, pas de backtest sur les prix actuels')
        result = backtest_grid(args.db, args.prices)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    elif args.command == 'momentum-grid':
        if not args.prices:
            p.error('--prices requis : historique horodaté, pas de backtest sur les prix actuels')
        result = momentum_grid(args.db, args.prices)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    else:
        if not args.prices:
            p.error('--prices requis : historique horodaté, pas de backtest sur les prix actuels')
        from bot.analyser.behavior_pipeline import behavior_grid
        result = behavior_grid(args.db, args.prices)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
