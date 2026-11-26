"""COMPLETE flag of a G2-3 collection (informative only, R02 plan e886578c point 3): true iff G23_COLLECT_RESULT.json says
verdict_run DONE and every pool's STATE.json under window/collect/window says done = true. The rule « no verdict on a
partial collection » stays checked by R02. Usage: python -B g23_complete.py OUT  ->  prints COMPLETE=true|false"""
import json
import sys
from pathlib import Path

RESULT = 'G23_COLLECT_RESULT.json'


def complete(out, pools):
    out = Path(out)
    try:
        res = json.loads((out / RESULT).read_text())
    except (OSError, ValueError):
        return False
    if res.get('verdict_run') != 'DONE' or sorted(res.get('pools') or []) != sorted(pools):
        return False
    for pool in pools:
        st = out / 'window' / 'collect' / 'window' / pool / 'STATE.json'
        try:
            if json.loads(st.read_text()).get('done') is not True:
                return False
        except (OSError, ValueError):
            return False
    return True


if __name__ == '__main__':
    import importlib.util
    spec = importlib.util.spec_from_file_location('g23_collect_v0_2', Path(__file__).resolve().parent / 'g23_collect_v0_2.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print('COMPLETE=%s' % ('true' if complete(sys.argv[1], mod.POOLS) else 'false'))
