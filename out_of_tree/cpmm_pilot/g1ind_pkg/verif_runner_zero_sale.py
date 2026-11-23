"""Cross-check, outside the tests: the zero sale of the runner (cpmmpilot.step1.zero_sale, R03) equals the rule that
g1ind checks (zero_sale_lamports, cpmmcost 0.3 constants) for every run. Needs cpmmpilot_pkg of the R03 commit on the
PYTHONPATH (git archive <commit> out_of_tree/cpmmpilot_pkg). Prints one JSON line."""
import inspect
import json

from cpmmcost import model as CC
from cpmmpilot import step1 as S1
from g1ind import report as G

row = dict(pool='p', decision_index=1, decision_time=5, unpriced='x')
takes_failures = 'failures' in inspect.signature(S1.zero_sale).parameters
out = {}
for run, failures in (('primary', CC.FROZEN_FAILURES), ('placebo', CC.FROZEN_FAILURES),
                      ('one_failure_per_tx', CC.SENSITIVITY_FAILURES)):
    z = S1.zero_sale(row, failures) if takes_failures else S1.zero_sale(row)
    try:
        G.counted([z], run)
        ok = True
    except G.ReportError:
        ok = False
    out[run] = dict(runner=z['net_lamports'], rule=G.zero_sale_lamports(failures), accepted=ok)
print(json.dumps(dict(takes_failures=takes_failures, runs=out), sort_keys=True))
