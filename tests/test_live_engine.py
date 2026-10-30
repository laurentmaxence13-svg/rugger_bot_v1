"""Isolated lifecycle failures/recovery using genuine wire and explicit fake RPC.

The fake signatures and fixture transactions never establish market execution.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import struct

import pytest

from bot.live.engine import ExecutionEngine, Ed25519Verifier, message_from_rpc, reconcile_transaction
from bot.live.journal import ExecutionJournal
from bot.live.route import associated_token_address, build_launchlab_order, ephemeral_wsol_address
from bot.live.safety import AdmissionRequest, AuthorizationEnvelope, HealthEvidence, Mode, arm, enable
from bot.p3.certification import PROGRAM, _encode
from test_live_wire_route import route_request, _take_compact

GENESIS = _encode(bytes([12])*32)
ENDPOINT = 'a' * 64


class FakeIsolatedSigner:
    def __init__(self, public_key, after_sign=None):
        self.public_key, self.after_sign = public_key, after_sign
        self.calls = 0

    async def sign_message(self, message):
        self.calls += 1
        if self.after_sign:
            self.after_sign()
        return hashlib.sha512(b'ISOLATED-FAKE-SIGNATURE:' + message).digest()


class FakeSignatureVerifier:
    def verify(self, public_key, message, signature):
        if signature != hashlib.sha512(b'ISOLATED-FAKE-SIGNATURE:' + message).digest():
            raise ValueError('fake_fixture_signature_mismatch')


class FakeRpc:
    endpoint_sha256 = ENDPOINT

    def __init__(self):
        self.height = 4900
        self.send_calls = []
        self.simulation_calls = []
        self.status = None
        self.tx = None
        self.send_error = None
        self.simulation = dict(err=None, unitsConsumed=150000, context_slot=1300)

    async def get_block_height(self):
        return self.height

    async def genesis_hash(self):
        return GENESIS

    async def get_balance(self, wallet):
        return 10_000_000_000

    async def get_fee_for_message(self, message):
        return 5002

    async def simulate_transaction(self, raw, *, sig_verify):
        assert sig_verify is False
        assert raw[1:65] == bytes(64)
        self.simulation_calls.append(raw)
        return deepcopy(self.simulation)

    async def send_transaction(self, raw):
        self.send_calls.append(raw)
        if self.send_error:
            raise self.send_error
        return _encode(raw[1:65])

    async def signature_status(self, signature):
        return deepcopy(self.status)

    async def get_transaction(self, signature):
        return deepcopy(self.tx)


def configured(tmp_path, request=None, *, mode=Mode.LIVE_ENABLED):
    request = request or route_request()
    order = build_launchlab_order(**request)
    env = AuthorizationEnvelope(authorization_id='ISOLATED-fixture-authorization',
        approved_by='fixture-owner', cluster='mainnet-beta', genesis_hash=GENESIS,
        wallet=order.user, rpc_endpoint_sha256=ENDPOINT, allowed_programs=(PROGRAM,),
        issued_at_ms=1000, expires_at_ms=10000,
        max_capital_lamports=1_000_000_000, max_entry_lamports=200_000_000,
        max_daily_spend_lamports=2_000_000_000, max_daily_loss_lamports=100_000_000,
        max_open_positions=4, max_in_flight_orders=3, max_slippage_bps=200,
        max_price_impact_bps=2000,
        max_network_fee_lamports=10000, max_priority_fee_lamports=1000,
        max_compute_units=200000, max_quote_age_ms=5000, max_health_age_ms=1000,
        max_clock_skew_ms=100, max_consecutive_failures=3)
    arming = enable(env, arm(env, now_ms=1000, arm_receipt='fixture-arm'),
                    now_ms=1050, enable_receipt='fixture-enable')
    now = [1100]

    async def evidence(decision, prepared):
        parameters = json.loads(prepared.rebuild_request_json)
        request = AdmissionRequest(decision_id=decision, side=prepared.side.lower(),
            wallet=prepared.user, cluster='mainnet-beta', genesis_hash=GENESIS,
            rpc_endpoint_sha256=ENDPOINT, program_id=PROGRAM, mint=prepared.mint,
            pool=prepared.pool, quote_source_id='ISOLATED-fixture-bank',
            quote_payload_sha256=prepared.source_account_digest,
            route_message_sha256=hashlib.sha256(prepared.transaction.message).hexdigest(),
            quote_received_at_ms=prepared.source_available_at_ms,
            risk_checked_at_ms=now[0], quote_context_slot=prepared.source_slot,
            observed_bank_slot=prepared.source_slot, amount_in_atomic=prepared.input_amount,
            quote_input_atomic=prepared.input_amount, quote_output_atomic=prepared.expected_output,
            minimum_out_atomic=prepared.minimum_out,
            network_fee_upper_lamports=prepared.network_fee_upper_lamports,
            priority_fee_lamports=(parameters['compute_unit_limit'] * parameters['priority_fee_micro_lamports'] + 999999)//1000000,
            compute_units=parameters['compute_unit_limit'], slippage_bps=parameters['slippage_bps'],
            price_impact_bps=prepared.price_impact_bps,
            rent_deposit_upper_lamports=prepared.rent_deposit_lamports,
            exit_capacity_atomic=prepared.expected_output if prepared.side == 'BUY' else prepared.input_amount,
            identity_verified=True, route_verified=True, costs_known=True, anti_rug_reasons=())
        health = HealthEvidence(observed_at_ms=now[0], scanner_heartbeat_at_ms=now[0],
            rpc_success_at_ms=now[0], websocket_heartbeat_at_ms=now[0],
            scanner_connected=True, rpc_connected=True, websocket_connected=True,
            rpc_genesis_hash=GENESIS, rpc_endpoint_sha256=ENDPOINT, clock_offset_ms=0)
        return request, health

    journal = ExecutionJournal(tmp_path / 'private-live.sqlite')
    rpc = FakeRpc()
    signer = FakeIsolatedSigner(order.user)
    engine = ExecutionEngine(journal=journal, rpc=rpc, signer=signer,
        verifier=FakeSignatureVerifier(), mode=mode, envelope=env, arming=arming,
        evidence_provider=evidence, clock_ms=lambda: now[0])
    return engine, order, rpc, signer, now


def rpc_message(prepared):
    message = prepared.transaction.message
    count, p = _take_compact(message, 3)
    keys = [_encode(message[p+32*i:p+32*(i+1)]) for i in range(count)]
    p += 32 * count
    blockhash = _encode(message[p:p+32]); p += 32
    count, p = _take_compact(message, p)
    instructions = []
    for _ in range(count):
        program = message[p]; p += 1
        length, p = _take_compact(message, p)
        accounts = list(message[p:p+length]); p += length
        length, p = _take_compact(message, p)
        data = message[p:p+length]; p += length
        instructions.append(dict(programIdIndex=program, accounts=accounts, data=_encode(data)))
    assert p == len(message)
    return dict(header=dict(numRequiredSignatures=message[0], numReadonlySignedAccounts=message[1],
        numReadonlyUnsignedAccounts=message[2]), accountKeys=keys,
        recentBlockhash=blockhash, instructions=instructions)


def finalized_payload(order, signature, *, error=None, quantity=None, proceeds=None, fee=5002):
    message = rpc_message(order)
    keys = message['accountKeys']
    wallet_index, base_index = keys.index(order.user), keys.index(order.base_token_account)
    before = [0] * len(keys); after = [0] * len(keys)
    before[wallet_index] = after[wallet_index] = 10_000_000_000
    before[base_index] = after[base_index] = 2_039_280 if order.base_balance_before else 0
    token_before = order.base_balance_before
    if error is not None:
        after[wallet_index] -= fee
        token_after = token_before
    elif order.side == 'BUY':
        quantity = quantity if quantity is not None else order.expected_output
        rent = 0 if order.base_balance_before else 2_039_280
        after[base_index] += rent
        after[wallet_index] -= order.input_amount + fee + rent
        token_after = token_before + quantity
    else:
        proceeds = proceeds if proceeds is not None else order.expected_output
        after[wallet_index] += proceeds - fee
        token_after = token_before - order.input_amount
    def token(value):
        return dict(accountIndex=base_index, mint=order.mint, owner=order.user,
                    uiTokenAmount=dict(amount=str(value), decimals=6, uiAmount=None, uiAmountString='not-used'))
    return dict(slot=1300, version='legacy', transaction=dict(signatures=[signature], message=message),
        meta=dict(err=error, fee=fee, preBalances=before, postBalances=after,
            preTokenBalances=[token(token_before)] if before[base_index] else [],
            postTokenBalances=[token(token_after)] if after[base_index] else []))


def run(coro):
    return asyncio.run(coro)


def test_default_prepared_simulates_real_wire_without_signer_or_send(tmp_path):
    engine, order, rpc, signer, _ = configured(tmp_path, mode=Mode.LIVE_PREPARED)
    engine.envelope = engine.arming = engine.signer = None
    result = run(engine.execute(json.loads(order.rebuild_request_json)['decision_id'], order))
    assert result['state'] == 'SIMULATED'
    assert len(rpc.simulation_calls) == 1 and not rpc.send_calls and signer.calls == 0
    assert engine.journal.risk_snapshot(at=1100, wallet_balance_lamports=10_000_000_000).reserved_lamports == 0


def test_buy_finality_cash_fee_inventory_and_idempotent_recovery(tmp_path):
    engine, order, rpc, signer, _ = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    result = run(engine.execute(decision, order))
    assert result['state'] == 'SUBMITTED' and signer.calls == 1 and len(rpc.send_calls) == 1
    assert engine.journal.get(decision)['reserved_lamports'] == 104_083_562
    rpc.status = dict(confirmationStatus='confirmed', err=None, slot=1300)
    assert run(engine.recover(decision))['state'] == 'CONFIRMED'
    assert engine.journal.con.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 0
    rpc.tx = finalized_payload(order, result['signature'])
    rpc.status['confirmationStatus'] = 'finalized'
    assert run(engine.recover(decision))['state'] == 'RECONCILED'
    position = engine.journal.con.execute('SELECT * FROM positions').fetchone()
    assert position['quantity_atomic'] == order.expected_output
    assert position['entry_cost_lamports'] == 100_005_002
    assert position['locked_rent_lamports'] == 2_039_280
    assert engine.journal.get(decision)['reserved_lamports'] == 0
    run(engine.recover(decision)); run(engine.execute(decision, order))
    assert signer.calls == 1 and len(rpc.send_calls) == 1
    assert engine.journal.verify_audit() != '0' * 64


def test_ambiguous_send_timeout_retains_funds_and_survives_restart(tmp_path):
    engine, order, rpc, signer, now = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    rpc.send_error = TimeoutError('isolated fixture timeout')
    assert run(engine.execute(decision, order))['state'] == 'UNCERTAIN'
    assert engine.journal.killed and engine.journal.get(decision)['signed_raw']
    reserved = engine.journal.get(decision)['reserved_lamports']
    engine.journal.close()
    journal = ExecutionJournal(tmp_path / 'private-live.sqlite')
    restored = ExecutionEngine(journal=journal, rpc=rpc, clock_ms=lambda: now[0])
    rpc.height = 5001
    assert run(restored.recover(decision))['state'] == 'EXPIRED_UNKNOWN'
    assert journal.get(decision)['reserved_lamports'] == reserved and journal.killed
    assert signer.calls == 1 and len(rpc.send_calls) == 1


@pytest.mark.parametrize('reason', ['expiry', 'kill', 'blockhash'])
def test_rechecks_after_slow_or_interrupted_signer_before_send(tmp_path, reason):
    engine, order, rpc, signer, now = configured(tmp_path)
    def interrupt():
        if reason == 'expiry': now[0] = 10000
        elif reason == 'kill': engine.journal.kill('fixture emergency', now[0])
        else: rpc.height = 5001
    signer.after_sign = interrupt
    with pytest.raises(ValueError):
        run(engine.execute(json.loads(order.rebuild_request_json)['decision_id'], order))
    assert not rpc.send_calls
    assert engine.journal.con.execute('SELECT reserved_lamports FROM orders').fetchone()[0] == 0


def test_confirmed_then_disappeared_does_not_credit_or_resubmit(tmp_path):
    engine, order, rpc, _, _ = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    run(engine.execute(decision, order))
    rpc.status = dict(confirmationStatus='confirmed', err=None, slot=1300)
    run(engine.recover(decision)); rpc.status = None
    assert run(engine.recover(decision))['state'] == 'REORG_PENDING'
    assert engine.journal.killed and len(rpc.send_calls) == 1
    assert not list(engine.journal.con.execute('SELECT * FROM positions'))


@pytest.mark.parametrize('corrupt', ['signature', 'message', 'fee', 'tokens', 'cash'])
def test_finalized_unbound_or_underfilled_result_kills_and_retains_reservation(tmp_path, corrupt):
    engine, order, rpc, _, _ = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    result = run(engine.execute(decision, order))
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    rpc.tx = finalized_payload(order, result['signature'])
    if corrupt == 'signature': rpc.tx['transaction']['signatures'] = ['wrong']
    if corrupt == 'message': rpc.tx['transaction']['message']['instructions'][0]['data'] = '1'
    if corrupt == 'fee': rpc.tx['meta']['fee'] += 1
    if corrupt == 'tokens': rpc.tx['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '1'
    if corrupt == 'cash': rpc.tx['meta']['postBalances'][0] += 1
    with pytest.raises(ValueError): run(engine.recover(decision))
    assert engine.journal.killed and engine.journal.get(decision)['reserved_lamports'] > 0
    assert not list(engine.journal.con.execute('SELECT * FROM positions'))


def test_failed_finalized_transaction_charges_only_actual_fee(tmp_path):
    engine, order, rpc, _, _ = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    result = run(engine.execute(decision, order))
    err = dict(InstructionError=[2, 'Custom'])
    rpc.status = dict(confirmationStatus='finalized', err=err, slot=1300)
    rpc.tx = finalized_payload(order, result['signature'], error=err)
    assert run(engine.recover(decision))['state'] == 'RECONCILED'
    risk = engine.journal.risk_snapshot(at=1100, wallet_balance_lamports=10_000_000_000)
    assert risk.day_spent_lamports == 5002 and risk.consecutive_failures == 1 and risk.open_positions == 0
    assert risk.realized_daily_loss_lamports == 5002


def test_unowned_sell_is_refused_even_with_wallet_fixture_balance(tmp_path):
    engine, order, rpc, signer, _ = configured(tmp_path, route_request('SELL'))
    with pytest.raises(ValueError, match='inventory|position'):
        run(engine.execute(json.loads(order.rebuild_request_json)['decision_id'], order))
    assert not rpc.send_calls and signer.calls == 0


def test_decision_identity_and_prepared_bytes_cannot_be_changed(tmp_path):
    engine, order, rpc, signer, _ = configured(tmp_path)
    with pytest.raises(ValueError, match='decision_id'):
        run(engine.execute('new-unbound-id', order))
    with pytest.raises(ValueError, match='modified'):
        run(engine.execute(json.loads(order.rebuild_request_json)['decision_id'], replace(order, input_amount=1)))
    assert not rpc.simulation_calls and signer.calls == 0


def test_journal_refuses_an_existing_foreign_database_and_insecure_mode(tmp_path):
    import sqlite3
    path = tmp_path / 'foreign.sqlite'
    sqlite3.connect(path).close(); os.chmod(path, 0o600)
    with pytest.raises(ValueError, match='not_a_rugger'):
        ExecutionJournal(path)
    os.chmod(path, 0o644)
    with pytest.raises(ValueError, match='private'):
        ExecutionJournal(path)


def test_audit_tamper_is_detected_on_restart(tmp_path):
    engine, order, _, _, _ = configured(tmp_path, mode=Mode.RESEARCH)
    run(engine.execute(json.loads(order.rebuild_request_json)['decision_id'], order))
    engine.journal.con.execute("UPDATE audit SET event_json='{}' WHERE sequence=1")
    with pytest.raises(ValueError, match='audit_chain'):
        ExecutionEngine(journal=engine.journal, rpc=FakeRpc())


@pytest.mark.parametrize('target', ['order', 'inventory', 'kill', 'signed_wire'])
def test_database_row_tampering_is_bound_to_durable_audit(tmp_path, target):
    engine, order, rpc, _, _ = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    result = run(engine.execute(decision, order))
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    rpc.tx = finalized_payload(order, result['signature'])
    run(engine.recover(decision))
    if target == 'order':
        engine.journal.con.execute("UPDATE orders SET order_json='{}'")
    elif target == 'inventory':
        engine.journal.con.execute('UPDATE positions SET quantity_atomic=quantity_atomic+1')
    elif target == 'kill':
        engine.journal.con.execute("INSERT INTO execution_meta VALUES('kill','unlogged')")
    else:
        engine.journal.con.execute("UPDATE orders SET signed_raw=X'00'")
    with pytest.raises(ValueError, match='bound_to_audit'):
        ExecutionEngine(journal=engine.journal, rpc=FakeRpc())


def test_ed25519_public_rfc8032_vector_and_invalid_signature():
    pytest.importorskip('cryptography')
    public = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
    signature = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555'
                              'fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
    verifier = Ed25519Verifier()
    verifier.verify(_encode(public), b'', signature)
    with pytest.raises(ValueError, match='signature_invalid'):
        verifier.verify(_encode(public), b'changed', signature)


def sell_request(quantity, held, decision):
    import base64
    request = route_request('SELL')
    old, _ = ephemeral_wsol_address(request['wallet'], request['decision_id'])
    request['accounts'].pop(old)
    request['decision_id'] = decision
    new, _ = ephemeral_wsol_address(request['wallet'], decision)
    request['accounts'][new] = None
    ata = request['accounts'][associated_token_address(request['wallet'], request['mint'])]
    raw = bytearray(base64.b64decode(ata['data'][0]))
    struct.pack_into('<Q', raw, 64, held)
    ata['data'][0] = base64.b64encode(raw).decode()
    request['amount_in'] = quantity
    return request


def test_coherent_buy_two_partial_exits_exact_remainder_cost_and_locked_rent(tmp_path):
    engine, buy, rpc, signer, _ = configured(tmp_path)
    decision = json.loads(buy.rebuild_request_json)['decision_id']
    result = run(engine.execute(decision, buy))
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    rpc.tx = finalized_payload(buy, result['signature'])
    run(engine.recover(decision))
    quantity = buy.expected_output
    half = quantity // 2
    sale_outputs = []
    for index, (amount, held) in enumerate(((half, quantity), (quantity-half, quantity-half))):
        sell = build_launchlab_order(**sell_request(amount, held, f'fixture-sell-{index}'))
        result = run(engine.execute(f'fixture-sell-{index}', sell))
        assert result['state'] == 'SUBMITTED'
        rpc.tx = finalized_payload(sell, result['signature'])
        run(engine.recover(f'fixture-sell-{index}'))
        sale_outputs.append(sell.expected_output)
        run(engine.recover(f'fixture-sell-{index}'))
        position = engine.journal.con.execute('SELECT * FROM positions').fetchone()
        assert position['quantity_atomic'] == held - amount
    position = engine.journal.con.execute('SELECT * FROM positions').fetchone()
    assert position['entry_cost_lamports'] == 0 and position['locked_rent_lamports'] == 2_039_280
    daily = engine.journal.con.execute('SELECT * FROM daily').fetchone()
    assert daily['realized_pnl'] == sum(sale_outputs) - buy.input_amount - 3 * 5002
    assert daily['spent'] == buy.input_amount + 3 * 5002 + 2_039_280
    risk = engine.journal.risk_snapshot(at=1100, wallet_balance_lamports=10_000_000_000)
    assert risk.capital_at_risk_lamports == 2_039_280 and risk.open_positions == 0
    assert signer.calls == 3 and len(rpc.send_calls) == 3


def test_unsubmitted_reservation_can_be_cancelled_after_crash_without_rpc_send(tmp_path):
    from bot.live.engine import order_record
    engine, order, rpc, signer, now = configured(tmp_path)
    decision = json.loads(order.rebuild_request_json)['decision_id']
    journal = engine.journal
    journal.create(decision, order_record(order), now[0])
    journal.transition(decision, ('PREPARED',), 'SIMULATED', now[0])
    journal.reserve(decision, now[0], wallet_balance_lamports=10_000_000_000,
        max_capital_lamports=1_000_000_000, max_open_positions=4,
        max_in_flight_orders=3, max_daily_spend_lamports=2_000_000_000,
        max_daily_loss_lamports=100_000_000)
    assert journal.get(decision)['reserved_lamports'] > 0
    assert run(engine.recover(decision))['state'] == 'UNSENT_CANCELLED'
    assert journal.get(decision)['reserved_lamports'] == 0
    assert signer.calls == 0 and not rpc.send_calls


def test_atomic_reservation_rechecks_pending_daily_spend_and_keeps_first_order(tmp_path):
    from bot.live.engine import order_record
    engine, order, rpc, signer, now = configured(tmp_path)
    journal = engine.journal
    kwargs = dict(wallet_balance_lamports=10_000_000_000,
        max_capital_lamports=1_000_000_000, max_open_positions=4,
        max_in_flight_orders=3, max_daily_spend_lamports=150_000_000,
        max_daily_loss_lamports=100_000_000)
    # Both workers saw no pending order before the first acquired the SQLite
    # write lock. The second reservation must still see the committed first.
    for decision in ('worker-A', 'worker-B'):
        journal.create(decision, order_record(order), now[0])
        journal.transition(decision, ('PREPARED',), 'SIMULATED', now[0])
    journal.reserve('worker-A', now[0], **kwargs)
    with pytest.raises(ValueError, match='daily_spend'):
        journal.reserve('worker-B', now[0], **kwargs)
    assert journal.get('worker-A')['state'] == 'RESERVED'
    assert journal.get('worker-B')['state'] == 'SIMULATED'
