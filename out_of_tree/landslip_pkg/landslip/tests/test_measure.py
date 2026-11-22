"""landslip: counts of other traders' buy failures by priority and of their reaction gap, on the public fixtures."""
import copy
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

import bot
from bot.market import launchlab_events as LE
from landslip import measure as M
from w1aux.lazy import clear_cache, load_fixtures_lazy

PACK = Path(bot.__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'launchlab_sol_pools'
SHA = hashlib.sha256((PACK / 'MANIFEST.json').read_bytes()).hexdigest()
L = M.LAUNCHLAB
TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'


def _archives():
    try:
        return [a for _e, a in load_fixtures_lazy(PACK)[2]]
    finally:
        clear_cache()


def test_only_the_launchlab_frame_names_its_instruction():
    logs = [f'Program {L} invoke [1]', f'Program {TOKEN} invoke [2]', 'Program log: Instruction: TransferChecked',
            f'Program {TOKEN} success', 'Program log: Instruction: BuyExactIn', 'Program log: Instruction: Second',
            f'Program {L} success',
            'Program Router111 invoke [1]', f'Program {L} invoke [2]', 'Program log: Instruction: SellExactIn',
            f'Program {L} failed: custom program error: 0x1']
    assert M.launchlab_instructions(logs) == ['BuyExactIn', 'SellExactIn']
    assert M.launchlab_instructions(['Program log: Instruction: BuyExactIn']) == []          # outside any frame
    assert M.launchlab_instructions(None) == []


def _tx_with(instructions, keys):
    return dict(transaction=dict(message=dict(accountKeys=keys, instructions=instructions)), meta=dict())


def test_the_declared_unit_price_and_its_buckets():
    keys = [M.COMPUTE_BUDGET, 'Other']
    price = dict(programIdIndex=0, data=LE.b58encode(bytes([3]) + struct.pack('<Q', 12_345)))
    limit = dict(programIdIndex=0, data=LE.b58encode(bytes([2]) + struct.pack('<I', 200_000)))
    other = dict(programIdIndex=1, data=LE.b58encode(bytes([3]) + struct.pack('<Q', 9)))
    assert M.unit_price(_tx_with([limit, price, other], keys)) == 12_345
    assert M.unit_price(_tx_with([limit, other], keys)) is None
    assert M.unit_price(_tx_with([price], [{'pubkey': M.COMPUTE_BUDGET}])) == 12_345            # jsonParsed keys
    cases = {None: 'none', 0: '0', 1: '1-10000', 10_000: '1-10000', 10_001: '10001-100000', 100_000: '10001-100000',
             100_001: '100001-1000000', 1_000_000: '100001-1000000', 1_000_001: '>1000000'}
    for value, bucket in cases.items():
        assert M.priority_bucket(value) == bucket
    for gap, bucket in {0: '0', 4: '4', 5: '5-8', 8: '5-8', 9: '9-32', 32: '9-32', 33: '>32'}.items():
        assert M.gap_bucket(gap) == bucket
    with pytest.raises(M.MeasureError, match='events_out_of_order'):
        M.gap_bucket(-1)


def test_counts_on_the_fixture_pack_match_an_independent_count():
    doc = M.measure(PACK, SHA)
    buys = sum(1 for a in _archives() for tx in a.transactions.values()
               if any(n in M.BUY_INSTRUCTIONS for n in M.launchlab_instructions(tx['meta']['logMessages'])))
    by_priority = doc['buys_by_priority']
    assert sum(v['ok'] for v in by_priority.values()) == buys > 0
    assert sum(v['failed'] for v in by_priority.values()) == 0                                # no failed tx in the fixtures
    expected = 0
    for a in _archives():
        events = sorted((e for tx in a.transactions.values() for e in LE.extract_trade_events(tx) if e.pool == a.pool),
                        key=lambda e: (e.slot, e.signature, e.event_index))
        expected += sum(1 for e in events[1:] if e.side == 'buy')
    assert sum(doc['buy_reaction_gap_slots'].values()) == expected > 0
    assert doc['pools'] == 3 and doc['measures_our_landing'] is False and doc['descriptive_only'] is True
    # counts only: integers under fixed keys, no identifier anywhere
    assert set(doc) == {'schema', 'pools', 'input', 'buys_by_priority', 'buy_reaction_gap_slots', 'measures_our_landing',
                        'label', 'descriptive_only'}
    assert set(by_priority) == set(M.PRIORITY_BUCKETS) and set(doc['buy_reaction_gap_slots']) == set(M.GAP_BUCKETS)
    text = json.dumps(doc)
    for a in _archives():
        assert a.pool not in text and not any(sig in text for sig in a.transactions)


def test_a_failed_buy_is_counted_as_failed_in_its_priority_bucket():
    archive = _archives()[0]
    txs = copy.deepcopy(archive.transactions)
    target = next(sig for sig, tx in txs.items()
                  if 'BuyExactIn' in M.launchlab_instructions(tx['meta']['logMessages']))
    txs[target]['meta']['err'] = {'InstructionError': [3, {'Custom': 6001}]}
    txs[target]['meta']['innerInstructions'] = []
    bucket = M.priority_bucket(M.unit_price(txs[target]))
    counts = dict(buys_by_priority={b: dict(ok=0, failed=0) for b in M.PRIORITY_BUCKETS},
                  buy_reaction_gap_slots={b: 0 for b in M.GAP_BUCKETS})
    M.measure_archive(SimpleNamespace(pool=archive.pool, transactions=txs), counts)
    assert counts['buys_by_priority'][bucket]['failed'] == 1
    base = dict(buys_by_priority={b: dict(ok=0, failed=0) for b in M.PRIORITY_BUCKETS},
                buy_reaction_gap_slots={b: 0 for b in M.GAP_BUCKETS})
    M.measure_archive(archive, base)
    assert counts['buys_by_priority'][bucket]['ok'] == base['buys_by_priority'][bucket]['ok'] - 1
    # the failed buy has no decoded event (inner instructions): it leaves the reaction gaps
    assert sum(counts['buy_reaction_gap_slots'].values()) <= sum(base['buy_reaction_gap_slots'].values())


def test_inputs_are_guarded(tmp_path, capsys):
    with pytest.raises(M.MeasureError, match='holdout_refused'):
        M.measure(PACK, '9f19ccac' + '0' * 56)
    with pytest.raises(M.MeasureError, match='manifest_is_not_the_anchored_one'):
        M.measure(PACK, '0' * 64)
    assert M.main(['--pack', str(PACK), '--manifest-sha256', SHA, '--out', str(tmp_path / 'o')]) == 0
    raw = (tmp_path / 'o' / 'LANDSLIP_COUNTS.json').read_bytes()
    assert json.loads(capsys.readouterr().out)['sha256'] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(M.MeasureError, match='output_exists'):
        M.main(['--pack', str(PACK), '--manifest-sha256', SHA, '--out', str(tmp_path / 'o')])
