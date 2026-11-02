"""Offline public-only Render post-deploy smoke contract."""
from io import BytesIO
import json

import pytest

from bot.ops import render_readiness_http_smoke as smoke
from bot.ops.render_master_readiness import assess_master_paper_readiness


def signed():
    return {
        "observer_status": "DISABLED_EXPLICITLY",
        "signed_evidence_fresh": False,
        "live_trading_enabled": False,
        "no_signing_or_order_submission": True,
        "last_summary": None,
    }


def test_known_readonly_paths_only_and_bounded_response():
    paths = []
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, limit):
            assert limit == smoke.MAX_BYTES + 1
            return b'{"financial_order_submitted":false}'
    def opener(req, *, timeout):
        assert req.get_method() == "GET"
        assert timeout == 30
        assert req.full_url == smoke.RENDER_ORIGIN + "/healthz"
        paths.append(req.full_url)
        return Response()
    assert smoke.fetch_public_json("/healthz", opener=opener) == {
        "financial_order_submitted": False}
    assert paths == [smoke.RENDER_ORIGIN + "/healthz"]
    with pytest.raises(ValueError, match="unapproved_readonly_smoke_path"):
        smoke.fetch_public_json("/api/wallet/execute", opener=opener)


def test_smoke_validates_only_genuine_master_source():
    source = signed()
    readiness = assess_master_paper_readiness(source)
    payloads = {
        "/healthz": {"status": "up", "financial_order_submitted": False},
        "/api/helius": source,
        "/api/master-readiness": readiness,
    }
    calls = []
    def fake_fetch(path):
        calls.append(path)
        return payloads[path]
    result = smoke.smoke_once(fetcher=fake_fetch)
    assert calls == list(smoke.PATHS)
    assert result["status"] == "POST_DEPLOY_READONLY_SMOKE_OK"
    assert result["master_paper_status"] == "NO_GO"
    assert result["next_blocker"] == "SIGNED_OBSERVER_DISABLED"
    assert result["financial_order_submitted"] is False


@pytest.mark.parametrize("tamper", [
    {"status": "READY"},
    {"master_buy_sell_paper_verified": True},
    {"master_net_pnl_sol": 7.0},
    {"master_reference_edge_sol": 9.0},
    {"financial_order_submitted": True},
    {"next_blocker": "PROFITABLE"},
    {"source": "DEXSCREENER_EXPERIMENT"},
    {"signed_evidence_fresh": True},
    {"experimental_dexscreener_excluded": False},
])
def test_false_success_and_cross_feed_claims_refused(tamper):
    source = signed()
    report = assess_master_paper_readiness(source)
    report.update(tamper)
    with pytest.raises(ValueError, match="inconsistent_master_readiness"):
        smoke.validate_readiness(
            {"financial_order_submitted": False}, source, report)


def test_reject_unsafe_signed_source_even_with_no_go_report():
    source = signed()
    report = assess_master_paper_readiness(source)
    source["live_trading_enabled"] = True
    with pytest.raises(ValueError, match="unsafe_signed_source"):
        smoke.validate_readiness(
            {"financial_order_submitted": False}, source, report)


def test_no_network_without_explicit_flag(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(smoke, "smoke_once",
                        lambda: calls.append("WOULD_FETCH_NETWORK"))
    assert smoke.main([]) == 2
    assert calls == []
    assert "EXPLICIT_NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_network_failure_is_redacted(monkeypatch, capsys):
    marker = "HELIUS_API_KEY=synthetic_do_not_echo"
    def fail():
        raise RuntimeError(marker)
    monkeypatch.setattr(smoke, "smoke_once", fail)
    assert smoke.main(["--network"]) == 2
    assert marker not in capsys.readouterr().out


def test_network_optin_is_explicit_and_reports_no_go(monkeypatch, capsys):
    source = signed()
    report = assess_master_paper_readiness(source)
    monkeypatch.setattr(smoke, "smoke_once",
        lambda: smoke.validate_readiness(
            {"financial_order_submitted": False}, source, report))
    assert smoke.main(["--network"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["next_blocker"] == "SIGNED_OBSERVER_DISABLED"
    assert output["master_buy_sell_paper_verified"] is False
