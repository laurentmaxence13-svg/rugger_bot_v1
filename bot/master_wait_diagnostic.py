"""RUGGER 03 offline diagnostic of MASTER WAIT causes on retained archives.

Read-only, no network, no strategy change, no trade. It counts which inputs the
frozen MASTER gates in ``bot.master_decision`` would need and which of them the
retained ``events.jsonl.gz`` archives really contain. It never builds a frame
with invented values: a missing field stays missing.
"""
import argparse
import collections
import gzip
import json
from pathlib import Path

SCHEMA = 'rugger03-master-wait-diagnostic-v1'
BLOCKERS = ('additional_costs_unknown', 'qualified_past_edge_evidence_unavailable',
            'source_identity_supply_creation_unqualified')


def _tx_meta_fee(payload):
    raw = payload.get('raw_transaction')
    if type(raw) is not dict:
        return None
    result = raw.get('result', raw)
    meta = result.get('meta') if type(result) is dict else None
    fee = meta.get('fee') if type(meta) is dict else None
    return fee if type(fee) is int and fee >= 0 else None


def diagnose(root):
    """Count gate inputs per archive directory under ``root`` (events.jsonl.gz)."""
    per = {}
    creators = set()
    for path in sorted(Path(root).glob('*/events.jsonl.gz')):
        c = collections.Counter()
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            for line in handle:
                try:
                    e = json.loads(line)
                except ValueError:
                    c['unparseable_lines'] += 1
                    continue
                kind, outcome = e.get('kind'), e.get('outcome')
                p = e.get('payload') if type(e.get('payload')) is dict else {}
                c['events'] += 1
                if kind == 'transaction' and outcome == 'observed':
                    c['tx_observed'] += 1
                    c['tx_with_meta_fee'] += _tx_meta_fee(p) is not None
                elif kind == 'transaction' and outcome == 'chain_failed':
                    c['tx_chain_failed_unattributed'] += 1
                elif kind == 'launch':
                    c['launch_events'] += 1
                    if p.get('creator'):
                        creators.add(p['creator'])
                elif kind == 'checkpoint' and outcome == 'creation_matched':
                    c['creation_matched'] += 1
                    if p.get('creator'):
                        creators.add(p['creator'])
                    c['creation_fee_known'] += type(p.get('meta_fee_lamports')) is int
                elif kind == 'candidate_decision':
                    c['candidate_decisions'] += 1
                    if 'creation_verified' in p:
                        c['creation_verified_field'] += 1
                        c['creation_verified_true'] += p['creation_verified'] is True
                    c['entry_permitted_true'] += p.get('entry_permitted') is True
                elif kind == 'quote_attempt':
                    c['quote_attempts'] += 1
                    c['quote_quoted'] += outcome == 'quoted'
        per[path.parent.name] = dict(c)
    total = collections.Counter()
    for c in per.values():
        total.update(c)
    total = dict(total)
    n = lambda k: total.get(k, 0)
    availability = {
        'additional_costs_unknown': dict(
            needs='entry_extra_lamports, exit_extra_lamports, failed_attempt_lamports with pool-fee exclusion flags',
            present=dict(observed_tx_with_fee=n('tx_with_meta_fee'), creation_fee_known=n('creation_fee_known')),
            missing=['exit_extra_lamports (no sell executed)', 'failed_attempt_lamports (chain_failed rows carry no fee/owner)',
                     'quote_amounts_net_of_pool_fees flag'],
            reconstructible_offline=False),
        'qualified_past_edge_evidence_unavailable': dict(
            needs='>=50 qualified economic cycles and >=20 independent creator groups, bound to the policy hash',
            present=dict(qualified_cycles=0, independent_creators_seen=len(creators)),
            missing=['complete BUY/SELL cycles', 'creator groups (need >=20)'],
            reconstructible_offline=False),
        'source_identity_supply_creation_unqualified': dict(
            needs='bank_state identity_qualified & supply_verified & creation_verified all True',
            present=dict(creation_matched=n('creation_matched'), launch_events=n('launch_events'),
                         creation_verified_true=n('creation_verified_true')),
            missing=['supply_verified', 'identity_qualified', 'creation_verified=True on candidates'],
            reconstructible_offline=False),
    }
    return dict(schema=SCHEMA, archives=len(per), per_archive=per, totals=total,
                distinct_creators=len(creators), availability=availability,
                eligible_frames=0, eligibility_rate=0.0,
                profitability_claimed=False, strategy_changed=False)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('root', help='directory holding <archive>/events.jsonl.gz')
    print(json.dumps(diagnose(ap.parse_args(argv).root), indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
