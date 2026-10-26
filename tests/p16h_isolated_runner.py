"""Offline harness; use in a disposable source copy, never the worktree."""
import os
import sys
import socket
import threading
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if (root / ".git").exists():
    raise SystemExit("P1.6h: run only from a source copy without Git metadata")
os.chdir(root)
sys.path.insert(0, str(root))
sys.dont_write_bytecode = True
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
# No dotenv file is opened, including through config imports.
dotenv = types.ModuleType('dotenv')
dotenv.load_dotenv = lambda *args, **kwargs: False
sys.modules['dotenv'] = dotenv
local = threading.local()
original_pair = socket.socketpair

def local_pair(*args, **kwargs):
    previous = getattr(local, 'pair', False)
    local.pair = True
    try:
        return original_pair(*args, **kwargs)
    finally:
        local.pair = previous

socket.socketpair = local_pair

def guard(event, args):
    if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.gethostbyname'):
        if not getattr(local, 'pair', False):
            raise AssertionError('P1.6h: external networking prohibited: ' + event)
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0]))
        if path.name == '.env' or path.name.startswith('.env.'):
            raise AssertionError('P1.6h: dotenv read prohibited')
        if path.suffix in ('.db', '.sqlite', '.sqlite3') and not path.resolve().is_relative_to(root.parent):
            # tempfile databases from existing tests are also synthetic.
            import tempfile
            if not path.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError('P1.6h: database outside synthetic environment')

sys.addaudithook(guard)
if sys.argv[1:] == ['--compare']:
    import hashlib
    import json
    import tempfile
    sys.path.insert(0, str(root / 'tests'))
    from test_paper_report_cleanup import synthetic_session
    results = {}
    with tempfile.TemporaryDirectory(prefix='p16h_normal_') as directory:
        for mode in ('empty', 'tp', 'sl', 'reject', 'guard_blocked', 'undated'):
            results[mode] = synthetic_session(Path(directory) / mode, mode)
    artifact = root / 'normal_scenarios.json'
    artifact.write_text(json.dumps(results, indent=2, sort_keys=True), encoding='utf-8')
    print('SHA256', hashlib.sha256(artifact.read_bytes()).hexdigest())
    raise SystemExit(0)

import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
