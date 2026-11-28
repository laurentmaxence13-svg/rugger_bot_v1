import sys, json, gzip, glob
from cpmmpilot import layout as L, rpc
run, raw = sys.argv[1], sys.argv[2]
calls = [json.loads(l) for l in open(run + '/TIME1R_20261124T102126Z/calls_u2.jsonl')]
gpa = [c for c in calls if c['method'] == 'getProgramAccounts']
shas = {c['result_sha256'] for c in gpa}
lst = json.load(open(run + '/TIME1R_20261124T102126Z/LIST_L.json'))['list']
want = {r['pool'] for r in lst}
ok = bad = 0
flags = {}
for f in sorted(glob.glob(raw + '/gpa_*.json.gz')):
    doc = json.loads(gzip.open(f).read())
    if rpc.sha(doc) in shas:
        ok += 1
    else:
        bad += 1
        print('NO MATCH', f.split('/')[-1])
    if 'gpa_pools' not in f:
        continue
    rows = doc['value'] if isinstance(doc, dict) and 'value' in doc else doc
    for r in rows:
        if r['pubkey'] in want:
            p = L.decode_pool(L.raw(r['account']['data']))
            flags[r['pubkey']] = (p['enable_creator_fee'], p['creator_fee_on'], p['amm_config'])
print('gpa calls in log', len(gpa), 'raw files matched', ok, 'unmatched', bad)
print('pools of L decoded', len(flags), 'of', len(want))
from collections import Counter
print('(enable_creator_fee, creator_fee_on) counts over L:', Counter((a, b) for a, b, _ in flags.values()))
on = sorted(p for p, v in flags.items() if v[0] or v[1])
print('pools with a flag set:', len(on))
json.dump({p: dict(enable_creator_fee=v[0], creator_fee_on=v[1], amm_config=v[2]) for p, v in sorted(flags.items())},
          open(sys.argv[3], 'w'), indent=1, sort_keys=True)
