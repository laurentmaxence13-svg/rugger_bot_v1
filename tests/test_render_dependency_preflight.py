"""Offline Render build-contract tests. No sockets, RPC, or financial orders."""
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


def test_render_build_install_then_preflight_then_compile(monkeypatch):
    from bot.ops import render_readonly_build as build
    calls = []
    def fake_runner(args, *, check, env):
        assert check is True
        assert env["RUGGER_NO_DOTENV"] == "1"
        assert env["RUGGER_LIVE_ENABLED"] == "0"
        calls.append(args)
    assert build.run_build(runner=fake_runner) is True
    assert len(calls) == 3
    assert calls[0][1:] == [
        "-m", "pip", "install", "--disable-pip-version-check",
        "-r", "requirements-render.txt"]
    assert calls[1][1:] == [
        "-B", "-m", "bot.ops.render_dependency_preflight"]
    assert calls[2][1:3] == ["-m", "compileall"]


def test_render_build_failure_prevents_all_later_steps():
    import subprocess
    from bot.ops import render_readonly_build as build
    calls = []
    def fail_pip(args, *, check, env):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)
    with pytest.raises(subprocess.CalledProcessError):
        build.run_build(runner=fail_pip)
    assert len(calls) == 1


def test_render_build_main_refuses_without_printing_secrets(monkeypatch, capsys):
    from bot.ops import render_readonly_build as build
    marker = "API_KEY=synthetic_sensitive_value"
    def fail():
        raise RuntimeError(marker)
    monkeypatch.setattr(build, "run_build", fail)
    assert build.main() == 1
    out = capsys.readouterr().out
    assert "READONLY_RENDER_BUILD_REFUSED:RuntimeError" in out
    assert marker not in out
