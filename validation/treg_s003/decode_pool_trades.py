"""T-REG S-003 / T-0008: decode every trade of the 3 certified SOL pool archives (offline).

Input: tests/fixtures/launchlab_sol_pools/ at 4f2875d, certified by T-0007.
Uses only the decoders already in the repository (bot.market.launchlab_events);
no network, no key, no change to bot code.

For each pool: the archive lists MANIFEST `signatures` signatures and stores
exactly the successful ones (err null); every trade passes the exact curve
check; the number of decoded trades equals MANIFEST `trades`; every implied fee
rate equals MANIFEST `fee_rate_ppm`. One JSON line per trade, then one summary
line per pool.

  python -B validation/treg_s003/decode_pool_trades.py > validation/treg_s003/pool_trade_checks.jsonl
"""
import dataclasses
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bot.market.launchlab_events import check_trade, extract_trade_events, implied_fee_rate_ppm  # noqa: E402

PACK = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
manifest = json.loads((PACK / 'MANIFEST.json').read_text(encoding='utf-8'))
summaries = []
for pool in sorted(manifest['pools'], key=lambda p: p['pool']):
    archive = json.loads(gzip.decompress((PACK / pool['file']).read_bytes()))
    trades, exact, fee_match = 0, 0, 0
    for signature in sorted(archive['transactions']):
        tx = archive['transactions'][signature]
        result = tx.get('result', tx) if isinstance(tx, dict) else tx
        if not result:
            continue
        for index, event in enumerate(extract_trade_events(result)):
            values = dataclasses.asdict(event)
            try:
                check_trade(values)
                ok = True
            except ValueError:
                ok = False
            fee = implied_fee_rate_ppm(values)
            trades += 1
            exact += ok
            fee_match += fee == pool['fee_rate_ppm']
            print(json.dumps({'pool': pool['pool'], 'signature': signature, 'index': index, 'side': values['side'],
                              'slot': values['slot'], 'exact_curve_check': ok, 'implied_fee_rate_ppm': fee,
                              'manifest_fee_rate_ppm': pool['fee_rate_ppm']}, sort_keys=True, default=str))
    # `signatures` lists every signature of the pool, failed ones included; the archive stores the
    # transactions of the successful ones only (err is null).
    successful = {s['signature'] for s in archive['signatures'] if s.get('err') is None}
    summaries.append({'summary': True, 'pool': pool['pool'], 'signatures': len(archive['signatures']),
                      'manifest_signatures': pool['signatures'], 'successful_signatures': len(successful),
                      'stored_transactions': len(archive['transactions']), 'trades': trades,
                      'manifest_trades': pool['trades'], 'exact_curve_checks': exact, 'fee_rate_matches': fee_match,
                      'pass': (trades == pool['trades'] == exact == fee_match
                               and len(archive['signatures']) == pool['signatures']
                               and set(archive['transactions']) == successful)})
for summary in summaries:
    print(json.dumps(summary, sort_keys=True))
sys.exit(0 if all(s['pass'] for s in summaries) else 1)
