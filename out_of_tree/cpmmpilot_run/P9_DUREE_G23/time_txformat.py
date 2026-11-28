import sys,json,time
from pathlib import Path
from cpmmpilot import step1
out,u2=Path(sys.argv[1]),sys.argv[2]
POOLS=[p.name for p in (out/'collect'/'window').iterdir() if p.is_dir()]
sel=[r for r in json.load(open(u2))['selected'] if r['pool'] in POOLS]
n=sum(len(list((out/'collect'/'window'/r['pool']).glob('page_*.json.gz'))) for r in sel)
t=time.perf_counter()
try:
  r=step1.require_tx_format(out,'window',sel); ok='ok'
except Exception as e: r=None; ok=type(e).__name__+':'+str(e)[:80]
dt=time.perf_counter()-t
print(json.dumps(dict(pools=len(sel),pages=n,seconds=round(dt,1),s_per_page=round(dt/n,4),result=ok,tx=sum((r or {}).get('transactions_by_version',{}).values()))))
