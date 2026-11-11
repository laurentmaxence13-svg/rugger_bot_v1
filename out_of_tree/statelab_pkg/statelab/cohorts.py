"""Who moves the price after a decision point: exact accounting of the curve's quote flow by cohort.

  python -B -m statelab.cohorts <visible_pack> --expect-manifest-sha <sha256> --out <cohorts.json> [--markdown <file>]

Descriptive, no strategy, no order, no P&L of a rule: for every decision point of ``statelab.points``
(same grid, same landing rule, same windows as ``statelab.study``) it splits the REAL trades that
follow the landing into cohorts fixed at the decision, from the history up to the decision only:

  creator   the creator of the pool;
  early     the other actors who bought in the creation slot or the next one (snipers, bundles);
  before    every other actor already seen at the decision;
  new       actors first seen after the decision.

An actor is the owner of the trader's token account (``v4sim.io.actors_from_archive``, the mapping
the simulator's ledgers use), else the fee payer.

EXACT IDENTITY, checked for every point and window: the sum over cohorts of the signed quote each
trade moved into the curve equals the change of the curve's real quote over the window; on this
constant-product curve that change alone fixes the price change. So the table says who pushed the
price down (or up) after the moment we would have bought, with no model.

Also recorded at the decision (causal): the share of the tokens in circulation held by each cohort
(positive net positions over the tokens the curve has sold): the inventory that can be sold to us.

Windows: ``latency`` = real trades between the decision and our landing; then one window per horizon
h of ``statelab.points.HORIZONS_S`` = trades after the landing up to the landing of a clock sale due at
h (the window that prices ``value`` in ``statelab.study``). Discovery segments only (exploration,
train); labels under the sample floors of ``statelab.study`` are not tabulated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from bot.market.collector import summarize
from bot.p4 import historical_research_replay as hrr

from v3lab import plan
from v3lab.pack import Pack

from v4sim.engine import landing_index
from v4sim.io import actors_from_archive

from statelab.points import HORIZONS_S, PLACEBO_CELL, decision_points
from statelab.study import (DEFAULT_POPULATION, DISCOVERY_SEGMENTS, MIN_CREATORS, MIN_PROBES, POPULATIONS, cluster_key,
                            window_cutoff)

SCHEMA = 'statelab-cohorts-v1'
COHORTS = ('creator', 'early', 'before', 'new')


def cohort_state(events, k, creator, creation_slot, actor_of):
    """Cohort of every actor seen up to event ``k`` and the tokens each cohort holds; reads ``events[:k + 1]`` only."""
    cohorts, positions = {}, {}
    for event in events[:k + 1]:
        actor = actor_of(event)
        if actor == creator:
            cohorts[actor] = 'creator'
        elif (event.side == 'buy' and creation_slot is not None and event.slot <= creation_slot + 1
              and cohorts.get(actor) != 'creator'):
            cohorts[actor] = 'early'
        else:
            cohorts.setdefault(actor, 'before')
        delta = event.amount_out if event.side == 'buy' else -event.amount_in
        positions[actor] = positions.get(actor, 0) + delta
    held = {name: 0 for name in COHORTS[:3]}
    for actor, tokens in positions.items():
        if tokens > 0:
            held[cohorts[actor]] += tokens
    return cohorts, held


def _window(events, start, stop, cohorts, actor_of):
    """Signed quote moved into the curve by each cohort over ``events[start:stop]``, with gross buys and sells."""
    flows = {name: dict(net=0, bought=0, sold=0, trades=0) for name in COHORTS}
    for event in events[start:stop]:
        name = cohorts.get(actor_of(event), 'new')
        delta = event.real_quote_after - event.real_quote_before
        if (delta > 0) != (event.side == 'buy') and delta != 0:
            raise ValueError('quote_flow_sign_disagrees_with_the_side')
        flow = flows[name]
        flow['net'] += delta
        flow['bought' if delta > 0 else 'sold'] += abs(delta)
        flow['trades'] += 1
    return flows


def point_flows(events, k, facts, actors, latency_slots):
    """Flows of one decision point; every window carries the exact identity with the curve's real quote."""
    actor_of = lambda event: actors.get(event.key, event.fee_payer)               # noqa: E731
    cohorts, held = cohort_state(events, k, facts['creator'], facts['creation_slot'], actor_of)
    land = landing_index(events, k, events[k].slot + latency_slots)
    entry_time = events[land].block_time
    latency_s = hrr.clock_exit_latency_s(latency_slots)
    circulating = events[k].state_after().real_base
    row = dict(decision_index=k, land_index=land, circulating_tokens=circulating,
               held_share={name: (held[name] / circulating if circulating else None) for name in held},
               real_quote_at_decision=events[k].state_after().real_quote, windows={})

    def add(name, start, stop):
        flows = _window(events, start, stop, cohorts, actor_of)
        before = events[start - 1].state_after().real_quote
        after = events[stop - 1].state_after().real_quote if stop > start else before
        if sum(flow['net'] for flow in flows.values()) != after - before:
            raise ValueError('cohort_flows_do_not_add_up_to_the_curve_change')
        row['windows'][name] = dict(curve_change=after - before, cohorts=flows)

    add('latency', k + 1, land + 1)
    for h in HORIZONS_S:
        stop = land + 1
        while stop < len(events) and events[stop].block_time <= entry_time + h + latency_s:
            stop += 1
        add(str(h), land + 1, stop)
    return row


def pool_rows(archive, entry, segment, params, cutoff_slot, population=DEFAULT_POPULATION):
    if population not in POPULATIONS:
        raise ValueError('unknown_population')
    summary, timeline = summarize(archive)
    try:
        timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
    except hrr.PoolExcluded as exc:
        return None, list(exc.reasons)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    if population == 'signed' and not facts['signed_creator_verified']:
        return None, ['creator_not_signed']
    events = timeline.events
    actors, _stats = actors_from_archive(archive, events)
    rows = []
    for k, labels in decision_points(events, facts['creation_block_time'], archive.pool):
        if cutoff_slot is not None and events[k].slot > cutoff_slot:
            continue
        rows.append(dict(point_flows(events, k, facts, actors, params.latency_slots), pool=archive.pool,
                         creator=cluster_key(archive, facts), segment=segment, labels=labels))
    return rows, None


def _mean(values):
    return statistics.fmean(values) if values else None


def table(rows):
    """Per label above the floors and per window: mean flows by cohort (SOL) and who does the selling."""
    by_label = {}
    for row in rows:
        for kind, level in row['labels']:
            by_label.setdefault(f'{kind}:{level}', []).append(row)
    out = {}
    for key in sorted(by_label, key=lambda key: (key.split(':')[0], int(key.split(':')[1]))):
        items = by_label[key]
        if key == PLACEBO_CELL or len(items) < MIN_PROBES or len({r['creator'] for r in items}) < MIN_CREATORS:
            continue
        block = dict(probes=len(items), creators=len({r['creator'] for r in items}),
                     mean_real_quote_at_decision_sol=_mean([r['real_quote_at_decision'] / 1e9 for r in items]),
                     mean_held_share={name: _mean([r['held_share'][name] for r in items if r['held_share'][name] is not None])
                                      for name in COHORTS[:3]}, windows={})
        for name in ('latency',) + tuple(str(h) for h in HORIZONS_S):
            windows = [r['windows'][name] for r in items]
            sold = {c: sum(w['cohorts'][c]['sold'] for w in windows) for c in COHORTS}
            bought = {c: sum(w['cohorts'][c]['bought'] for w in windows) for c in COHORTS}
            block['windows'][name] = dict(
                mean_curve_change_sol=_mean([w['curve_change'] / 1e9 for w in windows]),
                share_curve_down=sum(w['curve_change'] < 0 for w in windows) / len(windows),
                share_no_trade=sum(not any(w['cohorts'][c]['trades'] for c in COHORTS) for w in windows) / len(windows),
                mean_net_sol={c: _mean([w['cohorts'][c]['net'] / 1e9 for w in windows]) for c in COHORTS},
                share_of_gross_sales={c: (sold[c] / sum(sold.values()) if sum(sold.values()) else None) for c in COHORTS},
                share_of_gross_buys={c: (bought[c] / sum(bought.values()) if sum(bought.values()) else None) for c in COHORTS})
        out[key] = block
    return out


def study(pack_dir, expect_manifest_sha256, *, latency_slots=plan.REPLAY['latency_slots'], population=DEFAULT_POPULATION):
    params = hrr.ReplayParams(latency_slots=latency_slots)
    pack = Pack(pack_dir, expect_manifest_sha256)
    rows, excluded = [], 0
    for entry, archive, segment in pack.pools():
        if segment not in DISCOVERY_SEGMENTS:
            continue
        result, _reasons = pool_rows(archive, entry, segment, params, window_cutoff(entry, pack.manifest, params),
                                     population)
        if result is None:
            excluded += 1
            continue
        rows.extend(result)
    document = dict(schema=SCHEMA, status='EXPLORATORY', pack_manifest_sha256=pack.manifest_sha256,
                    segments=list(DISCOVERY_SEGMENTS), population=population, latency_slots=latency_slots,
                    horizons_s=list(HORIZONS_S),
                    rows=len(rows), excluded_pools=excluded, table=table(rows),
                    flags=dict(strategy_evaluated=False, rule_pnl_computed=False, trial_registered=False,
                               holdout_read=False, w1_data_read=False),
                    notes=['descriptive: REAL market trades after the decision points of the fixed grid, WITHOUT any buy of '
                           'ours, split by cohorts fixed at the decision; no order of ours, no rule, no P&L',
                           'identity checked for every point and window: cohort flows add up to the change of the '
                           'curve real quote',
                           'discovery segments only; labels under the sample floors are not tabulated'])
    document['rows_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return document


def _sol(value):
    return '—' if value is None else f'{value:+.3f}'


def _pct(value):
    return '—' if value is None else f'{100 * value:.1f} %'


def markdown(document):
    lines = ['> ' + note for note in document['notes']] + [
        '', '### Qui détient les tokens au moment de la décision (part moyenne des tokens en circulation)', '',
        '| État | Points | SOL dans la courbe | Créateur | Acheteurs des 2 premiers slots | Autres détenteurs |', '|---|---|---|---|---|---|']
    for key, block in document['table'].items():
        h = block['mean_held_share']
        lines.append(f"| {key} | {block['probes']} | {block['mean_real_quote_at_decision_sol']:.3f} | {_pct(h['creator'])} | "
                     f"{_pct(h['early'])} | {_pct(h['before'])} |")
    lines += ['', '### Qui fait bouger la courbe après l’instant où nous aurions atterri — marché réel, SANS notre achat (flux net moyen en SOL ; part des ventes brutes)', '',
              '| État | Fenêtre (s) | Variation moyenne de la courbe (SOL) | Courbe en baisse | Aucun trade | Net créateur | Net premiers slots '
              '| Net autres antérieurs | Net nouveaux | Ventes : créateur | premiers slots | autres antérieurs | nouveaux |',
              '|' + '---|' * 13]
    for key, block in document['table'].items():
        for name, w in block['windows'].items():
            n, s = w['mean_net_sol'], w['share_of_gross_sales']
            lines.append(
                f"| {key} | {name} | {_sol(w['mean_curve_change_sol'])} | {_pct(w['share_curve_down'])} | {_pct(w['share_no_trade'])} | "
                f"{_sol(n['creator'])} | {_sol(n['early'])} | {_sol(n['before'])} | {_sol(n['new'])} | {_pct(s['creator'])} | "
                f"{_pct(s['early'])} | {_pct(s['before'])} | {_pct(s['new'])} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='who moves the curve after the decision points (descriptive)')
    parser.add_argument('pack', type=Path)
    parser.add_argument('--expect-manifest-sha', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--markdown', type=Path)
    parser.add_argument('--population', choices=POPULATIONS, default=DEFAULT_POPULATION)
    a = parser.parse_args(argv)
    if a.out.exists():
        raise SystemExit('output_exists')
    document = study(a.pack, a.expect_manifest_sha, population=a.population)
    a.out.write_text(json.dumps(document, sort_keys=True, indent=1, allow_nan=False) + '\n', encoding='utf-8')
    if a.markdown:
        a.markdown.write_text(markdown(document), encoding='utf-8')
    print(json.dumps(dict(rows=document['rows'], excluded_pools=document['excluded_pools'],
                          labels=list(document['table']), rows_sha256=document['rows_sha256'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
