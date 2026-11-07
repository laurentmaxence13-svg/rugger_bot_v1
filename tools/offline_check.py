#!/usr/bin/env python3
"""Run the repository's offline harness on a fresh, disposable source copy."""
from pathlib import Path, PurePosixPath
import os
import shutil
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
if not (repo / "tests/p16h_isolated_runner.py").is_file():
    raise SystemExit("Offline harness missing; inspect the repository before continuing.")
files = subprocess.check_output(
    ["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
).split(b"\0")
with tempfile.TemporaryDirectory(prefix="rugger-cloud-check-", dir="/tmp") as directory:
    root = Path(directory)
    copied = 0
    for item in sorted(set(files)):
        if not item:
            continue
        relative = PurePosixPath(os.fsdecode(item))
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("Unsafe source path")
        # Workflow definitions and root requirements*.txt are copied as plain data for
        # the trigger guard test; they hold secret names only, never secret values,
        # and are never executed.
        workflow_file = (relative.parts[:2] == (".github", "workflows") and len(relative.parts) == 3
                         and relative.suffix in (".yml", ".yaml")) \
            or (len(relative.parts) == 1 and relative.name.startswith("requirements") and relative.suffix == ".txt")
        if relative.parts[0] not in ("bot", "tests") and not workflow_file:
            # Explicit audit-only allowlist; do not import arbitrary tools, secrets or config.
            if relative.as_posix() not in ("tools/bitquery_dextrades_markout.py", "tools/bitquery_dextrades_pages.py", "tools/bitquery_dextrades_replay.py", "tools/bitquery_cross_protocol_audit.py", "tools/master_prospective_gate.py",
                                           "render_status_service.py",
                                           # Offline tools exercised by PR #90/#91/#98 tests.
                                           "tools/launchlab_baseline_report.py", "tools/master_feature_inventory.py",
                                           "tools/dev_state.py", "docs/autonomy/BACKLOG.json",
                                           # Offline GitHub Actions trigger guard (P-PRIV correction).
                                           "tools/workflow_trigger_guard.py",
                                           # Offline L1 replay CLI exercised by the P0 fix tests.
                                           "tools/historical_research_replay.py"):
                continue
        if relative.parts[:2] in (("bot", "bot"), ("tests", "tests")):
            continue
        # Compressed archives are accepted only as committed test fixtures.
        gz_fixture = relative.parts[:2] == ("tests", "fixtures") and relative.suffixes[-2:] == [".json", ".gz"]
        if relative.suffix not in (".py", ".json") and not gz_fixture and not workflow_file:
            continue
        source = repo / relative
        if not source.resolve().is_relative_to(repo) or source.is_symlink():
            raise SystemExit("Source symlinks require inspection: " + str(relative))
        if not source.is_file():
            continue
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied += 1
    print(f"Offline validation: {copied} source/fixture files copied; no .env, Git metadata or user database.", flush=True)
    args = sys.argv[1:] or ["-q", "tests", "--ignore=tests/tests", "-p", "no:cacheprovider", "-rs"]
    child_env = os.environ.copy()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # Runtime credentials are unnecessary for synthetic tests.
    for name in ("HELIUS_API_KEY", "BIRDEYE_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
        child_env.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-B", "tests/p16h_isolated_runner.py", *args],
        cwd=root, env=child_env,
    )
    raise SystemExit(result.returncode)
