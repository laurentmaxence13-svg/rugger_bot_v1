"""livepaper 0.1.3 commands (R03; `collect-gsfa` and `run` cannot open the network in 0.1):
  prepare      --eligible ELIGIBLE.json --eligible-sha <anchored by R02> --list-l LIST_L.json --variant A|B --start T
               --out POOLS.json   universe and b3 FROM THE ANCHORED livesim ELIGIBLE (R02: no new history); each pool's
               AmmConfig by livesim.pool_config (frozen), checked against the sha ELIGIBLE recorded; pilots refused.
  collect-gsfa --pools POOLS.json --out GSFA --ledger F --calls F --authorization TEXT --endpoint URL
               the order-check input, on the ONE ledger of the test (25 000 / 24 500).
  ordercheck   --pools POOLS.json --gsfa GSFA --gtfa PRE_PAGES --out ORDERCHECK.json   offline; R02 anchors it.
  run          --pools POOLS.json --ordercheck ORDERCHECK.json --ordercheck-sha <anchored by R02> --journal J
               --store DIR --seed-sha HEX --ledger F
               --calls F --authorization TEXT --endpoint URL --max-minutes 110
               the way follows the ANCHORED verdict: a-ok -> gsfa_rank every 30 s, b -> gtfa every 150 s; frozen in
               START (a resume with another way is refused).
  replay   --pools POOLS.json --journal J --store DIR    every record re-derived from the pages (S-2)
  verify   --journal J                                  the hash chain and its head
  compare  --pools POOLS.json --journal J --store DIR --now T --out COMPARE.json
           the a-posteriori simulation (livesim.g23_rows, frozen anchors) on the SAME pages, decision by decision."""
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

from cpmmpilot import rpc as RPC
from cpmmpilot.store import read_gz_page
from cpmmx import timeline as TL
from livesim import sim as LS
from livepaper import engine as E, journal as J, ordercheck as OC, source as S

SCHEMA_POOLS = 'livepaper-pools-v0.1'
SCHEMA_COMPARE = 'livepaper-compare-v0.1'


class CliError(ValueError):
    pass


ELIGIBLE_SCHEMA = {'A': 'livesim-v0.3.1', 'B': 'livesim-v0.3.2'}


def prepare(eligible_path, eligible_sha, list_l_path, variant, start):
    if LS.file_sha(eligible_path) != eligible_sha:
        raise CliError('eligible_not_the_anchored_file')
    doc = json.loads(Path(eligible_path).read_text())
    if doc.get('schema') != ELIGIBLE_SCHEMA[variant]:
        raise CliError('eligible_not_of_the_variant')
    if type(start) is not int or start < doc['t_start']:
        raise CliError('start_before_the_eligible_history')
    ll = LS.list_l_doc(list_l_path)
    if doc['list_l_sha256'] != LS.LIST_L_SHA256:
        raise CliError('eligible_of_another_list_l')
    if not doc['pools']:
        raise CliError('no_eligible_pool')
    LS.check_universe(doc['pools'])
    by = {r['pool']: r for r in doc['rows']}
    lrow = {r['pool']: r for r in ll['list']}
    rows = []
    for x in doc['pools']:
        if not by[x]['eligible']:
            raise CliError('eligible_list_and_rows_differ')
        cfg = LS.pool_config(ll, x)
        if cfg['sha256'] != by[x]['amm_config_sha256']:
            raise CliError('amm_config_differs_from_eligible:%s' % x)
        rows.append(dict(pool=x, base_mint=lrow[x]['base_mint'], wsol_vault=lrow[x]['wsol_vault'], config=cfg,
                         b3=by[x]['b3'], eligible=True))
    return dict(schema=SCHEMA_POOLS, variant=variant, start=start, eligible_sha256=eligible_sha,
                eligible_t_start=doc['t_start'], list_l_sha256=LS.LIST_L_SHA256, rows=rows,
                eligible=[r['pool'] for r in rows])


def _pools(doc):
    by = {r['pool']: r for r in doc['rows']}
    return [by[p] for p in doc['eligible']]


def way(ordercheck_path, ordercheck_sha):
    """The frozen way: the mode the ANCHORED order-check verdict designates (its sha given, as --eligible-sha), and its
    poll period."""
    if type(ordercheck_sha) is not str or len(ordercheck_sha) != 64 or LS.file_sha(ordercheck_path) != ordercheck_sha:
        raise CliError('ordercheck_not_the_anchored_file')
    verdict = json.loads(Path(ordercheck_path).read_text())['verdict']
    if verdict not in S.VERDICT_MODE:
        raise CliError('unknown_ordercheck_verdict')
    mode = S.VERDICT_MODE[verdict]
    return mode, S.MODE_POLL[mode]


def run(args, pools_doc, *, transport=None, modules=None, clocks=None):
    S.check_imports()
    mode, poll_s = way(args.ordercheck, args.ordercheck_sha)
    if not S.env_has_no_key():
        raise CliError('provider_key_visible_in_the_environment')
    S.check_no_signing_modules(sys.modules if modules is None else modules)
    if transport is None:
        transport = S.LiveTransport(args.endpoint, authorization_file=args.authorization)   # refuses in 0.1
    pools = _pools(pools_doc)
    engine = E.resume(pools, start=pools_doc['start'], seed_sha=args.seed_sha, variant=pools_doc['variant'],
                      journal_path=args.journal, store=args.store, mode=mode, poll_s=poll_s)
    client = S.TimedClient(RPC.Client(transport, S.Budget(args.ledger), args.calls), str(args.calls) + '.timing.jsonl')
    source = S.Source(client, [p['pool'] for p in pools], mode=mode, start=pools_doc['start'])
    source.restore(engine.journal.records)
    return S.Runner(engine, source, poll_s=poll_s, max_s=args.max_minutes * 60,
                    head_file=Path(args.journal).with_name('HEAD.json'), **(clocks or {})).run()


def replay(pools_doc, journal_path, store, seed_sha):
    first = J.read(journal_path)[0]
    engine = E.resume(_pools(pools_doc), start=pools_doc['start'], seed_sha=seed_sha, variant=pools_doc['variant'],
                      journal_path=journal_path, store=store, mode=first['mode'], poll_s=first['poll_s'])
    return dict(reproduced=len(engine.journal.records), head=engine.journal.head)


def _pct(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def compare(pools_doc, journal_path, store, now):
    """Live records against the a-posteriori simulation (livesim.g23_rows: frozen anchors on the trigger) on the same
    pages; a measure of the live operation, never a verdict."""
    records = J.read(journal_path)
    J.verify_records(records)
    start = records[0]['start']
    seed = records[0]['seed_sha']
    pools = {p['pool']: p for p in _pools(pools_doc)}
    live = {r['id']: r for r in records if r['kind'] == 'DECISION' and r.get('series') == 'primary'}
    exits = {r['id']: r for r in records if r['kind'] == 'EXIT'}
    by_trigger = {(r['pool'], r['trigger_signature']): r for r in live.values()}
    out, only_after = [], []
    for name, row in pools.items():
        txs = {}
        for p in sorted((Path(store) / name).glob('page_*.json.gz')):
            for t in read_gz_page(p)['data']:
                txs[t['transaction']['signatures'][0]] = t
        if not txs:
            continue
        line = TL.build(name, txs, base_mint=row['base_mint'])
        if pools_doc['variant'] == 'B':
            line, _rep = E.rebuilt(line, txs, row['wsol_vault'], row['config'])
        known = LS.truncated(line, now)
        after = LS.g23_rows(line, txs, row['config'], row['b3'], seed, start=start, now=now)['primary']
        for r in after['closed'] + after['open']:
            sig = known.swaps[r['decision_index']].signature
            d = by_trigger.pop((name, sig), None)
            if d is None:
                only_after.append(dict(pool=name, trigger_signature=sig, a_posteriori_status=r.get('status'),
                                       a_posteriori_net_lamports=r.get('net_lamports')))
                continue
            e = exits.get(d['id'])
            out.append(dict(pool=name, trigger_signature=sig, delay_s=d['delay_s'],
                            decided_after_gap=d['decided_after_gap'], live_status=e['status'] if e else 'open',
                            live_net_lamports=e['net_lamports'] if e else None,
                            a_posteriori_status=r.get('status'), a_posteriori_net_lamports=r.get('net_lamports')))
    steps = [r for r in records if r['kind'] == 'STEP']
    proc = [r['processing_ms'] for r in steps]
    delays = [r['delay_s'] for r in live.values()]
    return dict(schema=SCHEMA_COMPARE, label=E.LABEL, counts_for_operational_master=False, verdict=None, now=now,
                journal_head=records[-1]['sha'], matched=out, only_live=sorted(
                    [dict(pool=k[0], trigger_signature=k[1], delay_s=v['delay_s'],
                          decided_after_gap=v['decided_after_gap']) for k, v in by_trigger.items()],
                    key=lambda x: (x['pool'], x['trigger_signature'])),
                only_a_posteriori=only_after,
                gaps=[[r['gap_start'], r['gap_end']] for r in records if r['kind'] == 'GAP'],
                processing_ms=dict(p50=_pct(proc, 0.5), p95=_pct(proc, 0.95), p99=_pct(proc, 0.99), steps=len(proc)),
                decision_delay_s=dict(p50=_pct(delays, 0.5), p95=_pct(delays, 0.95),
                                      mean=statistics.mean(delays) if delays else None, decisions=len(delays)))


def _write(path, doc):
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n'
    Path(path).write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def main(argv=None, **kw):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('prepare')
    for k in ('--eligible', '--list-l', '--out'):
        a.add_argument(k, type=Path, required=True)
    a.add_argument('--eligible-sha', required=True)
    a.add_argument('--variant', choices=E.VARIANTS, required=True)
    a.add_argument('--start', type=int, required=True)
    g = sub.add_parser('collect-gsfa')
    for k in ('--pools', '--out', '--ledger', '--calls', '--authorization'):
        g.add_argument(k, type=Path, required=True)
    g.add_argument('--endpoint', required=True)
    o = sub.add_parser('ordercheck')
    for k in ('--pools', '--gsfa', '--gtfa', '--out'):
        o.add_argument(k, type=Path, required=True)
    r = sub.add_parser('run')
    for k in ('--pools', '--ordercheck', '--journal', '--store', '--ledger', '--calls', '--authorization'):
        r.add_argument(k, type=Path, required=True)
    r.add_argument('--seed-sha', required=True)
    r.add_argument('--ordercheck-sha', required=True)
    r.add_argument('--endpoint', required=True)
    r.add_argument('--max-minutes', type=int, default=110)
    for name in ('replay', 'compare'):
        c = sub.add_parser(name)
        for k in ('--pools', '--journal', '--store'):
            c.add_argument(k, type=Path, required=True)
        if name == 'replay':
            c.add_argument('--seed-sha', required=True)
        else:
            c.add_argument('--now', type=int, required=True)
            c.add_argument('--out', type=Path, required=True)
    v = sub.add_parser('verify')
    v.add_argument('--journal', type=Path, required=True)
    args = p.parse_args(argv)
    if args.cmd == 'prepare':
        if args.out.exists():
            raise CliError('output_exists')
        print(_write(args.out, prepare(args.eligible, args.eligible_sha, args.list_l, args.variant, args.start)),
              args.out)
    elif args.cmd == 'collect-gsfa':
        S.check_imports()
        doc = json.loads(args.pools.read_text())
        transport = kw.get('transport') or S.LiveTransport(args.endpoint, authorization_file=args.authorization)
        client = S.TimedClient(RPC.Client(transport, S.Budget(args.ledger), args.calls),
                               str(args.calls) + '.timing.jsonl')
        window = doc['eligible_t_start'] - 7 * 86_400
        print(json.dumps(S.collect_gsfa(client, doc['eligible'], args.out, window_start=window)))
    elif args.cmd == 'ordercheck':
        if args.out.exists():
            raise CliError('output_exists')
        doc = json.loads(args.pools.read_text())
        print(_write(args.out, OC.check(args.gsfa, args.gtfa, doc['eligible'])), args.out)
    elif args.cmd == 'run':
        if args.max_minutes > 115:
            raise CliError('process_above_115_min')
        print(run(args, json.loads(args.pools.read_text()), **kw))
    elif args.cmd == 'replay':
        print(json.dumps(replay(json.loads(args.pools.read_text()), args.journal, args.store, args.seed_sha)))
    elif args.cmd == 'verify':
        records = J.read(args.journal)
        print(json.dumps(dict(records=len(records), head=J.verify_records(records))))
    else:
        if args.out.exists():
            raise CliError('output_exists')
        doc = compare(json.loads(args.pools.read_text()), args.journal, args.store, args.now)
        print(_write(args.out, doc), args.out)


if __name__ == '__main__':
    main()
