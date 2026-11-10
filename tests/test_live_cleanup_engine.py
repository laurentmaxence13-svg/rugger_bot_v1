"""The base-account cleanup through the real engine and journal, offline only.

Fake signer, fake send and fake finality as in test_live_engine. The finalized
fixture MODELS the closure (account absent from postTokenBalances, lamports
credited to the wallet). Nothing here is a chain execution.
"""
import base64
from dataclasses import replace
import hashlib
import json
import sqlite3
import struct

import pytest

from bot.live.cleanup import (MAX_CLEANUP_ATTEMPTS, MAX_DUST_BURN_ATOMIC,
                              PreparedBaseAccountCleanup, build_base_account_cleanup)
from bot.live.engine import ExecutionEngine
from bot.live.journal import ExecutionJournal
from bot.live.route import (TOKEN_PROGRAM, associated_token_address,
                            build_launchlab_order, ephemeral_wsol_address)
from bot.live.safety import AdmissionRequest, HealthEvidence, Mode, arm, enable
from bot.live.submission import BoundSubmissionGuard
from bot.p3.certification import PROGRAM, _encode
from test_live_cleanup_base_account import RENT, cleanup_payload, cleanup_request, totally_sold
from test_live_engine import ENDPOINT, GENESIS, FakeRpc, FakeSignatureVerifier, run
from test_live_wire_route import route_request

FEE = 5001
BALANCE = 10_000_000_000


def authorize(engine, **changes):
    """Owner scope that explicitly lists the Token program for the cleanup."""
    changes.setdefault('allowed_programs', (PROGRAM, TOKEN_PROGRAM))
    env = replace(engine.envelope, **changes)
    engine.envelope = env
    engine.arming = enable(env, arm(env, now_ms=1000, arm_receipt='fixture-arm'),
                           now_ms=1050, enable_receipt='fixture-enable')


def sold(tmp_path, *, third_party_dust=0):
    engine, buy, sell, sale, rpc, signer = totally_sold(tmp_path, third_party_dust=third_party_dust)
    authorize(engine)
    trade_evidence = engine.evidence_provider

    async def evidence(decision, prepared):
        if type(prepared) is not PreparedBaseAccountCleanup:
            return await trade_evidence(decision, prepared)
        now = engine.clock_ms()
        parameters = json.loads(prepared.rebuild_request_json)
        request = AdmissionRequest(decision_id=decision, side='cleanup',
            wallet=prepared.user, cluster='mainnet-beta', genesis_hash=GENESIS,
            rpc_endpoint_sha256=ENDPOINT, program_id=TOKEN_PROGRAM, mint=prepared.mint,
            pool=buy.pool, quote_source_id='ISOLATED-fixture-bank',
            quote_payload_sha256=prepared.source_account_digest,
            route_message_sha256=hashlib.sha256(prepared.transaction.message).hexdigest(),
            quote_received_at_ms=prepared.source_available_at_ms,
            risk_checked_at_ms=now, quote_context_slot=prepared.source_slot,
            observed_bank_slot=prepared.source_slot, amount_in_atomic=0,
            quote_input_atomic=0, quote_output_atomic=0, minimum_out_atomic=0,
            network_fee_upper_lamports=prepared.network_fee_upper_lamports,
            priority_fee_lamports=(parameters['compute_unit_limit'] * parameters['priority_fee_micro_lamports'] + 999999)//1000000,
            compute_units=parameters['compute_unit_limit'], slippage_bps=0,
            price_impact_bps=0, rent_deposit_upper_lamports=0, exit_capacity_atomic=0,
            identity_verified=True, route_verified=True, costs_known=True, anti_rug_reasons=())
        health = HealthEvidence(observed_at_ms=now, scanner_heartbeat_at_ms=now,
            rpc_success_at_ms=now, websocket_heartbeat_at_ms=now,
            scanner_connected=True, rpc_connected=True, websocket_connected=True,
            rpc_genesis_hash=GENESIS, rpc_endpoint_sha256=ENDPOINT, clock_offset_ms=0)
        return request, health

    async def cleanup_fee(message):
        return FEE

    engine.evidence_provider = evidence
    rpc.get_fee_for_message = cleanup_fee
    rpc.simulation = dict(err=None, unitsConsumed=9000, context_slot=1300)
    return engine, buy, sell, rpc, signer


def start(engine, buy, decision='fixture-cleanup-0', *, leftover=0, built=None, **changes):
    def build(bound):
        prepared = build_base_account_cleanup(**cleanup_request(
            leftover, decision=decision, **dict(dict(max_dust_burn_atomic=bound), **changes)))
        if built is not None:
            built.append(prepared)
        return prepared
    return run(engine.cleanup(decision, mint=buy.mint, wallet=buy.user, build=build))


def settle(engine, rpc, decision, prepared, *, error=None):
    rpc.status = dict(confirmationStatus='finalized', err=error, slot=1400)
    rpc.tx = cleanup_payload(prepared, engine.result(decision)['signature'], error=error)
    return run(engine.recover(decision))


def ledger(engine):
    journal = engine.journal
    return (dict(journal.con.execute('SELECT * FROM positions').fetchone()),
            [dict(r) for r in journal.con.execute('SELECT * FROM daily ORDER BY day')],
            journal.risk_snapshot(at=engine.clock_ms(), wallet_balance_lamports=BALANCE))


def audit_kinds(journal):
    return [json.loads(r[0])['kind'] for r in journal.con.execute('SELECT event_json FROM audit ORDER BY sequence')]


def test_cleanup_end_to_end_closes_account_releases_rent_and_never_touches_proceeds(tmp_path):
    engine, buy, sell, rpc, signer = sold(tmp_path)
    journal = engine.journal
    position, daily, risk = ledger(engine)
    assert position['locked_rent_lamports'] == RENT == risk.capital_at_risk_lamports
    sale_record = journal.get('fixture-total-sell')['reconciliation_json']
    guard, guarded, built = BoundSubmissionGuard(engine), [], []
    send = rpc.send_transaction

    async def guarded_send(raw):
        guarded.append(guard(raw))
        return await send(raw)
    rpc.send_transaction = guarded_send

    def build(bound):
        # D-a: the bound and the in-flight marker are durable BEFORE the build.
        intent = journal.cleanup('fixture-cleanup-0')
        assert intent['outcome'] == 'IN_FLIGHT' and intent['attempt'] == 1
        assert bound == intent['max_dust_burn_atomic'] == MAX_DUST_BURN_ATOMIC == 1_000_000
        assert audit_kinds(journal)[-1] == 'cleanup_intent'
        assert journal.get('fixture-cleanup-0') is None
        built.append(build_base_account_cleanup(**cleanup_request(max_dust_burn_atomic=bound)))
        return built[0]
    result = run(engine.cleanup('fixture-cleanup-0', mint=buy.mint, wallet=buy.user, build=build))
    assert result['execution']['state'] == 'SUBMITTED' and guarded == [True]
    assert signer.calls == 3 and len(rpc.send_calls) == 3
    row = journal.get('fixture-cleanup-0')
    assert not guard(row['signed_raw'])  # no second transmission of the same bytes
    record = json.loads(row['order_json'])
    assert (record['route_kind'], record['side']) == ('BASE_ACCOUNT_CLEANUP', 'CLEANUP')
    # Not a trade: only the fee upper bound is reserved, no notional, no inventory.
    assert (row['reserved_lamports'], row['reserved_atomic']) == (FEE, 0)
    # In flight, then merely confirmed: the rent is still locked.
    rpc.status = dict(confirmationStatus='confirmed', err=None, slot=1400)
    assert run(engine.recover('fixture-cleanup-0'))['state'] == 'CONFIRMED'
    assert ledger(engine)[0] == position and ledger(engine)[1] == daily
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'IN_FLIGHT'

    final = settle(engine, rpc, 'fixture-cleanup-0', built[0])
    assert final['state'] == 'RECONCILED'
    reconciliation = final['reconciliation']
    assert reconciliation['account_closed'] is True
    assert reconciliation['rent_recovered_lamports'] == RENT
    assert (reconciliation['gross_output_lamports'], reconciliation['sale_proceeds_lamports'],
            reconciliation['market_pnl_lamports']) == (0, 0, 0)
    after_position, after_daily, after_risk = ledger(engine)
    # Position closed; locked rent released only now.
    assert after_position == dict(position, locked_rent_lamports=0)
    assert after_position['quantity_atomic'] == 0 and after_risk.capital_at_risk_lamports == 0
    # Daily P&L = proceeds - costs (three fees); the rent is in neither side.
    assert after_daily[0]['realized_pnl'] == sell.expected_output - buy.input_amount - 2 * 5002 - FEE
    assert after_daily[0]['realized_pnl'] == daily[0]['realized_pnl'] - FEE
    assert after_daily[0]['realized_loss'] == daily[0]['realized_loss'] + FEE
    assert after_daily[0]['spent'] == daily[0]['spent'] + FEE == buy.input_amount + 2 * 5002 + RENT + FEE
    assert journal.get('fixture-total-sell')['reconciliation_json'] == sale_record
    cleanup = journal.cleanup('fixture-cleanup-0')
    assert (cleanup['outcome'], cleanup['fee_lamports'], cleanup['burned_atomic']) == ('CLOSED', FEE, 0)
    assert cleanup['rent_released_lamports'] == cleanup['rent_recovered_lamports'] == RENT
    assert json.loads(cleanup['alerts_json']) == []
    assert journal.cleanup_costs(buy.mint) == dict(cleanup_fee_lamports=FEE,
        rent_paid_lamports=RENT, rent_recovered_lamports=RENT,
        rent_still_locked_lamports=0, net_rent_cost_lamports=0, alerts=[])
    assert after_risk.consecutive_failures == risk.consecutive_failures == 0
    # Idempotent: neither recovery nor a duplicate request re-signs or re-sends.
    run(engine.recover('fixture-cleanup-0'))
    again = run(engine.cleanup('fixture-cleanup-0', mint=buy.mint, wallet=buy.user, build=None))
    assert again['cleanup'] == cleanup and again['execution'] == final
    assert signer.calls == 3 and len(rpc.send_calls) == 3 and ledger(engine)[1] == after_daily
    assert journal.verify_audit() != '0' * 64


def test_cleanup_on_a_later_day_books_only_its_fee_and_never_rewrites_the_buy_day(tmp_path):
    engine, buy, _, rpc, _ = sold(tmp_path)
    buy_day = ledger(engine)[1]
    later = 86_400_000 + 1100
    engine.clock_ms = lambda: later
    authorize(engine, expires_at_ms=later + 10_000)
    built = []
    start(engine, buy, built=built, available_at_ms=later - 100, decision_at_ms=later)
    settle(engine, rpc, 'fixture-cleanup-0', built[0])
    days = ledger(engine)[1]
    assert days[0] == buy_day[0] and days[0]['day'] == '1970-01-01'
    assert days[1] == dict(day='1970-01-02', spent=FEE, realized_loss=FEE, realized_pnl=-FEE)
    assert engine.journal.cleanup_costs(buy.mint)['net_rent_cost_lamports'] == 0


def test_foreign_deposit_is_burned_alerted_and_above_the_bound_the_account_stays_open(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path, third_party_dust=1)
    journal = engine.journal
    position, daily, _ = ledger(engine)
    # Above the journaled bound: no burn, no close, nothing built, signed or sent.
    with pytest.raises(ValueError, match='leftover_exceeds_retained_dust_bound_account_left_open'):
        start(engine, buy, 'fixture-cleanup-big', leftover=MAX_DUST_BURN_ATOMIC + 1)
    refused = journal.cleanup('fixture-cleanup-big')
    assert refused['outcome'] == 'NOT_SENT' and json.loads(refused['alerts_json']) == ['foreign_deposit']
    assert refused['max_dust_burn_atomic'] == 1_000_000 and journal.get('fixture-cleanup-big') is None
    assert signer.calls == 2 and ledger(engine)[:2] == (position, daily)
    costs = journal.cleanup_costs(buy.mint)
    assert costs['net_rent_cost_lamports'] == costs['rent_still_locked_lamports'] == RENT
    # The builder cannot raise the bound afterwards.
    with pytest.raises(ValueError, match='journaled_cleanup_intent_required_before_build'):
        start(engine, buy, 'fixture-cleanup-raised', leftover=1, max_dust_burn_atomic=MAX_DUST_BURN_ATOMIC + 1)
    assert journal.cleanup('fixture-cleanup-raised')['outcome'] == 'NOT_SENT' and signer.calls == 2
    # Within the bound: burned, closed, alerted; still never proceeds.
    built = []
    assert start(engine, buy, leftover=1, built=built)['execution']['state'] == 'SUBMITTED'
    final = settle(engine, rpc, 'fixture-cleanup-0', built[0])
    cleanup = journal.cleanup('fixture-cleanup-0')
    assert (cleanup['outcome'], cleanup['burned_atomic']) == ('CLOSED', 1)
    assert json.loads(cleanup['alerts_json']) == ['foreign_deposit']
    assert final['reconciliation']['sale_proceeds_lamports'] == 0
    assert ledger(engine)[1][0]['realized_pnl'] == daily[0]['realized_pnl'] - FEE
    assert journal.cleanup_costs(buy.mint)['alerts'] == ['foreign_deposit']
    journal.verify_audit()


def rebuy(decision):
    request = route_request(has_ata=True)
    wallet, mint = request['wallet'], request['mint']
    request['accounts'].pop(ephemeral_wsol_address(wallet, request['decision_id'])[0])
    request['accounts'][ephemeral_wsol_address(wallet, decision)[0]] = None
    request['decision_id'] = decision
    account = request['accounts'][associated_token_address(wallet, mint)]
    raw = bytearray(base64.b64decode(account['data'][0]))
    struct.pack_into('<Q', raw, 64, 0)
    account['data'][0] = base64.b64encode(raw).decode()
    return build_launchlab_order(**request)


def test_second_cleanup_and_any_trade_of_the_mint_are_refused_while_one_is_in_flight(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    journal = engine.journal
    built = []
    assert start(engine, buy, built=built)['execution']['state'] == 'SUBMITTED'
    called = []
    with pytest.raises(ValueError, match='cleanup_refused:unsettled_order_for_mint'):
        run(engine.cleanup('fixture-cleanup-1', mint=buy.mint, wallet=buy.user, build=called.append))
    assert journal.cleanup('fixture-cleanup-1') is None and not called
    # The account may close under a new entry: no trade is reserved meanwhile.
    rpc.get_fee_for_message = FakeRpc.get_fee_for_message.__get__(rpc)
    rpc.simulation = dict(err=None, unitsConsumed=150000, context_slot=1300)
    with pytest.raises(ValueError, match='base_account_cleanup_in_flight_for_mint'):
        run(engine.execute('fixture-rebuy', rebuy('fixture-rebuy')))
    assert signer.calls == 3 and len(rpc.send_calls) == 3
    journal.release_unsent('fixture-rebuy', 1100, 'fixture_cancel')
    settle(engine, rpc, 'fixture-cleanup-0', built[0])
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'CLOSED'


def test_intent_without_an_order_blocks_a_second_cleanup_until_recovery_settles_it(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    journal = engine.journal
    # Crash right after the durable intent: nothing was built, signed or sent.
    journal.begin_cleanup('fixture-cleanup-0', 1100, mint=buy.mint, wallet=buy.user,
                          max_dust_burn_atomic=MAX_DUST_BURN_ATOMIC)
    with pytest.raises(ValueError, match='cleanup_refused:cleanup_already_in_flight_for_position'):
        start(engine, buy, 'fixture-cleanup-1')
    with pytest.raises(ValueError, match='cleanup_decision_id_already_used'):
        journal.begin_cleanup('fixture-cleanup-0', 1100, mint=buy.mint, wallet=buy.user,
                              max_dust_burn_atomic=MAX_DUST_BURN_ATOMIC)
    assert run(engine.recover('fixture-cleanup-0')) is None
    settled = journal.cleanup('fixture-cleanup-0')
    assert (settled['outcome'], settled['reason']) == ('NOT_SENT', 'recovered_before_submission_marker')
    assert start(engine, buy, 'fixture-cleanup-1')['execution']['state'] == 'SUBMITTED'
    assert signer.calls == 3 and len(rpc.send_calls) == 3


def test_three_failed_cleanups_leave_the_account_open_and_a_fourth_is_refused(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    journal = engine.journal
    position, daily, _ = ledger(engine)
    error = {'InstructionError': [2, {'Custom': 11}]}  # e.g. tokens deposited meanwhile
    for attempt in range(MAX_CLEANUP_ATTEMPTS):
        built, decision = [], f'fixture-cleanup-{attempt}'
        started = start(engine, buy, decision, built=built,
                        recent_blockhash=_encode(bytes([40 + attempt]) * 32))
        assert started['execution']['state'] == 'SUBMITTED'
        assert started['cleanup']['attempt'] == attempt + 1
        assert settle(engine, rpc, decision, built[0], error=error)['state'] == 'RECONCILED'
        cleanup = journal.cleanup(decision)
        assert (cleanup['outcome'], cleanup['fee_lamports']) == ('FAILED', FEE)
        assert cleanup['rent_recovered_lamports'] == cleanup['rent_released_lamports'] == 0
        assert json.loads(cleanup['alerts_json']) == (
            ['cleanup_attempts_exhausted_account_left_open'] if attempt == 2 else [])
    assert MAX_CLEANUP_ATTEMPTS == 3 and signer.calls == 5 and len(rpc.send_calls) == 5
    called = []
    with pytest.raises(ValueError, match='cleanup_refused:attempt_limit_reached_account_left_open'):
        run(engine.cleanup('fixture-cleanup-3', mint=buy.mint, wallet=buy.user, build=called.append))
    assert journal.cleanup('fixture-cleanup-3') is None and not called and signer.calls == 5
    # Account left open: rent still locked and a full cost; only fees were paid.
    after_position, after_daily, risk = ledger(engine)
    assert after_position == position and risk.capital_at_risk_lamports == RENT
    assert after_daily[0]['realized_pnl'] == daily[0]['realized_pnl'] - 3 * FEE
    assert after_daily[0]['realized_loss'] == daily[0]['realized_loss'] + 3 * FEE
    assert after_daily[0]['spent'] == daily[0]['spent'] + 3 * FEE
    assert journal.cleanup_costs(buy.mint) == dict(cleanup_fee_lamports=3 * FEE,
        rent_paid_lamports=RENT, rent_recovered_lamports=0, rent_still_locked_lamports=RENT,
        net_rent_cost_lamports=RENT, alerts=['cleanup_attempts_exhausted_account_left_open'])
    # A third party can force these failures: they never feed the trade streak.
    assert risk.consecutive_failures == 0
    journal.verify_audit()


def test_kill_latch_blocks_the_cleanup_before_the_intent_and_before_the_send(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    journal = engine.journal
    signer.after_sign = lambda: journal.kill('fixture emergency', 1100)
    with pytest.raises(ValueError, match='submission_admission_refused:persistent_kill_switch'):
        start(engine, buy)
    assert signer.calls == 3 and len(rpc.send_calls) == 2
    row = journal.get('fixture-cleanup-0')
    assert (row['state'], row['reserved_lamports']) == ('UNSENT_CANCELLED', 0)
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'NOT_SENT'
    # The latch has no reset: not even an intent can be journaled any more.
    signer.after_sign = None
    with pytest.raises(ValueError, match='cleanup_refused:persistent_kill_switch_active'):
        start(engine, buy, 'fixture-cleanup-1')
    assert journal.cleanup('fixture-cleanup-1') is None
    assert signer.calls == 3 and len(rpc.send_calls) == 2 and journal.killed
    assert ledger(engine)[0]['locked_rent_lamports'] == RENT


@pytest.mark.parametrize('case', ['prepared', 'armed_mode', 'armed_only_receipt',
                                  'no_authority', 'token_program_not_authorized',
                                  'expired', 'research'])
def test_cleanup_is_not_submitted_unless_armed_and_enabled_like_any_submission(tmp_path, case):
    engine, buy, _, rpc, signer = sold(tmp_path)
    journal = engine.journal
    refusal = None
    if case == 'prepared': engine.mode = Mode.LIVE_PREPARED
    if case == 'armed_mode': engine.mode = Mode.LIVE_ARMED
    if case == 'research': engine.mode = Mode.RESEARCH
    if case == 'armed_only_receipt':
        engine.arming = arm(engine.envelope, now_ms=1000, arm_receipt='fixture-arm')
        refusal = 'submission_admission_refused:explicit_arm_and_enable_required'
    if case == 'no_authority':
        engine.arming = None
        refusal = 'explicit_authorization_and_fresh_evidence_required'
    if case == 'token_program_not_authorized':
        authorize(engine, allowed_programs=(PROGRAM,))
        refusal = 'submission_admission_refused:program_not_authorized'
    if case == 'expired':
        authorize(engine, expires_at_ms=1100)
        refusal = 'submission_admission_refused:authorization_not_current'
    if refusal:
        with pytest.raises(ValueError, match=refusal):
            start(engine, buy)
    else:
        assert start(engine, buy)['execution']['state'] == 'UNSENT_CANCELLED'
    assert signer.calls == 2 and len(rpc.send_calls) == 2
    row = journal.get('fixture-cleanup-0')
    assert (row['state'], row['reserved_lamports'], row['signature']) == ('UNSENT_CANCELLED', 0, None)
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'NOT_SENT'
    assert ledger(engine)[0]['locked_rent_lamports'] == RENT
    assert not journal.killed
    journal.verify_audit()


def test_fee_above_the_envelope_cap_blocks_the_cleanup(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    assert engine.envelope.max_network_fee_lamports == 10000
    built = []
    with pytest.raises(ValueError, match='submission_admission_refused:fee_limit'):
        start(engine, buy, built=built, priority_fee_micro_lamports=300_000,
              max_priority_fee_lamports=6000)
    assert built[0].network_fee_upper_lamports == 11000
    assert signer.calls == 2 and len(rpc.send_calls) == 2
    assert engine.journal.cleanup('fixture-cleanup-0')['outcome'] == 'NOT_SENT'
    # The total fee cap alone also blocks, with the priority cap satisfied.
    authorize(engine, max_network_fee_lamports=5000, max_priority_fee_lamports=1000)
    with pytest.raises(ValueError, match='submission_admission_refused:fee_limit'):
        start(engine, buy, 'fixture-cleanup-1')
    # The bank's fee for the message above the reserved bound also refuses.
    authorize(engine)
    rpc.get_fee_for_message = FakeRpc.get_fee_for_message.__get__(rpc)  # 5002 > 5001
    with pytest.raises(ValueError, match='causal_message_fee_unknown_stale_or_above_reserved_bound'):
        start(engine, buy, 'fixture-cleanup-2')
    assert signer.calls == 2 and len(rpc.send_calls) == 2


def test_cleanup_evidence_must_be_the_exact_zero_notional_request(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    honest = engine.evidence_provider

    async def as_a_sale(decision, prepared):
        request, health = await honest(decision, prepared)
        return replace(request, side='sell', amount_in_atomic=1, quote_input_atomic=1,
                       quote_output_atomic=1, minimum_out_atomic=1), health
    engine.evidence_provider = as_a_sale
    with pytest.raises(ValueError, match='admission_evidence_not_bound_to_exact_prepared_order'):
        start(engine, buy)

    async def with_notional(decision, prepared):
        request, health = await honest(decision, prepared)
        return replace(request, amount_in_atomic=1, quote_input_atomic=1), health
    engine.evidence_provider = with_notional
    with pytest.raises(ValueError, match='cleanup_carries_no_notional'):
        start(engine, buy, 'fixture-cleanup-1')
    assert signer.calls == 2 and len(rpc.send_calls) == 2
    # The trade entry point still refuses the type; the lifecycle needs an intent.
    cleanup = build_base_account_cleanup(**cleanup_request(decision='fixture-cleanup-2'))
    with pytest.raises(ValueError, match='explicit_supported_execution_route_required'):
        run(engine.execute('fixture-cleanup-2', cleanup))
    with pytest.raises(ValueError, match='journaled_cleanup_intent_required_before_build'):
        run(engine._lifecycle('fixture-cleanup-2', cleanup))
    assert engine.journal.get('fixture-cleanup-2') is None


def test_crash_between_write_ahead_and_send_is_ambiguous_like_any_other_order(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    path = tmp_path / 'private-live.sqlite'
    built, rpc.status = [], None

    async def process_dies(raw):
        rpc.send_calls.append(raw)
        engine.journal.close()  # nothing after the write-ahead marker is recorded
        raise TimeoutError('isolated fixture crash')
    rpc.send_transaction = process_dies
    with pytest.raises(sqlite3.ProgrammingError):
        start(engine, buy, built=built)
    journal = ExecutionJournal(path)
    row = journal.get('fixture-cleanup-0')
    assert row['state'] == 'SUBMITTING' and row['reserved_lamports'] == FEE and row['signed_raw']
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'IN_FLIGHT'
    restored = ExecutionEngine(journal=journal, rpc=rpc, verifier=FakeSignatureVerifier(),
                               clock_ms=lambda: 1100)
    with pytest.raises(ValueError, match='cleanup_refused:unsettled_order_for_mint'):
        run(restored.cleanup('fixture-cleanup-1', mint=buy.mint, wallet=buy.user, build=None))
    # Unknown on chain and still within its lifetime: nothing is released.
    assert run(restored.recover('fixture-cleanup-0'))['state'] == 'SUBMITTING'
    assert journal.get('fixture-cleanup-0')['reserved_lamports'] == FEE
    # Never re-sent; once expired the history is unknown: kill, keep reservation.
    rpc.height = 5001
    assert run(restored.recover('fixture-cleanup-0'))['state'] == 'EXPIRED_UNKNOWN'
    assert journal.killed and journal.get('fixture-cleanup-0')['reserved_lamports'] == FEE
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'IN_FLIGHT'
    assert journal.con.execute('SELECT locked_rent_lamports FROM positions').fetchone()[0] == RENT
    assert signer.calls == 3 and len(rpc.send_calls) == 3
    # It had landed after all: finality still reconciles the exact closure.
    final = settle(restored, rpc, 'fixture-cleanup-0', built[0])
    assert final['state'] == 'RECONCILED' and journal.cleanup('fixture-cleanup-0')['outcome'] == 'CLOSED'
    assert journal.con.execute('SELECT locked_rent_lamports FROM positions').fetchone()[0] == 0
    assert journal.killed  # no reset
    journal.verify_audit(); journal.close()


def test_ambiguous_send_and_unsubmitted_reservation_recover_like_other_orders(tmp_path):
    engine, buy, _, rpc, signer = sold(tmp_path)
    journal = engine.journal
    # Reserved, then a crash before the write-ahead marker: provably unsent.
    journal.begin_cleanup('fixture-cleanup-0', 1100, mint=buy.mint, wallet=buy.user,
                          max_dust_burn_atomic=MAX_DUST_BURN_ATOMIC)
    from bot.live.engine import cleanup_record
    cleanup = build_base_account_cleanup(**cleanup_request())
    journal.create('fixture-cleanup-0', cleanup_record(cleanup, buy.pool), 1100)
    journal.transition('fixture-cleanup-0', ('PREPARED',), 'SIMULATED', 1100)
    journal.reserve('fixture-cleanup-0', 1100, wallet_balance_lamports=BALANCE,
        max_capital_lamports=1, max_open_positions=1, max_in_flight_orders=3,
        max_daily_spend_lamports=2_000_000_000, max_daily_loss_lamports=1)
    assert journal.get('fixture-cleanup-0')['reserved_lamports'] == FEE
    assert run(engine.recover('fixture-cleanup-0'))['state'] == 'UNSENT_CANCELLED'
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'NOT_SENT'
    assert signer.calls == 2 and len(rpc.send_calls) == 2
    # Ambiguous send: UNCERTAIN, killed, reservation kept, intent still in flight.
    rpc.send_error = TimeoutError('isolated fixture timeout')
    result = start(engine, buy, 'fixture-cleanup-1', recent_blockhash=_encode(bytes([41]) * 32))
    assert result['execution']['state'] == 'UNCERTAIN' and journal.killed
    assert result['cleanup']['outcome'] == 'IN_FLIGHT'
    assert journal.get('fixture-cleanup-1')['reserved_lamports'] == FEE
    assert ledger(engine)[0]['locked_rent_lamports'] == RENT


def test_reservation_rechecks_eligibility_and_limits_in_its_own_transaction(tmp_path):
    from bot.live.engine import cleanup_record, order_record
    engine, buy, _, rpc, signer = sold(tmp_path)
    journal = engine.journal
    limits = dict(wallet_balance_lamports=BALANCE, max_capital_lamports=1,
        max_open_positions=1, max_in_flight_orders=3,
        max_daily_spend_lamports=2_000_000_000, max_daily_loss_lamports=1)
    journal.begin_cleanup('fixture-cleanup-0', 1100, mint=buy.mint, wallet=buy.user,
                          max_dust_burn_atomic=MAX_DUST_BURN_ATOMIC)
    cleanup = build_base_account_cleanup(**cleanup_request())
    journal.create('fixture-cleanup-0', cleanup_record(cleanup, buy.pool), 1100)
    journal.transition('fixture-cleanup-0', ('PREPARED',), 'SIMULATED', 1100)
    # Between simulation and reservation the position is no longer closed.
    journal.con.execute('UPDATE positions SET quantity_atomic=1')
    with pytest.raises(ValueError, match='inventory_not_bound_to_audit'):
        journal.reserve('fixture-cleanup-0', 1100, **limits)
    journal.con.execute('UPDATE positions SET quantity_atomic=0')
    # ... or another order of the mint appeared: refused by assert_cleanup_allowed.
    journal.create('fixture-rebuy', order_record(rebuy('fixture-rebuy')), 1100)
    with pytest.raises(ValueError, match='cleanup_refused:unsettled_order_for_mint'):
        journal.reserve('fixture-cleanup-0', 1100, **limits)
    journal.release_unsent('fixture-rebuy', 1100, 'fixture_cancel')
    for name, value, reason in (('max_in_flight_orders', 0, 'in_flight_order_limit'),
                                ('wallet_balance_lamports', FEE - 1, 'insufficient_free_lamports'),
                                ('max_daily_spend_lamports', FEE, 'daily_spend_reservation_limit')):
        with pytest.raises(ValueError, match=reason):
            journal.reserve('fixture-cleanup-0', 1100, **dict(limits, **{name: value}))
    assert journal.get('fixture-cleanup-0')['state'] == 'SIMULATED'
    # No notional: capital, open-position and daily-loss trade limits are not consumed.
    journal.reserve('fixture-cleanup-0', 1100, **limits)
    row = journal.get('fixture-cleanup-0')
    assert (row['state'], row['reserved_lamports'], row['reserved_atomic']) == ('RESERVED', FEE, 0)


@pytest.mark.parametrize('corrupt', ['signature', 'message', 'fee', 'not_closed', 'cash', 'record'])
def test_finalized_cleanup_that_does_not_reconcile_kills_and_releases_nothing(tmp_path, corrupt):
    engine, buy, _, rpc, _ = sold(tmp_path)
    journal = engine.journal
    built = []
    result = start(engine, buy, built=built)
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1400)
    rpc.tx = cleanup_payload(built[0], result['execution']['signature'])
    if corrupt == 'signature': rpc.tx['transaction']['signatures'] = ['wrong']
    if corrupt == 'message': rpc.tx['transaction']['message']['instructions'][0]['data'] = '1'
    if corrupt == 'fee': rpc.tx['meta']['fee'] += 1
    if corrupt == 'not_closed': rpc.tx = cleanup_payload(built[0], result['execution']['signature'], closed=False)
    if corrupt == 'cash': rpc.tx['meta']['postBalances'][0] += 1
    if corrupt == 'record':
        record = json.loads(journal.get('fixture-cleanup-0')['order_json'])
        record['account_lamports_observed'] += 1
        journal.con.execute('UPDATE orders SET order_json=? WHERE decision_id=?',
                            (json.dumps(record, sort_keys=True, separators=(',', ':')), 'fixture-cleanup-0'))
    with pytest.raises(ValueError, match='finalized_cleanup_record_invalid' if corrupt == 'record' else None):
        run(engine.recover('fixture-cleanup-0'))
    assert journal.killed and journal.get('fixture-cleanup-0')['reserved_lamports'] == FEE
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'IN_FLIGHT'
    assert journal.con.execute('SELECT locked_rent_lamports FROM positions').fetchone()[0] == RENT


@pytest.mark.parametrize('target', ['cleanup_row', 'cleanup_alert', 'cleanup_order', 'released_rent',
                                    'audit_event', 'unlogged_cleanup', 'deleted_cleanup'])
def test_audit_chain_verifies_and_detects_tampering_of_a_cleanup_record(tmp_path, target):
    engine, buy, _, rpc, _ = sold(tmp_path)
    journal = engine.journal
    built = []
    start(engine, buy, leftover=1, built=built)
    settle(engine, rpc, 'fixture-cleanup-0', built[0])
    kinds = audit_kinds(journal)
    assert kinds.index('cleanup_intent') < len(kinds) - 8 and kinds[-2:] == ['cleanup_settled', 'reconciled']
    assert journal.verify_audit() != '0' * 64
    reason = 'cleanup_not_bound_to_durable_audit'
    if target == 'cleanup_row':
        journal.con.execute('UPDATE cleanups SET rent_recovered_lamports=rent_recovered_lamports+1')
    elif target == 'cleanup_alert':
        journal.con.execute("UPDATE cleanups SET alerts_json='[]'")
    elif target == 'unlogged_cleanup':
        journal.con.execute("INSERT INTO cleanups(decision_id,mint,pool,wallet,attempt,max_dust_burn_atomic,outcome) VALUES('x',?,?,?,1,2000000,'IN_FLIGHT')",
                            (buy.mint, buy.pool, buy.user))
    elif target == 'deleted_cleanup':
        journal.con.execute('DELETE FROM cleanups')
    elif target == 'cleanup_order':
        journal.con.execute("UPDATE orders SET reconciliation_json='{}' WHERE decision_id='fixture-cleanup-0'")
        reason = 'execution_journal_rows_not_bound_to_audit'
    elif target == 'released_rent':
        journal.con.execute('UPDATE positions SET locked_rent_lamports=?', (RENT,))
        reason = 'execution_inventory_not_bound_to_audit'
    else:
        sequence, event = journal.con.execute("SELECT sequence,event_json FROM audit WHERE json_extract(event_json,'$.kind')='cleanup_settled'").fetchone()
        journal.con.execute('UPDATE audit SET event_json=? WHERE sequence=?',
                            (event.replace('"rent_recovered_lamports":%d' % RENT, '"rent_recovered_lamports":1'), sequence))
        reason = 'execution_audit_chain_corrupt'
    with pytest.raises(ValueError, match=reason):
        ExecutionEngine(journal=journal, rpc=FakeRpc())


def test_existing_journal_file_without_the_cleanup_table_opens_and_verifies_unchanged(tmp_path):
    engine, buy, _, rpc, _ = sold(tmp_path)
    journal = engine.journal
    head = journal.verify_audit()
    rows = [tuple(r) for r in journal.con.execute('SELECT * FROM audit ORDER BY sequence')]
    ledger_before = (list(map(tuple, journal.con.execute('SELECT * FROM positions'))),
                     list(map(tuple, journal.con.execute('SELECT * FROM daily'))),
                     list(map(tuple, journal.con.execute('SELECT * FROM orders'))))
    journal.con.execute('DROP TABLE cleanups')  # a file written before this version
    journal.close()
    reopened = ExecutionJournal(tmp_path / 'private-live.sqlite')
    assert reopened.verify_audit() == head
    assert [tuple(r) for r in reopened.con.execute('SELECT * FROM audit ORDER BY sequence')] == rows
    assert (list(map(tuple, reopened.con.execute('SELECT * FROM positions'))),
            list(map(tuple, reopened.con.execute('SELECT * FROM daily'))),
            list(map(tuple, reopened.con.execute('SELECT * FROM orders')))) == ledger_before
    assert reopened.con.execute('SELECT COUNT(*) FROM cleanups').fetchone()[0] == 0
    reopened.close()
