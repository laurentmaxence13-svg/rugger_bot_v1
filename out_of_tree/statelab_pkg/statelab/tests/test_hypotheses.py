"""statelab.hypotheses: the two new triggers against an independent recomputation, causality, the W1 guard,
positions equal to the audited probes, sample-size counts and the frozen verdict rules."""
import gzip
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import shutil

import pytest

from bot.master_v2.features import native_features
from bot.p4 import historical_research_replay as hrr
from v3lab import plan
from v3lab.tests.test_v3lab import FIXTURES, archives, visible            # noqa: F401  (fixtures)

from statelab import hypotheses as hyp, points, study
from statelab.tests.test_statelab import COST, RENT, _pool, _row, _synthetic

PARAMS = hrr.ReplayParams(**plan.REPLAY)
SOL = 10 ** 9


def _spot(state):
    return Fraction(state.quote_reserve, state.base_reserve)


def _dip_by_hand(events):
    """Independent recomputation of HW1-1 with exact fractions and an explicit search of the reference."""
    for k, event in enumerate(events):
        if not points.whole(events, k) or event.side != 'sell' or event.real_quote_after < 5 * SOL:
            continue
        old = [e for e in events[:k] if e.block_time <= event.block_time - 10]
        reference = _spot(old[-1].state_after()) if old else _spot(events[0].state_before())
        if _spot(event.state_after()) <= Fraction(9, 10) * reference:
            return k
    return None


def _purge_by_hand(events, created):
    for k, event in enumerate(events):
        before = [events[0].state_before()] + [e.state_after() for e in events[:k]]
        if (points.whole(events, k) and event.side == 'buy' and event.block_time - created >= 30
                and max(s.real_quote for s in before) >= 2 * SOL
                and Fraction(event.real_base_before) <= Fraction(max(s.real_base for s in before), 4)):
            return k
    return None


DEEP = [(0, 'buy', 4 * SOL, 'a'), (2, 'buy', 3 * SOL, 'b'), (3, 'buy', 2 * SOL, 'c')]          # about 8.9 SOL real
# a first sale of about 4 %, then within 10 s a large one: more than 10 % under the spot of 10 s earlier
DIP = _synthetic(DEEP + [(12, 'sell', 20 * 10 ** 12, 'a'), (3, 'sell', 60 * 10 ** 12, 'a'), (5, 'buy', SOL, 'd')])
# the same large sale, but the price had already fallen more than 10 s before: under 10 % against the reference
SLOW = _synthetic(DEEP + [(12, 'sell', 60 * 10 ** 12, 'a'), (11, 'sell', 20 * 10 ** 12, 'b'), (5, 'buy', SOL, 'd')])
# a first sale of about 7 % (between the 5 % and 10 % marks: not enough), then, 12 s later, one of more than 10 %
MID = _synthetic(DEEP + [(12, 'sell', 31 * 10 ** 12, 'a'), (12, 'sell', 60 * 10 ** 12, 'a'), (5, 'buy', SOL, 'd')])
# dumped while it had raised only 1 SOL; it passes 2 SOL only at the very end
LATEBIG = _synthetic([(0, 'buy', SOL, 'a'), (5, 'sell', 30 * 10 ** 12, 'a'), (40, 'buy', 10 ** 8, 'y'), (10, 'buy', 5 * SOL, 'z'),
                      (5, 'sell', 10 ** 12, 'z')])
# two thirds of the tokens sold back (not three quarters), a small buy, then a huge buy that lifts real_base far above
# its past maximum: read one event too far, that future peak would wrongly qualify the small buy (R02 T-H1)
FUTUREPEAK = _synthetic([(0, 'buy', 3 * SOL, 'a'), (5, 'sell', 62 * 10 ** 12, 'a'), (35, 'buy', 10 ** 8, 'y'),
                         (5, 'buy', 20 * SOL, 'z'), (5, 'sell', 10 ** 12, 'z')])
# the large sale leaves less than 5 SOL in the curve
SHALLOW = _synthetic([(0, 'buy', 3 * SOL, 'a'), (2, 'buy', 3 * SOL, 'b'), (12, 'sell', 80 * 10 ** 12, 'a'), (5, 'buy', SOL, 'd')])
# pump to more than 2 SOL, dump to less than a quarter of the tokens, then buys at age 20 s (too early) and 45 s
PURGE = _synthetic([(0, 'buy', 3 * SOL, 'a'), (5, 'sell', 80 * 10 ** 12, 'a'), (15, 'buy', 10 ** 8, 'x'),
                    (25, 'buy', 3 * SOL, 'y'), (10, 'buy', 10 ** 8, 'z')])
SMALL = _synthetic([(0, 'buy', SOL, 'a'), (5, 'sell', 30 * 10 ** 12, 'a'), (40, 'buy', 10 ** 8, 'y')])   # never reached 2 SOL
HELD = _synthetic([(0, 'buy', 3 * SOL, 'a'), (5, 'sell', 30 * 10 ** 12, 'a'), (40, 'buy', 10 ** 8, 'y')])  # two thirds still held


def test_the_dip_trigger_matches_the_by_hand_rule_and_each_condition_matters():
    assert hyp.dip_trigger(DIP.events) == _dip_by_hand(DIP.events) == 4
    first, second = DIP.events[3], DIP.events[4]
    assert first.real_quote_after >= 5 * SOL and _spot(first.state_after()) > Fraction(9, 10) * _spot(DIP.events[2].state_after())
    assert second.block_time - first.block_time < 10          # the reference of event 4 is still event 2, not event 3
    assert hyp.dip_trigger(SLOW.events) == _dip_by_hand(SLOW.events)
    assert hyp.dip_trigger(SLOW.events) == 3 and SLOW.events[4].side == 'sell'   # the later, smaller sale would not qualify
    assert _spot(SLOW.events[4].state_after()) > Fraction(9, 10) * _spot(SLOW.events[3].state_after())
    assert hyp.dip_trigger(MID.events) == _dip_by_hand(MID.events) == 4
    ratio = _spot(MID.events[3].state_after()) / _spot(MID.events[2].state_after())
    assert Fraction(90, 100) < ratio < Fraction(95, 100)        # a 5 to 10 % fall does not qualify
    assert hyp.dip_trigger(SHALLOW.events) is None is _dip_by_hand(SHALLOW.events)
    assert SHALLOW.events[2].real_quote_after < 5 * SOL
    # a sale that is not the last event of its transaction is not a decision
    split = _synthetic(DEEP + [(12, 'sell', 20 * 10 ** 12, 'a'), (3, 'sell', 60 * 10 ** 12, 'a', 'tx'), (0, 'buy', 10 ** 7, 'd', 'tx'),
                               (5, 'sell', 10 ** 12, 'b')])
    assert hyp.dip_trigger(split.events) == _dip_by_hand(split.events) and hyp.dip_trigger(split.events) != 4


def test_the_purge_trigger_matches_the_by_hand_rule_and_ignores_the_triggering_buy():
    events, created = PURGE.events, PURGE.events[0].block_time
    assert hyp.purge_trigger(events, created) == _purge_by_hand(events, created) == 3
    assert events[2].side == 'buy' and events[2].block_time - created == 20      # same state, too young: not taken
    big = events[3]
    assert big.real_base_before * 4 <= events[0].real_base_after < big.real_base_after * 4   # the buy itself refills the curve
    for timeline in (SMALL, HELD, LATEBIG, FUTUREPEAK):
        ev = timeline.events
        assert hyp.purge_trigger(ev, ev[0].block_time) is None is _purge_by_hand(ev, ev[0].block_time)
    assert max(e.real_quote_after for e in SMALL.events) < 2 * SOL
    peak = FUTUREPEAK.events                                     # 25 % < share still held < 33 %; the next buy is the future
    assert peak[0].real_base_after < peak[2].real_base_before * 4 < peak[3].real_base_after
    assert peak[2].side == 'buy' and peak[2].block_time - peak[0].block_time >= 30
    late = LATEBIG.events                                        # the 2 SOL are reached only AFTER the candidate buys
    assert max(e.real_quote_after for e in late[:3]) < 2 * SOL <= late[-1].real_quote_after
    assert late[2].side == 'buy' and late[2].real_base_before * 4 <= late[0].real_base_after
    assert HELD.events[2].real_base_before * 4 > HELD.events[0].real_base_after


def test_triggers_never_depend_on_the_future_and_agree_with_the_frozen_features(archives):          # noqa: F811
    pools = [(t.events, t.events[0].block_time, 'P')
             for t in (DIP, SLOW, MID, SHALLOW, PURGE, SMALL, HELD, LATEBIG, FUTUREPEAK)]
    for _entry, archive in archives:
        timeline, facts, _actors = _pool(archive)
        pools.append((timeline.events, facts['creation_block_time'], archive.pool))
    for events, created, pool in pools:
        dip, purge = hyp.dip_trigger(events), hyp.purge_trigger(events, created)
        assert dip == _dip_by_hand(events) and purge == _purge_by_hand(events, created)
        for cut in [k for k in range(len(events)) if points.whole(events, k)]:
            part = events[:cut + 1]
            assert hyp.dip_trigger(part) == (dip if dip is not None and dip <= cut else None)
            assert hyp.purge_trigger(part, created) == (purge if purge is not None and purge <= cut else None)
            # the same through the public entry point, label triggers included: later events neither create
            # nor move any trigger (R02 T-H1)
            facts = dict(creation_block_time=created)
            whole_life, prefix = hyp.triggers(events, facts, pool), hyp.triggers(part, facts, pool)
            for key, k in whole_life.items():
                assert prefix[key] == (k if k is not None and k <= cut else None), (pool, key, cut)
        # the frozen feature price_change_10s uses the same reference: the trigger is its first value <= -10 %
        facts = dict(creator=None, creation_block_time=created, creation_slot=events[0].slot)
        for k in [k for k in range(len(events)) if points.whole(events, k) and events[k].side == 'sell'
                  and events[k].real_quote_after >= 5 * SOL]:
            change = native_features(events[:k + 1], facts)['price_change_10s']
            if abs(change + 0.10) > 1e-9 and (dip is None or k <= dip):
                assert (change <= -0.10) == (k == dip)


def test_the_unsigned_signal_is_structural_and_distinct_from_unreadable():
    assert hyp.creator_not_signer(dict(creator='C', signed_creator_reason='creator_not_a_transaction_signer')) is True
    assert hyp.creator_not_signer(dict(creator='C', signed_creator_reason='creation_is_inner_cpi_not_in_signed_outer_message;'
                                                                         'creator_not_a_transaction_signer')) is True
    assert hyp.creator_not_signer(dict(creator='C', signed_creator_reason='ed25519_signatures_not_verified')) is False
    assert hyp.creator_not_signer(dict(creator='C', signed_creator_reason='ed25519_valid_outer_creation_signed_by_creator')) is False
    assert hyp.creator_not_signer(dict(creator=None, signed_creator_reason='creation_decode_refused:x')) is None


def test_positions_are_the_audited_probes_and_missing_ones_are_counted(archives, monkeypatch):      # noqa: F811
    seen = {}
    for entry, archive in archives:
        rows, missing = hyp.pool_rows(archive, entry, 'train', PARAMS, None)
        timeline, facts, actors = _pool(archive)
        wanted = hyp.triggers(timeline.events, facts, archive.pool)
        unsigned = hyp.creator_not_signer(facts)
        for row in rows:
            k = wanted[row['hypothesis']]
            assert row['decision_index'] == k and row['decision_slot'] == timeline.events[k].slot
            probe = study.probe(timeline, k, actors, PARAMS.execution_model())
            assert {f: row[f] for f in probe} == probe
            assert row['payer'] == hyp.creation_payer(archive, facts) and row['creator_not_signer'] is unsigned
            seen[row['hypothesis']] = seen.get(row['hypothesis'], 0) + 1
        ids = [row['hypothesis'] for row in rows]
        assert len(ids) == len(set(ids)) and ('HW1-5' in ids) == (unsigned is True and wanted['HW1-5'] is not None)
        if wanted['HW1-5'] is not None and unsigned is True:
            k = wanted['HW1-5']
            slot = timeline.events[k].slot
            outside, missing = hyp.pool_rows(archive, entry, 'train', PARAMS, None, (slot + 1, slot + 10 ** 6))
            assert not any(r['decision_index'] == k for r in outside)
            assert any(key.endswith(':outside_evaluation_range') for key in missing)
            late, missing = hyp.pool_rows(archive, entry, 'train', PARAMS, slot - 1)
            assert not late and any(key.endswith(':exit_would_leave_the_window') for key in missing)
    assert seen.get('HW1-5', 0) >= 1 and seen.get(hyp.PLACEBO, 0) >= 1
    entry, archive = archives[0]
    real = hrr.creation_facts
    monkeypatch.setattr(hrr, 'creation_facts', lambda a: dict(real(a), creator=None, signed_creator_verified=False,
                                                              signed_creator_reason='creation_decode_refused:x'))
    rows, missing = hyp.pool_rows(archive, entry, 'train', PARAMS, None)
    assert 'HW1-5' not in [r['hypothesis'] for r in rows] and missing.get('HW1-5:creator_unreadable') == 1


def test_the_p0_run_prints_sizes_only_and_validation_needs_the_family_flag(visible):               # noqa: F811
    directory, sha = visible
    document = hyp.run_p0(directory, sha)
    assert document['segments'] == ['exploration', 'train'] and document['w1_data_read'] is False
    assert {r['segment'] for r in document['rows']} <= {'exploration', 'train'}
    assert hyp.run_p0(directory, sha)['rows_sha256'] == document['rows_sha256']
    sizes = document['counts']
    assert set(sizes) == {'HW1-1', 'HW1-2', 'HW1-3', 'HW1-4', 'HW1-5', 'PLACEBO', 'm'} and sizes['m'] == 0
    assert all(set(sizes[h['id']]) == {'positions', 'clusters', 'distinct_payers', 'migrated', 'migrated_share', 'evaluable'}
               for h in hyp.HYPOTHESES)
    for bad in (dict(segments=('validation',)), dict(segments=('validation',), confirm_validation='HW1-5'),
                dict(segments=('exploration', 'validation'))):
        with pytest.raises(ValueError, match='validation_is_read_once_for_the_frozen_family_HW1'):
            hyp.run_p0(directory, sha, **bad)
    with pytest.raises(ValueError, match='unknown_segment'):
        hyp.run_p0(directory, sha, segments=('holdout',))
    confirmation = hyp.run_p0(directory, sha, segments=('validation',), confirm_validation='HW1')
    assert {r['segment'] for r in confirmation['rows']} <= {'validation'}
    json.dumps(document, allow_nan=False)


def _export(tmp_path, *, shift=0, window=None):
    """A copy of the public fixture export; ``shift`` moves every slot (to imitate a W1 window)."""
    out = tmp_path / ('export_%d' % shift)
    out.mkdir()
    manifest = json.loads((FIXTURES / 'MANIFEST.json').read_text())
    for entry in manifest['pools']:
        data = json.loads(gzip.decompress((FIXTURES / entry['file']).read_bytes()))
        if shift:
            for tx in data['transactions'].values():
                tx['slot'] += shift
            for row in data['signatures']:
                row['slot'] += shift
        raw = gzip.compress(json.dumps(data).encode(), mtime=0)
        (out / entry['file']).write_bytes(raw)
        entry['sha256'] = hashlib.sha256(raw).hexdigest()
    if window:
        manifest.update(window)
    raw = json.dumps(manifest).encode()
    (out / 'MANIFEST.json').write_bytes(raw)
    return out, hashlib.sha256(raw).hexdigest()


def test_the_export_reader_gives_the_same_positions_as_the_pack_reader(visible, tmp_path):          # noqa: F811
    """Identity on P0-format data: same pools, same rows, whatever the reader."""
    directory, sha = visible
    packed = hyp.run_p0(directory, sha)['rows'] + hyp.run_p0(directory, sha, segments=('validation',),
                                                             confirm_validation='HW1')['rows']
    out, manifest_sha = _export(tmp_path)
    exported = hyp.run_export(out, manifest_sha)
    assert exported['w1_data_read'] is False and exported['evaluation'] is None
    strip = lambda rows: sorted((json.dumps({k: v for k, v in r.items() if k != 'segment'}, sort_keys=True)   # noqa: E731
                                 for r in rows))
    assert strip(exported['rows']) == strip(packed) and exported['rows']
    with pytest.raises(ValueError, match='export_manifest_sha256_is_not_the_expected_one'):
        hyp.run_export(out, '0' * 64)


def test_w1_slots_need_the_anchored_verdict_and_the_evaluation_range(tmp_path):
    shift = plan.S0_W1                                           # every slot is now inside the W1 window
    out, manifest_sha = _export(tmp_path, shift=shift)
    with pytest.raises(ValueError, match='w1_data_need_the_sha256_of_the_anchored_official_verdict'):
        hyp.run_export(out, manifest_sha)
    for bad in ('abc', 'G' * 64, None):
        with pytest.raises(ValueError, match='anchored_official_verdict'):
            hyp.run_export(out, manifest_sha, evaluation=(1, 2), official_verdict_sha256=bad)
    with pytest.raises(ValueError, match='w1_data_need_the_evaluation_range'):
        hyp.run_export(out, manifest_sha, official_verdict_sha256='a' * 64)
    with pytest.raises(ValueError, match='invalid_evaluation_range'):
        hyp.run_export(out, manifest_sha, evaluation=(5, 5), official_verdict_sha256='a' * 64)
    base, base_sha = _export(tmp_path)
    plain = hyp.run_export(base, base_sha)['rows']
    slots = sorted(r['decision_slot'] for r in plain)
    middle = slots[len(slots) // 2] + shift
    document = hyp.run_export(out, manifest_sha, evaluation=(middle, 10 ** 12), official_verdict_sha256='a' * 64)
    assert document['w1_data_read'] is True and document['official_verdict_sha256'] == 'a' * 64
    kept = [r for r in plain if r['decision_slot'] + shift >= middle]
    assert len(document['rows']) == len(kept) < len(plain)       # warm-up decisions give no position, never a later one
    assert all(r['decision_slot'] >= middle and r['entry_slot'] >= middle for r in document['rows'])
    assert sum(v for key, v in document['missing'].items() if key.endswith(':outside_evaluation_range')) == len(plain) - len(kept)
    # the declared window of the export also counts
    (tmp_path / 'w').mkdir()
    declared, declared_sha = _export(tmp_path / 'w', window=dict(entry_cutoff_slot=plan.S0_W1 + 5,
                                                                window_slot_max=plan.S0_W1 + 10))
    with pytest.raises(ValueError, match='anchored_official_verdict'):
        hyp.run_export(declared, declared_sha)


def _position(pool, hypothesis, value, *, slot=1, creator=None, payer=None, migrated=False):
    row = _row(pool, [], value, migrated=migrated)
    row.update(hypothesis=hypothesis, creator=creator or 'c' + pool, payer=payer or 'y' + pool, decision_slot=slot)
    return row


def _family(n=60, *, value=lambda i: 125_000_000, placebo=96_000_000, **extra):
    rows = []
    for i in range(n):
        name = 'p%03d' % i
        rows.append(_position(name, 'HW1-5', value(i), slot=i, **{k: v(i) for k, v in extra.items()}))
        rows.append(_position(name, hyp.PLACEBO, placebo, slot=i))
    return rows


def _doc(rows, **over):
    return dict(dict(schema=hyp.SCHEMA, rows=rows, rows_sha256='x', pack_manifest_sha256='m', source='p0_visible',
                     segments=['train'], w1_data_read=False, hypotheses_sha256='h', latency_slots=4), **over)


def test_counts_decide_what_is_evaluable_before_any_value():
    rows = _family(60) + [_position('q%02d' % i, 'HW1-3', 10 ** 9, migrated=i < 4) for i in range(30)]
    rows += [_position('r%02d' % i, 'HW1-1', 10 ** 9) for i in range(29)]
    rows += [_position('s%02d' % i, 'HW1-4', 10 ** 9, creator='same%d' % (i % 19)) for i in range(40)]
    sizes = hyp.counts(rows)
    assert sizes['HW1-5'] == dict(positions=60, clusters=60, distinct_payers=60, migrated=0, migrated_share=0.0, evaluable=True)
    assert sizes['HW1-3']['migrated_share'] == pytest.approx(4 / 30) and sizes['HW1-3']['evaluable'] is False   # > 10 % migrated
    assert sizes['HW1-1']['evaluable'] is False and sizes['HW1-4']['evaluable'] is False   # 29 positions ; 19 clusters
    assert sizes['HW1-2']['positions'] == 0 and sizes['m'] == 1
    out = hyp.verdicts(_doc(rows), declared_m=1, n_boot=500)
    assert [out['hypotheses'][k]['verdict'] for k in ('HW1-1', 'HW1-2', 'HW1-3', 'HW1-4')] == ['NON ÉVALUABLE'] * 4
    assert out['holm_family'] == ['HW1-5'] and out['trials_added_to_n'] == 5
    for bad in (0, 2, None):
        with pytest.raises(ValueError, match='declared_m_is_not_the_number_of_evaluable_hypotheses:1'):
            hyp.verdicts(_doc(rows), declared_m=bad)


def test_the_exploratory_hypothesis_needs_every_condition():
    slow = _doc(_family(60), latency_slots=10)
    good = hyp.verdicts(_doc(_family(60)), declared_m=1, latency10=slow, n_boot=2_000)['hypotheses']['HW1-5']
    r = (125_000_000 - COST - RENT) / (COST + RENT)
    assert good['mean_r'] == pytest.approx(r) and good['primary_passed'] is True and good['r1_met'] is False
    assert all(v is True for v in good['conditions'].values())
    assert good['verdict'] == 'CRITÈRE PRINCIPAL ET CONDITIONS ATTEINTS — CRITÈRES V1 À APPLIQUER'
    assert good['vs_placebo']['pairs'] == 60 and good['vs_placebo']['ci95'][0] > 0 and good['win_rate'] == 1.0
    # without the 10-slot run the latency condition is unknown: never confirmed by default
    pending = hyp.verdicts(_doc(_family(60)), declared_m=1, n_boot=2_000)['hypotheses']['HW1-5']
    assert pending['conditions']['vi_positive_at_latency_10_slots'] is None and pending['verdict'] == 'EXPLORATOIRE NON CONFIRMÉE'
    # a losing average: rejected
    bad = hyp.verdicts(_doc(_family(60, value=lambda i: 96_000_000)), declared_m=1, latency10=slow, n_boot=500)
    assert bad['hypotheses']['HW1-5']['verdict'] == 'REJETÉE' and bad['hypotheses']['HW1-5']['primary_passed'] is False
    # five pools carry everything: the mean and its interval pass, the condition "without the 5 best" fails
    lucky = _family(60, value=lambda i: 2_000_000_000 if i < 5 else 101_000_000)
    block = hyp.verdicts(_doc(lucky), declared_m=1, latency10=_doc(lucky, latency_slots=10), n_boot=2_000)['hypotheses']['HW1-5']
    assert block['primary_passed'] is True and block['conditions']['iii_positive_without_5_best_pools'] is False
    assert block['conditions']['v_no_pool_above_25pct_of_gains'] is True and block['verdict'] == 'EXPLORATOIRE NON CONFIRMÉE'
    # the last chronological third and the middle one lose
    fading = _family(60, value=lambda i: 190_000_000 if i < 20 else 101_000_000)
    block = hyp.verdicts(_doc(fading), declared_m=1, latency10=_doc(fading, latency_slots=10), n_boot=2_000)['hypotheses']['HW1-5']
    assert block['conditions']['iv_two_thirds_of_three_positive'] is False and block['verdict'] == 'EXPLORATOIRE NON CONFIRMÉE'
    # positive at 4 slots but not at 10
    block = hyp.verdicts(_doc(_family(60)), declared_m=1, n_boot=2_000,
                         latency10=_doc(_family(60, value=lambda i: 96_000_000), latency_slots=10))['hypotheses']['HW1-5']
    assert block['conditions']['vi_positive_at_latency_10_slots'] is False and block['verdict'] == 'EXPLORATOIRE NON CONFIRMÉE'
    with pytest.raises(ValueError, match='latency10_rows_are_not_the_10_slot_run_of_the_same_data'):
        hyp.verdicts(_doc(_family(60)), declared_m=1, latency10=_doc(_family(60)))
    # one payer behind every creation with enough distinct payers elsewhere: the payer interval must not contradict
    one = _family(60, value=lambda i: 250_000_000 if i % 3 == 0 else 100_000_000, payer=lambda i: 'pay%d' % (i % 3))
    block = hyp.verdicts(_doc(one), declared_m=1, latency10=_doc(one, latency_slots=10), n_boot=2_000)['hypotheses']['HW1-5']
    assert block['payer_cluster_sensitivity'] == dict(distinct_payers=3, evaluable=False,
                                                      mean_r_ci95=block['payer_cluster_sensitivity']['mean_r_ci95'])
    # six winners behind ONE payer, the 54 others lose slightly: positive by creators, not by payers
    many = _family(60, value=lambda i: 400_000_000 if i < 6 else 101_500_000,
                   payer=lambda i: 'pay0' if i < 6 else 'pay%d' % (1 + i % 19))
    block = hyp.verdicts(_doc(many), declared_m=1, latency10=_doc(many, latency_slots=10), n_boot=2_000)['hypotheses']['HW1-5']
    assert block['payer_cluster_sensitivity']['evaluable'] is True and block['primary_passed'] is True
    assert block['payer_cluster_sensitivity']['mean_r_ci95'][0] <= 0 and block['verdict'] == 'NON CONCLUANT'
    text = hyp.markdown(hyp.verdicts(_doc(_family(60)), declared_m=1, latency10=slow, n_boot=500))
    assert '| HW1-5 NON SIGNE | 10 | 60 | 60 | 0 |' in text and '(vi) moyenne > 0 à 10 slots de latence' in text


def test_holm_is_applied_over_the_evaluable_family_and_migrated_positions_count_minus_one():
    rows = _family(60, value=lambda i: 103_500_000 + 40_000 * i)                   # a small positive edge
    rows += [_position('a%03d' % i, 'HW1-1', 96_000_000) for i in range(40)]
    rows += [_position('b%03d' % i, 'HW1-2', 200_000_000, migrated=i < 4) for i in range(40)]   # exactly 10 % migrated
    out = hyp.verdicts(_doc(rows), declared_m=3, latency10=_doc(rows, latency_slots=10), n_boot=4_000)
    h = out['hypotheses']
    assert out['holm_family'] == ['HW1-1', 'HW1-2', 'HW1-5'] and h['HW1-1']['verdict'] == 'REJETÉE'
    win = (200_000_000 - COST - RENT) / (COST + RENT)
    assert h['HW1-2']['mean_r'] == pytest.approx((36 * win - 4) / 40) and h['HW1-2']['migrated'] == 4
    assert h['HW1-2']['verdict'] == 'CRITÈRE PRINCIPAL ATTEINT — CRITÈRES V1 À APPLIQUER' and h['HW1-2']['r1_met'] is False
    assert h['HW1-5']['p_holm'] >= h['HW1-5']['p_one_sided'] and h['HW1-1']['p_holm'] == 1.0
    census = dict(schema='t22pol-census-v1', disagreements_with_frozen_reader=[], rows=[])
    with pytest.raises(ValueError, match='token_class_unknown'):
        hyp.verdicts(_doc(rows), census, declared_m=3, n_boot=0)
    with pytest.raises(ValueError, match='not_a_hypothesis_rows_document'):
        hyp.verdicts(dict(_doc(rows), schema='x'), declared_m=3)


def test_a_positive_mean_is_not_enough_and_holm_can_reject_what_a_single_test_would_pass():
    # one huge winner among slight losers: the mean is positive, the interval is not
    lone = _family(60, value=lambda i: 3_000_000_000 if i == 0 else 101_000_000)
    block = hyp.verdicts(_doc(lone), declared_m=1, latency10=_doc(lone, latency_slots=10), n_boot=2_000)['hypotheses']['HW1-5']
    assert block['mean_r'] > 0 and block['mean_r_ci95'][0] <= 0 and block['primary_passed'] is False
    assert block['verdict'] == 'REJETÉE'
    # a family of three: a result that a single test would accept (p < 0.025) is refused by Holm (p x 3 >= 0.05)
    found = None
    for winners in range(148, 158):
        rows = [_position('h%03d' % i, 'HW1-1', 130_000_000 if i < winners else 80_000_000) for i in range(300)]
        rows += [_position('i%03d' % i, 'HW1-2', 96_000_000) for i in range(40)]
        rows += _family(40, value=lambda i: 96_000_000)
        out = hyp.verdicts(_doc(rows), declared_m=3, n_boot=4_000)['hypotheses']['HW1-1']
        if out['mean_r_ci95'][0] > 0 and 0.05 / 3 <= out['p_one_sided'] < 0.025:
            found = out
            break
    assert found is not None, 'no calibration point between the single-test and the Holm thresholds'
    assert found['p_holm'] >= 0.05 and found['primary_passed'] is False and found['verdict'] == 'REJETÉE'


def test_a_buy_that_lands_outside_the_evaluation_range_gives_no_position(archives):                # R02 T-H2  # noqa: F811
    found = 0
    for entry, archive in archives:
        rows, _missing = hyp.pool_rows(archive, entry, 'export', PARAMS, None)
        for row in rows:
            decision, landing = row['decision_slot'], row['entry_slot']
            if landing == decision:
                continue                                       # the buy landed in the slot of its decision
            # the decision is inside the range, the landing is its (excluded) upper bound
            kept, missing = hyp.pool_rows(archive, entry, 'export', PARAMS, None, (decision, landing))
            assert not any(r['hypothesis'] == row['hypothesis'] for r in kept)
            assert missing.get('%s:landing_outside_evaluation_range' % row['hypothesis']) == 1
            # one slot more and the same position is back, unchanged
            again, _missing = hyp.pool_rows(archive, entry, 'export', PARAMS, None, (decision, landing + 1))
            assert [r for r in again if r['hypothesis'] == row['hypothesis']] == [row]
            found += 1
    assert found >= 1
