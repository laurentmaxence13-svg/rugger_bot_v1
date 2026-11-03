"""T-REG S-002 / T-0005: decode LaunchLab TradeEvents of the 7 fixtures certified by T-0004.

Offline: reads committed getTransaction results, no network, no keys.

  python -B validation/treg_s002/decode_trade_events.py > validation/treg_s002/trade_events.jsonl
"""
import dataclasses
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bot.market.launchlab_events import check_trade, extract_trade_events, implied_fee_rate_ppm  # noqa: E402
for path in sorted((ROOT / 'tests' / 'fixtures' / 'launchlab_trades').glob('*.json')):
    result = json.loads(path.read_text(encoding='utf-8'))['result']
    for index, event in enumerate(extract_trade_events(result)):
        values = dataclasses.asdict(event)
        try:
            check_trade(values)
            exact = True
        except ValueError:
            exact = False
        print(json.dumps({'file': path.name, 'index': index, 'event': values,
                          'implied_fee_rate_ppm': implied_fee_rate_ppm(values), 'exact_curve_check': exact},
                         sort_keys=True, default=str))
