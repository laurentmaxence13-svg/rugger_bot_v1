#!/usr/bin/env python3
"""Launch one preregistered P3 control with a hard process watchdog, no retries."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['RUGGER_NO_DOTENV']='1'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--watchdog-report',type=Path,required=True)
    parser.add_argument('--network',action='store_true')
    args=parser.parse_args()
    paths=(args.plan,args.db,args.output,args.watchdog_report)
    if (not args.network or len({p.resolve() for p in paths})!=4
            or any(p.exists() or p.is_symlink() for p in paths[1:])
            or args.plan.is_symlink() or args.plan.name.startswith('.env')
            or args.plan.suffix!='.json' or args.watchdog_report.suffix!='.json'):
        parser.error('Explicit network opt-in, published plan and new separate output paths required')
    from bot.p3.active_cohort_campaign import validate_plan,run_process_watchdog
    validate_plan(json.loads(args.plan.read_text()))
    command=[sys.executable,'-B','-m','bot.p3.active_cohort_campaign','--network',
        '--plan',str(args.plan.resolve()),'--db',str(args.db.resolve()),'--output',str(args.output.resolve())]
    # Reserve two seconds for TERM/KILL within the global60-second process budget.
    receipt=run_process_watchdog(command,timeout_seconds=58,
        working_directory=Path(__file__).resolve().parents[1])
    receipt['acquisition_report_retained']=args.output.is_file()
    from bot.analyser.artifacts import atomic_write_json
    atomic_write_json(args.watchdog_report,receipt,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps(receipt))
    return 124 if receipt['process_deadline_exceeded'] else receipt['child_exit_code']


if __name__=='__main__':raise SystemExit(main())
