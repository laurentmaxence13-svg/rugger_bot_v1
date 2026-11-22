"""w2cost 0.1 -- PROPOSAL (task P4) of a 'full-cost W2 engine': papercost 0.1 + rtgate 0.2 + landslip guard under ONE
declared parameter set, frozen before any W2 datum. NOT ADOPTED: adopting it would change frozen hypotheses of dossier B
v1.9; that decision belongs to the owner. Fixtures only; nothing here reads W1 or W2 data.

* ``PARAMETERS``: the single declared parameter document (its sha256 is what a freeze would anchor);
* ``complete_or_excluded``: rtgate 0.2 run on a complete batch timeline (W2 replays are collected archives): COMPLETE
  is required, otherwise the pool is excluded (fail shut), never repaired;
* ``n_min``: the dossier B 6.1 formula n = ((z_(1-alpha) + z_power) x sigma / delta)^2 (414 for sigma 13.7 %, delta
  +2 %, alpha 0.05/3, power 0.80), and ``n_min_full_cost`` with the effect reduced by the extra cost per cycle;
* ``fixture_impact``: on the public fixture pools, every event index as a forced entry (EnterAt), frozen engine vs
  the proposed primary: share of entries refused by the guard, mean extra cost per entered cycle (on the stake) and
  standard deviations. These numbers describe the three public pools ONLY: they are not an estimate for W1 or W2.
"""
import hashlib
import json
import math
import statistics
from dataclasses import asdict
from statistics import NormalDist

from bot.market import replay as R
from landslip import guard as G
from mevsens import model as MEV
from papercost import engine as PC
from rtgate import gate as RT

SCHEMA = 'w2cost-proposal-v0.1'
SIGMA_DOSSIER_B = 0.137
DELTA_DOSSIER_B = 0.02
ALPHA_DOSSIER_B = 0.05 / 3
POWER_DOSSIER_B = 0.80
N_MIN_DOSSIER_B = 414
STAKE = 100_000_000

PARAMETERS = dict(
    schema=SCHEMA,
    engine=dict(paperstream='0.4 e86f66b0 (subclassed, unchanged)', papercost='0.1 2937aa3 PASS R02',
                rtgate='0.2 22c595b PASS R02', landslip='0.1 8e432a5 PASS R02', mevsens='0.1 a94a660 PASS R02'),
    primary=dict(buy_guard_ppm=G.BUY_GUARD_PPM, sell_guard_ppm=None, h1=True, buy_failures=0, sell_failures=0,
                 fail_ppm=0, account_mode='rent_lost', wsol_lamports_per_tx=PC.WSOL_FLAT_LAMPORTS,
                 cleanup_failures=0, mev_scenario='none', open_positions='marked_and_counted',
                 unpriced='counted_at_zero', stream_gate='rtgate COMPLETE required, else pool excluded'),
    published_apart=dict(account_mode='closed', buy_guard_ppm=G.BUY_GUARD_SENSITIVITY_PPM,
                         sell_guard_ppm=G.SELL_GUARD_SENSITIVITY_PPM, failures_per_tx=1,
                         wsol_lamports_per_tx=PC.WSOL_SEPARATE_CLOSE_LAMPORTS,
                         mev_scenarios=[s['name'] for s in MEV.SCENARIOS], frozen_net='always published beside'),
    adopted=False,
    adoption='owner decision: it changes frozen hypotheses of dossier B v1.9 (engine of A0/A1 and the cost of C-B)')


def parameters_sha256():
    return hashlib.sha256(json.dumps(PARAMETERS, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def primary_options():
    p = PARAMETERS['primary']
    return PC.Options(buy_guard_ppm=p['buy_guard_ppm'], sell_guard_ppm=p['sell_guard_ppm'], h1=p['h1'],
                      buy_failures=p['buy_failures'], sell_failures=p['sell_failures'], fail_ppm=p['fail_ppm'])


def n_min(sigma=SIGMA_DOSSIER_B, delta=DELTA_DOSSIER_B, alpha=ALPHA_DOSSIER_B, power=POWER_DOSSIER_B):
    if not (sigma > 0 and delta > 0 and 0 < alpha < 0.5 and 0.5 < power < 1):
        raise ValueError('invalid_power_inputs')
    z = NormalDist().inv_cdf(1 - alpha) + NormalDist().inv_cdf(power)
    return math.ceil((z * sigma / delta) ** 2)


def n_min_full_cost(extra_cost, sigma=SIGMA_DOSSIER_B, delta=DELTA_DOSSIER_B, entry_share=1.0, **kwargs):
    """Decisions needed when each entered cycle costs ``extra_cost`` more (share of the stake) and only ``entry_share``
    of the decisions enter (the guard refuses the rest): the detectable effect becomes delta - extra_cost."""
    if not 0 < entry_share <= 1:
        raise ValueError('invalid_entry_share')
    effect = delta - extra_cost
    if effect <= 0:
        return None                                            # the effect is eaten by the costs: never detectable
    # never below the protected n_min of dossier B: a cost layer that LOOKS favourable on some data (e.g. the guard
    # removing losing entries) is not a reason to need fewer cycles
    cycles = max(n_min(sigma, effect, **kwargs), N_MIN_DOSSIER_B)
    return dict(cycles=cycles, decisions=math.ceil(cycles / entry_share), effect=effect)


def complete_or_excluded(timeline, strategy, model, *, quote_mint=R.WSOL_MINT):
    record = RT.run(timeline.pool, list(timeline.events), strategy, model, quote_mint=quote_mint)
    return record['status'] == RT.COMPLETE, record


def _net(result, options_costs):
    row = dict(outcome=result['outcome'], spent=result['spent'], received=result['received'],
               tx_costs=result['tx_costs'], failed_attempt_costs=0, entry_index=result['entry_index'],
               notes=result['notes'], tokens=result['tokens'])
    return PC.row_costs(row, options_costs)


def fixture_impact(timelines, model, strategy_factory, indices):
    """Frozen engine vs the proposed primary on forced entries at the given event indices of each fixture pool."""
    frozen_nets, full_nets, deltas, engine_only, refused, entered = [], [], [], [], 0, 0
    for timeline in timelines:
        for k in indices:
            if k >= len(timeline.events):
                continue
            frozen = asdict(R.replay(timeline, strategy_factory(k), model, quote_mint=R.WSOL_MINT))
            if frozen['entry_index'] is None:
                continue
            trade = PC.CostedTrade(timeline.pool, strategy_factory(k), model, quote_mint=R.WSOL_MINT,
                                   options=primary_options())
            for event in timeline.events:
                if trade.phase == 'stopped':
                    break
                trade.push(event)
            full = asdict(trade.finish())
            entered += 1
            f = _net(frozen, 'frozen_assumption')                 # the A0/A1 engine: rent assumed refunded for free
            f_mode = _net(frozen, PARAMETERS['primary']['account_mode'])   # frozen fills, full-cost accounting
            c = _net(full, PARAMETERS['primary']['account_mode'])
            if c['status'] == 'guard_failed':
                refused += 1
            frozen_nets.append(f['net_return'])
            full_nets.append(c['net_return'])
            deltas.append(f['net_return'] - c['net_return'])
            engine_only.append(f_mode['net_return'] - c['net_return'])
    if not entered:
        raise ValueError('no_entry_on_the_fixtures')
    sd = (lambda xs: statistics.pstdev(xs) if len(xs) > 1 else None)
    return dict(entries_frozen=entered, refused_by_guard=refused, entry_share=(entered - refused) / entered,
                mean_extra_cost_vs_frozen_engine=statistics.fmean(deltas),
                mean_extra_cost_engine_only=statistics.fmean(engine_only),
                sd_frozen=sd(frozen_nets), sd_full=sd(full_nets),
                fixtures_only=True, estimate_for_w2=False)
