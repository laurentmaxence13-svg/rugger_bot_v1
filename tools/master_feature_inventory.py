"""Offline inventory: which genuine Master inputs exist point-in-time in LaunchLab TradeEvents?

Read-only audit helper. It scores nothing, changes no strategy parameter and
never runs a Master. Reviewed references (read-only, not imported):
  * decision engine: ``SignalFeatures`` in bot/analyser/final_decision_engine.py,
    as on branch feat/prepurchase-bitquery-official-sample-proof-20261102 @ ce0f76d2353c93fe7c5b73a3e6576b483c09d6d2
  * frame contract: bot/p4_experiment.py ``_features`` and bot/master_decision.py, same SHA.
"""
import gzip
import json
import sys
from pathlib import Path

REFERENCE_SHA = 'ce0f76d2353c93fe7c5b73a3e6576b483c09d6d2'
COORDINATION_SHA = '4f2875d943f970983ee6198cc35931c3f31d380d'

# Classes
EVENTS = 'DERIVABLE_FROM_TRADE_EVENTS'        # needs only decoded TradeEvents
TX = 'DERIVABLE_WITH_TRANSACTION_DATA'        # needs full transactions (accounts, transfers)
EXTRA = 'NEEDS_EXTRA_READS'                   # token accounts, other pools, creator history, FX
UNKNOWN = 'UNKNOWN'                           # source or definition not established

# name: (class, unit_or_note, lookahead_or_zero_risk)
INVENTORY = {
    'mint': (TX, 'pool creation transaction account keys', ''),
    'creator': (TX, 'pool creation transaction; not a TradeEvent field', ''),
    'signal_time': (EVENTS, 'first event block_time (int s)', 'block_time may be None'),
    'observed_at': (EVENTS, 'block_time of last event used', 'must be <= decision time'),
    'price_usd': (EXTRA, 'events give SOL per base token; USD needs a SOL/USD price absent from events', 'any USD rate sampled later leaks the future'),
    'liquidity_usd': (EXTRA, 'real_quote_after is SOL; USD needs a rate', 'same as price_usd'),
    'quote_count': (UNKNOWN, 'meaning in the DEX-market source is not defined by TradeEvents', 'do not substitute event count silently'),
    'momentum_60s': (EVENTS, 'price ratio over a 60 s window of events', 'None, not 0, when pool younger than window'),
    'momentum_300s': (EVENTS, 'price ratio over a 300 s window of events', 'None, not 0, when pool younger than window'),
    'volume_5m_usd': (EXTRA, 'SOL volume derivable; USD needs a rate', 'partial 5 min window is not a 5 min value'),
    'volume_24h_usd': (EXTRA, 'window longer than any observed pool life', 'unavailable, not equal to 5 min volume'),
    'price_change_5m_pct': (EVENTS, 'event prices; USD rate cancels in a ratio', 'None when pool younger than 5 min'),
    'price_change_1h_pct': (EVENTS, 'event prices', 'None when pool younger than 1 h'),
    'tx_buys_5m': (EVENTS, 'count of BUY events in window', 'events are not transactions; zero is a real count only if history is complete'),
    'tx_sells_5m': (EVENTS, 'count of SELL events in window', 'same as tx_buys_5m'),
    'market_cap_usd': (EXTRA, 'needs total supply and USD rate', ''),
    'fdv_usd': (EXTRA, 'needs total supply and USD rate', ''),
    'fee_bps': (EVENTS, 'implied_fee_rate_ppm / 100', ''),
    'depth_usd': (EVENTS, 'exact curve capacity in SOL from reserves; USD needs a rate', ''),
    'slippage_bps_est': (EVENTS, 'exact curve math at a chosen size', 'size must be fixed before the decision'),
    'market_data_quality': (UNKNOWN, 'label of the external source, not a market fact', ''),
    'quote_source': (UNKNOWN, 'label of the external source', ''),
    'prior_launches': (EXTRA, 'creator history from other pools', 'future launches of the creator leak'),
    'behavior_known': (EXTRA, 'flag of the creator-history scan', 'False must mean unknown, never clean'),
    'relevant_transactions': (TX, 'creator-related transactions of this pool', ''),
    'dev_sales': (TX, 'SELL events whose fee_payer is the creator', 'needs creator'),
    'relay_transfers': (TX, 'system/token transfers inside transactions', 'needs wallet-flow rules'),
    'bundle_transactions': (EVENTS, 'distinct signatures sharing a slot', 'same-slot rule is a definition, not a fact'),
    'bundle_wallets': (EVENTS, 'distinct fee_payer values sharing a slot', ''),
    'same_slot_wallets': (EVENTS, 'distinct fee_payer values per slot', ''),
    'holder_count': (EXTRA, 'token-account scan', 'default 0 is NOT an observation'),
    'top_holder_share': (EXTRA, 'token-account scan', 'None means unknown'),
    'holder_data_known': (EXTRA, 'depends on the scan having run', 'default False must stay UNKNOWN'),
    'linked_wallets': (EXTRA, 'cross-pool wallet graph', 'default 0 is NOT an observation'),
    'wallet_link_count': (EXTRA, 'cross-pool wallet graph', 'default 0 is NOT an observation'),
    'wallet_graph_transactions': (EXTRA, 'cross-pool wallet graph', 'default 0 is NOT an observation'),
    'funding_usd': (EXTRA, 'creator funding history and USD rate', 'None means unknown'),
}

# Non-feature frame inputs consumed by the Master (bot/master_decision.py)
FRAME_INPUTS = {
    'independent_buyers': (UNKNOWN, 'definition of independence not in TradeEvents; distinct fee_payer is only an upper bound'),
    'source_slot': (EVENTS, 'TradeEvent.slot'),
    'slot_available_at_ms': (UNKNOWN, 'local receipt time; cannot be reconstructed from chain data'),
    'available_at_ms': (UNKNOWN, 'local receipt time; replay must assume a latency, which is unverified'),
    'research_evidence': (EXTRA, 'qualified historical report with >=50 cycles and >=20 creator groups'),
    'inventory_context.fees': (UNKNOWN, 'observed fees need real transactions; PAPER fixtures are estimates'),
}

# Fields that default to a value that looks like an observation.
ZERO_DEFAULTS = ('holder_count', 'linked_wallets', 'wallet_link_count', 'wallet_graph_transactions',
                 'holder_data_known', 'market_data_quality', 'quote_source')


def classify_counts():
    counts = {}
    for cls, _, _ in INVENTORY.values():
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def fixture_measurements(events, windows=(60, 300)):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bot.market.launchlab_events import BUY, SELL
    """Facts measurable from one pool's events: span, windows covered, same-slot wallets."""
    times = [e.block_time for e in events if e.block_time is not None]
    span = (max(times) - min(times)) if times else None
    slots = {}
    for e in events:
        slots.setdefault(e.slot, set()).add(e.fee_payer)
    return {
        'events': len(events),
        'buys': sum(e.side == BUY for e in events),
        'sells': sum(e.side == SELL for e in events),
        'missing_block_time': sum(e.block_time is None for e in events),
        'span_seconds': span,
        'windows_computable': {str(w): span is not None and span >= w for w in windows},
        'max_wallets_in_one_slot': max((len(v) for v in slots.values()), default=0),
        'distinct_fee_payers': len({e.fee_payer for e in events}),
    }


def audit(pack_dir):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bot.market.launchlab_events import extract_trade_events
    out = {}
    for path in sorted(Path(pack_dir).glob('*.json.gz')):
        data = json.loads(gzip.decompress(path.read_bytes()))
        events = [e for tx in data['transactions'].values() for e in extract_trade_events(tx)]
        out[data['pool']] = fixture_measurements(events)
    return out


def main(argv=None):
    pack = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
    report = {'reference_sha': REFERENCE_SHA, 'coordination_sha': COORDINATION_SHA,
              'class_counts': classify_counts(), 'fixtures': audit(pack),
              'master_executed': False}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
