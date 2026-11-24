"""RPC of the pilot. ``Client`` charges the budget BEFORE every call and logs every call (method, params sha, result
sha). ``FakeChain`` answers the six methods of the pilot from an in-memory chain (fixtures). ``LiveRpc`` (0.2) is the
JSON-RPC transport over HTTPS, written under R02 note fb28705b: it REFUSES to open unless the caller hands the file of an
authorization text whose sha256 is in ``AUTHORIZED_TEXT_SHA256`` -- EMPTY in 0.2, so no network call is possible from
this release; only a later audited release adds the sha anchored by R02 after the owner's texts A/B/C. The code reads no
host and no key (no environment variable, no file, no .env): the endpoint is an explicit argument, refused if it carries
credentials (user info, query, key-like path); the key is injected by the environment's proxy. No retry inside the
transport (every attempt is charged by ``Client`` before it leaves); every failure is an ``RpcError`` that never echoes
the endpoint or the provider's message."""
import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import layout as L


class RpcError(RuntimeError):
    error_text = None             # 0.2.5: the provider's message, lower-cased and REDACTED (redact_error_text), or None


def redact_error_text(text):
    """R02 f2e62c72 (c): lower case; any whitespace-free segment containing 'http', 'api' or 'key', or longer than 32
    characters, is masked; then cut to 200 characters. Only this redacted text is ever recorded."""
    out = []
    for seg in str(text).lower().split():
        out.append(REDACT_MARK if ('http' in seg or 'api' in seg or 'key' in seg or len(seg) > 32) else seg)
    return ' '.join(out)[:ERROR_TEXT_MAX]


class MethodRefused(RpcError):
    """The provider refuses the method (e.g. GTFA on the Free plan): text B(b) -> STOP, no fallback."""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


# sha256 of the authorization texts ANCHORED by R02 (owner's texts, verified at the source). 0.2 was EMPTY. 0.2.1: the
# owner's texts B and C of v1.3 (event b1f263a6, 24/11 07:00:22Z, verified VALID by R02), canonical file = the exact
# UTF-8 bytes of message.content, no final newline, 2 175 bytes (AUTORISATION_B_C_v1_3.txt). Never modified at run time.
AUTHORIZED_TEXT_SHA256 = frozenset({'e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1'})
PILOT_METHODS = ('getSlot', 'getProgramAccounts', 'getMultipleAccounts', 'getSignaturesForAddress', 'getTransaction',
                 'getTransactionsForAddress')                              # the priced methods of budget.COSTS (test)
MAX_RESPONSE_BYTES = 256 * 1024 ** 2
MIN_INTERVAL_S = 0.2           # 0.2.2 (R02 note 41c20a16): <= 5 requests/s, within Free's 10 req/s and 5 gPA/s
MAX_TX_VERSION = 1             # 0.2.5 (R02 erratum f2e62c72): v1 transactions (Agave 4.2) are returned, not refused
TX_VERSION_WORDS = 'transaction version'
REDACT_MARK = '[masque]'
ERROR_TEXT_MAX = 200
REFUSAL_WORDS = ('plan', 'upgrade', 'not available', 'not supported', 'paid')
METHOD_NOT_FOUND = -32601


def _file_sha(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def check_endpoint(endpoint):
    """https only; no user info, query, fragment or key-like path (a key in the URL would land in logs)."""
    if type(endpoint) is not str:
        raise RpcError('endpoint_must_be_a_string')
    u = urllib.parse.urlsplit(endpoint)
    if u.scheme != 'https' or not u.hostname:
        raise RpcError('endpoint_must_be_https')
    if u.username or u.password or u.query or u.fragment:
        raise RpcError('endpoint_must_not_carry_credentials')
    if any(w in u.path.lower() for w in ('key', 'token', 'secret')):
        raise RpcError('endpoint_must_not_carry_credentials')
    return endpoint


class LiveRpc:
    """JSON-RPC 2.0 over HTTPS. ``opener`` (tests): a callable (request, timeout) -> response with ``read(n)``."""

    def __init__(self, endpoint=None, *, authorization_file=None, timeout_s=60, opener=None, clock=None, sleep=None):
        if authorization_file is None:
            raise RpcError('live_rpc_needs_an_anchored_authorization')
        try:
            digest = _file_sha(authorization_file)
        except OSError as exc:
            raise RpcError('authorization_file_unreadable') from exc
        if digest not in AUTHORIZED_TEXT_SHA256:
            raise RpcError('authorization_not_anchored')
        self._endpoint = check_endpoint(endpoint)
        self.authorization_sha256 = digest
        self.timeout_s = timeout_s
        self._open = opener if opener is not None else urllib.request.build_opener().open
        self._clock = clock if clock is not None else time.monotonic
        self._sleep = sleep if sleep is not None else time.sleep
        self._last_sent = None
        self.requests = 0

    def __repr__(self):
        return 'LiveRpc(authorization_sha256=%s)' % self.authorization_sha256       # never the endpoint

    def request(self, method, params):
        if method not in PILOT_METHODS:
            raise RpcError('method_not_in_pilot')
        if self._last_sent is not None:                                       # spacing: never two sends < 0.2 s apart
            wait = self._last_sent + MIN_INTERVAL_S - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_sent = self._clock()
        self.requests += 1
        rid = self.requests
        body = json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params)).encode()
        req = urllib.request.Request(self._endpoint, data=body, method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            response = self._open(req, timeout=self.timeout_s)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RpcError('rate_limited_429') from None
            if exc.code in (401, 403):
                raise RpcError('unauthorized_%d' % exc.code) from None
            raise RpcError('http_%d' % exc.code) from None
        except (urllib.error.URLError, OSError, ValueError):
            raise RpcError('network_error') from None                         # no detail: it may name the host
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RpcError('response_too_large')
        try:
            payload = json.loads(raw)
        except ValueError:
            raise RpcError('response_truncated') from None
        if not isinstance(payload, dict) or payload.get('id') != rid:
            raise RpcError('response_id_mismatch')
        if payload.get('error') is not None:
            err = payload['error'] if isinstance(payload['error'], dict) else {}
            code = err.get('code')
            text = str(err.get('message', '')).lower()
            tag = '%s:%s' % (code, hashlib.sha256(text.encode()).hexdigest()[:12])   # the message is hashed, never echoed
            if TX_VERSION_WORDS in text:                                    # never a method refusal (R02 f2e62c72)
                exc = RpcError('tx_version_unsupported:' + tag)
            elif code == METHOD_NOT_FOUND or any(w in text for w in REFUSAL_WORDS):
                exc = MethodRefused('method_refused:' + tag)
            else:
                exc = RpcError('rpc_error:' + tag)
            exc.error_text = redact_error_text(text)
            raise exc
        if 'result' not in payload:
            raise RpcError('response_without_result')
        return payload['result']


class Client:
    def __init__(self, transport, budget, calls_log):
        self.transport, self.budget, self.calls_log = transport, budget, calls_log

    def call(self, method, params):
        self.budget.charge(method, params)              # ledger on disk before the request leaves
        result = self.transport.request(method, params)
        with open(self.calls_log, 'a') as handle:
            handle.write(canonical(dict(method=method, params_sha256=sha(params), result_sha256=sha(result),
                                        credits_after=self.budget.credits)) + '\n')
        return result


class FakeChain:
    """accounts: {address: {'owner': program, 'data': bytes}}; history: {address: [tx, ...]} (any order);
    transactions carry slot, blockTime, transactionIndex, meta and transaction.signatures."""

    def __init__(self, accounts, history, *, slot, block_time, gtfa_refused=False, truncate_program_accounts=False):
        self.accounts, self.slot, self.block_time = accounts, slot, block_time
        self.history = {a: sorted(txs, key=lambda t: (t['slot'], t['transactionIndex'])) for a, txs in history.items()}
        self.by_signature = {t['transaction']['signatures'][0]: t for txs in self.history.values() for t in txs}
        self.gtfa_refused, self.truncate = gtfa_refused, truncate_program_accounts
        self.requests = 0

    def request(self, method, params):
        self.requests += 1
        return getattr(self, '_' + method)(*params)

    def _context(self, value):
        return dict(context=dict(slot=self.slot), value=value)

    @staticmethod
    def _encoded(data):
        return [base64.b64encode(data).decode(), 'base64']

    def _getSlot(self, *_):
        return self.slot

    def _getProgramAccounts(self, program, options):
        if self.truncate:
            raise RpcError('response_truncated')
        out = []
        for address, account in sorted(self.accounts.items()):
            data = account['data']
            if account['owner'] != program:
                continue
            ok = True
            for f in options.get('filters', []):
                if 'dataSize' in f:
                    ok &= len(data) == f['dataSize']
                else:
                    m = f['memcmp']
                    want = L.b58decode_any(m['bytes'])
                    ok &= data[m['offset']:m['offset'] + len(want)] == want
            if ok:
                sl = options.get('dataSlice')
                view = data[sl['offset']:sl['offset'] + sl['length']] if sl else data
                out.append(dict(pubkey=address, account=dict(owner=program, data=self._encoded(view))))
        return self._context(out) if options.get('withContext') else out

    def _getMultipleAccounts(self, addresses, options):
        if len(addresses) > 100:
            raise RpcError('too_many_accounts')
        return self._context([None if a not in self.accounts else dict(
            owner=self.accounts[a]['owner'], data=self._encoded(self.accounts[a]['data'])) for a in addresses])

    def _getSignaturesForAddress(self, address, options):
        txs = [t for t in reversed(self.history.get(address, [])) if t['slot'] <= self.slot]
        sigs = [t['transaction']['signatures'][0] for t in txs]
        start = sigs.index(options['before']) + 1 if options.get('before') else 0
        out = []
        for t in txs[start:start + options.get('limit', 1000)]:
            out.append(dict(signature=t['transaction']['signatures'][0], slot=t['slot'], blockTime=t['blockTime'],
                            err=t['meta'].get('err')))
        return out

    def _getTransaction(self, signature, options):
        return self.by_signature.get(signature)

    def _getTransactionsForAddress(self, address, options):
        if self.gtfa_refused:
            raise MethodRefused('method_not_available_on_plan')
        txs = [t for t in self.history.get(address, []) if t['slot'] <= self.slot]
        bt = (options.get('filters') or {}).get('blockTime') or {}
        txs = [t for t in txs if bt.get('gte', -1) <= t['blockTime'] and t['blockTime'] < bt.get('lt', 1 << 62)]
        if options.get('sortOrder') == 'desc':
            txs = list(reversed(txs))
        start = int(options.get('paginationToken') or 0)
        page = txs[start:start + options['limit']]
        token = str(start + len(page)) if start + len(page) < len(txs) else None
        return dict(data=page, paginationToken=token)
