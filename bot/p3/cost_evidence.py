"""Read-only network-fee evidence from another retained public transaction.

meta.fee is the reference transaction's total network fee, including priority
fees. It excludes swaps, token transfer fees and refundable account deposits.
No field here establishes costs applicable to our unexecuted PAPER scenario.
"""
import struct


COMPUTE_BUDGET_PROGRAM = 'ComputeBudget111111111111111111111111111111'
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def _uint(value, maximum=2**64-1, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= maximum:
        raise ValueError('invalid_unsigned_integer')
    return value


def _base58(value, maximum):
    if type(value) is not str or not value or len(value) > 192:
        raise ValueError('invalid_public_base58')
    number = 0
    for character in value:
        number = number*58+_B58.index(character)
    leading = len(value)-len(value.lstrip('1'))
    raw = bytes(leading)+number.to_bytes((number.bit_length()+7)//8,'big')
    if len(raw) > maximum:
        raise ValueError('public_base58_too_large')
    return raw


def _program(instruction, keys):
    if type(instruction) is not dict:
        raise ValueError('invalid_instruction')
    if 'programId' in instruction:
        address = instruction['programId']
    else:
        index = _uint(instruction.get('programIdIndex'),len(keys)-1)
        key = keys[index]
        address = key.get('pubkey') if type(key) is dict else key
    if len(_base58(address,32)) != 32:
        raise ValueError('invalid_program_identity')
    return address


def _budget(message, total_fee, succeeded):
    result = dict(compute_unit_limit=None,compute_unit_price_micro_lamports=None,
                  derived_requested_priority_fee_lamports=None,
                  residual_network_fee_lamports=None,
                  derivation_scope='explicit_message_budget_only; not_our_execution_cost',reasons=[])
    instructions, keys = message.get('instructions'), message.get('accountKeys')
    if type(instructions) is not list or type(keys) is not list:
        result['reasons'].append('reference_instruction_list_unavailable')
        return result
    seen = set()
    for instruction in instructions:
        try:
            if _program(instruction,keys) != COMPUTE_BUDGET_PROGRAM:
                continue
            parsed = instruction.get('parsed')
            if type(parsed) is dict:
                info, kind = parsed.get('info'), parsed.get('type')
                if type(info) is not dict:
                    raise ValueError('invalid_parsed_budget')
                if kind == 'setComputeUnitLimit':
                    field, value = 'compute_unit_limit', _uint(info.get('units'),2**32-1,positive=True)
                elif kind == 'setComputeUnitPrice':
                    field, value = 'compute_unit_price_micro_lamports', _uint(info.get('microLamports'))
                elif kind == 'requestHeapFrame':
                    _uint(info.get('bytes'),2**32-1,positive=True)
                    continue
                else:
                    raise ValueError('unsupported_budget_instruction')
            else:
                raw = _base58(instruction.get('data'),64)
                if len(raw) == 5 and raw[0] == 2:
                    field, value = 'compute_unit_limit', _uint(struct.unpack_from('<I',raw,1)[0],positive=True)
                elif len(raw) == 9 and raw[0] == 3:
                    field, value = 'compute_unit_price_micro_lamports', struct.unpack_from('<Q',raw,1)[0]
                elif len(raw) == 5 and raw[0] == 1:
                    continue
                else:
                    raise ValueError('unsupported_budget_instruction')
            if field in seen:
                raise ValueError('duplicate_budget_instruction')
            seen.add(field)
            result[field] = value
        except (ValueError,TypeError,IndexError,KeyError,struct.error):
            result['reasons'].append('unsupported_or_ambiguous_reference_budget_instruction')
    units, price = result['compute_unit_limit'], result['compute_unit_price_micro_lamports']
    if not succeeded:
        result['reasons'].append('failed_reference_transaction_priority_split_not_certified')
    elif not result['reasons'] and units is not None and price is not None:
        # Above the supported runtime limit the requested value may be clamped.
        # Do not treat that requested product as the charged priority component.
        if units > 1_400_000:
            result['reasons'].append('requested_compute_limit_effective_value_unproven')
        else:
            priority = (units*price+999_999)//1_000_000
            if priority > total_fee:
                result['reasons'].append('requested_priority_exceeds_observed_total_fee')
            else:
                result['derived_requested_priority_fee_lamports'] = priority
                result['residual_network_fee_lamports'] = total_fee-priority
    return result


def classify_reference_transaction(event):
    """Classify one captured transaction, never extrapolating its fee to ours.

    The caller verifies the capture chain. This checks retained RPC semantics,
    public signature/slot linkage and timing; it is not provider authentication.
    Missing blockTime or malformed metadata prevents a validated reference.
    """
    result = dict(schema='p3-reference-transaction-cost-v1',known_reference_fee=False,
        known_reference_fee_lamports=None,reference_signature=None,reference_slot=None,
        reference_block_time_ms=None,source_time_kind='chain_block_time_estimate',
        reference_transaction_succeeded=None,compute_budget=None,
        fee_source='retained_getTransaction.meta.fee',
        fee_scope='total_reference_network_fee_including_priority; excludes_curve_fees_and_rent',
        applicability_to_our_scenario='UNPROVEN',our_network_fee_lamports=None,
        our_priority_fee_lamports=None,our_account_rent_lamports=None,
        our_additional_costs_known=False,execution_verified=False,
        net_economic_pnl_sol=None,economic_verdict='INSUFFICIENT DATA',reasons=[])
    try:
        if type(event) is not dict or event.get('kind') != 'transaction' or event.get('outcome') != 'observed':
            raise ValueError('reference_transaction_observation_missing')
        if event.get('provenance') not in ('live','synthetic','historical_replay'):
            raise ValueError('reference_provenance_unknown')
        payload = event.get('payload')
        tx = payload.get('raw_transaction') if type(payload) is dict else None
        if type(tx) is not dict or type(tx.get('meta')) is not dict or 'err' not in tx['meta']:
            raise ValueError('reference_transaction_metadata_missing')
        transaction = tx.get('transaction')
        if type(transaction) is not dict or type(transaction.get('message')) is not dict:
            raise ValueError('reference_transaction_message_missing')
        signatures = transaction.get('signatures')
        if type(signatures) is not list or not signatures:
            raise ValueError('reference_signature_list_missing')
        if any(len(_base58(signature,64)) != 64 for signature in signatures):
            raise ValueError('reference_signature_invalid')
        if event.get('signature') != signatures[0]:
            raise ValueError('reference_requested_signature_mismatch')
        slot = _uint(tx.get('slot'),2**63-1,positive=True)
        if event.get('source_slot') != slot or type(event.get('source_slot')) is not int:
            raise ValueError('reference_requested_slot_mismatch')
        source = _uint(tx.get('blockTime'),2**63-1,positive=True)*1000
        received = _uint(event.get('received_at_ms'),2**63-1)
        available = _uint(event.get('available_at_ms'),2**63-1)
        if (not source <= received <= available or event.get('source_time_ms') != source
                or type(event.get('source_time_ms')) is not int):
            raise ValueError('reference_block_time_or_availability_inconsistent')
        fee = _uint(tx['meta'].get('fee'),positive=True)
        result.update(known_reference_fee=True,known_reference_fee_lamports=fee,
            reference_signature=signatures[0],reference_slot=slot,reference_block_time_ms=source,
            reference_transaction_succeeded=tx['meta']['err'] is None,
            compute_budget=_budget(transaction['message'],fee,tx['meta']['err'] is None),
            source_provenance=event.get('provenance'))
    except (ValueError,TypeError,IndexError,KeyError) as error:
        # Only categorical local errors are returned; no raw provider text/URLs.
        reason = str(error)
        result['reasons'].append(reason if reason.startswith('reference_') else 'invalid_reference_public_encoding_or_integer')
    return result
