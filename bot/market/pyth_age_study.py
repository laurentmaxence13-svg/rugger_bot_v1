"""Pre-registered SOL/USD age study for option B' (W1 protocol v2.5). Offline, no network.

Input: effective points of ``bot.market.pyth_push.decode_entries`` from the transactions of the
study windows (P0-era slots, disjoint from W1). At every whole second t of each window, the
replay's rule is applied (last point whose block_time second has ended, i.e.
block_time * 1000 + 999 < t * 1000; age = t - publish_time); a second without any point yet is
missing and counts as refused.

Rules FIXED BEFORE the measurement, made coherent with the W1 WAIT rule (R02 D-1): W1 waits
when more than 1 % of M1 decision seconds have no accepted point, so the acceptance may refuse
at most a third of that.
* max_age_ms = smallest multiple of 5 s with at least 99.8 % of the measured seconds at or below
  it (expected age refusals <= 0.2 %); above 120 s: REJECTED.
* max_confidence_ppm = 99.9th percentile of confidence / price over the points, rounded up to a
  multiple of 50 ppm (expected confidence refusals <= 0.1 %); above 5 000 ppm: REJECTED.
* Measured coherence: with both thresholds, the share of refused seconds (missing, too old or
  too wide) must be <= 0.3 % (= 1 % / 3, the margin below the WAIT rule); above: REJECTED.
* Error (owner, R02 D-3): at every accepted second, |used price - next published price| /
  next published price; its 99th percentile must be <= 0.5 %; above: REJECTED. Seconds whose
  point has no later publication in the window are not counted (published).
* Published, never tuned: shares at 5, 10, 15, 30, 45, 60, 75, 90, 120 s; quantiles of the
  gaps between publications, of the publication-to-block delay and of the error; counts.
Density (R02): ``density_projection`` turns a probe's transaction count into credits; the study
STOPS before its windows when their projection exceeds STUDY_MAX_CREDITS.
"""
from fractions import Fraction

THRESHOLDS_S = (5, 10, 15, 30, 45, 60, 75, 90, 120)
AGE_COVERAGE = Fraction(998, 1000)
AGE_STEP_S = 5
AGE_LIMIT_S = 120
CONF_QUANTILE = Fraction(999, 1000)
CONF_STEP_PPM = 50
CONF_LIMIT_PPM = 5_000
WAIT_SHARE = Fraction(1, 100)                     # W1 rule: WAIT above 1 % of decision seconds
MAX_REFUSED_SHARE = WAIT_SHARE / 3                # 0.3 %
ERROR_QUANTILE = Fraction(99, 100)
ERROR_LIMIT = Fraction(5, 1000)                   # 0.5 %
STUDY_MAX_CREDITS = 2_000
GTFA_FULL_PAGE = 100
GTFA_CREDITS_PER_PAGE = 10


def _quantile(values, q):
    """Nearest-rank quantile (no interpolation): the smallest value with at least q of the sample at or below."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, -(-q.numerator * len(ordered) // q.denominator))
    return ordered[rank - 1]


def _price(point):
    return Fraction(point['price']) * Fraction(10) ** point['exponent']


def _ordered(points):
    return sorted(points, key=lambda p: (p['slot'], p['transaction_index']))


def chosen(points, start_s, end_s):
    """Index (in chain order) of the point the replay would use at each second, or None."""
    if type(start_s) is not int or type(end_s) is not int or not start_s < end_s:
        raise ValueError('invalid_window')
    usable = _ordered(points)
    out, index, current = [], 0, None
    for t in range(start_s, end_s):
        while index < len(usable) and usable[index]['block_time'] * 1000 + 999 < t * 1000:
            current = index
            index += 1
        out.append(current)
    return usable, out


def ages(points, start_s, end_s):
    """Age in whole seconds at each second of [start_s, end_s) (None: no available point yet)."""
    usable, picks = chosen(points, start_s, end_s)
    return [None if i is None else t - usable[i]['publish_time'] for t, i in zip(range(start_s, end_s), picks)]


def density_projection(transactions, slots, target_slots):
    """Credits of getTransactionsForAddress full pages for ``target_slots`` at the probe's density."""
    for value in (transactions, slots, target_slots):
        if type(value) is not int or value < 0:
            raise ValueError('invalid_density_inputs')
    if slots == 0:
        raise ValueError('probe_without_slots')
    expected = -(-transactions * target_slots // slots)
    return -(-expected // GTFA_FULL_PAGE) * GTFA_CREDITS_PER_PAGE


def study_go_no_go(probe_transactions, probe_slots, windows_slots):
    """'GO' or 'STOP' before the study windows are read, from the density probe (R02)."""
    projected = density_projection(probe_transactions, probe_slots, windows_slots)
    return ('GO' if projected <= STUDY_MAX_CREDITS else 'STOP'), projected


def study(points, windows):
    """Measured profile and the pre-registered thresholds over ``windows`` [(start_s, end_s)]."""
    ordered = _ordered(points)
    picks = []                                       # (t, index or None) over every window second
    for start, end in windows:
        usable, chosen_rows = chosen(ordered, start, end)
        picks += list(zip(range(start, end), chosen_rows))
    seconds = len(picks)
    known = [t - ordered[i]['publish_time'] for t, i in picks if i is not None]
    shares = {t: Fraction(sum(1 for a in known if a <= t), seconds) for t in THRESHOLDS_S}
    max_age_s = next((limit for limit in range(AGE_STEP_S, AGE_LIMIT_S + AGE_STEP_S, AGE_STEP_S)
                      if Fraction(sum(1 for a in known if a <= limit), seconds) >= AGE_COVERAGE), None)
    conf_ppm = [Fraction(p['confidence'] * 1_000_000, p['price']) for p in ordered]
    conf_q = _quantile(conf_ppm, CONF_QUANTILE)
    max_conf_ppm = None if conf_q is None else int(-(-conf_q // CONF_STEP_PPM) * CONF_STEP_PPM)
    refused = errors = None
    errors_list = []
    if max_age_s is not None and max_conf_ppm is not None:
        refused_count = 0
        for t, i in picks:
            if (i is None or t - ordered[i]['publish_time'] > max_age_s
                    or ordered[i]['confidence'] * 1_000_000 > max_conf_ppm * ordered[i]['price']):
                refused_count += 1
            elif i + 1 < len(ordered):
                nxt = _price(ordered[i + 1])
                errors_list.append(abs(_price(ordered[i]) - nxt) / nxt)
        refused = Fraction(refused_count, seconds)
        errors = _quantile(errors_list, ERROR_QUANTILE)
    gaps = [b['publish_time'] - a['publish_time'] for a, b in zip(ordered, ordered[1:])]
    delays = [p['block_time'] - p['publish_time'] for p in ordered]
    reasons = []
    if max_age_s is None:
        reasons.append('age_coverage_above_120_s')
    if max_conf_ppm is None or max_conf_ppm > CONF_LIMIT_PPM:
        reasons.append('confidence_above_5000_ppm')
    if refused is not None and refused > MAX_REFUSED_SHARE:
        reasons.append('refused_seconds_above_0_3_percent')
    if refused is not None and (errors is None or errors > ERROR_LIMIT):
        reasons.append('error_p99_above_0_5_percent')
    return dict(seconds=seconds, missing_seconds=seconds - len(known), points=len(ordered),
                shares={str(t): float(v) for t, v in shares.items()},
                gap_s=dict(p50=_quantile(gaps, Fraction(1, 2)), p99=_quantile(gaps, Fraction(99, 100)),
                           max=max(gaps, default=None)),
                delay_s=dict(p50=_quantile(delays, Fraction(1, 2)), p99=_quantile(delays, Fraction(99, 100)),
                             max=max(delays, default=None)),
                confidence_ppm_q999=None if conf_q is None else float(conf_q),
                refused_share=None if refused is None else float(refused),
                error=dict(seconds=len(errors_list), p50=None if not errors_list else float(_quantile(errors_list, Fraction(1, 2))),
                           p99=None if errors is None else float(errors),
                           max=None if not errors_list else float(max(errors_list))),
                acceptance=None if reasons else dict(max_age_ms=max_age_s * 1000, max_confidence_ppm=max_conf_ppm),
                verdict='REJECTED' if reasons else 'ACCEPTED', reasons=reasons,
                rules=dict(age_coverage=str(AGE_COVERAGE), age_step_s=AGE_STEP_S, age_limit_s=AGE_LIMIT_S,
                           confidence_quantile=str(CONF_QUANTILE), confidence_step_ppm=CONF_STEP_PPM,
                           confidence_limit_ppm=CONF_LIMIT_PPM, max_refused_share=str(MAX_REFUSED_SHARE),
                           error_quantile=str(ERROR_QUANTILE), error_limit=str(ERROR_LIMIT),
                           study_max_credits=STUDY_MAX_CREDITS))
