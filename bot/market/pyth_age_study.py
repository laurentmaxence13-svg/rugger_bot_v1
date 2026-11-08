"""Pre-registered SOL/USD age study for option B' (W1 protocol v2.4). Offline, no network.

Input: points of ``bot.market.pyth_push.sol_usd_points`` decoded from the transactions of the
pilot windows (P0 slots, disjoint from W1). At every whole second t of each window, the
decision rule of the replay is applied (last point whose block_time second has ended, i.e.
block_time * 1000 + 999 < t * 1000, age = t - publish_time) and the age is recorded; a second
before the first point of its window has no point (counted as missing).

Rules FIXED BEFORE the measurement (the owner asked for a measured threshold, not a chosen one):
* max_age_ms = the smallest multiple of 5 s such that at least 99 % of the measured seconds
  have an age at or below it; if it exceeds 120 s, option B' is REJECTED.
* max_confidence_ppm = the 99.5th percentile of confidence / price over the decoded points,
  rounded up to a multiple of 50 ppm; if it exceeds 5 000 ppm (0.5 %), option B' is REJECTED.
* Published, never tuned: shares at 5, 10, 15, 30, 45, 60, 75, 90, 120 s, quantiles of the
  gaps between publications and of the publication-to-block delay, the longest gap.
"""
from fractions import Fraction

THRESHOLDS_S = (5, 10, 15, 30, 45, 60, 75, 90, 120)
COVERAGE = Fraction(99, 100)
AGE_STEP_S = 5
AGE_LIMIT_S = 120
CONF_QUANTILE = Fraction(995, 1000)
CONF_STEP_PPM = 50
CONF_LIMIT_PPM = 5_000


def _quantile(values, q):
    """Nearest-rank quantile (no interpolation): the smallest value with at least q of the sample at or below."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, -(-q.numerator * len(ordered) // q.denominator))
    return ordered[rank - 1]


def ages(points, start_s, end_s):
    """Age in whole seconds at each second of [start_s, end_s) (None: no available point yet)."""
    if type(start_s) is not int or type(end_s) is not int or not start_s < end_s:
        raise ValueError('invalid_window')
    usable = sorted(points, key=lambda p: (p['slot'], p['transaction_index']))
    out, index, current = [], 0, None
    for t in range(start_s, end_s):
        while index < len(usable) and usable[index]['block_time'] * 1000 + 999 < t * 1000:
            current = usable[index]
            index += 1
        out.append(None if current is None else t - current['publish_time'])
    return out


def study(points, windows):
    """Measured profile and the two pre-registered thresholds over ``windows`` [(start_s, end_s)]."""
    measured = [age for start, end in windows for age in ages(points, start, end)]
    known = [age for age in measured if age is not None]
    seconds = len(measured)
    shares = {t: Fraction(sum(1 for a in known if a <= t), seconds) for t in THRESHOLDS_S}
    ordered = sorted(points, key=lambda p: (p['slot'], p['transaction_index']))
    gaps = [b['publish_time'] - a['publish_time'] for a, b in zip(ordered, ordered[1:])]
    delays = [p['block_time'] - p['publish_time'] for p in ordered]
    conf_ppm = [Fraction(p['confidence'] * 1_000_000, p['price']) for p in ordered]
    max_age_s = None
    for limit in range(AGE_STEP_S, AGE_LIMIT_S + AGE_STEP_S, AGE_STEP_S):
        if Fraction(sum(1 for a in known if a <= limit), seconds) >= COVERAGE:
            max_age_s = limit
            break
    conf_q = _quantile(conf_ppm, CONF_QUANTILE)
    max_conf_ppm = None if conf_q is None else -(-conf_q // CONF_STEP_PPM) * CONF_STEP_PPM
    rejected = []
    if max_age_s is None:
        rejected.append('age_coverage_above_120_s')
    if max_conf_ppm is None or max_conf_ppm > CONF_LIMIT_PPM:
        rejected.append('confidence_above_5000_ppm')
    return dict(seconds=seconds, missing_seconds=seconds - len(known), points=len(ordered),
                shares={str(t): float(v) for t, v in shares.items()},
                gap_s=dict(p50=_quantile(gaps, Fraction(1, 2)), p99=_quantile(gaps, COVERAGE), max=max(gaps, default=None)),
                delay_s=dict(p50=_quantile(delays, Fraction(1, 2)), p99=_quantile(delays, COVERAGE),
                             max=max(delays, default=None)),
                confidence_ppm_q995=None if conf_q is None else float(conf_q),
                acceptance=None if rejected else dict(max_age_ms=max_age_s * 1000, max_confidence_ppm=int(max_conf_ppm)),
                verdict='REJECTED' if rejected else 'ACCEPTED', reasons=rejected,
                rules=dict(coverage=str(COVERAGE), age_step_s=AGE_STEP_S, age_limit_s=AGE_LIMIT_S,
                           confidence_quantile=str(CONF_QUANTILE), confidence_step_ppm=CONF_STEP_PPM,
                           confidence_limit_ppm=CONF_LIMIT_PPM))
