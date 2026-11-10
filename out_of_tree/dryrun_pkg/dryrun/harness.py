"""Offline BUY -> hold -> SELL rehearsal around the frozen order builders.

Orders are built by ``bot.live.route.build_launchlab_order`` and checked by
``bot.live.unsigned_preflight.check_unsigned_order``; neither is modified. The
fill itself is a SHADOW FILL: exact curve arithmetic applied to a synthetic
bank and to a shadow position that exists only in the dry-run journal. Nothing
is signed, nothing is sent, no wallet is loaded and no fund moves.

The journal is the single commit point. In-memory state (bank, position,
simulated wallet) changes only by applying a record that was appended first, so
re-opening a journal on the same initial bank reproduces the state exactly.
"""
from dataclasses import asdict, dataclass, replace
import base64
import hashlib

from bot.live.cpmm_exit import build_cpmm_exit
from bot.live.route import (SYSTEM_PROGRAM, TOKEN_PROGRAM, associated_token_address,
                            build_launchlab_order, ephemeral_wsol_address)
from bot.live.unsigned_preflight import check_unsigned_order
from bot.market.launchlab_curve import CurveError
from bot.p3.certification import _decode

from .bank import curve_record
from .costs import CostModel, close_pnl, total
from .fixture_rpc import FixtureRpc
from .journal import DryRunJournal, JournalError, canonical

class Refusal(Exception):
    """The harness declined an operation; the reason is in the journal too."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class HarnessConfig:
    wallet: str                      # public address only; no key exists in the harness
    simulated_wallet_lamports: int   # simulated balance, no funds
    max_exposure_lamports: int       # cap on the open shadow position's entry cost
    max_loss_lamports: int           # cumulative realised loss that stops new BUYs
    genesis_hash: str
    endpoint_sha256: str
    recent_blockhash: str
    last_valid_block_height: int
    token_account_rent_lamports: int = 2_039_280
    slippage_bps: int = 100
    max_slippage_bps: int = 200
    max_price_impact_bps: int = 500
    costs: CostModel = CostModel()

    def __post_init__(self):
        for name in ('simulated_wallet_lamports', 'max_exposure_lamports', 'max_loss_lamports',
                     'last_valid_block_height', 'token_account_rent_lamports'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('invalid_' + name)
        if type(self.costs) is not CostModel:
            raise ValueError('invalid_costs')


@dataclass(frozen=True)
class ShadowPosition:
    """Inventory of the rehearsal. Not a position of the live execution journal."""
    quantity_atomic: int = 0
    principal_lamports: int = 0       # quote put into BUY orders, curve fee included
    curve_fee_lamports: int = 0       # part of the principal kept by the curve fee
    base_fee_lamports: int = 0
    priority_fee_lamports: int = 0
    failed_attempts: int = 0
    failed_attempts_lamports: int = 0
    rent_opened_lamports: int = 0     # token account opened by this position's first BUY

    @property
    def entry_cost_lamports(self):
        return (self.principal_lamports + self.base_fee_lamports + self.priority_fee_lamports
                + self.failed_attempts_lamports + self.rent_opened_lamports)


def _token_account(mint, owner, amount, lamports):
    """A plain initialised SPL token account, as the frozen tests synthesise it."""
    raw = bytearray(165)
    raw[:32], raw[32:64] = _decode(mint), _decode(owner)
    raw[64:72] = amount.to_bytes(8, 'little')
    raw[108] = 1
    return dict(owner=TOKEN_PROGRAM, executable=False, lamports=lamports,
                data=[base64.b64encode(bytes(raw)).decode(), 'base64'])


def closes_token_account(message, address):
    """True when the legacy message holds a Token CloseAccount (0x09) whose first account is ``address``."""
    def shortvec(position):
        value = shift = 0
        while True:
            byte = message[position]
            position += 1
            value |= (byte & 0x7f) << shift
            if byte < 0x80:
                return value, position
            shift += 7
    count, position = shortvec(3)
    keys = [message[position + 32 * i:position + 32 * i + 32] for i in range(count)]
    position += 32 * count + 32
    total_instructions, position = shortvec(position)
    target = _decode(address)
    for _ in range(total_instructions):
        program = keys[message[position]]
        size, position = shortvec(position + 1)
        indexes = message[position:position + size]
        length, position = shortvec(position + size)
        data = message[position:position + length]
        position += length
        if program == _decode(TOKEN_PROGRAM) and data == b'\x09' and indexes and keys[indexes[0]] == target:
            return True
    return False


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class DryRunHarness:
    def __init__(self, journal_path, bank, config, *, rpc, clock_ms):
        if not isinstance(rpc, FixtureRpc):
            raise ValueError('offline_fixture_rpc_required')
        if type(config) is not HarnessConfig or not callable(clock_ms):
            raise ValueError('explicit_configuration_and_clock_required')
        self.config, self.rpc, self.clock_ms = config, rpc, clock_ms
        self.bank = bank.copy()
        self.position = ShadowPosition()
        self.wallet_lamports = config.simulated_wallet_lamports
        self.realized_pnl_lamports = 0
        self.token_account_open = False
        self._decisions = {}
        self.journal = DryRunJournal(journal_path)
        opening = dict(config=asdict(config), mint=bank.mint, pool=bank.pool_address,
                       initial_bank_sha256=_sha256(canonical(bank.accounts).encode()),
                       initial_slot=bank.context_slot, wallet_balance_is_simulated=True)
        if not self.journal.records:
            self.journal.append('open', self._now(), **opening)
            return
        first = self.journal.records[0]
        if first['kind'] != 'open' or any(first.get(k) != v for k, v in opening.items()):
            raise JournalError('journal_opened_with_another_bank_or_configuration')
        for record in self.journal.records[1:]:
            self._apply(record)

    # ---- state -----------------------------------------------------------

    @property
    def stopped(self):
        """Read from the append-only journal; there is no setter and no reset."""
        return any(record['kind'] == 'emergency_stop' for record in self.journal.records)

    @property
    def pending(self):
        """Decisions with a built order and no shadow fill (e.g. after a crash)."""
        return sorted(d for d, known in self._decisions.items() if not known['filled'])

    def _now(self):
        now = self.clock_ms()
        if type(now) is not int or now < 0:
            raise ValueError('integer_millisecond_clock_required')
        return now

    def _commit(self, kind, **fields):
        record = self.journal.append(kind, self._now(), **fields)
        self._apply(record)
        return record

    def _apply(self, record):
        """The only place where bank, position and wallet change."""
        kind, decision = record['kind'], record.get('decision_id')
        if kind == 'order_built':
            known = self._decisions.setdefault(decision, dict(intent=record['intent'], filled=False))
            if known['filled'] or known['intent'] != record['intent']:
                raise JournalError('journal_decision_history_inconsistent')
        elif kind in ('shadow_fill', 'others_trade'):
            try:
                fill = self.bank.quote(record['side'], record['amount_in'])
            except CurveError:
                raise JournalError('journal_does_not_replay_on_this_bank') from None
            if ((fill.amount_out, fill.fee, curve_record(fill.after))
                    != (record['amount_out'], record['curve_fee_lamports'], record['curve_after'])):
                raise JournalError('journal_does_not_replay_on_this_bank')
            if kind == 'shadow_fill':
                known = self._decisions.get(decision)
                if not known or known['filled']:
                    raise JournalError('journal_fill_without_one_built_order')
                known['filled'] = True
                self.position = ShadowPosition(**record['position_after'])
                self.wallet_lamports = record['wallet_after_lamports']
                self.realized_pnl_lamports = record['realized_pnl_after_lamports']
                self.token_account_open = not record.get('base_token_account_closed', False)
            self.bank.apply(fill)
        elif kind == 'cpmm_exit_probe':
            self._decisions[decision] = dict(intent=None, filled=True)

    # ---- refusals ----------------------------------------------------------

    def _refuse(self, operation, reason, decision_id=None):
        self.journal.append('refusal', self._now(), operation=operation,
                            decision_id=decision_id, reason=reason)
        raise Refusal(reason)

    def _guard(self, operation, decision_id, intent):
        if (type(decision_id) is not str or not 1 <= len(decision_id) <= 128
                or any(not 33 <= ord(c) <= 126 for c in decision_id)):
            raise ValueError('stable_printable_decision_id_required')
        if self.stopped:
            self._refuse(operation, 'emergency_stop_active', decision_id)
        known = self._decisions.get(decision_id)
        if known and known['filled']:
            self._refuse(operation, 'duplicate_decision_id', decision_id)
        if known and known['intent'] != intent:
            self._refuse(operation, 'decision_id_reused_with_different_intent', decision_id)

    def _quote(self, operation, side, amount_in, decision_id=None):
        """Liquidity check before anything is built: exact, or refused with a reason."""
        try:
            return self.bank.quote(side, amount_in)
        except CurveError as error:
            self._refuse(operation, 'curve:' + str(error), decision_id)

    # ---- frozen builder and preflight ----------------------------------------

    def _request(self, decision_id, side, amount_in, now):
        c, rent = self.config, self.config.token_account_rent_lamports
        accounts = self.bank.snapshot()
        # Simulated balance, no funds: the wallet and its token account are
        # fixture observations, supplied the way the frozen tests supply them.
        accounts[c.wallet] = dict(owner=SYSTEM_PROGRAM, executable=False,
                                  data=['', 'base64'], lamports=self.wallet_lamports)
        accounts[associated_token_address(c.wallet, self.bank.mint)] = (
            _token_account(self.bank.mint, c.wallet, self.position.quantity_atomic, rent)
            if self.token_account_open else None)
        accounts[ephemeral_wsol_address(c.wallet, decision_id)[0]] = None
        return dict(
            accounts=accounts, pool_address=self.bank.pool_address, mint=self.bank.mint,
            wallet=c.wallet, context_slot=self.bank.context_slot, available_at_ms=now,
            decision_at_ms=now, side=side, amount_in=amount_in, slippage_bps=c.slippage_bps,
            max_slippage_bps=c.max_slippage_bps, max_price_impact_bps=c.max_price_impact_bps,
            recent_blockhash=c.recent_blockhash,
            last_valid_block_height=c.last_valid_block_height,
            rent_exempt_lamports=rent, base_ata_rent_lamports=rent, decision_id=decision_id,
            compute_unit_limit=c.costs.compute_unit_limit,
            priority_fee_micro_lamports=c.costs.priority_fee_micro_lamports,
            max_priority_fee_lamports=c.costs.priority_fee_lamports)

    async def _preflight(self, operation, decision_id, order):
        receipt = await check_unsigned_order(
            self.rpc, order, expected_genesis_hash=self.config.genesis_hash,
            expected_endpoint_sha256=self.config.endpoint_sha256, now_ms=self._now(),
            clock_ms=self._now)
        self._commit('preflight', decision_id=decision_id, result=receipt['result'],
                     reason=receipt['reason'], message_sha256=receipt['message_sha256'],
                     simulation_units=receipt.get('simulation_units'),
                     simulation_source='offline_fixture_rpc', simulated_by_rpc_node=False)
        if receipt['result'] != 'SIMULATION_SUCCEEDED_UNSENT':
            self._refuse(operation, 'preflight:' + receipt['reason'], decision_id)
        return receipt

    async def _order(self, decision_id, intent, fill, costs):
        """Build with the frozen builder, record the intent, then preflight."""
        side, amount_in = intent['side'], intent['amount_in']
        rent = self.config.token_account_rent_lamports
        request = self._request(decision_id, side, amount_in, self._now())
        try:
            order = build_launchlab_order(**request)
        except ValueError as error:  # the builder's own, unpatched refusal
            self._refuse(side, 'builder:' + str(error), decision_id)
        if (order.expected_output != fill.amount_out
                or order.network_fee_upper_lamports != self.config.costs.attempt_fee_lamports
                or order.rent_deposit_lamports != rent + costs['rent_opened_lamports']):
            self._refuse(side, 'builder_and_dry_run_arithmetic_disagree', decision_id)
        # The temporary WSOL account's rent comes back in the same transaction,
        # but the wallet must hold it, after any failed attempt was paid for.
        if (amount_in if side == 'BUY' else 0) + total(costs) + rent > self.wallet_lamports:
            self._refuse(side, 'simulated_wallet_insufficient_with_failed_attempts', decision_id)
        self._commit(
            'order_built', decision_id=decision_id, intent=intent,
            semantic_digest=order.semantic_digest,
            message_sha256=_sha256(order.transaction.message), source_slot=order.source_slot,
            expected_output=order.expected_output, minimum_out=order.minimum_out,
            price_impact_bps=order.price_impact_bps,
            network_fee_upper_lamports=order.network_fee_upper_lamports,
            rent_deposit_lamports=order.rent_deposit_lamports,
            source_account_digest=order.source_account_digest)
        await self._preflight(side, decision_id, order)
        return order

    def _fill_fields(self, decision_id, order, fill, costs):
        return dict(
            decision_id=decision_id, side=order.side, amount_in=fill.amount_in,
            amount_out=fill.amount_out, curve_fee_lamports=fill.fee,
            fee_rate_ppm=self.bank.fee_rate_ppm, share_fee_rate_ppm=0,
            curve_before=curve_record(fill.before), curve_after=curve_record(fill.after),
            bank_slot=self.bank.context_slot, semantic_digest=order.semantic_digest,
            minimum_out=order.minimum_out, costs=costs,
            temporary_wsol_rent_round_trip_lamports=self.config.token_account_rent_lamports,
            wallet_before_lamports=self.wallet_lamports, wallet_balance_is_simulated=True,
            fill_source='exact_curve_arithmetic_on_synthetic_bank')

    # ---- operations ----------------------------------------------------------

    async def buy(self, decision_id, amount_in):
        """Shadow BUY of ``amount_in`` lamports; returns the shadow-fill record."""
        intent = dict(side='BUY', amount_in=amount_in)
        self._guard('BUY', decision_id, intent)
        if -self.realized_pnl_lamports >= self.config.max_loss_lamports:
            self._refuse('BUY', 'loss_limit_reached', decision_id)
        fill = self._quote('BUY', 'BUY', amount_in, decision_id)
        costs = self.config.costs.order_costs(rent_opened_lamports=(
            0 if self.token_account_open else self.config.token_account_rent_lamports))
        spent = amount_in + total(costs)
        if self.position.entry_cost_lamports + spent > self.config.max_exposure_lamports:
            self._refuse('BUY', 'exposure_limit_exceeded', decision_id)
        order = await self._order(decision_id, intent, fill, costs)
        held = self.position
        position = replace(
            held, quantity_atomic=held.quantity_atomic + fill.amount_out,
            principal_lamports=held.principal_lamports + amount_in,
            curve_fee_lamports=held.curve_fee_lamports + fill.fee,
            base_fee_lamports=held.base_fee_lamports + costs['base_fee_lamports'],
            priority_fee_lamports=held.priority_fee_lamports + costs['priority_fee_lamports'],
            failed_attempts=held.failed_attempts + costs['failed_attempts'],
            failed_attempts_lamports=(held.failed_attempts_lamports
                                      + costs['failed_attempts_lamports']),
            rent_opened_lamports=held.rent_opened_lamports + costs['rent_opened_lamports'])
        return self._commit(
            'shadow_fill', **self._fill_fields(decision_id, order, fill, costs),
            wallet_after_lamports=self.wallet_lamports - spent,
            position_after=asdict(position), position_closed=False,
            realized_pnl_after_lamports=self.realized_pnl_lamports)

    async def sell(self, decision_id):
        """Shadow SELL of the whole shadow position; returns the fill with its P&L."""
        quantity = self.position.quantity_atomic
        intent = dict(side='SELL', amount_in=quantity)
        self._guard('SELL', decision_id, intent)
        if quantity == 0:
            self._refuse('SELL', 'no_shadow_inventory', decision_id)
        fill = self._quote('SELL', 'SELL', quantity, decision_id)
        costs = self.config.costs.order_costs(rent_opened_lamports=0)
        order = await self._order(decision_id, intent, fill, costs)
        # Rent comes back only if the built transaction itself closes the emptied base token account.
        closed = closes_token_account(order.transaction.message, order.base_token_account)
        recovered = self.config.token_account_rent_lamports if closed else 0
        pnl = close_pnl(self.position, sell_gross_lamports=fill.amount_out + fill.fee,
                        sell_curve_fee_lamports=fill.fee, sell_costs=costs, rent_recovered_lamports=recovered)
        return self._commit(
            'shadow_fill', **self._fill_fields(decision_id, order, fill, costs),
            wallet_after_lamports=self.wallet_lamports + fill.amount_out - total(costs) + recovered,
            base_token_account_closed=closed,
            position_after=asdict(ShadowPosition()), position_closed=True, pnl=pnl,
            realized_pnl_after_lamports=self.realized_pnl_lamports + pnl['net_pnl_lamports'])

    def hold(self, trades):
        """Advance the synthetic pool by exact-in trades of other participants.

        ``trades`` is a sequence of ``('BUY' | 'SELL', amount_in)``.
        """
        records = []
        for side, amount_in in trades:
            if self.stopped:
                self._refuse('HOLD', 'emergency_stop_active')
            fill = self._quote('HOLD', side, amount_in)
            records.append(self._commit(
                'others_trade', side=side, amount_in=amount_in, amount_out=fill.amount_out,
                curve_fee_lamports=fill.fee, curve_before=curve_record(fill.before),
                curve_after=curve_record(fill.after), bank_slot=self.bank.context_slot,
                trade_is_synthetic=True))
        return records

    def emergency_stop(self, reason):
        """Latch the stop. Deliberately, no method of this harness clears it."""
        if type(reason) is not str or not reason:
            raise ValueError('explicit_stop_reason_required')
        if not self.stopped:
            self._commit('emergency_stop', reason=reason)

    async def cpmm_exit_probe(self, request):
        """Build and preflight a CPMM exit from caller-supplied fixture accounts.

        No verified ``migrate_to_cpswap`` receipt links that CPMM pool to the
        shadow position, so this records an unsigned order only: the shadow
        inventory is not sold, not reduced and no P&L is computed.
        """
        decision_id = request.get('decision_id') if type(request) is dict else None
        self._guard('CPMM_EXIT_PROBE', decision_id, None)
        try:
            order = build_cpmm_exit(**request)
        except ValueError as error:
            self._refuse('CPMM_EXIT_PROBE', 'builder:' + str(error), decision_id)
        receipt = await self._preflight('CPMM_EXIT_PROBE', decision_id, order)
        return self._commit(
            'cpmm_exit_probe', decision_id=decision_id, pool=order.pool, mint=order.mint,
            program_id=receipt['program_id'], amount_in=order.input_amount,
            expected_output=order.expected_output, minimum_out=order.minimum_out,
            semantic_digest=order.semantic_digest, message_sha256=receipt['message_sha256'],
            migration_receipt_verified=False, bound_to_shadow_position=False,
            shadow_position_changed=False)
