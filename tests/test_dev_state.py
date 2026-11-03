"""Decision rules of the autonomous development planner (pure logic, no network)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'dev_state.py'
BACKLOG = ROOT / 'docs' / 'autonomy' / 'BACKLOG.json'


def _load_tool():
    spec = importlib.util.spec_from_file_location('dev_state', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ds = _load_tool()


def item(item_id, rank, paths, **overrides):
    base = {'id': item_id, 'rank': rank, 'title': item_id, 'target_paths': list(paths),
            'offline': True, 'requires_owner': False, 'acceptance': ['x']}
    base.update(overrides)
    return base


def pr(number, state='OPEN'):
    return {'number': number, 'state': state, 'isDraft': True,
            'url': f'https://example.invalid/pull/{number}'}


def branch(name, files=(), ids=(), pull=None, corrections=(), rounds=0):
    return {'name': name, 'head': 'a' * 40, 'changed_files': list(files),
            'backlog_ids': list(ids), 'pr': pull, 'rounds': rounds,
            'corrections': list(corrections), 'ci': None}


def test_path_overlap_respects_directory_boundaries():
    assert ds.paths_overlap('bot/market', 'bot/market/timing.py')
    assert ds.paths_overlap('tests/', 'tests/test_x.py')
    assert not ds.paths_overlap('bot/marketing', 'bot/market')
    assert not ds.paths_overlap('docs/a.md', 'bot/market')


def test_start_takes_the_lowest_rank_eligible_item():
    items = [item('b', 2, ['docs/b.md']), item('a', 1, ['docs/a.md'])]
    decision = ds.plan([], items)
    assert decision['action'] == 'START' and decision['item'] == 'a'


def test_open_work_locks_its_files_and_the_next_item_proceeds():
    items = [item('a', 1, ['bot/market/timing.py']), item('b', 2, ['docs/b.md'])]
    branches = [branch('claude/dev-x', files=['bot/market/replay.py'], ids=['old'], pull=pr(7))]
    decision = ds.plan(branches, items)
    assert decision['action'] == 'START' and decision['item'] == 'a'
    branches = [branch('claude/dev-x', files=['bot/market/timing.py'], pull=pr(7))]
    decision = ds.plan(branches, items)
    assert decision['item'] == 'b'
    assert any('overlaps open work' in r for r in decision['reasons'])


def test_claimed_item_is_not_started_twice():
    items = [item('a', 1, ['docs/a.md']), item('b', 2, ['docs/b.md'])]
    branches = [branch('claude/dev-a', files=['docs/a.md'], ids=['a'], pull=pr(3))]
    assert ds.plan(branches, items)['item'] == 'b'


def test_a_closed_unmerged_pull_request_releases_its_claim():
    items = [item('a', 1, ['docs/a.md'])]
    branches = [branch('claude/dev-a', files=['docs/a.md'], ids=['a'], pull=pr(3, 'CLOSED'))]
    decision = ds.plan(branches, items)
    assert decision['action'] == 'START' and decision['item'] == 'a'


def test_owner_gated_and_online_items_are_never_started():
    items = [item('gated', 1, ['docs/g.md'], requires_owner=True),
             item('online', 2, ['docs/o.md'], offline=False)]
    decision = ds.plan([], items)
    assert decision['action'] == 'STOP'
    assert any('owner' in r for r in decision['reasons'])
    assert any('not offline' in r for r in decision['reasons'])


def test_corrections_are_resumed_before_any_new_work():
    items = [item('a', 1, ['docs/a.md'])]
    branches = [branch('claude/dev-fix', files=['docs/f.md'], ids=['f'], pull=pr(12),
                       corrections=[{'reason': 'owner_request', 'excerpt': '/fix tests'}],
                       rounds=1)]
    decision = ds.plan(branches, items, resume_corrections=True)
    assert decision['action'] == 'RESUME' and decision['branch'] == 'claude/dev-fix'
    assert decision['pr'] == 12 and decision['backlog_ids'] == ['f']


def test_exhausted_rounds_stop_automatic_corrections_and_new_work_continues():
    items = [item('a', 1, ['docs/a.md'])]
    branches = [branch('claude/dev-fix', files=['docs/f.md'], pull=pr(12),
                       corrections=[{'reason': 'owner_request', 'excerpt': '/fix'}],
                       rounds=ds.MAX_ROUNDS)]
    decision = ds.plan(branches, items)
    assert decision['action'] == 'START' and decision['item'] == 'a'
    assert any('needs owner decision' in r for r in decision['reasons'])


def test_lowest_pull_request_number_is_resumed_first():
    branches = [branch('claude/dev-b', pull=pr(9), corrections=[{'reason': 'ci_failed'}], rounds=1),
                branch('claude/dev-a', pull=pr(7), corrections=[{'reason': 'ci_failed'}], rounds=1)]
    assert ds.plan(branches, [], resume_corrections=True)['pr'] == 7


def test_stop_explains_every_blocked_item():
    decision = ds.plan([], [item('a', 1, ['docs/a.md'], requires_owner=True)])
    assert decision == {'action': 'STOP', 'locked_paths': [],
                        'reasons': ['a: gated on an owner decision']}


def test_only_comments_after_the_last_agent_reply_are_requests():
    comments = [
        {'createdAt': '2026-11-03T01:00:00Z', 'body': '/fix old request'},
        {'createdAt': '2026-11-03T01:05:00Z', 'body': '[dev-agent] round 1: addressed it'},
    ]
    rounds, requests = ds.corrections_since_last_agent(comments)
    assert rounds == 1 and requests == []
    comments.append({'createdAt': '2026-11-03T02:00:00Z', 'body': '/fix the new bug'})
    rounds, requests = ds.corrections_since_last_agent(comments)
    assert rounds == 1 and [r['reason'] for r in requests] == ['owner_request']


def test_reviewer_verdict_and_plain_comments_are_told_apart():
    comments = [
        {'createdAt': '2026-11-03T01:00:00Z',
         'body': '[automated review] head=abc verdict: CHANGES_REQUESTED on bot/x.py'},
        {'createdAt': '2026-11-03T01:01:00Z', 'body': 'looks good to me'},
    ]
    _, requests = ds.corrections_since_last_agent(comments)
    assert [r['reason'] for r in requests] == ['review_changes_requested']


def test_failed_check_needs_a_fix_only_on_an_unaddressed_head():
    head = 'b' * 40
    addressed = [{'body': f'[dev-agent] round 1: fixed, head={head}'}]
    assert ds.ci_needs_fix(head, 'FAILURE', []) is True
    assert ds.ci_needs_fix(head, 'FAILURE', addressed) is False
    assert ds.ci_needs_fix(head, 'SUCCESS', []) is False


def test_backlog_trailers_are_read_from_commit_messages():
    messages = ('feat: measure slots\n\nBody text.\n\nBacklog: slot-timing-v1\n'
                'Co-Authored-By: Claude <noreply@anthropic.com>\n')
    assert ds.TRAILER.findall(messages) == ['slot-timing-v1']


def test_out_of_scope_detects_files_outside_the_item_and_its_run_record():
    spec_item = item('a', 1, ['bot/market/timing.py', 'tests/test_t.py'])
    changed = ['bot/market/timing.py', 'tests/test_t.py', 'docs/autonomy/runs/x.md',
               'bot/market/replay.py', 'bot/marketing.py']
    assert ds.out_of_scope(changed, spec_item) == ['bot/market/replay.py', 'bot/marketing.py']


def test_repository_backlog_is_valid_and_ranked():
    coord, items = ds.load_backlog(BACKLOG)
    assert coord.startswith('claude/')
    assert [i['rank'] for i in items] == sorted(i['rank'] for i in items)
    assert any(i['offline'] and not i['requires_owner'] for i in items)


def test_scope_checks_the_callers_repository_not_the_tool_checkout(tmp_path, monkeypatch):
    """The routine runs the protocol checkout's tool from a dev branch working tree."""
    import subprocess

    repo = tmp_path / 'work'
    repo.mkdir()

    def git(*args):
        return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t.invalid', *args],
                              cwd=repo, check=True, capture_output=True, text=True)

    git('init', '-q', '-b', 'base')
    git('commit', '-q', '--allow-empty', '-m', 'base')
    git('checkout', '-q', '-b', 'dev')
    (repo / 'bot').mkdir()
    (repo / 'bot' / 'timing.py').write_text('x = 1\n', encoding='utf-8')
    (repo / 'elsewhere.txt').write_text('y\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', 'work')
    backlog = tmp_path / 'backlog.json'
    backlog.write_text(json.dumps({'coordination_branch': 'base',
                                   'items': [item('x', 1, ['bot/timing.py'])]}), encoding='utf-8')
    monkeypatch.chdir(repo)
    assert ds.main(['scope', 'x', '--base', 'base', '--backlog', str(backlog)]) == 3
    git('rm', '-q', 'elsewhere.txt')
    git('commit', '-q', '-m', 'drop out-of-scope file')
    assert ds.main(['scope', 'x', '--base', 'base', '--backlog', str(backlog)]) == 0


def test_owner_switches_fail_closed_for_start_and_resume():
    items = [item('a', 1, ['docs/a.md'])]
    assert ds.plan([], items, start_new_work=False)['action'] == 'STOP'
    branches = [branch('claude/dev-fix', files=['docs/f.md'], ids=['f'], pull=pr(12),
                       corrections=[{'reason': 'owner_request', 'excerpt': '/fix'}], rounds=1)]
    assert ds.plan(branches, items, start_new_work=False)['action'] == 'STOP'
    decision = ds.plan(branches, items, start_new_work=False, resume_corrections=True)
    assert decision['action'] == 'RESUME' and decision['pr'] == 12
    decision = ds.plan(branches, items, start_new_work=True, resume_corrections=False)
    assert decision['action'] == 'START' and decision['item'] == 'a'


def test_missing_or_false_switch_fails_closed(tmp_path):
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps({'coordination_branch': 'claude/x', 'items': []}), encoding='utf-8')
    assert ds.load_policy(path) == {'start_new_work': False, 'resume_corrections': False}
    path.write_text(json.dumps({'start_new_work': 'yes', 'resume_corrections': 'yes'}), encoding='utf-8')
    assert ds.load_policy(path) == {'start_new_work': False, 'resume_corrections': False}
    # The repository's current owner authorization can change independently of this test.
    # Exercise fail-closed behavior on the temporary policy fixture instead.
    path.write_text(json.dumps({'start_new_work': False, 'resume_corrections': True}), encoding='utf-8')
    assert ds.load_policy(path) == {'start_new_work': False, 'resume_corrections': True}


def test_git_event_wakeup_is_always_stopped(tmp_path, capsys):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'branches': []}), encoding='utf-8')
    assert ds.main(['plan', str(state), '--run-origin', 'event']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['action'] == 'STOP'
    assert 'GitHub event' in result['reasons'][0]
    assert ds.main(['plan', str(state)]) == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'STOP'


def test_scheduled_run_cannot_resume_even_when_owner_corrections_gate_is_true(tmp_path, capsys):
    backlog = tmp_path / 'backlog.json'
    backlog.write_text(json.dumps({'coordination_branch': 'claude/launchlab-trade-events',
                                   'start_new_work': False, 'resume_corrections': True,
                                   'items': []}), encoding='utf-8')
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'branches': [
        branch('claude/dev-fix', pull=pr(12),
               corrections=[{'reason': 'owner_request', 'excerpt': '/fix'}])
    ]}), encoding='utf-8')
    assert ds.main(['plan', str(state), '--backlog', str(backlog),
                    '--run-origin', 'scheduled']) == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'STOP'
    assert ds.main(['plan', str(state), '--backlog', str(backlog),
                    '--run-origin', 'manual']) == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'RESUME'


def test_duplicate_or_incomplete_backlog_is_rejected(tmp_path):
    duplicate = {'coordination_branch': 'claude/x', 'items': [
        item('same', 1, ['a']), item('same', 2, ['b'])]}
    path = tmp_path / 'dup.json'
    path.write_text(json.dumps(duplicate), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate'):
        ds.load_backlog(path)
    incomplete = {'coordination_branch': 'claude/x', 'items': [{'id': 'x', 'rank': 1}]}
    path.write_text(json.dumps(incomplete), encoding='utf-8')
    with pytest.raises(ValueError, match='lacks'):
        ds.load_backlog(path)
