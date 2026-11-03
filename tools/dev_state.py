#!/usr/bin/env python3
"""Deterministic work planner for the autonomous development routine.

Each run performs at most one action, decided by code rather than by prose:

* RESUME a ``claude/dev-`` branch whose pull request asks for corrections
  (an owner comment starting with ``/fix``, a reviewer verdict containing
  CHANGES_REQUESTED, or a failed check on a head no agent has addressed), as
  long as it has used fewer than MAX_ROUNDS rounds. Corrections come first.
* START the first eligible backlog item: not claimed by any live dev branch,
  offline, not gated on the owner, and with target paths that do not overlap
  files already changed by an open dev branch.
* otherwise STOP and say why.

Git refs are the source of truth for claims and changed files. ``gh`` only adds
pull-request state and comments when it is available. The planner never writes
to GitHub and never merges. ``scope`` checks a branch against its item's target
paths before anything is pushed.

  python tools/dev_state.py fetch --out state.json      # reads git and gh
  python tools/dev_state.py plan state.json             # decides one action
  python tools/dev_state.py scope <item-id> --base origin/<coordination>
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG_PATH = ROOT / 'docs' / 'autonomy' / 'BACKLOG.json'
RUN_RECORD_DIR = 'docs/autonomy/runs'
DEV_PREFIX = 'claude/dev-'
DEV_RUN_PREFIX = 'claude/dev-run-'   # the routine's local workspace: never pushed, never planned
AGENT_PREFIX = '[dev-agent]'
ROUND_PREFIX = '[dev-agent] round'
REVIEW_PREFIX = '[automated review]'
MAX_ROUNDS = 3
TRAILER = re.compile(r'^Backlog:[ \t]*([a-z0-9][a-z0-9-]*)[ \t]*$', re.MULTILINE)
HEAD_MARK = re.compile(r'head=([0-9a-f]{40})')
ID_PATTERN = re.compile(r'[a-z0-9][a-z0-9-]*')


def load_backlog(path=BACKLOG_PATH):
    """Return (coordination_branch, items sorted by rank). Raises on a malformed file."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    items, ids = data['items'], set()
    for item in items:
        for key in ('id', 'rank', 'target_paths', 'offline', 'requires_owner', 'acceptance'):
            if key not in item:
                raise ValueError(f"backlog item {item.get('id', '?')} lacks {key}")
        if not ID_PATTERN.fullmatch(item['id']):
            raise ValueError(f"invalid backlog id {item['id']!r}")
        if item['id'] in ids:
            raise ValueError(f"duplicate backlog id {item['id']}")
        if not item['target_paths']:
            raise ValueError(f"backlog item {item['id']} has no target_paths")
        ids.add(item['id'])
    return data['coordination_branch'], sorted(items, key=lambda i: i['rank'])


def load_policy(path=BACKLOG_PATH):
    """Owner switch for new work. Missing, null or false means no new work (fail closed)."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return {'start_new_work': data.get('start_new_work') is True}


def normalize(path):
    return path.strip().strip('/')


def paths_overlap(a, b):
    """True when two repository paths are equal or one lies inside the other."""
    a, b = normalize(a), normalize(b)
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


def inside(path, allowed):
    """True when a changed file is the allowed path or lies inside it."""
    path, allowed = normalize(path), normalize(allowed)
    return path == allowed or path.startswith(allowed + '/')


def out_of_scope(changed_files, item):
    """Changed files that are neither a target path of the item nor its run record."""
    allowed = list(item['target_paths']) + [RUN_RECORD_DIR]
    return sorted(f for f in changed_files if not any(inside(f, a) for a in allowed))


def corrections_since_last_agent(comments):
    """Return (rounds_used, requests) from pull-request comments.

    A request is an owner comment starting with ``/fix`` or a reviewer comment
    containing CHANGES_REQUESTED, posted after the last agent comment.
    """
    ordered = sorted(comments, key=lambda c: c.get('createdAt', ''))
    bodies = [c.get('body', '').lstrip() for c in ordered]
    rounds = sum(1 for body in bodies if body.startswith(ROUND_PREFIX))
    last_agent = max((i for i, body in enumerate(bodies) if body.startswith(AGENT_PREFIX)),
                     default=-1)
    requests = []
    for comment, body in zip(ordered[last_agent + 1:], bodies[last_agent + 1:]):
        if body.startswith('/fix'):
            requests.append({'reason': 'owner_request', 'at': comment.get('createdAt', ''),
                             'excerpt': body[:200]})
        elif body.startswith(REVIEW_PREFIX) and 'CHANGES_REQUESTED' in body:
            requests.append({'reason': 'review_changes_requested',
                             'at': comment.get('createdAt', ''), 'excerpt': body[:200]})
    return rounds, requests


def ci_needs_fix(head, ci_state, comments):
    """A failed check on a head that no agent comment has addressed needs a correction."""
    if ci_state != 'FAILURE':
        return False
    addressed = {match.group(1) for c in comments
                 if c.get('body', '').lstrip().startswith(AGENT_PREFIX)
                 for match in HEAD_MARK.finditer(c.get('body', ''))}
    return head not in addressed


def plan(branches, items, max_rounds=MAX_ROUNDS, start_new_work=True):
    """Decide exactly one action from the branch facts and the ranked backlog.

    Corrections (RESUME) are always allowed. New work (START) only when the
    owner's switch start_new_work is true.
    """
    reasons = []
    open_branches = [b for b in branches if b['pr'] is None or b['pr']['state'] == 'OPEN']
    claimed = {i for b in branches
               if not (b['pr'] and b['pr']['state'] == 'CLOSED') for i in b['backlog_ids']}
    locked = sorted({f for b in open_branches for f in b['changed_files']})

    resumable = []
    for branch in sorted(open_branches, key=lambda b: (b['pr']['number'] if b['pr'] else 10**9,
                                                       b['name'])):
        if not branch['corrections']:
            continue
        if branch['rounds'] >= max_rounds:
            reasons.append(f"{branch['name']}: corrections requested after {branch['rounds']} "
                           f"rounds; needs owner decision")
            continue
        resumable.append(branch)
    if resumable:
        pick = resumable[0]
        return {'action': 'RESUME', 'branch': pick['name'],
                'pr': pick['pr']['number'] if pick['pr'] else None,
                'rounds': pick['rounds'], 'backlog_ids': pick['backlog_ids'],
                'requests': pick['corrections'], 'reasons': reasons, 'locked_paths': locked}

    if not start_new_work:
        return {'action': 'STOP', 'locked_paths': locked,
                'reasons': reasons + ['new work is disabled by the owner '
                                      '(start_new_work is not true in BACKLOG.json)']}
    eligible = []
    for item in sorted(items, key=lambda i: i['rank']):   # never rely on the caller's order
        if item['id'] in claimed:
            reasons.append(f"{item['id']}: already claimed by a dev branch")
        elif item['requires_owner']:
            reasons.append(f"{item['id']}: gated on an owner decision")
        elif not item['offline']:
            reasons.append(f"{item['id']}: needs network data, not offline")
        else:
            clash = sorted({f for p in item['target_paths'] for f in locked
                            if paths_overlap(p, f)})
            if clash:
                reasons.append(f"{item['id']}: overlaps open work on {clash}")
            else:
                eligible.append(item)
    if eligible:
        pick = eligible[0]
        return {'action': 'START', 'item': pick['id'], 'target_paths': pick['target_paths'],
                'locked_paths': locked, 'reasons': reasons}
    return {'action': 'STOP', 'locked_paths': locked,
            'reasons': reasons or ['no backlog item is defined']}


def _run(args):
    """Run git or gh in the caller's working directory: the dev branch checkout."""
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          encoding='utf-8').stdout


def _ci_state(rollup):
    states = [(c.get('conclusion') or c.get('state') or '').upper() for c in rollup]
    if any(s in ('FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE') for s in states):
        return 'FAILURE'
    if states and all(s in ('SUCCESS', 'SKIPPED', 'NEUTRAL') for s in states):
        return 'SUCCESS'
    return 'PENDING' if states else None


def _gh_pull_request(name):
    """Return (pr, comments, ci) from gh, or (None, [], None) when gh is unusable."""
    try:
        prs = json.loads(_run(['gh', 'pr', 'list', '--head', name, '--state', 'all',
                               '--json', 'number,state,isDraft,url']) or '[]')
        if not prs:
            return None, [], None
        pr = max(prs, key=lambda p: p['number'])
        detail = json.loads(_run(['gh', 'pr', 'view', str(pr['number']), '--json',
                                  'comments,statusCheckRollup']))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None, [], None
    comments = [{'author': (c.get('author') or {}).get('login', ''),
                 'body': c.get('body', ''), 'createdAt': c.get('createdAt', '')}
                for c in detail.get('comments', [])]
    return pr, comments, _ci_state(detail.get('statusCheckRollup') or [])


def fetch_state(coord, use_gh=True):
    """Collect the live dev-branch facts. Read-only: fetch, ls-remote, log, diff, gh view."""
    _run(['git', 'fetch', '-q', 'origin', coord])
    listing = _run(['git', 'ls-remote', '--heads', 'origin', DEV_PREFIX + '*'])
    names = sorted({line.split('\t', 1)[1][len('refs/heads/'):]
                    for line in listing.splitlines() if '\t' in line})
    names = [n for n in names if not n.startswith(DEV_RUN_PREFIX)]
    branches = []
    for name in names:
        _run(['git', 'fetch', '-q', 'origin', name])
        head = _run(['git', 'rev-parse', f'origin/{name}']).strip()
        changed = _run(['git', 'diff', '--name-only', f'origin/{coord}...origin/{name}']).split()
        messages = _run(['git', 'log', '--format=%B', f'origin/{coord}..origin/{name}'])
        pr, comments, ci = _gh_pull_request(name) if use_gh else (None, [], None)
        rounds, requests = corrections_since_last_agent(comments)
        if ci_needs_fix(head, ci, comments):
            requests.append({'reason': 'ci_failed', 'at': '',
                             'excerpt': f'failing check on {head[:7]}'})
        branches.append({'name': name, 'head': head, 'changed_files': changed,
                         'backlog_ids': sorted(set(TRAILER.findall(messages))), 'pr': pr,
                         'rounds': rounds, 'corrections': requests, 'ci': ci})
    return {'coordination_branch': coord, 'branches': branches}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('fetch', help='collect live dev-branch facts')
    fetch.add_argument('--coord', help='coordination branch (default: from BACKLOG.json)')
    fetch.add_argument('--out', required=True)
    fetch.add_argument('--no-gh', action='store_true', help='git-only view')
    decide = sub.add_parser('plan', help='decide one action from a fetched state file')
    decide.add_argument('state')
    decide.add_argument('--backlog', default=str(BACKLOG_PATH))
    check = sub.add_parser('scope', help='check changed files against an item scope')
    check.add_argument('item')
    check.add_argument('--base', required=True, help='e.g. origin/claude/launchlab-trade-events')
    check.add_argument('--backlog', default=str(BACKLOG_PATH))
    args = parser.parse_args(argv)

    if args.command == 'fetch':
        coord = args.coord or load_backlog(BACKLOG_PATH)[0]
        state = fetch_state(coord, use_gh=not args.no_gh)
        Path(args.out).write_text(json.dumps(state, indent=2, sort_keys=True), encoding='utf-8')
        print(json.dumps({'coordination_branch': coord, 'dev_branches': len(state['branches']),
                          'written': args.out}, sort_keys=True))
        return 0
    if args.command == 'plan':
        _, items = load_backlog(args.backlog)
        policy = load_policy(args.backlog)
        state = json.loads(Path(args.state).read_text(encoding='utf-8'))
        print(json.dumps(plan(state['branches'], items,
                              start_new_work=policy['start_new_work']),
                         indent=2, sort_keys=True))
        return 0
    _, items = load_backlog(args.backlog)
    matches = [i for i in items if i['id'] == args.item]
    if not matches:
        print(json.dumps({'ok': False, 'error': f'unknown item {args.item}'}))
        return 2
    changed = _run(['git', 'diff', '--name-only', f'{args.base}...HEAD']).split()
    extra = out_of_scope(changed, matches[0])
    print(json.dumps({'ok': not extra, 'item': args.item, 'changed': changed,
                      'out_of_scope': extra}, indent=2, sort_keys=True))
    return 0 if not extra else 3


if __name__ == '__main__':
    sys.exit(main())
