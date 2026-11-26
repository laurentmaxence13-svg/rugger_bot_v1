"""D13 check (R01, read only, no network): python3 -I d13_verify.py LIVEPAPER_DIR LIVESIM_LIVE_004_POOL_DIR
Finds every transaction of the pool present in the livesim live pages but absent from the livepaper RECEIVED records,
then, for each, whether getTransaction was called for it (params sha in C.jsonl), whether a GSFA later used it as
`until` (the cursor moved past it), and every request charged in L.json but missing from C.jsonl (a failed call)."""
import gzip, hashlib, json, sys
from collections import Counter
from pathlib import Path

run, live = Path(sys.argv[1]), Path(sys.argv[2])
pool = live.name
can = lambda o: json.dumps(o, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
sha = lambda o: hashlib.sha256(can(o).encode()).hexdigest()
TXO = dict(encoding='json', maxSupportedTransactionVersion=1, commitment='confirmed')   # livepaper 0.1.2 TX_OPTIONS
recs = [json.loads(x) for x in (run / 'J.jsonl').read_text().split('\n') if x]
got = {r['signature'] for r in recs if r['kind'] == 'RECEIVED' and r['pool'] == pool}
first = min(r['block_time'] for r in recs if r['kind'] == 'RECEIVED' and r['pool'] == pool)
last = max(r['block_time'] for r in recs if r['kind'] == 'RECEIVED' and r['pool'] == pool)
txs = [t for p in sorted(live.glob('page_*.json.gz')) for t in json.load(gzip.open(p))['data']]
calls = [json.loads(x) for x in (run / 'C.jsonl').read_text().split('\n') if x]
where = {}
for i, c in enumerate(calls):
    where.setdefault(c['params_sha256'], []).append(i)
missing = [t for t in txs if first <= t['blockTime'] <= last and t['transaction']['signatures'][0] not in got]
print('pool', pool, '| livesim txs in the received span', sum(first <= t['blockTime'] <= last for t in txs),
      '| missing from livepaper', len(missing))
for t in missing:
    s = t['transaction']['signatures'][0]
    print(' missing', s[:12], 'slot', t['slot'], 'blockTime', t['blockTime'], 'err', (t.get('meta') or {}).get('err'))
    print('   getTransaction called at C.jsonl lines', where.get(sha([s, TXO])))
    print('   GSFA with until=it at lines', where.get(sha([pool, dict(limit=1000, commitment='confirmed', until=s)])))
cost = dict(getSlot=1, getSignaturesForAddress=1, getTransaction=1, getTransactionsForAddress=10)
holes = [i for i in range(len(calls) - 1)
         if calls[i + 1]['credits_after'] - calls[i]['credits_after'] != cost[calls[i + 1]['method']]]
ledger = json.loads((run / 'L.json').read_text())
logged = Counter(c['method'] for c in calls)
print('charged but not logged: after line(s)', holes, '| ledger', ledger['requests'], 'requests vs', len(calls),
      'lines | per method (ledger - log):', {m: ledger['by_method'].get(m, 0) // cost[m] - logged.get(m, 0)
                                             for m in ledger['by_method']})
