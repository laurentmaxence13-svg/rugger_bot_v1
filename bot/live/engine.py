"""LaunchLab/CPMM lifecycle, inactive without explicit financial authority.

Transport, isolated signer and fresh admission evidence are injected services.
There is no key loader, automatic arming, fallback route, transaction rebuild or
blind send retry. Tests use explicitly isolated signers/RPCs, never a wallet.
"""
import base64
import asyncio
from dataclasses import asdict
import hashlib
import json
import time
from typing import Protocol

from bot.p3.certification import PROGRAM, _decode, _encode
from .journal import ACTIVE, ExecutionJournal, canonical, uint
from .route_dispatch import (validate_execution_order, execution_program,
                             route_kind, order_inventory_pool)
from .safety import AdmissionRequest, HealthEvidence, Mode, evaluate_admission
from .wire import shortvec


class IsolatedSigner(Protocol):
    """External sign-only service; private material never enters this engine."""
    @property
    def public_key(self) -> str: ...
    async def sign_message(self, message: bytes) -> bytes: ...


class Ed25519Verifier:
    """Audited cryptographic verification, never a structural signature check."""
    def verify(self, public_key, message, signature):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError:
            raise RuntimeError('audited_ed25519_verifier_dependency_missing') from None
        if type(message) is not bytes or type(signature) is not bytes or len(signature) != 64:
            raise ValueError('exact_ed25519_message_and_signature_required')
        try:
            Ed25519PublicKey.from_public_bytes(_decode(public_key)).verify(signature, message)
        except Exception:
            raise ValueError('external_signature_invalid') from None


def _base58_bytes(value):
    if type(value) is not str or not value:
        raise ValueError('compiled_instruction_data_required')
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number = 0
    for character in value:
        if character not in alphabet:
            raise ValueError('compiled_instruction_data_invalid')
        number = number * 58 + alphabet.index(character)
    raw = b'\0' * (len(value) - len(value.lstrip('1')))
    raw += number.to_bytes((number.bit_length() + 7) // 8, 'big')
    if _encode(raw) != value:
        raise ValueError('compiled_instruction_data_noncanonical')
    return raw


def message_from_rpc(transaction):
    """Reconstruct the exact legacy message from getTransaction(encoding=json)."""
    message = transaction.get('message')
    if type(message) is not dict or 'addressTableLookups' in message:
        raise ValueError('raw_legacy_rpc_message_required')
    header = message.get('header')
    if type(header) is not dict:
        raise ValueError('raw_legacy_rpc_header_required')
    counts = tuple(header.get(k) for k in ('numRequiredSignatures',
        'numReadonlySignedAccounts', 'numReadonlyUnsignedAccounts'))
    if any(type(n) is not int or not 0 <= n < 256 for n in counts):
        raise ValueError('raw_legacy_rpc_header_invalid')
    keys = message.get('accountKeys')
    if type(keys) is not list or not keys or len(keys) > 256 or len(set(keys)) != len(keys):
        raise ValueError('raw_legacy_rpc_account_keys_required')
    raw = bytes(counts) + shortvec(len(keys)) + b''.join(_decode(k) for k in keys)
    raw += _decode(message.get('recentBlockhash'))
    instructions = message.get('instructions')
    if type(instructions) is not list or not instructions:
        raise ValueError('compiled_rpc_instructions_required')
    raw += shortvec(len(instructions))
    for ix in instructions:
        if type(ix) is not dict or 'parsed' in ix:
            raise ValueError('unparsed_rpc_instruction_required')
        program_index, accounts = ix.get('programIdIndex'), ix.get('accounts')
        if (type(program_index) is not int or not 0 <= program_index < len(keys)
                or type(accounts) is not list
                or any(type(a) is not int or not 0 <= a < len(keys) for a in accounts)):
            raise ValueError('compiled_rpc_indices_invalid')
        data = b'' if ix.get('data') == '' else _base58_bytes(ix.get('data'))
        raw += bytes((program_index,)) + shortvec(len(accounts)) + bytes(accounts)
        raw += shortvec(len(data)) + data
    return raw


def order_record(order):
    record = asdict(order)
    record['transaction']['message'] = base64.b64encode(order.transaction.message).decode()
    record['transaction']['account_keys'] = list(order.transaction.account_keys)
    record['transaction']['required_signers'] = list(order.transaction.required_signers)
    record['source_pins'] = list(order.source_pins)
    return record


def _amount(value):
    if type(value) is not str or not value.isascii() or not value.isdigit() or str(int(value)) != value:
        raise ValueError('canonical_atomic_token_amount_required')
    amount = int(value)
    if not 0 <= amount < 2**64:
        raise ValueError('atomic_token_amount_overflow')
    return amount


def reconcile_transaction(row, payload):
    """Bind final chain metadata to signed message, exact inventory and costs."""
    if type(payload) is not dict or payload.get('version', 'legacy') not in ('legacy', None):
        raise ValueError('finalized_legacy_transaction_required')
    order = json.loads(row['order_json'])
    inventory_pool=order_inventory_pool(order)
    if order.get('route_kind')=='CPMM':
        # A changed serialized record must never make an unrelated signed
        # message settle the held LaunchLab position. Rebuild the exact CPMM
        # route independently of the submitted/signature metadata.
        from .cpmm_exit import build_cpmm_exit
        try:
            rebuilt=build_cpmm_exit(**json.loads(order['rebuild_request_json']))
            core=order_record(rebuilt)
            if canonical({k:order.get(k) for k in core})!=canonical(core):
                raise ValueError('serialized_CPMM_order_changed')
        except (TypeError,KeyError,ValueError,OverflowError):
            raise ValueError('finalized_CPMM_route_record_invalid') from None
    transaction, meta = payload.get('transaction'), payload.get('meta')
    if type(transaction) is not dict or type(meta) is not dict:
        raise ValueError('finalized_transaction_metadata_missing')
    if transaction.get('signatures') != [row['signature']]:
        raise ValueError('finalized_signature_binding_failed')
    if message_from_rpc(transaction) != base64.b64decode(order['transaction']['message'], validate=True):
        raise ValueError('finalized_message_differs_from_signed_intent')
    keys = transaction['message']['accountKeys']
    wallet_index, base_index = keys.index(order['user']), keys.index(order['base_token_account'])
    before, after = meta.get('preBalances'), meta.get('postBalances')
    if type(before) is not list or type(after) is not list or len(before) != len(keys) or len(after) != len(keys):
        raise ValueError('complete_native_balances_required')
    for value in before + after:
        uint(value)
    # RPC token-balance entries are indexed into the exact signed message.
    # Reject boolean indices (bool is an int subclass), duplicates, records
    # outside that message and malformed irrelevant entries. A forged extra
    # entry must not be silently ignored merely because the position's own
    # token-balance entry happens to be present and valid.
    token_error_scope = 'CPMM_' if order.get('route_kind') == 'CPMM' else ''
    for label in ('preTokenBalances', 'postTokenBalances'):
        token_entries = meta.get(label)
        if type(token_entries) is not list:
            raise ValueError(token_error_scope + 'complete_token_balances_required')
        observed_indices = set()
        for entry in token_entries:
            if type(entry) is not dict:
                raise ValueError(token_error_scope + 'finalized_token_balance_entry_invalid')
            index = entry.get('accountIndex')
            if (type(index) is not int or not 0 <= index < len(keys)
                    or index in observed_indices):
                raise ValueError(token_error_scope + 'finalized_token_balance_account_index_invalid')
            observed_indices.add(index)
    fee = uint(meta.get('fee'))
    if fee > order['network_fee_upper_lamports']:
        raise ValueError('actual_fee_exceeds_reserved_upper_bound')
    slot = uint(payload.get('slot'), positive=True)
    if slot < order['source_slot']:
        raise ValueError('finalized_slot_precedes_observed_intent')
    if order.get('route_kind') == 'CPMM':
        # The exact signed SELL creates one ephemeral WSOL account and closes
        # it atomically into the wallet. A nominal quote can look profitable
        # even when rent remains trapped in that account; do not finalize a
        # position from net wallet proceeds without checking closure. This
        # is a consequence of the actually finalized transaction's native
        # balance vector, not a claim inferred from the unsigned builder.
        ephemeral = order['quote_token_account']
        if (type(ephemeral) is not str or ephemeral in (
                order['user'], order['base_token_account'])
                or keys.count(ephemeral) != 1):
            raise ValueError('CPMM_ephemeral_WSOL_identity_missing_in_finalized_message')
        temp_index = keys.index(ephemeral)
        if before[temp_index] != 0 or after[temp_index] != 0:
            raise ValueError('CPMM_ephemeral_WSOL_not_fully_closed_at_finality')
        # A closed token account must not appear as a post-transaction token
        # balance. Missing pre/post token arrays are refused below; do not
        # silently treat a missing array as positive proof of closure.
        post_tokens = meta.get('postTokenBalances')
        if (type(post_tokens) is not list or
                any(type(item) is not dict for item in post_tokens)):
            raise ValueError('CPMM_post_token_balances_required_for_closure')
        if any(type(item.get('accountIndex')) is not int
               for item in post_tokens):
            raise ValueError('CPMM_post_token_balance_indices_invalid')
        if any(item['accountIndex'] == temp_index for item in post_tokens):
            raise ValueError('CPMM_ephemeral_WSOL_persisted_in_token_balances')
    native_delta = after[wallet_index] - before[wallet_index]
    if meta.get('err') is not None:
        if (native_delta != -fee
                or any(a != b for i, (a, b) in enumerate(zip(before, after)) if i != wallet_index)
                or meta.get('preTokenBalances') != meta.get('postTokenBalances')):
            raise ValueError('failed_transaction_has_unexplained_balance_change')
        return dict(slot=slot, fee_lamports=fee, chain_error=meta['err'],
            token_delta_atomic=0, wallet_delta_lamports=native_delta,
            gross_output_lamports=0, rent_locked_lamports=0,
            realized_market_execution=True, economic_edge_proven=False,
            inventory_pool=inventory_pool)

    def token_amount(name):
        values = meta.get(name)
        if type(values) is not list:
            raise ValueError('complete_token_balances_required')
        matches = [v for v in values if type(v) is dict and v.get('accountIndex') == base_index]
        if len(matches) > 1:
            raise ValueError('ambiguous_position_token_balance')
        if not matches:
            # A newly created ATA can be absent before the transaction only.
            if name == 'preTokenBalances' and before[base_index] == 0:
                return 0
            raise ValueError('position_token_balance_missing')
        value = matches[0]
        if value.get('mint') != order['mint'] or value.get('owner') != order['user']:
            raise ValueError('position_token_identity_mismatch')
        return _amount(value.get('uiTokenAmount', {}).get('amount'))

    token_delta = token_amount('postTokenBalances') - token_amount('preTokenBalances')
    rent_locked = max(0, after[base_index] - before[base_index])
    if rent_locked > order['rent_deposit_lamports']:
        raise ValueError('actual_rent_exceeds_reserved_upper_bound')
    if order['side'] == 'BUY':
        if token_delta < order['minimum_out']:
            raise ValueError('buy_fill_below_minimum_out')
        if native_delta != -(order['input_amount'] + fee + rent_locked):
            raise ValueError('buy_native_cash_flow_unexplained')
        gross_output = 0
    else:
        if token_delta != -order['input_amount'] or before[base_index] != after[base_index]:
            raise ValueError('sell_fill_quantity_or_rent_mismatch')
        gross_output = native_delta + fee
        if gross_output < order['minimum_out']:
            raise ValueError('sell_fill_below_minimum_out')
    return dict(slot=slot, fee_lamports=fee, chain_error=None,
        token_delta_atomic=token_delta, wallet_delta_lamports=native_delta,
        gross_output_lamports=gross_output, rent_locked_lamports=rent_locked,
        realized_market_execution=True, economic_edge_proven=False,
        inventory_pool=inventory_pool)


class ExecutionEngine:
    def __init__(self, *, journal: ExecutionJournal, rpc, signer=None,
                 verifier=None, mode=Mode.LIVE_PREPARED, envelope=None,
                 arming=None, evidence_provider=None, clock_ms=None):
        if type(mode) is not Mode:
            raise ValueError('explicit_execution_mode_required')
        self.journal, self.rpc, self.signer = journal, rpc, signer
        self.verifier = verifier if verifier is not None else Ed25519Verifier()
        self.mode, self.envelope, self.arming = mode, envelope, arming
        self.evidence_provider = evidence_provider
        self._admission_cache = {}
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.journal.verify_audit()

    def result(self, decision_id):
        row = self.journal.get(decision_id)
        if not row:
            return None
        return dict(decision_id=decision_id, state=row['state'],
                    signature=row['signature'], failure_type=row['failure_type'],
                    reconciliation=json.loads(row['reconciliation_json']) if row['reconciliation_json'] else None)

    async def _admission(self, decision_id, order, *, own_reservation=False):
        self._refuse_retired_launchlab_route(order)
        if self.evidence_provider is None or self.envelope is None or self.arming is None:
            raise ValueError('explicit_authorization_and_fresh_evidence_required')
        request, health = await self.evidence_provider(decision_id, order)
        if type(request) is not AdmissionRequest or type(health) is not HealthEvidence:
            raise ValueError('typed_fresh_submission_evidence_required')
        wire_parameters = json.loads(order.rebuild_request_json)
        binding=self._cpmm_binding(order) if route_kind(order)=='CPMM' else None
        priority = (wire_parameters['compute_unit_limit'] * wire_parameters['priority_fee_micro_lamports'] + 999999) // 1000000
        expected = dict(decision_id=decision_id, side=order.side.lower(), wallet=order.user,
            program_id=execution_program(order), mint=order.mint, pool=order.pool,
            amount_in_atomic=order.input_amount, quote_input_atomic=order.input_amount,
            quote_output_atomic=order.expected_output, minimum_out_atomic=order.minimum_out,
            network_fee_upper_lamports=order.network_fee_upper_lamports,
            rent_deposit_upper_lamports=order.rent_deposit_lamports,
            route_message_sha256=hashlib.sha256(order.transaction.message).hexdigest(),
            quote_context_slot=order.source_slot,
            quote_payload_sha256=order.source_account_digest,
            quote_received_at_ms=order.source_available_at_ms,
            compute_units=wire_parameters['compute_unit_limit'],
            slippage_bps=wire_parameters['slippage_bps'], priority_fee_lamports=priority,
            price_impact_bps=order.price_impact_bps,
            position_pool=binding['inventory_pool'] if binding else None)
        if any(getattr(request, key) != value for key, value in expected.items()):
            raise ValueError('admission_evidence_not_bound_to_exact_prepared_order')
        actual_endpoint = getattr(self.rpc, 'endpoint_sha256', None)
        if actual_endpoint != self.envelope.rpc_endpoint_sha256 or request.rpc_endpoint_sha256 != actual_endpoint:
            raise ValueError('actual_rpc_endpoint_differs_from_authorized_endpoint')
        if await self.rpc.genesis_hash() != self.envelope.genesis_hash:
            raise ValueError('rpc_genesis_differs_from_authorized_cluster')
        # The fee quote must come from a bank at least as recent as the
        # prepared market-source bank. An uncontextualized getFeeForMessage
        # result can price a message against an earlier Solana fork and must
        # never authorize a LIVE signature or send.
        receipt_method = getattr(self.rpc, 'get_fee_for_message_receipt', None)
        if not callable(receipt_method):
            raise ValueError('causal_message_fee_receipt_adapter_required')
        fee_receipt = await receipt_method(
            order.transaction.message, min_context_slot=order.source_slot)
        if (type(fee_receipt) is not dict
                or type(fee_receipt.get('context_slot')) is not int
                or fee_receipt['context_slot'] < order.source_slot
                or type(fee_receipt.get('value')) is not int
                or not 0 < fee_receipt['value'] <= order.network_fee_upper_lamports):
            raise ValueError('causal_message_fee_unknown_stale_or_above_reserved_bound')
        balance = await self.rpc.get_balance(order.user)
        now = self.clock_ms()
        risk = self.journal.risk_snapshot(at=now, wallet_balance_lamports=balance,
            exclude_decision_id=decision_id if own_reservation else None)
        verdict = evaluate_admission(request, envelope=self.envelope,
            arming=self.arming, health=health, risk=risk, now_ms=now)
        if not verdict.allowed:
            raise ValueError('submission_admission_refused:' + ','.join(verdict.reasons))
        self._admission_cache[decision_id] = (request, health, balance, now)
        return balance

    def _refuse_retired_launchlab_route(self,order):
        if (route_kind(order)=='LAUNCHLAB'
                and self.journal.inventory_migration(order.mint,order.pool) is not None):
            raise ValueError('LaunchLab_route_retired_by_verified_migration')

    def _cpmm_binding(self,order,*,prepared_genesis=None):
        if route_kind(order)!='CPMM':return None
        endpoint=getattr(self.rpc,'endpoint_sha256',None)
        if self.envelope is None:
            # In PREPARED mode the source-backed registration still supplies
            # the pinned cluster. Never infer a migration from raw pool state.
            genesis=prepared_genesis
        else:genesis=self.envelope.genesis_hash
        if type(endpoint) is not str or type(genesis) is not str:
            raise ValueError('CPMM_pinned_migration_source_required')
        binding=self.journal.migration_binding(order.mint,order.pool,
            at_ms=self.clock_ms(),source_slot=order.source_slot,wallet=order.user,
            endpoint_sha256=endpoint,genesis_hash=genesis)
        row=self.journal.get(json.loads(order.rebuild_request_json)['decision_id'])
        if row is not None:
            record=json.loads(row['order_json'])
            if (record.get('migration_binding_sha256')!=binding['binding_sha256']
                    or order_inventory_pool(record)!=binding['inventory_pool']):
                raise ValueError('CPMM_order_migration_binding_changed')
        return binding

    def _final_admission(self, decision_id):
        if self.mode is not Mode.LIVE_ENABLED:
            raise ValueError('execution_disarmed_before_submission')
        operational_check=getattr(self.evidence_provider,'assert_operational_now',None)
        if operational_check is not None:
            operational_check()
        request, health, balance, balance_observed_at = self._admission_cache[decision_id]
        record=json.loads(self.journal.get(decision_id)['order_json'])
        if (record.get('route_kind')!='CPMM'
                and self.journal.inventory_migration(record['mint'],record['pool']) is not None):
            raise ValueError('LaunchLab_route_retired_by_verified_migration')
        if record.get('route_kind')=='CPMM':
            binding=self.journal.migration_binding(record['mint'],record['pool'],
                at_ms=self.clock_ms(),source_slot=record['source_slot'],wallet=record['user'],
                endpoint_sha256=self.envelope.rpc_endpoint_sha256,
                genesis_hash=self.envelope.genesis_hash)
            if (binding['binding_sha256']!=record['migration_binding_sha256']
                    or binding['inventory_pool']!=order_inventory_pool(record)):
                raise ValueError('final_CPMM_migration_binding_changed')
        risk = self.journal.risk_snapshot(at=balance_observed_at,
            wallet_balance_lamports=balance, exclude_decision_id=decision_id)
        verdict = evaluate_admission(request, envelope=self.envelope,
            arming=self.arming, health=health, risk=risk, now_ms=self.clock_ms())
        if not verdict.allowed:
            raise ValueError('final_submission_admission_refused:' + ','.join(verdict.reasons))

    async def execute(self, decision_id, order):
        order = validate_execution_order(order)
        if json.loads(order.rebuild_request_json)['decision_id'] != decision_id:
            raise ValueError('decision_id_not_bound_to_prepared_route')
        if order.transaction.required_signers != (order.user,):
            raise ValueError('exact_isolated_wallet_signer_required')
        record = order_record(order)
        if route_kind(order)=='CPMM':
            genesis=await self.rpc.genesis_hash() if self.envelope is None else None
            binding=self._cpmm_binding(order,prepared_genesis=genesis)
            record.update(route_kind='CPMM',program_id=execution_program(order),
                inventory_pool=binding['inventory_pool'],
                migration_binding_sha256=binding['binding_sha256'])
        if not self.journal.create(decision_id, record, self.clock_ms()):
            # A duplicate can only inspect/recover its original signature; it
            # never silently reconstructs, re-signs or re-sends an order.
            return self.result(decision_id)
        self._refuse_retired_launchlab_route(order)
        if self.mode is Mode.RESEARCH:
            return self.result(decision_id)
        if self.journal.killed:
            raise ValueError('persistent_kill_switch_active')
        height = await self.rpc.get_block_height()
        if type(height) is not int or height > order.transaction.last_valid_block_height:
            self.journal.release_unsent(decision_id, self.clock_ms(), 'blockhash_expired_before_simulation')
            return self.result(decision_id)
        simulation_options=dict(sig_verify=False)
        if route_kind(order)=='CPMM':simulation_options['min_context_slot']=order.source_slot
        simulation = await self.rpc.simulate_transaction(order.transaction.unsigned_transaction(), **simulation_options)
        if type(simulation) is not dict or 'err' not in simulation or simulation['err'] is not None:
            self.journal.transition(decision_id, ('PREPARED',), 'SIMULATION_FAILED', self.clock_ms(), failure_type='simulation_refused')
            return self.result(decision_id)
        simulation_slot = simulation.get('context_slot')
        if type(simulation_slot) is not int or simulation_slot < order.source_slot:
            raise ValueError('simulation_bank_precedes_observed_route')
        used = simulation.get('unitsConsumed')
        planned_compute = json.loads(order.rebuild_request_json)['compute_unit_limit']
        if type(used) is not int or not 0 <= used <= planned_compute:
            raise ValueError('simulation_compute_measurement_missing_or_above_limit')
        self.journal.transition(decision_id, ('PREPARED',), 'SIMULATED', self.clock_ms())
        if self.mode is not Mode.LIVE_ENABLED:
            return self.result(decision_id)
        if self.signer is None or self.signer.public_key != order.user:
            raise ValueError('matching_isolated_signer_required')
        balance = await self._admission(decision_id, order)
        height = await self.rpc.get_block_height()
        if type(height) is not int or height > order.transaction.last_valid_block_height:
            self.journal.release_unsent(decision_id, self.clock_ms(), 'blockhash_expired_before_signing')
            return self.result(decision_id)
        self.journal.reserve(decision_id, self.clock_ms(), wallet_balance_lamports=balance,
            max_capital_lamports=self.envelope.max_capital_lamports,
            max_open_positions=self.envelope.max_open_positions,
            max_in_flight_orders=self.envelope.max_in_flight_orders,
            max_daily_spend_lamports=self.envelope.max_daily_spend_lamports,
            max_daily_loss_lamports=self.envelope.max_daily_loss_lamports)
        try:
            signature_bytes = await self.signer.sign_message(order.transaction.message)
            self.verifier.verify(order.user, order.transaction.message, signature_bytes)
            raw = order.transaction.transaction((signature_bytes,))
            signature = _encode(signature_bytes)
            self.journal.transition(decision_id, ('RESERVED',), 'SIGNED', self.clock_ms(), signature=signature, signed_raw=raw)
            # Signing hardware can stall. Recheck fresh services, financial
            # authority and chain lifetime after it returns, before submission.
            await self._admission(decision_id, order, own_reservation=True)
            height = await self.rpc.get_block_height()
            if type(height) is not int or height > order.transaction.last_valid_block_height:
                raise ValueError('blockhash_expired_during_signing')
            self.journal.transition(decision_id, ('SIGNED',), 'SUBMITTING', self.clock_ms(),
                final_admission=lambda: self._final_admission(decision_id))
        except BaseException as error:
            self.journal.release_unsent(decision_id, self.clock_ms(), type(error).__name__)
            raise
        # No RPC or signer call may occur between this write-ahead marker and
        # sending; a crash in this interval remains explicitly ambiguous.
        try:
            returned = await self.rpc.send_transaction(raw)
            if returned != signature:
                raise ValueError('rpc_returned_different_transaction_signature')
        except BaseException as error:
            self.journal.transition(decision_id, ('SUBMITTING',), 'UNCERTAIN', self.clock_ms(), failure_type=type(error).__name__)
            self.journal.kill('ambiguous_submission_requires_chain_reconciliation', self.clock_ms())
            if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):
                raise
            return self.result(decision_id)
        self.journal.transition(decision_id, ('SUBMITTING',), 'SUBMITTED', self.clock_ms())
        return self.result(decision_id)

    async def recover(self, decision_id):
        row = self.journal.get(decision_id)
        if row and row['state'] in ('RESERVED', 'SIGNED'):
            # SUBMITTING is committed before the sole send call. Earlier
            # states therefore prove that this engine never submitted it.
            self.journal.release_unsent(decision_id, self.clock_ms(), 'recovered_before_submission_marker')
            return self.result(decision_id)
        if not row or row['state'] not in ACTIVE or not row['signature']:
            return self.result(decision_id)
        record=json.loads(row['order_json'])
        if record.get('route_kind')=='CPMM':
            # A restart must not settle a mainnet order from an accidentally
            # different endpoint/cluster. The pinned source is durable even
            # when recovery runs without a signer or financial envelope.
            binding=self.journal.migration_binding(record['mint'],record['pool'],
                at_ms=self.clock_ms(),source_slot=record['source_slot'],wallet=record['user'],
                endpoint_sha256=getattr(self.rpc,'endpoint_sha256',None),
                genesis_hash=await self.rpc.genesis_hash())
            if (binding['binding_sha256']!=record['migration_binding_sha256']
                    or binding['inventory_pool']!=order_inventory_pool(record)):
                raise ValueError('CPMM_recovery_source_or_inventory_binding_changed')
        status = await self.rpc.signature_status(row['signature'])
        now = self.clock_ms()
        if status is None:
            if row['state'] == 'REORG_PENDING':
                # Already quarantined: blockhash expiry must not erase the reorg evidence.
                return self.result(decision_id)
            if row['state'] == 'CONFIRMED':
                self.journal.transition(decision_id, ('CONFIRMED',), 'REORG_PENDING', now)
                self.journal.kill('confirmation_disappeared', now)
                return self.result(decision_id)
            height = await self.rpc.get_block_height()
            lifetime = json.loads(row['order_json'])['transaction']['last_valid_block_height']
            if type(height) is not int:
                raise ValueError('valid_block_height_required')
            if height > lifetime:
                if row['state'] == 'SIGNED':
                    self.journal.release_unsent(decision_id, now, 'unsent_signed_transaction_expired')
                else:
                    current = self.journal.get(decision_id)['state']
                    self.journal.transition(decision_id, (current,), 'EXPIRED_UNKNOWN', now)
                    self.journal.kill('expired_submission_history_unknown_no_reservation_release', now)
            return self.result(decision_id)
        if type(status) is not dict or status.get('confirmationStatus') not in ('processed', 'confirmed', 'finalized'):
            raise ValueError('valid_signature_status_required')
        if status['confirmationStatus'] != 'finalized':
            if status['confirmationStatus'] == 'confirmed':
                self.journal.transition(decision_id, (row['state'],), 'CONFIRMED', now)
            return self.result(decision_id)
        payload = await self.rpc.get_transaction(row['signature'])
        if payload is None:
            return self.result(decision_id)
        try:
            reconciliation = reconcile_transaction(row, payload)
            if payload.get('slot') != status.get('slot') or reconciliation['chain_error'] != status.get('err'):
                raise ValueError('status_transaction_finality_binding_failed')
            self.journal.finalize(decision_id, reconciliation, now)
        except Exception:
            self.journal.kill('finalized_balance_reconciliation_failed', now)
            raise
        return self.result(decision_id)
