"""Offline guarantees: public PAPER result only, no secrets, no implicit GO."""
import json
from pathlib import Path
import pytest
from bot.p3.readonly_evidence_archive import (
    build_archive,archive_from_github_actions)

VALID=dict(schema="rugger-test-observation",status="PREDECLARED_S1_CAPACITY_SAMPLE_RECORDED",
           financial_order_submitted=False,live_ready_to_arm=False,
           observations=[dict(pool="public-pool",S1_slot=12345,
                              S2_conditional_sell_lamports=None,
                              refused=True)])
SHA="a"*40


def packet(value=None, **overrides):
    return build_archive(value if value is not None else VALID,
        kind=overrides.pop("kind","s1_capacity_s2"),
        run_id=overrides.pop("run_id","12345"),
        commit_sha=overrides.pop("commit_sha",SHA),
        now_iso=overrides.pop("now_iso","2026-10-30T17:00:00+00:00"),
        **overrides)


def test_archive_preserves_denominator_and_unknown_exits():
    got=packet()
    assert got["schema"]=="rugger-paper-observation-archive-v1"
    assert got["observation"]["observations"][0]["S2_conditional_sell_lamports"] is None
    assert len(got["observation_sha256"])==64
    assert got["independent_creator_holdout_validated"] is False
    assert got["economic_edge_validated"] is False
    assert got["financial_order_submitted"] is False
    assert got["live_ready_to_arm"] is False


def test_hash_is_content_based_and_stable():
    a=packet()
    b=packet(now_iso="2026-10-31T01:00:00+00:00")
    assert a["observation_sha256"]==b["observation_sha256"]


@pytest.mark.parametrize("sensitive",[
    dict(HELIUS_API_KEY="key"),
    dict(private_key="secret"),
    dict(nested=dict(authorization="secret")),
    dict(error="https://mainnet.helius-rpc.com/?api-key=secret"),
    dict(message="Bearer very-secret"),
])
def test_secret_detection_refuses_persisting_any_credentials(sensitive):
    evidence=dict(VALID,**sensitive)
    with pytest.raises(ValueError,match="secret|forbidden"):
        packet(evidence)


@pytest.mark.parametrize("changes",[
    dict(financial_order_submitted=True),
    dict(live_ready_to_arm=True),
    dict(financial_order_submitted=None),
])
def test_no_financial_authorization_allowed(changes):
    with pytest.raises(ValueError,match="read_only"):
        packet(dict(VALID,**changes))


@pytest.mark.parametrize("kwargs",[
    dict(kind="signed_orders"),
    dict(run_id="../../escape"),
    dict(commit_sha="invalid"),
    dict(now_iso="2026-10-30"),
])
def test_invalid_archive_metadata_rejected(kwargs):
    with pytest.raises(ValueError):
        packet(**kwargs)


def test_not_in_github_actions_does_not_write(monkeypatch,tmp_path):
    monkeypatch.delenv("RUGGER_WRITE_PUBLIC_EVIDENCE",raising=False)
    monkeypatch.setenv("GITHUB_WORKSPACE",str(tmp_path))
    assert archive_from_github_actions(VALID,kind="s1_capacity_s2") is None
    assert list(tmp_path.iterdir())==[]


def test_opted_in_gha_writes_only_public_json_with_consistent_sha(monkeypatch,tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS","true")
    monkeypatch.setenv("GITHUB_WORKSPACE",str(tmp_path))
    monkeypatch.setenv("GITHUB_RUN_ID","100200300")
    monkeypatch.setenv("GITHUB_SHA",SHA)
    monkeypatch.setenv("RUGGER_WRITE_PUBLIC_EVIDENCE","1")
    result=archive_from_github_actions(VALID,kind="s1_capacity_s2")
    obj=json.loads((tmp_path/result["path"]).read_text())
    assert result["observation_sha256"]==obj["observation_sha256"]
    assert obj["observation"]["status"]==VALID["status"]
    assert obj["economic_edge_validated"] is False
