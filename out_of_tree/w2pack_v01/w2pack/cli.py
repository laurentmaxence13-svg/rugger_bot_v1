"""w2pack CLI (R03). Nothing here sends a request; ``argv`` only PRINTS the frozen backfill command.

  python -B -m w2pack.cli plan   --config W2.json
  python -B -m w2pack.cli argv   --config W2.json --segment K --out DIR --max-credits N --max-requests N
  python -B -m w2pack.cli verify --dir DIR

A segment is collected by the frozen ``bot.market.backfill_cli run`` with exactly the printed arguments, only after
the owner's GO and a fresh quota reading. Re-running the same command resumes it (frozen state.json; only unlisted
segments are deleted; caps are cumulative and on disk before every send).
"""
import argparse
import json
import sys
from pathlib import Path

from w2pack import plan as P


def load(path):
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    allowed = set(P.W2Config.__dataclass_fields__)
    if set(doc) - allowed:
        raise P.PlanError('unknown_config_keys:' + ','.join(sorted(set(doc) - allowed)))
    return P.W2Config(**doc).check()


def segment_argv(cfg, index, out, *, max_credits, max_requests):
    segs = P.segments(cfg)
    if not 0 <= index < len(segs):
        raise P.PlanError('no_such_segment')
    if type(max_credits) is not int or not 0 < max_credits <= cfg.credit_cap:
        raise P.PlanError('max_credits_outside_the_cap')
    if type(max_requests) is not int or max_requests <= 0:
        raise P.PlanError('invalid_max_requests')
    s = segs[index]
    return ['run', '--network', '--slot-min', str(s['slot_min']), '--slot-max', str(s['slot_max']),
            '--anchor-after-window', '--costs', P.COSTS, '--max-requests', str(max_requests),
            '--max-credits', str(max_credits), '--out', str(out)]


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog='w2pack')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan'); p.add_argument('--config', required=True)
    a = sub.add_parser('argv'); a.add_argument('--config', required=True); a.add_argument('--segment', type=int, required=True)
    a.add_argument('--out', required=True); a.add_argument('--max-credits', type=int, required=True)
    a.add_argument('--max-requests', type=int, required=True)
    v = sub.add_parser('verify'); v.add_argument('--dir', required=True)
    args = ap.parse_args(argv)
    if args.cmd == 'plan':
        out.write(json.dumps(P.plan(load(args.config)), indent=1, sort_keys=True) + '\n')
    elif args.cmd == 'argv':
        cfg = load(args.config)
        out.write(json.dumps(dict(module='bot.market.backfill_cli', argv=segment_argv(
            cfg, args.segment, args.out, max_credits=args.max_credits, max_requests=args.max_requests))) + '\n')
    else:
        from bot.market import backfill as bf
        result = bf.verify(Path(args.dir))
        out.write(json.dumps(dict(ok=result['ok'], problems=result.get('problems')), sort_keys=True) + '\n')
        return 0 if result['ok'] else 1
    return 0


if __name__ == '__main__':          # pragma: no cover
    raise SystemExit(main())
