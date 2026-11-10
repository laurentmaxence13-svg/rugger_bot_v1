"""Offline dry-run harness for the LaunchLab execution chain.

It rehearses BUY -> hold -> SELL on synthetic pool state with the frozen order
builder and unsigned preflight, and writes a hash-chained journal of shadow
fills. It never signs, never sends and proves nothing about mainnet execution.
"""
from .bank import SyntheticBank
from .costs import CostModel
from .fixture_rpc import FixtureRpc
from .harness import DryRunHarness, HarnessConfig, Refusal, ShadowPosition
from .journal import FLAGS, DryRunJournal, JournalError, verify_journal

__all__ = ['CostModel', 'DryRunHarness', 'DryRunJournal', 'FLAGS', 'FixtureRpc',
           'HarnessConfig', 'JournalError', 'Refusal', 'ShadowPosition',
           'SyntheticBank', 'verify_journal']
