"""Order check (owner text livepaper v2 1366025b, R02 14:50Z point 1), run ONCE before the test, offline.
Question: is the order of getSignaturesForAddress inside a slot the order of the transactions in the block (the
transactionIndex that cpmmx needs)? Inputs: the getSignaturesForAddress pages of the eligible pools collected by R03
(source.collect_gsfa, newest first) and the anchored GTFA pages of the pre-start window (SHA256SUMS 951b8479), which
carry the provider's transactionIndex. For every PAIR of signatures of the same slot present on both sides, the GSFA
order (newest first -> later index first) must equal the transactionIndex order. Verdict 'a-ok' (way (i-a)
admissible) only with at least one pair compared, zero discrepancy and zero slot mismatch; otherwise 'b' (way (i-b)).
R02 anchors the output before the start."""
import itertools
from pathlib import Path

from cpmmpilot.store import read_gz_page

SCHEMA = 'livepaper-ordercheck-v0.1'


def gsfa_signatures(root, pool):
    out = []
    for p in sorted((Path(root) / pool).glob('page_*.json.gz')):
        out += read_gz_page(p).get('data') or []
    return out


def gtfa_index(root, pool):
    out = {}
    for p in sorted((Path(root) / pool).glob('page_*.json.gz')):
        for t in read_gz_page(p).get('data') or []:
            out[t['transaction']['signatures'][0]] = (t['slot'], t['transactionIndex'])
    return out


def compare_pool(gsfa, gtfa):
    position = {}                                        # 0 = newest in the GSFA listing
    for k, s in enumerate(gsfa):
        position.setdefault(s['signature'], (s['slot'], k))
    both = [sig for sig in position if sig in gtfa]
    mismatched = sorted(sig for sig in both if position[sig][0] != gtfa[sig][0])
    by_slot = {}
    for sig in both:
        if sig not in mismatched:
            by_slot.setdefault(gtfa[sig][0], []).append(sig)
    pairs, bad = 0, []
    for slot in sorted(by_slot):
        for a, b in itertools.combinations(sorted(by_slot[slot]), 2):
            pairs += 1
            gsfa_a_later = position[a][1] < position[b][1]           # listed first = newer = later in the block
            index_a_later = gtfa[a][1] > gtfa[b][1]
            if gsfa_a_later != index_a_later or gtfa[a][1] == gtfa[b][1]:
                bad.append(dict(slot=slot, a=a, b=b, gsfa_first=a if gsfa_a_later else b,
                                index=[gtfa[a][1], gtfa[b][1]]))
    return dict(signatures_both=len(both), slots_compared=len([s for s in by_slot if len(by_slot[s]) > 1]),
                pairs=pairs, discrepancies=len(bad), slot_mismatches=len(mismatched), examples=bad[:20],
                slot_mismatch_examples=mismatched[:20])


def check(gsfa_root, gtfa_root, pools):
    per = {p: compare_pool(gsfa_signatures(gsfa_root, p), gtfa_index(gtfa_root, p)) for p in pools}
    pairs = sum(v['pairs'] for v in per.values())
    bad = sum(v['discrepancies'] + v['slot_mismatches'] for v in per.values())
    verdict = 'a-ok' if pairs > 0 and bad == 0 else 'b'
    return dict(schema=SCHEMA, pools=per, pairs=pairs, discrepancies=bad, verdict=verdict,
                rule='a-ok iff at least one same-slot pair is compared, with zero discrepancy and zero slot mismatch')
