"""Pre-registered synthetic research diagnostics; never an activatable model.

Only generated SOL-denominated observations are accepted by the CLI. No network,
wallet, database, market data or production strategy is used by this experiment.
"""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import heapq
import json
import math
from pathlib import Path
import random
from statistics import mean

from bot.analyser.temporal_split import temporal_partition

PROTOCOL = 'rugger_synthetic_sol_v1'
POLICIES = ('all_eligible', 'positive_momentum', 'cautious_momentum')
COSTS_BPS = (200, 500, 1000)
SLIPPAGE_BPS = (0, 100, 300)
INITIAL_SOL = 10.0
POSITION_SOL = INITIAL_SOL * .10
MAX_OPEN = 3
MIN_SIZES = (30, 15, 15)


@dataclass(frozen=True)
class Observation:
    signal_time: int
    signature: str
    mint: str
    momentum: float
    liquidity_sol: float
    gross_return_sol: float
    quote_delay: int = 0
    entry_available: bool = True

    @property
    def entry_time(self):
        return self.signal_time + 300 + self.quote_delay

    @property
    def exit_time(self):
        return self.signal_time + 900 + self.quote_delay

    @property
    def event(self):
        return (self.signal_time, self.signature, 'synthetic', self.mint, 'synthetic-pool')


def generate(seed=20261026, count=300, regime='null'):
    """Entirely invented fixtures, including known zero-edge and adverse worlds."""
    if type(seed) is not int or type(count) is not int or count < 1:
        raise ValueError('Invalid synthetic seed/count')
    if regime not in ('null', 'momentum_linked', 'adverse'):
        raise ValueError('Unknown synthetic regime')
    rng = random.Random(seed)
    rows = []
    for group in range((count + 1) // 2):
        # Both mints share a transaction, timestamp and outcome shock.
        common_shock = rng.gauss(0, .08)
        for sibling in range(2):
            i = group * 2 + sibling
            if i >= count:
                break
            momentum = rng.uniform(-.15, .20)
            gross = common_shock + rng.gauss(0, .025)
            if regime == 'momentum_linked':
                gross += momentum * .5
            elif regime == 'adverse':
                gross -= .06
                if group % 17 == 0:
                    gross = -.95
            rows.append(Observation(1000 + group * 180, f'synthetic-tx-{group:06}',
                f'synthetic-mint-{i:06}', momentum, rng.uniform(5, 100),
                max(-1., min(2., gross)), rng.choice((0, 0, 0, 60, 180)),
                rng.random() >= .05))
    return rows


def _validate(rows):
    if not rows:
        raise ValueError('INSUFFICIENT DATA: empty synthetic corpus')
    for row in rows:
        if (not isinstance(row, Observation) or type(row.signal_time) is not int
                or row.signal_time < 0 or not row.signature or not row.mint
                or type(row.quote_delay) is not int or row.quote_delay < 0
                or type(row.entry_available) is not bool):
            raise ValueError('Invalid synthetic observation identity/time')
        for field in ('momentum', 'liquidity_sol', 'gross_return_sol'):
            value = getattr(row, field)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('INSUFFICIENT DATA: finite SOL observations required')
        if row.gross_return_sol < -1 or row.liquidity_sol < 0:
            raise ValueError('Invalid unleveraged SOL observation')


def split_periods(rows):
    """Choose both raw boundaries before filtering, then purge prior labels."""
    _validate(rows)
    ordered = sorted(rows, key=lambda row: row.event)
    events = [row.event for row in ordered]
    ends = {row.mint: row.exit_time for row in ordered}
    _, holdout, final_info = temporal_partition(events, ends, .8)
    if not final_info['boundary_available']:
        raise ValueError('INSUFFICIENT DATA: no grouped final-test boundary')
    final_start = final_info['test_period_started_at']
    raw_development = [event for event in events if event[0] < final_start]
    train, validation_raw, development_info = temporal_partition(raw_development, ends, .75)
    if not development_info['boundary_available']:
        raise ValueError('INSUFFICIENT DATA: no grouped validation boundary')
    validation = [event for event in validation_raw if ends[event[3]] < final_start]
    by_mint = {row.mint: row for row in ordered}
    parts = tuple([by_mint[event[3]] for event in part]
                  for part in (train, validation, holdout))
    if any(len(part) < minimum for part, minimum in zip(parts, MIN_SIZES)):
        raise ValueError('INSUFFICIENT DATA after grouping/purge: ' + str(tuple(map(len, parts))))
    diagnostics = {
        'raw_target_fractions': [.6, .2, .2],
        'validation_started_at': development_info['test_period_started_at'],
        'final_test_started_at': final_start,
        'train': development_info,
        'development_before_final': final_info,
        'purged_validation_observations': len(validation_raw) - len(validation),
        'sizes_after_purge': dict(zip(('train', 'validation', 'final_test'), map(len, parts))),
        'min_sizes': dict(zip(('train', 'validation', 'final_test'), MIN_SIZES)),
    }
    return (*parts, diagnostics)


def _eligible(row, policy):
    if policy not in POLICIES:
        raise ValueError('Unknown fixed synthetic policy')
    return (policy == 'all_eligible' or row.momentum > 0) and (
        policy != 'cautious_momentum' or row.liquidity_sol >= 50)


def simulate(rows, policy, cost_bps=200, slippage_bps=0):
    """Event ledger in SOL. Fixed all-in budget avoids trade-return compounding.

    Synthetic execution assumptions: no leverage; zero exit value bounds loss to
    the budget; roundtrip costs/slippage are deducted from exit proceeds. Fees of
    failed submissions are zero in this fixture; no claim of executable prices.
    """
    _validate(rows)
    for value in (cost_bps, slippage_bps):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid nonnegative execution-cost assumption')
    if policy not in POLICIES:
        raise ValueError('Unknown fixed synthetic policy')
    cash = equity = peak = INITIAL_SOL
    pending, trades = [], []
    rejected = dict(policy=0, missing_entry_quote=0, stale_quote=0,
                    liquidity=0, exposure=0, balance=0)
    max_open = 0
    max_drawdown = 0.
    minimum_cash = cash

    def close_until(timestamp):
        nonlocal cash, equity, peak, max_drawdown
        while pending and pending[0][0] <= timestamp:
            batch_time, batch_pnl = pending[0][0], 0.
            while pending and pending[0][0] == batch_time:
                end, mint, signature, gross = heapq.heappop(pending)
                exit_proceeds = POSITION_SOL * max(0., 1 + gross - (cost_bps + slippage_bps) / 10000)
                pnl = exit_proceeds - POSITION_SOL
                cash += exit_proceeds
                batch_pnl += pnl
                trades.append(dict(mint=mint, signature=signature, exit_time=end,
                                   position_sol=POSITION_SOL, pnl_sol=pnl))
            equity += batch_pnl
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    for row in sorted(rows, key=lambda row: (row.entry_time, row.signature, row.mint)):
        close_until(row.entry_time)
        if not _eligible(row, policy):
            rejected['policy'] += 1
        elif not row.entry_available:
            rejected['missing_entry_quote'] += 1
        elif row.quote_delay > 120:
            rejected['stale_quote'] += 1
        elif row.liquidity_sol < 20 * POSITION_SOL:
            rejected['liquidity'] += 1
        elif len(pending) >= MAX_OPEN:
            rejected['exposure'] += 1
        elif cash < POSITION_SOL:
            rejected['balance'] += 1
        else:
            cash -= POSITION_SOL
            minimum_cash = min(minimum_cash, cash)
            heapq.heappush(pending, (row.exit_time, row.mint, row.signature, row.gross_return_sol))
            max_open = max(max_open, len(pending))
    close_until(math.inf)
    pnls = [trade['pnl_sol'] for trade in trades]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    profit_factor = sum(wins) / -sum(losses) if losses else None
    return {
        'opportunities': len(rows), 'trades': len(trades), 'rejections': rejected,
        'execution_fraction': len(trades) / len(rows),
        'entry_quote_coverage': sum(row.entry_available for row in rows) / len(rows),
        'initial_capital_sol': INITIAL_SOL, 'final_capital_sol': equity,
        'net_pnl_sol': equity - INITIAL_SOL, 'capital_return': equity / INITIAL_SOL - 1,
        'max_drawdown_realized': max_drawdown,
        'mean_trade_pnl_sol': mean(pnls) if pnls else None,
        'win_rate': len(wins) / len(pnls) if pnls else None,
        'average_gain_sol': mean(wins) if wins else None,
        'average_loss_sol': mean(losses) if losses else None,
        'worst_trade_pnl_sol': min(pnls) if pnls else None,
        'profit_factor': profit_factor,
        'profit_factor_status': 'finite' if losses else ('no_losses' if wins else 'no_nonzero_trades'),
        'max_open_positions': max_open, 'max_reserved_sol': max_open * POSITION_SOL,
        'minimum_available_cash_sol': minimum_cash,
        'cost_bps': cost_bps, 'slippage_bps': slippage_bps,
        'closed_trades': trades,
    }


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def select_policy(train, validation):
    """No final-test observations are accepted by this function."""
    results = []
    for policy in POLICIES:
        fit = simulate(train, policy, max(COSTS_BPS), max(SLIPPAGE_BPS))
        check = simulate(validation, policy, max(COSTS_BPS), max(SLIPPAGE_BPS))
        results.append(dict(policy=policy, train=fit, validation=check,
                            eligible=fit['trades'] >= 5 and check['trades'] >= 5))
    eligible = [result for result in results if result['eligible']]
    if not eligible:
        raise ValueError('INSUFFICIENT DATA: fewer than five train/validation executions per policy')
    best = max(eligible, key=lambda result: (result['validation']['net_pnl_sol'],
                                            -POLICIES.index(result['policy'])))
    return best['policy'], results


def _uncertainty(trades, seed):
    """Conditional moving-block bootstrap, not a profitability or DD guarantee."""
    groups = {}
    for trade in trades:
        groups.setdefault(trade['signature'], []).append(trade['pnl_sol'])
    blocks = list(groups.values())
    if len(blocks) < 10:
        return {'status': 'insufficient_groups', 'groups': len(blocks)}
    rng = random.Random(seed)
    draws = []
    for _ in range(200):
        sampled = []
        while len(sampled) < len(blocks):
            start = rng.randrange(len(blocks))
            sampled.extend(blocks[(start + offset) % len(blocks)] for offset in range(5))
        values = [pnl for group in sampled[:len(blocks)] for pnl in group]
        draws.append(mean(values))
    draws.sort()
    return {'status': 'conditional_descriptive', 'groups': len(blocks), 'resamples': 200,
            'block_length_groups': 5, 'interval_quantiles': [.025, .975],
            'mean_trade_pnl_sol_interval': [draws[4], draws[194]],
            'limitation': 'Conditions on executed cohorts; not a confidence interval for market profitability, drawdown or ruin.'}


def run_experiment(rows, seed=20261026, regime='custom_synthetic'):
    train, validation, final_test, partition = split_periods(rows)
    chosen, development = select_policy(train, validation)
    chosen_validation = next(result['validation'] for result in development
                             if result['policy'] == chosen)
    # The choice is frozen before this loop; no final result changes it.
    final_runs = []
    for cost in COSTS_BPS:
        for slip in SLIPPAGE_BPS:
            metrics = simulate(final_test, chosen, cost, slip)
            metrics['uncertainty'] = _uncertainty(metrics['closed_trades'], seed)
            final_runs.append(metrics)
    result = {
        'protocol': PROTOCOL, 'data_kind': 'synthetic', 'seed': seed, 'regime': regime,
        'economic_verdict': 'INSUFFICIENT DATA',
        'model_eligible': False, 'paper_eligible': False, 'real_orders_enabled': False,
        'unit': 'SOL', 'synthetic_return_field': 'gross_return_sol',
        'fx_assumption': 'No USD data: every generated return and capital amount is denominated in SOL.',
        'dataset_sha256': _digest([asdict(row) for row in rows]),
        'selection_input_sha256': _digest([asdict(row) for row in train + validation]),
        'partition': partition, 'policies_registered': list(POLICIES),
        'candidate_trials': len(POLICIES), 'final_policy': chosen,
        'validation_positive': chosen_validation['net_pnl_sol'] > 0,
        'selection_outcome': ('positive_on_validation' if chosen_validation['net_pnl_sol'] > 0
                              else 'no_positive_validation_candidate'),
        'no_trade_control': {'initial_capital_sol': INITIAL_SOL,
                             'final_capital_sol': INITIAL_SOL, 'net_pnl_sol': 0.,
                             'capital_return': 0., 'max_drawdown_realized': 0., 'trades': 0},
        'selection_rule': 'Highest validation net SOL PnL at 1000bps cost + 300bps slippage; fixed policy-order tie break; minimum 5 executions in train and validation.',
        'development': development, 'final_test': final_runs,
        'assumptions': {
            'capital_sol': INITIAL_SOL, 'fixed_all_in_position_sol': POSITION_SOL,
            'max_open_positions': MAX_OPEN, 'minimum_observed_liquidity_sol': 20 * POSITION_SOL,
            'quote_delay_limit_seconds': 120, 'signal_to_entry_seconds': 300,
            'signal_to_exit_seconds': 900,
            'exit_availability': 'Guaranteed only by the synthetic generator; complete labels required, never a market-data claim.',
            'failed_submission_cost_sol': 0,
            'cost_convention': 'Roundtrip costs/slippage deducted from exit proceeds, floored at zero; maximum loss is the all-in position budget.',
            'drawdown': 'Realized SOL equity aggregated by exit timestamp; no mark-to-market or executable intratrade drawdown.',
            'same_timestamp_order': 'Aggregate all exits before deterministic mint-ordered entries; a synthetic convention, not a network guarantee.',
        },
    }
    result['report_sha256'] = _digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=20261026)
    parser.add_argument('--count', type=int, default=300)
    parser.add_argument('--regime', choices=('null', 'momentum_linked', 'adverse'), default='null')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run_experiment(generate(args.seed, args.count, args.regime), args.seed, args.regime)
    from bot.analyser.artifacts import atomic_write_json
    atomic_write_json(args.output, result, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps({key: result[key] for key in ('protocol', 'data_kind', 'economic_verdict',
                                                'final_policy', 'report_sha256')}, sort_keys=True))


if __name__ == '__main__':
    main()
