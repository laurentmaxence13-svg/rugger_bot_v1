"""RPC of the pilot. ``Client`` charges the budget BEFORE every call and logs every call (method, params sha, result
sha). ``FakeChain`` answers the six methods of the pilot from an in-memory chain (fixtures). ``LiveRpc`` is REFUSED in
0.1: nothing in this package can reach the network."""
import base64
import hashlib
import json

from . import layout as L


class RpcError(RuntimeError):
    pass


class MethodRefused(RpcError):
    """The provider refuses the method (e.g. GTFA on the Free plan): text B(b) -> STOP, no fallback."""


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


class LiveRpc:
    def __init__(self, *args, **kwargs):
        raise RpcError('live_rpc_disabled_in_cpmmpilot_0_1')


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
