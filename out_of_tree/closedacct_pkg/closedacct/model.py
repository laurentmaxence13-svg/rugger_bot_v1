"""closedacct 0.2 -- offline model of the « token account CLOSED » mode for the replay outcomes (prerequisite P-5;
0.2 = R02 corrections 1 and 2: one denominator, the 0.1 SOL STAKE, in both modes; failed attempts frozen at 0).

The frozen chain counts the SPL rent of our base token account (2 039 280 lamports, ``statelab.exits.SPL_RENT_LAMPORTS``)
as LOST. The live design (branch ``claude/r01-live-close-base-ata``, commits edc2a1c and 9674826, offline, never armed)
closes that account in a SEPARATE cleanup transaction after a finalized TOTAL sale: optional Burn of a bounded leftover
(MAX_DUST_BURN_ATOMIC = 1 000 000), then CloseAccount; the deposit comes back, it is never sale proceeds; the ONLY cost
is the network fee of that transaction (5 000 lamports + priority, one signer). After MAX_CLEANUP_ATTEMPTS = 3 failed
attempts the account is left open.

RETURN on the STAKE (0.1 SOL), the same denominator in both modes (Dossier B section 4), so that the modes and the cost
decomposition are on one base:

  open    r = (received - cost - rent) / stake
  closed  r = (received - cost - (failed_attempts + 1) x cleanup_fee) / stake
  left open after 3 failures   r = (received - cost - rent - 3 x cleanup_fee) / stake
  migrated  received = 0 and no sale, so no cleanup: r = (- cost - rent) / stake in both modes

``cost`` = stake + the transaction costs of the frozen chain (run_rule's ``cost``). FROZEN HYPOTHESIS: failed_attempts
= 0; sensitivity: 1 (``SENSITIVITY_FAILED_ATTEMPTS``). CLEANUP FEE, conservative: 105 000 lamports = 5 000 base +
100 000 priority (one transaction of the frozen chain); the live default (5 000) is a sensitivity. Admissibility: only
after a TOTAL sale; any other outcome is refused. Nothing here reads a curve state or selects anything.
"""
from statelab.exits import SPL_RENT_LAMPORTS
from statelab.study import STAKE_LAMPORTS

CLEANUP_FEE_LAMPORTS = 105_000            # conservative: one frozen-chain transaction (5 000 + 100 000)
CLEANUP_FEE_LIVE_DEFAULT_LAMPORTS = 5_000  # live cleanup.py: 5 000 + priority 0
MAX_CLEANUP_ATTEMPTS = 3                  # live cleanup.py
FROZEN_FAILED_ATTEMPTS = 0                # R02 correction 2
SENSITIVITY_FAILED_ATTEMPTS = 1


class ClosedAccountError(ValueError):
    pass


def _received(outcome):
    if outcome['migrated']:
        return 0
    if outcome.get('value') is None or outcome.get('tokens') is None:
        raise ClosedAccountError('closed_mode_requires_a_total_sale')
    return outcome['value']


def net_return_open(outcome, *, rent=SPL_RENT_LAMPORTS, stake=STAKE_LAMPORTS):
    return (_received(outcome) - outcome['cost'] - rent) / stake


def net_return_closed(outcome, *, cleanup_fee=CLEANUP_FEE_LAMPORTS, failed_attempts=FROZEN_FAILED_ATTEMPTS,
                      rent=SPL_RENT_LAMPORTS, stake=STAKE_LAMPORTS):
    """Net return on the stake when the base token account is closed after the total sale."""
    received = _received(outcome)
    if outcome['migrated']:                                    # no sale, so no cleanup: the rent is lost
        return net_return_open(outcome, rent=rent, stake=stake)
    if type(failed_attempts) is not int or not 0 <= failed_attempts <= MAX_CLEANUP_ATTEMPTS:
        raise ClosedAccountError('failed_attempts_out_of_range')
    if failed_attempts == MAX_CLEANUP_ATTEMPTS:              # left open: rent lost, and every attempt paid
        return (received - outcome['cost'] - rent - failed_attempts * cleanup_fee) / stake
    return (received - outcome['cost'] - (failed_attempts + 1) * cleanup_fee) / stake


def rent_effect(outcome, **kwargs):
    """closed - open, in return points on the stake (the gain of closing the account)."""
    return net_return_closed(outcome, **kwargs) - net_return_open(outcome)
