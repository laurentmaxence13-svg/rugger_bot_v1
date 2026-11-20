"""C1 correction of the W1 ledger's control rule (w1aux v7.7; owner decision 20/11: C1-b + D2; R02 3708a816).

DECLARED CHANGE OF ONE CONTROL RULE, nothing else. ``w1aux/ledger.py`` v7.4 (115f3cb5) is NOT modified.

The defect (confirmed on W1 by the step-2 diagnosis): the frozen replay counts 1 x tx_cost at the buy and +1 x at the
sale or the end-of-data mark (bot/market/replay.py l. 224, 239, 256, 290) and hrr._trade sets failed_attempt_costs to
2 x when the result is priced (closed / open_at_end); hrr then RELABELS some priced rows without touching those costs:
``_apply_window`` (-> open_at_window_end), ``_migrated`` (open_at_end -> migrated_unpriced, no note) and
``_exit_after_migration`` (closed -> migrated_unpriced, note ``exit_after_migration``). Ledger v7.4 ``verify_cycle``
(l. 337 and 344-347) expects 1 x for every outcome outside {closed, open_at_end}: a priced-then-relabelled row is
flagged although the replay is right.

RULE REPLACED, only for the outcomes in ``RELABELED`` (open_at_window_end, migrated_unpriced) when an exit rule is
known: the v7.4 expectation ``own = 1`` (tx_costs = 1 x, failed_attempt_costs = 1 x) is replaced by the outcome of the
ledger's OWN holding loop ``derive_hold`` (independent copy, v7.4), re-derived from the bundle's entry:
- re-derived outcome priced (closed / open_at_end): expected tx_costs = 2 x (base + priority), failed = 2 x the failed
  fee, the re-derived ``exit_index`` equal to the bundle's, and the relabelling consistent: migrated_unpriced WITH the
  note ``exit_after_migration`` must come from a re-derived ``closed``, WITHOUT the note from a re-derived
  ``open_at_end``; open_at_window_end from either;
- re-derived outcome not priced: expected 1 x (the v7.4 rule) and the re-derived outcome equal to the bundle's.
The scope stays ``entry_only``: no P&L is verified or counted for these rows (they have none).

Every other outcome, and any row whose v7.4 checks stop before the costs (indices, fee rate, refused buy), keeps
EXACTLY the v7.4 result (tested). Within ``c1_rule()``, ``ledger.verify_cycle`` (called by name from ``_entry_for``)
is this function; outside, v7.4. No network, no result read.
"""
import contextlib
import hashlib
from pathlib import Path

from bot.market.launchlab_curve import CurveError, buy_exact_in
from w1aux import ledger
from w1aux import ledger_parallel as lp

RELABELED = ('open_at_window_end', 'migrated_unpriced')
PRICED = ('closed', 'open_at_end')
COST_CHECKS = ('tx_costs', 'failed_attempt_costs')
RULE = dict(
    replaced='w1aux/ledger.py v7.4 verify_cycle l. 337 and 344-347: own = 1 (tx_costs 1 x, failed 1 x) for every '
             'outcome outside closed/open_at_end',
    by='for open_at_window_end and migrated_unpriced: expected multiplicity from the ledger\'s own derive_hold '
       '(2 x if the re-derived outcome is closed/open_at_end, else 1 x), plus exit_index equality and relabelling '
       'consistency',
    outcomes=list(RELABELED))
_ACTIVE = {'on': False}
_ORIGINAL = {}


class LedgerC1Error(RuntimeError):
    pass


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _reason(check):
    return check.split(':', 1)[0]


def verify_cycle_c1(events, row, params, spec=None):
    """v7.4 verify_cycle, with the C1 multiplicity rule for the relabelled outcomes (see the module docstring)."""
    checks, decomposition, bad = _ORIGINAL['verify_cycle'](events, row, params, spec)
    if row.get('outcome') not in RELABELED or spec is None or 'tx_costs' not in checks:
        return checks, decomposition, bad                          # v7.4 result, unchanged
    k, land = row['decision_index'], row['entry_index']
    rate, _evidence, problem = ledger.derive_fee_rate(events, k, row, params)
    if problem:
        return checks, decomposition, bad
    try:
        tokens = buy_exact_in(events[land].state_after(), row['spent'], rate).amount_out
    except CurveError:
        return checks, decomposition, bad
    rule = (ledger._L1Rule(row['exit_conditions'], spec['options'], params, land, events) if spec['kind'] == 'L1'
            else ledger._V2Rule(spec['rule'], events))
    hold = ledger.derive_hold(events, land, row['spent'], tokens, rate, rule, params['latency_slots'])
    priced = hold['outcome'] in PRICED
    own = 2 if priced else 1
    checks, bad = dict(checks), [b for b in bad if _reason(b) not in COST_CHECKS]

    def check(name, ours, theirs):
        checks[name] = ours == theirs
        if ours != theirs:
            bad.append(f'{name}:ledger={ours}:bundle={theirs}')

    check('failed_attempt_costs', params['failed_attempt_fee_lamports'] * own, row['failed_attempt_costs'])
    check('tx_costs', (params['base_fee_lamports'] + params['priority_fee_lamports']) * own, row['tx_costs'])
    if priced:
        check('exit_index', hold['exit_index'], row['exit_index'])
        note = 'exit_after_migration' in (row.get('notes') or ())
        expected = (('closed',) if note else ('open_at_end',)) if row['outcome'] == 'migrated_unpriced' else PRICED
        check('c1_relabel_consistent', hold['outcome'] in expected, True)
    else:
        check('outcome', hold['outcome'], row['outcome'])
    checks['c1_rule_applied'] = True
    return checks, decomposition, bad


@contextlib.contextmanager
def c1_rule():
    """Within the block, the ledger checks the relabelled outcomes with the C1 rule (declared, see RULE)."""
    if _ACTIVE['on']:
        raise LedgerC1Error('c1_rule_is_not_reentrant')
    lp._check_ledger_module()                                       # ledger.py must be v7.4, unmodified
    _ORIGINAL['verify_cycle'] = ledger.verify_cycle
    if _ORIGINAL['verify_cycle'].__module__ != 'w1aux.ledger':
        _ORIGINAL.clear()
        raise LedgerC1Error('verify_cycle_is_already_replaced')
    _ACTIVE['on'] = True
    ledger.verify_cycle = verify_cycle_c1
    try:
        yield dict(RULE, module='w1aux/ledger_c1.py', sha256=module_sha256())
    finally:
        ledger.verify_cycle = _ORIGINAL['verify_cycle']
        _ACTIVE['on'] = False
        _ORIGINAL.clear()
