"""n1verdict 0.2.3 lines -- PROJECT (R02 12:42:09Z: prepared, NOT anchored until the owner text cda64700 and R02
check). 0.2.2 + cpmmrecon 0.1 (PASS R02, 49ccd25) BEFORE the positions, and G-0 COMPUTED (no more --g0):
  1. the union line (pre-T0 + window) is rebuilt by cpmmrecon.rebuild (all or nothing per transaction); the
     transactions still undecoded go to n1verdict.verdict 0.2.3 as (slot, transactionIndex) (UNDECODED rule);
  2. G-0 = cpmmcost.pool_gate (unchanged) on each named pool's WINDOW line, rebuilt the same way, as g23run 0.1.2
     does for G2-3. g0_passed = no integrity failure (an exception) on the 3 pools; a pool that is not admitted is
     excluded with its reasons (cda64700 point (3), R02 13:03Z option (a), as b1a0d629);
  3. RECONSTRUCTION.json (--reconstruction): per pool and per line (union, window), rebuilt and kept with reasons, the
     G-0 of every pool, the transactions still undecoded and the daily marks they touch (descriptive). RESULT.json is byte-identical to 0.2.2 (--g0 passed) when no transaction is truncated
     and every pool is admitted (tested), so SCHEMA is kept.
Below: the docstring of 0.2.2, unchanged.

n1verdict 0.2.2 -- the pool lines of N1 from the two collected page roots, and the one-shot verdict run (R03, AFTER
R02 anchored the N1 sheet and this code). verdict.py (0.2.1, PASS R02) is unchanged.

R03 21:59Z: the collection driver builds no line and merges nothing; assembling the pre-T0 pages and the window pages
belongs to the verdict code, which must limit the pre-T0 use to the state before T0 (R02 point (b)).
  pre-T0 pages : <pre_root>/<pool>/page_*.json.gz    (A2r, STEP1A2R_.../pre_pages, SHA256SUMS_PRE_PAGES 8fb3cac4)
  window pages : <window_root>/<pool>/page_*.json.gz (G2-3 collection, OUT/window/collect/window)
RULES: every pre-T0 transaction has block_time < T0 and every window transaction T0 <= block_time < T0 + D days (else
STOP); a signature present on both sides is refused; the line is cpmmx.timeline.build over the union. The pre-T0 part
is used by lpcost / n1verdict only through states at or before the first landing (decision state, stake, entry worse
states) and the stake of an unpriced position: every mark, fee estimate and LP event of the position is at or after
the landing after T0 (low key = last swap before the entry landing).
DECLARED LIMIT L4: the window collection stops at T0 + D days; a swap in [T0 + D d ; exit landing] (about one second)
is not in the pages, the exit state is then the last swap before T0 + D d (logged amounts, exact with the AmmConfig).
"""
import argparse
import hashlib
import json
from pathlib import Path

from cpmmcost import model as CC
from cpmmpilot import step1 as PILOT
from cpmmpilot.store import read_gz_page
from cpmmrecon import rebuild as RB
from cpmmx import timeline as TL
from n1verdict import verdict as N

SCHEMA = 'n1verdict-lines-v0.2.2'                # kept: identical RESULT without truncation (0.2.3)
RECONSTRUCTION_SCHEMA = 'n1verdict-reconstruction-v0.2.3'
POOLS = ('AEZjoUACNSpmYHHRNbfknjL8oiBDw6GhtrMm7tZgBfca', 'G8kgi7aUpeX8EVR8VMkrth9SKEv5BietWC33UjAiiMGh',
         'GdxFycQMfy5g1m1Ax2ViF8ZPAv22i27GSza7m9d6Cq4A')
POOLS_SHA256 = 'c72bd586c0de5c8441c321707a2df2019d8541bc1b0df9e24c4616ee3832a9da'      # n1rot 6b9b02a9, R02
T0 = 1795515686                                                                       # 24/11/2026 10:21:26Z
D_DAYS = 12


class LinesError(ValueError):
    pass


def page_transactions(directory, *, t0, d_days, side):
    txs = {}
    pages = sorted(Path(directory).glob('page_*.json.gz'))
    if not pages:
        raise LinesError('no_%s_page' % side)
    for page in pages:
        for tx in read_gz_page(page).get('data') or []:
            when = tx.get('blockTime')
            if type(when) is not int:
                raise LinesError('transaction_without_block_time')
            if side == 'pre' and when >= t0:
                raise LinesError('pre_t0_page_at_or_after_t0')
            if side == 'window' and not t0 <= when < t0 + d_days * N.DAY_S:
                raise LinesError('window_page_outside_the_window')
            txs[tx['transaction']['signatures'][0]] = tx
    return txs


def pool_line(pool, base_mint, pre_dir, window_dir, *, t0, d_days):
    pre = page_transactions(pre_dir, t0=t0, d_days=d_days, side='pre')
    window = page_transactions(window_dir, t0=t0, d_days=d_days, side='window')
    if set(pre) & set(window):
        raise LinesError('signature_on_both_sides')
    return TL.build(pool, {**pre, **window}, base_mint=base_mint)


def pool_sides(pool, base_mint, pre_dir, window_dir, *, t0, d_days):
    """0.2.3: ((union line, union txs), (window line, window txs)), with the checks of pool_line."""
    pre = page_transactions(pre_dir, t0=t0, d_days=d_days, side='pre')
    window = page_transactions(window_dir, t0=t0, d_days=d_days, side='window')
    if set(pre) & set(window):
        raise LinesError('signature_on_both_sides')
    union = {**pre, **window}
    return (TL.build(pool, union, base_mint=base_mint), union), (TL.build(pool, window, base_mint=base_mint), window)


def rebuilt(line, txs, row, config):
    """cpmmrecon 0.1 on one line, as g23run 0.1.2: (line, report)."""
    if not line.skipped:
        return line, dict(skipped=0, rebuilt=0, rebuilt_swaps=0, kept={}, transactions={})
    try:
        side = CC.creator_side(line, len(line.swaps) - 1) if line.swaps else None
    except CC.CostError:
        side = None
    if side is None:
        return line, dict(skipped=len(line.skipped), rebuilt=0, rebuilt_swaps=0,
                          kept={'kept:not_tried_creator_side': len(line.skipped)}, transactions={})
    new, rep = RB.rebuild(line, txs, wsol_vault=row['wsol_vault'], fees=CC.fees_from_amm_config(config), on_input=side)
    kept = {}
    for why in rep.values():
        if why.startswith('kept'):
            kept[why] = kept.get(why, 0) + 1
    return new, dict(skipped=len(line.skipped), rebuilt=sum(1 for v in rep.values() if v.startswith('rebuilt')),
                     rebuilt_swaps=len(new.swaps) - len(line.swaps), kept=kept, transactions=rep)


def undecoded_keys(line, txs):
    """(slot, transactionIndex) of the transactions still undecoded on the line, in order."""
    return sorted((txs[sig]['slot'], txs[sig]['transactionIndex']) for sig, _why in line.skipped)


def marks_touched(line, undecoded, *, t0, d_days):
    """DESCRIPTIVE (R02, 13:03Z): the daily marks (start of days 1 .. D-1) whose state is separated from the mark time by
    an undecoded transaction, as the UNDECODED rule reads it; no effect on the verdict."""
    if not undecoded:
        return 0
    return sum(1 for k in range(1, d_days) if N._span_hit(line, undecoded, t0 + k * N.DAY_S, t0 + k * N.DAY_S))


def gate(window_lines, config):
    """G-0 as g23run 0.1.2 (R02 (2)): pool_gate on every pool; an exception -> integrity failure -> g0_passed False."""
    out, ok = {}, True
    for line in window_lines:
        try:
            out[line.pool] = CC.pool_gate(line, config)
        except (ValueError, KeyError, TypeError) as exc:
            out[line.pool] = dict(admitted=False, reasons=['integrity_failure:%s' % exc])
            ok = False
    return out, ok


def prepared(selected, pre_root, window_root, config, *, pools=POOLS, t0=T0, d_days=D_DAYS):
    """0.2.3: (rebuilt union lines of the ADMITTED pools in the sheet order, undecoded, excluded, g0_passed, report)."""
    by_pool = {r['pool']: r for r in selected}
    if any(p not in by_pool for p in pools):
        raise LinesError('a_named_pool_is_missing_from_the_selection')
    lines, windows, undecoded, report = {}, [], {}, {}
    for p in pools:
        (u_line, u_txs), (w_line, w_txs) = pool_sides(p, by_pool[p]['base_mint'], Path(pre_root) / p,
                                                      Path(window_root) / p, t0=t0, d_days=d_days)
        lines[p], rep_u = rebuilt(u_line, u_txs, by_pool[p], config)
        w_new, rep_w = rebuilt(w_line, w_txs, by_pool[p], config)
        windows.append(w_new)
        undecoded[p] = undecoded_keys(lines[p], u_txs)
        report[p] = dict(union=rep_u, window=rep_w, undecoded_after=len(undecoded[p]),
                         undecoded_marks=marks_touched(lines[p], undecoded[p], t0=t0, d_days=d_days))
    gates, g0_passed = gate(windows, config)
    excluded = {p: gates[p]['reasons'] for p in pools if not gates[p]['admitted']}
    for p in pools:
        report[p]['g0'] = gates[p]
    return [lines[p] for p in pools if p not in excluded], undecoded, excluded, g0_passed, report


def lines_for(selected, pre_root, window_root, *, pools=POOLS, t0=T0, d_days=D_DAYS):
    by_pool = {r['pool']: r for r in selected}
    missing = [p for p in pools if p not in by_pool]
    if missing:
        raise LinesError('a_named_pool_is_missing_from_the_selection')
    return [pool_line(p, by_pool[p]['base_mint'], Path(pre_root) / p, Path(window_root) / p, t0=t0, d_days=d_days)
            for p in pools]


def main(argv=None):
    """python -B -m n1verdict.lines --u2 U2.json --pre-root DIR --window-root DIR --t0-slot S --sheet-sha HEX
    --result RESULT.json --reconstruction RECONSTRUCTION.json   (0.2.3: G-0 computed, no --g0)"""
    p = argparse.ArgumentParser()
    for k in ('--u2', '--pre-root', '--window-root', '--result', '--reconstruction'):
        p.add_argument(k, type=Path, required=True)
    p.add_argument('--t0-slot', type=int, required=True)
    p.add_argument('--sheet-sha', required=True)
    a = p.parse_args(argv)
    if hashlib.sha256('\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:
        raise LinesError('named_list_altered')
    if a.result.exists() or a.reconstruction.exists():
        raise LinesError('result_exists')
    u2 = json.loads(a.u2.read_text())
    if u2.get('t0_time') != T0:
        raise LinesError('t0_mismatch')
    rows = [r for r in u2['selected'] if r['pool'] in POOLS]
    config = PILOT.amm_config_for_rules(rows, a.t0_slot)
    lines, undecoded, excluded, g0_passed, recon = prepared(rows, a.pre_root, a.window_root, config, pools=POOLS,
                                                            t0=T0, d_days=D_DAYS)
    doc = N.report(lines, config, pools=list(POOLS), g0_passed=g0_passed, freeze_sheet_sha256=a.sheet_sha,
                   t0=T0, d_days=D_DAYS, undecoded=undecoded, excluded=excluded)
    doc['lines'] = dict(schema=SCHEMA, skipped_transactions={line.pool: len(line.skipped) for line in lines},
                        swaps={line.pool: len(line.swaps) for line in lines})
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n'
    a.result.write_text(text)
    print(hashlib.sha256(text.encode()).hexdigest(), a.result)
    text = json.dumps(dict(schema=RECONSTRUCTION_SCHEMA, g0_passed=g0_passed, pools=recon), indent=1, sort_keys=True,
                      ensure_ascii=False, default=str) + '\n'
    a.reconstruction.write_text(text)
    print(hashlib.sha256(text.encode()).hexdigest(), a.reconstruction)


if __name__ == '__main__':
    main()
