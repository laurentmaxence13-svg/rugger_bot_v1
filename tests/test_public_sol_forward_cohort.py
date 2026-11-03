"""Synthetic no-network verification of finite public signed cohort."""
import json

import pytest

from bot.live import public_sol_forward_cohort as cohort


def fake_source(*, creators=("one","two"), duplicate=False, forged=False):
    calls=[]
    def capture(*,seconds,output_dir):
        index=len(calls)
        assert seconds==75
        output_dir.mkdir(parents=True,exist_ok=False)
        signature="repeat" if duplicate else "public-source-"+str(index)
        (output_dir/"public_log_capture.json").write_text(json.dumps({
            "events":[{"signature":signature}]}))
        creator=creators[index] if index<len(creators) else "one"
        (output_dir/"paired_master_source_shadow.json").write_text(json.dumps({
            "selected":[{"creator":creator}],
            "observations":[{"creator":creator,"graph":None}]}))
        result={
            "schema":"rugger-public-solana-forward-signed-paper-v1",
            "source":"FREE_PUBLIC_SOLANA_MAINNET_NOT_HELIUS",
            "financial_order_submitted":False,
            "live_trading_enabled":False,
            "genuine_master_paper_buys":1 if forged else 0,
            "genuine_master_paper_sells":0,
            "master_net_pnl_lamports":None,
            "log_events":1,
            "signed_creation_transactions":1,
            "frozen_master_S1_decisions":0,
            "verification_rpc_calls":2,
            "bank_rpc_calls":1,
        }
        calls.append(result)
        return result
    return calls,capture


def test_two_windows_preserve_independent_creator_denominator_without_trades(tmp_path):
    calls,capture=fake_source(creators=("same-creator","same-creator"))
    root=tmp_path/"public-cohort"
    out=cohort.collect_public_cohort(
        directory=root,window_count=2,seconds=75,capture=capture)
    assert len(calls)==2
    assert out["window_count"]==2
    assert out["observed_unique_events"]==2
    assert out["uniquely_selected_signed_creators"]==1
    assert out["native_SOL_source_creators"]==0
    assert out["total_rpc_calls"]==6
    assert out["absolute_rpc_call_cap"]==30
    assert out["master_paper_buys"]==0
    assert out["master_paper_sells"]==0
    assert out["master_net_pnl_lamports"] is None
    assert out["financial_order_submitted"] is False
    assert json.loads((root/"campaign_summary.json").read_text())==out


def test_duplicate_transaction_across_windows_not_counted_as_new_candidate(tmp_path):
    _,capture=fake_source(duplicate=True)
    with pytest.raises(ValueError,match="replayed_or_invalid_cross_window_signature"):
        cohort.collect_public_cohort(
            directory=tmp_path/"duplicate",window_count=2,
            seconds=75,capture=capture)
    assert not (tmp_path/"duplicate"/"campaign_summary.json").exists()


@pytest.mark.parametrize("windows,seconds",[(0,75),(5,75),(4,90),
                                            (3,150),(-1,30),(1,29)])
def test_unbounded_public_sampling_refused_without_running_network(
        tmp_path,windows,seconds):
    calls=[]
    with pytest.raises(ValueError,match="fixed_free_public_observation_budget"):
        cohort.collect_public_cohort(directory=tmp_path/"blocked",
            window_count=windows,seconds=seconds,
            capture=lambda **kwargs:calls.append("NETWORK"))
    assert not calls


def test_false_financial_activity_in_provider_report_never_promotes(tmp_path):
    _,capture=fake_source(forged=True)
    with pytest.raises(ValueError,match="unqualified_or_financial_public_window"):
        cohort.collect_public_cohort(directory=tmp_path/"fake",
            window_count=1,seconds=75,capture=capture)
    assert not (tmp_path/"fake"/"campaign_summary.json").exists()


def test_campaign_cannot_reuse_original_artifact_folder(tmp_path):
    root=tmp_path/"already-exists"
    root.mkdir()
    _,capture=fake_source()
    with pytest.raises(ValueError,match="new_free_public_campaign_directory"):
        cohort.collect_public_cohort(
            directory=root,window_count=1,seconds=75,capture=capture)


def test_default_cli_requires_explicit_network_optin(monkeypatch,capsys,tmp_path):
    calls=[]
    monkeypatch.setattr(cohort,"collect_public_cohort",
                        lambda **kw:calls.append("NETWORK"))
    assert cohort.main(["--output-dir",str(tmp_path/"not-created")])==2
    assert calls==[]
    assert "EXPLICIT_NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out
