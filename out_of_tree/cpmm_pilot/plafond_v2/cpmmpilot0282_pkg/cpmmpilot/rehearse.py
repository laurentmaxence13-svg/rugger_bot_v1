"""T-R03-1: OFFLINE REHEARSAL of the whole pilot chain on the synthetic fake chain (no network by construction).

  python -B -m cpmmpilot.rehearse --out <NEW DIR>

Order: step 0 (synthetic vectors) -> U-2 (snapshot, list L hashed, permutation, creation by GTFA) -> step 1 (1) count
-> point-(2) rule -> (2) pre-T0 collection + trigger counts -> (3) freeze sheets + simulated R02 anchor -> (4) window
collection INTERRUPTED half-way then RESUMED (container-restart drill) -> (5) G-1 inputs -> archive in parts.
Extra drills: credit hard stop, GTFA refused, truncated getProgramAccounts, list < 20, anchor mismatch."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from . import budget as B
from . import fixtures, step0, step1, u2
from .rpc import Client
from .store import archive_parts, file_sha, sha256sums, write_json

HERE = Path(__file__).resolve().parent


def code_sha():
    files = sorted(p for p in HERE.rglob('*.py') if '__pycache__' not in p.parts)
    return {p.relative_to(HERE.parent).as_posix(): file_sha(p) for p in files}


class Interrupt(RuntimeError):
    pass


class Flaky:
    """Transport that dies after ``n`` window-collection calls (simulated container restart)."""

    def __init__(self, inner, n):
        self.inner, self.n = inner, n

    def request(self, method, params):
        if method == 'getTransactionsForAddress' and params[1].get('filters'):
            if self.n == 0:
                raise Interrupt('simulated_container_restart')
            self.n -= 1
        return self.inner.request(method, params)


def _client(transport, out, stage, cap):
    return Client(transport, B.PilotBudget(out / ('ledger_%s.json' % stage), stage=stage, max_credits=cap),
                  out / ('calls_%s.jsonl' % stage))


def main_chain(out, journal):
    chain, spec = fixtures.build()
    t0, t0_slot = spec['t0_time'], spec['t0_slot']
    final_slot = chain.slot
    chain.slot = t0_slot                                      # the chain as seen at T0
    write_json(out / 'FIXTURE_SPEC.json', spec)
    # step 0 -- synthetic vectors: 60 swap signatures of the first valid pool
    valid0 = next(p for p in spec['pools'] if p['kind'] == 'valid')['pool']
    sigs = [t['transaction']['signatures'][0] for t in chain.history[valid0][1:61]]
    vf = out / 'vectors_V1prime_SYNTHETIC.txt'
    vf.write_text('\n'.join(sigs) + '\n')
    c0 = _client(chain, out, 'step0', B.STEP0_CAP)
    journal.append(('step0', step0.run(c0, out / 'step0', vf, file_sha(vf))))
    # U-2
    cu = _client(chain, out, 'u2', B.U2_CAP)
    doc = u2.run(cu, out / 'u2', t0_time=t0)
    journal.append(('u2', {k: doc[k] for k in ('verdict', 'counts', 'sha_l', 'permutation_seed', 'tested',
                                                'creation_reasons', 'budget')}))
    selected = doc['selected']
    pools = [r['pool'] for r in selected]
    # step 1
    c1 = _client(chain, out, 'step1', B.STEP1_HARD_STOP)
    cnt = step1.count_24h(c1, pools, t0_time=t0)
    journal.append(('step1.1_count', dict(r_hat=cnt['r_hat'], point2=cnt['point2'], d_max=cnt['d_max_days'])))
    if cnt['point2']['stop']:
        journal.append(('step1.point2', 'STOP'))
        return
    step1.collect(c1, out / 'step1', pools, start_time=t0 - 7 * step1.DAY, end_time=t0, phase='pre')
    trig = step1.trigger_counts(out / 'step1', selected, t0_time=t0, t0_slot=doc['t0_slot'])
    journal.append(('step1.2_triggers', dict(rcp1=trig['rcp1']['triggers'], b1=trig['b1']['triggers'],
                                             skipped=trig['skipped_transactions'])))
    d_days = min(spec['window_days'], cnt['d_max_days'])
    sheets = step1.freeze_sheets(out / 'step1', u2_doc=doc, count_doc=cnt, triggers=trig, d_days=d_days,
                                 code_sha=code_sha())
    journal.append(('step1.3_freeze_sheets', sheets))
    anchored = dict(sheets)                                   # stands for R02's anchor in the rehearsal
    step1.check_anchor(out / 'step1', anchored)
    chain.slot = final_slot                                   # after T0 + D: the window now exists on chain
    end = t0 + int(d_days * step1.DAY)
    flaky = _client(Flaky(chain, 3), out, 'step1', B.STEP1_HARD_STOP)
    try:
        step1.collect(flaky, out / 'step1', pools, start_time=t0, end_time=end, phase='window')
        journal.append(('step1.4_restart_drill', 'NO_INTERRUPTION (unexpected)'))
    except Interrupt:
        credits_at_cut = flaky.budget.credits
        resumed = _client(chain, out, 'step1', B.STEP1_HARD_STOP)        # new process: ledger re-read
        states = step1.collect(resumed, out / 'step1', pools, start_time=t0, end_time=end, phase='window')
        journal.append(('step1.4_restart_drill', dict(
            credits_at_cut=credits_at_cut, credits_after_resume=resumed.budget.credits,
            ledger_monotone=resumed.budget.credits >= credits_at_cut, all_done=all(s['done'] for s in states.values()),
            window_transactions=sum(s['transactions'] for s in states.values()))))
    cut = json.loads((out / 'step1' / 'FICHE_GEL_RCP1.json').read_text())['cut_time']
    g1 = step1.g1(out / 'step1', selected, t0_slot=doc['t0_slot'], sheets=sheets, g0_passed=True,   # G-0 anchored by R02
                  cut_time=cut)
    journal.append(('step1.5_g1', g1))
    journal.append(('budgets', dict(step0=c0.budget.snapshot(), u2=cu.budget.snapshot(),
                                    step1=B.PilotBudget(out / 'ledger_step1.json', stage='step1',
                                                        max_credits=B.STEP1_HARD_STOP).snapshot())))


def drills(out, journal):
    res = {}
    # credit hard stop
    b = B.PilotBudget(out / 'drill_ledger.json', stage='step1', max_credits=B.STEP1_HARD_STOP)
    b.credits = B.STEP1_HARD_STOP - 5
    try:
        b.charge('getTransactionsForAddress', ['x', dict(limit=100)])
        res['hard_stop_49000'] = 'NOT STOPPED'
    except B.BudgetExhausted as exc:
        res['hard_stop_49000'] = 'STOP ' + str(exc)
    res['point2_at_1692'] = B.point2_stop(1692)['stop']
    res['point2_at_1693'] = B.point2_stop(1693)['stop']
    # GTFA refused / truncated gPA / list < 20
    for name, kw in (('gtfa_refused', dict(gtfa_refused=True)), ('gpa_truncated', dict(truncate=True)),
                     ('list_below_20', dict(n_pools=18))):
        chain, spec = fixtures.build(**kw)
        chain.slot = spec['t0_slot']
        d = out / ('drill_' + name)
        try:
            r = u2.run(_client(chain, d, 'u2', B.U2_CAP), d / 'u2', t0_time=spec['t0_time'])
            res[name] = r['verdict'] + (' (%s)' % r.get('reason', ''))
        except u2.U2Stop as exc:
            res[name] = 'STOP ' + str(exc)
    # anchor mismatch
    try:
        step1.check_anchor(out / 'step1', dict(RCP1='0' * 64, B1='0' * 64))
        res['anchor_mismatch'] = 'NOT STOPPED'
    except step1.Step1Stop as exc:
        res['anchor_mismatch'] = 'STOP ' + str(exc)
    journal.append(('drills', res))


def main(argv=None):
    p = argparse.ArgumentParser(prog='cpmmpilot.rehearse')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    if a.out.exists():
        raise SystemExit('out_exists')
    a.out.mkdir(parents=True)
    started = time.time()
    journal = []
    main_chain(a.out, journal)
    drills(a.out, journal)
    sums = sha256sums(a.out / 'step1')
    parts = archive_parts(a.out / 'step1', a.out / 'archive', part_bytes=256 * 1024)
    journal.append(('archive', dict(step1_sha256sums=sums, archive_sha256=parts['archive_sha256'],
                                    parts=len(parts['parts']), largest_part=max(x['bytes'] for x in parts['parts']))))
    doc = dict(schema='cpmmpilot-rehearsal-v0.1', synthetic=True, network=False, seconds=round(time.time() - started, 1),
               code=code_sha(), journal=journal)
    write_json(a.out / 'REHEARSAL_JOURNAL.json', doc)
    print(json.dumps(dict(journal_sha256=file_sha(a.out / 'REHEARSAL_JOURNAL.json'), seconds=doc['seconds'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
