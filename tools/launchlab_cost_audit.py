#!/usr/bin/env python3
"""Offline accounting audit of the fixed LaunchLab baseline replay cycles.

Reads only the committed SOL fixtures (no network, no key, no transaction). For
each pool it re-runs the baseline of ``launchlab_baseline_report`` (0.05 SOL
entry, 2-slot assumed latency, the pool's inferred fee rate) and then
recomputes every leg of the cycle independently from the curve arithmetic, so
that the replay totals can be checked line by line.

It makes NO claim of profitability: it audits bookkeeping on two entries.

  python -B tools/launchlab_cost_audit.py [--dir DIR] [--markdown]
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.market.collector import load_archive, summarize  # noqa: E402
from bot.market.launchlab_curve import FEE_DENOMINATOR, buy_exact_in, fee_for  # noqa: E402
from bot.market.replay import ExecutionModel, replay  # noqa: E402

DEFAULT_DIR = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
LAMPORTS = 1_000_000_000

# Quantities the current replay/archives do not expose. Reported, never guessed.
NOT_EXPOSED = (
    'priority_fee_lamports: modelled as 0; observed tx fees mix base and priority fee and the compute-budget price is not parsed',
    'jito_or_other_tip_lamports: not modelled',
    'token_account_rent: assumed refunded after exit (replay docstring); the rent float is not counted',
    'wsol_wrap_unwrap_costs: not modelled',
    'slippage_tolerance_and_failed_or_reverted_transactions: not modelled (fills are exact at the replayed state)',
    'cost_of_our_own_transactions: the base fee is the median of OTHER traders\' successful fees in the pool, an assumption',
    'cpmm_exit_after_migration: not priced (outcome migrated_unpriced, no P&L credited)',
)


def _load_baseline():
    spec = importlib.util.spec_from_file_location('launchlab_baseline_report',
                                                  ROOT / 'tools' / 'launchlab_baseline_report.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exit_gross(received, rate_ppm):
    """Gross sell output g with g - ceil(g*rate/1e6) == received, or None."""
    guess = received * FEE_DENOMINATOR // (FEE_DENOMINATOR - rate_ppm)
    for gross in range(max(guess - 2, 1), guess + 4):
        if gross - fee_for(gross, rate_ppm) == received:
            return gross
    return None


def audit_pool(directory, pool):
    base = _load_baseline()
    archive = load_archive(directory, pool)
    summary, timeline = summarize(archive)
    low, high = base.fee_rate_interval(timeline.events)
    row = {'pool': pool, 'trades': len(timeline.events), 'complete': summary['complete'],
           'quote_is_sol': summary['quote_is_sol'], 'fee_rate_ppm_interval': [low, high],
           'entry_size_SOL': base.SPEND_LAMPORTS / LAMPORTS, 'latency_slots_assumed': base.LATENCY_SLOTS}
    if not (summary['complete'] and summary['quote_is_sol'] and low <= high and timeline.events):
        row['outcome'] = 'not_replayable'
        return row
    fees = [tx['meta']['fee'] for tx in archive.transactions.values()
            if (tx.get('meta') or {}).get('err') is None]
    fees.sort()
    median_fee = int(base.statistics.median(fees)) if fees else 0
    model = ExecutionModel(latency_slots=base.LATENCY_SLOTS, fee_rate_ppm=low,
                           base_fee_lamports=median_fee, priority_fee_lamports=0)
    result = replay(timeline, base.Baseline(), model, quote_mint=archive.account['mint_quote'])
    final_state = timeline.events[-1].state_after()
    row.update({
        'outcome': result.outcome,
        'decision_index': result.decision_index, 'entry_index': result.entry_index,
        'exit_index': result.exit_index, 'hold_slots': result.hold_slots,
        'fee_rate_ppm_used': low,
        'tx_fee_lamports': {'observed_min': fees[0] if fees else 0, 'observed_median': median_fee,
                            'observed_max': fees[-1] if fees else 0, 'used_per_tx': model.tx_cost,
                            'kind': 'assumed (median of other traders\' fees, priority fee 0)'},
        'flags': {'migrated': result.outcome == 'migrated_unpriced' or final_state.remaining_base == 0,
                  'final_liquidation_marked_not_executed': result.outcome == 'open_at_end',
                  'counterfactual_divergence': result.outcome == 'counterfactual_divergence'},
    })
    if result.entry_index is None:
        return row
    entry_state = timeline.events[result.entry_index].state_after()
    fill = buy_exact_in(entry_state, base.SPEND_LAMPORTS, low)
    entry = {'curve_input_lamports': fill.amount_in, 'entry_fee_lamports': fill.fee,
             'net_into_curve_lamports': fill.amount_in - fill.fee, 'tokens_out': fill.amount_out}
    row['entry_leg'] = entry
    row['entry_matches_replay'] = (fill.amount_in == result.spent and fill.amount_out == result.tokens)
    if result.outcome in ('closed', 'open_at_end'):
        gross = _exit_gross(result.received, low)
        exit_leg = {'tokens_in': result.tokens, 'curve_output_gross_lamports': gross,
                    'exit_fee_lamports': None if gross is None else gross - result.received,
                    'net_received_lamports': result.received}
        row['exit_leg'] = exit_leg
        costs = result.tx_costs
        pnl = result.received - result.spent - costs
        denominator = result.spent + costs
        row['accounting'] = {
            'curve_fees_total_lamports': None if gross is None else fill.fee + gross - result.received,
            'tx_costs_lamports': costs, 'tx_count': 2,
            'pnl_lamports': pnl, 'pnl_SOL': pnl / LAMPORTS,
            'net_return': round(pnl / denominator, 6),
            'sensitivity_pnl_SOL_if_both_txs_pay_observed_max_fee': (
                result.received - result.spent - 2 * (fees[-1] if fees else 0)) / LAMPORTS,
            'identity_ok': pnl == result.pnl and round(pnl / denominator, 6) == round(result.net_return, 6),
        }
        row['baseline_report_differences'] = _differences(base, directory, pool, row)
    row['not_exposed'] = list(NOT_EXPOSED)
    return row


def _differences(base, directory, pool, row):
    """Compare with the existing baseline report; empty list means identical."""
    reference = base.report_pool(directory, pool).get('replay', {})
    acc, entry = row['accounting'], row['entry_leg']
    pairs = (('spent_SOL', reference.get('spent_SOL'), entry['curve_input_lamports'] / LAMPORTS),
             ('received_SOL', reference.get('received_SOL'), row['exit_leg']['net_received_lamports'] / LAMPORTS),
             ('tx_costs_SOL', reference.get('tx_costs_SOL'), acc['tx_costs_lamports'] / LAMPORTS),
             ('pnl_SOL', reference.get('pnl_SOL'), acc['pnl_SOL']),
             ('net_return', reference.get('net_return'), acc['net_return']))
    return [{'field': n, 'baseline_report': a, 'audit': b} for n, a, b in pairs
            if a is None or abs(a - b) > 1e-9]


def to_markdown(rows):
    out = ['| pool | outcome | spent | entry fee | received | exit fee | tx costs | pnl (SOL) | return | migrated |',
           '|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        e, x, a = r.get('entry_leg'), r.get('exit_leg'), r.get('accounting')
        out.append('| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |'.format(
            r['pool'][:8], r['outcome'],
            e and e['curve_input_lamports'], e and e['entry_fee_lamports'],
            x and x['net_received_lamports'], x and x['exit_fee_lamports'],
            a and a['tx_costs_lamports'], a and a['pnl_SOL'], a and a['net_return'],
            r.get('flags', {}).get('migrated')))
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', type=Path, default=DEFAULT_DIR)
    parser.add_argument('--markdown', action='store_true')
    args = parser.parse_args(argv)
    pools = [p.name[:-len('.json.gz')] for p in sorted(args.dir.glob('*.json.gz'))]
    rows = [audit_pool(args.dir, pool) for pool in pools]
    if args.markdown:
        print(to_markdown(rows))
    else:
        for row in rows:
            print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
