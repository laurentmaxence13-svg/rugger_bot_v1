"""Offline cleanup of our base token account, separate from the unchanged SELL.

Fixtures model a finalized closure (account absent from postTokenBalances,
its lamports returned to the wallet). They are not chain executions.
"""
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import struct

import pytest

from bot.live.cleanup import (
    CLEANUP_COMPUTE_UNIT_LIMIT, SUGGESTED_MAX_DUST_BURN_ATOMIC,
    PreparedBaseAccountCleanup, assert_cleanup_allowed, build_base_account_cleanup,
    journal_cleanup_refusal, reconcile_cleanup, validate_prepared_cleanup)
from bot.live.route import (COMPUTE_BUDGET_PROGRAM, TOKEN_PROGRAM,
                            associated_token_address, build_launchlab_order)
from bot.live.route_dispatch import validate_execution_order
from bot.p3.certification import _encode
from test_live_engine import configured, finalized_payload, rpc_message, run, sell_request
from test_live_wire_route import _instructions, route_request

RENT = 2_039_280
FROZEN_CHAIN = dict(  # computed from commit a054c00 (frozen chain) itself
    BUY=('4dd0a79086e66ded7ea5de86c59ed550c44b8fabd723d311ec0b440674bb6982',
         '8813b83ab022bbba744197c3080fc68a3e9a10c1aca51a510e4c085fb0948e63'),
    PARTIAL=('dc4462eba472efa1a97a114ba463a49e709fd0c8c6c58525184157eb9e4b1485',
             '6f4abc88ea6bb0899f4623ae286c5a713533a054d9488a176ef945a3be65dc2e'),
    TOTAL=('9b1ac365e0f0a4f886c5603b90821692244b0ff18e5246d14ce004cebe56c750',
           'd3a7327181d684e40d041906caf909805dad2119e2caafdbab08660869749170'))


def cleanup_request(leftover=0, *, decision='fixture-cleanup-0', **changes):
    source = route_request('SELL')
    wallet, mint = source['wallet'], source['mint']
    ata = associated_token_address(wallet, mint)
    account = source['accounts'][ata]
    raw = bytearray(base64.b64decode(account['data'][0]))
    struct.pack_into('<Q', raw, 64, leftover)
    account['data'][0] = base64.b64encode(raw).decode()
    request = dict(accounts={wallet: source['accounts'][wallet],
                             mint: source['accounts'][mint], ata: account},
        mint=mint, wallet=wallet, context_slot=1300, available_at_ms=1000,
        decision_at_ms=1100, recent_blockhash=_encode(bytes([34])*32),
        last_valid_block_height=5000, decision_id=decision,
        max_dust_burn_atomic=SUGGESTED_MAX_DUST_BURN_ATOMIC,
        compute_unit_limit=CLEANUP_COMPUTE_UNIT_LIMIT,
        priority_fee_micro_lamports=10, max_priority_fee_lamports=2)
    request.update(changes)
    return request


def cleanup_payload(cleanup, signature, *, error=None, fee=5001, rent=RENT, closed=True):
    """Finalized payload that MODELS the closure of the base token account."""
    message = rpc_message(cleanup)
    keys = message['accountKeys']
    wallet_index, base_index = keys.index(cleanup.user), keys.index(cleanup.base_token_account)
    before = [0] * len(keys); after = [0] * len(keys)
    before[wallet_index] = 10_000_000_000
    before[base_index] = rent
    token = dict(accountIndex=base_index, mint=cleanup.mint, owner=cleanup.user,
        uiTokenAmount=dict(amount=str(cleanup.burn_amount), decimals=6,
                           uiAmount=None, uiAmountString='not-used'))
    if error is not None or not closed:
        after[wallet_index] = before[wallet_index] - fee
        after[base_index] = rent
        post = [deepcopy(token)]
    else:
        after[wallet_index] = before[wallet_index] - fee + rent
        post = []
    return dict(slot=1400, version='legacy',
        transaction=dict(signatures=[signature], message=message),
        meta=dict(err=error, fee=fee, preBalances=before, postBalances=after,
                  preTokenBalances=[token], postTokenBalances=post))


def finalize(engine, rpc, decision, order):
    result = run(engine.execute(decision, order))
    assert result['state'] == 'SUBMITTED'
    rpc.status = dict(confirmationStatus='finalized', err=None, slot=1300)
    rpc.tx = finalized_payload(order, result['signature'])
    return run(engine.recover(decision))


def bought(tmp_path):
    engine, buy, rpc, signer, _ = configured(tmp_path)
    finalize(engine, rpc, json.loads(buy.rebuild_request_json)['decision_id'], buy)
    return engine, buy, rpc, signer


def totally_sold(tmp_path, *, third_party_dust=0):
    engine, buy, rpc, signer = bought(tmp_path)
    quantity = buy.expected_output
    sell = build_launchlab_order(**sell_request(quantity, quantity + third_party_dust,
                                                'fixture-total-sell'))
    sale = finalize(engine, rpc, 'fixture-total-sell', sell)
    return engine, buy, sell, sale, rpc, signer


def ledger(engine):
    return (dict(engine.journal.con.execute('SELECT * FROM positions').fetchone()),
            dict(engine.journal.con.execute('SELECT * FROM daily').fetchone()))


def test_sell_and_buy_messages_are_byte_identical_to_the_frozen_chain():
    buy = build_launchlab_order(**route_request())
    quantity = buy.expected_output
    built = dict(BUY=buy,
        PARTIAL=build_launchlab_order(**sell_request(quantity // 2, quantity, 'golden-partial')),
        TOTAL=build_launchlab_order(**sell_request(quantity, quantity, 'golden-total')))
    for name, order in built.items():
        assert (hashlib.sha256(order.transaction.message).hexdigest(),
                order.semantic_digest) == FROZEN_CHAIN[name], name
    # The total sale still closes only the temporary WSOL account.
    closes = [i for i in _instructions(built['TOTAL'].transaction.message)[3]
              if i[0] == TOKEN_PROGRAM and i[2] == b'\x09']
    assert len(closes) == 1 and closes[0][1][0] == built['TOTAL'].quote_token_account
    assert all(i[2][:1] != b'\x08' for i in _instructions(built['TOTAL'].transaction.message)[3]
               if i[0] == TOKEN_PROGRAM)


def test_cleanup_after_total_sale_returns_deposit_without_touching_sale_proceeds(tmp_path):
    engine, buy, sell, sale, rpc, signer = totally_sold(tmp_path)
    position, daily = ledger(engine)
    assert position['quantity_atomic'] == 0 and position['entry_cost_lamports'] == 0
    # Daily P&L = proceeds - costs; the sale reconciliation holds no rent.
    assert sale['reconciliation']['gross_output_lamports'] == sell.expected_output
    assert daily['realized_pnl'] == sell.expected_output - buy.input_amount - 2 * 5002
    assert_cleanup_allowed(engine.journal, mint=buy.mint, wallet=buy.user)
    cleanup = build_base_account_cleanup(**cleanup_request())
    header, keys, _, instructions = _instructions(cleanup.transaction.message)
    assert header[0] == 1 and cleanup.transaction.required_signers == (buy.user,)
    assert [i[0] for i in instructions] == [COMPUTE_BUDGET_PROGRAM, COMPUTE_BUDGET_PROGRAM, TOKEN_PROGRAM]
    assert instructions[0][2] == b'\x02' + struct.pack('<I', CLEANUP_COMPUTE_UNIT_LIMIT)
    assert instructions[1][2] == b'\x03' + struct.pack('<Q', 10)
    assert instructions[2][1] == (cleanup.base_token_account, buy.user, buy.user)
    assert instructions[2][2] == b'\x09' and cleanup.burn_amount == 0
    assert cleanup.base_token_account == sell.base_token_account
    assert cleanup.network_fee_upper_lamports == 5001
    result = reconcile_cleanup(cleanup, 'fixture-cleanup-signature',
                               cleanup_payload(cleanup, 'fixture-cleanup-signature'))
    assert result['account_closed'] is True and result['chain_error'] is None
    assert result['deposit_returned_lamports'] == RENT == position['locked_rent_lamports']
    assert result['cost_lamports'] == result['fee_lamports'] == 5001
    assert result['wallet_delta_lamports'] == RENT - 5001
    assert (result['gross_output_lamports'], result['sale_proceeds_lamports'],
            result['market_pnl_lamports']) == (0, 0, 0)
    assert result['realized_market_execution'] is False
    # Standalone reconciliation: sale ledger, P&L and signer are untouched.
    assert ledger(engine) == (position, daily)
    assert signer.calls == 2 and len(rpc.send_calls) == 2
    engine.journal.verify_audit()


def test_cleanup_refused_while_inventory_or_an_order_is_open_for_the_mint(tmp_path):
    engine, buy, rpc, _ = bought(tmp_path)
    scope = dict(mint=buy.mint, wallet=buy.user)
    assert journal_cleanup_refusal(engine.journal, **scope) == 'open_inventory_for_mint'
    quantity = buy.expected_output
    partial = build_launchlab_order(**sell_request(quantity // 2, quantity, 'fixture-partial'))
    finalize(engine, rpc, 'fixture-partial', partial)
    with pytest.raises(ValueError, match='cleanup_refused:open_inventory_for_mint'):
        assert_cleanup_allowed(engine.journal, **scope)
    rest = quantity - quantity // 2
    last = build_launchlab_order(**sell_request(rest, rest, 'fixture-rest'))
    assert run(engine.execute('fixture-rest', last))['state'] == 'SUBMITTED'
    # Submitted, not finalized: inventory is still journaled and in flight.
    assert journal_cleanup_refusal(engine.journal, **scope) == 'open_inventory_for_mint'
    rpc.tx = finalized_payload(last, engine.result('fixture-rest')['signature'])
    run(engine.recover('fixture-rest'))
    assert journal_cleanup_refusal(engine.journal, **scope) is None


def test_cleanup_refused_for_unjournaled_mint_other_wallet_unsettled_order_or_kill(tmp_path):
    engine, buy, sell, _, rpc, _ = totally_sold(tmp_path)
    journal = engine.journal
    assert journal_cleanup_refusal(journal, mint=buy.pool, wallet=buy.user) == 'no_journaled_closed_position_for_mint'
    assert journal_cleanup_refusal(journal, mint=buy.mint, wallet=buy.pool) == 'journaled_position_belongs_to_another_wallet'
    again = build_launchlab_order(**sell_request(1_000_000_000, 1_000_000_000, "fixture-unsettled"))
    with pytest.raises(ValueError):  # unowned inventory: stays SIMULATED
        run(engine.execute('fixture-unsettled', again))
    assert journal.get('fixture-unsettled')['state'] == 'SIMULATED'
    assert journal_cleanup_refusal(journal, mint=buy.mint, wallet=buy.user) == 'unsettled_order_for_mint'
    journal.release_unsent('fixture-unsettled', 1100, 'fixture_cancel')
    assert journal_cleanup_refusal(journal, mint=buy.mint, wallet=buy.user) is None
    journal.kill('fixture_kill', 1100)
    assert journal_cleanup_refusal(journal, mint=buy.mint, wallet=buy.user) == 'persistent_kill_switch_active'


def test_dust_bound_is_fixed_in_the_retained_request_and_above_it_nothing_is_built():
    request = cleanup_request(leftover=SUGGESTED_MAX_DUST_BURN_ATOMIC + 1)
    with pytest.raises(ValueError, match='leftover_exceeds_retained_dust_bound_account_left_open'):
        build_base_account_cleanup(**request)
    with pytest.raises(ValueError, match='leftover_exceeds_retained_dust_bound_account_left_open'):
        build_base_account_cleanup(**cleanup_request(leftover=1, max_dust_burn_atomic=0))
    missing = cleanup_request()
    missing.pop('max_dust_burn_atomic')
    with pytest.raises(TypeError):  # no default: never chosen at build time
        build_base_account_cleanup(**missing)
    for bad in (-1, True, 1.0, '1', 2**64):
        with pytest.raises(ValueError, match='exact_atomic_u64_required'):
            build_base_account_cleanup(**cleanup_request(max_dust_burn_atomic=bad))
    cleanup = build_base_account_cleanup(**cleanup_request(leftover=7, max_dust_burn_atomic=7))
    assert json.loads(cleanup.rebuild_request_json)['max_dust_burn_atomic'] == 7
    # Raising the bound after the fact changes the retained record.
    with pytest.raises(ValueError, match='prepared_cleanup_or_wire_modified'):
        validate_prepared_cleanup(replace(cleanup, max_dust_burn_atomic=8))


def test_third_party_dust_never_blocks_the_sale_and_is_burned_then_closed(tmp_path):
    # One atomic token is sent to our account before the exit.
    engine, buy, sell, sale, _, _ = totally_sold(tmp_path, third_party_dust=1)
    assert sale['state'] == 'RECONCILED' and sell.input_amount == buy.expected_output
    position, daily = ledger(engine)
    assert position['quantity_atomic'] == 0
    assert_cleanup_allowed(engine.journal, mint=buy.mint, wallet=buy.user)
    cleanup = build_base_account_cleanup(**cleanup_request(leftover=1))
    instructions = _instructions(cleanup.transaction.message)[3]
    burn, close = instructions[2], instructions[3]
    assert len(instructions) == 4 and cleanup.burn_amount == 1
    assert burn[0] == TOKEN_PROGRAM and burn[2] == b'\x08' + struct.pack('<Q', 1)
    assert burn[1] == (cleanup.base_token_account, buy.mint, buy.user)
    assert close[2] == b'\x09' and close[1] == (cleanup.base_token_account, buy.user, buy.user)
    result = reconcile_cleanup(cleanup, 'sig', cleanup_payload(cleanup, 'sig'))
    assert result['burned_atomic'] == 1 and result['deposit_returned_lamports'] == RENT
    assert result['sale_proceeds_lamports'] == 0 and ledger(engine) == (position, daily)
    # More dust arrived after the build: the finalized leftover differs.
    payload = cleanup_payload(cleanup, 'sig')
    payload['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = '2'
    with pytest.raises(ValueError, match='cleanup_burn_differs_from_finalized_leftover'):
        reconcile_cleanup(cleanup, 'sig', payload)


def test_duplicate_cleanup_is_refused_once_the_account_is_closed():
    request = cleanup_request(decision='fixture-cleanup-again')
    ata = associated_token_address(request['wallet'], request['mint'])
    request['accounts'][ata] = None
    with pytest.raises(ValueError, match='base_token_account_absent_nothing_to_close'):
        build_base_account_cleanup(**request)
    request['accounts'].pop(ata)
    with pytest.raises(ValueError, match='explicit_user_account_observations_required'):
        build_base_account_cleanup(**request)
    # A duplicate that reached the chain fails there: fee only, no deposit.
    cleanup = build_base_account_cleanup(**cleanup_request())
    error = {'InstructionError': [2, 'InvalidAccountData']}
    result = reconcile_cleanup(cleanup, 'sig', cleanup_payload(cleanup, 'sig', error=error))
    assert result['chain_error'] == error and result['account_closed'] is False
    assert result['deposit_returned_lamports'] == 0 and result['cost_lamports'] == 5001
    assert result['wallet_delta_lamports'] == -5001


def test_modified_cleanup_bytes_or_fields_are_detected_by_full_rebuild():
    cleanup = build_base_account_cleanup(**cleanup_request(leftover=3))
    assert validate_prepared_cleanup(cleanup) == cleanup
    message = cleanup.transaction.message
    foreign = build_base_account_cleanup(**cleanup_request(leftover=4))
    for corrupt in (
        replace(cleanup, transaction=replace(cleanup.transaction, message=message[:-1] + b'X')),
        replace(cleanup, transaction=foreign.transaction),
        replace(cleanup, burn_amount=0),
        replace(cleanup, semantic_digest='0' * 64),
        replace(cleanup, account_lamports_observed=1),
        replace(cleanup, source_slot=cleanup.source_slot + 1),
    ):
        with pytest.raises(ValueError, match='prepared_cleanup_or_wire_modified'):
            validate_prepared_cleanup(corrupt)
        with pytest.raises(ValueError, match='prepared_cleanup_or_wire_modified'):
            reconcile_cleanup(corrupt, 'sig', cleanup_payload(cleanup, 'sig'))
    with pytest.raises(ValueError, match='prepared_cleanup_rebuild_failed'):
        validate_prepared_cleanup(replace(cleanup, rebuild_request_json='{}'))
    with pytest.raises(ValueError, match='builder_generated_cleanup_required'):
        validate_prepared_cleanup(build_launchlab_order(**route_request()))
    # The finalized message must be the prepared one, not a look-alike.
    with pytest.raises(ValueError, match='finalized_message_differs_from_prepared_cleanup'):
        reconcile_cleanup(cleanup, 'sig', cleanup_payload(foreign, 'sig'))
    with pytest.raises(ValueError, match='finalized_signature_binding_failed'):
        reconcile_cleanup(cleanup, 'other', cleanup_payload(cleanup, 'sig'))


def test_cleanup_reconciliation_refuses_unclosed_account_or_unexplained_cash():
    cleanup = build_base_account_cleanup(**cleanup_request())
    with pytest.raises(ValueError, match='base_token_account_not_closed_at_finality'):
        reconcile_cleanup(cleanup, 'sig', cleanup_payload(cleanup, 'sig', closed=False))
    payload = cleanup_payload(cleanup, 'sig')
    payload['meta']['postBalances'][0] += 1  # one lamport beyond deposit - fee
    with pytest.raises(ValueError, match='cleanup_native_cash_flow_unexplained'):
        reconcile_cleanup(cleanup, 'sig', payload)
    payload = cleanup_payload(cleanup, 'sig')
    payload['meta']['postBalances'][-1] += 1
    with pytest.raises(ValueError, match='cleanup_native_cash_flow_unexplained'):
        reconcile_cleanup(cleanup, 'sig', payload)
    with pytest.raises(ValueError, match='actual_fee_exceeds_reserved_upper_bound'):
        reconcile_cleanup(cleanup, 'sig', cleanup_payload(cleanup, 'sig', fee=5002))
    payload = cleanup_payload(cleanup, 'sig')
    payload['meta']['postTokenBalances'] = None
    with pytest.raises(ValueError, match='complete_token_balances_required'):
        reconcile_cleanup(cleanup, 'sig', payload)
    payload = cleanup_payload(cleanup, 'sig')
    payload['meta']['preTokenBalances'][0]['accountIndex'] = True
    with pytest.raises(ValueError, match='cleanup_token_balance_entry_invalid'):
        reconcile_cleanup(cleanup, 'sig', payload)
    payload = cleanup_payload(cleanup, 'sig')
    payload['meta']['preTokenBalances'][0]['owner'] = cleanup.mint
    with pytest.raises(ValueError, match='cleanup_token_identity_mismatch'):
        reconcile_cleanup(cleanup, 'sig', payload)
    payload = cleanup_payload(cleanup, 'sig', error={'InstructionError': [2, 'Custom']})
    payload['meta']['postBalances'][0] += RENT
    with pytest.raises(ValueError, match='failed_cleanup_has_unexplained_balance_change'):
        reconcile_cleanup(cleanup, 'sig', payload)


def test_token2022_and_unsafe_or_foreign_accounts_are_refused():
    from bot.p3.launchlab import TOKEN_2022_PROGRAM
    request = cleanup_request()
    request['accounts'][request['mint']]['owner'] = TOKEN_2022_PROGRAM
    with pytest.raises(ValueError, match='Token2022_cleanup_not_certified'):
        build_base_account_cleanup(**request)
    request = cleanup_request()
    request['accounts'][request['mint']]['owner'] = request['wallet']
    with pytest.raises(ValueError, match='classic_SPL_mint_required_for_cleanup'):
        build_base_account_cleanup(**request)
    ata = associated_token_address(request['wallet'], request['mint'])
    for offset, value in ((108, 2), (72, 1), (129, 1), (32, 9), (0, 9)):
        request = cleanup_request()
        raw = bytearray(base64.b64decode(request['accounts'][ata]['data'][0]))
        raw[offset] = value  # frozen, delegate, close authority, owner, mint
        request['accounts'][ata]['data'][0] = base64.b64encode(raw).decode()
        with pytest.raises(ValueError, match='unsafe_or_foreign_user_base_ATA'):
            build_base_account_cleanup(**request)
    request = cleanup_request()
    request['accounts'][ata]['owner'] = TOKEN_2022_PROGRAM
    with pytest.raises(ValueError, match='unsafe_or_foreign_user_base_ATA'):
        build_base_account_cleanup(**request)
    for field, value, reason in (
            ('priority_fee_micro_lamports', 1000, 'priority_fee_limit_exceeded'),
            ('decision_at_ms', 7000, 'fresh_asof_raw_bank_required'),
            ('context_slot', 0, 'observed_context_slot_required'),
            ('compute_unit_limit', 0, 'compute_unit_limit_invalid')):
        with pytest.raises(ValueError, match=reason):
            build_base_account_cleanup(**cleanup_request(**{field: value}))
    request = cleanup_request()
    request['accounts'][request['wallet']]['lamports'] = 5000
    with pytest.raises(ValueError, match='wallet_insufficient_for_cleanup_fee'):
        build_base_account_cleanup(**request)


def test_cleanup_is_not_an_execution_route_so_no_engine_gate_can_be_bypassed(tmp_path):
    engine, buy, _, _, rpc, signer = totally_sold(tmp_path)
    cleanup = build_base_account_cleanup(**cleanup_request())
    assert type(cleanup) is PreparedBaseAccountCleanup
    with pytest.raises(ValueError, match='explicit_supported_execution_route_required'):
        validate_execution_order(cleanup)
    with pytest.raises(ValueError, match='explicit_supported_execution_route_required'):
        run(engine.execute('fixture-cleanup-0', cleanup))
    assert engine.journal.get('fixture-cleanup-0') is None
    assert signer.calls == 2 and len(rpc.send_calls) == 2
