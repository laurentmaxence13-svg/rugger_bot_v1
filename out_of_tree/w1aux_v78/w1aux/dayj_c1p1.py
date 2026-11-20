"""Official dayj ledger step with the C1 rule and the P1 parallel ledger (w1aux v7.8; cloud package v2.6.4, option
A2 prepared on the owner's decision of 20/11: « Préparez l'option A2 avec un plafond maximal de 66 $ TTC, sans
lancement ni engagement financier »). NOT for use before the owner's explicit approval of the C1 amendment and the
PASS of RUGGER 02 on the package (R02 257bf065).

``python -m w1aux.dayj_c1p1 --ledger-workers N --trace PATH -- <the dayj arguments of the ledger step>`` runs the
UNCHANGED ``dayj.main`` for the step ``ledger`` only, inside two declared, audited context managers:
* ``ledger_c1.c1_rule()`` (R02 PASS a03e12d0): ``ledger.verify_cycle`` checks the priced-then-relabelled outcomes
  with the C1 rule; every other outcome keeps the v7.4 result;
* ``ledger_parallel.parallel_ledger(N)`` (R02 PASS 07b3a3e6): the L1 plans are derived in N processes, files
  identical byte for byte to the sequential ledger.
dayj itself (identities, expect-sha, memory guard, digests, PASS required) is not modified: the step digest is the
dayj digest of the ``ledger/`` directory. The declaration (C1 rule, modules and sha256, workers, P1 stats) is written
to ``--trace``, OUTSIDE the dayj directory, so that no dayj digest changes. Any other step is refused.
No network.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from w1aux import dayj, ledger_c1, ledger_parallel

SCHEMA = 'rugger-dayj-ledger-c1-p1-v1'


class DayjC1P1Error(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None, *, out=None):
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(prog='w1aux.dayj_c1p1')
    parser.add_argument('--ledger-workers', type=int, required=True)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('dayj_args', nargs=argparse.REMAINDER)
    a = parser.parse_args(argv)
    args = a.dayj_args[1:] if a.dayj_args[:1] == ['--'] else a.dayj_args
    if dayj.parser().parse_args(args).step != 'ledger':
        raise DayjC1P1Error('only_the_ledger_step')
    if type(a.ledger_workers) is not int or a.ledger_workers < 1:
        raise DayjC1P1Error('ledger_workers_must_be_positive')
    if a.trace.exists():
        raise DayjC1P1Error('trace_exists')
    with ledger_c1.c1_rule() as rule, ledger_parallel.parallel_ledger(a.ledger_workers) as stats:
        code = dayj.main(args, out=out)
        stats = dict(stats)
    here = Path(__file__).resolve().parent
    trace = dict(schema=SCHEMA, step='ledger', dayj_exit_code=code, c1=rule,
                 p1=dict(module='w1aux/ledger_parallel.py', sha256=_sha(here / 'ledger_parallel.py'),
                         workers=a.ledger_workers, stats=stats),
                 launcher=dict(module='w1aux/dayj_c1p1.py', sha256=_sha(__file__)),
                 dayj=dict(module='w1aux/dayj.py', sha256=_sha(here / 'dayj.py')))
    a.trace.write_text(json.dumps(trace, sort_keys=True, indent=1, default=str) + '\n', encoding='utf-8')
    return code


if __name__ == '__main__':                                              # pragma: no cover
    raise SystemExit(main())
