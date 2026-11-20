"""closedacct 0.1 -- offline model of the « token account CLOSED » mode for the replay outcomes (prerequisite P-5).

The frozen chain counts the SPL rent of our base token account (2 039 280 lamports, ``statelab.exits.SPL_RENT_LAMPORTS``)
as LOST. The live design (branch ``claude/r01-live-close-base-ata``, commits edc2a1c and 9674826, offline, never armed)
closes that account in a SEPARATE cleanup transaction after a finalized TOTAL sale: optional Burn of a bounded leftover
(MAX_DUST_BURN_ATOMIC = 1 000 000), then CloseAccount; the deposit comes back, it is never sale proceeds; the ONLY cost
is the network fee of that transaction (5 000 lamports + priority, one signer). After MAX_CLEANUP_ATTEMPTS = 3 failed
attempts the account is left open.

This module turns a replay outcome (``statelab.exits.run_rule`` dict) into its net return in the closed mode:

  closed  r = (received - cost - cleanup_fee) / cost          (rent recovered, cleanup fee paid)
  open    r = (received - cost - rent) / (cost + rent)          (= latelab.net_return, the frozen default)
  migrated  -1 in both modes (no sale, so no cleanup: the account is not closed)

CLEANUP FEE (conservative by default): 105 000 lamports = 5 000 base + 100 000 priority, the cost of one transaction of
the frozen chain (``bot.master_v2.w1_run.EXECUTION``); the live default priority is 0 (5 000 lamports), given as a
sensitivity. A failed attempt is modelled by ``failed_attempts`` (each one costs the fee; after 3 the rent is lost).
Admissibility: the mode applies only after a TOTAL sale (all tokens bought are sold, the replay's clock / TP / SL sale);
any other outcome is refused. Nothing here reads a curve state or selects anything.
"""
from statelab.exits import SPL_RENT_LAMPORTS

CLEANUP_FEE_LAMPORTS = 105_000            # conservative: one frozen-chain transaction (5 000 + 100 000)
CLEANUP_FEE_LIVE_DEFAULT_LAMPORTS = 5_000  # live cleanup.py: 5 000 + priority 0
MAX_CLEANUP_ATTEMPTS = 3                  # live cleanup.py


class ClosedAccountError(ValueError):
    pass


def net_return_open(outcome, *, rent=SPL_RENT_LAMPORTS):
    if outcome['migrated']:
        return -1.0
    return (outcome['value'] - outcome['cost'] - rent) / (outcome['cost'] + rent)


def net_return_closed(outcome, *, cleanup_fee=CLEANUP_FEE_LAMPORTS, failed_attempts=0, rent=SPL_RENT_LAMPORTS):
    """Net return when the base token account is closed after the total sale."""
    if outcome['migrated']:
        return -1.0
    if outcome.get('value') is None or outcome.get('tokens') is None:
        raise ClosedAccountError('closed_mode_requires_a_total_sale')
    if type(failed_attempts) is not int or not 0 <= failed_attempts <= MAX_CLEANUP_ATTEMPTS:
        raise ClosedAccountError('failed_attempts_out_of_range')
    if failed_attempts == MAX_CLEANUP_ATTEMPTS:              # left open: rent lost, and every attempt paid
        return (outcome['value'] - outcome['cost'] - rent - failed_attempts * cleanup_fee) / (outcome['cost'] + rent)
    fees = (failed_attempts + 1) * cleanup_fee
    return (outcome['value'] - outcome['cost'] - fees) / outcome['cost']


def rent_effect(outcome, **kwargs):
    """closed - open, in return points (the gain of closing the account)."""
    return net_return_closed(outcome, **kwargs) - net_return_open(outcome)
