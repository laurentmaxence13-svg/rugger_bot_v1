"""Bounded, resumable, read-only backfill of one address over a contiguous slot window.

Built for the L2 data plan: download every transaction (failed ones included) that
touches the LaunchLab program, or a migrated CPMM pool, between two finalized slots,
and prove the download is complete.

Guarantees, each covered by an offline test:

- Read-only: only the methods in ``READ_METHODS`` can be sent.
- Bounded: a request cap AND a credit cap (per-method cost table) are charged
  before every send, retries included. The run stops cleanly at the first cap.
- Resumable: pages are committed in segments; ``state.json`` only advances after
  its segment is on disk, so an interrupted run resumes without losing or
  duplicating rows.
- Verifiable: ``manifest.json`` lists each segment with its SHA-256 and row count,
  and the signature set of the bodies is reconciled against a second listing
  method (``getSignaturesForAddress`` vs ``getTransactionsForAddress``).
- Secret-safe: the endpoint URL (which may carry an API key) is read from an
  environment variable named by the caller and is never logged, stored or put in
  an exception message; only its scheme and host are recorded.

Nothing here signs, sends or simulates a transaction.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import urllib.parse

from bot.market.collector import MAX_TX_VERSION, BudgetExhausted, JsonRpc

LAUNCHLAB_PROGRAM = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
READ_METHODS = frozenset({'getSignaturesForAddress', 'getTransaction', 'getTransactionsForAddress'})
SCHEMA_STATE = 'rugger-backfill-state-v1'
SCHEMA_MANIFEST = 'rugger-backfill-manifest-v1'
GSFA_PAGE = 1000          # getSignaturesForAddress maximum
GTFA_FULL_PAGE = 100      # getTransactionsForAddress, transactionDetails=full (Helius docs)
GTFA_SIG_PAGE = 1000      # getTransactionsForAddress, transactionDetails=signatures

# Credits per request. 'helius-conservative' takes the HIGHEST figure found in
# Helius's own sources (2026-11-04): 10 per archival call, 100 per
# getTransactionsForAddress call (old launch blog; current docs say about 10 per
# 100 transactions). Caps computed with it can only be too safe. Override with a
# JSON file once the dashboard meter has confirmed the real cost.
COST_PRESETS = {
    'helius-conservative': {'getSignaturesForAddress': 10, 'getTransaction': 10,
                            'getTransactionsForAddress': 100},
    'public': {'getSignaturesForAddress': 0, 'getTransaction': 0,
               'getTransactionsForAddress': 0},
    # W1 protocol R6: the current official Helius pages, archived by RUGGER 03 on 2026-11-08
    # (pricing sha256 b6794b1636f1bb74f9dea17c1ae86274fd79635378ea1bfda8acb9d06d268c81,
    # billing/credits sha256 fa152d54f117265801aeae38bd6052be863eaf4e10303817180dc0dea6e4ab49):
    # standard RPC 1 credit; getTransactionsForAddress 10 credits per 100 full transactions
    # returned, rounded up, minimum 10 (signatures-only: 10 flat). With pages of at most 100
    # full transactions (GTFA_FULL_PAGE), 10 charged BEFORE each call is the documented
    # maximum of that call. The provider's dashboard has not confirmed the billing.
    'helius-documented-20261108': {'getSignaturesForAddress': 1, 'getTransaction': 1,
                                   'getTransactionsForAddress': 10},
}


class BackfillError(RuntimeError):
    pass


class CreditBudget:
    """Request and credit caps, charged before each send (retries included).

    With a ``ledger`` file, every charge is written to disk atomically BEFORE the
    request leaves, so spend survives any failure, exception or interrupt, and a
    resume can never restart from a lower counter. The ledger pins the cost table:
    a resume with a different table is refused (a cheaper table would hide spend).
    """

    SCHEMA = 'rugger-backfill-spend-v1'

    def __init__(self, max_requests, max_credits, costs, *, used_requests=0, used_credits=0,
                 ledger=None):
        if set(costs) != READ_METHODS or any(type(v) is not int or v < 0 for v in costs.values()):
            raise BackfillError('cost_table_must_price_every_read_method')
        if type(max_requests) is not int or type(max_credits) is not int \
                or max_requests < 0 or max_credits < 0:
            raise BackfillError('caps_must_be_non_negative_integers')
        self.max_requests, self.max_credits, self.costs = max_requests, max_credits, dict(costs)
        self.used, self.credits = used_requests, used_credits
        self.next_method = None
        self.ledger, self.cap_history = (Path(ledger) if ledger else None), []
        if self.ledger is not None:
            self._open_ledger()

    def _open_ledger(self):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        if self.ledger.exists():
            data = json.loads(self.ledger.read_text())
            if data.get('schema') != self.SCHEMA:
                raise BackfillError('unknown_spend_ledger')
            if data['costs'] != dict(sorted(self.costs.items())):
                raise BackfillError('cost_table_differs_from_spend_ledger')
            self.used = max(self.used, data['requests'])
            self.credits = max(self.credits, data['credits'])
            self.cap_history = data.get('cap_history', [])
        caps = {'max_requests': self.max_requests, 'max_credits': self.max_credits}
        if not self.cap_history or self.cap_history[-1] != caps:
            self.cap_history.append(caps)          # every cap change stays on record
        self._write_ledger()

    def _write_ledger(self):
        if self.ledger is not None:
            _write_atomic(self.ledger, json.dumps({
                'schema': self.SCHEMA, 'requests': self.used, 'credits': self.credits,
                'costs': dict(sorted(self.costs.items())), 'cap_history': self.cap_history},
                indent=1, sort_keys=True).encode())

    @property
    def max_calls(self):            # JsonRpc.__repr__ compatibility
        return self.max_requests

    def charge(self):
        cost = self.costs[self.next_method]
        if self.used + 1 > self.max_requests:
            raise BudgetExhausted(f'request_cap_reached:{self.max_requests}')
        if self.credits + cost > self.max_credits:
            raise BudgetExhausted(f'credit_cap_reached:{self.max_credits}')
        self.used += 1
        self.credits += cost
        self._write_ledger()           # on disk before the request is sent

    def snapshot(self):
        return {'requests': self.used, 'credits': self.credits, 'max_requests': self.max_requests,
                'max_credits': self.max_credits, 'costs': dict(sorted(self.costs.items()))}


class ReadOnlyRpc(JsonRpc):
    """JsonRpc limited to READ_METHODS and metered by a CreditBudget."""

    def call(self, method, params):
        if method not in READ_METHODS:
            raise BackfillError(f'method_not_allowed:{method}')
        self.budget.next_method = method
        return super().call(method, params)


def load_costs(spec):
    """A preset name, or a path to a JSON object pricing every read method."""
    if spec in COST_PRESETS:
        return dict(COST_PRESETS[spec])
    with open(spec, encoding='utf-8') as handle:
        return json.load(handle)


def endpoint_from_env(name, environ=None):
    """The endpoint URL from the named variable; errors never echo its value."""
    environ = os.environ if environ is None else environ
    url = environ.get(name)
    if not url:
        raise BackfillError(f'endpoint_variable_missing:{name}')
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname:
        raise BackfillError(f'endpoint_must_be_https:{name}')
    return url


def endpoint_label(url):
    """Scheme and host only: path, query and credentials are dropped."""
    parts = urllib.parse.urlsplit(url)
    return f'{parts.scheme}://{parts.hostname}'


def signature_of(entry):
    """Signature of a getTransaction result or a getTransactionsForAddress full entry."""
    try:
        return entry['transaction']['signatures'][0]
    except (KeyError, IndexError, TypeError):
        raise BackfillError('entry_without_signature') from None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path, data):
    temporary = Path(str(path) + '.tmp')
    with open(temporary, 'wb') as handle:
        handle.write(data)
    os.replace(temporary, path)


def _write_segment(path, rows):
    body = ''.join(json.dumps(r, separators=(',', ':'), sort_keys=True) + '\n' for r in rows)
    _write_atomic(path, gzip.compress(body.encode(), mtime=0))


def read_segment(path):
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        return [json.loads(line) for line in handle]


class Window:
    """Inclusive finalized slot window [slot_min, slot_max] of one address."""

    def __init__(self, address, slot_min, slot_max):
        if type(slot_min) is not int or type(slot_max) is not int or not 0 <= slot_min <= slot_max:
            raise BackfillError('invalid_slot_window')
        self.address, self.slot_min, self.slot_max = address, slot_min, slot_max

    def to_json(self):
        return {'address': self.address, 'slot_min': self.slot_min, 'slot_max': self.slot_max}


def plan(window, costs, *, expected_tx_per_slot, bodies='gtfa', check=True,
         failed_share=0.34, anchor=False):
    """Pre-run estimate (no network). The expected volume is the caller's assumption."""
    if expected_tx_per_slot <= 0 or not 0 <= failed_share < 1:
        raise BackfillError('invalid_volume_assumption')
    slots = window.slot_max - window.slot_min + 1
    tx = int(round(slots * expected_tx_per_slot))
    pages = lambda n, size: -(-n // size) if n else 1          # noqa: E731
    requests = {}
    if bodies == 'gtfa':
        requests['getTransactionsForAddress'] = pages(tx, GTFA_FULL_PAGE)
        if check:
            requests['getSignaturesForAddress'] = pages(tx, GSFA_PAGE)
    elif bodies == 'rpc':
        requests['getSignaturesForAddress'] = pages(tx, GSFA_PAGE)
        requests['getTransaction'] = tx               # failed bodies included
        if check:
            requests['getTransactionsForAddress'] = pages(tx, GTFA_SIG_PAGE)
    else:
        raise BackfillError('bodies_must_be_gtfa_or_rpc')
    if anchor and requests.get('getSignaturesForAddress'):
        requests['getTransactionsForAddress'] = requests.get('getTransactionsForAddress', 0) + 1
    credits = sum(n * costs[m] for m, n in requests.items())
    return {'window': window.to_json(), 'slots': slots, 'expected_transactions': tx,
            'assumed_tx_per_slot': expected_tx_per_slot, 'bodies': bodies, 'check': check,
            'requests': dict(sorted(requests.items())), 'total_requests': sum(requests.values()),
            'credits': credits, 'stored_gz_bytes_estimate': tx * 1700,
            'note': 'estimate only; gsfa pages newer than slot_max are extra unless an anchor '
                    'signature is given'}


class Backfill:
    """One resumable run over a window, writing segments, state and manifest to ``out``."""

    def __init__(self, rpc, window, out, *, bodies='gtfa', check=True, segment_pages=50,
                 endpoint='unset', before_signature=None, anchor_after_window=False):
        if bodies not in ('gtfa', 'rpc'):
            raise BackfillError('bodies_must_be_gtfa_or_rpc')
        if anchor_after_window and before_signature:
            raise BackfillError('anchor_after_window_and_before_signature_are_exclusive')
        if anchor_after_window and bodies == 'gtfa' and not check:
            raise BackfillError('anchor_after_window_needs_the_gsfa_listing')
        self.rpc, self.window, self.out = rpc, window, Path(out)
        self.bodies, self.check, self.segment_pages = bodies, check, segment_pages
        self.endpoint, self.before_signature = endpoint, before_signature
        self.anchor_after_window = anchor_after_window
        self.out.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    # ----------------------------------------------------------------- state
    def _load_state(self):
        path = self.out / 'state.json'
        if not path.exists():
            return {'schema': SCHEMA_STATE, 'window': self.window.to_json(),
                    'bodies': self.bodies, 'check': self.check, 'endpoint': self.endpoint,
                    'phases': {}, 'segments': [], 'budget_used': {'requests': 0, 'credits': 0}}
        state = json.loads(path.read_text())
        if (state.get('schema') != SCHEMA_STATE or state['window'] != self.window.to_json()
                or state['bodies'] != self.bodies or state['check'] != self.check):
            raise BackfillError('resume_parameters_differ_from_state')
        # Segments written after the last committed state are uncommitted: drop them.
        known = {s['path'] for s in state['segments']}
        for stray in self.out.glob('*.jsonl.gz'):
            if stray.name not in known:
                stray.unlink()
        return state

    def _commit(self, kind, rows, phase, cursor, done):
        """Transactional commit (R02 B1 on 13b5eea): the next state is built on a copy and
        becomes ``self.state`` only once state.json has been replaced. A commit that fails
        partway leaves the in-memory state unchanged, so retrying it reuses the same segment
        name (the file is overwritten) and can never reference the same rows twice. Nested
        objects that are not changed here (``sample_stats``...) stay shared, by identity."""
        state = dict(self.state)
        if rows:
            name = f'{kind}-{len(state["segments"]) + 1:06d}.jsonl.gz'
            _write_segment(self.out / name, rows)
            state['segments'] = list(state['segments']) + [
                {'path': name, 'kind': kind, 'rows': len(rows)}]
        state['phases'] = dict(state['phases'], **{phase: {'cursor': cursor, 'done': done}})
        budget = self.rpc.budget
        state['budget_used'] = {'requests': budget.used, 'credits': budget.credits}
        _write_atomic(self.out / 'state.json',
                      json.dumps(state, indent=1, sort_keys=True).encode())
        # One in-place update (no clear): ``state`` has every key of ``self.state``, so there
        # is no window where the in-memory state is empty (R02 observation on c3dec78).
        self.state.update(state)

    def _phase(self, name):
        return self.state['phases'].get(name, {'cursor': None, 'done': False})

    # ----------------------------------------------------------------- listings
    def _gtfa_phase(self, phase, kind, details, page_size):
        """getTransactionsForAddress, oldest first, slot-filtered, failed included."""
        current = self._phase(phase)
        token, rows, pages = current['cursor'], [], 0
        if current['done']:
            return
        while True:
            options = {'transactionDetails': details, 'encoding': 'json',
                       'maxSupportedTransactionVersion': MAX_TX_VERSION,
                       'commitment': 'finalized', 'limit': page_size, 'sortOrder': 'asc',
                       'filters': {'status': 'any', 'slot': {'gte': self.window.slot_min,
                                                             'lte': self.window.slot_max}}}
            if token:
                options['paginationToken'] = token
            result = self.rpc.call('getTransactionsForAddress', [self.window.address, options])
            if not isinstance(result, dict) or not isinstance(result.get('data'), list):
                raise BackfillError('getTransactionsForAddress:malformed_result')
            for entry in result['data']:
                slot = entry.get('slot')
                if type(slot) is not int or not self.window.slot_min <= slot <= self.window.slot_max:
                    raise BackfillError('getTransactionsForAddress:entry_outside_window')
                if details == 'full':
                    rows.append(dict(entry, signature=signature_of(entry)))
                else:
                    rows.append(dict(entry))
            token, pages = result.get('paginationToken'), pages + 1
            done = not token
            if done or pages >= self.segment_pages:
                self._commit(kind, rows, phase, token, done)
                rows, pages = [], 0
            if done:
                return

    def _anchor_phase(self):
        """First transaction strictly after the window (GTFA signatures, one call), or None.

        Without an anchor, getSignaturesForAddress lists from the chain head down to slot_max:
        on an old window of a busy account that costs one page per 1000 signatures newer than
        the window. One getTransactionsForAddress call (slot >= slot_max + 1, successful only,
        oldest first, limit 1) gives the first signature after the window; listing ``before``
        it starts at the window's newest signature. It is the FIRST request of the run (R02),
        charged before it is sent like any other, and committed in state like any cursor; the
        manifest copies it and verify() checks it. Rows above slot_max are still dropped.
        """
        current = self._phase('anchor')
        if current['done']:
            return current['cursor']['signature']
        if not self.anchor_after_window:
            return None
        options = {'transactionDetails': 'signatures', 'encoding': 'json',
                   'maxSupportedTransactionVersion': MAX_TX_VERSION,
                   'commitment': 'finalized', 'limit': 1, 'sortOrder': 'asc',
                   'filters': {'status': 'succeeded', 'slot': {'gte': self.window.slot_max + 1}}}
        result = self.rpc.call('getTransactionsForAddress', [self.window.address, options])
        if not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise BackfillError('getTransactionsForAddress:malformed_result')
        if not result['data']:
            raise BackfillError('no_transaction_after_the_window_to_anchor')
        entry = result['data'][0]
        if not isinstance(entry, dict):
            raise BackfillError('getTransactionsForAddress:anchor_not_a_successful_transaction_after_the_window')
        slot, signature, index = entry.get('slot'), entry.get('signature'), entry.get('transactionIndex')
        if (type(slot) is not int or slot <= self.window.slot_max
                or type(signature) is not str or not signature or entry.get('err') is not None
                or not (index is None or type(index) is int)):
            raise BackfillError('getTransactionsForAddress:anchor_not_a_successful_transaction_after_the_window')
        self._commit('anc', [], 'anchor', {'signature': signature, 'slot': slot, 'transaction_index': index}, True)
        return signature

    def _gsfa_phase(self, phase='gsfa', kind='sig'):
        """getSignaturesForAddress, newest first, kept only inside the window."""
        current = self._phase(phase)
        if current['done']:
            return
        anchor = None if (current['cursor'] or self.before_signature) else self._anchor_phase()
        before, rows, pages = current['cursor'] or self.before_signature or anchor, [], 0
        while True:
            options = {'limit': GSFA_PAGE, 'commitment': 'finalized'}
            if before:
                options['before'] = before
            page = self.rpc.call('getSignaturesForAddress', [self.window.address, options]) or []
            if not isinstance(page, list):
                raise BackfillError('getSignaturesForAddress:malformed_result')
            reached_start = False
            for row in page:
                if row['slot'] < self.window.slot_min:
                    reached_start = True
                    break
                if row['slot'] <= self.window.slot_max:
                    rows.append(dict(row))      # whole row: blockTime, transactionIndex, err
            done = reached_start or len(page) < GSFA_PAGE
            before, pages = (page[-1]['signature'] if page else before), pages + 1
            if done or pages >= self.segment_pages:
                self._commit(kind, rows, phase, before, done)
                rows, pages = [], 0
            if done:
                return

    def _rpc_bodies_phase(self):
        """getTransaction for every listed signature (failed ones included)."""
        current = self._phase('bodies')
        if current['done']:
            return
        listed = [r for s in self.state['segments'] if s['kind'] == 'sig'
                  for r in read_segment(self.out / s['path'])]
        listed.sort(key=lambda r: (r['slot'], r['signature']))
        start, rows, missing = current['cursor'] or 0, [], self.state.setdefault('missing', [])
        for index in range(start, len(listed)):
            signature = listed[index]['signature']
            result = self.rpc.call('getTransaction', [signature, {
                'encoding': 'json', 'maxSupportedTransactionVersion': MAX_TX_VERSION,
                'commitment': 'finalized'}])
            if result is None:
                missing.append(signature)
            else:
                rows.append(dict(result, signature=signature))
            if len(rows) >= self.segment_pages * GTFA_FULL_PAGE:
                self._commit('tx', rows, 'bodies', index + 1, False)
                rows = []
        self._commit('tx', rows, 'bodies', len(listed), True)

    # ----------------------------------------------------------------- run
    def run(self):
        """Run or resume. Returns the manifest; a cap stop gives complete=False."""
        stop = None
        try:
            if self.anchor_after_window:
                self._anchor_phase()                 # the first request of the run (R02)
            if self.bodies == 'gtfa':
                self._gtfa_phase('gtfa', 'tx', 'full', GTFA_FULL_PAGE)
                if self.check:
                    self._gsfa_phase()
            else:
                self._gsfa_phase()
                self._rpc_bodies_phase()
                if self.check:
                    self._gtfa_phase('gtfa_sig', 'chk', 'signatures', GTFA_SIG_PAGE)
        except BudgetExhausted as exc:
            stop = str(exc)
            budget = self.rpc.budget
            self.state['budget_used'] = {'requests': budget.used, 'credits': budget.credits}
            _write_atomic(self.out / 'state.json',
                          json.dumps(self.state, indent=1, sort_keys=True).encode())
        return self.write_manifest(stop)

    def write_manifest(self, stop=None):
        segments, tx_sigs, failed, check_sigs = [], [], 0, []
        for seg in self.state['segments']:
            path = self.out / seg['path']
            rows = read_segment(path)
            segments.append({'path': seg['path'], 'kind': seg['kind'], 'rows': len(rows),
                             'bytes': path.stat().st_size, 'sha256': _sha256(path)})
            if seg['kind'] == 'tx':
                tx_sigs += [r['signature'] for r in rows]
                failed += sum(1 for r in rows if (r.get('meta') or {}).get('err') is not None)
            elif seg['kind'] in ('sig', 'chk'):
                check_sigs += [r['signature'] for r in rows] if (
                    (self.bodies == 'gtfa' and seg['kind'] == 'sig')
                    or (self.bodies == 'rpc' and seg['kind'] == 'chk')) else []
        phases_done = all(p.get('done') for p in self.state['phases'].values()) and bool(
            self.state['phases'])
        reconciliation = None
        if self.check:
            a, b = set(tx_sigs), set(check_sigs)
            reconciliation = {'bodies': len(a), 'second_method': len(b), 'equal': a == b,
                              'only_in_bodies': sorted(a - b)[:20],
                              'only_in_second_method': sorted(b - a)[:20]}
        duplicates = len(tx_sigs) - len(set(tx_sigs))
        missing = list(self.state.get('missing', []))
        complete = (stop is None and phases_done and duplicates == 0 and not missing
                    and (reconciliation is None or reconciliation['equal']))
        manifest = {'schema': SCHEMA_MANIFEST, 'window': self.window.to_json(),
                    'endpoint': self.state['endpoint'], 'bodies': self.bodies,
                    'check': self.check, 'segments': segments,
                    'totals': {'transactions': len(tx_sigs), 'failed_transactions': failed,
                               'duplicate_signatures': duplicates,
                               'bodies_missing': len(missing)},
                    'reconciliation': reconciliation,
                    'budget': dict(self.rpc.budget.snapshot()), 'stopped_by': stop,
                    'complete': complete,
                    'single_method': not self.check,
                    'gsfa_anchor': self._phase('anchor')['cursor']}
        _write_atomic(self.out / 'manifest.json',
                      json.dumps(manifest, indent=1, sort_keys=True).encode())
        return manifest


def verify(out):
    """Offline check of a run directory against its manifest (no network)."""
    out = Path(out)
    manifest = json.loads((out / 'manifest.json').read_text())
    if manifest.get('schema') != SCHEMA_MANIFEST:
        raise BackfillError('unknown_manifest_schema')
    problems, tx_sigs, failed, check_sigs = [], [], 0, []
    check_kind = {'gtfa': 'sig', 'rpc': 'chk'}[manifest['bodies']]
    for seg in manifest['segments']:
        path = out / seg['path']
        if not path.exists():
            problems.append(f'missing:{seg["path"]}')
            continue
        if _sha256(path) != seg['sha256']:
            problems.append(f'sha256_mismatch:{seg["path"]}')
            continue
        rows = read_segment(path)
        if len(rows) != seg['rows']:
            problems.append(f'row_count_mismatch:{seg["path"]}')
        if seg['kind'] == 'tx':
            tx_sigs += [r['signature'] for r in rows]
            failed += sum(1 for r in rows if (r.get('meta') or {}).get('err') is not None)
        elif seg['kind'] == check_kind:
            check_sigs += [r['signature'] for r in rows]
    anchor = manifest.get('gsfa_anchor')
    if anchor is not None:
        state_path = out / 'state.json'
        state_anchor = (json.loads(state_path.read_text()).get('phases', {}).get('anchor') or {}).get('cursor') \
            if state_path.exists() else None
        if (not isinstance(anchor, dict) or type(anchor.get('slot')) is not int
                or anchor['slot'] <= manifest['window']['slot_max'] or type(anchor.get('signature')) is not str
                or not anchor['signature'] or anchor != state_anchor):
            problems.append('gsfa_anchor_invalid')
    # Recompute what the manifest claims instead of trusting it.
    if not problems:
        totals = manifest['totals']
        if (len(tx_sigs), failed, len(tx_sigs) - len(set(tx_sigs))) != (
                totals['transactions'], totals['failed_transactions'],
                totals['duplicate_signatures']):
            problems.append('totals_differ_from_segments')
        if manifest['check']:
            equal = set(tx_sigs) == set(check_sigs)
            if equal != manifest['reconciliation']['equal']:
                problems.append('reconciliation_differs_from_segments')
            if manifest['complete'] and not equal:
                problems.append('complete_claimed_without_reconciliation')
    return {'ok': not problems, 'problems': problems, 'complete': manifest['complete'] and not problems,
            'transactions': len(tx_sigs),
            'manifest_sha256': _sha256(out / 'manifest.json')}


def open_rpc(url, budget, *, opener=None, min_interval=0.12):
    """A metered read-only client. ``opener`` is injectable for offline tests."""
    kwargs = {'min_interval': min_interval}
    if opener is not None:
        kwargs.update(opener=opener, sleep=lambda _s: None)
    return ReadOnlyRpc(url, budget, **kwargs)
