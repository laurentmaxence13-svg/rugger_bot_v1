"""Forward liquidation value of a fixed 0.1 SOL buy from every decision point of ``statelab.points``.

  python -B -m statelab.study <visible_pack> --expect-manifest-sha <sha256> --out <rows.json>
         [--segments exploration,train] [--latency-slots 4] [--confirm-validation <hypothesis id>]

One probe per decision point: ``v4sim.engine.replay`` (unchanged, mode M-P, actors from the archive)
buys ``STAKE_LAMPORTS`` decided at that event, lands with the order latency, then the other
holders' later trades are replayed on the counterfactual curve; the probe records the exact
liquidation value of the whole position after every later real event. Nothing is optimised and
nothing is chosen: the grid of points, the horizons and the stake are constants of this file.

Row conventions (all integers are lamports):
* ``cost`` = stake + two own transaction costs (the frozen model); rent is NOT in ``cost`` (it is
  added by the reader of the rows, lost or recovered, as ``v3lab.scenarios`` does);
* ``immediate`` = liquidation at once on the state our own buy left (the instant round trip);
* per horizon h (seconds after the entry block time): ``value`` = liquidation after the last real
  event of age <= h (``immediate`` when none); ``value_late`` = same with age <= h + 1 s (a sale
  decided at h lands about one second later: the gap is the sale-latency sensitivity);
  ``best`` / ``worst`` = HINDSIGHT extremes up to h; ``events`` = real events of age <= h;
  ``migrated`` = the counterfactual curve completed by then: ``value`` is None (not credited,
  R02 criteria v1) and ``last_curve_value`` of the row is descriptive only.
Segments: discovery reads exploration and train. Reading validation needs ``--confirm-validation``
with the identifier of ONE pre-registered hypothesis; the flag is written in the output.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bot.market.collector import summarize
from bot.market.launchlab_curve import CurveError, buy_exact_in
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import Strategy
from bot.master_v2.features import native_features
from bot.master_v2.harness import ExitRule, hold_gap_slots
from bot.p4 import historical_research_replay as hrr

from v3lab import plan
from v3lab.features import v3_extras
from v3lab.pack import Pack

from v4sim import PROTOCOL_SHA256, VERSION as V4SIM_VERSION
from v4sim import engine
from v4sim.io import actors_from_archive
from v4sim.valuation import liquidation

from statelab import SCHEMA, VERSION
from statelab.points import AGE_GRID_S, MAX_LATENESS_S, PROGRESS_GRID_PPM, decision_points

STAKE_LAMPORTS = 100_000_000
HORIZONS_S = (10, 25, 60, 120, 300)
SALE_LATENCY_ALLOWANCE_S = 1
DISCOVERY_SEGMENTS = ('exploration', 'train')
MODE = 'M-P'


class Probe(Strategy):
    """Buy the stake decided at ``decision_index``; record (age, mark, index) after every later real event."""

    def __init__(self, decision_index, amount, last_age_s):
        self.decision_index, self.amount, self.last_age_s = decision_index, amount, last_age_s
        self.path = []

    def entry(self, history):
        return self.amount if len(history) - 1 == self.decision_index else None

    def exit(self, history, position, mark):
        age = history[-1].block_time - position.entry_time
        self.path.append((age, mark, len(history) - 1))
        return age > self.last_age_s          # nothing later is read: the replay may stop


def probe(timeline, k, actors, model, *, stake=STAKE_LAMPORTS, horizons=HORIZONS_S):
    """Forward values of one probe decided at event ``k``; a dict, ``entered`` False when the buy is refused."""
    events = timeline.events
    strategy = Probe(k, stake, max(horizons) + SALE_LATENCY_ALLOWANCE_S)
    result = engine.replay(timeline, strategy, model, quote_mint=WSOL_MINT, mode=MODE, actors=actors)
    if result.decision_index != k:
        raise ValueError('probe_did_not_decide_at_the_requested_event')
    row = dict(decision_index=k, entered=result.entry_index is not None, fee_rate_ppm=result.fee_rate_ppm,
               notes=list(result.notes))
    if not row['entered']:
        return row
    land = result.entry_index
    fill = buy_exact_in(events[land].state_after(), stake, result.fee_rate_ppm)
    if fill.amount_out != result.tokens or result.spent != stake:
        raise ValueError('entry_fill_not_reproduced')
    cost = stake + 2 * model.tx_cost
    immediate = liquidation(fill.after, result.tokens, result.fee_rate_ppm)[0]
    migrated_age = None
    if result.outcome == 'migrated_unpriced':
        stop = (strategy.path[-1][2] if strategy.path else land) + 1
        migrated_age = events[min(stop, len(events) - 1)].block_time - events[land].block_time
    row.update(land_index=land, events_before_landing=land - k, entry_slot=events[land].slot,
               entry_block_time=events[land].block_time, spent=stake, tokens=result.tokens, cost=cost,
               immediate=immediate, outcome=result.outcome, flags=list(result.v4['flags']),
               last_curve_value=result.v4['last_curve_value'], migrated_age_s=migrated_age, horizons={})
    for h in horizons:
        seen = [(age, mark) for age, mark, _index in strategy.path if age <= h]
        late = [(age, mark) for age, mark, _index in strategy.path if age <= h + SALE_LATENCY_ALLOWANCE_S]
        points = [(0, immediate)] + seen
        best = max(points, key=lambda p: (p[1], -p[0]))
        migrated = migrated_age is not None and migrated_age <= h
        row['horizons'][str(h)] = dict(
            value=None if migrated else points[-1][1],
            value_late=None if migrated or (migrated_age is not None and migrated_age <= h + SALE_LATENCY_ALLOWANCE_S)
            else ([(0, immediate)] + late)[-1][1],
            events=len(seen), best=best[1], best_age_s=best[0], worst=min(mark for _age, mark in points),
            migrated=migrated)
    return row


def window_cutoff(entry, manifest, params):
    """Last slot at which a probe may be decided so that its longest horizon is inside the collected window."""
    source = entry if ('entry_cutoff_slot' in entry or 'window_slot_max' in entry) else manifest
    cutoff, end = source.get('entry_cutoff_slot'), source.get('window_slot_max')
    if cutoff is None and end is None:
        return None
    if type(cutoff) is not int or type(end) is not int or not 0 < cutoff < end:
        raise ValueError('invalid_collection_window')
    rule = ExitRule(max_hold_s=max(HORIZONS_S) + SALE_LATENCY_ALLOWANCE_S, clock_exit=True)
    return min(cutoff, end - hold_gap_slots(rule, params))


def pool_rows(archive, entry, segment, params, cutoff_slot):
    """Rows of one pool, or ``(None, reasons)`` when the pool cannot be replayed or its creator is not signed."""
    summary, timeline = summarize(archive)
    try:
        timeline, migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded as exc:
        return None, list(exc.reasons)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    if not facts['signed_creator_verified']:
        return None, ['creator_not_signed']                      # same population as the reference policies
    events = timeline.events
    actors, _stats = actors_from_archive(archive, events)
    model = params.execution_model()
    rows, dropped = [], 0
    for k, labels in decision_points(events, facts['creation_block_time']):
        if cutoff_slot is not None and events[k].slot > cutoff_slot:
            dropped += 1
            continue
        history = events[:k + 1]
        features = dict(native_features(history, facts), **v3_extras(history, facts))
        row = dict(pool=archive.pool, creator=facts['creator'], segment=segment, labels=labels,
                   decision_slot=events[k].slot, decision_block_time=events[k].block_time,
                   pool_migrated_in_data=migration is not None, features=features)
        row.update(probe(timeline, k, actors, model))
        rows.append(row)
    return rows, dropped


def study(pack_dir, expect_manifest_sha256, *, segments=DISCOVERY_SEGMENTS, latency_slots=plan.REPLAY['latency_slots'],
          confirm_validation=None):
    segments = tuple(segments)
    if set(segments) - set(plan.SEGMENTS):
        raise ValueError('unknown_segment')
    if 'validation' in segments and not confirm_validation:
        raise ValueError('validation_is_read_once_per_pre_registered_hypothesis')
    if confirm_validation and segments != ('validation',):
        raise ValueError('a_confirmation_pass_reads_validation_only')
    params = hrr.ReplayParams(latency_slots=latency_slots)
    pack = Pack(pack_dir, expect_manifest_sha256)
    rows, excluded, after_cutoff, pools = [], [], 0, 0
    for entry, archive, segment in pack.pools():
        if segment not in segments:
            continue
        cutoff = window_cutoff(entry, pack.manifest, params)
        result, info = pool_rows(archive, entry, segment, params, cutoff)
        if result is None:
            excluded.append(dict(pool=archive.pool, segment=segment, reasons=info))
            continue
        pools += 1
        after_cutoff += info
        rows.extend(result)
    document = dict(
        schema=SCHEMA, status='EXPLORATORY', statelab_version=VERSION, statelab_sha256=fingerprint(),
        v4sim_version=V4SIM_VERSION, v4sim_protocol_sha256=PROTOCOL_SHA256, mode=MODE,
        pack_manifest_sha256=pack.manifest_sha256, segments=list(segments), confirm_validation=confirm_validation,
        constants=dict(stake_lamports=STAKE_LAMPORTS, horizons_s=list(HORIZONS_S), latency_slots=latency_slots,
                       sale_latency_allowance_s=SALE_LATENCY_ALLOWANCE_S, age_grid_s=list(AGE_GRID_S),
                       max_lateness_s=MAX_LATENESS_S, progress_grid_ppm=list(PROGRESS_GRID_PPM),
                       tx_cost_lamports=params.execution_model().tx_cost),
        pools_read=pools, excluded_pools=excluded, points_after_cutoff=after_cutoff, rows=rows,
        flags=dict(strategy_evaluated=False, trial_registered=False, holdout_read=False, w1_data_read=False,
                   promotion_allowed=False, financial_order_submitted=False),
        notes=['descriptive: forward values of a fixed probe from a fixed grid of causal points; no rule is chosen here',
               'best / worst are hindsight; value ignores the sale latency, value_late allows one second for it',
               'a point whose longest horizon would leave the collected window is dropped and counted'])
    document['rows_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return document


def fingerprint():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ('__init__.py', 'points.py', 'study.py'):
        digest.update(name.encode() + b'\0' + (root / name).read_bytes())
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description='forward liquidation values from a fixed grid of causal points')
    parser.add_argument('pack', type=Path)
    parser.add_argument('--expect-manifest-sha', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--segments', default=','.join(DISCOVERY_SEGMENTS))
    parser.add_argument('--latency-slots', type=int, default=plan.REPLAY['latency_slots'])
    parser.add_argument('--confirm-validation')
    a = parser.parse_args(argv)
    if a.out.exists():
        raise SystemExit('output_exists')
    document = study(a.pack, a.expect_manifest_sha, segments=tuple(s for s in a.segments.split(',') if s),
                     latency_slots=a.latency_slots, confirm_validation=a.confirm_validation)
    a.out.write_text(json.dumps(document, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    # Identifiers and counts only: no value is shown at run time.
    print(json.dumps(dict(rows=len(document['rows']), pools_read=document['pools_read'],
                          excluded=len(document['excluded_pools']), points_after_cutoff=document['points_after_cutoff'],
                          rows_sha256=document['rows_sha256'], statelab_sha256=document['statelab_sha256'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
