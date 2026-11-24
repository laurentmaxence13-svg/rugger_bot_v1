import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'lpcost' / 'model.py').read_text()
MUT = [
 ("HALF = STAKE // 2", "HALF = STAKE // 3", 'not_half'),
 ("    return decision_time + hrr.clock_exit_latency_s(latency_slots)", "    return decision_time", 'no_latency'),
 ("    bought, (b0, q0) = min(buys, key=lambda pair: pair[0].output_amount)", "    bought, (b0, q0) = max(buys, key=lambda pair: pair[0].output_amount)", 'entry_best_state'),
 ("        db, dq = CC._state(line, fees, time_limit=start_time)", "        db, dq = CC._state(line, fees, time_limit=land_in)", 'guard_on_landing_state'),
 ("        if tokens < expected * (1_000_000 - buy_guard_ppm) // 1_000_000:", "        if tokens < expected * (1_000_000 - 2 * buy_guard_ppm) // 1_000_000:", 'guard_doubled'),
 ("            charged = (1 + failures.buy) * TX", "            charged = TX", 'refusal_failures_free'),
 ("    dep_b, dep_q = min(_ceil(share * b0), tokens), min(_ceil(share * q0), HALF)", "    dep_b, dep_q = min(_floor(share * b0), tokens), min(_floor(share * q0), HALF)", 'deposit_rounded_down'),
 ("    wd_b, wd_q = _floor(share * b1), _floor(share * q1)", "    wd_b, wd_q = _ceil(share * b1), _ceil(share * q1)", 'withdrawal_rounded_up'),
 ("            share = share / (1 + f)", "            share = share * (1 + f)", 'deposit_rescale_inverted'),
 ("            share = share / (1 - f)", "            share = share", 'withdrawal_not_rescaled'),
 ("        if not low_key < key <= high_key:", "        if not low_key <= key <= high_key:", 'window_low_inclusive'),
 ("    b1, q1 = min(exits, key=lambda s: Fraction(s[1], s[0]))", "    b1, q1 = max(exits, key=lambda s: Fraction(s[1], s[0]))", 'withdraw_on_best_state'),
 ("        return min(candidates)", "        return max(candidates)", 'sale_best_state'),
 ("            for bb, qq in ((b, q), (b - wd_b, q - wd_q)):", "            for bb, qq in ((b, q),):", 'sale_without_our_withdrawal'),
 ("    lp_received = wd_q + left_q + sale(wd_b + left_b)", "    lp_received = wd_q + sale(wd_b + left_b)", 'leftover_quote_lost'),
 ("    hold_received = HALF + sale(tokens)", "    hold_received = HALF + sale(tokens) + 1", 'hold_shifted'),
 ("    n = (1 + failures.buy) + 1 + 1 + (1 + failures.sell) + (1 if wsol_separate_close else 0)", "    n = (1 + failures.buy) + (1 + failures.sell) + (1 if wsol_separate_close else 0)", 'lp_tx_free'),
 ("    n = (1 + failures.buy) + 1 + 1 + (1 + failures.sell) + (1 if wsol_separate_close else 0)", "    n = 1 + 1 + 1 + (1 + failures.sell) + (1 if wsol_separate_close else 0)", 'buy_failures_free'),
 ("ACCOUNTS = 2 ", "ACCOUNTS = 1 ", 'one_rent'),
 ("        return (n + failures.cleanup) * TX, ACCOUNTS * RENT", "        return (n + failures.cleanup + 1) * TX, ACCOUNTS * RENT", 'left_open_extra_tx'),
 ("    net = lp_received - STAKE - tx_cost - rent_lost", "    net = lp_received - STAKE - tx_cost", 'rent_not_charged'),
 ("    lp_part = Fraction(curve.FEE_DENOMINATOR - fees.protocol_fee_rate - fees.fund_fee_rate, curve.FEE_DENOMINATOR)", "    lp_part = Fraction(1)", 'fee_estimate_all_fee'),
 ("        total += share_at_entry * (fee if swap.side == 'buy' else fee * spot)", "        total += share_at_entry * fee", 'fee_estimate_unvalued'),
 ("        if not land_in < swap.block_time <= land_out:", "        if not swap.block_time <= land_out:", 'fee_window_open'),
 ("    if type(start_time) is not int or type(end_time) is not int or end_time <= start_time:", "    if type(start_time) is not int or type(end_time) is not int:", 'period_unchecked'),
 ("    if buy_guard_ppm not in CC.ALLOWED_BUY_GUARDS:\n        raise LpCostError('buy_guard_not_a_declared_threshold')\n", "", 'guard_any_value'),
 ("        if event.token_0_vault_before <= 0:\n            raise LpCostError('lp_event_on_an_empty_vault')\n", "", 'empty_vault_accepted'),
 ("            if f >= 1:\n                raise LpCostError('pool_emptied_by_a_withdrawal')\n", "", 'drain_accepted'),
 ("                amm_config_sha256=config['sha256'], labels=list(LABELS), counts_for_operational_master=False)", "                amm_config_sha256=config['sha256'], labels=list(LABELS), counts_for_operational_master=True)", 'counts_for_master'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'lpcost' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'lpcost', base / 'lpcost')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'lpcost', work / 'lpcost')
    (work / 'lpcost' / 'model.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
