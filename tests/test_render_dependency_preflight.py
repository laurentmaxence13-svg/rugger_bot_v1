"""Offline Render build-contract tests. No sockets, RPC, or financial orders."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.ops import render_dependency_preflight as preflight


def test_verifier_checked_before_importing_signed_pipeline():
    calls = []

    def verifier():
        calls.append("ed25519")
        return object()

    def loader(name):
        calls.append(name)
        return SimpleNamespace(run_pipeline=lambda **kwargs: None)

    assert preflight.verify_readonly_source(
        load_module=loader, verify_signature=verifier) is True
    assert calls == ["ed25519", preflight.SOURCE_MODULE]


def test_missing_crypto_fails_before_importing_pipeline():
    called = []

    def reject():
        raise ModuleNotFoundError("fake_missing_crypto")

    with pytest.raises(ModuleNotFoundError):
        preflight.verify_readonly_source(
            load_module=lambda name: called.append(name),
            verify_signature=reject)
    assert called == []


@pytest.mark.parametrize("pipeline", [None, 0, "NOT_MASTER"])
def test_missing_or_invalid_master_source_fails_closed(pipeline):
    with pytest.raises(RuntimeError, match="missing_readonly_signed_source_pipeline"):
        preflight.verify_readonly_source(
            load_module=lambda name: SimpleNamespace(run_pipeline=pipeline),
            verify_signature=lambda: object())


def test_main_does_not_log_private_exception_details(monkeypatch, capsys):
    marker = "HELIUS_API_KEY=synthetic_do_not_print"
    def reject():
        raise RuntimeError(marker)
    monkeypatch.setattr(preflight, "verify_readonly_source", reject)
    assert preflight.main() == 1
    printed = capsys.readouterr().out
    assert "READONLY_RENDER_BUILD_PREFLIGHT_REFUSED:RuntimeError" in printed
    assert marker not in printed


def test_real_source_import_only_no_capture():
    # All packages are present in isolated CI; this import is read-only.
    assert preflight.verify_readonly_source() is True


def test_build_script_installs_before_crypto_preflight():
    root = Path(__file__).resolve().parents[1]
    lines = (root / "scripts/render_readonly_build.sh").read_text().splitlines()
    commands = [line.strip() for line in lines
                if line.strip().startswith("python ")]
    assert commands == [
        "python -m pip install --disable-pip-version-check -r requirements-render.txt",
        "python -B -m bot.ops.render_dependency_preflight",
        "python -m compileall -q render_status_service.py bot/ops/render_readonly_service.py bot/ops/render_dependency_preflight.py",
    ]
    assert "export RUGGER_LIVE_ENABLED=0" in lines
    assert "export RUGGER_NO_DOTENV=1" in lines
    assert "-r requirements-live.txt" in (
        root / "requirements-render.txt").read_text()
