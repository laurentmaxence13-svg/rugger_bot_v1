import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'barmap' / 'carte.py').read_text()
MUT = [
 ("RENT = 2_039_280", "RENT = 2_000_000", 'rent_changed'),
 ("BASE_FEE, FROZEN_PRIORITY = 5_000, 100_000", "BASE_FEE, FROZEN_PRIORITY = 0, 100_000", 'base_fee_zero'),
 ("    per_tx = Fraction(BASE_FEE + priority) * (1 + Fraction(failure) / (1 - Fraction(failure)))", "    per_tx = Fraction(BASE_FEE + priority) * (1 + Fraction(failure))", 'failure_linear'),
 ("    return 2 + (1 if wsol_separate else 0) + (1 if rent == 'closed' else 0)", "    return 2 + (1 if wsol_separate else 0)", 'cleanup_free'),
 ("    return 2 + (1 if wsol_separate else 0) + (1 if rent == 'closed' else 0)", "    return 2 + (1 if rent == 'closed' else 0)", 'wsol_free'),
 ("    return per_tx * transactions(rent=rent, wsol_separate=wsol_separate) + (RENT if rent == 'rent_lost' else 0)", "    return per_tx * transactions(rent=rent, wsol_separate=wsol_separate)", 'rent_never_lost'),
 ("    q2, b2 = quote * root // scale, base * scale // root", "    q2, b2 = quote * root // scale, base", 'move_not_constant_k'),
 ("    sold = curve.swap_base_input(tokens, b2, q2, f, True)", "    sold = curve.swap_base_input(tokens, b2, q2, fees(0), True)", 'sale_fee_free'),
 ("    bought = curve.swap_base_input(STAKE, quote, base, f, True)", "    bought = curve.swap_base_input(STAKE, quote, base, fees(0), True)", 'buy_fee_free'),
 ("    mid_before_buy = Fraction(quote, base)", "    mid_before_buy = Fraction(q2 if False else quote * 101 // 100, base)", 'reference_shifted'),
 ("    return float((2 * fee_for(STAKE, rate) + costs) / STAKE)         # costs: buy + sale (+ cleanup) (+ rent lost)", "    return float((fee_for(STAKE, rate) + costs) / STAKE)", 'launchlab_one_fee'),
 ("    for _ in range(60):", "    for _ in range(3):", 'bisection_short'),
 ("        if net(mid) >= 0:\n            high = mid\n        else:\n            low = mid", "        if net(mid) >= 0:\n            low = mid\n        else:\n            high = mid", 'bisection_inverted'),
 ("    return [dict(lever=name, span=span) for span, name in sorted(spans, reverse=True)]", "    return [dict(lever=name, span=span) for span, name in sorted(spans)]", 'levers_unsorted'),
 ("    if not 0 <= failure < 1:", "    if not 0 <= failure <= 1:", 'failure_one_accepted'),
]
def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'barmap' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
base = M / '_baseline'
shutil.copytree(D / 'barmap', base / 'barmap')
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'barmap', work / 'barmap')
    (work / 'barmap' / 'carte.py').write_text(src.replace(old, new))
    out.append(dict(mutant=name, detected=run(work).returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
