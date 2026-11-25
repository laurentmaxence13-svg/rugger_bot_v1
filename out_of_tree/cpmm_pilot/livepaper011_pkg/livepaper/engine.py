"""The live loop of livepaper 0.1.1 (0.1 PASS DE CODE R02 3c87b24 + its reserves 2-5; R04-17): event -> decision -> fictitious order -> simulated landing -> exit.

One STEP = one receipt: the new raw transactions of every pool, the receipt slot (getSlot AFTER the fetch) and the
receipt time. Per pool, in the sheet order:
  1. RECEIVED records; the raw transactions are stored as one gz page per pool and step (sha in the record);
  2. the live line (cpmmx.timeline over the live transactions; variant B: cpmmrecon 0.1, the rule of g23run 0.1.2);
     G-0 = cpmmcost.pool_gate on the line truncated at the receipt (livesim.truncated); a change is a G0 record;
  3. eligible (G-0 admitted and b3 > 0): cpmmgen2.decisions_g23 on that truncated line; a trigger swap at or after the
     start and never decided before is a LIVE decision NOW: DECISION + ORDER, anchored on the receipt (fill.py);
  4. the paired placebo: each primary decision schedules ONE placebo order on the same pool, at the first receipt
     after a delay of 60 to 1 800 s drawn from sha256(seed | pool | trigger signature) (declared seed); it needs the
     pool eligible at that receipt;
  5. every open position is resolved on the SETTLED view of its pool (swaps at most receipt slot - 150 and receipt time
     - 60 s: confirmed data that a later poll can no longer complete): LANDING once its buy landing slot is settled,
     EXIT once its exit point (TP / SL slot, or clock time) is settled, priced by fill.position (a cpmmcost error is the
     K01 zero sale of cpmmpilot.step1.zero_sale, as g23run);
  6. WAIT when a pool turns not eligible (its G-0 reasons or b3 = 0) or a placebo cannot enter; MARK every hour for
     each landed open position: the exact sale value on its settled state (descriptive, never a result);
  7. a STEP record closes the step (receipt, processing time).
The mode and the poll period are FROZEN in START (owner text 1366025b, R02): a replay or a resume with another one is
refused at the first record.
Nothing reads a datum received after the receipt; the hash chain of the journal makes the order verifiable. The
journal is also the replay: Engine on an existing journal re-derives every record from the stored pages and must find
it byte for byte (stable fields), then continues -- the same code resumes after a restart (S-2).
LABEL PAPER_LIVE_DEMO: no order, no signature, no sending; never an operational Master trade, never counted for 50/20."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from cpmmcost import model as CC
from cpmmgen2 import rule as G2
from cpmmpilot import step1 as PILOT
from cpmmpilot.store import read_gz_page, write_gz_page
from cpmmprereg import rule as R
from cpmmrecon import rebuild as RB
from cpmmx import timeline as TL
from livesim import sim as LS
from livepaper import fill as F, journal as J

SCHEMA = 'livepaper-v0.1.1'
LABEL = 'PAPER_LIVE_DEMO'
SETTLE_SLOTS, SETTLE_S = 150, 60
PLACEBO_MIN_S, PLACEBO_SPAN_S = 60, 1_741
VARIANTS = ('A', 'B')
CODE_FILES = ('engine.py', 'fill.py', 'journal.py')


class EngineError(ValueError):
    pass


def code_sha256():
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in CODE_FILES:
        h.update(name.encode() + b'\0' + (root / name).read_bytes() + b'\0')
    return h.hexdigest()


def raw_sha(raw):
    return hashlib.sha256(J.canonical(raw).encode()).hexdigest()


def placebo_delay(seed_sha, pool, signature):
    return PLACEBO_MIN_S + int(hashlib.sha256(('%s|%s|%s' % (seed_sha, pool, signature)).encode()).hexdigest()[:8],
                               16) % PLACEBO_SPAN_S


def rebuilt(line, txs, wsol_vault, config):
    """cpmmrecon 0.1 on one line, the rule of g23run 0.1.2 / livesim 0.3.2: (line, report)."""
    if not line.skipped:
        return line, dict(skipped=0, rebuilt=0)
    try:
        side = CC.creator_side(line, len(line.swaps) - 1) if line.swaps else None
    except CC.CostError:
        side = None
    if side is None:
        return line, dict(skipped=len(line.skipped), rebuilt=0)
    new, rep = RB.rebuild(line, txs, wsol_vault=wsol_vault, fees=CC.fees_from_amm_config(config), on_input=side)
    return new, dict(skipped=len(line.skipped), rebuilt=sum(1 for v in rep.values() if v.startswith('rebuilt')))


def settled_view(line, slot, time):
    return replace(line, swaps=tuple(s for s in line.swaps if s.slot <= slot and s.block_time <= time),
                   lp_changes=tuple(r for r in line.lp_changes if r[0] <= slot))


class Engine:
    """pools: [dict(pool, base_mint, wsol_vault, config, b3)] in the sheet order (the eligible pools of `prepare`)."""

    def __init__(self, pools, *, start, seed_sha, variant, journal, store, mode='gtfa', poll_s=150):
        if variant not in VARIANTS:
            raise EngineError('variant_must_be_A_or_B')
        if type(seed_sha) is not str or len(seed_sha) != 64:
            raise EngineError('seed_sha_required')
        if type(start) is not int:
            raise EngineError('start_must_be_an_integer')
        names = [p['pool'] for p in pools]
        LS.check_universe(names)                                  # pilots and 2yLFom refused, as livesim
        self.pools = {p['pool']: p for p in pools}
        self.order = names
        self.start, self.seed, self.variant = start, seed_sha, variant
        self.journal, self.store = journal, Path(store)
        self.txs = {p: {} for p in names}
        self.first_step = {p: {} for p in names}
        self.decided = {p: set() for p in names}
        self.g0 = {p: None for p in names}
        self.positions, self.due = [], []
        self.eligible = {p: None for p in names}
        self.mark_hour = None
        self.n = 0
        self.journal.append('START', schema=SCHEMA, label=LABEL, counts_for_operational_master=False,
                            start=start, seed_sha=seed_sha, variant=variant, mode=mode, poll_s=poll_s,
                            settle=[SETTLE_SLOTS, SETTLE_S],
                            code_sha256=code_sha256(),
                            pools=[dict(pool=p['pool'], base_mint=p['base_mint'], wsol_vault=p['wsol_vault'],
                                        b3=p['b3'], amm_config_sha256=p['config']['sha256']) for p in pools])
        self.journal.commit()

    # -- lines ----------------------------------------------------------------------------------------------------------
    def line(self, pool):
        row = self.pools[pool]
        line = TL.build(pool, self.txs[pool], base_mint=row['base_mint'])
        if self.variant == 'B':
            line, _rep = rebuilt(line, self.txs[pool], row['wsol_vault'], row['config'])
        return line

    def _gate(self, known, config):
        if not known.swaps:
            return dict(admitted=False, reasons=['no_live_swap'])
        try:
            g = CC.pool_gate(known, config)
        except (ValueError, KeyError, TypeError) as exc:
            return dict(admitted=False, reasons=['integrity_failure:%s' % exc])
        return dict(admitted=g['admitted'], reasons=list(g['reasons']))

    # -- one receipt ----------------------------------------------------------------------------------------------------
    def step(self, *, receipt_slot, receipt_time, batch, wall, mono_ns, gap=None, clock_ns=None):
        if type(receipt_slot) is not int or type(receipt_time) is not int:
            raise EngineError('receipt_slot_and_time_must_be_integers')
        if set(batch) - set(self.order):
            raise EngineError('transactions_of_a_pool_outside_the_universe')
        n, self.n = self.n, self.n + 1
        if gap is not None:
            self.journal.append('GAP', step=n, gap_start=gap[0], gap_end=gap[1])
        for pool in self.order:
            new = {}
            for raw in batch.get(pool, []):
                sig = raw['transaction']['signatures'][0]
                if sig in self.txs[pool] or sig in new:
                    continue
                if type(raw.get('slot')) is not int or raw['slot'] > receipt_slot:
                    raise EngineError('transaction_after_the_receipt_slot')
                new[sig] = raw
            if not new:
                continue
            ordered = sorted(new.values(), key=lambda r: (r['slot'], r.get('transactionIndex', -1)))
            page = '%s/page_%06d.json.gz' % (pool, n)
            self._page(page, ordered)
            for raw in ordered:
                sig = raw['transaction']['signatures'][0]
                self.journal.append('RECEIVED', step=n, pool=pool, signature=sig, slot=raw['slot'],
                                    block_time=raw.get('blockTime'), transaction_index=raw.get('transactionIndex'),
                                    index_source=raw.get('livepaper_index_source', 'provider'),
                                    raw_sha256=raw_sha(raw), page=page, receipt_slot=receipt_slot,
                                    receipt_time=receipt_time, wall=wall, mono_ns=mono_ns)
                self.txs[pool][sig] = raw
                self.first_step[pool][sig] = n
        known = {}
        for pool in self.order:
            row = self.pools[pool]
            k = LS.truncated(self.line(pool), receipt_time)
            known[pool] = k
            gate = self._gate(k, row['config'])
            if gate != self.g0[pool]:
                self.journal.append('G0', step=n, pool=pool, receipt_time=receipt_time, **gate)
                self.g0[pool] = gate
            ok = gate['admitted'] and row['b3'] > 0
            if ok != self.eligible[pool]:
                if not ok:
                    self.journal.append('WAIT', step=n, pool=pool, receipt_time=receipt_time,
                                        reasons=list(gate['reasons']) + ([] if row['b3'] > 0 else ['b3_zero']))
                self.eligible[pool] = ok
            if not ok:
                continue
            for i in G2.decisions_g23(k, self.txs[pool], row['b3']):
                s = k.swaps[i]
                if s.block_time < self.start or s.signature in self.decided[pool]:
                    continue
                self.decided[pool].add(s.signature)
                pid = self._order(n, pool, 'primary', k, receipt_slot, receipt_time, trigger=s, gap=gap)
                self.due.append(dict(due=receipt_time + placebo_delay(self.seed, pool, s.signature), pool=pool,
                                     primary=pid))
        for d in sorted([d for d in self.due if d['due'] <= receipt_time], key=lambda d: (d['due'], d['primary'])):
            self.due.remove(d)
            pool, row = d['pool'], self.pools[d['pool']]
            if self.g0[pool]['admitted'] and row['b3'] > 0 and known[pool].swaps:
                self._order(n, pool, 'placebo', known[pool], receipt_slot, receipt_time, primary=d['primary'])
            else:
                self.journal.append('WAIT', step=n, pool=pool, series='placebo', primary=d['primary'],
                                    reasons=['pool_not_eligible_at_the_placebo_receipt'], receipt_time=receipt_time)
        settled = {}
        for pos in self.positions:
            if pos['status'] == 'closed':
                continue
            pool = pos['pool']
            if pool not in settled:
                settled[pool] = settled_view(known[pool], receipt_slot - SETTLE_SLOTS, receipt_time - SETTLE_S)
            self._resolve(n, pos, settled[pool], receipt_slot - SETTLE_SLOTS, receipt_time - SETTLE_S)
        hour = receipt_time // 3_600
        if self.mark_hour is not None and hour != self.mark_hour:
            for pos in self.positions:
                if pos['status'] != 'landed':
                    continue
                pool = pos['pool']
                if pool not in settled:
                    settled[pool] = settled_view(known[pool], receipt_slot - SETTLE_SLOTS, receipt_time - SETTLE_S)
                try:
                    value, why = F.mark_value(settled[pool], pos['anchor'], self.pools[pool]['config']), None
                except (CC.CostError, TL.TimelineError) as exc:
                    value, why = None, str(exc)
                self.journal.append('MARK', step=n, id=pos['id'], pool=pool, series=pos['series'],
                                    mark_time=hour * 3_600, value_lamports=value, stake_lamports=CC.STAKE_LAMPORTS,
                                    unpriced=why, descriptive=True)
        self.mark_hour = hour
        done_ns = clock_ns() if clock_ns is not None else mono_ns
        self.journal.append('STEP', step=n, receipt_slot=receipt_slot, receipt_time=receipt_time, wall=wall,
                            mono_ns=mono_ns, processing_ms=(done_ns - mono_ns) / 1e6,
                            open_positions=sum(1 for p in self.positions if p['status'] != 'closed'))
        self.journal.commit()

    def _page(self, page, ordered):
        path = self.store / page
        if self.journal.replaying:                                # the stored page must be the recorded one
            if not path.exists() or read_gz_page(path)['data'] != json.loads(J.canonical(ordered)):
                raise EngineError('stored_page_differs:%s' % page)
            return
        write_gz_page(path, dict(data=ordered))

    def _order(self, n, pool, series, known, receipt_slot, receipt_time, *, trigger=None, gap=None, primary=None):
        anchor = F.Anchor(tuple(known.swaps[-1].key), receipt_slot, receipt_time)
        pid = len(self.positions)
        fields = dict(step=n, id=pid, pool=pool, series=series, entered=True, receipt_slot=receipt_slot,
                      receipt_time=receipt_time, anchor_key=list(anchor.key))
        if trigger is not None:
            fields.update(trigger_signature=trigger.signature, trigger_slot=trigger.slot,
                          trigger_key=list(trigger.key), trigger_time=trigger.block_time,
                          delay_s=receipt_time - trigger.block_time,
                          trigger_received_step=self.first_step[pool].get(trigger.signature),
                          decided_after_gap=gap is not None and trigger.block_time < gap[1])
        else:
            fields.update(primary=primary)
        self.journal.append('DECISION', **fields)
        self.journal.append('ORDER', step=n, id=pid, pool=pool, series=series, side='buy',
                            stake_lamports=CC.STAKE_LAMPORTS, receipt_slot=receipt_slot, receipt_time=receipt_time,
                            simulated=True, sent=False)
        self.positions.append(dict(id=pid, pool=pool, series=series, anchor=anchor, status='ordered'))
        return pid

    def _resolve(self, n, pos, view, settled_slot, settled_time):
        anchor, config = pos['anchor'], self.pools[pos['pool']]['config']
        land = anchor.slot + CC.LATENCY_SLOTS
        if land > settled_slot:
            return
        if pos['status'] == 'ordered':
            self.journal.append('LANDING', step=n, id=pos['id'], pool=pos['pool'], series=pos['series'],
                                buy_landing_slot=land, settled_slot=settled_slot)
            pos['status'] = 'landed'
        try:
            exit_slot, exit_time = F.exit_point(view, anchor, config)
        except (CC.CostError, R.PreregError, TL.TimelineError) as exc:
            row = self._zero_sale(pos, exc)
        else:
            if exit_slot is not None and exit_slot > settled_slot:
                return
            if exit_time is not None and exit_time > settled_time:
                return
            try:
                row = F.position(view, anchor, config, exit_slot=exit_slot, exit_time=exit_time)
            except (CC.CostError, TL.TimelineError) as exc:
                row = self._zero_sale(pos, exc)
        self.journal.append('EXIT', step=n, id=pos['id'], pool=pos['pool'], series=pos['series'],
                            status=row['status'], net_lamports=row['net_lamports'], row=json.loads(J.canonical(row)))
        pos['status'] = 'closed'

    @staticmethod
    def _zero_sale(pos, exc):
        return PILOT.zero_sale(dict(pool=pos['pool'], decision_slot=pos['anchor'].slot, unpriced=str(exc)))


# -- replay and resume ----------------------------------------------------------------------------------------------
def steps_of(records, store):
    """The inputs of every recorded step, rebuilt from the journal and the stored pages (sha checked)."""
    store = Path(store)
    received, gaps, out = {}, {}, []
    pages = {}
    for r in records:
        if r['kind'] == 'RECEIVED':
            received.setdefault(r['step'], []).append(r)
        elif r['kind'] == 'GAP':
            gaps[r['step']] = (r['gap_start'], r['gap_end'])
        elif r['kind'] == 'STEP':
            batch = {}
            for x in received.get(r['step'], []):
                if x['page'] not in pages:
                    pages[x['page']] = {t['transaction']['signatures'][0]: t
                                        for t in read_gz_page(store / x['page'])['data']}
                raw = pages[x['page']].get(x['signature'])
                if raw is None or raw_sha(raw) != x['raw_sha256']:
                    raise EngineError('stored_transaction_differs:%s' % x['signature'])
                batch.setdefault(x['pool'], []).append(raw)
            out.append(dict(receipt_slot=r['receipt_slot'], receipt_time=r['receipt_time'], batch=batch,
                            wall=r['wall'], mono_ns=r['mono_ns'], gap=gaps.get(r['step'])))
    return out


def resume(pools, *, start, seed_sha, variant, journal_path, store, mode='gtfa', poll_s=150):
    """Replay an existing journal from its stored pages (every record must be reproduced), then return the engine ready
    to continue. A fresh path starts a new journal."""
    journal = J.Journal(journal_path, replay=Path(journal_path).exists())
    recorded = list(journal.records)
    engine = Engine(pools, start=start, seed_sha=seed_sha, variant=variant, journal=journal, store=store, mode=mode,
                    poll_s=poll_s)
    for step in steps_of(recorded, store):
        engine.step(**step)
    journal.skip_runner_records()
    if journal.replaying:
        raise EngineError('journal_has_records_the_replay_did_not_reproduce')
    return engine
