"""T-R01-4 (recadré, fbb0538): VERIFICATION of the frozen G-1 function cpmmcost.pilot_verdict (cpmmcost 0.3, 7deb7b7)
against the pilot decision of the sheets R-CP1 (PREENREGISTREMENT_CPMM_RCP1_v0_2, 66ab4ab4) and B1 (v0_1, 7c26497f),
and of the call made by cpmmpilot 0.1 step1.g1_inputs (R03, 9169b10). NOT a package, NOT a second verdict: every
decision below is produced by the frozen function itself; this script only feeds it synthetic positions and compares the
word it returns with the word the sheet prescribes. No data is read. Output: one JSON document on stdout.
"""
import inspect
import json
import sys

from cpmmb1 import rule as B1
from cpmmcost import model as CC
from cpmmprereg import rule as RCP1
from plbench import bench as PB
from w2arms import ce as W

SHA = 'a' * 64
SHA2 = '0123456789abcdef' * 4


def rows(n_entered, pools, net, *, guard_failed=0, guard_net=-0.0105):
    out = [dict(pool='p%02d' % (i % pools), net_return=net(i), entered=True, status='entered')
           for i in range(n_entered)]
    out += [dict(pool='p%02d' % (i % pools), net_return=guard_net, entered=False, status='guard_failed')
            for i in range(guard_failed)]
    return out


def spread(center):
    return lambda i: center + 0.001 * ((i % 7) - 3)


def verdict(positions, sha=SHA, g0=True):
    return CC.pilot_verdict(positions, g0_passed=g0, freeze_sheet_sha256=sha)


def raises(fn):
    try:
        fn()
    except Exception as exc:              # noqa: BLE001 -- the type is the observation
        return '%s: %s' % (type(exc).__name__, exc)
    return None


checks = []


def check(cid, clause, expected, observed):
    checks.append(dict(id=cid, clause=clause, expected=expected, observed=observed, conforme=expected == observed))


# -- sheet § 5 "Décision du pilote" (R-CP1 66ab4ab4 l. 75-83; B1 7c26497f l. 47: same G-0 then G-1) ----------------
check('C01', 'G-0 not passed -> STOP, no number published', ['STOP', False],
      [verdict(rows(40, 20, spread(0.01)), g0=False)[k] for k in ('decision', 'published_numbers')])
check('C02', 'G-0 must be exactly True (1 or "True" -> STOP)', ['STOP', 'STOP'],
      [verdict(rows(40, 20, spread(0.01)), g0=v)['decision'] for v in (1, 'True')])
check('C03', 'freeze sheet sha required (64 hex) else error', True,
      all(raises(lambda s=s: verdict(rows(40, 20, spread(0.01)), sha=s)) for s in ('', 'A' * 64, 'a' * 63, None)))
check('C04', 'n < 30 entered -> INCONCLUSIF (29 entries, 20 pools)', 'INCONCLUSIF',
      verdict(rows(29, 20, spread(0.01)))['decision'])
check('C05', 'fewer than 20 pools -> INCONCLUSIF (30 entries, 19 pools)', 'INCONCLUSIF',
      verdict(rows(30, 19, spread(0.01)))['decision'])
check('C06', 'INCONCLUSIF before NO-GO (R-0.1 order): 29 entries all strongly negative', 'INCONCLUSIF',
      verdict(rows(29, 20, spread(-0.05)))['decision'])
check('C07', 'upper bound < 0 -> NO-GO (30 entries, 20 pools, mean -5 %)', 'NO-GO',
      verdict(rows(30, 20, spread(-0.05)))['decision'])
check('C08', 'otherwise GO_PILOTE, the maximal word (mean +1 %)', 'GO_PILOTE',
      verdict(rows(30, 20, spread(0.01)))['decision'])
check('C09', 'boundary: upper bound exactly 0 is not "< 0" -> GO_PILOTE', ['GO_PILOTE', 0.0],
      [verdict(rows(30, 20, lambda i: 0.0))[k] for k in ('decision', 'upper_bound_95_one_sided')])
g = verdict(rows(29, 20, spread(0.01), guard_failed=10))
check('C10', 'floors count ENTERED only: 29 entered + 10 guard-failed -> INCONCLUSIF, n = 39',
      ['INCONCLUSIF', 39, 29, 10], [g['decision'], g['n'], g['n_entered'], g['guard_failed']])
mix = rows(30, 20, lambda i: 0.0, guard_failed=10, guard_net=-0.0105)
m = verdict(mix)
check('C11', 'mean and bound include guard-failed fees (30 x 0 + 10 x -1.05 %) / 40', round(-0.0105 * 10 / 40, 12),
      round(m['mean_net_return'], 12))
groups = {}
for p in mix:
    groups.setdefault(p['pool'], []).append(p)
manual = -W.lower_bound(groups, lambda r: -sum(x['net_return'] for x in r) / len(r), seed=int(SHA[:8], 16),
                        draws=10_000, alpha=0.05)
check('C12', 'bound = one-sided 95 % of the mean, cluster bootstrap BY POOL, 10 000 draws, seed int(sheet[:8], 16)',
      [manual, 10_000, int(SHA[:8], 16)], [m['upper_bound_95_one_sided'], m['draws'], m['seed']])
check('C13', 'reproducible bit for bit (same input, same sheet)', True,
      verdict(rows(30, 20, spread(0.0)))['upper_bound_95_one_sided']
      == verdict(rows(30, 20, spread(0.0)))['upper_bound_95_one_sided'])
check('C14', 'labels research only, never an operational Master trade',
      [['MASTER_RESEARCH_PAPER', 'HISTORICAL_REPLAY'], False],
      [m['labels'], m['counts_for_operational_master']])

# -- what the caller must respect (constraints of the frozen function) --------------------------------------------
unpriced = rows(30, 20, spread(0.01)) + [dict(pool='p01', decision_index=3, unpriced='data_ends_before_exit')]
check('K01', 'an UNPRICED row (cpmmprereg.positions on CostError) is not accepted: caller passes priced rows only',
      'KeyError', (raises(lambda: verdict(unpriced)) or '').split(':')[0])
_k02 = raises(lambda: PB.assert_closed_vocabulary(verdict(rows(30, 20, spread(0.01)))))
check('K02', 'the output passes the closed-vocabulary check (plbench.assert_closed_vocabulary); the word found is '
      'withheld (closed vocabulary)', None, _k02 if _k02 is None else _k02.rsplit(':', 1)[0])

# -- cpmmpilot 0.1 step1.g1_inputs (9169b10) ------------------------------------------------------------------------
check('S01', 'step1 looks up pilot_verdict on the RULE modules: it must find the frozen function', [True, True],
      [getattr(RCP1, 'pilot_verdict', None) is not None, getattr(B1, 'pilot_verdict', None) is not None])
check('S02', 'step1 call verdict_fn(primary, placebo_=placebo, freeze_sheet_sha256=...) is accepted', None,
      raises(lambda: CC.pilot_verdict(rows(30, 20, spread(0.01)), placebo_=[], freeze_sheet_sha256=SHA)))

doc = dict(schema='g1verif-v0.1', frozen_function='cpmmcost.model.pilot_verdict',
           signature=str(inspect.signature(CC.pilot_verdict)), frozen_check=CC.frozen_check(), checks=checks,
           conforme=[c['id'] for c in checks if c['conforme']], ecarts=[c['id'] for c in checks if not c['conforme']])
json.dump(doc, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True, default=str)
sys.stdout.write('\n')
