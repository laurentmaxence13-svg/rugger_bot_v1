"""E-1 (R02 573939a7): the rent of the base token account, read from the built SELL transaction itself."""
import asyncio

from bot.live.route import build_launchlab_order

from dryrun.cycle import run_fixture_cycle
from dryrun.harness import closes_token_account


def test_rent_recovery_follows_the_built_transaction_and_the_wallet_balances(tmp_path):
    harness, bought, sold = run_fixture_cycle(tmp_path / 'rent.jsonl')
    pnl, closed = sold['pnl'], sold['base_token_account_closed']
    assert pnl['rent_recovered_lamports'] + pnl['rent_written_off_lamports'] == pnl['rent_opened_lamports']
    assert harness.token_account_open is (not closed)
    # the wallet moved by exactly the net P&L: nothing is created or lost outside the itemised lines
    start = harness.config.simulated_wallet_lamports
    assert harness.wallet_lamports - start == pnl['net_pnl_lamports'] == harness.realized_pnl_lamports


def test_close_detector_reads_the_message_not_a_flag(tmp_path):
    harness, _, _ = run_fixture_cycle(tmp_path / 'detector.jsonl', others=())
    asyncio.run(harness.buy('detector-buy', 100_000_000))
    request = harness._request('detector-sell', 'SELL', harness.position.quantity_atomic, harness._now())
    total = build_launchlab_order(**request)
    partial = build_launchlab_order(**dict(request, amount_in=harness.position.quantity_atomic // 2))
    assert closes_token_account(partial.transaction.message, partial.base_token_account) is False
    assert closes_token_account(total.transaction.message, total.quote_token_account) is True      # WSOL, always
    # total sale: closed by the fixed chain, never by the frozen one; the harness must agree with the bytes
    sold = asyncio.run(harness.sell('detector-sell'))
    assert sold['base_token_account_closed'] is closes_token_account(total.transaction.message, total.base_token_account)
