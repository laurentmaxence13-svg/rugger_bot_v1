"""Rugger Wallet research view (L3): labels, sha256 verification, rows and links. Offline."""
import ast
import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from bot.dashboard import research_view as rv
from bot.p4 import historical_research_replay as hrr
from bot.p4 import sol_usd_series as sus

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools'
COMMITTED = ROOT / 'validation' / 'historical_replay_l1' / 'bundle_default.json'
MINT_LIKE = '11111111111111111111111111111111'           # system program: decodes to 32 bytes


def raw(document):
    return json.dumps(document, indent=1, sort_keys=True).encode()


def resealed(document):
    """Recompute bundle_sha256 after a deliberate change (a self-consistent forgery)."""
    body = {k: v for k, v in document.items() if k != 'bundle_sha256'}
    return dict(body, bundle_sha256=rv.canonical_sha256(body))


@pytest.fixture(scope='module')
def committed():
    registry = rv.load_results_registry(ROOT)
    return rv.verify_bundle(COMMITTED.read_bytes(), registry=registry, name='committed'), registry


def test_committed_bundle_is_verified_against_the_results_registry(committed):
    (document, verification), _registry = committed
    assert verification['status'] == 'VERIFIED_AGAINST_RESULTS_REGISTRY'
    assert verification['registry_variant'] == 'a_default'
    assert verification['file_sha256'] == hashlib.sha256(COMMITTED.read_bytes()).hexdigest()
    assert verification['bundle_sha256'] == document['bundle_sha256'] == (
        'fa86f314f015277fc7a84f0124e5a04c4beaef00ab7caec05f91e3d255985270')
    loaded, refused = rv.committed_bundles(ROOT)
    assert refused == [] and [v['committed_path'] for _d, v in loaded] == [
        'validation/historical_replay_l1/bundle_default.json']


def test_canonical_hash_is_the_replay_hash(committed):
    (document, _v), _r = committed
    body = {k: v for k, v in document.items() if k != 'bundle_sha256'}
    assert rv.canonical_sha256(body) == hrr._sha(body)


def test_tampering_is_refused_or_never_shown_as_registered(committed):
    (document, _v), registry = committed
    edited = copy.deepcopy(document)
    edited['pools'][0]['journal'][0]['intent'] = 'ENTER'
    with pytest.raises(rv.BundleRefused, match='bundle_sha256_mismatch'):
        rv.verify_bundle(raw(edited), registry=registry)
    # Re-sealed forgery: self-consistent, but never presented as the registered bundle.
    _doc, verification = rv.verify_bundle(raw(resealed(edited)), registry=registry)
    assert verification['status'] == 'SELF_CONSISTENT_NOT_IN_REGISTRY'
    assert verification['registry_variant'] is None
    # Same bundle_sha256 but other file bytes than the registry entry.
    with pytest.raises(rv.BundleRefused, match='file_sha256_differs_from_results_registry'):
        rv.verify_bundle(COMMITTED.read_bytes() + b'\n', registry=registry)


@pytest.mark.parametrize('mutate, reason', [
    (lambda d: d['flags'].update(master_operational_trade=True), 'bundle_flag_must_be_false:master_operational_trade'),
    (lambda d: d['flags'].update(counted_in_master_gate=None), 'bundle_flag_must_be_false:counted_in_master_gate'),
    (lambda d: d['flags'].pop('financial_order_submitted'), 'bundle_flag_must_be_false:financial_order_submitted'),
    (lambda d: d['flags'].update(admissible_in_paper_ledger=1), 'bundle_flag_must_be_false:admissible_in_paper_ledger'),
    (lambda d: d.update(category='REAL'), 'bundle_category'),
    (lambda d: d['flags'].update(category='PROSPECTIVE_PAPER'), 'bundle_category'),
    (lambda d: d.update(schema='rugger-dual-arm-live-like-paper-ledger-v1'), 'bundle_schema_not_supported'),
])
def test_bundle_claiming_real_or_operational_status_is_refused(committed, mutate, reason):
    (document, _v), registry = committed
    edited = copy.deepcopy(document)
    mutate(edited)
    with pytest.raises(rv.BundleRefused, match=reason):
        rv.verify_bundle(raw(resealed(edited)), registry=registry)


def test_malformed_input_is_refused():
    with pytest.raises(rv.BundleRefused, match='json_constant_refused'):
        rv.verify_bundle(b'{"schema": NaN}')
    with pytest.raises(rv.BundleRefused, match='bundle_json'):
        rv.verify_bundle(b'not json')
    with pytest.raises(rv.BundleRefused, match='bundle_size'):
        rv.verify_bundle(b' ' * (rv.MAX_BUNDLE_BYTES + 1))
    with pytest.raises(rv.BundleRefused, match='bundle_schema_not_supported'):
        rv.verify_bundle(b'[]')


def test_default_bundle_rows_labels_and_empty_pnl(committed):
    (document, verification), _r = committed
    assert rv.bundle_labels(document) == ('HISTORICAL_REPLAY', [])
    pools, decisions, cycles = rv.pool_rows(document), rv.decision_rows(document), rv.cycle_rows(document)
    assert len(pools) == 3 and len(decisions) == sum(len(p['journal']) for p in document['pools']) == 226
    assert all(row['label'] == 'HISTORICAL_REPLAY' for row in pools + decisions)
    assert cycles == []
    s = rv.summary(document, verification)
    assert (s['entries'], s['closed_cycles'], s['pnl_sol_by_arm']) == (0, 0, None)
    assert s['counted_in_master_gate'] is False and s['sol_usd_verified'] is False
    row = decisions[0]
    assert (row['action'], row['sol_usd'], row['sol_usd_source']) == (
        'WAIT', None, 'refusé : sol_usd_rate_unavailable')
    assert row['transaction'] == f"https://solscan.io/tx/{row['signature']}"
    assert set(rv.EMPTY_SECTIONS) == {'PROSPECTIVE_PAPER', 'REAL'}


def test_declared_rate_and_synthetic_series_are_labelled_synthetic():
    declared = hrr.run_replay(FIXTURES, hrr.ReplayParams(sol_usd=150, sol_usd_provenance='ASSUMED_DECLARED'))
    label, reasons = rv.bundle_labels(declared)
    assert label == 'HISTORICAL_REPLAY · SYNTHETIC' and 'ASSUMED_DECLARED' in reasons[0]
    rows = rv.decision_rows(declared)
    assert all(row['label'] == label for row in rows + rv.pool_rows(declared))
    priced = [row for row in rows if row['sol_usd'] is not None]
    assert priced and all(row['sol_usd'] == 150 and 'déclaré' in row['sol_usd_source'] for row in priced)

    points = []
    for path in sorted(FIXTURES.glob('*.json.gz')):
        archive = json.loads(gzip.decompress(path.read_bytes()))
        points += [(tx['slot'], tx.get('transactionIndex') or 0, tx['blockTime'])
                   for tx in archive['transactions'].values()]
    def series(label):
        return sus.series_from_document(dict(schema=sus.SERIES_SCHEMA, label=label, points=[
            dict(schema=sus.POINT_SCHEMA, slot=s, transaction_index=i, block_time=None, received_at_ms=None,
                 publish_time=t - 1, price=150_00000000, exponent=-8, confidence=None,
                 source_kind='pyth_onchain_account', source_ref='SYNTHETIC-REF',
                 evidence_sha256=hashlib.sha256(f'{s}:{i}'.encode()).hexdigest(), signature=None)
            for s, i, t in sorted(set(points))]))
    synthetic = hrr.run_replay(FIXTURES, hrr.ReplayParams(), series('SYNTHETIC_TEST_FIXTURE'))
    label, reasons = rv.bundle_labels(synthetic)
    assert label == 'HISTORICAL_REPLAY · SYNTHETIC' and 'SYNTHETIC_TEST_FIXTURE' in reasons[0]
    used = [row for row in rv.decision_rows(synthetic) if row['sol_usd'] is not None]
    assert used and all(row['sol_usd'] == 150.0 and row['sol_usd_source'].startswith('pyth_onchain_account')
                        and row['sol_usd_age_ms'] == 1_400 for row in used)
    # The journaled point carries its exact mantissa and exponent.
    point = next(r['sol_usd_point'] for p in synthetic['pools'] for r in p['journal'] if 'sol_usd_point' in r)
    assert (point['price'], point['exponent']) == (150_00000000, -8)
    # A COLLECTED series alone does not make the bundle synthetic.
    collected = hrr.run_replay(FIXTURES, hrr.ReplayParams(), series('COLLECTED'))
    assert rv.bundle_labels(collected) == ('HISTORICAL_REPLAY', [])


def test_cycle_rows_convert_lamports_exactly_and_keep_open_cycles_apart(committed):
    (document, _v), _r = committed
    edited = copy.deepcopy(document)
    master = edited['pools'][0]['arms']['master']
    master.update(outcome='closed', spent=100_000_000, received=112_345_678, tx_costs=210_000,
                  failed_attempt_costs=0, pnl_lamports=12_135_678, entry_slot=10, exit_slot=90,
                  entry_block_time=1_793_658_226, exit_block_time=1_793_658_256,
                  entry_signature=edited['pools'][0]['journal'][0]['signature'], exit_signature='bad',
                  exit_trigger='take_profit')
    reference = edited['pools'][1]['arms']['reference']
    reference.update(outcome='open_at_window_end', spent=100_000_000, received=0, tx_costs=105_000,
                     pnl_lamports=None, mark_pnl_lamports=-5_000_000)
    rows = rv.cycle_rows(edited)
    assert len(rows) == 2 and all(row['label'] == 'HISTORICAL_REPLAY' for row in rows)
    closed = next(row for row in rows if row['outcome'] == 'closed')
    assert (closed['buy_sol'], closed['sell_sol'], closed['fees_sol'], closed['pnl_sol']) == (
        0.1, 0.112345678, 0.00021, 0.012135678)
    assert closed['entry_transaction'].startswith('https://solscan.io/tx/') and closed['exit_transaction'] is None
    opened = next(row for row in rows if row['outcome'] == 'open_at_window_end')
    assert (opened['pnl_sol'], opened['sell_sol'], opened['mark_pnl_sol']) == (None, None, -0.005)
    s = rv.summary(edited, {})
    assert s['closed_cycles'] == 1 and s['pnl_sol_by_arm'] == {'MASTER (recherche)': 0.012135678}


@pytest.mark.parametrize('value', [
    None, 42, '', 'short', '1' * 31, '1' * 33, '0OIl' * 10,
    'abc)](javascript:alert(1))', MINT_LIKE + '/../x', 'z' * 44,
])
def test_links_are_built_only_from_valid_addresses(value):
    links = rv.external_links(value, value)
    assert all(url is None for url in links.values())
    assert rv.transaction_link(value) is None


def test_link_formats(committed):
    (document, _v), _r = committed
    pool = document['pools'][0]
    links = rv.external_links(pool['mint'], pool['pool'])
    assert links == dict(
        axiom=f"https://axiom.trade/t/{pool['mint']}",
        solscan_token=f"https://solscan.io/token/{pool['mint']}",
        raydium=f"https://raydium.io/launchpad/token/?mint={pool['mint']}",
        solscan_pool=f"https://solscan.io/account/{pool['pool']}",
        dexscreener=f"https://dexscreener.com/solana/{pool['pool']}")
    assert rv.is_solana_address(MINT_LIKE) and not rv.is_solana_signature(MINT_LIKE)


def test_research_view_imports_nothing_that_reaches_the_network():
    tree = ast.parse((ROOT / 'bot' / 'dashboard' / 'research_view.py').read_text())
    imported = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {'__future__', 'collections', 'datetime', 'fractions', 'hashlib', 'json', 'pathlib'}


def test_research_tab_renders_with_the_committed_bundle():
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / 'bot' / 'dashboard' / 'app.py'), default_timeout=60).run()
    assert list(app.exception) == [] and list(app.error) == []
    assert 'Recherche et rejeux historiques' in [tab.label for tab in app.tabs]
    assert any('fa86f314f015277fc7a84f0124e5a04c4beaef00ab7caec05f91e3d255985270' in s.value
               and 'VERIFIED_AGAINST_RESULTS_REGISTRY' in s.value for s in app.success)
    texts = [i.value for i in app.info]
    assert any('HISTORICAL_REPLAY' in t for t in texts)
    assert rv.EMPTY_SECTIONS['REAL'] in texts and rv.EMPTY_SECTIONS['PROSPECTIVE_PAPER'] in texts
    assert any("le P&L en SOL reste vide" in t for t in texts)


def test_committed_bundle_is_reproduced_by_the_replay(committed):
    (document, _v), _r = committed
    assert hrr.run_replay(FIXTURES)['bundle_sha256'] == document['bundle_sha256']
