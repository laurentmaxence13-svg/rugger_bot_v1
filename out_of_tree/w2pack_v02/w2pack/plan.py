"""W2 collection plan (R03, phase W2), v0.2. Offline: nothing here sends a request.

Dossier B v1.6 section 7 (R02 7b867c0f): W2 = k FROZEN consecutive windows, each the W1 window shape of
``bot.market.w1_collection`` (warm-up 402 800, evaluation 1 612 800, gap 4 513 slots), dayj unchanged,
s0_(i+1) = s0_i + 1 612 800. The collection stays the FROZEN program-window backfill (tree aff97638), ONE RUN PER
FROZEN WINDOW with exactly that window's bounds: the frozen export (R10) checks the run's manifest window against
the planned bounds and reads ONE verified run directory, so a window is never assembled from several runs (shown
offline on the pilot, test_w2pack). Consecutive windows overlap by warm-up + gap (407 312 slots), which is collected
again in each run: the price of keeping the frozen export unchanged.

Observation after a cohort = the frozen gap (4 513 slots, R02: HW1-4 needs about 3 349, C-E <= 150 s).
Clock for durations only: 215 ms per slot (R02 b580a61e).
"""
from dataclasses import dataclass, asdict

from bot.market import w1_collection as w1

SLOT_MS = 215
WINDOW_EVALUATION_SLOTS = w1.EVALUATION_SLOTS        # 1 612 800, frozen
W1_CREDITS = 228_882 + 72_578                        # LaunchLab + SOL/USD, measured (W1 manifests)
W1_COLLECTED_SLOTS = 2_020_112
COSTS = w1.COSTS                                     # 'helius-documented-20261108'


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class W2Config:
    s0: int
    windows: int
    credit_cap: int = 10_000_000
    margin: float = 1.5

    def check(self):
        if type(self.s0) is not int or self.s0 <= 0:
            raise PlanError('invalid_s0')
        if type(self.windows) is not int or self.windows < 1:
            raise PlanError('windows_must_be_an_integer_k_at_least_1')
        if type(self.credit_cap) is not int or self.credit_cap <= 0:
            raise PlanError('invalid_credit_cap')
        if not 1.0 <= self.margin <= 3.0:
            raise PlanError('invalid_margin')
        return self

    @property
    def evaluation_slots(self):
        return self.windows * WINDOW_EVALUATION_SLOTS


def window_bounds(cfg, i):
    """Bounds of frozen window i: exactly ``w1_collection.bounds(s0_i)``, s0_i = s0 + i * 1 612 800."""
    cfg.check()
    if type(i) is not int or not 0 <= i < cfg.windows:
        raise PlanError('no_such_window')
    return w1.bounds(cfg.s0 + i * WINDOW_EVALUATION_SLOTS)


def windows(cfg):
    out = []
    for i in range(cfg.windows):
        b = window_bounds(cfg, i)
        out.append(dict(index=i, s0=b['slot_min'], slot_min=b['slot_min'], slot_max=b['slot_max'],
                        evaluation=list(b['evaluation']), slots=b['collected_slots']))
    return out


def union(cfg):
    """The k evaluation ranges tile [s0 + warm-up, s0 + warm-up + k * 1 612 800) without gap or overlap."""
    ws = windows(cfg)
    if any(a['evaluation'][1] != c['evaluation'][0] for a, c in zip(ws, ws[1:])):
        raise PlanError('evaluation_ranges_do_not_tile')
    return dict(slot_min=ws[0]['slot_min'], slot_max=ws[-1]['slot_max'],
                evaluation=[ws[0]['evaluation'][0], ws[-1]['evaluation'][1]],
                evaluation_slots=cfg.evaluation_slots, distinct_slots=ws[-1]['slot_max'] - ws[0]['slot_min'] + 1)


def projection(cfg):
    """Credits per window run and in total at the W1 measured rate; overlaps are counted (collected again)."""
    rate = W1_CREDITS / W1_COLLECTED_SLOTS
    per = [dict(index=w['index'], credits=round(w['slots'] * rate), with_margin=round(w['slots'] * rate * cfg.margin))
           for w in windows(cfg)]
    total_margin = sum(p['with_margin'] for p in per)
    return dict(rate_credits_per_slot=rate, windows=per, total=sum(p['credits'] for p in per),
                total_with_margin=total_margin, credit_cap=cfg.credit_cap, fits=total_margin <= cfg.credit_cap,
                overlap_slots_per_extra_window=w1.WARMUP_SLOTS + w1.GAP_SLOTS)


def plan(cfg):
    u = union(cfg)
    days = lambda slots: round(slots * SLOT_MS / 86_400_000, 3)
    return dict(schema='w2pack-plan-v0.2', config=asdict(cfg), union=u, days_evaluation=days(u['evaluation_slots']),
                days_distinct=days(u['distinct_slots']), days_per_window_run=days(W1_COLLECTED_SLOTS),
                windows=windows(cfg), projection=projection(cfg), costs=COSTS)
