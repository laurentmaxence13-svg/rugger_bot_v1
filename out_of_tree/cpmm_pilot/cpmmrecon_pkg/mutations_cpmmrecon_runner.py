import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'cpmmrecon' / 'rebuild.py').read_text()
MUT = [
 ("        if why != REBUILT_CAUSE:", "        if False:", 'any_cause_rebuilt'),
 ("        if (tx.get('meta') or {}).get('err') is not None:", "        if False:", 'failed_tx_rebuilt'),
 ("            raise ReconError('other_cpmm_instruction_on_the_pool')", "            continue", 'other_cpmm_ix_ignored'),
 ("            if top2 != top or h2 <= height:\n                break", "            if top2 != top:\n                break", 'children_not_bounded'),
 ("            if h2 != height + 1 or keys[child['programIdIndex']] not in TOKEN_PROGRAMS:", "            if keys[child['programIdIndex']] not in TOKEN_PROGRAMS:", 'grandchildren_counted'),
 ("            elif data[0] == TRANSFER_CHECKED:\n                src, dst = accts[0], accts[2]", "            elif data[0] == TRANSFER_CHECKED:\n                src, dst = accts[0], accts[1]", 'checked_wrong_destination'),
 ("        if len(ins) != 1 or len(outs) != 1 or ins[0][0] == outs[0][0]:", "        if not ins or not outs:", 'transfer_count_loose'),
 ("    if net != changes:", "    if False:", 'balances_not_cross_checked'),
 ("    if not found:\n        raise ReconError('no_swap_on_the_pool')", "    if False:\n        raise ReconError('no_swap_on_the_pool')", 'no_swap_accepted'),
 ("        if (got.input_amount, got.output_amount) != (a_in, a_out):", "        if False:", 'amounts_not_checked'),
 ("            got = (curve.swap_base_input(a_in, iv, ov, fees, on_input) if exact_in\n                   else curve.swap_base_output(a_out, iv, ov, fees, on_input))", "            got = curve.swap_base_input(a_in, iv, ov, fees, on_input)", 'mode_ignored'),
 ("        buy = vault_mints[vin] == line.quote_mint", "        buy = vault_mints[vin] != line.quote_mint", 'side_inverted'),
 ("        reserves = (new_out, new_in) if buy else (new_in, new_out)", "        reserves = (new_in, new_out) if buy else (new_out, new_in)", 'reserves_inverted'),
 ("            reserves = TL.after_swap(obj, fees.protocol_fee_rate, fees.fund_fee_rate)", "            reserves = TL.after_swap(obj, 0, 0)", 'skim_ignored'),
 ("        elif kind == 'lp':\n            reserves = None", "        elif kind == 'lp':\n            pass", 'lp_state_kept'),
 ("        elif reserves is None:\n            report[obj] = 'kept:no_state_before'", "        elif reserves is None and False:\n            report[obj] = 'kept:no_state_before'", 'no_state_guard_removed'),
 ("                report[obj] = 'kept:%s' % exc\n                reserves = None", "                report[obj] = 'kept:%s' % exc", 'state_kept_after_failure'),
 ("    items += [((txs[sig]['slot'], txs[sig]['transactionIndex'], -1), 'plan', sig) for sig in plans]", "    items += [((txs[sig]['slot'] + 1, txs[sig]['transactionIndex'], -1), 'plan', sig) for sig in plans]", 'plan_misordered'),
 ("    owners = {b.get('owner') for b in balances if keys[b['accountIndex']] == wsol_vault}", "    owners = {b.get('owner') for b in balances}", 'owner_not_of_the_vault'),
 ("    base = {keys[b['accountIndex']] for b in balances if b['mint'] == base_mint and b.get('owner') == owner}", "    base = {keys[b['accountIndex']] for b in balances if b['mint'] == base_mint}", 'base_owner_unchecked'),
 ("            if child.get('stackHeight') is None:\n                raise ReconError('inner_instruction_without_stack_height')", "            if False:\n                raise ReconError('inner_instruction_without_stack_height')", 'stack_height_unchecked'),
 ("        out.append(TL.Swap(sig, tx['slot'], tx['blockTime'], tx['transactionIndex'], order, 'buy' if buy else 'sell',", "        out.append(TL.Swap(sig, tx['slot'], tx['blockTime'], tx['transactionIndex'], 0, 'buy' if buy else 'sell',", 'order_lost'),
 ("                           base, quote, event, depth))", "                           base, quote, event, 1))", 'depth_lost'),
 ("    return b'\\0' * (len(text) - len(text.lstrip('1'))) + body", "    return body", 'b58_leading_zeros_lost'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'cpmmrecon' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'cpmmrecon', base / 'cpmmrecon', ignore=shutil.ignore_patterns('__pycache__'))
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
for old, new, name in MUT:
    assert src.count(old) == 1, name
def one(m):
    old, new, name = m
    work = M / name
    shutil.copytree(D / 'cpmmrecon', work / 'cpmmrecon', ignore=shutil.ignore_patterns('__pycache__'))
    (work / 'cpmmrecon' / 'rebuild.py').write_text(src.replace(old, new))
    return dict(mutant=name, detected=run(work).returncode != 0)
with ThreadPoolExecutor(4) as ex:
    out = list(ex.map(one, MUT))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
