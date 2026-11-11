"""statelab.creation: exact statuses from the creation transaction alone, counts only."""
import json

from bot.p4 import historical_research_replay as hrr
from v3lab.tests.test_v3lab import archives, visible            # noqa: F401  (fixtures)

from statelab import creation
from statelab.tests.test_statelab import _pool


def test_statuses_follow_the_frozen_creation_facts_and_never_read_a_later_trade(archives, monkeypatch):   # noqa: F811
    seen = set()
    for _entry, archive in archives:
        timeline, facts, _actors = _pool(archive)
        row = creation.classify(archive, timeline.events)
        assert row['status'] == ('signed' if facts['signed_creator_verified'] else
                                 'identified_unsigned' if facts['creator'] else 'unidentified')
        assert (row['reasons'] == []) == (row['status'] == 'signed') and row['launcher']
        # only the creation transaction matters: the same answer with every other transaction removed
        alone = type(archive)(**dict(archive.__dict__, transactions={
            facts['creation_signature']: archive.transactions[facts['creation_signature']]}))
        again = creation.classify(alone, ())
        assert {k: v for k, v in again.items() if k != 'trade_in_creation_transaction'} == \
               {k: v for k, v in row.items() if k != 'trade_in_creation_transaction'}
        seen.add(row['status'])
    assert 'signed' in seen
    entry, archive = archives[0]
    real = hrr.creation_facts
    monkeypatch.setattr(hrr, 'creation_facts', lambda a: dict(
        real(a), signed_creator_verified=False, signed_creator_reason='creator_not_a_transaction_signer'))
    assert creation.classify(archive)['status'] == 'identified_unsigned'
    assert creation.classify(archive)['reasons'] == ['creator_not_a_transaction_signer']
    monkeypatch.setattr(hrr, 'creation_facts', lambda a: dict(
        real(a), signed_creator_verified=False, creator=None, signed_creator_reason='creation_decode_refused:x'))
    row = creation.classify(archive)
    assert row['status'] == 'unidentified' and row['reasons'] == ['creation_decode_refused']
    assert row['cluster'].startswith('payer:') and row['creator_pays_fees'] is None


def test_outer_programs_drop_system_programs_and_flag_a_direct_call(archives):                      # noqa: F811
    for _entry, archive in archives:
        facts = hrr.creation_facts(archive)
        programs = creation.outer_programs(archive.transactions[facts['creation_signature']])
        assert not set(programs) & creation.SYSTEM_PROGRAMS and len(programs) == len(set(programs))
        row = creation.classify(archive)
        assert (row['launcher'] == 'direct') == (creation.LAUNCHLAB in programs)


def test_the_census_counts_discovery_pools_only_and_reads_no_price(visible):                        # noqa: F811
    directory, sha = visible
    document = creation.census(directory, sha)
    assert document['segments'] == ['exploration', 'train'] and document['status'] == 'DESCRIPTIVE'
    assert document['pools'] + document['not_replayable'] == 2
    assert sum(document['by_status'].values()) == document['pools']
    assert document['flags'] == dict(prices_read=False, rule_pnl_computed=False, trial_registered=False,
                                     holdout_read=False, w1_data_read=False)
    assert all(block['largest'] >= 1 for block in document['clusters_by_status'].values())
    text = json.dumps(document)
    assert 'value' not in text and 'mean_r' not in text and creation.census(directory, sha) == document
