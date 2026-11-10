"""The complete offline BUY -> hold -> SELL cycle and its cost arithmetic."""
import asyncio

import pytest

from bot.p3 import launchlab

from dryrun import CostModel, FLAGS, Refusal, ShadowPosition, SyntheticBank, verify_journal
from dryrun.cycle import OTHERS, run_fixture_cycle
from dryrun.fixtures import launchlab_fixture

run = asyncio.run
BUY = 100_000_000


def test_cycle_builds_with_frozen_builder_preflights_and_closes_shadow_position(tmp_path):
    path = tmp_path / 'cycle.jsonl'
    harness, bought, sold = run_fixture_cycle(path)
    records = verify_journal(path)
    assert [r['kind'] for r in records] == [
        'open', 'order_built', 'preflight', 'shadow_fill',
        'others_trade', 'others_trade', 'others_trade',
        'order_built', 'preflight', 'shadow_fill']
    assert all(r[flag] is value for r in records for flag, value in FLAGS.items())
    # Independent integer oracle for the fixture pool (x=9e14, y=35e9, 17500 ppm).
    fee = -(-BUY * 17500 // 1_000_000)
    out = (BUY - fee) * 9 * 10**14 // (35 * 10**9 + BUY - fee)
    assert (bought['amount_out'], bought['curve_fee_lamports']) == (out, fee)
    built = [r for r in records if r['kind'] == 'order_built']
    # The shadow fill is the quantity the frozen builder itself expected.
    assert built[0]['expected_output'] == bought['amount_out']
    assert built[1]['expected_output'] == sold['amount_out']
    assert built[1]['intent'] == dict(side='SELL', amount_in=bought['amount_out'])
    preflights = [r for r in records if r['kind'] == 'preflight']
    assert [p['result'] for p in preflights] == ['SIMULATION_SUCCEEDED_UNSENT'] * 2
    assert all(p['simulated_by_rpc_node'] is False for p in preflights)
    assert [p['message_sha256'] for p in preflights] == [b['message_sha256'] for b in built]
    # Only all-zero-signature wires ever reached the fixture RPC.
    assert len(harness.rpc.simulated) == 2
    assert all(raw[:65] == b'\x01' + bytes(64) for raw in harness.rpc.simulated)
    assert sold['position_closed'] is True and harness.position == ShadowPosition()


def test_sell_order_is_built_on_the_pool_state_advanced_by_others(tmp_path):
    harness, bought, sold = run_fixture_cycle(tmp_path / 'held.jsonl')
    _, _, immediate = run_fixture_cycle(tmp_path / 'immediate.jsonl', others=())
    built = [r for r in harness.journal.records if r['kind'] == 'order_built']
    assert built[1]['source_slot'] == built[0]['source_slot'] + 1 + len(OTHERS)
    others = [r for r in harness.journal.records if r['kind'] == 'others_trade']
    assert others[0]['curve_before'] == bought['curve_after']
    assert sold['curve_before'] == others[-1]['curve_after']
    assert sold['amount_out'] != immediate['amount_out']
    # An immediate round trip only loses: fees and floor rounding.
    assert immediate['pnl']['curve_move_lamports'] <= 0


def test_net_pnl_is_itemised_and_equals_the_simulated_wallet_delta(tmp_path):
    costs = CostModel(priority_fee_micro_lamports=2500, failed_attempts_per_order=2)
    harness, bought, sold = run_fixture_cycle(tmp_path / 'costs.jsonl', costs=costs)
    pnl = sold['pnl']
    assert costs.priority_fee_lamports == 500 and costs.attempt_fee_lamports == 5500
    assert pnl['curve_fees_lamports'] == bought['curve_fee_lamports'] + sold['curve_fee_lamports']
    assert pnl['base_fees_lamports'] == 2 * 5000
    assert pnl['priority_fees_lamports'] == 2 * 500
    assert (pnl['failed_attempts'], pnl['failed_attempts_lamports']) == (4, 4 * 5500)
    assert pnl['rent_opened_lamports'] == pnl['rent_written_off_lamports'] == 2_039_280
    assert pnl['rent_recovered_lamports'] == 0
    assert pnl['net_pnl_lamports'] == (
        pnl['curve_move_lamports'] - pnl['curve_fees_lamports'] - pnl['base_fees_lamports']
        - pnl['priority_fees_lamports'] - pnl['failed_attempts_lamports']
        - pnl['rent_written_off_lamports'])
    assert pnl['net_pnl_lamports'] == (
        harness.wallet_lamports - harness.config.simulated_wallet_lamports)
    assert harness.realized_pnl_lamports == pnl['net_pnl_lamports']
    # The priority fee is in the order the frozen builder produced, not only in the model.
    built = [r for r in harness.journal.records if r['kind'] == 'order_built']
    assert [b['network_fee_upper_lamports'] for b in built] == [5500, 5500]
    assert all(type(value) is int for value in pnl.values())


def test_wallet_without_funds_is_refused_by_the_unpatched_builder(open_harness):
    harness = open_harness(simulated_wallet_lamports=0)
    with pytest.raises(Refusal, match='builder:wallet_insufficient_for_input_rent_and_fees'):
        run(harness.buy('no-funds', BUY))
    assert [r['kind'] for r in harness.journal.records] == ['open', 'refusal']
    assert harness.position == ShadowPosition()
    assert harness.journal.records[0]['wallet_balance_is_simulated'] is True


def test_failed_attempts_must_be_affordable_from_the_simulated_balance(open_harness):
    exact = BUY + 5000 + 2 * 2_039_280  # input, fee, new token account, temporary WSOL rent
    harness = open_harness(simulated_wallet_lamports=exact,
                           costs=CostModel(failed_attempts_per_order=1))
    with pytest.raises(Refusal, match='simulated_wallet_insufficient_with_failed_attempts'):
        run(harness.buy('decision-1', BUY))
    assert harness.position == ShadowPosition() and harness.pending == []


def test_shadow_fill_must_equal_what_the_frozen_builder_expected(open_harness, monkeypatch):
    harness = open_harness()
    # A dry-run fee rate that differs from the one the builder decodes on chain.
    monkeypatch.setattr(SyntheticBank, 'fee_rate_ppm', property(lambda self: 17_499))
    with pytest.raises(Refusal, match='builder_and_dry_run_arithmetic_disagree'):
        run(harness.buy('decision-1', BUY))
    assert [r['kind'] for r in harness.journal.records] == ['open', 'refusal']
    assert harness.position == ShadowPosition()


def test_bank_moves_pool_and_vault_bytes_together_and_stays_qualified():
    bank, request = launchlab_fixture()

    def vaults():
        base = launchlab._vault(bank.accounts[bank.addresses['vault_a']], 'base')[0]
        quote = launchlab._vault(bank.accounts[bank.addresses['vault_b']], 'quote')[0]
        return base['amount_atomic'], quote['amount_atomic'], quote['account_lamports']
    start = vaults()
    bought = bank.quote('BUY', BUY)
    bank.apply(bought)
    net = BUY - bought.fee
    assert vaults() == (start[0] - bought.amount_out, start[1] + net, start[2] + net)
    assert bank.curve == bought.after and bank.context_slot == request['context_slot'] + 1
    with pytest.raises(ValueError, match='fill_not_quoted_on_current_bank_state'):
        bank.apply(bought)
    sold = bank.quote('SELL', bought.amount_out)
    bank.apply(sold)
    gross = sold.amount_out + sold.fee
    assert vaults() == (start[0], start[1] + net - gross, start[2] + net - gross)
    # The frozen analysis still sees a coherent, unflagged bank after the writes.
    analysis = launchlab.analyze_snapshot(
        bank.snapshot(), context_slot=bank.context_slot, expected_mint=bank.mint,
        pool_address=bank.pool_address, input_lamports=BUY,
        evidence_profile='published_metadata_v1')
    assert analysis['risk_flags'] == [] and analysis['conditional_projection'] is not None
    # The fixture mapping handed to the bank was copied, never written to.
    assert launchlab._pool(request['accounts'][bank.pool_address])[0]['real_a'] == 10**14


def test_refused_preflight_blocks_the_shadow_fill_until_it_passes(open_harness):
    harness = open_harness()
    harness.rpc.block_height = 5001  # past the order's last valid block height (5000)
    with pytest.raises(Refusal, match='preflight:blockhash_expired_before_simulation'):
        run(harness.buy('decision-1', BUY))
    assert [r['kind'] for r in harness.journal.records] == [
        'open', 'order_built', 'preflight', 'refusal']
    assert harness.journal.records[2]['result'] == 'REFUSED'
    assert harness.rpc.simulated == []
    assert harness.position == ShadowPosition() and harness.pending == ['decision-1']
    harness.rpc.block_height = 4900
    bought = run(harness.buy('decision-1', BUY))
    assert harness.position.quantity_atomic == bought['amount_out']


def test_second_cycle_reuses_the_open_token_account_without_new_rent(tmp_path):
    harness, _, first = run_fixture_cycle(tmp_path / 'twice.jsonl', others=())
    again = run(harness.buy('dry-run-buy-2', BUY))
    second = run(harness.sell('dry-run-sell-2'))
    assert again['costs']['rent_opened_lamports'] == 0
    assert first['pnl']['rent_written_off_lamports'] == 2_039_280
    assert second['pnl']['rent_written_off_lamports'] == 0
    assert harness.realized_pnl_lamports == (
        first['pnl']['net_pnl_lamports'] + second['pnl']['net_pnl_lamports'])


def test_same_inputs_write_the_same_journal(tmp_path):
    first, _, _ = run_fixture_cycle(tmp_path / 'a.jsonl')
    second, _, _ = run_fixture_cycle(tmp_path / 'b.jsonl')
    assert first.journal.head == second.journal.head
    assert (tmp_path / 'a.jsonl').read_bytes() == (tmp_path / 'b.jsonl').read_bytes()
