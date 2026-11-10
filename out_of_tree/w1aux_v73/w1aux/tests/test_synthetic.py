"""w1aux.synthetic (R02 C-Z2): the frozen pack copied K times, pools renamed, for load measurement only."""
import json

import pytest

from bot.market.collector import summarize
from bot.p4 import historical_research_replay as hrr
from w1aux import synthetic


def test_copies_are_renamed_everywhere_and_decode_the_same_events(tmp_path):
    doc = synthetic.build(tmp_path / 'k3', 3)
    assert doc['synthetic'] == dict(source_manifest_sha256=synthetic.SOURCE_MANIFEST_SHA256, copies=3,
                                    purpose='LOAD_MEASUREMENT_ONLY_NOT_FOR_ECONOMICS')
    _sha, _d, pools, _m = hrr.load_fixtures(tmp_path / 'k3')                # MANIFEST sha256s checked by the frozen loader
    assert len(pools) == 9 and len({e['pool'] for e, _a in pools}) == 9
    by_source = {}
    for entry, archive in pools:
        assert archive.pool == entry['pool']
        _summary, timeline = summarize(archive)
        assert timeline.events and all(e.pool == archive.pool for e in timeline.events)    # the event payloads were renamed
        by_source.setdefault(len(archive.transactions), []).append(len(timeline.events))
    assert all(len(set(counts)) == 1 and len(counts) == 3 for counts in by_source.values())
    text = (tmp_path / 'k3' / f"{synthetic.new_pool_address(pools[0][0]['pool'], 1)}.json.gz").name
    assert text.endswith('.json.gz')


def test_guards(tmp_path, monkeypatch):
    with pytest.raises(synthetic.SyntheticError, match='positive_integer'):
        synthetic.build(tmp_path / 'a', 0)
    (tmp_path / 'b').mkdir()
    with pytest.raises(synthetic.SyntheticError, match='already_exists'):
        synthetic.build(tmp_path / 'b', 1)
    monkeypatch.setattr(synthetic, 'SOURCE_MANIFEST_SHA256', '0' * 64)
    with pytest.raises(synthetic.SyntheticError, match='not_the_frozen_test_pack'):
        synthetic.build(tmp_path / 'c', 1)
