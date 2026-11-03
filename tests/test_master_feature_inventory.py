"""Offline tests for the Master feature inventory audit (no Master is executed)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('master_feature_inventory', ROOT / 'tools' / 'master_feature_inventory.py')
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

SIGNAL_FIELDS = (
    'mint creator signal_time observed_at prior_launches behavior_known relevant_transactions dev_sales '
    'relay_transfers bundle_transactions bundle_wallets liquidity_usd price_usd quote_count momentum_60s '
    'momentum_300s volume_5m_usd volume_24h_usd price_change_5m_pct price_change_1h_pct tx_buys_5m '
    'tx_sells_5m market_cap_usd fdv_usd fee_bps depth_usd slippage_bps_est market_data_quality holder_count '
    'top_holder_share holder_data_known linked_wallets wallet_link_count same_slot_wallets '
    'wallet_graph_transactions quote_source funding_usd').split()


def test_inventory_covers_every_signal_feature_exactly():
    assert sorted(inv.INVENTORY) == sorted(SIGNAL_FIELDS)


def test_every_entry_has_a_valid_class():
    valid = {inv.EVENTS, inv.TX, inv.EXTRA, inv.UNKNOWN}
    assert {c for c, _, _ in inv.INVENTORY.values()} <= valid


def test_zero_defaults_are_never_classified_as_derivable_from_events():
    for name in inv.ZERO_DEFAULTS:
        assert inv.INVENTORY[name][0] in (inv.EXTRA, inv.UNKNOWN), name


def test_usd_fields_are_not_claimed_from_events():
    for name in ('price_usd', 'liquidity_usd', 'market_cap_usd', 'fdv_usd', 'funding_usd', 'depth_usd'):
        assert inv.INVENTORY[name][0] != inv.EVENTS, name


def test_class_counts_after_depth_usd_reclassification():
    assert inv.classify_counts() == {inv.EVENTS: 13, inv.TX: 5, inv.EXTRA: 16, inv.UNKNOWN: 3}
    assert inv.INVENTORY['depth_usd'][0] == inv.EXTRA


def test_fixture_spans_and_computable_signal_features():
    report = inv.audit(ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools')
    assert sorted(m['span_seconds'] for m in report.values()) == [16, 29, 31]
    for pool, m in report.items():
        status = m['signal_features']
        for name in ('momentum_60s', 'momentum_300s', 'price_change_5m_pct', 'price_change_1h_pct'):
            assert status[name] == inv.UNAVAILABLE, (pool, name)
        assert status['tx_buys_5m'] == status['tx_sells_5m'] == inv.PARTIAL, pool
        computable = sorted(n for n, s in status.items() if s == inv.COMPUTABLE)
        assert computable == ['bundle_transactions', 'bundle_wallets', 'fee_bps', 'observed_at',
                              'same_slot_wallets', 'signal_time', 'slippage_bps_est'], pool


def test_window_status_is_complete_for_a_long_pool():
    assert set(inv.computable_on_span(3600).values()) == {inv.COMPUTABLE}
    assert inv.computable_on_span(None)['momentum_60s'] == inv.UNAVAILABLE


def test_fixture_pools_are_too_short_for_momentum_windows():
    report = inv.audit(ROOT / 'tests' / 'fixtures' / 'launchlab_sol_pools')
    assert len(report) == 3
    for pool, m in report.items():
        assert m['missing_block_time'] == 0, pool
        assert m['windows_computable'] == {'60': False, '300': False}, pool
        assert m['buys'] + m['sells'] == m['events'], pool


def test_audit_never_runs_a_master():
    assert inv.main.__module__ == 'master_feature_inventory'
    text = (ROOT / 'tools' / 'master_feature_inventory.py').read_text(encoding='utf-8')
    for banned in ('MasterDecisionOrchestrator', 'import requests', 'urllib', 'socket'):
        assert banned not in text.replace("'MasterDecisionOrchestrator'", '')
