import sys, json, gzip, hashlib, glob
from cpmmpilot import layout as L
raw = sys.argv[1]
want = ['GaPTvX', '6CQSpR', '7SJ5UK', '5zk4vh', 'CXgcuE', 'FAn5gz', 'A3URwh', '4D17GN', 'CqvMZm', 'AsVSzv',
        'AEZjoU', 'Gms3Ma', 'G8kgi7', 'GdxFyc']
found, files = {}, {}
for f in sorted(glob.glob(raw + '/gpa_pools_*.json.gz')):
    files[f.split('/')[-1]] = hashlib.sha256(open(f, 'rb').read()).hexdigest()
    doc = json.loads(gzip.open(f).read())
    rows = doc['value'] if isinstance(doc, dict) and 'value' in doc else doc
    for r in rows:
        if r['pubkey'][:6] in want:
            p = L.decode_pool(L.raw(r['account']['data']))
            found[r['pubkey']] = dict(config=p['amm_config'][:6], creator_fee_on=p['creator_fee_on'],
                                      enable_creator_fee=p['enable_creator_fee'], status=p['status'], file=f.split('/')[-1])
for k in want:
    m = [(p, v) for p, v in found.items() if p.startswith(k)]
    print(k, m[0][1] if m else 'NOT FOUND')
print(json.dumps(dict(files=files), indent=0)[:2000])
