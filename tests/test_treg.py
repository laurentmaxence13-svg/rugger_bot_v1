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


def test_run_policy_only_lifts_the_pause():
    stripped = {k: v for k, v in RUN_POLICY.items() if k not in ('paused', 'paused_note', 'run_scope', 'owner_mandate_ref_sha256')}
    assert RUN_POLICY['paused'] is False and POLICY['paused'] is True
    assert stripped == {k: v for k, v in POLICY.items() if k not in ('paused', 'paused_note')}


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
