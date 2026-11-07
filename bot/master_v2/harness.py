"""Causal replay harness for MASTER V2 challenger policies (offline research only).

A ``Policy`` sees ``native_features`` of the events up to the decision and answers
ENTER, WAIT or NO_TRADE (final abstention for the pool). Execution, latency, own
impact, migration and accounting reuse the audited L1 machinery
(``bot.market.replay`` with the causal fee estimate, ``usable_timeline``,
``_trade``/``_migrated`` of ``bot.p4.historical_research_replay``): a challenger can
only differ from the reference by its decisions, never by its bookkeeping.

Exits act on the exact net liquidation value of the whole position (``mark``):
stop loss, trailing stop (armed once the mark exceeded the amount spent), maximum
hold, then take profit -- the precedence of
``bot.master_positions.choose_frozen_position_action``.

Results are HISTORICAL_REPLAY research: never PAPER-ledger entries, never evidence
for the 50-cycle / 20-creator gate, never operational Master trades.
"""
from collections import Counter
from dataclasses import asdict, dataclass

from bot.market.collector import summarize
from bot.market.replay import Strategy, replay
from bot.master_v2.features import native_features
from bot.master_v2.validation import cycle_metrics, preregistration
from bot.p4 import historical_research_replay as hrr

SCHEMA = 'rugger-master-v2-research-v1'
INTENTS = ('ENTER', 'WAIT', 'NO_TRADE')


@dataclass(frozen=True)
class ExitRule:
    """Fractions of the amount spent (0.3 = 30 %); None disables a trigger.

    ``exit_progress_ppm`` sells once the observed curve progress reaches this level,
    so that a position is not carried into the migration (where it becomes
    unpriced on this curve).
    """
    take_profit: float = None
    stop_loss: float = None
    trailing: float = None
    max_hold_s: int = None
    exit_progress_ppm: int = None

    def __post_init__(self):
        for name in ('take_profit', 'stop_loss', 'trailing'):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float) or not 0 < value < 10):
                raise ValueError(f'invalid_{name}')
        if self.stop_loss is not None and self.stop_loss >= 1:
            raise ValueError('invalid_stop_loss')
        if self.trailing is not None and self.trailing >= 1:
            raise ValueError('invalid_trailing')
        if self.max_hold_s is not None and (type(self.max_hold_s) is not int or self.max_hold_s <= 0):
            raise ValueError('invalid_max_hold_s')
        if self.exit_progress_ppm is not None and (type(self.exit_progress_ppm) is not int
                                                   or not 0 < self.exit_progress_ppm < 1_000_000):
            raise ValueError('invalid_exit_progress_ppm')


class Policy:
    """Override ``decide``; ``name`` and ``params`` identify the pre-registered policy."""
    name = 'abstract'

    def params(self):
        return {}

    def decide(self, features, facts):
        """Return (intent, reasons) with intent in INTENTS."""
        raise NotImplementedError


class PolicyArm(Strategy):
    """Journal every decision, enter once with ``entry_lamports``, exit by ``exit_rule``."""

    def __init__(self, policy, exit_rule, facts, events_per_tx, entry_lamports):
        self.policy, self.rule, self.facts = policy, exit_rule, facts
        self.events_per_tx, self.entry_lamports = events_per_tx, entry_lamports
        self.journal, self.exit_plan, self.exit_trigger = [], None, None
        self.abstained, self.peak_mark = False, None

    def entry(self, history):
        if self.exit_plan is not None or self.abstained:
            return None
        last = history[-1]
        if sum(e.signature == last.signature for e in history) < self.events_per_tx[last.signature]:
            return None                       # a transaction is observed whole, never mid-way
        features = native_features(history, self.facts)
        intent, reasons = self.policy.decide(features, self.facts)
        if intent not in INTENTS:
            raise ValueError('invalid_policy_intent')
        self.journal.append(dict(index=len(history) - 1, signature=last.signature, slot=last.slot,
                                 block_time=last.block_time, intent=intent, reasons=list(reasons)))
        if intent == 'NO_TRADE':
            self.abstained = True
            return None
        if intent != 'ENTER':
            return None
        self.exit_plan = asdict(self.rule)
        return self.entry_lamports

    def exit(self, history, position, mark):
        rule = self.rule
        ratio = mark / position.spent
        self.peak_mark = mark if self.peak_mark is None else max(self.peak_mark, mark)
        held_s = history[-1].block_time - position.entry_time
        trailing = (rule.trailing is not None and self.peak_mark > position.spent
                    and mark <= self.peak_mark * (1 - rule.trailing))
        near_migration = (rule.exit_progress_ppm is not None
                          and history[-1].state_after().progress_ppm >= rule.exit_progress_ppm)
        trigger = ('stop_loss' if rule.stop_loss is not None and ratio <= 1 - rule.stop_loss else
                   'trailing_stop' if trailing else
                   'pre_migration' if near_migration else
                   'max_hold' if rule.max_hold_s is not None and held_s >= rule.max_hold_s else
                   'take_profit' if rule.take_profit is not None and ratio >= 1 + rule.take_profit else None)
        if trigger:
            self.exit_trigger = dict(reason=trigger, index=len(history) - 1, mark=mark)
        return trigger is not None


def run_policy_pool(archive, policy, exit_rule, params, *, quote_mint,
                    entry_lamports=hrr.ENTRY_LAMPORTS):
    """One pool: journal, trade row (closed P&L or explicit open/migrated/unpriced outcome)."""
    summary, timeline = summarize(archive)
    timeline, migration = hrr.usable_timeline(archive, summary, timeline)
    facts = dict(hrr.creation_facts(archive), pool=archive.pool)
    arm = PolicyArm(policy, exit_rule, facts, Counter(e.signature for e in timeline.events), entry_lamports)
    result = replay(timeline, arm, params.execution_model(), quote_mint=quote_mint)
    row = hrr._trade(result, timeline.events, arm, params)
    if migration is not None:
        row = hrr._migrated(row)
    record = dict(pool=archive.pool, creator=facts['creator'], created_slot=facts['creation_slot'],
                  signed_creator_verified=facts['signed_creator_verified'], trades=len(timeline.events),
                  journal=arm.journal, trade=row)
    if migration is not None:
        record['migration'] = migration
    return record


def run_policy(fixtures_dir, policy, exit_rule, params=None, *, design=None):
    """Bundle of one policy over a fixture directory, with closed-cycle metrics."""
    params = hrr.ReplayParams() if params is None else params
    manifest_sha256, digests, archives, _manifest = hrr.load_fixtures(fixtures_dir)
    pools, excluded = [], []
    for entry, archive in archives:
        try:
            pools.append(run_policy_pool(archive, policy, exit_rule, params, quote_mint=entry['quote_mint']))
        except hrr.PoolExcluded as exc:
            excluded.append(dict(pool=archive.pool, file=entry['file'], reasons=exc.reasons))
    if len(pools) + len(excluded) != len(archives):
        raise ValueError('pool_accounting_mismatch')
    cycles = [dict(pool=p['pool'], creator=p['creator'], pnl_lamports=p['trade']['pnl_lamports'],
                   cost_lamports=p['trade']['spent'] + p['trade']['tx_costs'] + p['trade']['failed_attempt_costs'],
                   order_key=(p['trade']['exit_slot'], p['pool']))
              for p in pools if p['trade']['outcome'] == 'closed']
    design = design or dict(split='none', note='descriptive run, not a validation')
    bundle = dict(
        schema=SCHEMA, category=hrr.CATEGORY, policy_status='MASTER_RESEARCH',
        policy=policy.name, policy_params=policy.params(), exit_rule=asdict(exit_rule),
        params=asdict(params), preregistration_sha256=preregistration(
            policy.name, dict(policy=policy.params(), exit=asdict(exit_rule), replay=asdict(params)), design),
        fixtures=dict(manifest_sha256=manifest_sha256, files=digests),
        pools=pools, excluded_pools=excluded,
        outcomes=dict(sorted(Counter(p['trade']['outcome'] for p in pools).items())),
        metrics=cycle_metrics(cycles),
        flags=dict(admissible_in_paper_ledger=False, counted_in_master_gate=False,
                   master_operational_trade=False, financial_order_submitted=False,
                   sol_usd_used=False, open_positions_in_pnl=False))
    bundle['bundle_sha256'] = hrr._sha(bundle)
    return bundle
