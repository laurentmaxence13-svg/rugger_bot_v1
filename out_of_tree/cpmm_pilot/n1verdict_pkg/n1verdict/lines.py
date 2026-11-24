"""n1verdict 0.2.2 -- the pool lines of N1 from the two collected page roots, and the one-shot verdict run (R03, AFTER
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

from cpmmpilot import step1 as PILOT
from cpmmpilot.store import read_gz_page
from cpmmx import timeline as TL
from n1verdict import verdict as N

SCHEMA = 'n1verdict-lines-v0.2.2'
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


def lines_for(selected, pre_root, window_root, *, pools=POOLS, t0=T0, d_days=D_DAYS):
    by_pool = {r['pool']: r for r in selected}
    missing = [p for p in pools if p not in by_pool]
    if missing:
        raise LinesError('a_named_pool_is_missing_from_the_selection')
    return [pool_line(p, by_pool[p]['base_mint'], Path(pre_root) / p, Path(window_root) / p, t0=t0, d_days=d_days)
            for p in pools]


def main(argv=None):
    """python -B -m n1verdict.lines --u2 U2.json --pre-root DIR --window-root DIR --t0-slot S --sheet-sha HEX
    --g0 passed|not_passed --result RESULT.json"""
    p = argparse.ArgumentParser()
    for k in ('--u2', '--pre-root', '--window-root', '--result'):
        p.add_argument(k, type=Path, required=True)
    p.add_argument('--t0-slot', type=int, required=True)
    p.add_argument('--sheet-sha', required=True)
    p.add_argument('--g0', choices=('passed', 'not_passed'), required=True)
    a = p.parse_args(argv)
    if hashlib.sha256('\n'.join(POOLS).encode()).hexdigest() != POOLS_SHA256:
        raise LinesError('named_list_altered')
    if a.result.exists():
        raise LinesError('result_exists')
    u2 = json.loads(a.u2.read_text())
    if u2.get('t0_time') != T0:
        raise LinesError('t0_mismatch')
    rows = [r for r in u2['selected'] if r['pool'] in POOLS]
    lines = lines_for(rows, a.pre_root, a.window_root, pools=POOLS, t0=T0, d_days=D_DAYS)
    config = PILOT.amm_config_for_rules(rows, a.t0_slot)
    doc = N.report(lines, config, pools=list(POOLS), g0_passed=a.g0 == 'passed', freeze_sheet_sha256=a.sheet_sha,
                   t0=T0, d_days=D_DAYS)
    doc['lines'] = dict(schema=SCHEMA, skipped_transactions={line.pool: len(line.skipped) for line in lines},
                        swaps={line.pool: len(line.swaps) for line in lines})
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n'
    a.result.write_text(text)
    print(hashlib.sha256(text.encode()).hexdigest(), a.result)


if __name__ == '__main__':
    main()
