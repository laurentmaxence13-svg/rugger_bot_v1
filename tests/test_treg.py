"""Offline tests for T-REG (no network, no GitHub call, no trigger)."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import treg  # noqa: E402

POLICY = json.loads((ROOT / 'docs' / 'treg' / 'agents.json').read_text(encoding='utf-8'))
ACTIVE = dict(copy.deepcopy(POLICY), paused=False)
AUTH = {'channel': 'owner_chat', 'quote_sha256': hashlib.sha256(b'ok').hexdigest(), 'scope': 'test'}


def task(task_id='T-0002', kind='implement', assignee='R01', reviewer='R02', deps=(), branch='claude/r01-t0002'):
    t = {'task_id': task_id, 'kind': kind, 'title': 't', 'assignee': assignee, 'depends_on': list(deps), 'authorization': AUTH}
    if kind == 'implement':
        t.update(reviewer=reviewer, branch=branch)
    return t


class Log:
    def __init__(self, policy=ACTIVE, start='2026-11-04T08:00:00'):
        self.policy, self.state, self.minute = policy, treg.empty_state(), 0
        self.base = start

    def utc(self):
        self.minute += 1
        h, m = divmod(self.minute, 60)
        return '2026-11-04T%02d:%02d:00Z' % (8 + h, m)

    def emit(self, task_id, agent, type, payload, utc=None):
        event = treg.make_event(self.state, task_id=task_id, from_agent=agent, type=type, utc=utc or self.utc(), payload=payload)
        self.state, applied = treg.apply_event(self.state, event, self.policy)
        return event, applied

    def create(self, t):
        return self.emit(t['task_id'], 'OWNER', 'create', {'task': t})


def submit_payload(commit='b' * 40, branch='claude/r01-t0002'):
    return {'status_to': 'submitted', 'commit': commit, 'branch': branch, 'input_sha256': 'c' * 64,
            'tests': {'passed': 3, 'failed': 0}}


# ---------------------------------------------------------------- scenario (requirement 7)
def test_full_scenario_r03_to_r01_to_r02_to_r04_inbox():
    state, ops = treg.simulate_scenario(POLICY)
    assert {k: v['status'] for k, v in state['tasks'].items()} == {'T-0001': 'done', 'T-0002': 'done', 'T-0003': 'done'}
    assert len(state['inbox']) == 1 and state['inbox'][0]['audit_verdict'] == 'PASS'
    assert state['tasks']['T-0002']['evidence']['audit']['audited_commit'] == 'b' * 40
    wakes = [o for o in ops if o['tool'].endswith('send_message')]
    assert [json.loads(w['message'])['treg_pointer']['task_id'] for w in wakes] == ['T-0001', 'T-0002', 'T-0002']
    assert all(set(json.loads(w['message'])) == {'treg_pointer'} for w in wakes)  # pointers only
    assert ops[-1]['issue'] == POLICY['r04']['inbox_title']
    assert POLICY['paused'] is True  # simulation never unpauses the shipped policy


def test_full_scenario_replays_identically_from_github_comments():
    state, _ = treg.simulate_scenario(POLICY)
    events = [e for tid in sorted(state['log']) for e in state['log'][tid]]
    bodies = [treg.render_comment(e) for e in events]
    replayed = treg.replay(treg.parse_comments(bodies), ACTIVE)
    assert replayed['tasks'] == state['tasks'] and replayed['inbox'] == state['inbox']


# ---------------------------------------------------------------- authorization and pause
def test_shipped_policy_is_paused_and_refuses_agent_events():
    log = Log(policy=POLICY)
    log.create(task())
    with pytest.raises(treg.TregError, match='registry_paused'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': 'claimed'})
    assert treg.next_action(log.state, POLICY, 'R01', '2026-11-04T09:00:00Z')['action'] == 'stop'


def test_any_agent_may_block_while_paused_but_not_unblock():
    log = Log(policy=POLICY)
    log.create(task())
    log.emit('T-0002', 'R02', 'transition', {'status_to': 'blocked', 'reason': 'anomaly'})
    with pytest.raises(treg.TregError, match='registry_paused'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': 'authorized'})


def test_task_creation_requires_owner_chat_authorization_and_owner_event():
    log = Log()
    bad = task(); bad['authorization'] = {'channel': 'github_label', 'quote_sha256': 'x', 'scope': 's'}
    with pytest.raises(treg.TregError, match='owner_chat_authorization_required'):
        log.create(bad)
    with pytest.raises(treg.TregError, match='create_must_be_first_owner_event'):
        log.emit('T-0002', 'R01', 'create', {'task': task()})


def test_only_owner_unblocks_or_cancels():
    log = Log()
    log.create(task())
    log.emit('T-0002', 'R01', 'transition', {'status_to': 'blocked', 'reason': 'x'})
    with pytest.raises(treg.TregError, match='transition_refused'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': 'authorized'})
    log.emit('T-0002', 'OWNER', 'transition', {'status_to': 'authorized'})
    assert log.state['tasks']['T-0002']['status'] == 'authorized'


# ---------------------------------------------------------------- roles and evidence
def test_assignee_cannot_audit_own_work_and_reviewer_must_differ():
    with pytest.raises(treg.TregError, match='independent_reviewer'):
        Log().create(task(reviewer='R01'))
    log = Log()
    log.create(task())
    for to in ('claimed', 'in_progress'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': to})
    log.emit('T-0002', 'R01', 'transition', submit_payload())
    with pytest.raises(treg.TregError, match='transition_refused'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': 'in_review'})


def test_done_requires_pass_audit_of_the_submitted_commit():
    log = Log()
    log.create(task())
    for to in ('claimed', 'in_progress'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': to})
    log.emit('T-0002', 'R01', 'transition', submit_payload())
    log.emit('T-0002', 'R02', 'transition', {'status_to': 'in_review'})
    with pytest.raises(treg.TregError, match='done_requires_pass_audit'):
        log.emit('T-0002', 'R02', 'transition', {'status_to': 'done', 'audit': {'verdict': 'PASS', 'audited_commit': 'd' * 40}})


def test_data_handoff_requires_digest_commit_rows_and_validation():
    log = Log()
    log.create(task('T-0001', 'data_handoff', 'R03'))
    for to in ('claimed', 'in_progress'):
        log.emit('T-0001', 'R03', 'transition', {'status_to': to})
    with pytest.raises(treg.TregError, match='data_handoff_requires'):
        log.emit('T-0001', 'R03', 'transition', {'status_to': 'submitted', 'dataset': {'sha256': 'e' * 64, 'commit': 'a' * 40, 'rows': 3},
                                                 'validation': {'status': 'FAIL'}})


def test_dependencies_must_be_done_before_claim():
    log = Log()
    log.create(task('T-0001', 'data_handoff', 'R03'))
    log.create(task(deps=['T-0001']))
    with pytest.raises(treg.TregError, match='dependencies_not_done'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': 'claimed'})
    assert treg.next_action(log.state, ACTIVE, 'R01', '2026-11-04T09:00:00Z') == {'action': 'wait', 'reason': 'nothing_actionable'}


# ---------------------------------------------------------------- loops (requirement 5)
def test_ping_pong_between_agents_hits_hop_limit():
    log = Log()
    log.create(task())
    for to in ('claimed', 'in_progress'):
        log.emit('T-0002', 'R01', 'transition', {'status_to': to})
    with pytest.raises(treg.TregError, match='hop_limit_exceeded'):
        for _ in range(10):
            log.emit('T-0002', 'R01', 'transition', submit_payload())
            log.emit('T-0002', 'R02', 'transition', {'status_to': 'in_review'})
            log.emit('T-0002', 'R02', 'transition', {'status_to': 'changes_requested', 'findings': ['f']})
            log.emit('T-0002', 'R01', 'transition', {'status_to': 'in_progress'})
    assert log.state['tasks']['T-0002']['status'] != 'done'


def test_forged_hop_counter_is_refused():
    log = Log()
    log.create(task())
    event = treg.make_event(log.state, task_id='T-0002', from_agent='R01', type='transition', utc=log.utc(), payload={'status_to': 'claimed'})
    event['hop'] = 0
    event['digest'] = treg.event_digest(event)
    with pytest.raises(treg.TregError, match='hop_counter_mismatch'):
        treg.apply_event(log.state, event, ACTIVE)


# ---------------------------------------------------------------- concurrency and idempotency
def test_duplicate_event_is_idempotent_and_conflicting_reuse_is_refused():
    log = Log()
    event, _ = log.create(task())
    same, applied = treg.apply_event(log.state, event, ACTIVE)
    assert applied is False and same == log.state
    forged = dict(event, utc='2026-11-04T23:00:00Z'); forged['digest'] = treg.event_digest(forged)
    with pytest.raises(treg.TregError, match='event_id_conflict'):
        treg.apply_event(log.state, forged, ACTIVE)


def test_two_writers_with_same_sequence_only_first_wins():
    log = Log()
    log.create(task())
    a = treg.make_event(log.state, task_id='T-0002', from_agent='R01', type='transition', utc=log.utc(), payload={'status_to': 'claimed'})
    same_agent = treg.make_event(log.state, task_id='T-0002', from_agent='R01', type='heartbeat', utc=log.utc(), payload={})
    other_agent = treg.make_event(log.state, task_id='T-0002', from_agent='R02', type='transition', utc=log.utc(),
                                  payload={'status_to': 'blocked', 'reason': 'race'})
    state, _ = treg.apply_event(log.state, a, ACTIVE)
    with pytest.raises(treg.TregError, match='event_id_conflict'):
        treg.apply_event(state, same_agent, ACTIVE)
    with pytest.raises(treg.TregError, match='sequence_or_chain_conflict'):
        treg.apply_event(state, other_agent, ACTIVE)
    assert state['tasks']['T-0002']['status'] == 'claimed'


def test_leased_task_refuses_other_agents_and_concurrent_claims_are_capped():
    log = Log()
    log.create(task())
    log.create(task('T-0003', 'report', 'R01'))
    log.emit('T-0002', 'R01', 'transition', {'status_to': 'claimed'})
    with pytest.raises(treg.TregError, match='concurrent_claim_limit'):
        log.emit('T-0003', 'R01', 'transition', {'status_to': 'claimed'})
    with pytest.raises(treg.TregError, match='task_leased_by_R01'):
        log.emit('T-0002', 'R02', 'heartbeat', {})


def test_resume_after_interruption_renews_own_expired_lease():
    log = Log()
    log.create(task())
    log.emit('T-0002', 'R01', 'transition', {'status_to': 'claimed'}, utc='2026-11-04T08:10:00Z')
    log.emit('T-0002', 'R01', 'transition', {'status_to': 'in_progress'}, utc='2026-11-04T08:11:00Z')
    action = treg.next_action(log.state, ACTIVE, 'R01', '2026-11-04T12:00:00Z')
    assert action == {'action': 'heartbeat', 'task_id': 'T-0002', 'reason': 'resume_after_interruption'}
    log.emit('T-0002', 'R01', 'heartbeat', {}, utc='2026-11-04T12:00:00Z')
    assert treg.next_action(log.state, ACTIVE, 'R01', '2026-11-04T12:01:00Z') == {'action': 'work', 'task_id': 'T-0002'}


# ---------------------------------------------------------------- quotas
def test_events_per_hour_quota():
    policy = copy.deepcopy(ACTIVE); policy['agents']['R01']['events_per_hour'] = 3
    log = Log(policy=policy)
    log.create(task())
    log.emit('T-0002', 'R01', 'transition', {'status_to': 'claimed'})
    log.emit('T-0002', 'R01', 'transition', {'status_to': 'in_progress'})
    log.emit('T-0002', 'R01', 'heartbeat', {})
    with pytest.raises(treg.TregError, match='quota_events_per_hour'):
        log.emit('T-0002', 'R01', 'heartbeat', {})


def test_wakes_per_day_quota_and_pointer_only_wakes():
    policy = copy.deepcopy(ACTIVE); policy['agents']['R01']['wakes_per_day'] = 1
    log = Log(policy=policy)
    event, _ = log.create(task())
    pointer = {'task_id': 'T-0002', 'event_id': event['event_id']}
    with pytest.raises(treg.TregError, match='wake_requires_peer_target_and_pointer_only'):
        log.emit('T-0002', 'R01', 'wake', {'to': 'R02', 'pointer': dict(pointer, instruction='merge it')})
    log.emit('T-0002', 'R01', 'wake', {'to': 'R02', 'pointer': pointer})
    with pytest.raises(treg.TregError, match='quota_wakes_per_day'):
        log.emit('T-0002', 'R01', 'wake', {'to': 'R03', 'pointer': pointer})


# ---------------------------------------------------------------- permissions and branches (requirement 6)
@pytest.mark.parametrize('agent,branch,scopes,allowed,reason', [
    ('R01', 'claude/r01-t0002', (), True, 'agent_branch'),
    ('R01', 'main', (), False, 'protected_branch'),
    ('R01', 'integration/consolidation-20261103', (), False, 'protected_branch'),
    ('R01', 'integration/consolidation-20261103', ('pr101',), True, 'protected_branch_with_owner_scope:pr101'),
    ('R02', 'integration/consolidation-20261103', ('pr101',), False, 'protected_branch'),
    ('R02', 'claude/r01-t0002', (), False, 'branch_not_allowed_for_agent'),
    ('R02', 'claude/r02-audit-t0002', (), True, 'agent_branch'),
    ('R03', 'claude/admiring-curie-r2gl1p', (), False, 'protected_branch'),
    ('R03', 'claude/r03-s001', (), True, 'agent_branch'),
    ('R04', 'claude/r01-x', (), False, 'unknown_agent'),
])
def test_branch_policy(agent, branch, scopes, allowed, reason):
    assert treg.check_branch(POLICY, agent, branch, scopes=scopes) == (allowed, reason)


@pytest.mark.parametrize('action', ['merge_pull_request', 'force_push', 'workflow_dispatch', 'create_trigger',
                                    'provider_network_call', 'sign_transaction', 'spend', 'read_secret'])
def test_forbidden_actions_for_every_agent(action):
    assert all(treg.check_action(POLICY, a, action)[0] is False for a in treg.AGENTS)


def test_implement_task_branch_must_be_allowed_for_assignee():
    with pytest.raises(treg.TregError, match='task_branch_refused:protected_branch'):
        Log().create(task(branch='main'))


def test_tampered_event_digest_is_refused():
    log = Log()
    event = treg.make_event(log.state, task_id='T-0002', from_agent='OWNER', type='create', utc=log.utc(), payload={'task': task()})
    event['payload']['task']['assignee'] = 'R02'
    with pytest.raises(treg.TregError, match='event_digest_mismatch'):
        treg.apply_event(log.state, event, ACTIVE)


def test_module_has_no_network_or_subprocess_imports():
    source = (ROOT / 'tools' / 'treg.py').read_text(encoding='utf-8')
    for banned in ('import socket', 'urllib', 'requests', 'aiohttp', 'subprocess', 'http.client', 'os.system'):
        assert banned not in source


# ---------------------------------------------------------------- live tooling (ingest / emit / dashboard)
RUN_POLICY = json.loads((ROOT / 'docs' / 'treg' / 'runs' / 'S-001.policy.json').read_text(encoding='utf-8'))


def assert_frozen_run_policy_never_looser_than_base(run):
    """Run policies are frozen evidence. After a run the base policy may only add restrictions."""
    extra = ('paused', 'paused_note', 'run_scope', 'owner_mandate_ref_sha256')
    base = {k: v for k, v in POLICY.items() if k not in ('paused', 'paused_note')}
    frozen = {k: v for k, v in run.items() if k not in extra}
    assert set(frozen) == set(base)
    for key in base:
        if key == 'agents':  # same quotas, sessions and branches; only the descriptive role may change
            for agent, spec in base['agents'].items():
                assert ({k: v for k, v in frozen['agents'][agent].items() if k != 'role'}
                        == {k: v for k, v in spec.items() if k != 'role'})
        elif key == 'forbidden_actions_by_agent':
            for agent, actions in frozen[key].items():
                assert set(actions) <= set(base[key][agent])
        else:
            assert frozen[key] == base[key]


def test_run_policy_only_lifts_the_pause():
    assert RUN_POLICY['paused'] is False and POLICY['paused'] is True
    assert_frozen_run_policy_never_looser_than_base(RUN_POLICY)


def test_ingest_ignores_non_event_comments_and_replays():
    state, _ = treg.simulate_scenario(POLICY)
    events = [e for tid in sorted(state['log']) for e in state['log'][tid]]
    mcp_like = [[{'id': i, 'body': treg.render_comment(e)} for i, e in enumerate(events)] + [{'body': 'human note'}]]
    snapshot = treg.ingest(mcp_like)
    assert len(snapshot['events']) == len(events)
    assert treg.replay(snapshot['events'], ACTIVE)['tasks'] == state['tasks']


def test_emit_cli_validates_and_prints_comment(tmp_path, capsys):
    log = Log()
    log.create(task('T-0001', 'data_handoff', 'R03'))
    snap = tmp_path / 'snap.json'
    snap.write_text(json.dumps({'schema': treg.SCHEMA_SNAPSHOT, 'events': log.state['log']['T-0001']}))
    pol = tmp_path / 'pol.json'
    pol.write_text(json.dumps(RUN_POLICY))
    assert treg.main(['emit', str(snap), '--policy', str(pol), '--task', 'T-0001', '--agent', 'R03',
                      '--type', 'transition', '--payload', '{"status_to": "claimed"}', '--now', '2026-11-04T09:00:00Z']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['comment_body'].startswith(treg.EVENT_MARKER) and out['event']['seq'] == 2
    with pytest.raises(treg.TregError, match='transition_refused'):
        treg.main(['emit', str(snap), '--policy', str(pol), '--task', 'T-0001', '--agent', 'R01',
                   '--type', 'transition', '--payload', '{"status_to": "claimed"}', '--now', '2026-11-04T09:00:00Z'])


def test_dashboard_lists_every_task_and_the_inbox():
    state, _ = treg.simulate_scenario(POLICY)
    board = treg.render_dashboard(state, generated_utc='2026-11-04T10:00:00Z')
    for tid in ('T-0001', 'T-0002', 'T-0003'):
        assert '| %s |' % tid in board
    assert 'audit PASS' in board and 'S-001' in board


# ---------------------------------------------------------------- forward links: closures notify the next agent
def _view(events, task_ids):
    """What an agent sees when it ingests only the issues of `task_ids` plus their transitive upstream
    (needed to replay claims). Downstream issues are deliberately NOT ingested."""
    deps = {e['task_id']: e['payload']['task']['depends_on'] for e in events if e['type'] == 'create'}
    wanted, todo = set(), list(task_ids)
    while todo:
        tid = todo.pop()
        if tid not in wanted:
            wanted.add(tid)
            todo.extend(deps.get(tid, []))
    return treg.replay(treg.order_events([e for e in events if e['task_id'] in wanted]), ACTIVE)


class Chain:
    """Full log shared on GitHub; each actor only ingests the issues it needs."""
    def __init__(self):
        self.events, self.minute, self.wakes, self.views = [], 0, [], []

    def act(self, agent, task_id, type, payload, sees):
        self.minute += 1
        view = _view(self.events, sees)
        event = treg.make_event(view, task_id=task_id, from_agent=agent, type=type,
                                utc='2026-11-04T10:%02d:00Z' % self.minute, payload=payload)
        view, _ = treg.apply_event(view, event, ACTIVE)
        self.views.append((task_id, payload.get('status_to'), sorted(view['tasks'])))
        self.events.append(event)
        targets = treg.wake_targets(view, event)
        self.wakes.append((task_id, payload.get('status_to'), [t['to'] for t in targets]))
        return view, targets


def _s001_tasks(with_downstream=True):
    t1 = task('T-0001', 'data_handoff', 'R03')
    t2 = task('T-0002', deps=['T-0001'], branch='claude/r01-t0002')
    t3 = task('T-0003', 'report', 'R01', deps=['T-0002'])
    if with_downstream:
        t1['downstream'] = [{'task_id': 'T-0002', 'agent': 'R01'}]
        t2['downstream'] = [{'task_id': 'T-0003', 'agent': 'R01'}]
    return t1, t2, t3


def test_real_failure_reproduced_reverse_scan_needs_full_snapshot():
    chain = Chain()
    for t in _s001_tasks(with_downstream=False):
        chain.act('OWNER', t['task_id'], 'create', {'task': t}, sees=[t['task_id']])
    for to in ('claimed', 'in_progress'):
        chain.act('R03', 'T-0001', 'transition', {'status_to': to}, sees=['T-0001'])
    chain.act('R03', 'T-0001', 'transition', {'status_to': 'submitted', 'dataset': {'sha256': 'e' * 64, 'commit': 'a' * 40, 'rows': 3},
                                              'validation': {'status': 'PASS'}}, sees=['T-0001'])
    _, partial = chain.act('R03', 'T-0001', 'transition', {'status_to': 'done'}, sees=['T-0001'])
    assert partial == []  # exactly what happened on #104
    full = _view(chain.events, ['T-0001', 'T-0002', 'T-0003'])
    assert [t['to'] for t in treg.wake_targets(full, chain.events[-1])] == ['R01']


def test_owner_link_repairs_notification_on_partial_view():
    chain = Chain()
    for t in _s001_tasks(with_downstream=False):
        chain.act('OWNER', t['task_id'], 'create', {'task': t}, sees=[t['task_id']])
    chain.act('OWNER', 'T-0001', 'link', {'downstream': [{'task_id': 'T-0002', 'agent': 'R01'}], 'recorded_by': 'R01'}, sees=['T-0001'])
    for to in ('claimed', 'in_progress'):
        chain.act('R03', 'T-0001', 'transition', {'status_to': to}, sees=['T-0001'])
    chain.act('R03', 'T-0001', 'transition', {'status_to': 'submitted', 'dataset': {'sha256': 'e' * 64, 'commit': 'a' * 40, 'rows': 3},
                                              'validation': {'status': 'PASS'}}, sees=['T-0001'])
    _, targets = chain.act('R03', 'T-0001', 'transition', {'status_to': 'done'}, sees=['T-0001'])
    assert [t['to'] for t in targets] == ['R01']


def test_every_closure_notifies_the_next_agent_on_partial_views():
    chain = Chain()
    for t in _s001_tasks():
        chain.act('OWNER', t['task_id'], 'create', {'task': t}, sees=[t['task_id']])
    for to in ('claimed', 'in_progress'):
        chain.act('R03', 'T-0001', 'transition', {'status_to': to}, sees=['T-0001'])
    chain.act('R03', 'T-0001', 'transition', {'status_to': 'submitted', 'dataset': {'sha256': 'e' * 64, 'commit': 'a' * 40, 'rows': 3},
                                              'validation': {'status': 'PASS'}}, sees=['T-0001'])
    chain.act('R03', 'T-0001', 'transition', {'status_to': 'done'}, sees=['T-0001'])
    for to in ('claimed', 'in_progress'):
        chain.act('R01', 'T-0002', 'transition', {'status_to': to}, sees=['T-0001', 'T-0002'])
    chain.act('R01', 'T-0002', 'transition', submit_payload(branch='claude/r01-t0002'), sees=['T-0002'])
    chain.act('R02', 'T-0002', 'transition', {'status_to': 'in_review'}, sees=['T-0002'])
    chain.act('R02', 'T-0002', 'transition', {'status_to': 'changes_requested', 'findings': ['rerun']}, sees=['T-0002'])
    chain.act('R01', 'T-0002', 'transition', {'status_to': 'in_progress'}, sees=['T-0002'])
    chain.act('R01', 'T-0002', 'transition', submit_payload(commit='f' * 40, branch='claude/r01-t0002'), sees=['T-0002'])
    chain.act('R02', 'T-0002', 'transition', {'status_to': 'in_review'}, sees=['T-0002'])
    chain.act('R02', 'T-0002', 'transition', {'status_to': 'done', 'audit': {'verdict': 'PASS', 'audited_commit': 'f' * 40}}, sees=['T-0002'])
    for to in ('claimed', 'in_progress'):
        chain.act('R01', 'T-0003', 'transition', {'status_to': to}, sees=['T-0002', 'T-0003'])
    chain.act('R01', 'T-0003', 'transition', {'status_to': 'submitted', 'inbox': {'summary': 's', 'task_refs': ['T-0001', 'T-0002']}}, sees=['T-0003'])
    view, last = chain.act('R01', 'T-0003', 'transition', {'status_to': 'done'}, sees=['T-0003'])
    notified = [(tid, to, who) for tid, to, who in chain.wakes if who]
    assert notified == [('T-0001', 'done', ['R01']), ('T-0002', 'submitted', ['R02']), ('T-0002', 'changes_requested', ['R01']),
                        ('T-0002', 'submitted', ['R02']), ('T-0002', 'done', ['R01'])]
    assert last == [] and view['inbox'][0]['task_refs'] == ['T-0001', 'T-0002']  # final hop goes to the RUGGER 04 inbox
    closing_views = {(tid, to): seen for tid, to, seen in chain.views if to == 'done'}
    assert closing_views[('T-0001', 'done')] == ['T-0001']            # R03 never saw T-0002
    assert closing_views[('T-0002', 'done')] == ['T-0001', 'T-0002']  # R02 never saw T-0003


@pytest.mark.parametrize('agent,payload,code', [
    ('R01', {'downstream': [{'task_id': 'T-0003', 'agent': 'R01'}]}, 'link_requires_owner_event_on_live_task'),
    ('OWNER', {'downstream': [{'task_id': 'T-0002', 'agent': 'R01'}]}, 'downstream_entry_invalid'),
    ('OWNER', {'downstream': [{'task_id': 'T-0003', 'agent': 'R04'}]}, 'downstream_entry_invalid'),
    ('OWNER', {'downstream': []}, 'link_requires_downstream_entries'),
    ('OWNER', {'downstream': [{'task_id': 'T-0003', 'agent': 'R01'}], 'status_to': 'done'}, 'link_requires_owner_event_on_live_task'),
])
def test_link_guards(agent, payload, code):
    log = Log()
    log.create(task())
    with pytest.raises(treg.TregError, match=code):
        log.emit('T-0002', agent, 'link', payload)


def test_emit_warns_on_partial_snapshot_and_unnotified_closure(tmp_path, capsys):
    log = Log()
    log.create(task('T-0001', 'data_handoff', 'R03'))
    for to in ('claimed', 'in_progress'):
        log.emit('T-0001', 'R03', 'transition', {'status_to': to})
    log.emit('T-0001', 'R03', 'transition', {'status_to': 'submitted', 'dataset': {'sha256': 'e' * 64, 'commit': 'a' * 40, 'rows': 3},
                                             'validation': {'status': 'PASS'}})
    snap = tmp_path / 's.json'
    snap.write_text(json.dumps({'schema': treg.SCHEMA_SNAPSHOT, 'events': log.state['log']['T-0001']}))
    pol = tmp_path / 'p.json'
    pol.write_text(json.dumps(RUN_POLICY))
    treg.main(['emit', str(snap), '--policy', str(pol), '--task', 'T-0001', '--agent', 'R03', '--type', 'transition',
               '--payload', '{"status_to": "done"}', '--now', '2026-11-04T11:00:00Z'])
    assert json.loads(capsys.readouterr().out)['warnings'] == ['done_without_downstream_nobody_notified']
    log2 = Log()
    log2.create(task(deps=['T-0001']))
    snap.write_text(json.dumps({'schema': treg.SCHEMA_SNAPSHOT, 'events': log2.state['log']['T-0002']}))
    out = treg.missing_references(treg.replay(log2.state['log']['T-0002'], ACTIVE))
    assert out == ['T-0001']


# ---------------------------------------------------------------- RUGGER 04 direct read: heads, digests, freshness
def test_s002_run_policy_only_lifts_the_pause():
    run = json.loads((ROOT / 'docs' / 'treg' / 'runs' / 'S-002.policy.json').read_text(encoding='utf-8'))
    extra = ('paused', 'paused_note', 'run_scope', 'owner_mandate_ref_sha256')
    assert run['paused'] is False and run['run_scope'] == 'treg-scenario-S-002' and set(extra) <= set(run)
    assert_frozen_run_policy_never_looser_than_base(run)


def test_heads_match_last_event_of_each_task_and_registry_digest_is_recomputable():
    state, _ = treg.simulate_scenario(POLICY)
    h = treg.heads(state, generated_utc='2026-11-04T10:00:00Z')
    for tid, head in h['tasks'].items():
        assert head['digest'] == state['log'][tid][-1]['digest'] and head['seq'] == len(state['log'][tid])
    assert h['registry_digest'] == treg.digest({k: v['digest'] for k, v in h['tasks'].items()})
    result = treg.verify_heads(h, state, now='2026-11-04T10:30:00Z')
    assert result == {'consistent': True, 'integrity_ok': True, 'fresh': True, 'integrity': [], 'stale': [],
                      'problems': [], 'registry_digest': h['registry_digest']}


def test_verify_heads_separates_an_obsolete_dashboard_from_an_integrity_divergence():
    state, _ = treg.simulate_scenario(POLICY)
    old = treg.heads(state, generated_utc='2026-11-04T10:00:00Z')
    tid = 'T-0002'
    ev = treg.make_event(state, task_id=tid, from_agent='R01', type='wake', utc='2026-11-04T11:00:00Z',
                         payload={'to': 'R02', 'pointer': {'task_id': tid, 'event_id': state['log'][tid][-1]['event_id']}})
    newer, _ = treg.apply_event(state, ev, ACTIVE)
    # Obsolete: the registry moved on after the dashboard, history unchanged.
    result = treg.verify_heads(old, newer, now='2026-11-04T12:30:00Z', max_age_minutes=60)
    assert result['consistent'] is False and result['integrity_ok'] is True and result['fresh'] is False
    n = len(state['log'][tid])
    assert result['stale'] == ['task_advanced:T-0002:published_seq=%d:registry_seq=%d' % (n, n + 1)]
    assert result['integrity'] == []
    # A task created after the dashboard is obsolescence too.
    created = treg.make_event(newer, task_id='T-0004', from_agent='OWNER', type='create', utc='2026-11-04T11:30:00Z',
                              payload={'task': task('T-0004', kind='report', deps=('T-0003',))})
    newest, _ = treg.apply_event(newer, created, ACTIVE)
    assert treg.verify_heads(old, newest, now='2026-11-04T11:40:00Z')['stale'][-1] == 'task_created_after_heads:T-0004'
    # Integrity: a task that existed when the dashboard was generated is missing from it.
    omitted = copy.deepcopy(old); del omitted['tasks']['T-0003']
    omitted['registry_digest'] = treg.digest({k: v['digest'] for k, v in omitted['tasks'].items()})
    assert treg.verify_heads(omitted, state, now='2026-11-04T10:01:00Z')['integrity'] == ['task_omitted_from_heads:T-0003']
    # Integrity: the event named by the dashboard differs in the registry (rewritten history).
    rewritten = copy.deepcopy(old); rewritten['tasks']['T-0001']['digest'] = '0' * 64
    rewritten['registry_digest'] = treg.digest({k: v['digest'] for k, v in rewritten['tasks'].items()})
    check = treg.verify_heads(rewritten, newer, now='2026-11-04T10:01:00Z')
    assert check['integrity_ok'] is False
    assert check['integrity'] == ['digest_mismatch_at_published_seq:T-0001:seq=%d' % len(state['log']['T-0001'])]
    # Integrity: the dashboard names an event the registry read does not contain (deleted or partial read).
    truncated = copy.deepcopy(state); truncated['log'][tid] = truncated['log'][tid][:-2]
    assert treg.verify_heads(old, truncated, now='2026-11-04T10:01:00Z')['integrity'] == [
        'published_event_not_in_registry_read:T-0002:published_seq=%d:registry_seq=%d' % (n, n - 2)]
    # Integrity: a self-inconsistent block.
    forged = copy.deepcopy(old); forged['tasks']['T-0001']['digest'] = '0' * 64
    assert 'published_registry_digest_inconsistent' in treg.verify_heads(forged, state, now='2026-11-04T10:01:00Z')['integrity']


def test_verify_heads_cli_reads_the_published_dashboard_markdown(tmp_path, capsys):
    state, _ = treg.simulate_scenario(POLICY)
    events = [e for tid in sorted(state['log']) for e in state['log'][tid]]
    snap = tmp_path / 'snap.json'
    snap.write_text(json.dumps({'schema': treg.SCHEMA_SNAPSHOT, 'events': treg.order_events(events)}))
    board = tmp_path / 'board.md'
    board.write_text(treg.render_dashboard(state, generated_utc='2026-11-04T10:00:00Z'))
    pol = tmp_path / 'pol.json'
    pol.write_text(json.dumps(RUN_POLICY))
    assert treg.HEADS_MARKER in board.read_text()
    code = treg.main(['verify-heads', str(snap), '--policy', str(pol), '--heads', str(board), '--now', '2026-11-04T10:20:00Z'])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out['consistent'] and out['fresh']
    # Old but consistent: obsolete (3), not an integrity failure (4).
    assert treg.main(['verify-heads', str(snap), '--policy', str(pol), '--heads', str(board), '--now', '2026-11-04T13:00:00Z']) == 3
    capsys.readouterr()
    board.write_text(board.read_text().replace(state['log']['T-0001'][-1]['digest'], '1' * 64))
    assert treg.main(['verify-heads', str(snap), '--policy', str(pol), '--heads', str(board), '--now', '2026-11-04T10:20:00Z']) == 4


# ---------------------------------------------------------------- planner closes producer tasks (S-002 finding)
@pytest.mark.parametrize('kind,agent,payload', [
    ('data_handoff', 'R03', {'status_to': 'submitted', 'dataset': {'path': 'd', 'sha256': 'e' * 64, 'commit': 'a' * 40,
                                                                   'rows': 7}, 'validation': {'status': 'PASS'}}),
    ('report', 'R01', {'status_to': 'submitted', 'inbox': {'summary': 's', 'task_refs': ['T-0001']}}),
])
def test_plan_tells_the_producer_to_close_a_submitted_handoff_or_report(kind, agent, payload):
    # Found by RUGGER 03 in S-002: `plan` answered `wait` at `submitted`, so an agent that
    # follows the planner literally never closed a data_handoff or report task.
    log = Log()
    log.create(task('T-0001', kind=kind, assignee=agent))
    for step in ({'status_to': 'claimed'}, {'status_to': 'in_progress'}, payload):
        log.emit('T-0001', agent, 'transition', step)
    now = '2026-11-04T09:00:00Z'
    assert treg.next_action(log.state, ACTIVE, agent, now) == {'action': 'close', 'task_id': 'T-0001'}
    other = 'R02'
    assert treg.next_action(log.state, ACTIVE, other, now)['action'] == 'wait'
    log.emit('T-0001', agent, 'transition', {'status_to': 'done'})
    assert treg.next_action(log.state, ACTIVE, agent, now) == {'action': 'wait', 'reason': 'nothing_actionable'}


def test_plan_never_closes_a_submitted_implement_for_its_author():
    log = Log()
    log.create(task())
    for step in ({'status_to': 'claimed'}, {'status_to': 'in_progress'}, submit_payload()):
        log.emit('T-0002', 'R01', 'transition', step)
    now = '2026-11-04T09:00:00Z'
    log.state, _ = treg.journal_wakes(log.state, ACTIVE, log.state['log']['T-0002'][-1], log.utc())
    assert treg.next_action(log.state, ACTIVE, 'R01', now)['action'] == 'wait'
    assert treg.next_action(log.state, ACTIVE, 'R02', now) == {'action': 'start_review', 'task_id': 'T-0002'}



# ---------------------------------------------------------------- wake journaling (owner priority after S-002)
EVIDENCE = ROOT / 'docs' / 'treg' / 'evidence'
BUSY = copy.deepcopy(ACTIVE)
for _spec in BUSY['agents'].values():
    _spec['events_per_hour'] = 1000  # isolate the wake quota from the hourly event quota


def submitted_log(policy=ACTIVE):
    log = Log(policy=policy)
    log.create(task())
    for step in ({'status_to': 'claimed'}, {'status_to': 'in_progress'}, submit_payload()):
        event, _ = log.emit('T-0002', 'R01', 'transition', step)
    return log, event


def wake(log, agent, to, pointer_event_id, task_id='T-0002', utc=None):
    return log.emit(task_id, agent, 'wake', {'to': to, 'pointer': {'task_id': task_id, 'event_id': pointer_event_id}},
                    utc=utc)


def test_a_required_wake_is_an_obligation_until_journaled_then_counted_once():
    log, submitted = submitted_log()
    due = treg.pending_wakes(log.state)
    assert [(d['from'], d['to'], d['pointer_event_id'], d['useful']) for d in due] == [
        ('R01', 'R02', submitted['event_id'], True)]
    now = '2026-11-04T09:00:00Z'
    assert treg.next_action(log.state, ACTIVE, 'R01', now) == {
        'action': 'journal_wake', 'task_id': 'T-0002', 'to': 'R02',
        'pointer': {'task_id': 'T-0002', 'event_id': submitted['event_id']}}
    log.state, items = treg.journal_wakes(log.state, ACTIVE, submitted, log.utc())
    assert len(items) == 1 and treg.pending_wakes(log.state) == []
    assert log.state['wakes'][0]['required'] is True
    assert treg.wake_quota(log.state, ACTIVE, 'R01', now)['used_24h'] == 1
    message = json.loads(items[0]['send']['message'])
    assert message == {'treg_pointer': {'task_id': 'T-0002', 'event_id': items[0]['event']['event_id']}}
    assert items[0]['send']['session_id'] == ACTIVE['agents']['R02']['session_id']


def test_duplicate_wake_is_refused_so_a_resend_never_counts_twice():
    log, submitted = submitted_log()
    wake(log, 'R01', 'R02', submitted['event_id'])
    with pytest.raises(treg.TregError, match='duplicate_wake'):
        wake(log, 'R01', 'R02', submitted['event_id'])
    assert treg.wake_quota(log.state, ACTIVE, 'R01', '2026-11-04T09:00:00Z')['used_24h'] == 1


def test_republishing_the_same_wake_after_a_failed_write_is_idempotent():
    log, submitted = submitted_log()
    event = treg.make_event(log.state, task_id='T-0002', from_agent='R01', type='wake', utc=log.utc(),
                            payload={'to': 'R02', 'pointer': {'task_id': 'T-0002', 'event_id': submitted['event_id']}})
    log.state, applied = treg.apply_event(log.state, event, ACTIVE)
    again, applied_again = treg.apply_event(log.state, event, ACTIVE)  # e.g. GitHub 500, then re-read and re-post
    assert applied and not applied_again and again == log.state
    forged = dict(event, utc='2026-11-04T23:00:00Z')
    forged['digest'] = treg.event_digest(forged)
    with pytest.raises(treg.TregError, match='event_id_conflict'):
        treg.apply_event(log.state, forged, ACTIVE)


@pytest.mark.parametrize('payload,code', [
    ({'to': 'R02', 'pointer': {'task_id': 'T-0002', 'event_id': 'T-0002-R01-0099'}}, 'wake_pointer_unknown'),
    ({'to': 'R02', 'pointer': {'task_id': 'T-0009', 'event_id': 'T-0002-OWNER-0001'}}, 'wake_pointer_unknown'),
    ({'to': 'R01', 'pointer': {'task_id': 'T-0002', 'event_id': 'T-0002-OWNER-0001'}}, 'wake_requires_peer'),
    ({'to': 'R04', 'pointer': {'task_id': 'T-0002', 'event_id': 'T-0002-OWNER-0001'}}, 'wake_requires_peer'),
    ({'to': 'R02', 'pointer': {'task_id': 'T-0002', 'event_id': 'T-0002-OWNER-0001'}, 'note': 'do X'},
     'wake_requires_peer'),
    ({'to': 'R02', 'pointer': 'T-0002-OWNER-0001'}, 'wake_requires_peer'),
])
def test_malformed_or_dangling_wakes_are_refused(payload, code):
    log = Log()
    log.create(task())
    with pytest.raises(treg.TregError, match=code):
        log.emit('T-0002', 'R01', 'wake', payload)


def test_wake_quota_is_a_rolling_24_hours_and_exhaustion_means_block():
    log = Log(policy=BUSY)
    log.create(task())
    previous = 'T-0002-OWNER-0001'
    for minute in range(24):  # 24 distinct wakes on 2026-11-04 between 20:00 and 20:23
        event, _ = wake(log, 'R01', ('R02', 'R03')[minute % 2], previous, utc='2026-11-04T20:%02d:00Z' % minute)
        previous = event['event_id']
    with pytest.raises(treg.TregError, match='quota_wakes_per_day'):  # calendar day would have allowed it
        wake(log, 'R01', 'R02', previous, utc='2026-11-05T00:30:00Z')
    # The agent cannot wake its peer any more: it stops by blocking (always allowed), it does not skip the journal.
    _, applied = log.emit('T-0002', 'R01', 'transition', {'status_to': 'blocked', 'reason': 'quota_wakes_per_day'},
                          utc='2026-11-05T00:31:00Z')
    assert applied and log.state['tasks']['T-0002']['status'] == 'blocked'
    _, applied = wake(log, 'R01', 'R02', previous, utc='2026-11-05T20:00:30Z')  # oldest wake left the window
    assert applied


def test_journal_wakes_raises_before_anything_is_posted_when_the_quota_is_spent():
    policy = copy.deepcopy(ACTIVE)
    policy['agents']['R01']['wakes_per_day'] = 1
    log, submitted = submitted_log(policy)
    wake(log, 'R01', 'R03', submitted['event_id'])  # spends the only wake
    with pytest.raises(treg.TregError, match='quota_wakes_per_day'):
        treg.journal_wakes(log.state, policy, submitted, log.utc())


def test_receiver_acts_only_on_journaled_wakes_addressed_to_it():
    log, submitted = submitted_log()
    r01, r02 = ACTIVE['agents']['R01']['session_id'], ACTIVE['agents']['R02']['session_id']
    check = treg.accept_pointer
    pointer = {'task_id': 'T-0002', 'event_id': submitted['event_id']}
    assert check(log.state, ACTIVE, 'R02', pointer)['reason'] == 'unjournaled_wake'  # sender skipped the registry
    log.state, items = treg.journal_wakes(log.state, ACTIVE, submitted, log.utc())
    wake_pointer = json.loads(items[0]['send']['message'])['treg_pointer']
    assert check(log.state, ACTIVE, 'R02', wake_pointer, sender_session=r01)['accept'] is True
    assert check(log.state, ACTIVE, 'R02', pointer)['accept'] is True  # earlier protocol: transition + journaled wake
    assert check(log.state, ACTIVE, 'R03', wake_pointer)['reason'] == 'wake_not_addressed_to_agent'
    assert check(log.state, ACTIVE, 'R02', wake_pointer, sender_session=r02)['reason'] == 'wake_sender_mismatch'
    assert check(log.state, ACTIVE, 'R02', {'task_id': 'T-0002', 'event_id': 'T-0002-R01-0042'})['reason'] == \
        'pointer_unknown_event'
    assert check(log.state, ACTIVE, 'R02', {'event_id': 'x'})['reason'] == 'pointer_format'


def test_a_duplicate_delivery_is_a_no_op_for_the_receiver():
    log, submitted = submitted_log()
    log.state, items = treg.journal_wakes(log.state, ACTIVE, submitted, log.utc())
    pointer = json.loads(items[0]['send']['message'])['treg_pointer']
    now = '2026-11-04T09:00:00Z'
    assert treg.accept_pointer(log.state, ACTIVE, 'R02', pointer)['accept']
    assert treg.next_action(log.state, ACTIVE, 'R02', now) == {'action': 'start_review', 'task_id': 'T-0002'}
    log.emit('T-0002', 'R02', 'transition', {'status_to': 'in_review'})
    assert treg.accept_pointer(log.state, ACTIVE, 'R02', pointer)['accept']  # same message delivered again
    assert treg.next_action(log.state, ACTIVE, 'R02', now) == {'action': 'audit', 'task_id': 'T-0002'}
    with pytest.raises(treg.TregError, match='transition_refused'):
        log.emit('T-0002', 'R02', 'transition', {'status_to': 'in_review'})


def test_an_unjournaled_wake_stops_being_demanded_once_the_target_has_moved_on():
    log, submitted = submitted_log()
    log.emit('T-0002', 'R02', 'transition', {'status_to': 'in_review'})  # R02 acted without a journaled wake
    due = treg.pending_wakes(log.state)
    assert len(due) == 1 and due[0]['useful'] is False  # still reported, no longer demanded
    assert treg.next_action(log.state, ACTIVE, 'R01', '2026-11-04T09:00:00Z')['action'] == 'wait'


def test_simulation_journals_every_required_wake_and_receivers_accept_them():
    state, ops = treg.simulate_scenario(POLICY)
    assert treg.pending_wakes(state) == []
    assert [(w['from'], w['to'], w['required']) for w in state['wakes']] == [
        ('R03', 'R01', True), ('R01', 'R02', True), ('R02', 'R01', True)]
    sends = [o for o in ops if o['tool'].endswith('send_message')]
    for send in sends:  # each message names the journaled wake event, which precedes it in the operations
        assert json.loads(send['message'])['treg_pointer']['event_id'].split('-')[-2] in treg.AGENTS


def test_emit_prints_the_wake_events_to_post_and_the_messages_to_send(tmp_path, capsys):
    log, _ = submitted_log()
    log.state['log']['T-0002'].pop()  # rebuild the snapshot just before the submission
    events = [e for tid in sorted(log.state['log']) for e in log.state['log'][tid]]
    snap = tmp_path / 'snap.json'
    snap.write_text(json.dumps({'schema': treg.SCHEMA_SNAPSHOT, 'events': events}), encoding='utf-8')
    policy = tmp_path / 'policy.json'
    policy.write_text(json.dumps(ACTIVE), encoding='utf-8')
    rc = treg.main(['emit', str(snap), '--policy', str(policy), '--task', 'T-0002', '--agent', 'R01',
                    '--type', 'transition', '--payload', json.dumps(submit_payload()), '--now', '2026-11-04T09:00:00Z'])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and len(out['wake_events']) == 1
    wake_event = out['wake_events'][0]['event']
    assert wake_event['prev_digest'] == out['event']['digest'] and wake_event['payload']['to'] == 'R02'
    assert json.loads(out['send_after_posting'][0]['message'])['treg_pointer']['event_id'] == wake_event['event_id']
    state = treg.replay(events + [out['event'], wake_event], ACTIVE)
    assert treg.pending_wakes(state) == []


@pytest.mark.parametrize('run,expected', [
    ('S-001', [('T-0001', 'R03', 'R01'), ('T-0002', 'R02', 'R01')]),
    ('S-002', [('T-0005', 'R02', 'R01')]),
])
def test_archived_runs_replay_and_show_exactly_their_unjournaled_wakes(run, expected):
    policy = json.loads((ROOT / 'docs' / 'treg' / 'runs' / ('%s.policy.json' % run)).read_text(encoding='utf-8'))
    snapshot = json.loads((EVIDENCE / run / 'events.json').read_text(encoding='utf-8'))
    state = treg.replay(snapshot['events'], policy)
    assert all(t['status'] == 'done' for t in state['tasks'].values())
    missing = treg.pending_wakes(state)
    assert [(m['task_id'], m['from'], m['to']) for m in missing] == expected
    assert not any(m['useful'] for m in missing)  # history: nobody is asked to journal them now
    for agent in treg.AGENTS:
        assert treg.next_action(state, policy, agent, '2026-11-04T09:00:00Z')['action'] == 'wait'


# ---------------------------------------------------------------- RUGGER 04 direct read (r04-verify)
def archived_registry():
    """Comment lists per task issue, rebuilt from the archived S-001 and S-002 evidence."""
    lists = []
    for run in ('S-001', 'S-002'):
        events = json.loads((EVIDENCE / run / 'events.json').read_text(encoding='utf-8'))['events']
        for task_id in sorted({e['task_id'] for e in events}):
            mine = sorted((e for e in events if e['task_id'] == task_id), key=lambda e: e['seq'])
            lists.append([{'body': treg.render_comment(e)} for e in mine])
    return lists


S002_POLICY = json.loads((ROOT / 'docs' / 'treg' / 'runs' / 'S-002.policy.json').read_text(encoding='utf-8'))


def inbox_with_dashboard(lists, generated_utc, *, extra_after=()):
    state = treg.replay(treg.ingest(lists)['events'], S002_POLICY)
    board = treg.render_dashboard(state, generated_utc=generated_utc, policy=S002_POLICY)
    return [{'id': 1, 'body': 'S-002 report, no heads here'},
            {'id': 2, 'html_url': 'https://example.invalid/issues/103#issuecomment-2', 'body': board},
            *({'id': 3 + i, 'body': b} for i, b in enumerate(extra_after))]


def test_r04_verify_reports_current_then_idle_then_diverged():
    lists = archived_registry()
    inbox = inbox_with_dashboard(lists, '2026-11-04T00:00:00Z', extra_after=['a later comment without heads'])
    fresh = treg.r04_verify(lists, inbox, POLICY, now='2026-11-04T00:30:00Z')  # shipped (paused) policy: reader mode
    assert fresh['verdict'] == 'CURRENT' and fresh['events'] == 40 and len(fresh['tasks']) == 6
    assert fresh['heads_comment'].endswith('#issuecomment-2') and fresh['wakes_not_journaled'] == 3
    assert fresh['line'].startswith('RUGGER04-VERIFY | utc=2026-11-04T00:30:00Z') and fresh['line'].endswith('CURRENT')
    idle = treg.r04_verify(lists, inbox, POLICY, now='2026-11-04T09:00:00Z')
    assert idle['verdict'] == 'CURRENT_IDLE' and idle['registry_digest'] == fresh['registry_digest']
    truncated = [list(x) for x in lists]
    truncated[-1].pop()  # an event the inbox heads know about is missing from what was read
    assert treg.r04_verify(truncated, inbox, POLICY, now='2026-11-04T00:30:00Z')['verdict'] == 'DIVERGED'
    partial = lists[3:]  # only S-002 issues read: the heads list tasks the reader did not see
    assert treg.r04_verify(partial, inbox, POLICY, now='2026-11-04T00:30:00Z')['verdict'] == 'DIVERGED'


def test_r04_verify_without_heads_and_from_the_command_line(tmp_path, capsys):
    lists = archived_registry()
    assert treg.r04_verify(lists, [{'body': 'nothing'}], POLICY, now='2026-11-04T00:30:00Z')['verdict'] == 'NO_HEADS'
    paths = []
    for i, comments in enumerate(lists):
        path = tmp_path / ('c%d.json' % i)
        path.write_text(json.dumps(comments), encoding='utf-8')
        paths.append(str(path))
    inbox = tmp_path / 'inbox.json'
    inbox.write_text(json.dumps(inbox_with_dashboard(lists, '2026-11-04T00:00:00Z')), encoding='utf-8')
    policy = str(ROOT / 'docs' / 'treg' / 'agents.json')
    assert treg.main(['r04-verify', '--policy', policy, '--registry', *paths, '--inbox', str(inbox),
                      '--now', '2026-11-04T00:10:00Z']) == 0
    assert json.loads(capsys.readouterr().out)['verdict'] == 'CURRENT'
    assert treg.main(['r04-verify', '--policy', policy, '--registry', *paths[:-1], '--inbox', str(inbox),
                      '--now', '2026-11-04T00:10:00Z']) == 4
    assert json.loads(capsys.readouterr().out)['verdict'] == 'DIVERGED'


def test_accept_pointer_command_reads_the_whole_message(tmp_path, capsys):
    events = json.loads((EVIDENCE / 'S-002' / 'events.json').read_text(encoding='utf-8'))['events']
    snap = tmp_path / 'snap.json'
    snap.write_text(json.dumps({'schema': treg.SCHEMA_SNAPSHOT, 'events': events}), encoding='utf-8')
    policy = str(ROOT / 'docs' / 'treg' / 'runs' / 'S-002.policy.json')
    r03 = S002_POLICY['agents']['R03']['session_id']
    ok = json.dumps({'treg_pointer': {'task_id': 'T-0004', 'event_id': 'T-0004-R03-0006'}})  # S-002, as sent by R03
    assert treg.main(['accept-pointer', str(snap), '--policy', policy, '--agent', 'R01', '--pointer', ok,
                      '--from-session', r03]) == 0
    assert json.loads(capsys.readouterr().out)['wake_event_id'] == 'T-0004-R03-0007'
    unjournaled = json.dumps({'task_id': 'T-0005', 'event_id': 'T-0005-R02-0007'})  # S-002, as sent by R02
    assert treg.main(['accept-pointer', str(snap), '--policy', policy, '--agent', 'R01', '--pointer', unjournaled]) == 4
    assert json.loads(capsys.readouterr().out)['reason'] == 'unjournaled_wake'


def test_s003_run_policy_only_lifts_the_pause():
    run = json.loads((ROOT / 'docs' / 'treg' / 'runs' / 'S-003.policy.json').read_text(encoding='utf-8'))
    assert run['paused'] is False and run['run_scope'] == 'treg-scenario-S-003'
    assert run['owner_mandate_ref_sha256'] == '08ed4480f5e9e2afeec24084ae9e95b9f5232b56b49fa488234bb647d0c1f1d5'
    assert run['agents'] == POLICY['agents']  # S-003 runs on the current base rules, R02 mandate included
    assert_frozen_run_policy_never_looser_than_base(run)



def test_r04_verify_calls_a_dashboard_stale_when_the_registry_only_moved_on(tmp_path, capsys):
    lists = archived_registry()
    s001 = lists[:3]  # dashboard generated when only S-001 existed, then S-002 happened
    inbox = inbox_with_dashboard(s001, '2026-11-03T23:20:00Z')
    stale = treg.r04_verify(lists, inbox, POLICY, now='2026-11-04T00:30:00Z')
    assert stale['verdict'] == 'STALE' and stale['integrity'] == []
    assert stale['stale'] == ['task_created_after_heads:T-0004', 'task_created_after_heads:T-0005',
                              'task_created_after_heads:T-0006']
    # The same S-001 dashboard dated after S-002 started would hide existing tasks: integrity anomaly.
    hiding = inbox_with_dashboard(s001, '2026-11-03T23:50:00Z')
    assert treg.r04_verify(lists, hiding, POLICY, now='2026-11-04T00:30:00Z')['verdict'] == 'DIVERGED'
    paths = []
    for i, comments in enumerate(lists):
        path = tmp_path / ('c%d.json' % i)
        path.write_text(json.dumps(comments), encoding='utf-8')
        paths.append(str(path))
    box = tmp_path / 'inbox.json'
    box.write_text(json.dumps(inbox), encoding='utf-8')
    assert treg.main(['r04-verify', '--policy', str(ROOT / 'docs' / 'treg' / 'agents.json'), '--registry', *paths,
                      '--inbox', str(box), '--now', '2026-11-04T00:30:00Z']) == 3
    assert json.loads(capsys.readouterr().out)['verdict'] == 'STALE'


def test_find_heads_prefers_the_most_recent_block_wherever_it_is():
    lists = archived_registry()
    newer = inbox_with_dashboard(lists, '2026-11-04T00:00:00Z')[1]
    older = dict(inbox_with_dashboard(lists[:3], '2026-11-03T23:20:00Z')[1], html_url='issue-body')
    block, ref = treg.find_heads([newer, older])  # an older table listed after (e.g. the issue body) never wins
    assert block['generated_utc'] == '2026-11-04T00:00:00Z' and ref == newer['html_url']
    assert treg.find_heads([older, newer])[1] == newer['html_url']


def test_s003_archived_run_has_every_required_wake_journaled_and_accepted():
    policy = json.loads((ROOT / 'docs' / 'treg' / 'runs' / 'S-003.policy.json').read_text(encoding='utf-8'))
    events = json.loads((EVIDENCE / 'S-003' / 'events.json').read_text(encoding='utf-8'))['events']
    state = treg.replay(events, policy)
    assert {k: v['status'] for k, v in state['tasks'].items()} == {'T-0007': 'done', 'T-0008': 'done', 'T-0009': 'done'}
    assert treg.pending_wakes(state) == []  # S-003: no required wake left unjournaled
    sessions = {a: policy['agents'][a]['session_id'] for a in treg.AGENTS}
    real = [('R03', 'T-0007-R01-0003', 'R01'), ('R01', 'T-0007-R03-0008', 'R03'),
            ('R02', 'T-0008-R01-0005', 'R01'), ('R01', 'T-0008-R02-0008', 'R02')]
    for receiver, wake_id, sender in real:
        task_id = wake_id[:6]
        check = treg.accept_pointer(state, policy, receiver, {'task_id': task_id, 'event_id': wake_id},
                                    sender_session=sessions[sender])
        assert check['accept'] and check['wake_event_id'] == wake_id
    # The real negative tests of S-003, replayed: unjournaled (N1) and misaddressed (N2) pointers are refused.
    assert treg.accept_pointer(state, policy, 'R03', {'task_id': 'T-0007', 'event_id': 'T-0007-OWNER-0001'})['reason'] \
        == 'unjournaled_wake'
    assert treg.accept_pointer(state, policy, 'R02', {'task_id': 'T-0007', 'event_id': 'T-0007-R01-0003'})['reason'] \
        == 'wake_not_addressed_to_agent'
    assert state['tasks']['T-0008']['evidence']['audit']['audited_commit'] == '0b41b13ba27352156ccd38690443605036703107'


# ---------------------------------------------------------------- supervision notifications (RUGGER 04 logic)
def test_supervise_reports_each_completed_step_once():
    state, _ = treg.simulate_scenario(POLICY)
    notes = treg.supervise(state, now='2026-11-04T12:00:00Z')
    assert [(n['kind'], n['task_id']) for n in notes] == [('step_done', 'T-0003')]
    assert all(len(n['message']) < 200 for n in notes)
    block = treg.render_notify_block(notes, utc='2026-11-04T12:00:01Z', channel='push')
    sent = treg.sent_notifications([{'body': 'x'}, {'body': block}])
    assert sent == {notes[0]['key']} and treg.supervise(state, now='2026-11-04T13:00:00Z', sent=sent) == []


def test_supervise_flags_failed_audits_blocked_tasks_stalls_and_integrity():
    log, submitted = submitted_log()
    log.state, _ = treg.journal_wakes(log.state, ACTIVE, submitted, log.utc())
    log.emit('T-0002', 'R02', 'transition', {'status_to': 'in_review'})
    event, _ = log.emit('T-0002', 'R02', 'transition', {'status_to': 'changes_requested', 'findings': ['missing test']})
    assert [n['kind'] for n in treg.supervise(log.state, now='2026-11-04T09:00:00Z')] == ['audit_failed', 'stalled']
    log.state, _ = treg.journal_wakes(log.state, ACTIVE, event, log.utc())  # protocol: wake the author
    kinds = [n['kind'] for n in treg.supervise(log.state, now='2026-11-04T09:00:00Z')]
    assert kinds == ['audit_failed']
    log.emit('T-0002', 'R01', 'transition', {'status_to': 'blocked', 'reason': 'quota_wakes_per_day'})
    notes = treg.supervise(log.state, now='2026-11-04T09:00:00Z')
    assert [n['kind'] for n in notes] == ['decision_needed'] and 'quota_wakes_per_day' in notes[0]['message']
    # An unjournaled wake that is still useful stops the chain: flagged after 15 minutes.
    log2, submitted2 = submitted_log()
    assert treg.supervise(log2.state, now='2026-11-04T08:10:00Z') == []
    assert [n['kind'] for n in treg.supervise(log2.state, now='2026-11-04T09:00:00Z')] == ['stalled']
    # A ready task nobody claims for longer than stall_minutes.
    log3 = Log()
    log3.create(task())
    assert [n['kind'] for n in treg.supervise(log3.state, now='2026-11-04T11:00:00Z', stall_minutes=60)] == ['stalled']
    # An r04_verify integrity divergence always alerts.
    alert = treg.supervise(log3.state, now='2026-11-04T08:02:00Z',
                           r04={'verdict': 'DIVERGED', 'registry_digest': 'ab', 'integrity': ['task_omitted_from_heads:T-0001']})
    assert [n['kind'] for n in alert] == ['integrity_alert']


def test_supervise_on_the_archived_registry_reports_the_three_reports_only():
    events = []
    for run in ('S-001', 'S-002', 'S-003'):
        events += json.loads((EVIDENCE / run / 'events.json').read_text(encoding='utf-8'))['events']
    policy = json.loads((ROOT / 'docs' / 'treg' / 'runs' / 'S-003.policy.json').read_text(encoding='utf-8'))
    state = treg.replay(treg.order_events(events), policy)
    notes = treg.supervise(state, now='2026-11-04T00:30:00Z')
    assert [(n['kind'], n['task_id']) for n in notes] == [('step_done', 'T-0003'), ('step_done', 'T-0006'),
                                                         ('step_done', 'T-0009')]



def test_priv1_run_policy_only_lifts_the_pause():
    run = json.loads((ROOT / 'docs' / 'treg' / 'runs' / 'PRIV-1.policy.json').read_text(encoding='utf-8'))
    assert run['paused'] is False and run['run_scope'] == 'probe-priv-1'
    assert run['owner_mandate_ref_sha256'] == '4806c91e6104ece55077855fb2347c50edb608cc5675f04409b4b0340eb0bd02'
    assert run['agents'] == POLICY['agents']
    assert_frozen_run_policy_never_looser_than_base(run)
