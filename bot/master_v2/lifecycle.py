"""Policy-free lifecycle of each pool from its real events (descriptive diagnostics).

For every pool: activity, peak, timing and creator behaviour measured on the observed
curve (no own trade, no execution model). It answers questions such as "how fast do
launches peak and dump?" before any policy is designed; it is exploration data, not
evidence of a profitable rule.
"""
from fractions import Fraction

from bot.market.collector import summarize
from bot.p4 import historical_research_replay as hrr

HORIZONS_S = (5, 15, 30, 60, 120, 300, 900)


def _spot(state):
    return Fraction(state.quote_reserve, state.base_reserve)


def pool_lifecycle(archive):
    summary, timeline = summarize(archive)
    timeline, migration = hrr.usable_timeline(archive, summary, timeline)
    facts = hrr.creation_facts(archive)
    events = timeline.events
    row = dict(pool=archive.pool, creator=facts['creator'], created_slot=facts['creation_slot'],
               signed_creator_verified=facts['signed_creator_verified'], trades=len(events),
               migrated=migration is not None)
    if not events:
        return row
    created = facts['creation_block_time']
    launch = _spot(events[0].state_before())
    prices = [(e.block_time - created, _spot(e.state_after())) for e in events]
    peak_age, peak = max(prices, key=lambda item: (item[1], -item[0]))
    row.update(
        last_trade_age_s=prices[-1][0], max_progress_ppm=max(e.state_after().progress_ppm for e in events),
        peak_multiple=float(peak / launch), peak_age_s=peak_age, final_multiple=float(prices[-1][1] / launch),
        unique_payers=len({e.fee_payer for e in events}),
        creator_first_sell_age_s=next((e.block_time - created for e in events
                                       if e.side == 'sell' and e.fee_payer == facts['creator']), None))
    for horizon in HORIZONS_S:
        seen = [price for age, price in prices if age <= horizon]
        row[f'multiple_at_{horizon}s'] = float(seen[-1] / launch) if seen else 1.0
    return row


def lifecycle_table(fixtures_dir):
    """(rows, excluded) for every MANIFEST pool."""
    rows, excluded = [], []
    for entry, archive in hrr.load_fixtures(fixtures_dir)[2]:
        try:
            rows.append(pool_lifecycle(archive))
        except hrr.PoolExcluded as exc:
            excluded.append(dict(pool=archive.pool, file=entry['file'], reasons=exc.reasons))
    return rows, excluded
