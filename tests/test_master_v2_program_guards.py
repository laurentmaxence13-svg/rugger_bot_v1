"""Run-safety guards enforced on direct programmatic calls, not only by the CLI (R02 O5, O7).

The CLI refuses an explicit zero latency or a short explicit L1 horizon (R02 O3). The same
safety floors now live in the harness itself, so preregister, run_policy, run_policy_pool and
evaluate refuse an unsafe run whatever the entry point.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from bot.market.collector import summarize  # noqa: F401  (import order as in the other harness tests)
from bot.market.launchlab_events import WSOL_MINT
from bot.master_v2 import harness as h
from bot.master_v2 import policies as pol
from bot.master_v2 import registry
from bot.p4 import historical_research_replay as hrr

PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'
RULE = h.ExitRule(max_hold_s=25)
PROTOCOL = hrr.ReplayParams(latency_slots=4, exit_horizon_ms=25_000)       # the P0 protocol
UNSAFE = ((hrr.ReplayParams(latency_slots=0), 'replay_latency_slots_below_1'),
          (hrr.ReplayParams(exit_horizon_ms=0), 'replay_exit_horizon_below_minimum'),
          (hrr.ReplayParams(exit_horizon_ms=999), 'replay_exit_horizon_below_minimum'))


def _cli():
    spec = importlib.util.spec_from_file_location('mv2r', Path(__file__).parents[1] / 'tools' / 'master_v2_research.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_safety_floors_are_explicit():
    assert (h.MIN_LATENCY_SLOTS, h.MIN_EXIT_HORIZON_MS) == (1, 1_000)
    h.validate_run_params(PROTOCOL)
    h.validate_run_params(hrr.ReplayParams())                       # L1 defaults stay accepted
    h.validate_run_params(hrr.ReplayParams(latency_slots=1, exit_horizon_ms=1_000))   # boundaries
    for params, error in UNSAFE:
        with pytest.raises(ValueError, match=error):
            h.validate_run_params(params)


@pytest.mark.parametrize('params, error', UNSAFE)
def test_direct_calls_refuse_unsafe_parameters(params, error):
    with pytest.raises(ValueError, match=error):
        h.preregister(PACK, pol.ImmediateSnipe(), RULE, params)
    with pytest.raises(ValueError, match=error):
        h.run_policy(PACK, pol.ImmediateSnipe(), RULE, params)
    archive = next(archive for _, archive in hrr.load_fixtures(PACK)[2])
    with pytest.raises(ValueError, match=error):
        h.run_policy_pool(archive, pol.ImmediateSnipe(), RULE, params, quote_mint=WSOL_MINT)


def test_rule_without_max_hold_is_guarded_too_r02_o5():
    """O5: a stop-loss-only rule with an L1 horizon of 0 used to be accepted and registered."""
    with pytest.raises(ValueError, match='replay_exit_horizon_below_minimum'):
        h.run_policy(PACK, pol.ImmediateSnipe(), h.ExitRule(stop_loss=0.1), hrr.ReplayParams(exit_horizon_ms=0))


def test_guarded_protocol_run_is_unchanged():
    doc = h.run_policy(PACK, pol.ImmediateSnipe(), RULE, PROTOCOL)
    assert doc['params']['latency_slots'] == 4 and doc['params']['exit_horizon_ms'] == 25_000
    assert doc['preregistration_sha256'] == h.preregister(PACK, pol.ImmediateSnipe(), RULE, PROTOCOL)[
        'preregistration_sha256']


def test_evaluate_refuses_a_bundle_with_unsafe_parameters(tmp_path, capsys):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    out = tmp_path / 'snipe.json'
    cli.main(['run', '--fixtures', str(PACK), '--registry', str(reg), '--policy', 'immediate-snipe',
              '--exit', 'max_hold_s=25', '--replay', 'latency_slots=4', '--replay', 'exit_horizon_ms=25000',
              '--out', str(out), '--at', '2026-11-08T00:00:00+00:00'])
    capsys.readouterr()
    doc = json.loads(out.read_text('utf-8'))
    entries = registry.load(reg)
    assert cli.evaluate([doc], registry_entries=entries, n_boot=200)['trials'] == 1
    tampered = dict(doc, params=dict(doc['params'], latency_slots=0))
    with pytest.raises(ValueError, match='replay_latency_slots_below_1'):
        cli.evaluate([tampered], registry_entries=entries, n_boot=200)
    with pytest.raises(ValueError, match='replay_latency_slots_below_1'):
        cli.required_embargo_slots([tampered])


def test_cli_refuses_before_registration_through_the_library(tmp_path, capsys):
    cli = _cli()
    reg = tmp_path / 'trials.jsonl'
    for replay in (['--replay', 'exit_horizon_ms=500'],                       # library floor
                   ['--replay', 'latency_slots=0']):
        with pytest.raises(SystemExit):
            cli.main(['run', '--fixtures', str(PACK), '--registry', str(reg), '--policy', 'immediate-snipe',
                      '--exit', 'stop_loss=0.1', *replay, '--out', str(tmp_path / 'x.json')])
        assert 'replay_' in capsys.readouterr().err
    assert not reg.exists()
