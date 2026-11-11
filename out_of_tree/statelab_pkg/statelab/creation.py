"""How pools are created: counts only (no price, no value, no result of any rule).

  python -B -m statelab.creation <visible_pack> --expect-manifest-sha <sha256> [--out <creation.json>]

Purpose: give the signal "creator not signed" an exact definition, distinct from "creator not
identified", and say whether it is known before a buy decision. Everything here is read from the
CREATION transaction alone (the first transaction of the pool), i.e. before any later trade.

Status of a pool (``status``), from the frozen ``hrr.creation_facts``:
  signed                the creation is an OUTER instruction of a transaction whose Ed25519 signatures
                        verify, the declared creator is one of its signers and the token decimals are read;
  identified_unsigned   a creator is declared by the creation instruction but at least one of the
                        conditions above fails; ``reasons`` lists which (frozen reason strings);
  unidentified          no creator can be read (creation not decoded, or the earliest stored
                        transaction is not this pool's creation).
Also counted: the programs of the OUTER instructions of the creation transaction other than the
system ones (``launcher``, in call order; LaunchLab can appear there for a trade while the creation
itself is an inner call of another program: the status reasons say which), whether the
declared creator pays the fees, whether a trade of the pool sits in the creation transaction itself,
and how many pools share a cluster (declared creator, else fee payer of the creation).
Discovery segments only (exploration, train).
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from bot.live.migration_rpc_json import normalized_compiled_transaction
from bot.market.collector import summarize
from bot.p4 import historical_research_replay as hrr

from v3lab.pack import Pack

from statelab.study import DISCOVERY_SEGMENTS, cluster_key

SCHEMA = 'statelab-creation-v1'
LAUNCHLAB = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
SYSTEM_PROGRAMS = frozenset((
    '11111111111111111111111111111111', 'ComputeBudget111111111111111111111111111111',
    'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL', 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
    'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'))


def outer_programs(tx):
    """Programs called at top level by a compiled transaction, in order, system ones removed."""
    keys = [k['pubkey'] for k in normalized_compiled_transaction(tx)['transaction']['message']['accountKeys']]
    programs = []
    for instruction in tx['transaction']['message']['instructions']:
        program = keys[instruction['programIdIndex']]
        if program not in SYSTEM_PROGRAMS and program not in programs:
            programs.append(program)
    return programs


def classify(archive, events=()):
    """Creation facts of one pool, from its creation transaction only (``events`` only says whether one sits in it)."""
    facts = hrr.creation_facts(archive)
    tx = archive.transactions[facts['creation_signature']]
    reasons = tuple(sorted(r.split(':')[0] for r in facts['signed_creator_reason'].split(';')))
    if facts['signed_creator_verified']:
        status, reasons = 'signed', ()
    elif facts.get('creator'):
        status = 'identified_unsigned'
    else:
        status = 'unidentified'
    try:
        programs = outer_programs(tx)
        keys = normalized_compiled_transaction(tx)['transaction']['message']['accountKeys']
        payer = keys[0]['pubkey']
    except (ValueError, KeyError, IndexError, TypeError):
        programs, payer = None, None
    launcher = None if programs is None else ('+'.join(programs) or 'none')        # LaunchLab may sit beside a launcher
    return dict(pool=archive.pool, status=status, reasons=list(reasons), launcher=launcher,
                creator_pays_fees=None if payer is None or not facts.get('creator') else facts['creator'] == payer,
                trade_in_creation_transaction=any(e.signature == facts['creation_signature'] for e in events),
                cluster=cluster_key(archive, facts))


def census(pack_dir, expect_manifest_sha256):
    pack = Pack(pack_dir, expect_manifest_sha256)
    rows, unreadable = [], 0
    for entry, archive, segment in pack.pools():
        if segment not in DISCOVERY_SEGMENTS:
            continue
        summary, timeline = summarize(archive)
        try:
            timeline, _migration = hrr.usable_timeline(archive, summary, timeline)
        except hrr.PoolExcluded:
            unreadable += 1
            continue
        rows.append(dict(classify(archive, timeline.events), segment=segment))
    by_status = Counter(r['status'] for r in rows)
    clusters = {status: Counter(r['cluster'] for r in rows if r['status'] == status) for status in by_status}
    document = dict(
        schema=SCHEMA, status='DESCRIPTIVE', pack_manifest_sha256=pack.manifest_sha256, segments=list(DISCOVERY_SEGMENTS),
        pools=len(rows), not_replayable=unreadable, by_status=dict(sorted(by_status.items())),
        reasons_of_identified_unsigned=dict(sorted(Counter(
            '+'.join(r['reasons']) for r in rows if r['status'] == 'identified_unsigned').items())),
        reasons_of_unidentified=dict(sorted(Counter(
            '+'.join(r['reasons']) for r in rows if r['status'] == 'unidentified').items())),
        launcher_by_status={status: dict(Counter(str(r['launcher']) for r in rows if r['status'] == status).most_common())
                            for status in sorted(by_status)},
        creator_pays_fees_by_status={status: dict(sorted(Counter(
            str(r['creator_pays_fees']) for r in rows if r['status'] == status).items())) for status in sorted(by_status)},
        trade_in_creation_transaction_by_status={status: dict(sorted(Counter(
            str(r['trade_in_creation_transaction']) for r in rows if r['status'] == status).items()))
            for status in sorted(by_status)},
        clusters_by_status={status: dict(clusters=len(counter), largest=max(counter.values()),
                                         pools_in_the_5_largest=sum(n for _c, n in counter.most_common(5)))
                            for status, counter in sorted(clusters.items())},
        flags=dict(prices_read=False, rule_pnl_computed=False, trial_registered=False, holdout_read=False,
                   w1_data_read=False),
        notes=['counts only, from the creation transaction of each pool: nothing about prices or results',
               'a status is known as soon as the creation transaction is seen, before any later trade'])
    document['rows_sha256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description='how pools are created: counts only')
    parser.add_argument('pack', type=Path)
    parser.add_argument('--expect-manifest-sha', required=True)
    parser.add_argument('--out', type=Path)
    a = parser.parse_args(argv)
    document = census(a.pack, a.expect_manifest_sha)
    text = json.dumps(document, sort_keys=True, indent=1, allow_nan=False) + '\n'
    if a.out:
        if a.out.exists():
            raise SystemExit('output_exists')
        a.out.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
