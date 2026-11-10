"""Session <-> cloud identity sample (D1). Offline, synthetic data only (LOAD_MEASUREMENT_ONLY, never W1 data).

Builds the frozen test pack x40 (w1aux.synthetic), then the SAME code path as day J:
series (selfcheck series), run_trials (lazy + 4 workers + slim), evaluate (n_boot=200), ledger.
Prints one JSON line with the sha256 of w1_report.json, ledger.json and the bundles SHA256SUMS.
The three machines (R01 session, R03 session, cloud VM) must print the same three digests.
Usage (cwd = checkout of tree aff97638, PYTHONPATH=<w1aux_pkg>:<checkout>, RUGGER_NO_DOTENV=1):
    python -B identity_check.py <empty work dir>
"""
import hashlib, io, json, platform, sys, time
from pathlib import Path
from bot.market import w1_collection
from bot.master_v2 import w1_run as run
from w1aux import dayj as D, lazy, ledger as L, parallel, synthetic

K, WORKERS, N_BOOT = 40, 4, 200
S0 = 464661843 - w1_collection.WARMUP_SLOTS
REGISTERED_AT = '2026-11-09T00:00:00+00:00'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root):
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise SystemExit('work_dir_not_empty')
    root.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    synthetic.build(root / 'pack', K)
    D._selfcheck_series(root / 'series.json')
    with lazy.lazy_archives(), parallel.parallel_replays(WORKERS, root / 'checkpoint'), D.slim_l1_trial_documents():
        run.run_trials(root / 'pack', root / 'series.json', registry_path=root / 'r.jsonl',
                       sensitivity_registry_path=root / 's.jsonl', registered_at=REGISTERED_AT, out=root / 'run')
    with lazy.lazy_archives():
        run.evaluate(root / 'pack', root / 'run', S0, registry_paths=[root / 'r.jsonl'], registry_path=root / 'r.jsonl',
                     sensitivity_registry_path=root / 's.jsonl', n_boot=N_BOOT)
    code = L.main(['--pools', str(root / 'pack'), '--bundles', str(root / 'run' / 'bundles'),
                   '--report', str(root / 'run' / 'w1_report.json'), '--series', str(root / 'series.json'),
                   '--out', str(root / 'ledger')], out=io.StringIO())
    bundles = sorted((root / 'run' / 'bundles').iterdir())
    sums = ''.join(f'{sha(p)}  {p.name}\n' for p in bundles)
    doc = dict(sample=f'synthetic_x{K}', signatures=sum(e['signatures'] for e in json.loads((root / 'pack' / 'MANIFEST.json').read_text())['pools']),
               ledger_exit=code, w1_report_sha256=sha(root / 'run' / 'w1_report.json'),
               ledger_sha256=sha(root / 'ledger' / 'ledger.json'), bundles_sums_sha256=hashlib.sha256(sums.encode()).hexdigest(),
               python=platform.python_version(), machine=platform.machine(), seconds=round(time.monotonic() - t0, 1))
    print(json.dumps(doc, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])
