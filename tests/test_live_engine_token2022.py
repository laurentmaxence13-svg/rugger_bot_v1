"""Token-2022 LaunchLab route and cleanup through the REAL engine and journal.

Offline only: fake signer, fake send and fake finality exactly as in
test_live_engine / test_live_cleanup_engine. The finalized payloads MODEL the
chain effects; nothing here is a chain execution, nothing is armed for real.
Production evidence for Token-2022 (bot/live/evidence.py) is NOT wired: the
evidence provider below is a test provider.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest

from bot.live.cleanup import MAX_DUST_BURN_ATOMIC, build_base_account_cleanup
from bot.live.cleanup_token2022 import (PreparedBaseAccountCleanupToken2022,
                                        build_base_account_cleanup_token2022)
from bot.live.engine import ExecutionEngine
from bot.live.journal import ExecutionJournal
from bot.live.route import TOKEN_PROGRAM, build_launchlab_order
from bot.live.route_token2022 import (TOKEN2022_ATA_RENT_LAMPORTS,
                                      build_launchlab_order_token2022)
from bot.live.safety import AdmissionRequest, HealthEvidence, Mode, arm, enable
from bot.live.submission import BoundSubmissionGuard
from bot.p3.certification import PROGRAM
from bot.p3.token2022 import TOKEN_2022_PROGRAM as T22
from test_live_cleanup_base_account import cleanup_payload, cleanup_request
from test_live_engine import (ENDPOINT, GENESIS, FakeSignatureVerifier, configured,
                              finalized_payload, rpc_message, run, sell_request)
from test_live_route_token2022 import (t22_cleanup_payload, t22_cleanup_request,
                                       t22_request, t22_sell)
from test_live_wire_route import route_request

T22_RENT = TOKEN2022_ATA_RENT_LAMPORTS
SPL_RENT = 2_039_280
TRADE_FEE = 5002
CLEANUP_FEE = 5001
BALANCE = 10_000_000_000


def authorize(engine, **changes):
    """Owner scope listing LaunchLab AND Token-2022 explicitly."""
    changes.setdefault('allowed_programs', (PROGRAM, T22))
    env = replace(engine.envelope, **changes)
    engine.envelope = env
    engine.arming = enable(env, arm(env, now_ms=1000, arm_receipt='fixture-arm'),
                           now_ms=1050, enable_receipt='fixture-enable')


def setup(tmp_path):
    engine, _, rpc, signer, now = configured(tmp_path)
    authorize(engine)
    trade_evidence = engine.evidence_provider

    async def evidence(decision, prepared):
        if type(prepared) is not PreparedBaseAccountCleanupToken2022:
            return await trade_evidence(decision, prepared)
        parameters = json.loads(prepared.rebuild_request_json)
        pool = json.loads(engine.journal.get(decision)['order_json'])['pool']
        request = AdmissionRequest(decision_id=decision, side='cleanup',
            wallet=prepared.user, cluster='mainnet-beta', genesis_hash=GENESIS,
            rpc_endpoint_sha256=ENDPOINT, program_id=T22, mint=prepared.mint,
            pool=pool, quote_source_id='ISOLATED-fixture-bank',
            quote_payload_sha256=prepared.source_account_digest,
            route_message_sha256=hashlib.sha256(prepared.transaction.message).hexdigest(),
            quote_received_at_ms=prepared.source_available_at_ms,
            risk_checked_at_ms=now[0], quote_context_slot=prepared.source_slot,
            observed_bank_slot=prepared.source_slot, amount_in_atomic=0,
            quote_input_atomic=0, quote_output_atomic=0, minimum_out_atomic=0,
            network_fee_upper_lamports=prepared.network_fee_upper_lamports,
            priority_fee_lamports=(parameters['compute_unit_limit'] * parameters['priority_fee_micro_lamports'] + 999999)//1000000,
            compute_units=parameters['compute_unit_limit'], slippage_bps=0,
            price_impact_bps=0, rent_deposit_upper_lamports=0, exit_capacity_atomic=0,
            identity_verified=True, route_verified=True, costs_known=True, anti_rug_reasons=())
        health = HealthEvidence(observed_at_ms=now[0], scanner_heartbeat_at_ms=now[0],
            rpc_success_at_ms=now[0], websocket_heartbeat_at_ms=now[0],
            scanner_connected=True, rpc_connected=True, websocket_connected=True,
            rpc_genesis_hash=GENESIS, rpc_endpoint_sha256=ENDPOINT, clock_offset_ms=0)
        return request, health

    engine.evidence_provider = evidence
    return engine, rpc, signer, now


def t22_payload(order, signature, *, error=None, quantity=None, proceeds=None,
                fee=TRADE_FEE, program=T22, rent=T22_RENT, closed_ata=False):
    """Finalized payload MODEL of a Token-2022 trade (programId included, as RPC does)."""
    message = rpc_message(order)
    keys = message['accountKeys']
    wallet_index, base_index = keys.index(order.user), keys.index(order.base_token_account)
    swap = next(i for i in message['instructions'] if keys[i['programIdIndex']] == PROGRAM)
    quote_vault_index = swap['accounts'][8]
    before = [0] * len(keys); after = [0] * len(keys)
    before[wallet_index] = after[wallet_index] = BALANCE
    existed = order.side == 'SELL' or order.base_balance_before > 0
    before[base_index] = after[base_index] = T22_RENT if existed else 0
    token_before = order.base_balance_before
    if error is not None:
        after[wallet_index] -= fee
        token_after = token_before
    elif order.side == 'BUY':
        quantity = quantity if quantity is not None else order.expected_output
        locked = 0 if existed else rent
        after[base_index] += locked
        after[wallet_index] -= order.input_amount + fee + locked
        token_after = token_before + quantity
    else:
        proceeds = proceeds if proceeds is not None else order.expected_output
        after[wallet_index] += proceeds - fee
        token_after = token_before - order.input_amount
        if closed_ata:  # the ATA was closed in the sale: rent leaves it
            after[wallet_index] += after[base_index]
            after[base_index] = 0

    def token(value):
        entry = dict(accountIndex=base_index, mint=order.mint, owner=order.user,
                     uiTokenAmount=dict(amount=str(value), decimals=6, uiAmount=None,
                                        uiAmountString='not-used'))
        if program is not None:
            entry['programId'] = program
        return entry
    # A realistic payload also lists the pool's WSOL vault under classic Token.
    vault = dict(accountIndex=quote_vault_index, mint='So11111111111111111111111111111111111111112',
                 owner=keys[swap['accounts'][1]], programId=TOKEN_PROGRAM,
                 uiTokenAmount=dict(amount='1', decimals=9, uiAmount=None, uiAmountString='x'))
    return dict(slot=1300, version='legacy', transaction=dict(signatures=[signature], message=message),
        meta=dict(err=error, fee=fee, preBalances=before, postBalances=after,
            preTokenBalances=([token(token_before)] if before[base_index] else []) + [vault],
            postTokenBalances=([token(token_after)] if after[base_index] else []) + [deepcopy(vault)]))


def submit(engine, decision, order):
    result = run(engine.execute(decision, order))
    assert result['state'] == 'SUBMITTED'
    return result


def finalize(engine, rpc, decision, order, **kwargs):
    result = submit(engine, decision, order)
    rpc.status = dict(confirmationStatus='finalized', err=kwargs.get('error'), slot=1300)
    rpc.tx = t22_payload(order, result['signature'], **kwargs)
    return run(engine.recover(decision))


def t22_buy():
    request = t22_request()
    return request['decision_id'], build_launchlab_order_token2022(**request)


def bought(tmp_path):
    engine, rpc, signer, now = setup(tmp_path)
    decision, buy = t22_buy()
    assert finalize(engine, rpc, decision, buy)['state'] == 'RECONCILED'
    return engine, rpc, signer, buy


def totally_sold(tmp_path):
    engine, rpc, signer, buy = bought(tmp_path)
    quantity = buy.expected_output
    sell = build_launchlab_order_token2022(**t22_sell(quantity, quantity, 't22-total-sell'))
    assert finalize(engine, rpc, 't22-total-sell', sell)['state'] == 'RECONCILED'
    engine.rpc.get_fee_for_message = _cleanup_fee
    rpc.simulation = dict(err=None, unitsConsumed=9000, context_slot=1300)
    return engine, rpc, signer, buy, sell


async def _cleanup_fee(message):
    return CLEANUP_FEE


def start_cleanup(engine, buy, decision='t22-cleanup-0', *, built=None, kind='BASE_ACCOUNT_CLEANUP_TOKEN2022',
                  leftover=0):
    def build(bound):
        prepared = build_base_account_cleanup_token2022(**t22_cleanup_request(
            leftover, decision=decision, max_dust_burn_atomic=bound))
        if built is not None:
            built.append(prepared)
        return prepared
    return run(engine.cleanup(decision, mint=buy.mint, wallet=buy.user, build=build, kind=kind))


def ledger(engine):
    journal = engine.journal
    return (dict(journal.con.execute('SELECT * FROM positions').fetchone()),
            [dict(r) for r in journal.con.execute('SELECT * FROM daily ORDER BY day')],
            journal.risk_snapshot(at=engine.clock_ms(), wallet_balance_lamports=BALANCE))


# ------------------------------------------------------------- end to end

def test_token2022_buy_partial_and_total_sell_then_cleanup_through_the_real_engine(tmp_path):
    engine, rpc, signer, now = setup(tmp_path)
    journal = engine.journal
    decision, buy = t22_buy()
    assert buy.rent_deposit_lamports == json.loads(buy.rebuild_request_json)['rent_exempt_lamports'] + T22_RENT
    final = finalize(engine, rpc, decision, buy)
    assert final['state'] == 'RECONCILED'
    assert final['reconciliation']['rent_locked_lamports'] == T22_RENT
    record = json.loads(journal.get(decision)['order_json'])
    assert (record['route_kind'], record['base_token_program']) == ('LAUNCHLAB_TOKEN2022', T22)
    position = ledger(engine)[0]
    quantity = buy.expected_output
    assert position == dict(mint=buy.mint, pool=buy.pool, quantity_atomic=quantity,
        entry_cost_lamports=buy.input_amount + TRADE_FEE, locked_rent_lamports=T22_RENT)
    # Partial then total sale; the ATA's lamports never move during a sale.
    half = quantity // 2
    proceeds = []
    for index, (amount, held) in enumerate(((half, quantity), (quantity - half, quantity - half))):
        sell = build_launchlab_order_token2022(**t22_sell(amount, held, f't22-sell-{index}'))
        fill = finalize(engine, rpc, f't22-sell-{index}', sell)
        assert fill['state'] == 'RECONCILED' and fill['reconciliation']['rent_locked_lamports'] == 0
        assert fill['reconciliation']['gross_output_lamports'] == sell.expected_output
        proceeds.append(sell.expected_output)
        assert ledger(engine)[0]['quantity_atomic'] == held - amount
    position, daily, risk = ledger(engine)
    assert position['quantity_atomic'] == position['entry_cost_lamports'] == 0
    assert position['locked_rent_lamports'] == T22_RENT == risk.capital_at_risk_lamports
    assert daily[0]['realized_pnl'] == sum(proceeds) - buy.input_amount - 3 * TRADE_FEE
    sales = [journal.get(f't22-sell-{i}')['reconciliation_json'] for i in range(2)]
    # Cleanup on Token-2022.
    rpc.get_fee_for_message = _cleanup_fee
    rpc.simulation = dict(err=None, unitsConsumed=9000, context_slot=1300)
    guard, guarded, built = BoundSubmissionGuard(engine), [], []
    send = rpc.send_transaction

    async def guarded_send(raw):
        guarded.append(guard(raw))
        return await send(raw)
    rpc.send_transaction = guarded_send
    started = start_cleanup(engine, buy, built=built)
    assert started['execution']['state'] == 'SUBMITTED' and guarded == [True]
    row = journal.get('t22-cleanup-0')
    record = json.loads(row['order_json'])
    assert (record['route_kind'], record['side'], record['program_id']) == ('BASE_ACCOUNT_CLEANUP', 'CLEANUP', T22)
    assert (row['reserved_lamports'], row['reserved_atomic']) == (CLEANUP_FEE, 0)
    rpc.status = dict(confirmationStatus='confirmed', err=None, slot=1400)
    assert run(engine.recover('t22-cleanup-0'))['state'] == 'CONFIRMED'
    assert ledger(engine)[0] == position and ledger(engine)[1] == daily  # still locked
    assert journal.cleanup('t22-cleanup-0')['outcome'] == 'IN_FLIGHT'
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1400)
    rpc.tx = t22_cleanup_payload(built[0], row['signature'])
    final = run(engine.recover('t22-cleanup-0'))
    assert final['state'] == 'RECONCILED'
    reconciliation = final['reconciliation']
    assert reconciliation['account_closed'] is True and reconciliation['token_program'] == T22
    assert reconciliation['rent_recovered_lamports'] == T22_RENT
    assert (reconciliation['gross_output_lamports'], reconciliation['sale_proceeds_lamports'],
            reconciliation['market_pnl_lamports']) == (0, 0, 0)
    after_position, after_daily, after_risk = ledger(engine)
    assert after_position == dict(position, locked_rent_lamports=0)
    assert after_risk.capital_at_risk_lamports == 0
    assert after_daily[0]['realized_pnl'] == sum(proceeds) - buy.input_amount - 3 * TRADE_FEE - CLEANUP_FEE
    assert after_daily[0]['realized_pnl'] == daily[0]['realized_pnl'] - CLEANUP_FEE
    assert after_daily[0]['realized_loss'] == daily[0]['realized_loss'] + CLEANUP_FEE
    assert after_daily[0]['spent'] == daily[0]['spent'] + CLEANUP_FEE == (
        buy.input_amount + 3 * TRADE_FEE + T22_RENT + CLEANUP_FEE)
    assert [journal.get(f't22-sell-{i}')['reconciliation_json'] for i in range(2)] == sales
    cleanup = journal.cleanup('t22-cleanup-0')
    assert (cleanup['outcome'], cleanup['fee_lamports'], cleanup['burned_atomic']) == ('CLOSED', CLEANUP_FEE, 0)
    assert cleanup['rent_released_lamports'] == cleanup['rent_recovered_lamports'] == T22_RENT
    assert journal.cleanup_costs(buy.mint) == dict(cleanup_fee_lamports=CLEANUP_FEE,
        rent_paid_lamports=T22_RENT, rent_recovered_lamports=T22_RENT,
        rent_still_locked_lamports=0, net_rent_cost_lamports=0, alerts=[])
    assert after_risk.consecutive_failures == 0
    # Idempotent: no re-sign, no re-send.
    assert signer.calls == 4 and len(rpc.send_calls) == 4
    run(engine.recover('t22-cleanup-0'))
    again = run(engine.cleanup('t22-cleanup-0', mint=buy.mint, wallet=buy.user, build=None,
                               kind='BASE_ACCOUNT_CLEANUP_TOKEN2022'))
    assert again['cleanup'] == cleanup and again['execution'] == final
    assert signer.calls == 4 and len(rpc.send_calls) == 4
    assert journal.verify_audit() != '0' * 64


def test_failed_token2022_cleanup_keeps_rent_locked_and_counts_attempts(tmp_path):
    engine, rpc, signer, buy, _ = totally_sold(tmp_path)
    journal = engine.journal
    position, daily, _ = ledger(engine)
    built = []
    assert start_cleanup(engine, buy, built=built)['cleanup']['attempt'] == 1
    error = {'InstructionError': [2, {'Custom': 11}]}
    rpc.status = dict(confirmationStatus='finalized', err=error, slot=1400)
    rpc.tx = t22_cleanup_payload(built[0], journal.get('t22-cleanup-0')['signature'], error=error)
    assert run(engine.recover('t22-cleanup-0'))['state'] == 'RECONCILED'
    cleanup = journal.cleanup('t22-cleanup-0')
    assert (cleanup['outcome'], cleanup['fee_lamports'], cleanup['rent_recovered_lamports']) == ('FAILED', CLEANUP_FEE, 0)
    assert ledger(engine)[0] == position
    assert ledger(engine)[1][0]['realized_pnl'] == daily[0]['realized_pnl'] - CLEANUP_FEE
    assert journal.cleanup_costs(buy.mint)['rent_still_locked_lamports'] == T22_RENT


# --------------------------------------------------------------- admission

def test_admission_refuses_token2022_when_the_envelope_omits_the_token2022_program(tmp_path):
    engine, rpc, signer, _ = setup(tmp_path)
    authorize(engine, allowed_programs=(PROGRAM,))
    decision, buy = t22_buy()
    with pytest.raises(ValueError, match='^submission_admission_refused:program_not_authorized$'):
        run(engine.execute(decision, buy))
    assert signer.calls == 0 and not rpc.send_calls
    assert engine.journal.get(decision)['state'] == 'SIMULATED'


def test_token2022_cleanup_refused_without_token2022_in_the_envelope(tmp_path):
    engine, rpc, signer, buy, _ = totally_sold(tmp_path)
    authorize(engine, allowed_programs=(PROGRAM, TOKEN_PROGRAM))
    with pytest.raises(ValueError, match='^submission_admission_refused:program_not_authorized$'):
        start_cleanup(engine, buy)
    assert signer.calls == 2 and len(rpc.send_calls) == 2
    assert engine.journal.cleanup('t22-cleanup-0')['outcome'] == 'NOT_SENT'
    assert ledger(engine)[0]['locked_rent_lamports'] == T22_RENT


def test_token2022_program_authorization_is_rechecked_after_signing(tmp_path):
    engine, rpc, signer, _ = setup(tmp_path)
    decision, buy = t22_buy()
    signer.after_sign = lambda: authorize(engine, allowed_programs=(PROGRAM,))
    with pytest.raises(ValueError, match='submission_admission_refused:program_not_authorized'):
        run(engine.execute(decision, buy))
    assert signer.calls == 1 and not rpc.send_calls
    row = engine.journal.get(decision)
    assert (row['state'], row['reserved_lamports']) == ('UNSENT_CANCELLED', 0)


@pytest.mark.parametrize('route', ['SPL', 'T22'])
@pytest.mark.parametrize('case', ['prepared', 'armed_mode', 'research', 'armed_only_receipt',
                                  'no_authority', 'kill', 'kill_after_sign', 'expired', 'fee_cap'])
def test_token2022_route_is_blocked_exactly_like_the_spl_route(tmp_path, route, case):
    engine, rpc, signer, now = setup(tmp_path)
    journal = engine.journal
    if route == 'SPL':
        request = route_request(); order = build_launchlab_order(**request)
    else:
        request = t22_request(); order = build_launchlab_order_token2022(**request)
    decision = request['decision_id']
    expected = dict(prepared=('SIMULATED', None), armed_mode=('SIMULATED', None),
        research=('PREPARED', None),
        armed_only_receipt=('SIMULATED', 'submission_admission_refused:explicit_arm_and_enable_required'),
        no_authority=('SIMULATED', 'explicit_authorization_and_fresh_evidence_required'),
        kill=('PREPARED', 'persistent_kill_switch_active'),
        kill_after_sign=('UNSENT_CANCELLED', 'submission_admission_refused:persistent_kill_switch'),
        expired=('SIMULATED', 'submission_admission_refused:authorization_not_current'),
        fee_cap=('SIMULATED', 'submission_admission_refused:fee_limit'))[case]
    if case == 'prepared': engine.mode = Mode.LIVE_PREPARED
    if case == 'armed_mode': engine.mode = Mode.LIVE_ARMED
    if case == 'research': engine.mode = Mode.RESEARCH
    if case == 'armed_only_receipt':
        engine.arming = arm(engine.envelope, now_ms=1000, arm_receipt='fixture-arm')
    if case == 'no_authority': engine.arming = None
    if case == 'kill': journal.kill('fixture emergency', 1100)
    if case == 'kill_after_sign': signer.after_sign = lambda: journal.kill('fixture emergency', 1100)
    if case == 'expired': authorize(engine, expires_at_ms=1100)
    if case == 'fee_cap': authorize(engine, max_network_fee_lamports=4999)
    if expected[1]:
        with pytest.raises(ValueError, match=expected[1]):
            run(engine.execute(decision, order))
    else:
        run(engine.execute(decision, order))
    row = journal.get(decision)
    assert row['state'] == expected[0] and row['reserved_lamports'] == 0
    assert (row['signature'] is not None) == (case == 'kill_after_sign')  # signed, never sent
    assert not rpc.send_calls and signer.calls == (1 if case == 'kill_after_sign' else 0)


# ----------------------------------------------------- reconciliation refusals

@pytest.mark.parametrize('corrupt', ['spl_program', 'program_absent', 'vault_program_absent',
                                     'short_fill', 'spl_rent', 'record'])
def test_finalized_token2022_buy_that_does_not_reconcile_kills_and_keeps_reservation(tmp_path, corrupt):
    engine, rpc, signer, _ = setup(tmp_path)
    journal = engine.journal
    decision, buy = t22_buy()
    result = submit(engine, decision, buy)
    reserved = journal.get(decision)['reserved_lamports']
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    kwargs = dict(spl_program=dict(program=TOKEN_PROGRAM), program_absent=dict(program=None),
                  short_fill=dict(quantity=buy.minimum_out - 1), spl_rent=dict(rent=SPL_RENT)).get(corrupt, {})
    rpc.tx = t22_payload(buy, result['signature'], **kwargs)
    if corrupt == 'vault_program_absent':
        for label in ('preTokenBalances', 'postTokenBalances'):
            del rpc.tx['meta'][label][-1]['programId']
    if corrupt == 'record':
        record = json.loads(journal.get(decision)['order_json'])
        record['rent_deposit_lamports'] += 1
        journal.con.execute('UPDATE orders SET order_json=? WHERE decision_id=?',
                            (json.dumps(record, sort_keys=True, separators=(',', ':')), decision))
    reason = dict(spl_program='token2022_balance_program_id_required',
                  program_absent='token2022_balance_program_id_required',
                  vault_program_absent='token2022_balance_program_id_required',
                  short_fill='buy_fill_below_minimum_out', spl_rent='token2022_ATA_rent_lock_mismatch',
                  record='finalized_token2022_route_record_invalid')[corrupt]
    with pytest.raises(ValueError, match=reason):
        run(engine.recover(decision))
    assert journal.killed and journal.get(decision)['state'] == 'SUBMITTED'
    assert journal.get(decision)['reserved_lamports'] == reserved
    assert journal.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 0


@pytest.mark.parametrize('corrupt', ['spl_program', 'program_absent', 'wrong_quantity',
                                     'short_proceeds', 'closed_ata'])
def test_finalized_token2022_sell_that_does_not_reconcile_kills_and_keeps_inventory(tmp_path, corrupt):
    engine, rpc, signer, buy = bought(tmp_path)
    journal = engine.journal
    quantity = buy.expected_output
    sell = build_launchlab_order_token2022(**t22_sell(quantity // 2, quantity, 't22-sell-x'))
    result = submit(engine, 't22-sell-x', sell)
    position = ledger(engine)[0]
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    kwargs = dict(spl_program=dict(program=TOKEN_PROGRAM), program_absent=dict(program=None),
                  short_proceeds=dict(proceeds=sell.minimum_out - 1),
                  closed_ata=dict(closed_ata=True)).get(corrupt, {})
    rpc.tx = t22_payload(sell, result['signature'], **kwargs)
    if corrupt == 'wrong_quantity':
        rpc.tx['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = str(quantity - quantity // 2 + 1)
    reason = dict(spl_program='token2022_balance_program_id_required',
                  program_absent='token2022_balance_program_id_required',
                  wrong_quantity='sell_fill_quantity_or_rent_mismatch',
                  short_proceeds='sell_fill_below_minimum_out',
                  closed_ata='position_token_balance_missing')[corrupt]
    with pytest.raises(ValueError, match=reason):
        run(engine.recover('t22-sell-x'))
    assert journal.killed and journal.get('t22-sell-x')['state'] == 'SUBMITTED'
    assert ledger(engine)[0] == position


def test_closed_ata_during_a_sale_with_a_post_balance_entry_is_still_refused(tmp_path):
    engine, rpc, signer, buy = bought(tmp_path)
    quantity = buy.expected_output
    sell = build_launchlab_order_token2022(**t22_sell(quantity, quantity, 't22-sell-z'))
    result = submit(engine, 't22-sell-z', sell)
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    rpc.tx = t22_payload(sell, result['signature'], closed_ata=True)
    base = rpc.tx['meta']['preTokenBalances'][0]
    rpc.tx['meta']['postTokenBalances'].insert(0, dict(deepcopy(base), uiTokenAmount=dict(
        base['uiTokenAmount'], amount='0')))
    with pytest.raises(ValueError, match='sell_fill_quantity_or_rent_mismatch'):
        run(engine.recover('t22-sell-z'))
    assert engine.journal.killed


@pytest.mark.parametrize('corrupt', ['program_absent', 'spl_program', 'not_closed', 'record'])
def test_finalized_token2022_cleanup_that_does_not_reconcile_releases_nothing(tmp_path, corrupt):
    engine, rpc, signer, buy, _ = totally_sold(tmp_path)
    journal = engine.journal
    built = []
    start_cleanup(engine, buy, built=built)
    signature = journal.get('t22-cleanup-0')['signature']
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1400)
    rpc.tx = t22_cleanup_payload(built[0], signature, closed=corrupt != 'not_closed')
    if corrupt == 'program_absent':
        del rpc.tx['meta']['preTokenBalances'][0]['programId']
    if corrupt == 'spl_program':
        rpc.tx['meta']['preTokenBalances'][0]['programId'] = TOKEN_PROGRAM
    if corrupt == 'record':
        record = json.loads(journal.get('t22-cleanup-0')['order_json'])
        record['program_id'] = TOKEN_PROGRAM  # pretend it was the SPL cleanup
        journal.con.execute('UPDATE orders SET order_json=? WHERE decision_id=?',
                            (json.dumps(record, sort_keys=True, separators=(',', ':')), 't22-cleanup-0'))
    reason = dict(program_absent='token2022_balance_program_id_required',
                  spl_program='token2022_balance_program_id_required',
                  not_closed='base_token_account_not_closed_at_finality',
                  record='finalized_cleanup_record_invalid')[corrupt]
    with pytest.raises(ValueError, match=reason):
        run(engine.recover('t22-cleanup-0'))
    assert journal.killed and journal.cleanup('t22-cleanup-0')['outcome'] == 'IN_FLIGHT'
    assert journal.get('t22-cleanup-0')['reserved_lamports'] == CLEANUP_FEE
    assert ledger(engine)[0]['locked_rent_lamports'] == T22_RENT


def test_cleanup_kinds_and_types_do_not_cross(tmp_path):
    engine, rpc, signer, buy, _ = totally_sold(tmp_path)
    with pytest.raises(ValueError, match='^builder_generated_cleanup_required$'):
        start_cleanup(engine, buy, 'cross-0', kind='BASE_ACCOUNT_CLEANUP')
    spl = build_base_account_cleanup(**cleanup_request(decision='cross-1'))
    with pytest.raises(ValueError, match='^token2022_builder_generated_cleanup_required$'):
        run(engine.cleanup('cross-1', mint=buy.mint, wallet=buy.user, build=lambda bound: spl,
                           kind='BASE_ACCOUNT_CLEANUP_TOKEN2022'))
    for decision in ('cross-0', 'cross-1'):
        assert engine.journal.cleanup(decision)['outcome'] == 'NOT_SENT'
        assert engine.journal.get(decision) is None
    # The trade entry point still refuses any cleanup object.
    t22 = build_base_account_cleanup_token2022(**t22_cleanup_request(decision='cross-2'))
    with pytest.raises(ValueError, match='explicit_supported_execution_route_required'):
        run(engine.execute('cross-2', t22))
    assert signer.calls == 2 and len(rpc.send_calls) == 2


# ------------------------------------------------------- crash / duplicates

def test_crash_between_write_ahead_and_send_is_ambiguous_for_token2022(tmp_path):
    engine, rpc, signer, _ = setup(tmp_path)
    decision, buy = t22_buy()
    rpc.status = None

    async def process_dies(raw):
        rpc.send_calls.append(raw)
        engine.journal.close()
        raise TimeoutError('isolated fixture crash')
    rpc.send_transaction = process_dies
    with pytest.raises(sqlite3.ProgrammingError):
        run(engine.execute(decision, buy))
    journal = ExecutionJournal(tmp_path / 'private-live.sqlite')
    row = journal.get(decision)
    assert row['state'] == 'SUBMITTING' and row['reserved_lamports'] > 0 and row['signed_raw']
    restored = ExecutionEngine(journal=journal, rpc=rpc, verifier=FakeSignatureVerifier(),
                               clock_ms=lambda: 1100)
    assert run(restored.recover(decision))['state'] == 'SUBMITTING'
    rpc.height = 5001
    assert run(restored.recover(decision))['state'] == 'EXPIRED_UNKNOWN'
    assert journal.killed and journal.get(decision)['reserved_lamports'] == row['reserved_lamports']
    assert signer.calls == 1 and len(rpc.send_calls) == 1
    # It had landed: finality still reconciles the exact Token-2022 BUY.
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    rpc.tx = t22_payload(buy, row['signature'])
    assert run(restored.recover(decision))['state'] == 'RECONCILED'
    assert journal.con.execute('SELECT locked_rent_lamports FROM positions').fetchone()[0] == T22_RENT
    journal.verify_audit(); journal.close()


def test_duplicate_token2022_decision_id_is_refused_and_never_resent(tmp_path):
    engine, rpc, signer, _ = setup(tmp_path)
    decision, buy = t22_buy()
    first = submit(engine, decision, buy)
    assert run(engine.execute(decision, buy)) == first
    other = build_launchlab_order_token2022(**dict(t22_request(), amount_in=buy.input_amount - 1))
    with pytest.raises(ValueError, match='decision_id_reused_with_different_order'):
        run(engine.execute(decision, other))
    spl = build_launchlab_order(**route_request())
    with pytest.raises(ValueError, match='decision_id_reused_with_different_order'):
        run(engine.execute(decision, spl))
    assert signer.calls == 1 and len(rpc.send_calls) == 1


# ------------------------------------- O-T3': realistic SPL payloads reconcile

def test_spl_sale_and_cleanup_with_realistic_program_ids_reconcile_unchanged(tmp_path):
    engine, buy, rpc, signer, _ = configured(tmp_path)
    authorize(engine, allowed_programs=(PROGRAM, TOKEN_PROGRAM))
    journal = engine.journal

    def named(payload):
        for label in ('preTokenBalances', 'postTokenBalances'):
            for entry in payload['meta'][label]:
                entry['programId'] = TOKEN_PROGRAM
        assert payload['meta']['preTokenBalances'] or payload['meta']['postTokenBalances']
        return payload

    decision = json.loads(buy.rebuild_request_json)['decision_id']
    result = submit(engine, decision, buy)
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    rpc.tx = named(finalized_payload(buy, result['signature']))
    assert run(engine.recover(decision))['state'] == 'RECONCILED'
    quantity = buy.expected_output
    sell = build_launchlab_order(**sell_request(quantity, quantity, 'spl-total-sell'))
    result = submit(engine, 'spl-total-sell', sell)
    rpc.tx = named(finalized_payload(sell, result['signature']))
    sale = run(engine.recover('spl-total-sell'))
    assert sale['state'] == 'RECONCILED'
    assert sale['reconciliation']['gross_output_lamports'] == sell.expected_output
    # SPL cleanup through the engine, payload naming the classic Token program.
    rpc.get_fee_for_message = _cleanup_fee
    rpc.simulation = dict(err=None, unitsConsumed=9000, context_slot=1300)
    trade_evidence = engine.evidence_provider

    async def evidence(decision_id, prepared):
        if type(prepared).__name__ != 'PreparedBaseAccountCleanup':
            return await trade_evidence(decision_id, prepared)
        request, health = await trade_evidence(decision_id, sell)
        parameters = json.loads(prepared.rebuild_request_json)
        return replace(request, decision_id=decision_id, side='cleanup', program_id=TOKEN_PROGRAM,
            quote_payload_sha256=prepared.source_account_digest,
            route_message_sha256=hashlib.sha256(prepared.transaction.message).hexdigest(),
            quote_received_at_ms=prepared.source_available_at_ms,
            quote_context_slot=prepared.source_slot, observed_bank_slot=prepared.source_slot,
            amount_in_atomic=0, quote_input_atomic=0, quote_output_atomic=0, minimum_out_atomic=0,
            network_fee_upper_lamports=prepared.network_fee_upper_lamports,
            priority_fee_lamports=(parameters['compute_unit_limit'] * parameters['priority_fee_micro_lamports'] + 999999)//1000000,
            compute_units=parameters['compute_unit_limit'], slippage_bps=0, price_impact_bps=0,
            rent_deposit_upper_lamports=0, exit_capacity_atomic=0), health
    engine.evidence_provider = evidence
    built = []

    def build(bound):
        built.append(build_base_account_cleanup(**cleanup_request(max_dust_burn_atomic=bound)))
        return built[0]
    run(engine.cleanup('fixture-cleanup-0', mint=buy.mint, wallet=buy.user, build=build))
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1400)
    rpc.tx = named(cleanup_payload(built[0], journal.get('fixture-cleanup-0')['signature']))
    final = run(engine.recover('fixture-cleanup-0'))
    assert final['state'] == 'RECONCILED' and final['reconciliation']['rent_recovered_lamports'] == SPL_RENT
    assert journal.cleanup('fixture-cleanup-0')['outcome'] == 'CLOSED'
    assert not journal.killed
