"""Offline falsification tests for the bounded Helius prospective PAPER campaign."""
import json
from pathlib import Path
import pytest
from bot.live import helius_prospective_campaign as c


def root(tmp_path):
    path=tmp_path/"bot/live"
    path.mkdir(parents=True)
    (path/"helius_early_signed_s1s2.py").write_text("# fixture marker\n")
    return tmp_path


def factory(*,same_signature=False, same_creator=False,
            pretend_fills=False):
    n=[0]
    async def fake(*,seconds,max_events):
        assert seconds == 10 and max_events == 20
        n[0]+=1
        signature="public-sig"+("one" if same_signature else str(n[0]))
        creator="creator"+("one" if same_creator else str(n[0]))
        event={"signature":signature}
        launch=dict(creator=creator)
        attempt=dict(signature=signature,signed_outer_creations=[launch],
                     frozen_pre_S2=dict(master_action="WAIT"))
        report=dict(schema=c.CAPTURE_SCHEMA,
            financial_order_submitted=bool(pretend_fills),
            live_ready_to_arm=False,qualified_economic_cycles=0,
            master_net_pnl_lamports=None,
            reference_net_pnl_lamports=None,
            forward_log_report=dict(events_received_unique=1),
            selected=[dict(signature=signature)],
            attempts=[attempt])
        return report,[event]
    return fake


def test_multiple_windows_persist_unique_causal_artifacts(tmp_path):
    out=c.campaign(windows=3,seconds=10,max_events=20,
        capture=factory(),workspace=root(tmp_path),session="unit")
    assert out["windows_requested"]==3
    assert out["observed_events"]==3
    assert out["verified_signed_launch_candidates"]==3
    assert out["observed_distinct_creator_claims"]==3
    assert out["frozen_S1_decisions"]==3
    assert out["max_readonly_helius_requests"]==30
    assert out["independent_creator_economic_cycles"]==0
    assert out["master_net_pnl_lamports"] is None
    assert not out["financial_order_submitted"]
    folder=tmp_path/"paper_artifacts"
    assert len(list(folder.glob("prospective_unit_window_*.json")))==3
    assert (folder/"prospective_unit_summary.json").is_file()
    for path in folder.glob("prospective_unit_window_*.json"):
        assert json.loads(path.read_text())["report"]["financial_order_submitted"] is False


def test_same_creator_not_multiplied_across_windows(tmp_path):
    out=c.campaign(windows=2,seconds=10,max_events=20,
        capture=factory(same_creator=True),workspace=root(tmp_path))
    assert out["verified_signed_launch_candidates"]==2
    assert out["observed_distinct_creator_claims"]==1


def test_same_signature_not_mistaken_for_independent_evidence(tmp_path):
    out=c.campaign(windows=2,seconds=10,max_events=20,
        capture=factory(same_signature=True,same_creator=True),workspace=root(tmp_path))
    assert out["repeated_signatures_across_windows"]==1
    assert out["observed_distinct_creator_claims"]==1


@pytest.mark.parametrize("windows,seconds,max_events",[
    (0,10,20),(7,10,20),(1,9,20),(1,61,20),(1,10,201),
    (1,10,0),(True,10,20),(1,10.0,20)])
def test_budget_refused_before_capture(tmp_path,windows,seconds,max_events):
    with pytest.raises(ValueError,match="explicit_multi_window_budget_required"):
        c.campaign(windows=windows,seconds=seconds,max_events=max_events,
            capture=factory(),workspace=root(tmp_path))


def test_paid_or_filled_claim_refused_without_artifact(tmp_path):
    home=root(tmp_path)
    with pytest.raises(ValueError,match="unqualified_capture_refused"):
        c.campaign(windows=1,seconds=10,max_events=20,
            capture=factory(pretend_fills=True),workspace=home)
    assert not list((home/"paper_artifacts").glob("*.json"))


def test_existing_evidence_cannot_be_overwritten(tmp_path):
    home=root(tmp_path)
    c.campaign(windows=1,seconds=10,max_events=20,
        capture=factory(),workspace=home,session="same")
    with pytest.raises(FileExistsError):
        c.campaign(windows=1,seconds=10,max_events=20,
            capture=factory(),workspace=home,session="same")


def test_missing_runtime_secret_refuses(monkeypatch,capsys):
    monkeypatch.delenv("HELIUS_API_KEY",raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS","true")
    monkeypatch.setenv("GITHUB_WORKSPACE","/tmp")
    assert c.main(["--windows","1"])==2
    assert "financial_order_submitted" in capsys.readouterr().out


def test_no_live_ready_flag_from_fake_market_data(tmp_path):
    out=c.campaign(windows=1,seconds=10,max_events=20,
        capture=factory(),workspace=root(tmp_path))
    assert out["market_profitability_verified"] is False
    assert out["live_ready_to_arm"] is False


def test_credential_not_written_to_artefacts(tmp_path,monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY","this_is_only_a_unit_test_secret")
    home=root(tmp_path)
    c.campaign(windows=1,seconds=10,max_events=20,
        capture=factory(),workspace=home)
    for path in (home/"paper_artifacts").glob("*.json"):
        assert "this_is_only_a_unit_test_secret" not in path.read_text()
