"""Prepared APART (separate process, never imported by v4sim): the synthetic x40 archive pack and the
series used by the anchored references 4aee76a3 / ba14a5db. Needs w1aux v7.3 on PYTHONPATH."""
import hashlib, json, sys
from pathlib import Path
from w1aux import dayj, synthetic
out = Path(sys.argv[1]); out.mkdir(parents=True)
doc = synthetic.build(out / 'x40', 40)
dayj._selfcheck_series(out / 'series.json')
print(json.dumps(dict(x40_manifest_sha256=hashlib.sha256((out / 'x40' / 'MANIFEST.json').read_bytes()).hexdigest(),
                      pools=len(doc['pools']), series_sha256=hashlib.sha256((out / 'series.json').read_bytes()).hexdigest())))
