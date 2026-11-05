"""Bounded public quote reader for the active PAPER inventory integration.

The caller owns the anonymous transport and a new dedicated CaptureStore.
There is no transaction, wallet, fee estimate, retry or endpoint fallback here.
Quotes remain indicative observations, including when their output is retained
as a projected PAPER lot. Unknown execution costs never become zero costs.
"""
import asyncio
import re
import time
import uuid

from bot.p3.collect import (
    ReadOnlyPolicyError, ReadOnlySession, _environment_proxy,
    _quote_with_cancellation_receipt, _record_quote,
)
from bot.p3.quotes import RaydiumQuoteClient, SOL_MINT, _atomic, _mint
from bot.p3.store import CaptureStore


class _DeadlineQuoteSession(ReadOnlySession):
    def __init__(self, session, max_requests, deadline):
        self.deadline = deadline
        def resolve_proxy(url):
            proxy = _environment_proxy(url)
            # Proxy resolution is synchronous and can outlast the first check.
            # Never dispatch a request after that work exhausted the deadline.
            if time.monotonic() >= self.deadline:
                raise ReadOnlyPolicyError('Inventory quote deadline exhausted during proxy resolution')
            if getattr(session, '_retry_connection', None) is not False:
                raise ReadOnlyPolicyError('Inventory quote transport must disable retries')
            return proxy
        super().__init__(session, max_requests, proxy_resolver=resolve_proxy)

    def get(self, url, **kwargs):
        # Recheck immediately before transport, not just before scheduling the
        # coroutine: lock waiting or event-loop load must not extend the budget.
        if time.monotonic() >= self.deadline:
            raise ReadOnlyPolicyError('Inventory quote deadline exhausted')
        if getattr(self.session, '_retry_connection', None) is not False:
            raise ReadOnlyPolicyError('Inventory quote transport must disable retries')
        return super().get(url, **kwargs)


class NativeInventoryQuoteProvider:
    """Observe at most 20 exact-size quotes within 60 seconds of construction.

    The standalone default stops after any unavailable/error/refused response.
    A preregistered campaign may retain HTTP-200 business refusals and continue
    its fixed schedule, sharing the exact global request counter and deadline.
    Exhausted/stopped calls return None without another request. Cancellation
    retains the bounded receipt and propagates. The PAPER engine chooses the
    amount before awaiting and adds its inventory version/decision afterwards.
    """

    def __init__(self, session, store, *, max_requests=20, shared_session=None,
                 append=None, stop_on_provider_rejection=True):
        if not isinstance(store, CaptureStore):
            raise TypeError('A dedicated CaptureStore is required')
        if type(stop_on_provider_rejection) is not bool:
            raise ValueError('Quote refusal policy must be explicit')
        if append is not None and not callable(append):
            raise TypeError('Capture append callback must be callable')
        self.started_monotonic = time.monotonic()
        self.deadline_monotonic = self.started_monotonic+60
        if shared_session is None:
            self._session = _DeadlineQuoteSession(session, max_requests, self.deadline_monotonic)
        else:
            from bot.p3.campaign import CampaignSession
            deadline = getattr(shared_session, '_deadline_ns', None)
            if (not isinstance(shared_session, CampaignSession)
                    or shared_session.session is not session
                    or type(max_requests) is not int or max_requests != 20
                    or shared_session.max_requests != max_requests
                    or type(deadline) is not int or deadline <= 0
                    or deadline-time.monotonic_ns() > 60_000_000_000):
                raise ValueError('Shared campaign requires the same transport, 20-call cap and fixed deadline')
            # No wrapper, fresh quota or fresh timer around this session. Its
            # discovery/RPC/quote calls all debit this exact shared counter.
            self._session = shared_session
            self.deadline_monotonic = deadline/1_000_000_000
        self._store = store
        self._append = append
        self._stop_on_provider_rejection = stop_on_provider_rejection
        self._lock = asyncio.Lock()
        self.stopped_reason = None

    @property
    def requests_used(self):
        return self._session.requests_used

    def _ready(self):
        if self.stopped_reason is not None:
            return False
        if time.monotonic() >= self.deadline_monotonic:
            self.stopped_reason = 'inventory_quote_deadline_exhausted'
        elif self.requests_used >= self._session.max_requests:
            self.stopped_reason = 'inventory_quote_request_budget_exhausted'
        elif getattr(self._session.session, '_retry_connection', None) is not False:
            self.stopped_reason = 'inventory_quote_transport_retry_policy_unsafe'
        return self.stopped_reason is None

    @staticmethod
    def _metadata(value):
        if value is None:
            return {}
        if type(value) is not dict or set(value)-{
                'probe_phase', 'exit_scope', 'inventory_buy_observation_id', 'prospective_ordinal'}:
            raise ValueError('Unsupported inventory quote observation metadata')
        result = dict(value)
        for key, item in result.items():
            if key in ('probe_phase', 'exit_scope'):
                if type(item) is not str or re.fullmatch(r'[A-Za-z0-9_:-]{1,64}', item) is None:
                    raise ValueError('Invalid inventory quote observation label')
            elif (type(item) is not int or not (1 if key == 'inventory_buy_observation_id' else 0)
                  <= item < 2**63):
                raise ValueError('Invalid inventory quote observation identifier')
        return result

    async def __call__(self, session_ignored, mint, *, side, amount_atomic,
                       inventory, decision_at_ms, observation_metadata=None):
        # Serialize consumers so a second request cannot race past the first
        # refusal before its latch has been recorded.
        async with self._lock:
            if not self._ready():
                return None
            try:
                metadata = self._metadata(observation_metadata)
                mint, amount = _mint(mint), _atomic(amount_atomic)
                if mint == SOL_MINT or side not in ('buy', 'sell'):
                    raise ValueError('Invalid inventory quote side or mint')
                if type(decision_at_ms) is not int or decision_at_ms < 0:
                    raise ValueError('Invalid inventory decision time')
                if side == 'sell':
                    if (type(inventory) is not dict
                            or _atomic(inventory.get('remaining_atomic')) != amount
                            or inventory.get('mint', mint) != mint):
                        raise ValueError('Sell size must exactly match persisted remaining inventory')
                elif inventory is not None:
                    raise ValueError('A buy quote cannot replace existing inventory')
            except (ValueError, TypeError):
                self.stopped_reason = 'invalid_inventory_quote_request'
                raise
            input_mint, output_mint = (SOL_MINT, mint) if side == 'buy' else (mint, SOL_MINT)
            identities = []
            def append(kind, **record):
                # Also annotate cancellation/policy-fallback receipts. Optional
                # metadata never replaces normalization or provenance fields.
                if metadata and kind == 'quote_attempt':
                    record['payload'] = dict(record['payload'], **metadata)
                identity = (self._append(kind, **record) if self._append is not None else
                            self._store.append(kind, provenance='live', **record))
                identities.append(identity)
                return identity
            remaining = self.deadline_monotonic-time.monotonic()
            if remaining <= 0:
                self.stopped_reason = 'inventory_quote_deadline_exhausted'
                return None
            client = RaydiumQuoteClient(self._session, timeout_seconds=min(8, remaining))
            request_id = str(uuid.uuid4())
            try:
                quote = await asyncio.wait_for(_quote_with_cancellation_receipt(
                    client, append, input_mint, output_mint, amount, side, request_id),
                    timeout=remaining)
            except asyncio.TimeoutError:
                self.stopped_reason = 'inventory_quote_deadline_exhausted'
                return None
            except asyncio.CancelledError:
                self.stopped_reason = 'inventory_quote_cancelled'
                raise
            except Exception:
                self.stopped_reason = 'inventory_quote_unexpected_error'
                raise
            try:
                retained = _record_quote(append, quote, side, request_id)
                # Read the committed journal envelope, including its
                # availability barrier, rather than inventing one here.
                event = next((event for event in self._store.events(kind='quote_attempt')
                              if event['id'] == identities[-1]), None)
                if event is None:
                    raise RuntimeError('Committed inventory quote receipt is unavailable')
            except Exception:
                self.stopped_reason = 'inventory_quote_persistence_error'
                raise
            logical_refusal = (retained and event['outcome'] == 'unavailable'
                and event.get('reason') in ('provider_rejected', 'route_unavailable')
                and event['payload'].get('http_status') == 200)
            if ((not retained or event['outcome'] != 'quoted')
                    and (self._stop_on_provider_rejection or not logical_refusal)):
                self.stopped_reason = event.get('reason') or 'inventory_quote_unavailable'
            context = {'fees':None, 'token_decimals':None, 'max_source_age_ms':5000,
                       'acquisition_verified':False, 'execution_verified':False}
            if side == 'buy':
                context.update(buy_observation=event, basis='expected_buy_output')
            else:
                context.update(sell_observation=event, requested_quantity_atomic=amount)
            return context
