"""MASTER V2 research CLI: runs are pre-registered; the holdout stays sealed unless unsealed."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(__file__).parent / 'fixtures' / 'launchlab_sol_pools'


def _cli():
    spec = importlib.util.spec_from_file_location('mv2_cli', ROOT / 'tools' / 'master_v2_research.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def _run(cli, tmp_path, name, *extra):
    out = tmp_path / f'{name}.json'
    cli.main(['run', '--fixtures', str(PACK), '--policy', name, '--exit', 'stop_loss=0.3',
              '--exit', 'max_hold_s=60', '--out', str(out), *extra])
    return out


def test_run_writes_a_preregistered_bundle(tmp_path, capsys):
    cli = _cli()
    out = _run(cli, tmp_path, 'immediate-snipe', '--param', 'max_age_s=3', '--param', 'max_early_slot_payers=none')
    doc = json.loads(out.read_text('utf-8'))
    printed = json.loads(capsys.readouterr().out)
    assert doc['policy_params']['max_age_s'] == 3 and doc['exit_rule']['max_hold_s'] == 60
    assert printed['preregistration_sha256'] == doc['preregistration_sha256']
    assert printed['bundle_sha256'] == doc['bundle_sha256']


def test_evaluate_keeps_the_holdout_sealed(tmp_path, capsys):
    cli = _cli()
    paths = [_run(cli, tmp_path, 'immediate-snipe'), _run(cli, tmp_path, 'placebo-no-trade')]
    capsys.readouterr()
    docs = [json.loads(p.read_text('utf-8')) for p in paths]
    result = cli.evaluate(docs, n_boot=200)
    assert sum(result['split'].values()) == 3 and result['trials'] == 2
    assert all('holdout' not in run['segments'] for run in result['runs'])
    sealed = cli.evaluate(docs, holdout=True, n_boot=200)
    assert all(run['segments']['holdout'] == 'sealed' for run in sealed['runs'])
    chosen = docs[0]['preregistration_sha256']
    opened = cli.evaluate(docs, holdout=True, unseal=[chosen], n_boot=200)
    by_sha = {run['preregistration_sha256']: run for run in opened['runs']}
    assert isinstance(by_sha[chosen]['segments']['holdout'], dict)
    assert by_sha[docs[1]['preregistration_sha256']]['segments']['holdout'] == 'sealed'
    with pytest.raises(SystemExit):
        cli.main(['evaluate', str(paths[0]), '--unseal', chosen])


def test_runs_on_different_fixtures_are_not_mixed(tmp_path, capsys):
    cli = _cli()
    doc = json.loads(_run(cli, tmp_path, 'immediate-snipe').read_text('utf-8'))
    other = json.loads(json.dumps(doc))
    other['fixtures']['manifest_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='runs_on_different_fixtures'):
        cli.evaluate([doc, other])


@pytest.mark.parametrize('argv', [['--param', 'nonsense'], ['--param', 'unknown_field=1']])
def test_invalid_parameters_are_refused(tmp_path, argv):
    cli = _cli()
    with pytest.raises(SystemExit):
        cli.main(['run', '--fixtures', str(PACK), '--policy', 'immediate-snipe', '--out',
                  str(tmp_path / 'x.json'), *argv])


def test_lifecycle_command_writes_every_pool(tmp_path, capsys):
    cli = _cli()
    out = tmp_path / 'life.json'
    cli.main(['lifecycle', '--fixtures', str(PACK), '--out', str(out)])
    doc = json.loads(out.read_text('utf-8'))
    assert doc['schema'] == 'rugger-master-v2-lifecycle-v1' and len(doc['pools']) == 3
    assert json.loads(capsys.readouterr().out) == dict(pools=3, excluded=0)
