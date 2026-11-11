"""Causal decision points of one pool: a fixed grid written here BEFORE any data is read.

A decision exists only at a real event and only once its transaction is seen whole (the frozen
``PolicyArm.entry`` rule). Three families, all read from the history up to that event only:
* ``age``       for each A of ``AGE_GRID_S``: the first whole event whose age is >= A, kept only if
                its age is <= A + ``MAX_LATENESS_S`` (a pool silent at that age gives no point);
* ``progress``  for each level L of ``PROGRESS_GRID_PPM``: the first whole event at which the curve
                progress is >= L while it was < L at the previous whole event (first upward crossing);
* ``placebo``   the timing placebo of the frozen ``RandomEntry`` policy (V3-02): a pseudo-random
                target age in 0..``PLACEBO_MAX_AGE_S`` drawn from the pool id with a fixed salt, the
                first whole event whose age is >= that target and <= ``PLACEBO_MAX_AGE_S``.
One event can carry several labels; it is probed once. A label occurs at most once per pool, so a
cell holds at most one probe per pool (R02 R-e).

Declared before any table (R02 C-S2): the grid cells are ``age`` and ``progress`` labels crossed
with ``HORIZONS_S`` (``K_GRID`` cells); ``REFERENCE_CELL`` is the entry of the reference V3-01;
the placebo is the main comparison of every cell, at the same horizon, paired by pool.
"""
import hashlib

AGE_GRID_S = (0, 5, 15, 30, 60, 120, 300, 600, 1200, 2400, 3600)
MAX_LATENESS_S = 30
PROGRESS_GRID_PPM = (50_000, 100_000, 200_000, 350_000, 500_000, 650_000, 800_000)
HORIZONS_S = (10, 25, 60, 120, 300)
PLACEBO_MAX_AGE_S = 120
PLACEBO_SALT = 'v1'
PLACEBO_CELL = 'placebo:0'
REFERENCE_CELL = 'age:5'
K_GRID = (len(AGE_GRID_S) + len(PROGRESS_GRID_PPM)) * len(HORIZONS_S)          # 90


def whole(events, k):
    """True when event ``k`` is the last event of its transaction."""
    return k + 1 == len(events) or events[k + 1].signature != events[k].signature


def placebo_target_age(pool):
    """The frozen ``bot.master_v2.policies.RandomEntry.target_age`` (salt and range fixed here)."""
    digest = hashlib.sha256(f'{PLACEBO_SALT}:{pool}'.encode()).digest()
    return int.from_bytes(digest[:4], 'big') % (PLACEBO_MAX_AGE_S + 1)


def decision_points(events, created_block_time, pool):
    """Ordered ``[(k, [[kind, level], ...])]``; reads ``events[:k + 1]`` only to label event ``k``."""
    if type(created_block_time) is not int:
        raise ValueError('creation_block_time_required')
    labels = {}
    ages = list(AGE_GRID_S)
    levels = list(PROGRESS_GRID_PPM)
    target, placebo_open = placebo_target_age(pool), True
    previous = events[0].state_before().progress_ppm if events else 0
    for k, event in enumerate(events):
        if not whole(events, k):
            continue
        age = event.block_time - created_block_time
        while ages and age >= ages[0]:
            wanted = ages.pop(0)
            if age <= wanted + MAX_LATENESS_S:
                labels.setdefault(k, []).append(['age', wanted])
        progress = event.state_after().progress_ppm
        for level in [level for level in levels if previous < level <= progress]:
            levels.remove(level)
            labels.setdefault(k, []).append(['progress', level])
        previous = progress
        if placebo_open and age >= target:
            placebo_open = False                            # one draw per pool, taken or lost
            if age <= PLACEBO_MAX_AGE_S:
                labels.setdefault(k, []).append(['placebo', 0])
    return sorted(labels.items())
