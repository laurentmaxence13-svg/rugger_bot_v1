"""Offline prospective S1/S2 sidecar controls, no real orders or providers."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock
import pytest

from bot.live import public_sol_forward_quote_research as mod

MINT="ChWZ8yNvMh31yHtkZh3fSjWZaQiv62bHr1WPnUPLvuLF"
POOL="EBA8nnnHuFRMHd3Ac9HMMCNTi52E3GXT7HDreXwvhnCu"
SOL="So11111111111111111111111111111111111111112"


def fake_pair(*,forged=False):
    row=dict(signature="synthetic-public-verified-signature",
        mint=MINT,pool=POOL,
        s1_bank_preserved_before_S2=True,s2_received_ms=1700000003000,
        frozen_decision_before_S2=dict(master_action="WAIT",
            at_ms=1700000001000,future_S2_used=False,real_order=False),
        s1_independent_research_buy_quote=dict(
            input_mint=SOL,output_mint=MINT,
            input_atomic="50000000",output_atomic="1000",
            provider_route_pool=POOL,actual_fill=False,
            hypothetical_lot_was_never_executed=True,
            provider_produced_at_ms=None,provider_source_slot=None,
            received_at_utc_ms=1700000002000),
        s2_independent_research_sell_quote=dict(
            input_mint=MINT,output_mint=SOL,
            input_atomic="1000",output_atomic="49000000",
            provider_route_pool="another-pool" if forged else POOL,
            actual_fill=False,provider_produced_at_ms=None,
            provider_source_slot=None,received_at_utc_ms=1700000003200),
        source_produced_quote_clocks_verified=False,
        research_quote_pair_is_not_an_actual_Master_PAPER_cycle=True,
        research_only_quote_delta_before_extra_costs_lamports="-1000000")
    return row


def source(*,rows):
    invoked=[]
    def fake_original_strategy(*args,**kwargs):
        invoked.append(kwargs.get("include_readonly_quotes"))
        return {}
    def fake_capture(*,seconds,output_dir,strategy):
        # The network-capture strategy is an explicit dependency only:
        # upstream signed creation and signature proof are separately tested.
        assert seconds==30
        assert strategy("captured","verified","read-only-rpc")=={}
        assert invoked==[True]
    def fake_collector(*,directory,window_count,seconds,capture):
        assert window_count==1 and seconds==30
        directory.mkdir(parents=True)
        for i in range(window_count):
            folder=directory/f"window_{i:02d}"
            folder.mkdir()
            capture(seconds=seconds,output_dir=folder)
            (folder/"paired_master_source_shadow.json").write_text(
                json.dumps(dict(observations=rows,financial_order_submitted=False,
                    execution_verified=False),sort_keys=True))
        return dict(schema="rugger-free-public-signed-cohort-v1",
            observed_unique_events=1,uniquely_selected_signed_creators=1,
            native_SOL_source_creators=1,
            financial_order_submitted=False,
            master_paper_buys=0,master_paper_sells=0,master_net_pnl_lamports=None)
    return invoked,fake_original_strategy,fake_collector,fake_capture


def test_one_independent_s1s2_quote_pair_never_creates_master_paper_pnl(
        monkeypatch,tmp_path):
    row=fake_pair()
    calls,scorer,collector,capture=source(rows=[row])
    monkeypatch.setattr(mod,"signed_creator_asof_paper",scorer)
    out=mod.run(directory=tmp_path/"cohort",window_count=1,seconds=30,
                collector=collector,capture=capture)
    assert calls==[True]
    assert out["independent_quote_S1_cases"]==1
    assert out["two_clock_quote_only_pairs"]==1
    assert out["incomplete_quote_pairs"]==0
    assert out["complete_causal_Master_economic_cycles"]==0
    assert out["actual_Master_PAPER_buys"]==0
    assert out["actual_Master_PAPER_sells"]==0
    assert out["net_Master_PAPER_pnl_lamports"] is None
    assert out["financial_order_submitted"] is False
    assert json.loads((tmp_path/"cohort"/"quote_sidecar_summary.json").read_text())==out


def test_wrong_pool_in_s2_quote_is_refused_not_counted(monkeypatch,tmp_path):
    _,scorer,collector,capture=source(rows=[fake_pair(forged=True)])
    monkeypatch.setattr(mod,"signed_creator_asof_paper",scorer)
    with pytest.raises(ValueError,match="unqualified_signed_S2_sell_quote_provenance"):
        mod.run(directory=tmp_path/"wrong-pool",window_count=1,
                seconds=30,collector=collector,capture=capture)
    assert not (tmp_path/"wrong-pool"/"quote_sidecar_summary.json").exists()


def test_uncharged_or_unowned_quote_cannot_become_master_trade(monkeypatch,tmp_path):
    row=fake_pair()
    row["frozen_decision_before_S2"]["master_action"]="ENTER"
    _,scorer,collector,capture=source(rows=[row])
    monkeypatch.setattr(mod,"signed_creator_asof_paper",scorer)
    with pytest.raises(ValueError,match="research_quote_was_not_after_actual_Master_wait"):
        mod.run(directory=tmp_path/"fake-master",window_count=1,seconds=30,
                collector=collector,capture=capture)


def test_quote_pair_without_full_sell_stays_censored(monkeypatch,tmp_path):
    row=fake_pair()
    row.pop("s2_independent_research_sell_quote")
    _,scorer,collector,capture=source(rows=[row])
    monkeypatch.setattr(mod,"signed_creator_asof_paper",scorer)
    out=mod.run(directory=tmp_path/"unpriced",window_count=1,seconds=30,
                collector=collector,capture=capture)
    assert out["incomplete_quote_pairs"]==1
    assert out["two_clock_quote_only_pairs"]==0
    assert out["net_Master_PAPER_pnl_lamports"] is None


@pytest.mark.parametrize("windows,seconds",[(0,75),(4,75),(3,90),(1,20)])
def test_bounded_sampling_rejects_before_any_network(tmp_path,windows,seconds):
    fake=Mock(side_effect=AssertionError("NETWORK_FORBIDDEN"))
    with pytest.raises(ValueError,match="bounded_signed_public_quote_cohort_required"):
        mod.run(directory=tmp_path/"invalid",window_count=windows,seconds=seconds,
                collector=fake,capture=fake)
    fake.assert_not_called()


def test_network_is_never_implicit(monkeypatch,tmp_path,capsys):
    fake=Mock(side_effect=AssertionError("NETWORK_FORBIDDEN"))
    monkeypatch.setattr(mod,"run",fake)
    assert mod.main(["--output-dir",str(tmp_path/"never-created")])==2
    fake.assert_not_called()
    assert "NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out
