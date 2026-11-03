#!/usr/bin/env python3
"""Pair two endurance implementations on disposable source-only offline copies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref',required=True,help='Already available local Git commit; never fetched')
    parser.add_argument('--output',type=Path,required=True,help='New dedicated directory')
    parser.add_argument('--events',type=int,default=1000)
    parser.add_argument('--restarts',type=int,default=10)
    parser.add_argument('--wall-seconds',type=float,default=30)
    args=parser.parse_args()
    if (args.output.exists() or args.output.is_symlink() or not 2<=args.events<=1000
            or not 1<=args.restarts<=min(10,args.events)
            or not 0<args.wall_seconds<=60):
        parser.error('New output and bounded events/restarts/positive wall pacing required')
    repo=Path(__file__).resolve().parents[1]
    baseline_tree=subprocess.check_output(['git','rev-parse',args.baseline_ref+'^{tree}'],cwd=repo,text=True).strip()
    baseline_source=subprocess.check_output(['git','show',args.baseline_ref+':bot/master_endurance.py'],cwd=repo)
    paths=subprocess.check_output(['git','ls-files','-z','bot'],cwd=repo).decode().split('\0')
    selected=[]
    for name in paths:
        if not name:continue
        path=Path(name)
        if (path.parts[:2]==('bot','bot') or path.suffix not in ('.py','.json')):continue
        source=repo/path
        if source.is_symlink() or not source.resolve().is_relative_to(repo):
            raise ValueError('Source symlinks cannot enter the benchmark')
        selected.append(path)
    output=args.output.resolve();output.mkdir(parents=True)
    source_hashes={str(path):digest(repo/path) for path in selected}
    runner='''
import json,os,sys
from pathlib import Path
os.environ['RUGGER_NO_DOTENV']='1'
from bot.__main__ import _offline_policy
sys.addaudithook(_offline_policy)
from bot import master_audit
original=master_audit.master_report
calls=[0]
def counted(con):
    calls[0]+=1
    return original(con)
master_audit.master_report=counted
from bot.master_endurance import run_master_endurance
result=run_master_endurance(sys.argv[1],events=int(sys.argv[2]),restarts=int(sys.argv[3]),wall_seconds=float(sys.argv[4]))
Path(sys.argv[1],'report_calls.json').write_text(json.dumps({'detailed_report_calls':calls[0]}))
print(json.dumps({'events':result['retained_shadow_events'],'wall_elapsed_ms':result['wall_elapsed_ms'],'detailed_report_calls':calls[0]}))
'''
    records={};reports={}
    for label in ('before','after'):
        package=output/(label+'-sources')
        for path in selected:
            target=package/path;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(repo/path,target)
        if label=='before':(package/'bot/master_endurance.py').write_bytes(baseline_source)
        for path in selected:
            expected=(hashlib.sha256(baseline_source).hexdigest()
                if label=='before' and str(path)=='bot/master_endurance.py' else source_hashes[str(path)])
            if digest(package/path)!=expected:
                raise RuntimeError('Sources changed during the paired benchmark; comparison refused')
        destination=output/label
        env={'PATH':os.defpath,'PYTHONPATH':str(package),'PYTHONDONTWRITEBYTECODE':'1',
             'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
        print('Starting '+label+' with identical budgets and isolated sources',flush=True)
        start=time.monotonic()
        with (output/(label+'.stdout')).open('w') as stdout,(output/(label+'.stderr')).open('w') as stderr:
            result=subprocess.run([sys.executable,'-B','-c',runner,str(destination),str(args.events),
                str(args.restarts),str(args.wall_seconds)],cwd=package,env=env,stdout=stdout,stderr=stderr,timeout=600)
        if result.returncode:raise RuntimeError(label+' failed; retained stderr for inspection')
        report=json.loads((destination/'report.json').read_text());reports[label]=report
        calls=json.loads((destination/'report_calls.json').read_text())['detailed_report_calls']
        records[label]=dict(wall_elapsed_ms=report['wall_elapsed_ms'],outer_elapsed_ms=(time.monotonic()-start)*1000,
            detailed_report_calls=calls,report_sha256=digest(destination/'report.json'),
            endurance_source_sha256=digest(package/'bot/master_endurance.py'))
        print(json.dumps({label:records[label]}),flush=True)
    invariant_keys=('fixture_sha256','event_chain_sha256','initial_financial_sha256','final_financial_sha256',
        'retained_shadow_events','duplicate_replays_ignored','conflicting_duplicates_refused',
        'interrupted_transactions_rolled_back','backups_verified','restarts_verified',
        'invariant_checks','inventory_acquired_atomic','inventory_remaining_atomic','final_capital_sol',
        'final_available_cash_sol','settled_shadow_legs','strict_economic_cycles')
    equal={key:reports['before'][key]==reports['after'][key] for key in invariant_keys}
    if not all(equal.values()):raise RuntimeError('Benchmark changed logical or financial evidence')
    for label in records:
        for snapshot in reports[label]['restart_snapshots']:
            if digest(output/label/snapshot['file'])!=snapshot['backup_sha256']:
                raise RuntimeError('Immutable backup fingerprint changed')
    summary=dict(schema='rugger-paired-endurance-performance-v1',baseline_ref=args.baseline_ref,
        baseline_tree=baseline_tree,events=args.events,restarts=args.restarts,wall_target_ms=args.wall_seconds*1000,
        runs=records,logical_and_financial_evidence_equal=equal,immutable_backups_verified=True,
        wall_speed_ratio=records['before']['wall_elapsed_ms']/records['after']['wall_elapsed_ms'],
        current_source_sha256=source_hashes,only_endurance_implementation_varied=True,
        copied_source_controls_verified=True,
        ordering='before_then_after; single paired run, no statistical performance claim',
        network_requests=0,new_market_observations=0,strict_market_economic_cycles=0,promotion_allowed=False)
    (output/'comparison.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(str(output/'comparison.json'),flush=True)


if __name__=='__main__':main()
