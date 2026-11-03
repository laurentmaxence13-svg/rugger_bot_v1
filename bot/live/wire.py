"""Solana legacy message/transaction encoding, with external signatures only.

This module serializes genuine wire bytes. It never possesses a key, connects,
or asserts that a supplied signature is cryptographically valid. The execution
boundary must verify signatures with an audited Ed25519 implementation.
"""
from dataclasses import dataclass

from bot.p3.certification import _decode

PACKET_LIMIT = 1232


def shortvec(value):
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError('shortvec_u16_required')
    encoded = bytearray()
    while True:
        limb = value & 127
        value >>= 7
        encoded.append(limb | (128 if value else 0))
        if not value:
            return bytes(encoded)


@dataclass(frozen=True)
class AccountMeta:
    pubkey: str
    is_signer: bool = False
    is_writable: bool = False

    def __post_init__(self):
        _decode(self.pubkey)
        if type(self.is_signer) is not bool or type(self.is_writable) is not bool:
            raise ValueError('explicit_account_privileges_required')


@dataclass(frozen=True)
class Instruction:
    program_id: str
    accounts: tuple
    data: bytes

    def __post_init__(self):
        _decode(self.program_id)
        if (type(self.accounts) is not tuple
                or any(type(a) is not AccountMeta for a in self.accounts)
                or type(self.data) is not bytes or len(self.data) > PACKET_LIMIT):
            raise ValueError('typed_instruction_required')


@dataclass(frozen=True)
class PreparedTransaction:
    message: bytes
    account_keys: tuple
    required_signers: tuple
    recent_blockhash: str
    last_valid_block_height: int

    def transaction(self, signatures):
        if (type(signatures) is not tuple or len(signatures) != len(self.required_signers)
                or any(type(s) is not bytes or len(s) != 64 for s in signatures)):
            raise ValueError('exact_external_signature_vector_required')
        raw = shortvec(len(signatures)) + b''.join(signatures) + self.message
        if len(raw) > PACKET_LIMIT:
            raise ValueError('solana_packet_limit_exceeded')
        return raw

    def unsigned_transaction(self):
        """Zero signatures, for sigVerify=false simulation only; never send."""
        return self.transaction(tuple(bytes(64) for _ in self.required_signers))


def compile_legacy(instructions, *, fee_payer, recent_blockhash,
                   last_valid_block_height):
    _decode(fee_payer)
    blockhash = _decode(recent_blockhash)
    if (type(instructions) is not tuple or not instructions
            or any(type(i) is not Instruction for i in instructions)
            or type(last_valid_block_height) is not int
            or not 0 < last_valid_block_height < 2**64):
        raise ValueError('typed_legacy_message_and_blockhash_lifetime_required')
    # Union privileges across all instructions, then preserve first encounter
    # order inside each protocol-defined signer/writable category. Fee payer
    # is always the first writable signer. Shared Token program IDs are valid.
    merged = {fee_payer: [True, True]}
    program_ids = {i.program_id for i in instructions}
    for instruction in instructions:
        for account in instruction.accounts:
            current = merged.setdefault(account.pubkey, [False, False])
            current[0] |= account.is_signer
            current[1] |= account.is_writable
        merged.setdefault(instruction.program_id, [False, False])
    if any(merged[p][0] or merged[p][1] for p in program_ids):
        raise ValueError('program_account_privilege_escalation')
    groups = ((True, True), (True, False), (False, True), (False, False))
    keys = tuple(k for group in groups for k, flags in merged.items()
                 if tuple(flags) == group)
    if len(keys) > 256:
        raise ValueError('legacy_account_index_limit_exceeded')
    signers = tuple(k for k in keys if merged[k][0])
    readonly_signed = sum(s and not w for s, w in merged.values())
    readonly_unsigned = sum(not s and not w for s, w in merged.values())
    if len(signers) > 127:
        raise ValueError('legacy_signer_limit_exceeded')
    index = {key: i for i, key in enumerate(keys)}
    header = bytes((len(signers), readonly_signed, readonly_unsigned))
    message = header + shortvec(len(keys)) + b''.join(_decode(k) for k in keys) + blockhash
    message += shortvec(len(instructions))
    for instruction in instructions:
        indices = bytes(index[a.pubkey] for a in instruction.accounts)
        message += bytes((index[instruction.program_id],)) + shortvec(len(indices)) + indices
        message += shortvec(len(instruction.data)) + instruction.data
    prepared = PreparedTransaction(message, keys, signers, recent_blockhash,
                                   last_valid_block_height)
    prepared.unsigned_transaction()  # Reject oversized packets at construction.
    return prepared
