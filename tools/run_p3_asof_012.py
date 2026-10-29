#!/usr/bin/env python3
"""One P3-012 capture under a 58+2-second process watchdog; no retries."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['RUGGER_NO_DOTENV']='1'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','db','output','watchdog-report'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--network',action='store_true');args=parser.parse_args(argv)
    paths=(args.plan,args.db,args.output,args.watchdog_report)
    if (not args.network or len({p.resolve() for p in paths})!=4
            or any(p.exists() or p.is_symlink() for p in paths[1:])
            or args.plan.is_symlink() or args.plan.name.startswith('.env') or args.plan.suffix!='.json'
            or args.output.suffix!='.json' or args.watchdog_report.suffix!='.json'):
        parser.error('Explicit network opt-in, published012 plan and new separate output paths required')
    from bot.p3.active_cohort_campaign import run_process_watchdog
    from bot.p3.asof_protocol_012 import validate_plan
    from bot.analyser.artifacts import atomic_write_json
    plan=json.loads(args.plan.read_text());validate_plan(plan)
    command=[sys.executable,'-B','-m','bot.p3.asof_campaign_012','--network',
        '--plan',str(args.plan.resolve()),'--db',str(args.db.resolve()),'--output',str(args.output.resolve())]
    receipt=run_process_watchdog(command,timeout_seconds=plan['process_child_deadline_seconds'],
        working_directory=Path(__file__).resolve().parents[1])
    receipt['acquisition_report_retained']=args.output.is_file()
    receipt['interrupted_prefix_replay_only']=not args.output.is_file()
    atomic_write_json(args.watchdog_report,receipt,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps(receipt))
    return 124 if receipt['process_deadline_exceeded'] else receipt['child_exit_code']


if __name__=='__main__':raise SystemExit(main())
