"""Masked secret-pattern scan of the whole git history (all fetched refs). Prints NO secret value:
only pattern name, commit (short), path and occurrence count; plus sha256 prefixes so findings can be
de-duplicated without disclosing the value."""
import re, subprocess, collections, hashlib, sys
PATTERNS = {
    'pem_private_key': re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    'github_token': re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b'),
    'aws_access_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'helius_key_in_url': re.compile(r'api[-_]key=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'),
    'helius_key_assignment': re.compile(r'HELIUS[_A-Z]*KEY\s*[:=]\s*["\']?([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})'),
    'bitquery_oauth_token': re.compile(r'\bory_at_[A-Za-z0-9_\-\.]{20,}'),
    'render_api_key': re.compile(r'\brnd_[A-Za-z0-9]{20,}\b'),
    'slack_or_discord_webhook': re.compile(r'https://hooks\.slack\.com/services/[A-Za-z0-9/]+|https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+'),
    'solana_keypair_json_64': re.compile(r'\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]'),
    'secret_assignment_generic': re.compile(r'(?i)\b(?:private[_-]?key|secret[_-]?key|seed[_-]?phrase|mnemonic)\b\s*[:=]\s*["\'][^"\'\s]{16,}["\']'),
}
log = subprocess.Popen(['git', 'log', '--all', '-p', '--no-color', '--no-ext-diff', '--format=@@COMMIT %H'],
                       stdout=subprocess.PIPE, text=True, errors='replace')
commit = path = None
hits = collections.defaultdict(lambda: {'commits': set(), 'paths': set(), 'n': 0, 'values': set()})
envfiles = set()
for line in log.stdout:
    if line.startswith('@@COMMIT '):
        commit = line.split()[1][:10]; continue
    if line.startswith('+++ b/'):
        path = line[6:].strip()
        if re.search(r'(^|/)\.env(\.|$)', path): envfiles.add((commit, path))
        continue
    if not line.startswith('+') or line.startswith('+++'):
        continue
    for name, rx in PATTERNS.items():
        for m in rx.finditer(line):
            v = m.group(1) if m.groups() else m.group(0)
            h = hits[name]; h['n'] += 1; h['commits'].add(commit); h['paths'].add(path)
            h['values'].add(hashlib.sha256(v.encode()).hexdigest()[:12])
print('pattern'.ljust(28), 'added_lines', 'distinct_values', 'commits', 'paths(sample)')
for name in PATTERNS:
    h = hits.get(name)
    if not h: print(name.ljust(28), 0); continue
    print(name.ljust(28), h['n'], len(h['values']), len(h['commits']), sorted(h['paths'])[:4])
print('.env-like files ever added:', sorted(envfiles)[:10] if envfiles else 'none')
