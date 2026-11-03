"""No-network tests: local Helius launcher never submits an order."""
import json
import os
from pathlib import Path
import pytest

from bot.live import helius_early_local as mod


async def fake_capture(*,seconds,max_events):
    assert seconds==10
    assert max_events==20
    return (dict(schema=mod.SCHEMA,
        selected=[{"signature":"public-id"}],
        attempts=[dict(status="CONFIRMED_RECEIPT_NOT_YET_AVAILABLE")],
        forward_log_report=dict(events_received_unique=1),
        qualified_economic_cycles=0,
        financial_order_submitted=False,live_ready_to_arm=False,
        master_net_pnl_lamports=None),[{"signature":"public-id"}])


def root_dir(tmp_path):
    path=tmp_path/"bot/live"
    path.mkdir(parents=True)
    (path/"helius_early_signed_s1s2.py").write_text("# public stub\n")
    return tmp_path


def test_local_capture_writes_unique_public_evidence_without_credentials(tmp_path,monkeypatch,capsys):
    root=root_dir(tmp_path)
    monkeypatch.setenv("HELIUS_API_KEY","local-test-not-a-real-secret")
    monkeypatch.delenv("GITHUB_ACTIONS",raising=False)
    first=mod.local_capture(seconds=10,max_events=20,root=root,capture=fake_capture)
    second=mod.local_capture(seconds=10,max_events=20,root=root,capture=fake_capture)
    assert first!=second
    assert first.is_file() and second.is_file()
    evidence=json.loads(first.read_text())
    assert evidence["report"]["selected"][0]["signature"]=="public-id"
    assert evidence["financial_order_submitted"] is False
    assert evidence["master_net_pnl_lamports"] is None
    assert "local-test-not-a-real-secret" not in first.read_text()
    assert "local-test-not-a-real-secret" not in capsys.readouterr().out
    assert first.parent==root/"paper_artifacts"


def test_missing_api_key_refused_without_calling_capture(tmp_path,monkeypatch):
    root=root_dir(tmp_path)
    monkeypatch.delenv("HELIUS_API_KEY",raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS",raising=False)
    with pytest.raises(ValueError,match="HELIUS_API_KEY_not_set"):
        mod.local_capture(seconds=10,root=root)


def test_unapproved_economic_report_cannot_be_persisted(tmp_path,monkeypatch):
    root=root_dir(tmp_path)
    monkeypatch.setenv("HELIUS_API_KEY","fake-unit-only")
    monkeypatch.delenv("GITHUB_ACTIONS",raising=False)
    async def unqualified(*,seconds,max_events):
        report,_=await fake_capture(seconds=10,max_events=20)
        report["financial_order_submitted"]=True
        return report,[]
    with pytest.raises(ValueError,match="not_an_unqualified_readonly"):
        mod.local_capture(seconds=10,max_events=20,root=root,capture=unqualified)
    assert not (root/"paper_artifacts").exists()


@pytest.mark.parametrize("seconds,max_events",[(0,20),(61,20),(10,101),(10,0)])
def test_invalid_bounds_never_capture(tmp_path,monkeypatch,seconds,max_events):
    monkeypatch.setenv("HELIUS_API_KEY","fake-unit-only")
    with pytest.raises(ValueError):
        mod.local_capture(seconds=seconds,max_events=max_events,root=root_dir(tmp_path))


def test_github_actions_runner_refused(tmp_path,monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS","true")
    monkeypatch.setenv("HELIUS_API_KEY","fake-unit-only")
    with pytest.raises(ValueError,match="local_capture_only"):
        mod.local_capture(seconds=10,root=root_dir(tmp_path))
