"""Controls (a)-(e) and (g): idempotence, resume, limits, stop, chain, liquidity."""
import asyncio
import json

import pytest

from bot.live.route import build_launchlab_order

from dryrun import DryRunHarness, JournalError, Refusal, ShadowPosition, verify_journal
from dryrun.fixtures import cpmm_fixture_request
from dryrun.journal import _digest, canonical

run = asyncio.run
BUY = 100_000_000


def kinds(harness):
    return [record['kind'] for record in harness.journal.records]


def fills(harness):
    return [r for r in harness.journal.records if r['kind'] == 'shadow_fill']


class SimulatedCrash(BaseException):
    """Stands for the process dying: nothing may catch it and carry on."""


def crash_on(target, method, *, when=lambda *args: True):
    original = getattr(target, method)

    def crashing(*args, **kwargs):
        if when(*args):
            raise SimulatedCrash()
        return original(*args, **kwargs)
    setattr(target, method, crashing)


# ---- (a) idempotence ---------------------------------------------------------

def test_duplicate_buy_for_the_same_decision_id_is_refused(open_harness):
    harness = open_harness()
    bought = run(harness.buy('decision-1', BUY))
    for amount in (BUY, 2 * BUY):
        with pytest.raises(Refusal, match='duplicate_decision_id'):
            run(harness.buy('decision-1', amount))
    assert harness.position.quantity_atomic == bought['amount_out']
    assert len(fills(harness)) == 1
    assert harness.journal.records[-1]['reason'] == 'duplicate_decision_id'
    sold = run(harness.sell('decision-2'))
    for repeat in (lambda: harness.sell('decision-2'), lambda: harness.sell('decision-1'),
                   lambda: harness.buy('decision-2', BUY)):
        with pytest.raises(Refusal, match='duplicate_decision_id'):
            run(repeat())
    assert len(fills(harness)) == 2 and harness.wallet_lamports == sold['wallet_after_lamports']


# ---- (b) resume after an interruption ------------------------------------------

@pytest.mark.parametrize('crash_point', ['during_preflight', 'before_fill_commit'])
def test_resume_between_buy_build_and_shadow_fill_does_not_double_position(
        open_harness, crash_point):
    harness = open_harness()
    if crash_point == 'during_preflight':
        crash_on(harness.rpc, 'simulate_transaction')
    else:
        crash_on(harness.journal, 'append', when=lambda kind, *_: kind == 'shadow_fill')
    with pytest.raises(SimulatedCrash):
        run(harness.buy('decision-1', BUY))
    assert 'order_built' in kinds(harness) and 'shadow_fill' not in kinds(harness)

    restarted = open_harness()
    assert restarted.pending == ['decision-1']
    assert restarted.position == ShadowPosition()
    assert restarted.wallet_lamports == restarted.config.simulated_wallet_lamports
    with pytest.raises(Refusal, match='decision_id_reused_with_different_intent'):
        run(restarted.buy('decision-1', 2 * BUY))
    bought = run(restarted.buy('decision-1', BUY))
    assert restarted.pending == []
    with pytest.raises(Refusal, match='duplicate_decision_id'):
        run(restarted.buy('decision-1', BUY))

    again = open_harness()
    assert again.position.quantity_atomic == bought['amount_out']
    assert again.position.principal_lamports == BUY
    assert len(fills(again)) == 1 and kinds(again).count('order_built') == 2


def test_resume_right_after_the_fill_was_committed_counts_it_exactly_once(open_harness):
    harness = open_harness()
    crash_on(harness.bank, 'apply')
    with pytest.raises(SimulatedCrash):
        run(harness.buy('decision-1', BUY))
    assert kinds(harness)[-1] == 'shadow_fill'

    restarted = open_harness()
    committed = fills(restarted)[0]
    assert restarted.position.quantity_atomic == committed['amount_out']
    assert restarted.bank.curve.real_base == committed['curve_after']['real_base']
    with pytest.raises(Refusal, match='duplicate_decision_id'):
        run(restarted.buy('decision-1', BUY))
    assert restarted.position.quantity_atomic == committed['amount_out']
    assert run(restarted.sell('decision-2'))['position_closed'] is True


# ---- (c) loss limit and maximum exposure ---------------------------------------

def test_maximum_exposure_refuses_a_new_buy(open_harness):
    harness = open_harness(max_exposure_lamports=150_000_000)
    bought = run(harness.buy('decision-1', BUY))
    assert harness.position.entry_cost_lamports == BUY + 5000 + 2_039_280
    with pytest.raises(Refusal, match='exposure_limit_exceeded'):
        run(harness.buy('decision-2', BUY))
    assert harness.position.quantity_atomic == bought['amount_out']
    assert kinds(harness)[-1] == 'refusal' and 'decision-2' not in harness.pending
    run(harness.buy('decision-3', 40_000_000))  # still inside the cap


def test_loss_limit_refuses_a_new_buy_once_the_realised_loss_reaches_it(open_harness):
    harness = open_harness(max_loss_lamports=3_000_000)
    run(harness.buy('decision-1', BUY))
    sold = run(harness.sell('decision-2'))
    assert -sold['pnl']['net_pnl_lamports'] >= 3_000_000
    with pytest.raises(Refusal, match='loss_limit_reached'):
        run(harness.buy('decision-3', BUY))
    assert harness.position == ShadowPosition()
    with pytest.raises(Refusal, match='loss_limit_reached'):
        run(open_harness(max_loss_lamports=3_000_000).buy('decision-4', BUY))


# ---- (d) emergency stop ----------------------------------------------------------

def test_emergency_stop_refuses_everything_and_cannot_be_cleared(open_harness):
    harness = open_harness()
    bought = run(harness.buy('decision-1', BUY))
    harness.emergency_stop('operator pressed stop')
    harness.emergency_stop('second press is not a second record')
    assert kinds(harness).count('emergency_stop') == 1

    def refused_everywhere(h):
        for operation in (lambda: run(h.buy('decision-2', BUY)),
                          lambda: run(h.sell('decision-3')),
                          lambda: h.hold([('BUY', BUY)]),
                          lambda: run(h.cpmm_exit_probe(cpmm_fixture_request()))):
            with pytest.raises(Refusal, match='emergency_stop_active'):
                operation()
        assert h.position.quantity_atomic == bought['amount_out']
    refused_everywhere(harness)

    with pytest.raises(AttributeError):
        harness.stopped = False
    assert not [name for name in dir(DryRunHarness) if not name.startswith('__')
                and any(word in name for word in ('clear', 'reset', 'resume', 'unstop', 'restart'))]
    restarted = open_harness()
    assert restarted.stopped is True
    refused_everywhere(restarted)

    # Cutting the stop record out of the file breaks the chain: nothing opens.
    lines = open_harness.path.read_text().splitlines(keepends=True)
    stop = kinds(restarted).index('emergency_stop')
    open_harness.path.write_text(''.join(lines[:stop] + lines[stop + 1:]))
    with pytest.raises(JournalError, match='chain_broken'):
        open_harness()


# ---- (e) hash-chained journal ------------------------------------------------------

def rewrite(path, mutate, *, rechain_from=None):
    """Tamper with the journal file; optionally recompute hashes like a forger."""
    records = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(records)
    if rechain_from is not None:
        for index in range(rechain_from, len(records)):
            record = records[index]
            record['seq'] = index
            record['prev_sha256'] = records[index - 1]['sha256']
            record['sha256'] = _digest({k: v for k, v in record.items() if k != 'sha256'})
    path.write_text(''.join(canonical(record) + '\n' for record in records))


def test_every_record_carries_the_sha256_of_the_previous_one(open_harness):
    harness = open_harness()
    run(harness.buy('decision-1', BUY))
    harness.hold([('BUY', 300_000_000)])
    run(harness.sell('decision-2'))
    records = verify_journal(open_harness.path, expected_head=harness.journal.head)
    assert records == harness.journal.records
    assert records[0]['prev_sha256'] == '0' * 64
    assert all(later['prev_sha256'] == earlier['sha256']
               for earlier, later in zip(records, records[1:]))
    assert len({record['sha256'] for record in records}) == len(records)


@pytest.mark.parametrize('tamper,rechain_from,error', [
    (lambda r: r[3].update(amount_out=r[3]['amount_out'] + 1), None, 'record_3_hash_mismatch'),
    (lambda r: r[3].update(amount_out=r[3]['amount_out'] + 1), 3, 'journal_does_not_replay'),
    (lambda r: r[3].update(sha256='0' * 64), None, 'record_3_hash_mismatch'),
    (lambda r: r.pop(4), None, 'record_4_chain_broken'),
    (lambda r: r.insert(5, dict(r[4])), None, 'record_5_chain_broken'),
    (lambda r: r[2].update(dry_run=False), 2, 'record_2_dry_run_flags_altered'),
    (lambda r: r[3].update(funds_used=True), 3, 'record_3_dry_run_flags_altered'),
    (lambda r: r[5].pop('signed'), 5, 'record_5_dry_run_flags_altered'),
])
def test_tampered_journal_is_detected(open_harness, tamper, rechain_from, error):
    harness = open_harness()
    run(harness.buy('decision-1', BUY))
    harness.hold([('BUY', 300_000_000)])
    run(harness.sell('decision-2'))
    assert kinds(harness)[3] == 'shadow_fill'
    rewrite(open_harness.path, tamper, rechain_from=rechain_from)
    # A forger who recomputes every later hash passes the chain check for a
    # changed amount; the replay on the bank still refuses it.
    if error == 'journal_does_not_replay':
        verify_journal(open_harness.path)
    else:
        with pytest.raises(JournalError, match=error):
            verify_journal(open_harness.path)
    with pytest.raises(JournalError, match=error):
        open_harness()


def test_removed_or_rewritten_tail_needs_a_pinned_head_to_be_seen(open_harness):
    harness = open_harness()
    run(harness.buy('decision-1', BUY))
    head = harness.journal.head
    harness.emergency_stop('stop')
    stopped_head = harness.journal.head
    rewrite(open_harness.path, lambda r: r.pop())  # drop the last record only
    assert verify_journal(open_harness.path, expected_head=head)
    with pytest.raises(JournalError, match='head_differs'):
        verify_journal(open_harness.path, expected_head=stopped_head)


def test_journal_refuses_floats_and_reserved_fields(open_harness):
    journal = open_harness().journal
    for fields in (dict(amount=1.5), dict(nested=dict(values=[1, 2.0])),
                   dict(dry_run=False), dict(sha256='0' * 64), dict(signed=True)):
        with pytest.raises(JournalError):
            journal.append('note', 1, **fields)
    assert len(journal.records) == 1


def test_journal_cannot_be_reopened_on_another_bank_or_configuration(open_harness):
    run(open_harness().buy('decision-1', BUY))
    with pytest.raises(JournalError, match='another_bank_or_configuration'):
        open_harness(max_exposure_lamports=1)


# ---- (g) amounts against pool liquidity ----------------------------------------------

@pytest.mark.parametrize('lamports,reason', [
    (97_000_000_000, 'curve:buy_reaches_fundraising_boundary'),
    (300_000_000_000, 'curve:buy_crosses_migration_boundary'),
])
def test_buy_crossing_the_migration_boundary_is_refused_with_a_reason(
        open_harness, lamports, reason):
    harness = open_harness(simulated_wallet_lamports=10**12, max_exposure_lamports=10**12)
    with pytest.raises(Refusal, match=reason):
        run(harness.buy('decision-1', lamports))
    assert kinds(harness) == ['open', 'refusal'] and harness.position == ShadowPosition()
    assert harness.journal.records[-1]['reason'] == reason
    # The unpatched frozen builder refuses the very same request on its own.
    with pytest.raises(ValueError, match='route_bank_unqualified'):
        build_launchlab_order(**harness._request('decision-1', 'BUY', lamports, 1_000_000))


def test_sell_larger_than_the_curve_can_pay_is_refused_with_a_reason(open_harness):
    harness = open_harness()
    bought = run(harness.buy('decision-1', BUY))
    held = bought['amount_out']
    # Adverse synthetic state: others sell more than was outstanding before our
    # BUY, so the curve no longer holds enough sold tokens to take ours back.
    harness.hold([('SELL', bought['curve_before']['real_base'] + held // 2)])
    assert harness.bank.curve.real_base < held
    with pytest.raises(Refusal, match='curve:sell_exceeds_curve_inventory'):
        run(harness.sell('decision-2'))
    assert harness.position.quantity_atomic == held and harness.pending == []
    assert kinds(harness)[-1] == 'refusal'
    with pytest.raises(ValueError, match='sell_exceeds_observed_outstanding_curve_tokens'):
        build_launchlab_order(**harness._request('decision-2', 'SELL', held, 1_000_000))


@pytest.mark.parametrize('amount', [0, -1, True, 1.5, '100', 2**64])
def test_non_exact_amounts_are_refused_not_rounded(open_harness, amount):
    harness = open_harness()
    with pytest.raises(Refusal, match='curve:invalid_quote_in'):
        run(harness.buy('decision-1', amount))
    with pytest.raises(Refusal, match='curve:'):
        harness.hold([('SELL', amount)])
    assert kinds(harness) == ['open', 'refusal', 'refusal']
