"""C-6 of the CPMM protocol: each mutation of a determining rule makes the core checks fail."""
import base64

import pytest

from cpmmx import curve, events, timeline as cpmm_timeline
from cpmmx.tests.test_cpmmx import BASE, BASE_B58, POOL_B58, QUOTE, logs, swap_payload, tx
from v4sim.engine import Execution

from v4cpmm import bridge
from v4cpmm.tests.test_bridge import FEES, MODEL, OPEN_SLOT, cpmm_pool, run

TWO_TRANSACTIONS = 2 * (5_000 + 100_000)        # base fee + priority fee of the model, twice
STEPS = [(1, 'buy', 10**9), (3, 'sell', 10**11), (4, 'buy', 2 * 10**9), (9, 'sell', 40 * 10**12)]


def core_checks():
    """What must hold: fees are charged, the order lands after its latency, on no future swap, on CPMM events only."""
    line, states = cpmm_pool(STEPS)
    got = run(cpmm=line, protocol_fee_rate=120_000, fund_fee_rate=40_000)
    block = got.cpmm
    base, quote = states[4]
    gross = got.tokens * quote // (base + got.tokens)                    # the curve output with no fee at all
    assert block['status'] == 'sold'
    assert block['landing'] == dict(slot_limit=OPEN_SLOT + 4)
    assert block['received'] == curve.swap_base_input(got.tokens, base, quote, FEES, True).output_amount
    assert block['received'] < gross                                     # a fee was taken
    assert block['total_tx_costs'] == TWO_TRANSACTIONS                   # the buy and the sale, written in full
    assert block['pnl_lamports'] == block['received'] - got.spent - TWO_TRANSACTIONS
    forged = swap_payload(1, 2, 3, 4, True, QUOTE, BASE, 5, 6, True)
    lines = logs(program='Evi1111111111111111111111111111111111111111')
    lines.insert(2, 'Program data: ' + base64.b64encode(forged).decode())
    assert events.transaction_events(tx(1, 0, lines), POOL_B58) == []
    failed = run(cpmm=line, execution=Execution(p_fail=0.999999, max_retries=0, salt='cpmm-only'),
                 protocol_fee_rate=120_000, fund_fee_rate=40_000)
    if failed.cpmm['status'] != 'not_applicable':                        # the curve buy itself may not be included
        assert failed.cpmm['status'] == 'unsold_exit_retries_exhausted' and 'received' not in failed.cpmm


def test_the_unmutated_code_passes_every_core_check():
    core_checks()


def test_mutation_fees_times_zero(monkeypatch):
    monkeypatch.setattr(curve, '_ceil_div', lambda amount, numerator, denominator: 0)
    with pytest.raises(AssertionError):
        core_checks()


def test_mutation_latency_zero(monkeypatch):
    monkeypatch.setattr(bridge, 'settle', lambda result, events_, cpmm, model, **kw: _settle(
        result, events_, cpmm, type(model)(latency_slots=0, fee_rate_estimator=model.fee_rate_estimator,
                                           clock_exit_latency_s=model.clock_exit_latency_s), **kw))
    with pytest.raises(AssertionError):
        core_checks()


_settle = bridge.settle


def test_mutation_reading_a_future_swap(monkeypatch):
    monkeypatch.setattr(cpmm_timeline, 'executed', lambda line, **limit: list(line.swaps))
    with pytest.raises(AssertionError):
        core_checks()


def test_mutation_program_frame_ignored(monkeypatch):
    def every_line(log_messages, program=events.CPMM_PROGRAM):
        return [base64.b64decode(line[len('Program data: '):]) for line in log_messages
                if line.startswith('Program data: ')]
    monkeypatch.setattr(events, 'program_data', every_line)
    with pytest.raises(AssertionError):
        core_checks()


def test_mutation_transaction_costs_forgotten(monkeypatch):
    monkeypatch.setattr(type(MODEL), 'tx_cost', property(lambda self: 0))
    with pytest.raises(AssertionError):
        core_checks()
