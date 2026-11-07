"""Offline HISTORICAL_REPLAY of the Master scorers on the committed LaunchLab pools."""
import ast
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from bot.analyser.behavior_pipeline import wallet_graph_snapshot
from bot.analyser.final_decision_engine import build_features
from bot.market.collector import PoolArchive, summarize
from bot.market.launchlab_events import WSOL_MINT
from bot.market.replay import Position
from bot.master_decision import POLICY as MASTER_POLICY, MasterDecisionOrchestrator
from bot.p4 import creator_disjoint_shadow_audit
from bot.p4 import historical_research_replay as hrr
from bot.p4.native_asof_signal_bridge import NativeQuote

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
MANIFEST = json.loads((PACK / 'MANIFEST.json').read_text(encoding='utf-8'))
C7F9 = 'C7F9KbS3XXUoScx7bd9eYfFtAqvqVnBdRFLRSEKLeSpC'
P5PZ = '5pZ6MdyXtsPCptPe6NWx5M4aSTo7N5QUapHiUVDL3oy2'
DVP = 'DVP426ot5M4gjTxKqoYJn1ATqrzvZfkqVSu1vP9a9E4r'
VAULT = 'WLHv2UAZm6z4KyaaELi5pjdbJh6RESMva1Rnn8pJVVh'
DECLARED = dict(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED')


@lru_cache(maxsize=None)
def bundle(**kwargs):
    return hrr.run_replay(PACK, hrr.ReplayParams(**kwargs))


def archives():
    return {archive.pool: archive for _entry, archive in hrr.load_fixtures(PACK)[2]}


def pool(doc, address):
    return next(row for row in doc['pools'] if row['pool'] == address)


def cached_rows(archive, limit):
    rows = sorted(archive.transactions.items(), key=lambda kv: (kv[1]['slot'], kv[1]['transactionIndex']))
    return [(tx['blockTime'], signature, tx) for signature, tx in rows[:limit]]


def test_holder_exclusion_defaults_are_unchanged_and_only_touch_holder_statistics():
    archive = archives()[P5PZ]           # the vault authority holds >= 90% here
    cached = cached_rows(archive, 4)
    facts = hrr.creation_facts(archive)
    mint, creator, start = facts['mint'], facts['creator'], facts['creation_block_time']
    end = cached[-1][0]
    default = wallet_graph_snapshot(cached, mint, start, end)
    assert default == wallet_graph_snapshot(cached, mint, start, end, excluded_owners=())
    excluded = wallet_graph_snapshot(cached, mint, start, end, excluded_owners=[VAULT])
    assert default['top_holder_share'] >= 0.9 and excluded['top_holder_share'] < default['top_holder_share']
    assert excluded['holder_count'] == default['holder_count'] - 1
    for key in ('linked_wallets', 'wallet_link_count', 'same_slot_wallets', 'source_transactions'):
        assert excluded[key] == default[key]
    quote = NativeQuote(price_usd=0.001, liquidity_usd=500.0)
    args = (cached, mint, creator, start, end, [], quote)
    base = build_features(*args)
    assert base == build_features(*args, excluded_holder_owners=())
    changed = build_features(*args, excluded_holder_owners=[VAULT]).to_dict()
    differing = {k for k, v in base.to_dict().items() if changed[k] != v}
    assert differing == {'holder_count', 'top_holder_share'}


def test_bundle_is_deterministic_and_self_hashed():
    params = hrr.ReplayParams(exclude_launchlab_vault=True, **DECLARED)
    first, second = hrr.run_replay(PACK, params), hrr.run_replay(PACK, params)
    assert first == second and first['bundle_sha256'] == second['bundle_sha256']
    body = {k: v for k, v in first.items() if k != 'bundle_sha256'}
    assert first['bundle_sha256'] == hrr._sha(body)
    assert first['params_sha256'] == hrr._sha(asdict(params)) == hrr._sha(first['params'])
    assert bundle()['bundle_sha256'] != first['bundle_sha256']


def test_labels_and_separation_flags():
    doc = bundle(**DECLARED)
    assert doc['schema'] == hrr.SCHEMA == 'rugger-historical-research-replay-v1'
    assert doc['category'] == hrr.CATEGORY == 'HISTORICAL_REPLAY'
    assert doc['entry_lamports'] == hrr.ENTRY_LAMPORTS == 100_000_000
    assert doc['fixtures']['files'] == {e['file']: e['sha256'] for e in MANIFEST['pools']}
    flags = doc['flags']
    assert flags['source_clock_verified'] is False and 'receipt_latency_ms' in flags['source_clock_model']
    assert flags['asof_inputs_causal'] is True
    assert flags['sol_usd'] == 150 and flags['sol_usd_provenance'] == 'ASSUMED_DECLARED'
    assert flags['sol_usd_verified'] is False and flags['archived_pool_account_used'] is False
    assert flags['admissible_in_paper_ledger'] is False and flags['counted_in_master_gate'] is False
    assert flags['master_operational_trade'] is False
    assert flags['research_evidence_status'] == 'PENDING_R02_QUALIFICATION'
    assert flags['failed_attempt_fees_modelled'] is False
    assert 0.33 < flags['fixture_failed_signature_share'] < 0.35
    params = doc['params']
    assert (params['latency_slots'], params['receipt_latency_ms']) == (2, 400)
    assert (params['exit_horizon_ms'], params['base_fee_lamports'], params['priority_fee_lamports']) == (
        30000, 5000, 100000)
    for row in (r for p in doc['pools'] for r in p['journal']):
        assert row['modelled_receipt_ms'] == row['block_time'] * 1000 + 400
        assert row['inputs_causal'] is True and len(row['features_sha256']) == 64
        assert row['intent'] == 'ENTER' or row['blocking_reasons']
        # The operational Master gate is evaluated untouched and never admits these frames.
        assert row['operational_master_action'] != 'ENTER'
        assert 'qualified_past_edge_evidence_unavailable' in row['operational_master_reasons']


def test_without_sol_usd_every_decision_waits_with_an_explicit_reason():
    doc = bundle()
    assert doc['flags']['sol_usd'] is None and doc['flags']['sol_usd_provenance'] is None
    journal = [row for p in doc['pools'] for row in p['journal']]
    assert len(journal) == 2 * sum(e['trades'] for e in MANIFEST['pools'])
    assert all(row['intent'] == 'WAIT' and row['features_sha256'] is None
               and 'sol_usd_rate_unavailable' in row['blocking_reasons'] for row in journal)
    for arm in hrr.ARMS:
        assert doc['totals'][arm]['entries'] == 0 and doc['totals'][arm]['enter_decisions'] == 0
        assert doc['totals'][arm]['blocking_reasons']['sol_usd_rate_unavailable'] == len(journal) // 2
    assert {p['arms'][a]['outcome'] for p in doc['pools'] for a in hrr.ARMS} == {'no_entry'}


def test_signed_creator_and_vault_authority_come_from_the_creation_transaction():
    doc = bundle()
    inner = pool(doc, P5PZ)
    assert inner['signed_creator_verified'] is False
    assert 'creation_is_inner_cpi_not_in_signed_outer_message' in inner['signed_creator_reason']
    assert 'creator_not_a_transaction_signer' in inner['signed_creator_reason']
    assert all('signed_creator_unverified' in row['blocking_reasons'] for row in inner['journal'])
    for address in (C7F9, DVP):
        assert pool(doc, address)['signed_creator_verified'] is True
    for row in doc['pools']:
        assert row['vault_authority'] == VAULT and row['base_decimals'] == 6
        archive = archives()[row['pool']]
        assert row['creator'] == archive.account['creator'] and row['mint'] == archive.account['mint_base']


def test_inner_creation_blocks_the_research_entry_even_with_scorer_intent():
    inner = pool(bundle(exclude_launchlab_vault=True, **DECLARED), P5PZ)
    intended = [row for row in inner['journal'] if row['strategy_intents']['early_sniping']['entry_intent']]
    assert intended and all(row['intent'] == 'WAIT'
                            and row['blocking_reasons'] == ['signed_creator_unverified'] for row in intended)
    assert pool(bundle(exclude_launchlab_vault=True, **DECLARED), DVP)['journal'][-1]['vetoes'] == [
        'vente_developpeur']


def _truncated(archive, keep):
    kept = {s: tx for s, tx in archive.transactions.items() if (tx['slot'], tx['transactionIndex']) <= keep}
    rows = [r for r in archive.signatures if r['signature'] in kept or r.get('err') is not None]
    return PoolArchive(archive.pool, archive.account, rows, True, kept)


def test_later_transactions_never_change_an_earlier_decision():
    params = hrr.ReplayParams(exclude_launchlab_vault=True, **DECLARED)
    archive = archives()[C7F9]
    full = hrr.replay_pool(archive, params, quote_mint=WSOL_MINT)
    decision = next(row for row in full['journal'] if row['arm'] == 'master' and row['index'] == 30)
    cut = (decision['slot'], decision['transaction_index'])
    mutated = deepcopy(archive)
    for tx in mutated.transactions.values():
        if (tx['slot'], tx['transactionIndex']) > cut:
            tx['meta']['postTokenBalances'].append(dict(
                accountIndex=0, mint=full['mint'], owner='FutureWha1e111111111111111111111111111111111',
                uiTokenAmount=dict(amount='900000000000000', decimals=6, uiAmount=9e8)))
    for variant in (mutated, _truncated(archive, cut)):
        other = hrr.replay_pool(variant, params, quote_mint=WSOL_MINT)
        before = [row for row in full['journal'] if row['index'] <= 30]
        assert before == [row for row in other['journal'] if row['index'] <= 30]
    for row in full['journal']:
        last = (row['inputs']['max_slot'], row['inputs']['max_transaction_index'])
        assert last <= (row['slot'], row['transaction_index'])
    assert decision['inputs']['transactions'] == sum(
        (tx['slot'], tx['transactionIndex']) <= cut for tx in archive.transactions.values())


class _EnterAt(hrr._PoolObserver):
    enter_index = 10

    def _evaluate(self, history):
        result = super()._evaluate(history)
        if len(history) - 1 == self.enter_index:
            result = dict(result, exit_conditions=dict(tp_pct=10.0, sl_pct=8.0), decisions={
                arm: dict(intent='ENTER', blocking_reasons=[]) for arm in hrr.ARMS})
        return result


def test_forced_cycle_accounting_and_preregistered_exit():
    params = hrr.ReplayParams(failed_attempt_fee_lamports=7_000, **DECLARED)
    archive = archives()[C7F9]
    _summary, timeline = summarize(archive)
    observer = _EnterAt(archive, timeline, hrr.creation_facts(archive), params)
    arm = hrr.ResearchArm('master', observer, params)
    result = hrr.replay(timeline, arm, params.execution_model(), quote_mint=WSOL_MINT)
    trade = hrr._trade(result, timeline.events, arm, params)
    assert trade['decision_index'] == 10 and trade['spent'] == hrr.ENTRY_LAMPORTS
    assert trade['outcome'] in ('closed', 'open_at_end') and trade['tokens'] > 0
    assert trade['tx_costs'] == 2 * 105_000 and trade['failed_attempt_costs'] == 14_000
    value = trade['received'] - trade['spent'] - trade['tx_costs'] - trade['failed_attempt_costs']
    # Only a closed cycle has a P&L; an open position keeps its mark apart (P0 fix).
    if trade['outcome'] == 'closed':
        assert trade['pnl_lamports'] == value
    else:
        assert trade['pnl_lamports'] is None and trade['mark_pnl_lamports'] == value
    # Causal fee estimate: every past event of this pool allows exactly 12 500 ppm.
    assert trade['fee_rate_ppm'] == 12_500 and trade['fee_rate_source'] == 'pool_events_causal_interval'
    assert trade['fee_rate_evidence']['interval_ppm'] == [12_500, 12_500]
    assert trade['fee_rate_evidence']['events_used'] == trade['decision_index'] + 1
    assert trade['entry_slot'] <= trade['decision_slot'] + params.latency_slots
    if trade['outcome'] == 'closed':
        assert trade['exit_trigger']['reason'] in ('take_profit', 'stop_loss', 'exit_horizon')
    assert all(not {'research_evidence', 'bank_state', 'inventory_context'} & set(frame)
               for frame in observer.frames.values())
    position = Position(0, 1, 100, 1_000, 5)     # tp 10%, sl 8%, horizon 30 s
    for block_time, mark, expected in ((101, 1_100, 'take_profit'), (101, 920, 'stop_loss'),
                                       (129, 1_099, None), (130, 1_000, 'exit_horizon')):
        arm.exit_trigger = None
        assert arm.exit([SimpleNamespace(block_time=block_time)], position, mark) is (expected is not None)
        assert (arm.exit_trigger or {}).get('reason') == expected


def test_any_priced_bundle_cycle_satisfies_the_pnl_identity():
    for kwargs in ({}, DECLARED, dict(exclude_launchlab_vault=True, **DECLARED)):
        for row in (p['arms'][a] for p in bundle(**kwargs)['pools'] for a in hrr.ARMS):
            if row['pnl_lamports'] is not None:
                assert row['pnl_lamports'] == (row['received'] - row['spent'] - row['tx_costs']
                                               - row['failed_attempt_costs'])
            else:
                assert row['outcome'] not in ('closed', 'open_at_end')


def test_parameters_and_fixtures_are_refused_when_invalid(tmp_path):
    with pytest.raises(ValueError, match='sol_usd_provenance_required'):
        hrr.ReplayParams(sol_usd=150)
    with pytest.raises(ValueError, match='sol_usd_provenance_without_rate'):
        hrr.ReplayParams(sol_usd_provenance='ASSUMED_DECLARED')
    with pytest.raises(ValueError, match='invalid_sol_usd'):
        hrr.ReplayParams(sol_usd=float('nan'), sol_usd_provenance='X')
    with pytest.raises(ValueError, match='invalid_receipt_latency_ms'):
        hrr.ReplayParams(receipt_latency_ms=1000)
    copy = tmp_path / 'pack'
    shutil.copytree(PACK, copy)
    target = copy / MANIFEST['pools'][0]['file']
    data = bytearray(target.read_bytes())
    data[-1] ^= 1
    target.write_bytes(bytes(data))
    with pytest.raises(ValueError, match='fixture_sha256_mismatch'):
        hrr.run_replay(copy, hrr.ReplayParams())


def test_protected_master_thresholds_are_unchanged():
    assert MASTER_POLICY['min_qualified_cycles'] == 50 and MASTER_POLICY['min_creator_groups'] == 20
    assert creator_disjoint_shadow_audit.MIN_QUALIFIED_CYCLES == 50
    assert creator_disjoint_shadow_audit.MIN_HOLDOUT_CREATORS == 50
    for key in ('min_qualified_cycles', 'min_creator_groups'):
        with pytest.raises(ValueError):
            MasterDecisionOrchestrator(dict(MASTER_POLICY, **{key: MASTER_POLICY[key] - 1}))


def test_paper_ledger_and_research_gate_are_never_reached():
    source = Path(hrr.__file__).read_text(encoding='utf-8')
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not {name for name in imported if 'ledger' in name or 'research_paper_intent' in name}
    for forbidden in ('PaperLedger', 'live_like_paper_ledger', "'research_evidence'", 'freeze_decision'):
        assert forbidden not in source
    code = ('import sys,types;d=types.ModuleType("dotenv");d.load_dotenv=lambda*a,**k:False;'
            'sys.modules["dotenv"]=d;from bot.p4 import historical_research_replay as m;'
            'm.run_replay(sys.argv[1],m.ReplayParams(sol_usd=150,sol_usd_provenance="X"));'
            'print(sorted(k for k in sys.modules if "ledger" in k or "research_paper_intent" in k))')
    env = dict(os.environ, RUGGER_NO_DOTENV='1', PYTHONDONTWRITEBYTECODE='1')
    output = subprocess.run([sys.executable, '-B', '-c', code, str(PACK)], cwd=ROOT, env=env,
                            capture_output=True, text=True, check=True, timeout=300).stdout
    assert output.strip() == '[]'


def _forced(window, params=hrr.ReplayParams(**DECLARED)):
    archive = archives()[C7F9]
    _summary, timeline = summarize(archive)
    observer = _EnterAt(archive, timeline, hrr.creation_facts(archive), params)
    arm = hrr.ResearchArm('master', observer, params, window)
    result = hrr.replay(timeline, arm, params.execution_model(), quote_mint=WSOL_MINT)
    return hrr._apply_window(hrr._trade(result, timeline.events, arm, params), window), arm, timeline


def test_collection_window_validation_and_absence():
    params = hrr.ReplayParams()
    assert hrr.collection_window({'pool': 'x'}, {'pools': []}, params) is None
    gap = -(-params.exit_horizon_ms // hrr.SLOT_MS_FLOOR) + 2 * params.latency_slots
    assert (hrr.SLOT_MS_FLOOR, gap) == (350, 90)   # 30 s horizon on 350 ms slots + 2 x 2 latency slots
    window = hrr.collection_window({'entry_cutoff_slot': 1000, 'window_slot_max': 1000 + gap}, {}, params)
    assert window == dict(entry_cutoff_slot=1000, window_slot_max=1000 + gap, minimum_gap_slots=gap)
    # Top-level values apply when the pool entry has none.
    assert hrr.collection_window({}, {'entry_cutoff_slot': 1, 'window_slot_max': 1 + gap}, params)
    for bad, error in (({'entry_cutoff_slot': 5}, 'invalid_collection_window'),
                       ({'entry_cutoff_slot': 10, 'window_slot_max': 10}, 'invalid_collection_window'),
                       ({'entry_cutoff_slot': 10, 'window_slot_max': 10 + gap - 1},
                        'collection_window_gap_shorter_than_exit_horizon')):
        with pytest.raises(ValueError, match=error):
            hrr.collection_window(bad, {}, params)


def test_no_entry_after_the_cutoff_slot():
    _summary, timeline = summarize(archives()[C7F9])
    decision_slot = timeline.events[_EnterAt.enter_index].slot
    window = dict(entry_cutoff_slot=decision_slot - 1, window_slot_max=decision_slot + 10_000)
    trade, arm, _timeline = _forced(window)
    assert trade['outcome'] == 'no_entry' and trade['entry_index'] is None
    late = [row for row in arm.journal if row['slot'] > window['entry_cutoff_slot']]
    assert late and all(row['intent'] == 'WAIT' and 'after_entry_cutoff_slot' in row['blocking_reasons']
                        for row in late)


def test_exit_after_window_end_is_never_a_closed_cycle():
    free, _arm, timeline = _forced(None)
    assert free['entry_index'] is not None
    decision_slot = timeline.events[_EnterAt.enter_index].slot
    # Window ends right after the entry: any exit (or end-of-data mark) falls outside it.
    window = dict(entry_cutoff_slot=decision_slot, window_slot_max=free['entry_slot'])
    trade, _arm, _timeline = _forced(window)
    assert trade['outcome'] == 'open_at_window_end'
    assert trade['pnl_lamports'] is None and trade['net_return'] is None
    free_value = free['pnl_lamports'] if free['outcome'] == 'closed' else free['mark_pnl_lamports']
    assert trade['mark_pnl_lamports'] == free_value


def test_manifest_window_is_read_and_default_bundle_unchanged(tmp_path):
    pack = tmp_path / 'pack'
    shutil.copytree(PACK, pack)
    manifest = json.loads((pack / 'MANIFEST.json').read_text(encoding='utf-8'))
    for entry in manifest['pools']:
        entry['entry_cutoff_slot'], entry['window_slot_max'] = 1, 10**12
    (pack / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    doc = hrr.run_replay(pack)
    assert all(row['window']['window_slot_max'] == 10**12 for row in doc['pools'])
    assert 'collection_window_rule' in doc['flags']
    reasons = doc['totals']['master']['blocking_reasons']
    assert reasons.get('after_entry_cutoff_slot', 0) > 0
    default = bundle()
    assert 'collection_window_rule' not in default['flags']
    assert all('window' not in row for row in default['pools'])
