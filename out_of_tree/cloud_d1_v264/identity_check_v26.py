"""Session <-> cloud identity sample (D1 v2.6). Offline, synthetic data only (LOAD_MEASUREMENT_ONLY, never W1 data).

v2.6: the frozen report records its runtime (harness.runtime_record: kernel string of platform.platform(), full
interpreter build string, installed distributions), and the ledger quotes the sha256 of the report file. The
sha256 of these two FILES therefore differ between two machines (and changed in the R01 session when its kernel
did). The machine-independent digests are the CORE ones: the report without its "runtime" key, the ledger without
the quoted report sha256, as canonical JSON. The file digests are still printed, for information.

Builds the frozen test pack x40 (w1aux.synthetic), then the SAME code path as day J:
series (selfcheck series), run_trials (lazy + 4 workers + slim), evaluate (n_boot=200), ledger.
Prints one JSON line with the sha256 of w1_report.json, ledger.json and the bundles SHA256SUMS.
The three machines (R01 session, R03 session, cloud VM) must print the same bundles_sums_sha256,
w1_report_core_sha256 and ledger_core_sha256.
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


def canonical(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def core_digests(root):
    """Digests of the report and of the ledger without what records the machine."""
    report = json.loads((root / 'run' / 'w1_report.json').read_text())
    ledger = json.loads((root / 'ledger' / 'ledger.json').read_text())
    if 'runtime' not in report or ledger['w1_report']['sha256'] != sha(root / 'run' / 'w1_report.json'):
        raise SystemExit('unexpected_report_or_ledger_layout')
    return (canonical({k: v for k, v in report.items() if k != 'runtime'}),
            canonical(dict(ledger, w1_report={k: v for k, v in ledger['w1_report'].items() if k != 'sha256'})))


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
    report_core, ledger_core = core_digests(root)
    bundles = sorted((root / 'run' / 'bundles').iterdir())
    sums = ''.join(f'{sha(p)}  {p.name}\n' for p in bundles)
    doc = dict(sample=f'synthetic_x{K}', signatures=sum(e['signatures'] for e in json.loads((root / 'pack' / 'MANIFEST.json').read_text())['pools']),
               ledger_exit=code, w1_report_core_sha256=report_core, ledger_core_sha256=ledger_core,
               w1_report_sha256=sha(root / 'run' / 'w1_report.json'),
               ledger_sha256=sha(root / 'ledger' / 'ledger.json'), bundles_sums_sha256=hashlib.sha256(sums.encode()).hexdigest(),
               python=platform.python_version(), machine=platform.machine(), seconds=round(time.monotonic() - t0, 1))
    print(json.dumps(doc, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])
