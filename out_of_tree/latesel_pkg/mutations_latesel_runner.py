import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'latesel' / 'select.py').read_text()
MUT = [
 ("return len({e.fee_payer for e in history if e.side == 'buy'} - {creator})", "return len({e.fee_payer for e in history if e.side == 'buy'})", 'creator_counted_as_buyer'),
 ("positions[e.fee_payer] = positions.get(e.fee_payer, 0) - e.amount_in", "positions[e.fee_payer] = positions.get(e.fee_payer, 0)", 'sells_not_subtracted'),
 ("return sum(held[:5]) / total if total else None", "return sum(held[:1]) / total if total else None", 'top1_instead_of_top5'),
 ("if payer != creator and amount > 0), reverse=True)", "if amount > 0), reverse=True)", 'creator_in_holders'),
 ("return value >= threshold if spec['keep'] == '>=' else value <= threshold", "return value <= threshold if spec['keep'] == '>=' else value >= threshold", 'keep_inverted'),
 ("    if value is None or threshold is None:\n        return False", "    if value is None or threshold is None:\n        return True", 'missing_kept'),
 ("T1=dict(age=120, feature='unique_buyers', q=2 / 3, keep='>='),", "T1=dict(age=120, feature='unique_buyers', q=1 / 2, keep='>='),", 'tercile_changed'),
 ("            if got is None or got[1] != 'discovery':", "            if got is None or got[1] != 'screen':", 'quantiles_on_half_2'),
 ("out.append((name, k, FEATURES[spec['feature']](events[:k + 1], facts.get('creator'))))", "out.append((name, k, FEATURES[spec['feature']](events, facts.get('creator'))))", 'future_read'),
 ("        if hashlib.sha256(raw).hexdigest() != a.quantiles_sha256:", "        if False:", 'quantiles_sha_ignored'),
 ("        if doc.get('schema') != SCHEMA or doc.get('hypotheses') != json.loads(json.dumps(HYPOTHESES)):", "        if False:", 'hypotheses_check_dropped'),
 ("    out['passes'] = out['interpretable'] and out['mean_net_return'] is not None and out['mean_net_return'] > 0", "    out['passes'] = out['mean_net_return'] is not None and out['mean_net_return'] > 0", 'pass_without_floor'),
 ("            if got is None or got[1] != 'screen':", "            if got is None:", 'screen_on_both_halves'),
 ("            if got is None or got[1] != 'discovery':", "            if got is None:", 'quantiles_on_both_halves'),
 ("return value >= threshold if spec['keep'] == '>=' else value <= threshold", "return value > threshold if spec['keep'] == '>=' else value <= threshold", 'strict_tercile'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'latesel', work / 'latesel')
    (work / 'latesel' / 'select.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'latesel' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
