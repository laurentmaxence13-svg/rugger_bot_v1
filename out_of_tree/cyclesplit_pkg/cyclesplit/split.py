"""cyclesplit 0.1 -- read-only RECONCILIATION of the W1 MASTER closed cycles by population (R02, 22/11).

Why: psverdict 0.2 compared ``totals.master.closed_cycles`` of the WHOLE bundle (191) with the 128 of the preliminary
reading, which counts the EVALUATION population only. This script splits the master closed cycles of the anchored L1
bundle into the pools created BEFORE, INSIDE and AFTER the evaluation range, with exactly the rule of the reading.

  python -I -B -m cyclesplit.split --bundle <run/bundles/L1.json.gz> --bundle-sha256 <anchored file sha> --s0 <S0>

Sources (cited, not re-implemented):
* bounds: ``bot.market.w1_collection.bounds(s0)['evaluation']`` (w1_collection.py:31-43; window documented l. 9-11:
  warm-up [S0, S0 + 402 800), evaluation [S0 + 402 800, S0 + 2 015 600)); S0 is given on the command line (W1:
  467 275 745, the s0 of the dayj chain and of the w1x exploratory chain, explore.py:148);
* population rule: w1x 0.1.5 reading.py:146, ``evaluation_min <= pool['creation_slot'] < evaluation_max``;
* closed cycle: reading.py:121-122, ``row['outcome'] == 'closed'``; here on the bundle's master row
  (``pool['arms']['master']['outcome']``), the same row the reading checks against the ledger (reading.py:155-163);
* total: must equal the frozen ``bundle['totals']['master']['closed_cycles']`` (historical_research_replay.py:767),
  else the script raises (no output).
Output (stdout, one JSON document): provenance (schema, the file sha checked BEFORE reading, s0, the evaluation range,
the rule) and FOUR integers only: master_closed_before / inside / after / total. Whitelisted keys; no P&L, no pool,
no other figure. Standard library + the frozen ``w1_collection`` for the bounds.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from bot.market import w1_collection

SCHEMA = 'cyclesplit-v0.1'
COUNTS = ('master_closed_before', 'master_closed_inside', 'master_closed_after', 'master_closed_total')
KEYS = ('schema', 'bundle_file_sha256', 's0', 'evaluation', 'rule', 'counts')
RULE = 'inside = evaluation_min <= pool.creation_slot < evaluation_max (w1x reading.py:146); closed = outcome "closed"'


class SplitError(RuntimeError):
    pass


def split(bundle, evaluation_min, evaluation_max):
    before = inside = after = 0
    for pool in bundle['pools']:
        slot = pool.get('creation_slot')
        if type(slot) is not int:
            raise SplitError('pool_without_creation_slot')
        if pool['arms']['master']['outcome'] != 'closed':
            continue
        if slot < evaluation_min:
            before += 1
        elif slot < evaluation_max:
            inside += 1
        else:
            after += 1
    total = before + inside + after
    if total != bundle['totals']['master']['closed_cycles']:
        raise SplitError('split_does_not_add_up_to_the_frozen_total')
    return dict(zip(COUNTS, (before, inside, after, total)))


def run(bundle_path, bundle_sha256, s0):
    raw = Path(bundle_path).read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != bundle_sha256:
        raise SplitError('bundle_is_not_the_anchored_one')
    bundle = json.loads(gzip.decompress(raw) if str(bundle_path).endswith('.gz') else raw)
    del raw
    evaluation_min, evaluation_max = w1_collection.bounds(s0)['evaluation']
    doc = dict(schema=SCHEMA, bundle_file_sha256=got, s0=s0, evaluation=[evaluation_min, evaluation_max], rule=RULE,
               counts=split(bundle, evaluation_min, evaluation_max))
    if tuple(doc) != KEYS or tuple(doc['counts']) != COUNTS or not all(type(v) is int for v in doc['counts'].values()):
        raise SplitError('output_not_whitelisted')
    return doc


def main(argv=None):
    p = argparse.ArgumentParser(prog='cyclesplit.split')
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--bundle-sha256', required=True)
    p.add_argument('--s0', type=int, required=True)
    a = p.parse_args(argv)
    print(json.dumps(run(a.bundle, a.bundle_sha256, a.s0), indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
