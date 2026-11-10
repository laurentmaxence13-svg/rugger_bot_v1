"""Control (f): the harness never signs, never sends, never reaches LIVE_ENABLED."""
import ast
import asyncio
import importlib
from pathlib import Path
import socket
import subprocess
import sys

import pytest

import bot
import dryrun
from bot.live.wire import PreparedTransaction
from dryrun import DryRunHarness, FixtureRpc, Refusal, verify_journal
from dryrun.cycle import StepClock, run_fixture_cycle
from dryrun.fixtures import cpmm_fixture_request

run = asyncio.run

# Every way the frozen tree signs, sends, opens a live journal or gains
# financial authority. (module, class or None, attribute)
TRIPWIRES = (
    ('bot.live.signer', 'UnixDomainSigner', '__init__'),
    ('bot.live.signer', 'UnixDomainSigner', 'sign_message'),
    ('bot.live.rpc', 'SolanaRpc', 'send_transaction'),
    ('bot.live.rpc', 'HttpJsonRpcTransport', '__init__'),
    ('bot.live.rpc', 'HttpJsonRpcTransport', '__call__'),
    ('bot.live.engine', 'ExecutionEngine', '__init__'),
    ('bot.live.engine', 'ExecutionEngine', 'execute'),
    ('bot.live.engine', 'ExecutionEngine', 'recover'),
    ('bot.live.submission', 'BoundSubmissionGuard', '__call__'),
    ('bot.live.runtime', 'LiveRuntime', '__init__'),
    ('bot.live.journal', 'ExecutionJournal', '__init__'),
    ('bot.live.safety', 'AuthorizationEnvelope', '__init__'),
    ('bot.live.safety', 'ArmingState', '__init__'),  # the only carrier of LIVE_ARMED/LIVE_ENABLED
    ('bot.live.safety', None, 'arm'),
    ('bot.live.safety', None, 'enable'),
    ('bot.live.safety', None, 'arming_from_record'),
    # bot/live/route.py imports bot/p3/quotes.py, which imports aiohttp: the HTTP
    # client library is loaded by the frozen builder, so it must stay unused.
    ('aiohttp', 'ClientSession', '__init__'),
)
FORBIDDEN_MODULES = tuple(sorted(
    {module for module, _, _ in TRIPWIRES if module.startswith('bot.live.')}))
ALLOWED_FROZEN_IMPORTS = {
    ('bot',), ('bot.live.cpmm_exit', 'build_cpmm_exit'),
    ('bot.live.route', 'SYSTEM_PROGRAM'), ('bot.live.route', 'TOKEN_PROGRAM'),
    ('bot.live.route', 'associated_token_address'), ('bot.live.route', 'build_launchlab_order'),
    ('bot.live.route', 'ephemeral_wsol_address'),
    ('bot.live.unsigned_preflight', 'check_unsigned_order'),
    ('bot.market.launchlab_curve', 'CurveError'), ('bot.market.launchlab_curve', 'CurveState'),
    ('bot.market.launchlab_curve', 'buy_exact_in'), ('bot.market.launchlab_curve', 'sell_exact_in'),
    ('bot.p3', 'launchlab'), ('bot.p3.certification', '_decode'),
    ('bot.p3.certification', '_encode'),
}


class Tripwire(AssertionError):
    pass


def _trip(name):
    def tripped(*args, **kwargs):
        raise Tripwire(name)
    return tripped


@pytest.fixture
def tripwires(monkeypatch):
    armed = []
    for module_name, owner, attribute in TRIPWIRES:
        module = importlib.import_module(module_name)
        target = getattr(module, owner) if owner else module
        monkeypatch.setattr(target, attribute, _trip(f'{module_name}:{owner}.{attribute}'))
        armed.append(getattr(target, attribute))
    assemble = PreparedTransaction.transaction

    def unsigned_only(self, signatures):
        # Putting any non-zero signature into a wire is the last step of signing.
        if any(signature != bytes(64) for signature in signatures):
            raise Tripwire('signed_wire_assembled')
        return assemble(self, signatures)
    monkeypatch.setattr(PreparedTransaction, 'transaction', unsigned_only)
    monkeypatch.setattr(socket.socket, 'connect', _trip('socket.connect'))
    monkeypatch.setattr(socket, 'create_connection', _trip('socket.create_connection'))
    return armed


def test_full_cycle_and_every_other_operation_trip_no_signer_or_send(tmp_path, tripwires):
    path = tmp_path / 'tripwired.jsonl'
    # Clock near 1100 ms: the frozen CPMM fixture bank was observed at 1000 ms.
    harness, bought, sold = run_fixture_cycle(path, clock_ms=StepClock(start=1100))
    assert sold['position_closed'] is True  # reached only if nothing tripped
    run(harness.buy('dry-run-buy-2', 50_000_000))
    with pytest.raises(Refusal, match='duplicate_decision_id'):
        run(harness.buy('dry-run-buy-2', 50_000_000))
    run(harness.cpmm_exit_probe(cpmm_fixture_request()))
    harness.emergency_stop('end of rehearsal')
    with pytest.raises(Refusal, match='emergency_stop_active'):
        run(harness.sell('dry-run-sell-2'))
    records = verify_journal(path)
    assert all(r['signed'] is False and r['submitted'] is False and r['funds_used'] is False
               and r['dry_run'] is True and r['master_operational_trade'] is False
               for r in records)
    # The tripwires are live: each patched entry point really raises when used.
    for patched in tripwires:
        with pytest.raises(Tripwire):
            patched()
    with pytest.raises(Tripwire, match='signed_wire_assembled'):
        PreparedTransaction(b'm', ('k',), ('k',), 'b', 1).transaction((b'\x01' * 64,))


def test_fixture_rpc_cannot_send_and_only_takes_unsigned_wires(open_harness):
    harness = open_harness()
    with pytest.raises(RuntimeError, match='dry_run_never_sends'):
        run(harness.rpc.send_transaction(b'\x01' + bytes(64) + b'message'))
    with pytest.raises(ValueError, match='only_unsigned_wire'):
        run(harness.rpc.simulate_transaction(b'\x01' + b'\x07' * 64 + b'message',
                                             sig_verify=False, min_context_slot=1))
    with pytest.raises(ValueError, match='only_unsigned_wire'):
        run(harness.rpc.simulate_transaction(b'\x01' + bytes(64) + b'message',
                                             sig_verify=True, min_context_slot=1))
    assert harness.rpc.simulated == []


def test_harness_accepts_no_rpc_but_the_offline_fixture(open_harness):
    class LooksLikeRpc:
        endpoint_sha256 = 'a' * 64
    with pytest.raises(ValueError, match='offline_fixture_rpc_required'):
        open_harness(rpc=LooksLikeRpc())
    assert isinstance(open_harness().rpc, FixtureRpc)
    assert not hasattr(DryRunHarness, 'mode') and not hasattr(open_harness(), 'signer')


def test_harness_sources_import_only_builders_preflight_and_curve_arithmetic():
    package = Path(dryrun.__file__).parent
    imported = set()
    for source in sorted(package.glob('*.py')):
        text = source.read_text()
        assert 'LIVE_ENABLED' not in text and 'LIVE_ARMED' not in text, source.name
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                imported |= {(alias.name,) for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported |= {(node.module, alias.name) for alias in node.names}
    frozen = {item for item in imported if item[0].split('.')[0] == 'bot'}
    assert frozen == ALLOWED_FROZEN_IMPORTS


def test_a_cycle_in_a_fresh_interpreter_never_loads_signing_or_sending_modules(tmp_path):
    script = (
        'import asyncio, sys\n'
        'from dryrun.cycle import StepClock, run_fixture_cycle\n'
        'from dryrun.fixtures import cpmm_fixture_request\n'
        'harness, bought, sold = run_fixture_cycle(sys.argv[1], clock_ms=StepClock(start=1100))\n'
        'assert sold["position_closed"] is True\n'
        # No Ed25519 implementation is even loaded by the LaunchLab cycle.
        f'print([m for m in {FORBIDDEN_MODULES + ("cryptography",)!r} if m in sys.modules])\n'
        'asyncio.run(harness.cpmm_exit_probe(cpmm_fixture_request()))\n'
        f'print([m for m in {FORBIDDEN_MODULES!r} if m in sys.modules])\n')
    result = subprocess.run(
        [sys.executable, '-B', '-W', 'error', '-c', script, str(tmp_path / 'fresh.jsonl')],
        cwd=Path(bot.__file__).resolve().parents[1], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['[]', '[]']
    assert len(verify_journal(tmp_path / 'fresh.jsonl')) == 12
