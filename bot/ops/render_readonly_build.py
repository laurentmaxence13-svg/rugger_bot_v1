"""Explicit, fail-closed Render build entrypoint for the read-only observer.

Run only as the *build command* on the already existing service:
    python -B -m bot.ops.render_readonly_build

The helper changes no Render setting, never deploys, and does not call a market
provider or sign transactions. It installs the declared public dependencies
before importing the real signed Helius source for build-time verification.
"""
from __future__ import annotations

import os
import subprocess
import sys


def run_build(*, runner=None):
    if runner is None:
        runner = subprocess.run
    env = os.environ.copy()
    env["RUGGER_NO_DOTENV"] = "1"
    env["RUGGER_LIVE_ENABLED"] = "0"
    commands = (
        [sys.executable, "-m", "pip", "install",
         "--disable-pip-version-check", "-r", "requirements-render.txt"],
        [sys.executable, "-B", "-m", "bot.ops.render_dependency_preflight"],
        [sys.executable, "-m", "compileall", "-q",
         "render_status_service.py", "bot/ops/render_readonly_service.py",
         "bot/ops/render_dependency_preflight.py",
         "bot/ops/render_readonly_build.py"],
    )
    for command in commands:
        runner(command, check=True, env=env)
    return True


def main():
    try:
        run_build()
    except Exception as error:
        # Do not print exception messages which may include environment data.
        print("READONLY_RENDER_BUILD_REFUSED:" + type(error).__name__)
        return 1
    print("READONLY_RENDER_BUILD_OK:NO_FINANCIAL_OPERATIONS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
