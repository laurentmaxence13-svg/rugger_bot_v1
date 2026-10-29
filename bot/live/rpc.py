"""Explicit, bounded Solana JSON-RPC adapter, inactive on construction.

The transport is injected; this module never starts a scanner or obtains keys.
Sending requires a separate transport admission callback as well as the engine's
owner envelope. Timeouts have unknown submission outcome and are never retried.
"""
import asyncio
import base64
import time
from urllib.parse import urlsplit

import aiohttp


class RpcError(RuntimeError):
    pass


READ_METHODS = frozenset(('getGenesisHash', 'getLatestBlockhash', 'getBlockHeight',
    'simulateTransaction', 'getSignatureStatuses', 'getTransaction', 'getBalance',
    'getTokenAccountBalance', 'getMultipleAccounts', 'getFeeForMessage',
    'getMinimumBalanceForRentExemption'))


class HttpJsonRpcTransport:
    """Use a caller-owned verified-TLS session and its managed HTTP proxy.

    No URL, error body, transaction payload or credentials are put in exception
    strings. A runtime supervisor must supply fresh submission admission; setting
    an environment variable or creating this object cannot enable transmission.
    """
    def __init__(self, session, *, endpoint, proxy, max_requests=20,
                 max_elapsed_seconds=60, submission_authorizer=None):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.port not in (None, 443)):
            raise ValueError('Explicit HTTPS endpoint without embedded credentials required')
        p = urlsplit(proxy)
        if (p.scheme != 'http' or not p.hostname or p.username or p.password
                or p.query or p.fragment or p.path not in ('', '/')):
            raise ValueError('Explicit anonymous managed proxy required')
        if (type(max_requests) is not int or not 1 <= max_requests <= 1000
                or type(max_elapsed_seconds) not in (int, float)
                or not 0 < max_elapsed_seconds <= 60):
            raise ValueError('Bounded transport budget required')
        self.session = session
        self.endpoint = endpoint
        self.proxy = proxy
        self.max_requests = max_requests
        self.used = 0
        self.deadline = time.monotonic() + max_elapsed_seconds
        self.submission_authorizer = submission_authorizer
        self.stopped = False

    async def __call__(self, method, params):
        if method not in READ_METHODS and method != 'sendTransaction':
            raise RpcError('RPC method outside execution adapter scope')
        if method == 'sendTransaction':
            try:
                raw = base64.b64decode(params[0], validate=True)
                admitted = (self.submission_authorizer is not None
                    and self.submission_authorizer(raw) is True)
            except (ValueError, TypeError, IndexError):
                admitted = False
            if not admitted:
                raise RpcError('Independent transport submission admission missing')
        remaining = self.deadline-time.monotonic()
        if self.stopped or self.used >= self.max_requests or remaining <= 0:
            raise RpcError('Transport stopped or budget exhausted')
        self.used += 1
        request_id = self.used
        timeout = aiohttp.ClientTimeout(total=min(8, remaining), connect=min(4, remaining),
            sock_connect=min(3, remaining), sock_read=min(4, remaining),
            ceil_threshold=float('inf'))
        try:
            async with self.session.post(self.endpoint,
                    json=dict(jsonrpc='2.0', id=request_id, method=method, params=params),
                    proxy=self.proxy, allow_redirects=False, timeout=timeout) as response:
                if response.status != 200:
                    raise RpcError('RPC HTTP response refused')
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > 4*1024*1024:
                        raise RpcError('RPC response exceeds retained body limit')
            import json
            value = json.loads(body)
            if (type(value) is not dict or value.get('jsonrpc') != '2.0'
                    or type(value.get('id')) is not int or value['id'] != request_id
                    or 'error' in value or 'result' not in value):
                raise RpcError('Invalid or failed RPC envelope')
            return value['result']
        except BaseException as error:
            self.stopped = True
            if isinstance(error, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            raise RpcError('RPC transport failed; outcome may be unknown') from None


def _uint(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64:
        raise RpcError('Invalid exact unsigned RPC integer')
    return value


def _pubkey(value):
    from bot.p3.certification import _decode
    try:
        if type(value) is not str or len(_decode(value)) != 32:
            raise ValueError()
    except (TypeError, ValueError):
        raise RpcError('Invalid Solana public identity') from None
    return value


def _signature(value):
    from bot.p3.platform_admin_history import _signature as validate
    try:
        return validate(value)
    except (ValueError,TypeError):
        raise RpcError('Invalid Solana signature identity') from None


class SolanaRpc:
    """RPC contract used by the persistent execution engine (no implicit retries)."""
    def __init__(self, transport):
        self.transport = transport

    @property
    def endpoint_sha256(self):
        import hashlib
        endpoint=getattr(self.transport,'endpoint',None)
        if type(endpoint) is not str:
            raise RpcError('Concrete RPC endpoint binding unavailable')
        return hashlib.sha256(endpoint.encode('utf-8')).hexdigest()

    async def genesis_hash(self):
        return _pubkey(await self.transport('getGenesisHash', []))

    async def get_latest_blockhash(self):
        result = await self.transport('getLatestBlockhash', [dict(commitment='confirmed')])
        value = result['value']
        return dict(blockhash=_pubkey(value['blockhash']),
            last_valid_block_height=_uint(value['lastValidBlockHeight'], positive=True),
            context_slot=_uint(result['context']['slot'], positive=True))

    async def get_block_height(self):
        return _uint(await self.transport('getBlockHeight', [dict(commitment='confirmed')]), positive=True)

    @staticmethod
    def _encoded(raw):
        if type(raw) is not bytes or not 65 <= len(raw) <= 1232:
            raise RpcError('Serialized bounded Solana transaction required')
        return base64.b64encode(raw).decode('ascii')

    async def simulate_transaction(self, raw, *, sig_verify, min_context_slot=None):
        if type(sig_verify) is not bool:
            raise RpcError('Explicit simulation signature verification flag required')
        options=dict(encoding='base64', commitment='confirmed', sigVerify=sig_verify,
                     replaceRecentBlockhash=False)
        if min_context_slot is not None:
            options['minContextSlot']=_uint(min_context_slot,positive=True)
        result = await self.transport('simulateTransaction', [self._encoded(raw),options])
        if (type(result) is not dict or type(result.get('value')) is not dict
                or 'err' not in result['value']):
            raise RpcError('Malformed simulation result')
        slot=_uint(result.get('context',{}).get('slot'),positive=True)
        if min_context_slot is not None and slot<min_context_slot:
            raise RpcError('Simulation bank precedes causal source')
        return dict(result['value'],context_slot=slot)

    async def send_transaction(self, raw):
        result = await self.transport('sendTransaction', [self._encoded(raw),
            dict(encoding='base64', skipPreflight=False, preflightCommitment='confirmed', maxRetries=0)])
        return _signature(result)

    async def signature_status(self, signature):
        _signature(signature)
        result = await self.transport('getSignatureStatuses', [[signature], dict(searchTransactionHistory=True)])
        values = result.get('value') if type(result) is dict else None
        if type(values) is not list or len(values) != 1:
            raise RpcError('Malformed signature status result')
        status = values[0]
        if status is None:
            return None
        if (type(status) is not dict or 'err' not in status
                or status.get('confirmationStatus') not in ('processed', 'confirmed', 'finalized')):
            raise RpcError('Malformed signature finality')
        _uint(status.get('slot'), positive=True)
        return status

    async def get_transaction(self, signature):
        _signature(signature)
        value = await self.transport('getTransaction', [signature,
            dict(encoding='json', commitment='finalized', maxSupportedTransactionVersion=0)])
        if value is not None and type(value) is not dict:
            raise RpcError('Malformed finalized transaction')
        return value

    async def get_balance(self, wallet):
        result = await self.transport('getBalance', [_pubkey(wallet), dict(commitment='finalized')])
        return _uint(result['value'])

    async def get_token_account_balance(self, address):
        result = await self.transport('getTokenAccountBalance', [_pubkey(address), dict(commitment='finalized')])
        amount = result['value']['amount']
        if type(amount) is not str or not amount.isascii() or not amount.isdecimal() or str(int(amount)) != amount:
            raise RpcError('Noncanonical token amount')
        return _uint(int(amount))

    async def get_multiple_accounts(self, addresses, *, min_context_slot):
        if type(addresses) not in (list, tuple) or not 1 <= len(addresses) <= 100:
            raise RpcError('Bounded exact account list required')
        result = await self.transport('getMultipleAccounts', [list(map(_pubkey, addresses)),
            dict(encoding='base64', commitment='confirmed', minContextSlot=_uint(min_context_slot, positive=True))])
        slot = _uint(result['context']['slot'], positive=True)
        if slot < min_context_slot or type(result.get('value')) is not list or len(result['value']) != len(addresses):
            raise RpcError('Bank below causal slot or account count mismatch')
        return result

    async def fee_for_message(self, message):
        if type(message) is not bytes or not message or len(message) > 1232:
            raise RpcError('Bounded serialized message required')
        result = await self.transport('getFeeForMessage', [base64.b64encode(message).decode(), dict(commitment='confirmed')])
        return None if result['value'] is None else _uint(result['value'])

    async def get_fee_for_message(self, message):
        return await self.fee_for_message(message)

    async def rent_exemption(self, account_bytes):
        if type(account_bytes) is not int or not 0 < account_bytes <= 10485760:
            raise RpcError('Bounded exact account size required')
        return _uint(await self.transport('getMinimumBalanceForRentExemption', [account_bytes, dict(commitment='confirmed')]))
