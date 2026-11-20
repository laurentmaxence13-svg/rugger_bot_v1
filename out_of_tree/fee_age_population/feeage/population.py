"""feeage 0.2 — POPULATION facts on the LaunchLab fee rate versus pool age (prerequisite of candidate C-D, R02
3cd2ffa2, points 3 and 4). No value: no P&L, no return, no reserve, no progress, no signer is read (tested).

Q3 (R02): does the LaunchLab fee rate DECREASE with pool age? If so, « late » and « 2 500 ppm » are confounded and C-D
must be written as ONE causal condition.
Q4 (R02): entry rate of C-D established by a population count: pools that reach age >= 450 slots while trading at a
tier <= 2 500 ppm (R02 bbac1ffb: ``<=``, not ``==``).

INPUT: an exported pools directory (MANIFEST.json + archives), read through ``w1aux.lazy.load_fixtures_lazy`` (the
same checks as the frozen ``load_fixtures`` on the same bytes, but ONE archive in memory at a time; R02 bbac1ffb). Only
these fields of each decoded trade event are used: ``slot``, ``side``, ``amount_in``, ``amount_out`` and the four fee
fields (``FEE_FIELDS``); the pool age is ``event.slot - creation_slot`` (frozen ``creation_facts``).

FEE RATE OF AN EVENT: the frozen ``implied_fee_rate_ppm`` (smallest rate compatible with the rounded fee), kept only
when the event fee is at least ``MIN_FEE_LAMPORTS`` (rounding error under 0.1 %), then rounded to the nearest
``TIER_STEP_PPM`` (the tier). Events with a smaller fee are counted, not used.

OUTPUT (``FEE_AGE_POPULATION.json``; nothing printed): counts only.
* constancy: pools with >= 2 usable events; pools whose tier never changes; pools whose tier changes, and among them
  those whose tier never increases with age (non-increasing), with the count of (first tier -> last tier) pairs;
* tiers by age class (slots) [0,5) [5,25) [25,50) [50,150) [150,450) >=450: number of usable events per tier;
* C-D population: pools with at least one usable event at age >= 450 slots; those whose tier at their FIRST usable
  event at age >= 450 is <= 2 500 ppm; creation-slot span of the population, and the counts per day at the declared
  clock of 215 ms per slot (measured, R02/R03).
Everything is given for ALL the pools and, when an evaluation range is given, for the pools CREATED in
[evaluation_min, evaluation_max) (per day over the width of the range), comparable with the preliminary reading.
"""
import argparse
import hashlib
import json
from pathlib import Path

from bot.market.collector import summarize
from bot.market.launchlab_events import implied_fee_rate_ppm
from bot.p4.historical_research_replay import creation_facts
from w1aux.lazy import clear_cache, load_fixtures_lazy

SCHEMA = 'rugger-fee-age-population-v0.2'
FEE_FIELDS = ('protocol_fee', 'platform_fee', 'creator_fee', 'share_fee')
MIN_FEE_LAMPORTS = 1_000
TIER_STEP_PPM = 500
AGE_EDGES = (0, 5, 25, 50, 150, 450)
LATE_SLOTS, LOW_TIER_PPM = 450, 2_500
SLOT_MS = 215


class FeeAgeError(RuntimeError):
    pass


def tier_of(event):
    """(tier ppm, usable) of one decoded trade event."""
    values = {name: getattr(event, name) for name in FEE_FIELDS + ('side', 'amount_in', 'amount_out')}
    fees = sum(values[name] for name in FEE_FIELDS)
    if fees < MIN_FEE_LAMPORTS:
        return None, False
    rate = implied_fee_rate_ppm(values)
    return int(round(rate / TIER_STEP_PPM)) * TIER_STEP_PPM, True


def age_class(age):
    for low, high in zip(AGE_EDGES, AGE_EDGES[1:]):
        if low <= age < high:
            return f'[{low},{high})'
    return f'>={AGE_EDGES[-1]}' if age >= AGE_EDGES[-1] else 'negative'


def pool_facts(archive):
    """[(age, tier)] of the usable events of one pool, in timeline order, and the count of unusable ones."""
    _summary, timeline = summarize(archive)
    creation_slot = creation_facts(archive)['creation_slot']
    usable, small = [], 0
    for event in timeline.events:
        tier, ok = tier_of(event)
        if ok:
            usable.append((event.slot - creation_slot, tier))
        else:
            small += 1
    return creation_slot, usable, small


def population(pools, *, span_slots=None):
    """``pools``: iterable of (creation_slot, [(age, tier)], small). ``span_slots``: the width used for the counts per
    day (default: the creation-slot span of the pools)."""
    constancy = dict(pools_with_two_usable_events=0, constant=0, changing=0, changing_non_increasing=0,
                     first_to_last={})
    by_age = {}
    late, late_low, slots, small_total, usable_total = 0, 0, [], 0, 0
    for creation_slot, usable, small in pools:
        slots.append(creation_slot)
        small_total += small
        usable_total += len(usable)
        for age, tier in usable:
            cls = by_age.setdefault(age_class(age), {})
            cls[str(tier)] = cls.get(str(tier), 0) + 1
        tiers = [tier for _age, tier in usable]
        if len(tiers) >= 2:
            constancy['pools_with_two_usable_events'] += 1
            if len(set(tiers)) == 1:
                constancy['constant'] += 1
            else:
                constancy['changing'] += 1
                if all(b <= a for a, b in zip(tiers, tiers[1:])):
                    constancy['changing_non_increasing'] += 1
                key = f'{tiers[0]}->{tiers[-1]}'
                constancy['first_to_last'][key] = constancy['first_to_last'].get(key, 0) + 1
        first_late = next((tier for age, tier in usable if age >= LATE_SLOTS), None)
        if first_late is not None:
            late += 1
            late_low += first_late <= LOW_TIER_PPM
    span = span_slots if span_slots is not None else ((max(slots) - min(slots)) if slots else 0)
    days = span * SLOT_MS / 1000 / 86_400
    order = [age_class(edge) for edge in AGE_EDGES] + ['negative']
    return dict(schema=SCHEMA, category='POPULATION_FACT', pools=len(slots), usable_events=usable_total,
                events_fee_below_min=small_total, constancy=constancy,
                tiers_by_age_class={k: dict(sorted(by_age[k].items(), key=lambda kv: int(kv[0])))
                                    for k in order if k in by_age},
                c_d_population=dict(rule=f'pool with a usable event at age >= {LATE_SLOTS} slots; low = tier at that '
                                         f'first late event <= {LOW_TIER_PPM} ppm',
                                    late_pools=late, late_pools_at_low_tier=late_low,
                                    creation_slot_span=span, days_at_declared_clock=round(days, 3),
                                    late_low_per_day=round(late_low / days, 2) if days else None),
                parameters=dict(min_fee_lamports=MIN_FEE_LAMPORTS, tier_step_ppm=TIER_STEP_PPM, slot_ms=SLOT_MS,
                                age_edges=list(AGE_EDGES)),
                flags=dict(values_read=False, curve_state_read=False, counted_in_n=False))


def run(pools_dir, manifest_sha256, out_dir, label, evaluation_min=None, evaluation_max=None):
    if (evaluation_min is None) != (evaluation_max is None) or (
            evaluation_min is not None and not evaluation_min < evaluation_max):
        raise FeeAgeError('invalid_evaluation_range')
    manifest_sha, _digests, entries, _manifest = load_fixtures_lazy(pools_dir)
    if manifest_sha != manifest_sha256:
        raise FeeAgeError('manifest_is_not_the_anchored_one')
    out = Path(out_dir)
    if out.exists():
        raise FeeAgeError('output_exists')
    facts = []
    try:
        for _entry, archive in entries:                       # one archive parsed and held at a time
            facts.append(pool_facts(archive))
    finally:
        clear_cache()
    doc = dict(schema=SCHEMA, all=population(facts))
    if evaluation_min is not None:
        inside = [f for f in facts if evaluation_min <= f[0] < evaluation_max]
        doc['evaluation_range'] = dict(population(inside, span_slots=evaluation_max - evaluation_min),
                                       evaluation_min=evaluation_min, evaluation_max=evaluation_max,
                                       rule='pools CREATED in [evaluation_min, evaluation_max)')
    doc['input'] = dict(label=label, manifest_sha256=manifest_sha)
    out.mkdir(parents=True)
    path = out / 'FEE_AGE_POPULATION.json'
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + '\n', encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--pools', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--label', required=True, help='P0 or W1, as admitted by RUGGER 02')
    parser.add_argument('--evaluation-min', type=int, default=None)
    parser.add_argument('--evaluation-max', type=int, default=None)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    run(a.pools, a.manifest_sha256, a.out, a.label, a.evaluation_min, a.evaluation_max)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
