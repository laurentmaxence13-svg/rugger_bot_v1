"""Causal decision points of one pool: a fixed grid written here BEFORE any data is read.

A decision exists only at a real event and only once its transaction is seen whole (the frozen
``PolicyArm.entry`` rule). Two families, both read from the history up to that event only:
* ``age``       for each A of ``AGE_GRID_S``: the first whole event whose age is >= A, kept only if
                its age is <= A + ``MAX_LATENESS_S`` (a pool silent at that age gives no point);
* ``progress``  for each level L of ``PROGRESS_GRID_PPM``: the first whole event at which the curve
                progress is >= L while it was < L at the previous whole event (first upward crossing).
One event can carry several labels; it is probed once.
"""
AGE_GRID_S = (0, 5, 15, 30, 60, 120, 300, 600, 1200, 2400, 3600)
MAX_LATENESS_S = 30
PROGRESS_GRID_PPM = (50_000, 100_000, 200_000, 350_000, 500_000, 650_000, 800_000)


def whole(events, k):
    """True when event ``k`` is the last event of its transaction."""
    return k + 1 == len(events) or events[k + 1].signature != events[k].signature


def decision_points(events, created_block_time):
    """Ordered ``[(k, [[kind, level], ...])]``; reads ``events[:k + 1]`` only to label event ``k``."""
    if type(created_block_time) is not int:
        raise ValueError('creation_block_time_required')
    labels = {}
    ages = list(AGE_GRID_S)
    levels = list(PROGRESS_GRID_PPM)
    previous = events[0].state_before().progress_ppm if events else 0
    for k, event in enumerate(events):
        if not whole(events, k):
            continue
        age = event.block_time - created_block_time
        while ages and age >= ages[0]:
            target = ages.pop(0)
            if age <= target + MAX_LATENESS_S:
                labels.setdefault(k, []).append(['age', target])
        progress = event.state_after().progress_ppm
        for level in [level for level in levels if previous < level <= progress]:
            levels.remove(level)
            labels.setdefault(k, []).append(['progress', level])
        previous = progress
    return sorted(labels.items())
