#!/bin/sh
# Opt-in Render build command for the existing READ-ONLY service:
# sh scripts/render_readonly_build.sh
# Does not deploy, read secrets, access Solana, or authorize LIVE trades.
set -eu
export RUGGER_NO_DOTENV=1
export RUGGER_LIVE_ENABLED=0
python -m pip install --disable-pip-version-check -r requirements-render.txt
python -B -m bot.ops.render_dependency_preflight
python -m compileall -q render_status_service.py bot/ops/render_readonly_service.py bot/ops/render_dependency_preflight.py
