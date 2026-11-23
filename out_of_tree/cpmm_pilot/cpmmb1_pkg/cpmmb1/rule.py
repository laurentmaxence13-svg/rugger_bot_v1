"""cpmmb1 0.1 -- PRE-REGISTRATION of B1, the exact MOMENTUM MIRROR of R-CP1 (catalogue R-1 v0.2; R02 audit 1070aae6;
R04 decision of 23/11), frozen as code BEFORE any pilot datum, on its OWN sheet. R-CP1 (cpmmprereg 0.2, 059a3b5) is
imported and NEVER modified: same universe, same collection, same exits, same costs (cpmmcost 0.3, guard ON), same
placebo construction, same activity and cooldown conditions; the only difference is the sign of the move:

  B1 (i)  P_i / P_ref - 1 >= +3 %, P_ref = spot after the LAST swap j with block_time_j <= t_i - 600 s;
     (ii) at least 20 real swaps in ]t_i - 600 ; t_i];  (iii) no B1 position opened on this pool in the previous 3 600 s.

OWN alpha: 0.05 at the pilot (n = 155, word max GO_PILOTE), 0.05 / 3 at the confirmation (n_c with sigma_c). OWN
trigger count on [T0 - 7 d ; T0) and OWN power stop. OWN placebo seed = sha256(B1 freeze sheet sha + pool)[:8].
B1 is the 170th and LAST trial under the current cap (169 -> 170), consumed only when the pilot starts.
Synthetic pools only; nothing reads collected data.
"""
from fractions import Fraction

from cpmmprereg import rule as R

SCHEMA = 'cpmmb1-v0.1'
RISE = Fraction(3, 100)
TRIALS_BEFORE = 169                      # R-CP1 consumed the 169th
PreregError = R.PreregError


def decisions(line, config):
    """Indices of the swaps where B1 decides (causal: only swaps up to i are read). Mirror of R.decisions."""
    fees = R.CC.fees_from_amm_config(config)
    out, last_open = [], None
    for i, swap in enumerate(line.swaps):
        t = swap.block_time
        refs = [j for j in range(i) if line.swaps[j].block_time <= t - R.LOOKBACK_S]
        if not refs:
            continue
        recent = sum(1 for k in range(i + 1) if t - R.LOOKBACK_S < line.swaps[k].block_time <= t)
        if recent < R.MIN_SWAPS_IN_LOOKBACK:
            continue
        if last_open is not None and t - last_open < R.COOLDOWN_S:
            continue
        if R.spot_after(line, i, fees) / R.spot_after(line, refs[-1], fees) - 1 >= RISE:
            out.append(i)
            last_open = t
    return out


# same exits, costs, placebo, halves, power and confirmation as R-CP1 (imported, unchanged)
exit_point, positions, placebo, halves = R.exit_point, R.positions, R.placebo, R.halves
n_required, power_stop, expected_entries = R.n_required, R.power_stop, R.expected_entries
sigma_of_pilot, confirmation_n, confirmation_verdict = R.sigma_of_pilot, R.confirmation_n, R.confirmation_verdict


def trigger_count(lines, config, t0):
    """B1 TRIGGERS with block time in [T0 - 7 d ; T0) per pool; data at or after T0 REFUSED; no outcome computed."""
    if type(t0) is not int:
        raise PreregError('t0_must_be_an_integer_block_time')
    start = t0 - R.COUNT_DAYS * R.DAY_S
    per_pool = {}
    for line in lines:
        if line.pool in per_pool:
            raise PreregError('pool_given_twice')
        if any(s.block_time >= t0 for s in line.swaps):
            raise PreregError('data_at_or_after_t0_refused')
        per_pool[line.pool] = sum(1 for i in decisions(line, config) if line.swaps[i].block_time >= start)
    return dict(schema=SCHEMA, t0=t0, window=[start, t0], days=R.COUNT_DAYS, per_pool=per_pool,
                triggers=sum(per_pool.values()), outcomes_computed=False)


def trials(n_before=TRIALS_BEFORE):
    if type(n_before) is not int or n_before + 1 > R.TRIAL_CAP:
        raise PreregError('trial_cap_exceeded')
    return dict(n_before=n_before, n_after=n_before + 1, left=R.TRIAL_CAP - n_before - 1,
                rule='B1 and its placebo are ONE trial, the 170th and last, consumed when the pilot starts; beyond 170 '
                     'no hypothesis without a costed authorisation and an anchored correction rule')
