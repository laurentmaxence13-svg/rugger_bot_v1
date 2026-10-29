"""New offline size study on existing007/008 banks; never recollects them."""
import argparse
import json
from pathlib import Path
import sys


def offline(event,args):
    if event.startswith('socket.') or event=='sqlite3.connect':
        raise RuntimeError('Position-size analysis forbids network and database access')
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        path=Path(args[0].decode() if isinstance(args[0],bytes) else args[0])
        if path.name.startswith('.env') or path.suffix in ('.db','.sqlite','.sqlite3'):
            raise RuntimeError('Private configuration and databases are not study inputs')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or args.output.is_symlink() or args.output.suffix!='.json':
        parser.error('A new JSON output is required')
    sys.dont_write_bytecode=True
    sys.addaudithook(offline)
    root=args.repo.resolve();sys.path.insert(0,str(root))
    from bot.p3.evidence import verify_bundle
    from bot.p3.size_study import frames_from_events,build_size_study
    from bot.analyser.artifacts import atomic_write_json
    index=json.loads((root/'evidence/p3/index.json').read_text())
    frames=[];sources=[]
    for run in ('active_exit_007','prospective_008'):
        rows=[r for r in index['bundles'] if r['run_id']==run]
        if len(rows)!=1:raise ValueError('A unique retained source anchor is required')
        anchor=rows[0]
        bundle=verify_bundle(root/'evidence/p3'/run,expected_tail=anchor['tail_hash'])
        if any(anchor[k]!=bundle[k] for k in ('source_revision','plan_sha256','records',
                'compressed_sha256','uncompressed_sha256')):
            raise ValueError('Portable source differs from the retained evidence index')
        frames.extend(frames_from_events(bundle['events'],run_id=run,
            expected_tail=anchor['tail_hash'],integrity_verified=True))
        sources.append({key:anchor[key] for key in ('run_id','source_revision','plan_sha256',
            'tail_hash','records','compressed_sha256')})
    result=build_size_study(frames);result['source_anchors']=sources
    atomic_write_json(args.output,result,indent=2,sort_keys=True,allow_nan=False)
    print(json.dumps({'output':str(args.output),'banks':result['source_banks'],
        'size_cases':result['bank_size_cases'],'admissible_models':result['admissible_model_cases'],
        'strict_economic_cycles':0,'new_market_requests':0}))


if __name__=='__main__':main()
