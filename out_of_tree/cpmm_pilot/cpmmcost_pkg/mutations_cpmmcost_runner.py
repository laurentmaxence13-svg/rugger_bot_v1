import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cpmmcost' / 'model.py').read_text()
MUT = [
 ("    land = decision.slot + latency_slots * (1 + failures.buy)", "    land = decision.slot", 'latency_zero'),
 ("    land = decision.slot + latency_slots * (1 + failures.buy)", "    land = decision.slot + latency_slots", 'buy_failure_delay_ignored'),
 ("        sale_slot = exit_slot + latency_slots * failures.sell", "        sale_slot = exit_slot", 'sale_failure_delay_ignored'),
 ("        if failures.sell:                                            # the resent sale: slots after the clock landing", "        if False:", 'clock_sale_failure_delay_ignored'),
 ("seed=int(freeze_sheet_sha256[:8], 16), draws=draws", "seed=int(freeze_sheet_sha256[-8:], 16), draws=draws", 'seed_not_the_sheet_prefix'),
 ("    bought, buy_state = min(buys, key=lambda pair: pair[0].output_amount)", "    bought, buy_state = max(buys, key=lambda pair: pair[0].output_amount)", 'h1_buy_best_case'),
 ("    sold, sell_state, kind, limit = min(candidates, key=lambda row: row[0].output_amount)", "    sold, sell_state, kind, limit = max(candidates, key=lambda row: row[0].output_amount)", 'h1_sale_best_case'),
 ("        sale_slot = exit_slot + latency_slots * failures.sell\n        limits = [dict(slot_limit=sale_slot - 1), dict(slot_limit=sale_slot)]", "        sale_slot = exit_slot + latency_slots * failures.sell\n        limits = [dict(slot_limit=sale_slot - 1)]", 'sale_before_slot_only'),
 ("    states = [_state(line, fees, slot_limit=land - 1), _state(line, fees, slot_limit=land)]", "    states = [_state(line, fees, slot_limit=land - 1)]", 'buy_before_slot_only'),
 ("        for state, kind in ((real, 'real_reserves'), (_with_our_buy(real, bought, buy_state), 'with_our_buy')):", "        for state, kind in ((_with_our_buy(real, bought, buy_state), 'with_our_buy'),):", 'sale_only_with_our_buy'),
 ("    return curve.Fees(config['trade_fee_rate'], config.get('creator_fee_rate', 0),", "    return curve.Fees(0, config.get('creator_fee_rate', 0),", 'fees_zero'),
 ("    tx_buy = (1 + failures.buy) * TX_FEE_LAMPORTS", "    tx_buy = 0", 'tx_fees_forgotten'),
 ("    tx_sell = (1 + failures.sell) * TX_FEE_LAMPORTS", "    tx_sell = TX_FEE_LAMPORTS", 'sale_failures_free'),
 ("    wsol_close = TX_FEE_LAMPORTS if wsol_separate_close else 0", "    wsol_close = 0", 'wsol_close_free'),
 ("        cleanup, rent_lost = (failures.cleanup + 1) * TX_FEE_LAMPORTS, 0", "        cleanup, rent_lost = 0, 0", 'cleanup_free'),
 ("        cleanup, rent_lost = failures.cleanup * TX_FEE_LAMPORTS, TOKEN_ACCOUNT_RENT_LAMPORTS", "        cleanup, rent_lost = failures.cleanup * TX_FEE_LAMPORTS, 0", 'left_open_rent_kept'),
 ("    if config.get('trade_fee_rate') != UNIVERSE_TRADE_FEE_RATE:", "    if False:", 'universe_unchecked'),
 ("    if type(sha) is not str or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or type(slot) is not int:", "    if False:", 'config_not_hashed_allowed'),
 ("        if type(exit_slot) is not int or exit_slot <= land:", "        if type(exit_slot) is not int or exit_slot < land:", 'exit_in_landing_slot'),
 ("        if any(s.block_time > exit_time - 1 for s in landed):", "        if False:", 'clock_guard_removed'),
 ("    if report['exact'] != report['swaps']:", "    if False:", 'gate_reproduction_skipped'),
 ("    if breaks:", "    if False:", 'gate_continuity_skipped'),
 ("    if any(s.event.input_transfer_fee or s.event.output_transfer_fee for s in line.swaps):", "    if False:", 'gate_transfer_fee_skipped'),
 ("    if line.skipped:", "    if False:", 'gate_skipped_ignored'),
 ("    if n_entered < MIN_ENTRIES or pools_entered < MIN_POOLS:", "    if pools_entered < MIN_POOLS:", 'min_entries_ignored'),
 ("    if n_entered < MIN_ENTRIES or pools_entered < MIN_POOLS:", "    if n_entered < MIN_ENTRIES:", 'min_pools_ignored'),
 ("    elif upper is None or upper < 0:", "    elif upper is None or mean < 0:", 'mean_instead_of_upper_bound'),
 ("        upper = None if low is None else -low", "        upper = low", 'bound_sign_wrong'),
 ("    if g0_passed is not True:", "    if g0_passed is False:", 'g0_none_accepted'),
 ("    if n_before + 1 > TRIAL_CAP_OUTSIDE_HW1:", "    if n_before > TRIAL_CAP_OUTSIDE_HW1:", 'trial_cap_off_by_one'),
 ("    return Fraction(in_fee) + out_fee * spot", "    return Fraction(in_fee)", 'creator_fee_in_tokens_ignored'),
 ("        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:", "        if False:", 'buy_guard_removed'),
 ("        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:", "        if tokens < expected * (1_000_000 - 2 * buy_guard_ppm) // 1_000_000:", 'buy_guard_doubled'),
 ("        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:", "        if tokens < expected * (1_000_000 - BUY_GUARD_SENSITIVITY_PPM) // 1_000_000:", 'buy_guard_always_sensitivity'),
 ("        decision_state = TL.after_swap(decision, fees.protocol_fee_rate, fees.fund_fee_rate)", "        decision_state = buy_state", 'buy_guard_reference_is_the_fill_state'),
 ("            charged = (1 + failures.buy) * TX_FEE_LAMPORTS", "            charged = 0", 'buy_guard_failure_free'),
 ("            charged = (1 + failures.buy) * TX_FEE_LAMPORTS", "            charged = TX_FEE_LAMPORTS", 'buy_guard_earlier_failures_free'),
 ("BUY_GUARD_PPM = 20_000 ", "BUY_GUARD_PPM = 25_000 ", 'buy_guard_threshold_changed'),
 ("    if buy_guard_ppm not in ALLOWED_BUY_GUARDS:", "    if False:", 'buy_guard_any_threshold'),
 ("    entered = [p for p in positions if p.get('entered', True)]", "    entered = positions", 'guard_failed_counted_as_entries'),
 ("    nets = [p['net_return'] for p in positions]", "    nets = [p['net_return'] for p in entered]", 'guard_failed_left_out_of_the_mean'),
 ("    land = decision.slot + latency_slots * (1 + failures.buy)", "    land = decision.slot + LATENCY_SLOTS * (1 + failures.buy)", 'latency_sensitivity_ignored_at_the_buy'),
 ("        sale_slot = exit_slot + latency_slots * failures.sell", "        sale_slot = exit_slot + LATENCY_SLOTS * failures.sell", 'latency_sensitivity_ignored_at_a_resent_sale'),
 ("            sale_slot = base_slot + latency_slots * failures.sell", "            sale_slot = base_slot + LATENCY_SLOTS * failures.sell", 'latency_sensitivity_ignored_at_a_resent_clock_sale'),
 ("    if type(latency_slots) is not int or latency_slots not in ALLOWED_LATENCIES:", "    if False:", 'latency_any_value'),
 ("SENSITIVITY_LATENCY_SLOTS = 10 ", "SENSITIVITY_LATENCY_SLOTS = 8 ", 'latency_sensitivity_changed'),
 ("        if found[key] != value:", "        if False:", 'frozen_code_unchecked'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cpmmcost' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)


# BASELINE GUARD (R02 21:34Z): the unmutated copy must pass first, or nothing is reported
base = M / '_baseline'
shutil.copytree(D / 'cpmmcost', base / 'cpmmcost')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cpmmcost', work / 'cpmmcost')
    (work / 'cpmmcost' / 'model.py').write_text(src.replace(old, new))
    r = run(work)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
