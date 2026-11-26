"""Polling source and runner of livepaper 0.1.4 (dossier T-R01-12 v0.3, option (i)).
0.1.4 (D13, R04 01:14Z; mechanism read on the anchored snapshot 1e86638): Source.fetch is ALL OR NOTHING. In 0.1.2 /
0.1.3 each pool moved last_sig / seen / rank / since as soon as it was read, BEFORE the batch reached the engine; a
later request of the same fetch that failed (GSFA of 6CQSpR) discarded the batch but not that progress, so the retry
asked GSFA(GaPTvX, until=5fP9...) and 5fP9 never reached the engine (reserves_chain_broken, GaPTvX excluded for good).
Now the state is saved before and restored on ANY exception: the retry asks again from the last DELIVERED signature.
0.1.4 (D14, R02 01:31Z: the signed text forbids tolerating RPC errors): the Runner STOPS at the FIRST incident (RpcError
or SourceError) after an ERROR record (type and a redacted message); no sleep-and-retry any more. The only tolerance is
the one of livesim_collect / activity_l2.RetryOnceClient: ONE re-read of the SAME call on 'response_truncated', charged
by the ledger (Client.call charges) and logged in the calls log (retry=True); a second truncation is an incident.
0.1.3 (R04 20:33Z, after a 60-s pause unexplained by a 29-ms processing): TimedClient wraps the frozen
cpmmpilot.rpc.Client (unchanged) and writes, for EVERY call, success or failure, its start, end and duration to
<calls>.timing.jsonl; STEP carries fetch_ms (the collection time, host clock); a pause of 2 x poll_s or MORE is a GAP.
0.1.1 (R02 reserves on 0.1 PASS DE CODE): the module bot.p4.historical_research_replay, imported outside every
MANIFEST (fill.py, cpmmprereg), has its sha checked at start (check_imports), as check_frozen does; the two sha sets
below receives the signed owner text by an audited release, never at run time; the ORDERCHECK sha anchored by R02 is
an argument of run (--ordercheck-sha), as --eligible-sha (R02 16:24Z: one executable release).
NO NETWORK CALL IS POSSIBLE FROM 0.1: LiveTransport opens only with an authorization text whose sha256 is in
AUTHORIZED_TEXT_SHA256, EMPTY here (the owner's text D-3 / D-7, anchored by R02, enters only by an audited release).
The transport is cpmmpilot.rpc.LiveRpc (frozen 0.2.8: https only, no key read, the proxy injects it, errors never echo
the endpoint), restricted to the four read methods below; there is no signing or sending method anywhere.
Two modes, the index of a transaction in its slot being needed by cpmmx (the order of the reserves chain):
  gtfa       getSignaturesForAddress limit 1 `until` the newest signature received (1 credit): only if something is
             new, getTransactionsForAddress pages (transactionIndex given by the provider), 10 credits per call;
  gsfa_rank  getSignaturesForAddress (1 credit) then getTransaction (1 credit) per new signature, the index being the
             RANK in the slot given by the getSignaturesForAddress order. NOT ADMISSIBLE until that order is verified
             against GTFA on real data and anchored by R02: run refuses it unless the verification sha is in
             GSFA_ORDER_VERIFIED (EMPTY in 0.1).
Owner text livepaper v2 (1366025b, R02 14:50Z): ONE credit ledger for the order check and the test, ceiling 25 000,
hard stop 24 500, charged and written BEFORE every request (as cpmmpilot.budget), no resume past it; the way is FROZEN
at the first pass: (i-a) gsfa_rank polled every 30 s, (i-b) gtfa polled every 150 s, the one the anchored order-check
verdict designates (a-ok -> (i-a), b -> (i-b)); its sha is given by run --ordercheck-sha."""
import json
import os
import time
import urllib.request
from pathlib import Path

from cpmmpilot import budget as B, rpc as RPC
from livepaper import journal as J

AUTHORIZED_TEXT_SHA256 = frozenset({'1366025b6290c0a748c2190eebc5e3ee078a25868ef005591710b23658ebface'})   # 0.1.2: signed (event a60ed568 17:40:23Z, R02)
HRR_SHA256 = '372385bd72ee0fda02d80d5be1e20d2925d4be54361f30570877d02dfdc2e8a0'   # bot/p4/historical_research_replay.py
CEILING, HARD_STOP = 25_000, 24_500         # owner text 1366025b: one ledger, order check + test
MODE_POLL = {'gsfa_rank': 30, 'gtfa': 150}  # (i-a) / (i-b), frozen at the first pass
VERDICT_MODE = {'a-ok': 'gsfa_rank', 'b': 'gtfa'}
METHODS = ('getSlot', 'getSignaturesForAddress', 'getTransaction', 'getTransactionsForAddress')
MODES = ('gtfa', 'gsfa_rank')
GSFA_LIMIT = 1_000
TX_OPTIONS = dict(encoding='json', maxSupportedTransactionVersion=RPC.MAX_TX_VERSION, commitment='confirmed')
GAP_FACTOR = 2
RETRY_ON_TRUNCATED = 1                      # 0.1.4: as livesim_collect (R02 01:31Z (a))
CATCHUP_GSFA_LIMIT, CATCHUP_MAX_TX = 100, 10    # 0.1.4: bounded catch-up, at most 1 + 10 credits per pool and step


class SourceError(RuntimeError):
    pass


class LiveTransport(RPC.LiveRpc):
    """cpmmpilot.rpc.LiveRpc with livepaper's OWN authorization set (empty in 0.1) and the four read methods only."""

    def __init__(self, endpoint=None, *, authorization_file=None, timeout_s=60, opener=None, clock=None, sleep=None):
        if authorization_file is None:
            raise RPC.RpcError('live_rpc_needs_an_anchored_authorization')
        try:
            digest = RPC._file_sha(authorization_file)
        except OSError as exc:
            raise RPC.RpcError('authorization_file_unreadable') from exc
        if digest not in AUTHORIZED_TEXT_SHA256:
            raise RPC.RpcError('authorization_not_anchored')
        self._endpoint = RPC.check_endpoint(endpoint)
        self.authorization_sha256 = digest
        self.timeout_s = timeout_s
        self._open = opener if opener is not None else urllib.request.build_opener().open
        self._clock = clock if clock is not None else time.monotonic
        self._sleep = sleep if sleep is not None else time.sleep
        self._last_sent = None
        self.requests = 0

    def request(self, method, params):
        if method not in METHODS:
            raise RPC.RpcError('method_not_in_livepaper')
        return RPC.LiveRpc.request(self, method, params)


class Budget:
    """The ONE credit ledger (order check and test): charged and written before the request leaves; refusal past the
    hard stop (24 500 of 25 000)."""

    def __init__(self, ledger, ceiling=CEILING, hard_stop=HARD_STOP):
        if (ceiling, hard_stop) != (CEILING, HARD_STOP):
            raise B.BudgetError('ceiling_is_the_owner_text_25000_24500')
        self.ledger, self.ceiling = Path(ledger), ceiling
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.hard_stop = hard_stop
        self.requests = self.credits = 0
        self.by_method = {}
        if self.ledger.exists():
            data = json.loads(self.ledger.read_text())
            if data['ceiling'] != ceiling or data['costs'] != dict(sorted(B.COSTS.items())):
                raise B.BudgetError('ledger_of_another_ceiling_or_cost_table')
            self.requests, self.credits, self.by_method = data['requests'], data['credits'], data['by_method']
        self._write()

    def _write(self):
        B._write_atomic(self.ledger, json.dumps(dict(
            schema='livepaper-spend-v0.1', ceiling=self.ceiling, hard_stop=self.hard_stop, requests=self.requests,
            credits=self.credits, by_method=dict(sorted(self.by_method.items())),
            costs=dict(sorted(B.COSTS.items()))), indent=1, sort_keys=True).encode())

    def charge(self, method, params=None):
        if method not in METHODS:
            raise B.BudgetError('method_not_in_livepaper:%s' % method)
        if method == 'getTransactionsForAddress':
            limit = (params or [None, {}])[1].get('limit')
            if type(limit) is not int or not 1 <= limit <= B.GTFA_MAX_LIMIT:
                raise B.BudgetError('gtfa_limit_must_be_1_to_100')
        cost = B.COSTS[method]
        if self.credits + cost > self.hard_stop:
            raise B.BudgetExhausted('credit_hard_stop:%d' % self.hard_stop)
        self.requests += 1
        self.credits += cost
        self.by_method[method] = self.by_method.get(method, 0) + cost
        self._write()


class Source:
    """The new raw transactions of every pool since the last receipt, and the receipt slot (getSlot AFTER the fetch)."""

    def __init__(self, client, pools, *, mode, start):
        if mode not in MODES:
            raise SourceError('unknown_mode')
        self.client, self.pools, self.mode, self.start = client, list(pools), mode, start
        self.last_sig = {p: None for p in self.pools}         # gsfa_rank: newest signature received
        self.rank = {p: {} for p in self.pools}               # gsfa_rank: transactions already ranked per slot
        self.since = {p: start for p in self.pools}           # gtfa: newest block time received
        self.seen = {p: set() for p in self.pools}            # signatures already handed to the engine

    def restore(self, records):
        """The source state after a restart, from the RECEIVED records of the journal."""
        for r in records:
            if r['kind'] != 'RECEIVED' or r['pool'] not in self.last_sig:
                continue
            self.last_sig[r['pool']] = r['signature']
            self.seen[r['pool']].add(r['signature'])
            self.rank[r['pool']][r['slot']] = self.rank[r['pool']].get(r['slot'], 0) + 1
            if type(r['block_time']) is int:
                self.since[r['pool']] = max(self.since[r['pool']], r['block_time'])

    def _state(self):
        return (dict(self.last_sig), {p: dict(r) for p, r in self.rank.items()}, dict(self.since),
                {p: set(s) for p, s in self.seen.items()})

    def fetch(self):
        """0.1.4 (D13): all or nothing -- the state moves only if every pool AND getSlot succeed."""
        saved = self._state()
        try:
            batch = {p: (self._gtfa(p) if self.mode == 'gtfa' else self._gsfa(p)) for p in self.pools}
            slot = self.client.call('getSlot', [dict(commitment='confirmed')])
            if type(slot) is not int:
                raise SourceError('slot_not_an_integer')
        except BaseException:
            self.last_sig, self.rank, self.since, self.seen = saved
            raise
        return batch, slot

    def catchup(self, pool, receipt_slot):
        """0.1.4 (D13 second net): ONE getSignaturesForAddress (the 100 newest, no cursor) and at most 10 getTransaction,
        for the signatures never delivered that are not newer than the newest delivered slot and not after the receipt.
        Refused (nothing added) when: mode gtfa; nothing missed; more than 10 missed; a missed transaction falls in a slot
        that already holds delivered transactions (its rank in the slot would be uncertain); a transaction not served.
        All or nothing, as fetch. Returns (transactions, outcome)."""
        if self.mode != 'gsfa_rank':
            return [], 'not_in_gtfa_mode'
        saved = self._state()
        try:
            page = self.client.call('getSignaturesForAddress',
                                    [pool, dict(limit=CATCHUP_GSFA_LIMIT, commitment='confirmed')])
            newest = max(self.rank[pool], default=None)
            missed = [s for s in reversed(page) if s['signature'] not in self.seen[pool]
                      and type(s.get('slot')) is int and newest is not None and s['slot'] <= min(newest, receipt_slot)
                      and not (type(s.get('blockTime')) is int and s['blockTime'] < self.start)]
            if not missed:
                return [], 'nothing_found'
            if len(missed) > CATCHUP_MAX_TX:
                return [], 'too_many_missed:%d' % len(missed)
            if any(self.rank[pool].get(s['slot'], 0) for s in missed):
                return [], 'rank_uncertain'
            out = []
            for s in missed:
                raw = self.client.call('getTransaction', [s['signature'], dict(TX_OPTIONS)])
                if raw is None:
                    self.last_sig, self.rank, self.since, self.seen = saved
                    return [], 'not_served'
                if raw.get('slot') != s['slot']:
                    raise SourceError('slot_differs_between_methods')
                rank = self.rank[pool].get(raw['slot'], 0)
                self.rank[pool][raw['slot']] = rank + 1
                self.seen[pool].add(s['signature'])
                out.append(dict(raw, transactionIndex=rank, livepaper_index_source='gsfa_rank_catchup'))
        except BaseException:
            self.last_sig, self.rank, self.since, self.seen = saved
            raise
        return out, 'found'

    def _gtfa(self, pool):
        if self.last_sig[pool]:                             # 1-credit novelty check before the 10-credit pages
            probe = self.client.call('getSignaturesForAddress',
                                     [pool, dict(limit=1, until=self.last_sig[pool], commitment='confirmed')])
            if not probe:
                return []
        out, token = [], None
        while True:
            opts = dict(transactionDetails='full', sortOrder='asc', limit=B.GTFA_MAX_LIMIT, encoding='json',
                        maxSupportedTransactionVersion=RPC.MAX_TX_VERSION,
                        filters=dict(blockTime=dict(gte=self.since[pool])))
            if token:
                opts['paginationToken'] = token
            page = self.client.call('getTransactionsForAddress', [pool, opts])
            out += page.get('data') or []
            token = page.get('paginationToken')
            if not token:
                break
        fresh = []
        for raw in out:
            sig = raw['transaction']['signatures'][0]
            if sig in self.seen[pool]:
                continue                                    # the gte boundary returns the last second again
            self.seen[pool].add(sig)
            fresh.append(raw)
            if type(raw.get('blockTime')) is int:
                self.since[pool] = max(self.since[pool], raw['blockTime'])
        if fresh:
            self.last_sig[pool] = max(fresh, key=lambda r: (r['slot'], r['transactionIndex']))['transaction']['signatures'][0]
        return fresh

    def _gsfa(self, pool):
        sigs, before = [], None
        while True:
            opts = dict(limit=GSFA_LIMIT, commitment='confirmed')
            if self.last_sig[pool]:
                opts['until'] = self.last_sig[pool]
            if before:
                opts['before'] = before
            page = self.client.call('getSignaturesForAddress', [pool, opts])
            sigs += page
            old = [s for s in page if type(s.get('blockTime')) is int and s['blockTime'] < self.start]
            if len(page) < GSFA_LIMIT or old:
                break
            before = page[-1]['signature']
        sigs = [s for s in reversed(sigs) if not (type(s.get('blockTime')) is int and s['blockTime'] < self.start)
                and s['signature'] not in self.seen[pool]]
        out = []
        for s in sigs:
            raw = self.client.call('getTransaction', [s['signature'], dict(TX_OPTIONS)])
            if raw is None:
                break                                   # not served yet: this pool resumes from here at the next poll
            if raw.get('slot') != s.get('slot'):
                raise SourceError('slot_differs_between_methods')
            rank = self.rank[pool].get(raw['slot'], 0)
            self.rank[pool][raw['slot']] = rank + 1
            out.append(dict(raw, transactionIndex=rank, livepaper_index_source='gsfa_rank'))
            self.last_sig[pool] = s['signature']
            self.seen[pool].add(s['signature'])
        return out


class Runner:
    """Polls every `poll_s` seconds for at most `max_s` (a process lives at most 2 h in R03's container); a pause of
    GAP_FACTOR x poll_s or more (restart, slow poll; 0.1.4: an error STOPS) is a GAP record. 0.1.4: STEP processing_ms
    includes the catch-up calls when a CATCHUP record precedes it. Writes HEAD.json (head sha, seq, wall) after every step: the
    wrapper of R03 commits and pushes it every 15 min."""

    def __init__(self, engine, source, *, poll_s, max_s, head_file, wall=time.time, mono_ns=time.monotonic_ns,
                 sleep=time.sleep):
        self.engine, self.source, self.poll_s, self.max_s = engine, source, poll_s, max_s
        self.head_file = Path(head_file)
        self.wall, self.mono_ns, self.sleep = wall, mono_ns, sleep
        steps = [r for r in engine.journal.records if r['kind'] == 'STEP']
        self.last_wall = steps[-1]['wall'] if steps else None

    def _stop(self, reason):
        j = self.engine.journal
        j.append('STOP', reason=reason, wall=self.wall())
        j.commit()
        self._head()
        return reason

    def _catchup(self, batch, slot, receipt_time):
        """0.1.4 (D13 second net): before G-0 can refuse a pool for a broken reserves chain, one bounded catch-up; its
        outcome is journaled (CATCHUP) whatever it is; what it finds joins the batch (RECEIVED records and pages, as any
        transaction, so the replay re-derives them)."""
        for pool in self.engine.breaks_ahead(batch, receipt_time):
            found, outcome = self.source.catchup(pool, slot)
            self.engine.journal.append('CATCHUP', pool=pool, outcome=outcome, receipt_slot=slot,
                                       signatures=[r['transaction']['signatures'][0] for r in found], wall=self.wall())
            if found:
                batch[pool] = found + list(batch.get(pool, []))

    def _error_stop(self, exc):
        """0.1.4 (D14): the first incident is journaled (ERROR, then STOP) and ends the process."""
        j = self.engine.journal
        j.append('ERROR', error_type=type(exc).__name__, message=redact(exc), wall=self.wall())
        return self._stop('incident:%s' % type(exc).__name__)

    def _head(self):
        j = self.engine.journal
        B._write_atomic(self.head_file, J.canonical(dict(head=j.head, seq=len(j.records) - 1, wall=self.wall())).encode())

    def gap_of(self, last_wall, wall):
        """0.1.3: a pause of GAP_FACTOR x poll_s or more is a GAP (0.1.2: strictly more)."""
        if last_wall is not None and wall - last_wall >= GAP_FACTOR * self.poll_s:
            return (last_wall, wall)
        return None

    def run(self):
        end_ns = self.mono_ns() + int(self.max_s * 1e9)
        while self.mono_ns() < end_ns:
            began = self.mono_ns()
            try:
                batch, slot = self.source.fetch()
                fetched = self.mono_ns()
                mono, wall = self.mono_ns(), self.wall()
                self._catchup(batch, slot, int(wall))
            except B.BudgetExhausted:
                return self._stop('credit_hard_stop_24500')
            except (RPC.RpcError, SourceError) as exc:
                return self._error_stop(exc)
            gap = self.gap_of(self.last_wall, wall)
            self.engine.step(receipt_slot=slot, receipt_time=int(wall), batch=batch, wall=wall, mono_ns=mono, gap=gap,
                             clock_ns=self.mono_ns, fetch_ms=(fetched - began) / 1e6)
            self.last_wall = wall
            self._head()
            rest = self.poll_s - (self.mono_ns() - began) / 1e9
            if rest > 0:
                self.sleep(rest)
        return self._stop('planned_end_of_process')


def check_no_signing_modules(modules):
    """S-4: no signing / sending module is loaded (checked at start and at every planned stop)."""
    banned = ('solders.keypair', 'solana.keypair', 'nacl', 'solders.transaction', 'solana.transaction')
    found = sorted(m for m in modules if any(m == b or m.startswith(b + '.') for b in banned))
    if found:
        raise SourceError('signing_module_loaded:%s' % ','.join(found))
    return True


def env_has_no_key():
    """The process must not see the provider key (the proxy injects it): refuse to start if one is in the environment."""
    return not any('HELIUS' in k.upper() and 'KEY' in k.upper() for k in os.environ)


def collect_gsfa(client, pools, out, *, window_start):
    """The order-check input (R03, once, before the test): getSignaturesForAddress pages of each pool, newest first, back
    to `window_start` (the pre-start window of the anchored ELIGIBLE), one gz page per call under <out>/<pool>/; on the
    SAME ledger as the test. Resumable: a pool whose DONE marker exists is skipped."""
    from cpmmpilot.store import write_gz_page
    out = Path(out)
    for pool in pools:
        d = out / pool
        if (d / 'DONE').exists():
            continue
        before, k = None, 0
        while True:
            opts = dict(limit=GSFA_LIMIT, commitment='confirmed')
            if before:
                opts['before'] = before
            page = client.call('getSignaturesForAddress', [pool, opts])
            write_gz_page(d / ('page_%05d.json.gz' % k), dict(data=page))
            k += 1
            if len(page) < GSFA_LIMIT or any(type(x.get('blockTime')) is int and x['blockTime'] < window_start
                                             for x in page):
                break
            before = page[-1]['signature']
        (d / 'DONE').write_text(str(k))
    return {p: int((out / p / 'DONE').read_text()) for p in pools}


def check_imports(expected=None):
    """R02 reserve 3: the sha of bot.p4.historical_research_replay (outside every MANIFEST) at start."""
    import hashlib
    from bot.p4 import historical_research_replay as hrr
    got = hashlib.sha256(Path(hrr.__file__).read_bytes()).hexdigest()
    if got != (HRR_SHA256 if expected is None else expected):
        raise SourceError('historical_research_replay_differs')
    return got


def redact(exc):
    """The message of an incident, kept to [A-Za-z0-9_:.-] and 80 characters (the frozen RpcError codes never name the
    endpoint; this keeps it so whatever the message)."""
    return ''.join(c if c.isascii() and (c.isalnum() or c in '_:.-') else '?' for c in str(exc))[:80]


class RetryOnce:
    """0.1.4: livesim_collect's RetryOnceClient rule. ONE re-read of the SAME call, only on 'response_truncated', charged
    (the wrapped call charges before sending) and logged in the calls log (retry=True); a second truncation raises."""

    def __init__(self, client, calls_log, retry=RETRY_ON_TRUNCATED):
        if retry not in (0, 1):
            raise SourceError('retry_on_truncated_is_0_or_1')
        self.client, self.calls_log, self.retry, self.retries = client, Path(calls_log), retry, 0

    @property
    def budget(self):
        return self.client.budget

    def call(self, method, params):
        try:
            return self.client.call(method, params)
        except RPC.RpcError as exc:
            if self.retry != 1 or str(exc) != 'response_truncated':
                raise
            self.retries += 1
            with open(self.calls_log, 'a') as handle:
                handle.write(RPC.canonical(dict(method=method, params_sha256=RPC.sha(params), retry=True,
                                                after='response_truncated')) + '\n')
            return self.client.call(method, params)


class TimedClient:
    """0.1.3: the frozen cpmmpilot.rpc.Client, wrapped (never modified): every call -- success or failure, budget refusal
    included -- appends one line to `timing_log`: method, params sha, start and end (wall clock), duration (monotonic
    clock, ms), ok, error (type and the first 80 characters of its message, never the endpoint: RpcError never echoes
    it). The frozen calls log keeps its own format."""

    def __init__(self, client, timing_log, *, wall=time.time, mono_ns=time.monotonic_ns):
        self.client, self.timing_log = client, Path(timing_log)
        self.wall, self.mono_ns = wall, mono_ns
        self.timing_log.parent.mkdir(parents=True, exist_ok=True)

    @property
    def budget(self):
        return self.client.budget

    def call(self, method, params):
        start_wall, start_ns = self.wall(), self.mono_ns()
        error = None
        try:
            return self.client.call(method, params)
        except Exception as exc:
            error = '%s:%s' % (type(exc).__name__, str(exc)[:80])
            raise
        finally:
            row = dict(method=method, params_sha256=RPC.sha(params), start_wall=start_wall, end_wall=self.wall(),
                       duration_ms=(self.mono_ns() - start_ns) / 1e6, ok=error is None, error=error)
            with open(self.timing_log, 'a') as handle:
                handle.write(J.canonical(row) + '\n')
