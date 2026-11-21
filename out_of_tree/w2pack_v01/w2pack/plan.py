"""W2 collection plan, parameterized by the window (R03, phase W2). Offline: nothing here sends a request.

The collection itself stays the FROZEN program-window backfill (``bot.market.backfill`` and its CLI, tree aff97638):
getTransactionsForAddress full pages of the LaunchLab program, getSignaturesForAddress reconciliation, request and
credit caps charged on disk before every send, resumable by re-running the same command. This module only replaces
the W1 constants of ``bot.market.w1_collection`` by parameters, and cuts the window into contiguous collection
segments so that the chain can run by weekly cohorts (R02 0eb4fe3f, 7f7e49d6).

Rules kept from W1: window [S0, S0 + warmup + evaluation + gap); warm-up = creator history only; entry cutoff =
last evaluation slot; positions close in the gap. Clock for durations only: 215 ms per slot (R02 b580a61e).
"""
from dataclasses import dataclass, asdict

SLOT_MS = 215
W1_CREDITS = 228_882 + 72_578          # LaunchLab + SOL/USD, measured (W1 manifests)
W1_COLLECTED_SLOTS = 2_020_112
COSTS = 'helius-documented-20261108'


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class W2Config:
    s0: int
    warmup_slots: int = 402_800
    evaluation_slots: int = 1_612_800
    gap_slots: int = 4_513
    segment_slots: int = 2_812_000          # about 7 days at 215 ms per slot
    observation_slots: int = 4_513          # a cohort is processed only once this many slots after its end are collected
    credit_cap: int = 10_000_000
    margin: float = 1.5

    def check(self):
        for name in ('s0', 'warmup_slots', 'evaluation_slots', 'gap_slots', 'segment_slots', 'observation_slots',
                     'credit_cap'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise PlanError(f'invalid_{name}')
        if not 1.0 <= self.margin <= 3.0:
            raise PlanError('invalid_margin')
        if self.observation_slots < self.gap_slots:
            raise PlanError('observation_shorter_than_the_exit_gap')
        return self


def bounds(cfg):
    """Every slot bound of the window, with the keys and values of ``w1_collection.bounds``."""
    cfg.check()
    evaluation_start = cfg.s0 + cfg.warmup_slots
    evaluation_end = evaluation_start + cfg.evaluation_slots
    slot_max = evaluation_end + cfg.gap_slots - 1
    return dict(slot_min=cfg.s0, slot_max=slot_max, warmup=(cfg.s0, evaluation_start),
                evaluation=(evaluation_start, evaluation_end), entry_cutoff_slot=evaluation_end - 1,
                window_slot_max=slot_max, gap_slots=cfg.gap_slots, evaluation_slots=cfg.evaluation_slots,
                collected_slots=slot_max - cfg.s0 + 1)


def segments(cfg):
    """Contiguous, non-overlapping collection segments [slot_min, slot_max] covering the whole window."""
    b = bounds(cfg)
    out, lo = [], b['slot_min']
    while lo <= b['slot_max']:
        hi = min(lo + cfg.segment_slots - 1, b['slot_max'])
        out.append(dict(index=len(out), slot_min=lo, slot_max=hi, slots=hi - lo + 1))
        lo = hi + 1
    return out


def cohorts(cfg):
    """Creation cohorts of the evaluation range, one per segment length, each with the first segment after which
    its pools can be processed (cohort end + observation collected). No pool history is ever cut (R02 condition 1)."""
    b, segs = bounds(cfg), segments(cfg)
    start, end = b['evaluation']
    out, lo = [], start
    while lo < end:
        hi = min(lo + cfg.segment_slots, end)
        need = min(hi - 1 + cfg.observation_slots, b['slot_max'])
        ready = next(s['index'] for s in segs if s['slot_max'] >= need)
        out.append(dict(index=len(out), created_from=lo, created_before=hi, needs_collected_to=need,
                        ready_after_segment=ready))
        lo = hi
    return out


def projection(cfg):
    """Credits per segment and in total, at the W1 measured rate, with the margin; checked against the cap."""
    segs = segments(cfg)
    rate = W1_CREDITS / W1_COLLECTED_SLOTS
    per = [dict(index=s['index'], credits=round(s['slots'] * rate), with_margin=round(s['slots'] * rate * cfg.margin))
           for s in segs]
    total = sum(p['with_margin'] for p in per)
    return dict(rate_credits_per_slot=rate, segments=per, total=sum(p['credits'] for p in per),
                total_with_margin=total, credit_cap=cfg.credit_cap, fits=total <= cfg.credit_cap)


def plan(cfg):
    b = bounds(cfg)
    days = lambda slots: round(slots * SLOT_MS / 86_400_000, 3)
    return dict(schema='w2pack-plan-v0.1', config=asdict(cfg), bounds=b, days_collected=days(b['collected_slots']),
                days_evaluation=days(cfg.evaluation_slots), segments=segments(cfg), cohorts=cohorts(cfg),
                projection=projection(cfg), costs=COSTS)
