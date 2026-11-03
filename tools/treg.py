#!/usr/bin/env python3
"""T-REG: shared task registry, protocol and guards for RUGGER 01/02/03 (+ RUGGER 04 inbox).

Offline and stdlib-only. This module never pushes, comments, sends a message,
fires a trigger or calls a provider. Agents read GitHub issues and comments with
their own tools, save a JSON snapshot, and use this module to validate the
event log and to compute the single next action they are allowed to take.

The registry is event-sourced: every task is the replay of its append-only
event log (one GitHub issue comment per event). Each event carries a sequence
number, the digest of the previous event, a hop counter and its own digest,
so duplicates, races and tampering are detected deterministically.

Trust boundary: all agents write to GitHub under the owner's identity, so the
registry cannot prove who authored an event. Authorization comes only from the
owner's chat in each session (recorded as data here). Pausing is safe to forge,
unpausing is not.
"""
import argparse
import copy
import fnmatch
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone

SCHEMA_EVENT = 'rugger-treg-event-v1'
SCHEMA_POLICY = 'rugger-treg-policy-v1'
SCHEMA_SNAPSHOT = 'rugger-treg-snapshot-v1'
AGENTS = ('R01', 'R02', 'R03')
OWNER = 'OWNER'
KINDS = ('data_handoff', 'implement', 'report')
STATUSES = ('authorized', 'claimed', 'in_progress', 'submitted', 'in_review',
            'changes_requested', 'done', 'blocked', 'cancelled')
LEASED = ('claimed', 'in_progress', 'in_review')
TYPES = ('create', 'transition', 'heartbeat', 'wake', 'link')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
TASK_ID = re.compile(r'T-\d{4}\Z')
EVENT_MARKER = '<!-- treg-event v1 -->'


class TregError(ValueError):
    """A refused event or command. The message is a stable machine-readable code."""


# --------------------------------------------------------------------------- utils
def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def parse_utc(text):
    if type(text) is not str or not text.endswith('Z'):
        raise TregError('utc_must_be_iso_z')
    try:
        return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        raise TregError('utc_must_be_iso_z') from None


def fmt_utc(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def event_digest(event):
    return digest({k: v for k, v in event.items() if k != 'digest'})


# -------------------------------------------------------------------------- policy
def validate_policy(policy):
    if type(policy) is not dict or policy.get('schema') != SCHEMA_POLICY:
        raise TregError('policy_schema')
    for agent in AGENTS:
        spec = policy['agents'].get(agent)
        if type(spec) is not dict:
            raise TregError('policy_agent_missing:' + agent)
        for key in ('events_per_hour', 'wakes_per_day', 'max_concurrent_claims'):
            if type(spec.get(key)) is not int or spec[key] < 1:
                raise TregError('policy_quota_invalid:%s:%s' % (agent, key))
        if not spec.get('push_branches'):
            raise TregError('policy_push_branches_missing:' + agent)
    return policy


def check_branch(policy, agent, branch, *, scopes=()):
    """Return (allowed, reason) for a push by `agent` to `branch`. Advisory: GitHub cannot enforce it."""
    if agent not in AGENTS:
        return False, 'unknown_agent'
    for rule in policy.get('protected_branches', ()):
        if fnmatch.fnmatchcase(branch, rule['pattern']):
            for grant in rule.get('push', ()):
                if grant['agent'] == agent and grant['scope'] in scopes:
                    return True, 'protected_branch_with_owner_scope:' + grant['scope']
            return False, 'protected_branch'
    for pattern in policy['agents'][agent]['push_branches']:
        if fnmatch.fnmatchcase(branch, pattern):
            return True, 'agent_branch'
    return False, 'branch_not_allowed_for_agent'


def check_action(policy, agent, action):
    if action in policy.get('forbidden_actions_all', ()):
        return False, 'forbidden_for_all_agents'
    if action in policy.get('forbidden_actions_by_agent', {}).get(agent, ()):
        return False, 'forbidden_for_agent'
    return True, 'allowed'


# --------------------------------------------------------------------------- state
def empty_state():
    return {'tasks': {}, 'log': {}, 'event_ids': {}, 'inbox': [], 'by_agent': {a: [] for a in AGENTS + (OWNER,)},
            'wake_due': [], 'wakes': []}


def _deps_done(state, task):
    return all(state['tasks'].get(dep, {}).get('status') == 'done' for dep in task['depends_on'])


def _lease_valid(task, at):
    lease = task.get('lease')
    return lease is not None and parse_utc(lease['until']) > at


def _claims_held(state, agent, at):
    return sum(1 for t in state['tasks'].values()
               if t['status'] in LEASED and t.get('lease') and t['lease']['agent'] == agent and _lease_valid(t, at))


def _transition_allowed(task, frm, to, agent):
    if to == 'blocked':
        return agent in AGENTS + (OWNER,) and frm not in ('done', 'cancelled', 'blocked')
    if to == 'cancelled' or frm == 'blocked':
        return agent == OWNER and to in ('cancelled', 'authorized')
    assignee, reviewer = task['assignee'], task.get('reviewer')
    rules = {
        ('authorized', 'claimed'): {assignee},
        ('claimed', 'in_progress'): {assignee},
        ('claimed', 'authorized'): {assignee},
        ('in_progress', 'authorized'): {assignee},
        ('in_progress', 'submitted'): {assignee},
        ('changes_requested', 'in_progress'): {assignee},
    }
    if task['kind'] == 'implement':
        rules[('submitted', 'in_review')] = {reviewer}
        rules[('in_review', 'done')] = {reviewer}
        rules[('in_review', 'changes_requested')] = {reviewer}
    else:
        rules[('submitted', 'done')] = {assignee}
    return agent in rules.get((frm, to), set())


def _validate_new_task(task, policy):
    keys = {'task_id', 'kind', 'title', 'assignee', 'reviewer', 'depends_on', 'authorization', 'branch', 'downstream'}
    if type(task) is not dict or set(task) - keys or not {'task_id', 'kind', 'title', 'assignee',
                                                          'depends_on', 'authorization'} <= set(task):
        raise TregError('task_fields')
    if not TASK_ID.match(task['task_id']) or task['kind'] not in KINDS or task['assignee'] not in AGENTS:
        raise TregError('task_identity')
    if task['kind'] == 'implement':
        if task.get('reviewer') not in AGENTS or task['reviewer'] == task['assignee']:
            raise TregError('implement_requires_independent_reviewer')
        ok, reason = check_branch(policy, task['assignee'], task.get('branch') or '')
        if not ok:
            raise TregError('task_branch_refused:' + reason)
    _validate_downstream(task.get('downstream', []), task['task_id'])
    auth = task['authorization']
    if (type(auth) is not dict or auth.get('channel') != 'owner_chat'
            or not HEX64.match(str(auth.get('quote_sha256', ''))) or not auth.get('scope')):
        raise TregError('owner_chat_authorization_required')


def _validate_downstream(entries, own_id):
    """Forward links: who must be woken when this task is done (works on a partial snapshot)."""
    if type(entries) is not list:
        raise TregError('downstream_must_be_list')
    for entry in entries:
        if (type(entry) is not dict or set(entry) != {'task_id', 'agent'} or not TASK_ID.match(str(entry['task_id']))
                or entry['task_id'] == own_id or entry['agent'] not in AGENTS):
            raise TregError('downstream_entry_invalid')


def missing_references(state):
    """Upstream tasks (depends_on) absent from the snapshot. A valid view holds every task it
    touches plus their transitive upstream; downstream tasks are not needed (forward links)."""
    refs = set()
    for task in state['tasks'].values():
        refs.update(task['depends_on'])
    return sorted(refs - set(state['tasks']))


def _check_evidence(task, payload, policy):
    kind = task['kind']
    if kind == 'data_handoff':
        data = payload.get('dataset') or {}
        if (not HEX64.match(str(data.get('sha256', ''))) or not HEX40.match(str(data.get('commit', '')))
                or type(data.get('rows')) is not int or data['rows'] < 1
                or (payload.get('validation') or {}).get('status') != 'PASS'):
            raise TregError('data_handoff_requires_sha256_commit_rows_and_validation_pass')
    elif kind == 'implement':
        tests = payload.get('tests') or {}
        if (not HEX40.match(str(payload.get('commit', ''))) or payload.get('branch') != task.get('branch')
                or type(tests.get('passed')) is not int or tests.get('failed') != 0
                or payload.get('input_sha256') is None):
            raise TregError('implement_requires_commit_branch_green_tests_and_input_digest')
        ok, reason = check_branch(policy, task['assignee'], payload['branch'])
        if not ok:
            raise TregError('submitted_branch_refused:' + reason)
    elif kind == 'report':
        if not (payload.get('inbox') or {}).get('summary') or not payload['inbox'].get('task_refs'):
            raise TregError('report_requires_inbox_summary_and_task_refs')


def _quota(state, policy, agent, at, kind):
    if agent == OWNER:
        return
    spec = policy['agents'][agent]
    mine = state['by_agent'][agent]
    if sum(1 for e in mine if parse_utc(e['utc']) > at - timedelta(hours=1)) >= spec['events_per_hour']:
        raise TregError('quota_events_per_hour')
    # Rolling 24 hours (not the calendar day): 24 wakes cannot be doubled across midnight.
    if kind == 'wake' and sum(1 for e in mine if e['type'] == 'wake'
                              and parse_utc(e['utc']) > at - timedelta(hours=24)) >= spec['wakes_per_day']:
        raise TregError('quota_wakes_per_day')


def apply_event(state, event, policy):
    """Return (new_state, applied: bool). Raise TregError when the event must be refused."""
    validate_policy(policy)
    required = {'schema', 'event_id', 'task_id', 'seq', 'prev_digest', 'from_agent', 'type', 'hop', 'utc', 'payload', 'digest'}
    if type(event) is not dict or set(event) != required or event['schema'] != SCHEMA_EVENT:
        raise TregError('event_fields')
    if event['type'] not in TYPES or event['from_agent'] not in AGENTS + (OWNER,):
        raise TregError('event_type_or_agent')
    if event_digest(event) != event['digest']:
        raise TregError('event_digest_mismatch')
    at = parse_utc(event['utc'])
    known = state['event_ids'].get(event['event_id'])
    if known is not None:
        if known == event['digest']:
            return state, False  # idempotent replay of the same event
        raise TregError('event_id_conflict')
    paused = policy.get('paused', False)
    if paused and event['from_agent'] != OWNER and not (
            event['type'] == 'transition' and event['payload'].get('status_to') == 'blocked'):
        raise TregError('registry_paused')
    new = copy.deepcopy(state)
    log = new['log'].setdefault(event['task_id'], [])
    last = log[-1] if log else None
    if event['seq'] != len(log) + 1 or event['prev_digest'] != (last['digest'] if last else None):
        raise TregError('sequence_or_chain_conflict')
    expected_hop = 0 if last is None else last['hop'] + (event['from_agent'] != last['from_agent'])
    if event['hop'] != expected_hop:
        raise TregError('hop_counter_mismatch')
    _quota(new, policy, event['from_agent'], at, event['type'])
    payload = event['payload']

    if event['type'] == 'create':
        if last is not None or event['from_agent'] != OWNER or event['task_id'] in new['tasks']:
            raise TregError('create_must_be_first_owner_event')
        task = copy.deepcopy(payload.get('task'))
        _validate_new_task(task, policy)
        if task['task_id'] != event['task_id']:
            raise TregError('task_id_mismatch')
        task.update(status='authorized', lease=None, evidence={}, transitions=0,
                    max_hops=policy['defaults']['max_hops'], max_transitions=policy['defaults']['max_transitions'])
        task.setdefault('reviewer', None)
        task.setdefault('downstream', [])
        new['tasks'][task['task_id']] = task
    else:
        task = new['tasks'].get(event['task_id'])
        if task is None:
            raise TregError('unknown_task')
        if event['hop'] > task['max_hops']:
            raise TregError('hop_limit_exceeded')
        agent = event['from_agent']
        if task['status'] in LEASED and task['lease'] and task['lease']['agent'] != agent and agent != OWNER:
            if not (event['type'] == 'transition' and payload.get('status_to') == 'blocked'):
                raise TregError('task_leased_by_' + task['lease']['agent'])
        if event['type'] == 'link':
            if agent != OWNER or task['status'] == 'cancelled' or set(payload) - {'downstream', 'recorded_by', 'note'}:
                raise TregError('link_requires_owner_event_on_live_task')
            entries = payload.get('downstream')
            _validate_downstream(entries, task['task_id'])
            if not entries:
                raise TregError('link_requires_downstream_entries')
            known = {e['task_id'] for e in task['downstream']}
            task['downstream'] += [copy.deepcopy(e) for e in entries if e['task_id'] not in known]
        elif event['type'] == 'heartbeat':
            if task['status'] not in LEASED or not task['lease'] or task['lease']['agent'] != agent:
                raise TregError('heartbeat_requires_own_lease')
            task['lease']['until'] = fmt_utc(at + timedelta(minutes=policy['defaults']['lease_ttl_minutes']))
        elif event['type'] == 'wake':
            target, pointer = payload.get('to'), payload.get('pointer')
            if (set(payload) != {'to', 'pointer'} or target not in AGENTS or target == agent
                    or type(pointer) is not dict or set(pointer) != {'task_id', 'event_id'}):
                raise TregError('wake_requires_peer_target_and_pointer_only')
            if pointer['task_id'] != event['task_id'] or pointer['event_id'] not in {e['event_id'] for e in log}:
                raise TregError('wake_pointer_unknown')
            if any(e['type'] == 'wake' and e['payload']['to'] == target and e['payload']['pointer'] == pointer
                   for e in log):
                raise TregError('duplicate_wake')  # a re-send reuses the journaled wake, never a new one
            due = [d for d in new['wake_due'] if (d['task_id'], d['from'], d['to'], d['pointer_event_id'])
                   == (event['task_id'], agent, target, pointer['event_id'])]
            for entry in due:
                new['wake_due'].remove(entry)
            new['wakes'].append({'event_id': event['event_id'], 'task_id': event['task_id'], 'from': agent,
                                 'to': target, 'pointer_event_id': pointer['event_id'], 'utc': event['utc'],
                                 'required': bool(due)})
        else:
            to = payload.get('status_to')
            if to not in STATUSES:
                raise TregError('unknown_status')
            if task['transitions'] + 1 > task['max_transitions']:
                raise TregError('transition_limit_exceeded')
            frm = task['status']
            if not _transition_allowed(task, frm, to, agent):
                raise TregError('transition_refused:%s->%s:%s' % (frm, to, agent))
            ttl = timedelta(minutes=policy['defaults']['lease_ttl_minutes'])
            if to == 'claimed':
                if not _deps_done(new, task):
                    raise TregError('dependencies_not_done')
                if _claims_held(new, agent, at) >= policy['agents'][agent]['max_concurrent_claims']:
                    raise TregError('concurrent_claim_limit')
                task['lease'] = {'agent': agent, 'until': fmt_utc(at + ttl)}
            elif to == 'in_review':
                if _claims_held(new, agent, at) >= policy['agents'][agent]['max_concurrent_claims']:
                    raise TregError('concurrent_claim_limit')
                task['lease'] = {'agent': agent, 'until': fmt_utc(at + ttl)}
            elif to == 'submitted':
                _check_evidence(task, payload, policy)
                task['evidence']['submitted'] = copy.deepcopy(payload)
                task['lease'] = None
            elif to == 'done' and task['kind'] == 'implement':
                audit = payload.get('audit') or {}
                if audit.get('verdict') != 'PASS' or audit.get('audited_commit') != task['evidence']['submitted']['commit']:
                    raise TregError('done_requires_pass_audit_of_submitted_commit')
                task['evidence']['audit'] = copy.deepcopy(audit)
                task['lease'] = None
            elif to == 'done':
                task['lease'] = None
                if task['kind'] == 'report':
                    new['inbox'].append(copy.deepcopy(task['evidence']['submitted']['inbox']))
            elif to == 'changes_requested':
                if not payload.get('findings'):
                    raise TregError('changes_requested_requires_findings')
                task['evidence']['findings'] = copy.deepcopy(payload['findings'])
                task['lease'] = None
            elif to in ('authorized', 'blocked', 'cancelled'):
                task['lease'] = None
                if to == 'blocked':
                    task['evidence']['blocked_reason'] = payload.get('reason') or 'unspecified'
            task['status'] = to
            task['transitions'] += 1
            # Every peer this transition must wake becomes a journaling obligation until its `wake` event.
            for target in wake_targets(new, event):
                new['wake_due'].append({'task_id': event['task_id'], 'from': agent, 'to': target['to'],
                                        'pointer_event_id': event['event_id'], 'utc': event['utc'],
                                        'reason': to})
    log.append(copy.deepcopy(event))
    new['event_ids'][event['event_id']] = event['digest']
    new['by_agent'][event['from_agent']].append({'utc': event['utc'], 'type': event['type']})
    return new, True


def replay(events, policy):
    state = empty_state()
    for event in events:
        state, _ = apply_event(state, event, policy)
    return state


# ----------------------------------------------------------------- event authoring
def make_event(state, *, task_id, from_agent, type, utc, payload):
    log = state['log'].get(task_id, [])
    last = log[-1] if log else None
    event = dict(schema=SCHEMA_EVENT, task_id=task_id, seq=len(log) + 1,
                 prev_digest=last['digest'] if last else None, from_agent=from_agent, type=type,
                 hop=0 if last is None else last['hop'] + (from_agent != last['from_agent']),
                 utc=utc, payload=payload)
    event['event_id'] = '%s-%s-%04d' % (task_id, from_agent, event['seq'])
    event['digest'] = event_digest(event)
    return event


def render_comment(event):
    """GitHub issue comment body for one event (data only, never instructions)."""
    return EVENT_MARKER + '\n```json\n' + json.dumps(event, sort_keys=True, indent=1, ensure_ascii=False) + '\n```\n'


def parse_comments(bodies):
    events = []
    for body in bodies:
        if type(body) is str and body.startswith(EVENT_MARKER):
            match = re.search(r'```json\n(.*?)\n```', body, re.S)
            if match:
                events.append(json.loads(match.group(1)))
    return events


def order_events(events):
    """Global replay order: declared UTC, then task and sequence (per-task order is preserved)."""
    return sorted(events, key=lambda e: (e['utc'], e['task_id'], e['seq']))


def ingest(comment_lists):
    """Snapshot from GitHub issue comments (lists of dicts with 'body', or raw bodies)."""
    bodies = []
    for item in comment_lists:
        for comment in (item if isinstance(item, list) else [item]):
            bodies.append(comment.get('body') if isinstance(comment, dict) else comment)
    return {'schema': SCHEMA_SNAPSHOT, 'events': order_events(parse_comments(bodies))}


HEADS_MARKER = '<!-- treg-heads v1 -->'


def heads(state, *, generated_utc):
    """Verifiable summary of the registry: last event of each task and one global digest.

    Anyone (RUGGER 04 included) can compare each task's head digest with the last
    `treg-event` comment of its issue, and recompute `registry_digest`.
    """
    per_task = {}
    for task_id in sorted(state['log']):
        last = state['log'][task_id][-1]
        per_task[task_id] = {'seq': last['seq'], 'event_id': last['event_id'], 'digest': last['digest'],
                             'utc': last['utc'], 'status': state['tasks'][task_id]['status']}
    utcs = [h['utc'] for h in per_task.values()]
    return {'schema': 'rugger-treg-heads-v1', 'generated_utc': generated_utc, 'tasks': per_task,
            'events': sum(len(v) for v in state['log'].values()), 'last_event_utc': max(utcs) if utcs else None,
            'registry_digest': digest({k: v['digest'] for k, v in per_task.items()})}


def verify_heads(published, state, *, now, max_age_minutes=60):
    """Compare a published heads block with a freshly replayed snapshot."""
    problems = []
    current = heads(state, generated_utc=now)
    if published.get('schema') != 'rugger-treg-heads-v1':
        problems.append('heads_schema')
    if published.get('registry_digest') != digest({k: v['digest'] for k, v in published.get('tasks', {}).items()}):
        problems.append('published_registry_digest_inconsistent')
    for task_id in sorted(set(current['tasks']) | set(published.get('tasks', {}))):
        mine, theirs = current['tasks'].get(task_id), published.get('tasks', {}).get(task_id)
        if theirs is None:
            problems.append('task_missing_from_published:' + task_id)
        elif mine is None:
            problems.append('task_unknown_in_registry:' + task_id)
        elif mine['digest'] != theirs['digest']:
            problems.append('stale_or_diverged:%s:published_seq=%s:registry_seq=%s' % (task_id, theirs['seq'], mine['seq']))
    age = (parse_utc(now) - parse_utc(published.get('generated_utc', now))).total_seconds() / 60
    fresh = 0 <= age <= max_age_minutes
    if not fresh:
        problems.append('published_heads_age_minutes:%d' % age)
    return {'consistent': not [p for p in problems if not p.startswith('published_heads_age')], 'fresh': fresh,
            'problems': problems, 'registry_digest': current['registry_digest']}


def find_heads(inbox_comments):
    """Latest `treg-heads` block among inbox comments (MCP dicts or raw bodies) -> (heads, reference)."""
    found = None
    for comment in inbox_comments:
        body = comment.get('body') if isinstance(comment, dict) else comment
        if type(body) is str and HEADS_MARKER in body:
            match = re.search(re.escape(HEADS_MARKER) + r'\s*```json\n(.*?)\n```', body, re.S)
            if match:
                ref = (comment.get('html_url') or comment.get('id')) if isinstance(comment, dict) else None
                found = (json.loads(match.group(1)), ref)
    return found if found else (None, None)


def r04_verify(registry_comment_lists, inbox_comments, policy, *, now, max_age_minutes=60):
    """What RUGGER 04 runs after reading GitHub itself: inbox heads vs a full replay of the registry.

    Read-only: the replay ignores the write-time pause (a reader never writes). Verdicts:
    CURRENT (heads match the registry and are recent), CURRENT_IDLE (match, older than
    `max_age_minutes`, no event since), DIVERGED (registry changed or heads incomplete),
    NO_HEADS (no heads block in the inbox).
    """
    published, ref = find_heads(inbox_comments)
    snapshot = ingest(registry_comment_lists)
    state = replay(snapshot['events'], dict(policy, paused=False))
    current = heads(state, generated_utc=now)
    missing = pending_wakes(state)
    if published is None:
        result = {'verdict': 'NO_HEADS', 'problems': ['no_heads_block_in_inbox']}
    else:
        check = verify_heads(published, state, now=now, max_age_minutes=max_age_minutes)
        verdict = 'DIVERGED' if not check['consistent'] else ('CURRENT' if check['fresh'] else 'CURRENT_IDLE')
        result = {'verdict': verdict, 'problems': check['problems'], 'heads_generated_utc': published.get('generated_utc')}
    result.update(heads_comment=ref, registry_digest=current['registry_digest'], events=current['events'],
                  tasks={k: v['status'] for k, v in sorted(state['tasks'].items())},
                  inbox_reports=len(state['inbox']), wakes_not_journaled=len(missing),
                  wakes_not_journaled_useful=sum(1 for m in missing if m['useful']))
    result['line'] = ('RUGGER04-VERIFY | utc=%s | heads_comment=%s | registry_digest=%s | events=%d | tasks=%d | '
                      'wakes_not_journaled=%d | verdict=%s' % (now, ref, current['registry_digest'], current['events'],
                                                               len(state['tasks']), len(missing), result['verdict']))
    return result


def render_dashboard(state, *, generated_utc, policy=None):
    """Markdown dashboard for RUGGER 04, derived only from the replayed event log."""
    lines = ['# RUGGER 04 — tableau de bord T-REG', '',
             'Généré %s à partir du journal rejoué et validé (`tools/treg.py`).' % generated_utc, '',
             '| Tâche | Type | Agent | Relecteur | Statut | Dépend de | Événements | Preuve |',
             '|---|---|---|---|---|---|---|---|']
    for task_id in sorted(state['tasks']):
        task = state['tasks'][task_id]
        evidence = task['evidence']
        proof = []
        submitted = evidence.get('submitted') or {}
        if submitted.get('commit'):
            proof.append('commit `%s`' % submitted['commit'][:12])
        if (submitted.get('dataset') or {}).get('sha256'):
            proof.append('données `%s`' % submitted['dataset']['sha256'][:12])
        if evidence.get('audit'):
            proof.append('audit %s' % evidence['audit']['verdict'])
        if evidence.get('blocked_reason'):
            proof.append('bloqué : %s' % evidence['blocked_reason'])
        lines.append('| %s | %s | %s | %s | **%s** | %s | %d | %s |' % (
            task_id, task['kind'], task['assignee'], task.get('reviewer') or '—', task['status'],
            ', '.join(task['depends_on']) or '—', len(state['log'].get(task_id, [])), ' ; '.join(proof) or '—'))
    lines += ['', '## Rapports reçus', '']
    lines += ['- %s (tâches : %s)' % (entry['summary'], ', '.join(entry['task_refs'])) for entry in state['inbox']] or ['- aucun']
    lines += ['', '## Réveils entre agents', '']
    if policy is not None:
        lines += ['| Agent | Réveils journalisés (24 h glissantes) | Quota |', '|---|---|---|']
        for agent in AGENTS:
            quota = wake_quota(state, policy, agent, generated_utc)
            lines.append('| %s | %d | %d |' % (agent, quota['used_24h'], quota['limit']))
        lines.append('')
    lines.append('Réveils journalisés : %d (dont %d exigés par une transition).' % (
        len(state['wakes']), sum(1 for w in state['wakes'] if w['required'])))
    missing = pending_wakes(state)
    lines += ['', 'Réveils exigés mais **non journalisés** : %d' % len(missing)]
    lines += ['- %s : %s → %s après `%s` (%s) — %s' % (
        m['task_id'], m['from'], m['to'], m['pointer_event_id'], m['reason'],
        'encore utile : le planificateur de %s demande `journal_wake`' % m['from'] if m['useful']
        else 'historique : sans effet sur le travail restant') for m in missing]
    lines += ['', '## Vérification (têtes du registre)', '',
              'Chaque `digest` doit être celui du dernier commentaire `treg-event` de l\'issue de la tâche ; '
              '`registry_digest` = SHA-256 canonique de `{tâche: digest}`. Vérification complète : '
              '`tools/treg.py ingest` puis `tools/treg.py verify-heads`.', '',
              HEADS_MARKER, '```json', json.dumps(heads(state, generated_utc=generated_utc), indent=1, sort_keys=True), '```']
    return '\n'.join(lines) + '\n'


# ------------------------------------------------------------------------ planning
def next_action(state, policy, agent, now):
    """The single action `agent` may take now. Deterministic and idempotent."""
    if policy.get('paused', False):
        return {'action': 'stop', 'reason': 'registry_paused'}
    at = parse_utc(now)
    for due in pending_wakes(state):
        if due['from'] == agent and due['useful']:
            # A wake that was sent (or is about to be) without its journal entry comes first.
            return {'action': 'journal_wake', 'task_id': due['task_id'], 'to': due['to'],
                    'pointer': {'task_id': due['task_id'], 'event_id': due['pointer_event_id']}}
    tasks = [state['tasks'][k] for k in sorted(state['tasks'])]
    for task in tasks:
        lease = task.get('lease')
        if task['status'] in LEASED and lease and lease['agent'] == agent:
            if not _lease_valid(task, at):
                return {'action': 'heartbeat', 'task_id': task['task_id'], 'reason': 'resume_after_interruption'}
            step = {'claimed': 'start', 'in_progress': 'work', 'in_review': 'audit'}[task['status']]
            return {'action': step, 'task_id': task['task_id']}
    for task in tasks:
        if task['status'] == 'changes_requested' and task['assignee'] == agent:
            return {'action': 'resume_work', 'task_id': task['task_id']}
        if task['status'] == 'submitted' and task['kind'] == 'implement' and task.get('reviewer') == agent:
            return {'action': 'start_review', 'task_id': task['task_id']}
        if task['status'] == 'submitted' and task['kind'] in ('data_handoff', 'report') and task['assignee'] == agent:
            # The producer closes its own handoff/report once the evidence is published.
            return {'action': 'close', 'task_id': task['task_id']}
    for task in tasks:
        if (task['status'] == 'authorized' and task['assignee'] == agent and _deps_done(state, task)
                and _claims_held(state, agent, at) < policy['agents'][agent]['max_concurrent_claims']):
            return {'action': 'claim', 'task_id': task['task_id']}
    return {'action': 'wait', 'reason': 'nothing_actionable'}


def wake_targets(state, event):
    """Peers to notify after `event`: pointers only, never instructions."""
    if event['type'] != 'transition':
        return []
    task = state['tasks'][event['task_id']]
    to = event['payload']['status_to']
    pointer = {'task_id': task['task_id'], 'event_id': event['event_id']}
    targets = []
    if to == 'submitted' and task['kind'] == 'implement':
        targets.append(task['reviewer'])
    elif to == 'changes_requested':
        targets.append(task['assignee'])
    elif to == 'done':
        # Declared forward links first: they work even when the snapshot holds only this task.
        for entry in task.get('downstream', []):
            other = state['tasks'].get(entry['task_id'])
            if other is None or other['status'] == 'authorized':
                targets.append(other['assignee'] if other else entry['agent'])
        for other in sorted(state['tasks'].values(), key=lambda t: t['task_id']):
            if task['task_id'] in other['depends_on'] and other['status'] == 'authorized':
                targets.append(other['assignee'])
    return [{'to': t, 'pointer': pointer} for t in dict.fromkeys(targets) if t != event['from_agent']]


def _wake_still_useful(state, due):
    """True while the woken agent still has something to do because of this transition."""
    task = state['tasks'].get(due['task_id'])
    if task is None:
        return False
    if due['reason'] == 'submitted':
        return task['status'] == 'submitted' and task.get('reviewer') == due['to']
    if due['reason'] == 'changes_requested':
        return task['status'] == 'changes_requested' and task['assignee'] == due['to']
    linked = {e['task_id'] for e in task.get('downstream', [])}
    for other in state['tasks'].values():
        if (other['assignee'] == due['to'] and other['status'] == 'authorized'
                and (other['task_id'] in linked or due['task_id'] in other['depends_on'])):
            return True
    return False


def pending_wakes(state):
    """Wakes a transition required but nobody journaled. `useful` = the target still has work from it."""
    return [dict(due, useful=_wake_still_useful(state, due)) for due in state['wake_due']]


def wake_quota(state, policy, agent, now):
    at = parse_utc(now)
    used = sum(1 for e in state['by_agent'][agent] if e['type'] == 'wake'
               and parse_utc(e['utc']) > at - timedelta(hours=24))
    return {'agent': agent, 'used_24h': used, 'limit': policy['agents'][agent]['wakes_per_day']}


def journal_wakes(state, policy, event, utc):
    """Build and validate the `wake` events that must follow `event`; return (state, items).

    Each item holds the wake event and the exact message to send. The message points at the
    journaled wake event itself, so a receiver can check that the wake is in the registry and
    counted in the sender's quota. Protocol: publish the wake event first, send second; a
    failed send is retried with the same message, never with a new wake event.
    """
    items = []
    for wake in wake_targets(state, event):
        wake_event = make_event(state, task_id=event['task_id'], from_agent=event['from_agent'], type='wake',
                                utc=utc, payload=wake)
        state, _ = apply_event(state, wake_event, policy)
        items.append({'event': wake_event, 'send': {
            'session_id': policy['agents'][wake['to']]['session_id'],
            'message': json.dumps({'treg_pointer': {'task_id': wake_event['task_id'],
                                                    'event_id': wake_event['event_id']}}, sort_keys=True)}})
    return state, items


def accept_pointer(state, policy, agent, pointer, *, sender_session=None):
    """Receiver-side check of a `treg_pointer`: act only on a wake journaled in the registry.

    Accepted: the pointer names a `wake` event addressed to `agent` (current protocol), or a
    transition followed by such a journaled wake (earlier protocol). Refused otherwise, in
    particular `unjournaled_wake`: the sender skipped the registry, so the wake is not counted in
    its quota and the receiver does not act on it. `sender_session` is the platform-provided
    session of the message; when given it must belong to the agent that journaled the wake.
    """
    if type(pointer) is not dict or set(pointer) != {'task_id', 'event_id'}:
        return {'accept': False, 'reason': 'pointer_format'}
    log = state['log'].get(pointer['task_id'], [])
    named = [e for e in log if e['event_id'] == pointer['event_id']]
    if not named:
        return {'accept': False, 'reason': 'pointer_unknown_event'}
    if named[0]['type'] == 'wake':
        wakes = named
    else:
        wakes = [e for e in log if e['type'] == 'wake' and e['payload']['pointer']['event_id'] == pointer['event_id']]
    wakes = [e for e in wakes if e['payload']['to'] == agent]
    if not wakes:
        return {'accept': False, 'reason': 'wake_not_addressed_to_agent' if named[0]['type'] == 'wake'
                else 'unjournaled_wake'}
    wake = wakes[0]
    if sender_session is not None:
        expected = policy['agents'][wake['from_agent']]['session_id']
        if sender_session != expected:
            return {'accept': False, 'reason': 'wake_sender_mismatch', 'wake_event_id': wake['event_id']}
    return {'accept': True, 'wake_event_id': wake['event_id'], 'from_agent': wake['from_agent'],
            'note': 'run plan: the registry, not the message, decides the action; duplicates are no-ops'}


# ------------------------------------------------------------------------ scenario
def simulate_scenario(policy, *, start='2026-11-04T08:00:00Z'):
    """RUGGER 03 hands validated data -> RUGGER 01 implements -> RUGGER 02 audits -> RUGGER 04 inbox.

    Returns (state, operations). Operations are the GitHub/Cloud calls an
    activated deployment would make; nothing is executed here.
    """
    policy = copy.deepcopy(policy)
    policy['paused'] = False  # simulation only; the shipped policy stays paused
    clock = parse_utc(start)
    state, ops = empty_state(), []
    quote = hashlib.sha256(b'owner chat: authorize T-REG scenario S-001').hexdigest()
    auth = {'channel': 'owner_chat', 'quote_sha256': quote, 'scope': 'treg-scenario-S-001'}
    data_sha = hashlib.sha256(b'synthetic dataset for S-001').hexdigest()

    def emit(task_id, agent, kind, payload):
        nonlocal state, clock
        clock += timedelta(minutes=5)
        event = make_event(state, task_id=task_id, from_agent=agent, type=kind, utc=fmt_utc(clock), payload=payload)
        state, _ = apply_event(state, event, policy)
        ops.append({'tool': 'mcp__github__add_issue_comment', 'issue': 'registry:' + task_id,
                    'by': agent, 'body_sha256': hashlib.sha256(render_comment(event).encode()).hexdigest()})
        state, items = journal_wakes(state, policy, event, fmt_utc(clock))
        for item in items:  # journal first, then send a pointer to the journaled wake
            ops.append({'tool': 'mcp__github__add_issue_comment', 'issue': 'registry:' + task_id, 'by': agent,
                        'body_sha256': hashlib.sha256(render_comment(item['event']).encode()).hexdigest()})
            ops.append({'tool': 'mcp__claude-code-remote__send_message', 'by': agent, **item['send']})
            receiver = item['event']['payload']['to']
            check = accept_pointer(state, policy, receiver, json.loads(item['send']['message'])['treg_pointer'],
                                   sender_session=policy['agents'][agent]['session_id'])
            if not check['accept']:
                raise TregError('simulation_wake_refused:' + check['reason'])
        return event

    for task in ({'task_id': 'T-0001', 'kind': 'data_handoff', 'title': 'S-001 validated dataset',
                  'assignee': 'R03', 'depends_on': [], 'authorization': auth,
                  'downstream': [{'task_id': 'T-0002', 'agent': 'R01'}]},
                 {'task_id': 'T-0002', 'kind': 'implement', 'title': 'S-001 process dataset',
                  'assignee': 'R01', 'reviewer': 'R02', 'depends_on': ['T-0001'],
                  'branch': 'claude/r01-t0002-s001', 'authorization': auth,
                  'downstream': [{'task_id': 'T-0003', 'agent': 'R01'}]},
                 {'task_id': 'T-0003', 'kind': 'report', 'title': 'S-001 result to RUGGER 04',
                  'assignee': 'R01', 'depends_on': ['T-0002'], 'authorization': auth}):
        emit(task['task_id'], OWNER, 'create', {'task': task})
    emit('T-0001', 'R03', 'transition', {'status_to': 'claimed'})
    emit('T-0001', 'R03', 'transition', {'status_to': 'in_progress'})
    emit('T-0001', 'R03', 'transition', {'status_to': 'submitted', 'dataset': {
        'path': 'validation/s001.json', 'sha256': data_sha, 'commit': 'a' * 40, 'rows': 3},
        'validation': {'status': 'PASS', 'checks': ['schema', 'sha256', 'no_lookahead']}})
    emit('T-0001', 'R03', 'transition', {'status_to': 'done'})
    emit('T-0002', 'R01', 'transition', {'status_to': 'claimed'})
    emit('T-0002', 'R01', 'transition', {'status_to': 'in_progress'})
    emit('T-0002', 'R01', 'heartbeat', {})
    emit('T-0002', 'R01', 'transition', {'status_to': 'submitted', 'commit': 'b' * 40,
                                         'branch': 'claude/r01-t0002-s001', 'input_sha256': data_sha,
                                         'tests': {'passed': 12, 'failed': 0}})
    emit('T-0002', 'R02', 'transition', {'status_to': 'in_review'})
    emit('T-0002', 'R02', 'transition', {'status_to': 'done', 'audit': {
        'verdict': 'PASS', 'audited_commit': 'b' * 40, 'findings': []}})
    emit('T-0003', 'R01', 'transition', {'status_to': 'claimed'})
    emit('T-0003', 'R01', 'transition', {'status_to': 'in_progress'})
    emit('T-0003', 'R01', 'transition', {'status_to': 'submitted', 'inbox': {
        'summary': 'S-001: dataset %s processed at %s, audit PASS by R02' % (data_sha[:12], 'b' * 12),
        'task_refs': ['T-0001', 'T-0002'], 'audit_verdict': 'PASS'}})
    emit('T-0003', 'R01', 'transition', {'status_to': 'done'})
    ops.append({'tool': 'mcp__github__add_issue_comment', 'issue': policy['r04']['inbox_title'],
                'by': 'R01', 'body_sha256': digest(state['inbox'][-1])})
    return state, ops


# ----------------------------------------------------------------------------- cli
def main(argv=None):
    parser = argparse.ArgumentParser(description='T-REG offline registry tool (no network).')
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ('validate', 'plan'):
        p = sub.add_parser(name)
        p.add_argument('snapshot')
        p.add_argument('--policy', required=True)
        if name == 'plan':
            p.add_argument('--agent', required=True, choices=AGENTS)
            p.add_argument('--now', required=True)
    p = sub.add_parser('check-branch')
    p.add_argument('--policy', required=True)
    p.add_argument('--agent', required=True)
    p.add_argument('--branch', required=True)
    p.add_argument('--scope', action='append', default=[])
    p = sub.add_parser('simulate')
    p.add_argument('--policy', required=True)
    p = sub.add_parser('ingest', help='build a snapshot from saved MCP issue comments')
    p.add_argument('comments', nargs='+')
    p.add_argument('--policy', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('emit', help='validate one new event and print the comment to post')
    p.add_argument('snapshot')
    p.add_argument('--policy', required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--agent', required=True, choices=AGENTS + (OWNER,))
    p.add_argument('--type', required=True, choices=TYPES)
    p.add_argument('--payload', required=True, help='JSON object')
    p.add_argument('--now', required=True)
    p = sub.add_parser('verify-heads', help='check a published heads block against the registry')
    p.add_argument('snapshot')
    p.add_argument('--policy', required=True)
    p.add_argument('--heads', required=True, help='JSON file, or a markdown file containing the treg-heads block')
    p.add_argument('--now', required=True)
    p.add_argument('--max-age-minutes', type=int, default=60)
    p = sub.add_parser('dashboard')
    p.add_argument('snapshot')
    p.add_argument('--policy', required=True)
    p.add_argument('--now', required=True)
    p = sub.add_parser('accept-pointer', help='receiver: act only on a wake journaled in the registry')
    p.add_argument('snapshot')
    p.add_argument('--policy', required=True)
    p.add_argument('--agent', required=True, choices=AGENTS)
    p.add_argument('--pointer', required=True, help='the treg_pointer object, or the whole message, as JSON')
    p.add_argument('--from-session', default=None, help='sender session id given by the platform')
    p = sub.add_parser('r04-verify', help='RUGGER 04: inbox heads vs a full replay of the registry')
    p.add_argument('--policy', required=True)
    p.add_argument('--registry', nargs='+', required=True, help='saved comments of every [T-REG] task issue')
    p.add_argument('--inbox', required=True, help='saved comments of the RUGGER04 inbox issue')
    p.add_argument('--now', required=True)
    p.add_argument('--max-age-minutes', type=int, default=60)
    args = parser.parse_args(argv)
    with open(args.policy, encoding='utf-8') as handle:
        policy = validate_policy(json.load(handle))
    if args.cmd == 'check-branch':
        ok, reason = check_branch(policy, args.agent, args.branch, scopes=tuple(args.scope))
        print(json.dumps({'allowed': ok, 'reason': reason}))
        return 0 if ok else 3
    if args.cmd == 'simulate':
        state, ops = simulate_scenario(policy)
        print(json.dumps({'statuses': {k: v['status'] for k, v in sorted(state['tasks'].items())},
                          'inbox': state['inbox'], 'operations_not_executed': ops}, indent=1, sort_keys=True))
        return 0
    if args.cmd == 'r04-verify':
        lists = []
        for path in args.registry:
            with open(path, encoding='utf-8') as handle:
                lists.append(json.load(handle))
        with open(args.inbox, encoding='utf-8') as handle:
            inbox = json.load(handle)
        result = r04_verify(lists, inbox if isinstance(inbox, list) else [inbox], policy, now=args.now,
                            max_age_minutes=args.max_age_minutes)
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0 if result['verdict'] in ('CURRENT', 'CURRENT_IDLE') else 4
    if args.cmd == 'ingest':
        loaded = []
        for path in args.comments:
            with open(path, encoding='utf-8') as handle:
                loaded.append(json.load(handle))
        snapshot = ingest(loaded)
        state = replay(snapshot['events'], policy)  # refuse to write an invalid snapshot
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump(snapshot, handle, indent=1, sort_keys=True)
        print(json.dumps({'events': len(snapshot['events']),
                          'tasks': {k: v['status'] for k, v in sorted(state['tasks'].items())}}, sort_keys=True))
        return 0
    with open(args.snapshot, encoding='utf-8') as handle:
        snapshot = json.load(handle)
    if snapshot.get('schema') != SCHEMA_SNAPSHOT:
        raise TregError('snapshot_schema')
    state = replay(snapshot['events'], policy)
    if args.cmd == 'emit':
        payload = json.loads(args.payload)
        if type(payload) is not dict:
            raise TregError('payload_must_be_object')
        event = make_event(state, task_id=args.task, from_agent=args.agent, type=args.type, utc=args.now, payload=payload)
        new_state, _ = apply_event(state, event, policy)
        targets = wake_targets(new_state, event)
        # Raises (nothing to post) when a required wake is refused, e.g. quota: block the task instead.
        _, wake_items = journal_wakes(new_state, policy, event, args.now)
        if event['type'] == 'wake':
            wake_items = [{'event': event, 'send': {
                'session_id': policy['agents'][payload['to']]['session_id'],
                'message': json.dumps({'treg_pointer': {'task_id': event['task_id'], 'event_id': event['event_id']}},
                                      sort_keys=True)}}]
        warnings = []
        if missing_references(new_state):
            warnings.append('partial_snapshot_missing:' + ','.join(missing_references(new_state)))
        task = new_state['tasks'][args.task]
        if (event['type'] == 'transition' and payload.get('status_to') == 'done' and task['kind'] != 'report'
                and not targets and not task.get('downstream')):
            warnings.append('done_without_downstream_nobody_notified')
        wake_events = [{'event': item['event'], 'comment_body': render_comment(item['event']), 'send': item['send']}
                       for item in wake_items if item['event'] is not event]
        print(json.dumps({'event': event, 'comment_body': render_comment(event), 'wake_targets': targets,
                          'wake_events': wake_events,
                          'send_after_posting': [item['send'] for item in wake_items],
                          'protocol': 'post comment_body, then each wake_events[].comment_body, then send; '
                                      'retry a failed send with the same message, never a new wake event',
                          'warnings': warnings}, indent=1, sort_keys=True, ensure_ascii=False))
        return 0
    if args.cmd == 'verify-heads':
        with open(args.heads, encoding='utf-8') as handle:
            text = handle.read()
        if HEADS_MARKER in text:
            text = re.search(re.escape(HEADS_MARKER) + r'\s*```json\n(.*?)\n```', text, re.S).group(1)
        result = verify_heads(json.loads(text), state, now=args.now, max_age_minutes=args.max_age_minutes)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['consistent'] and result['fresh'] else 4
    if args.cmd == 'dashboard':
        print(render_dashboard(state, generated_utc=args.now, policy=policy), end='')
        return 0
    if args.cmd == 'accept-pointer':
        pointer = json.loads(args.pointer)
        if isinstance(pointer, dict) and 'treg_pointer' in pointer:
            pointer = pointer['treg_pointer']
        result = accept_pointer(state, policy, args.agent, pointer, sender_session=args.from_session)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['accept'] else 4
    if args.cmd == 'validate':
        print(json.dumps({'tasks': {k: v['status'] for k, v in sorted(state['tasks'].items())},
                          'events': sum(len(v) for v in state['log'].values()),
                          'wakes_journaled': len(state['wakes']),
                          'wakes_not_journaled': pending_wakes(state)}, sort_keys=True))
        return 0
    print(json.dumps(next_action(state, policy, args.agent, args.now), sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except TregError as error:
        print(json.dumps({'refused': str(error)}))
        sys.exit(2)
