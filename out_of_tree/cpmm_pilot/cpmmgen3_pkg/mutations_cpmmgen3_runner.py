import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cpmmgen3' / 'rule.py').read_text()
MUT = [
 ("    limit = Fraction(barrier() if b is None else b)", "    limit = Fraction(barrier() / 2 if b is None else b)", 'barrier_halved'),
 ("        if gap(line_a, i, fees_a, line_b, j, fees_b) <= -limit:", "        if gap(line_a, i, fees_a, line_b, j, fees_b) < -limit:", 'gap_strict'),
 ("        if gap(line_a, i, fees_a, line_b, j, fees_b) <= -limit:", "        if gap(line_a, i, fees_a, line_b, j, fees_b) >= limit:", 'gap_wrong_side'),
 ("    while j + 1 < len(line_b.swaps) and (line_b.swaps[j + 1].slot, line_b.swaps[j + 1].tx_index) <= target:", "    while j + 1 < len(line_b.swaps) and (line_b.swaps[j + 1].slot, line_b.swaps[j + 1].tx_index) < target:", 'sibling_same_tx_unseen'),
 ("    while j + 1 < len(line_b.swaps) and (line_b.swaps[j + 1].slot, line_b.swaps[j + 1].tx_index) <= target:", "    while j + 1 < len(line_b.swaps) and line_b.swaps[j + 1].slot <= target[0] + 1:", 'sibling_lookahead'),
 ("    if j < 0:\n        return None, j", "    if j < 0:\n        return 0, j", 'sibling_before_first_swap'),
 ("        if j is None or (last is not None and swap.block_time - last < R.COOLDOWN_S):", "        if j is None:", 'g31_no_cooldown'),
 ("    if config_a['trade_fee_rate'] != TIER_A_PPM:\n        raise PreregError('pool_a_not_at_the_0_25_tier')\n", "", 'g31_any_tier'),
 ("    if line_a.base_mint != line_b.base_mint or line_a.quote_mint != TL.WSOL or line_b.quote_mint != TL.WSOL:", "    if line_a.quote_mint != TL.WSOL:", 'g31_any_mint'),
 ("    if line_a.pool == line_b.pool:\n        raise PreregError('sibling_is_the_pool_itself')\n", "", 'g31_self_sibling'),
 ("    if config.get('trade_fee_rate') not in MAP.CPMM_TIERS_PPM:", "    if config.get('trade_fee_rate') is None:", 'sibling_any_tier'),
 ("    if type(sha) is not str or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or type(slot) is not int:\n        raise PreregError('sibling_amm_config_not_read_and_hashed')", "    if type(sha) is not str:\n        raise PreregError('sibling_amm_config_not_read_and_hashed')", 'sibling_config_unchecked'),
 ("            and record['quote_reserve_lamports'] >= MIN_PAIR_RESERVE_LAMPORTS)", "            and record['quote_reserve_lamports'] > MIN_PAIR_RESERVE_LAMPORTS)", 'reserve_strict'),
 ("    return (record['program'] == 'cpmm' and record['quote_mint'] == TL.WSOL", "    return (record['quote_mint'] == TL.WSOL", 'pair_any_program'),
 ("    return (record['program'] == 'cpmm' and record['quote_mint'] == TL.WSOL", "    return (record['program'] == 'cpmm'", 'pair_any_quote'),
 ("            if a['trade_fee_rate'] != TIER_A_PPM:\n                continue\n", "", 'pair_a_any_tier'),
 ("                            key=lambda r: (-r['quote_reserve_lamports'], r['pool']))", "                            key=lambda r: (r['quote_reserve_lamports'], r['pool']))", 'sibling_shallowest'),
 ("                            key=lambda r: (-r['quote_reserve_lamports'], r['pool']))", "                            key=lambda r: (-r['quote_reserve_lamports'], [-ord(c) for c in r['pool']]))", 'sibling_tie_reversed'),
 ("MIN_PAIRED_MINTS = 10 ", "MIN_PAIRED_MINTS = 9 ", 'pairs_threshold_9'),
 ("    evaluable = len(mints) >= MIN_PAIRED_MINTS", "    evaluable = len(found) >= MIN_PAIRED_MINTS", 'pairs_counted_directed'),
 ("    candidates, pointer = [], -1\n    for i in range(len(line_a.swaps)):\n        j, pointer = _sibling_index(line_a, line_b, i, pointer)\n        if j is not None:\n            candidates.append(i)", "    candidates = list(range(len(line_a.swaps)))", 'placebo_without_sibling_state'),
 ("    return random.Random(int(hashlib.sha256((freeze_sheet_sha256 + pool).encode()).hexdigest()[:8], 16))", "    return random.Random(int(hashlib.sha256(freeze_sheet_sha256.encode()).hexdigest()[:8], 16))", 'placebo_seed_without_pool'),
 ("        _refuse_after_t0(line_b, t0)\n", "", 'sibling_after_t0_accepted'),
 ("        per_pool[line_a.pool] = sum(1 for i in idx if line_a.swaps[i].block_time >= start)", "        per_pool[line_a.pool] = len(idx)", 'g31_count_whole_history'),
 ("    return 0 if b58decode(line.quote_mint) < b58decode(line.base_mint) else 1", "    return 1 if b58decode(line.quote_mint) < b58decode(line.base_mint) else 0", 'quote_index_inverted'),
 ("    return event.change_type == DEPOSIT and before > 0 and before + amount >= DEPTH_FACTOR * before", "    return before > 0 and before + amount >= DEPTH_FACTOR * before", 'withdrawal_eligible'),
 ("    return event.change_type == DEPOSIT and before > 0 and before + amount >= DEPTH_FACTOR * before", "    return event.change_type == DEPOSIT and before + amount >= DEPTH_FACTOR * before", 'empty_reserve_eligible'),
 ("    return event.change_type == DEPOSIT and before > 0 and before + amount >= DEPTH_FACTOR * before", "    return event.change_type == DEPOSIT and before > 0 and before + amount > DEPTH_FACTOR * before", 'doubling_strict'),
 ("    return event.change_type == DEPOSIT and before > 0 and before + amount >= DEPTH_FACTOR * before", "    return event.change_type == DEPOSIT and before > 0 and amount * 1000 >= 999 * before", 'depth_factor_1_999'),
 ("    amount = (event.token_0_amount, event.token_1_amount)[q]", "    amount = (event.token_0_amount, event.token_1_amount)[1 - q]", 'amount_wrong_token'),
 ("        if swap.key > key:", "        if swap.key[0] >= key[0]:", 'first_swap_same_slot_before'),
 ("        if last is not None and t - last < R.COOLDOWN_S:          # also merges deposits before the same swap", "        if False:", 'g32_no_cooldown'),
 ("    evaluable = count >= MIN_ELIGIBLE_DEPOSITS", "    evaluable = count > MIN_ELIGIBLE_DEPOSITS - 2", 'deposits_threshold_29'),
 ("        per_pool[line.pool] = sum(1 for _k, i in deposit_points(line) if line.swaps[i].block_time >= start)", "        per_pool[line.pool] = len(deposit_points(line))", 'deposits_whole_history'),
 ("    if type(n_before) is not int or n_before < TRIALS_BEFORE_GEN3 or n_before + 1 > TRIAL_CAP_GEN3:", "    if type(n_before) is not int or n_before + 1 > TRIAL_CAP_GEN3:", 'trials_before_173'),
 ("TRIALS_BEFORE_GEN3, TRIAL_CAP_GEN3 = 173, 175", "TRIALS_BEFORE_GEN3, TRIAL_CAP_GEN3 = 173, 176", 'trial_cap_176'),
 ("ALPHA_GENERATION = 0.025 * 2 ** -(3 - 2)", "ALPHA_GENERATION = 0.025", 'alpha_not_halved'),
 ("        if p > ALPHA_GENERATION / (k - rank):", "        if p >= ALPHA_GENERATION / (k - rank):", 'holm_strict'),
 ("    full = {name: (1.0 if p is None else p) for name, p in p_values.items()}", "    full = {name: p for name, p in p_values.items() if p is not None}", 'holm_drops_missing_p'),
 ("    sigma_c = max(float(sigma_pilot), R.SIGMA_FLOOR)", "    sigma_c = float(sigma_pilot)", 'sigma_floor_dropped'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cpmmgen3' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'cpmmgen3', base / 'cpmmgen3')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'cpmmgen3', work / 'cpmmgen3')
    (work / 'cpmmgen3' / 'rule.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
