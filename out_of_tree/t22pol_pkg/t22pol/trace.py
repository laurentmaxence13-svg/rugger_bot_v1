"""Census from the pool's CREATION transaction (raw ``json`` encoding), when no mint account is archived.

  PYTHONPATH=<t22pol_pkg> python -B -m t22pol.trace <pools.json> [--frozen-check]

Input: {"pools": [{"pool", "mint", "creation_signature", "creation_transaction": <raw getTransaction result,
encoding json>}]}. Read: the program id, the first account and the data of every outer and inner
instruction of that one transaction; never an amount of a trade. Output: the same schema as
``t22pol.census`` (``source: creation_trace``), so ``v3lab.scenarios`` can read it.

What the trace shows, for the launched mint: its token program (who ran InitializeMint / InitializeMint2),
every extension initialised before it (Token-2022 extensions can only be initialised before the mint),
the freeze authority option of InitializeMint2, and whether the mint authority was set to None in the
same transaction. What it cannot show: changes made by later transactions; the census says so.
Tags: solana-program/token-2022 interface/src/instruction.rs (sha256 672b3890cb58e570…), tag = variant
order, 0 to 46, Batch = 255. Token metadata: spl_token_metadata_interface discriminators.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from t22pol import VERSION, policy

INSTRUCTION_SOURCE_SHA256 = '672b3890cb58e570'
_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
TOKEN_PROGRAMS = {policy.TOKEN_PROGRAM: 'spl', policy.TOKEN_2022_PROGRAM: 'token2022'}
NAMES = ('InitializeMint', 'InitializeAccount', 'InitializeMultisig', 'Transfer', 'Approve', 'Revoke',
         'SetAuthority', 'MintTo', 'Burn', 'CloseAccount', 'FreezeAccount', 'ThawAccount', 'TransferChecked',
         'ApproveChecked', 'MintToChecked', 'BurnChecked', 'InitializeAccount2', 'SyncNative',
         'InitializeAccount3', 'InitializeMultisig2', 'InitializeMint2', 'GetAccountDataSize',
         'InitializeImmutableOwner', 'AmountToUiAmount', 'UiAmountToAmount', 'InitializeMintCloseAuthority',
         'TransferFeeExtension', 'ConfidentialTransferExtension', 'DefaultAccountStateExtension', 'Reallocate',
         'MemoTransferExtension', 'CreateNativeMint', 'InitializeNonTransferableMint',
         'InterestBearingMintExtension', 'CpiGuardExtension', 'InitializePermanentDelegate',
         'TransferHookExtension', 'ConfidentialTransferFeeExtension', 'WithdrawExcessLamports',
         'MetadataPointerExtension', 'GroupPointerExtension', 'GroupMemberPointerExtension',
         'ConfidentialMintBurnExtension', 'ScaledUiAmountExtension', 'PausableExtension', 'UnwrapLamports',
         'PermissionedBurnExtension')
# Extension-initialising instruction (tag, first sub-byte or None) -> mint ExtensionType value (policy.EXTENSIONS)
EXTENSION_INIT = {(25, None): 3, (26, 0): 1, (27, 0): 4, (28, 0): 6, (32, None): 9, (33, 0): 10, (35, None): 12,
                  (36, 0): 14, (37, 0): 16, (39, 0): 18, (40, 0): 20, (41, 0): 22, (42, 0): 24, (43, 0): 25,
                  (44, 0): 26, (46, 0): 28}
# GetAccountDataSize (21), AmountToUiAmount (23), UiAmountToAmount (24): read-only queries on the mint
# (official processor returns data and writes nothing); 21 runs whenever an associated account is created.
READ_ONLY_ON_MINT = frozenset((21, 23, 24))
METADATA_INITIALIZE = bytes.fromhex('d2e11ea258b84d8d')
GROUP_INITIALIZE = {bytes.fromhex('79716c2736330004'): 21, bytes.fromhex('9820deb0dfed7486'): 23}


def b58decode(text):
    number = 0
    for char in text:
        number = number * 58 + _B58.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, 'big') if number else b''
    return b'\0' * (len(text) - len(text.lstrip('1'))) + raw


def _instructions(tx):
    """(program id, account addresses, data) of every outer and inner instruction, in execution order."""
    message = tx['transaction']['message']
    meta = tx.get('meta') or {}
    loaded = meta.get('loadedAddresses') or {}
    keys = list(message['accountKeys']) + list(loaded.get('writable', ())) + list(loaded.get('readonly', ()))
    inner = {group['index']: group['instructions'] for group in meta.get('innerInstructions') or ()}
    if meta.get('innerInstructions') is None:
        raise ValueError('inner_instructions_missing')
    out = []
    for index, ix in enumerate(message['instructions']):
        for one in [ix] + list(inner.get(index, ())):
            out.append((keys[one['programIdIndex']], [keys[i] for i in one['accounts']], b58decode(one['data'])))
    return out


def _transfer_fee_bps(data):
    """InitializeTransferFeeConfig: tag, 0, two COption<Pubkey> (flag + 32 bytes when present), u16 bps, u64 max."""
    offset = 2
    for _ in range(2):
        if offset >= len(data) or data[offset] not in (0, 1):
            return None
        offset += 1 + 32 * data[offset]
    return int.from_bytes(data[offset:offset + 2], 'little') if offset + 10 == len(data) else None


def _tag_name(tag):
    return 'Batch' if tag == 255 else (NAMES[tag] if tag < len(NAMES) else f'unknown_tag_{tag}')


def classify_trace(tx, mint):
    out = dict(mint=mint, token_program=None, extensions=[], reasons=[], class_='refused',
               transfer_fee_bps=None, our_account_len=None, our_account_rent_lamports=None)
    if type(tx) is not dict:
        out['reasons'] = ['creation_transaction_missing']
        return out
    if (tx.get('meta') or {}).get('err') is not None:
        out['reasons'] = ['creation_transaction_failed']
        return out
    try:
        instructions = _instructions(tx)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        out['reasons'] = [f'creation_trace_unreadable:{exc}']
        return out
    extensions, reasons, init, mint_authority_revoked, freeze_revoked = [], [], None, False, False
    values = {}                      # extension value bytes, to rebuild the mint for the frozen-reader check
    for program, accounts, data in instructions:
        if program not in TOKEN_PROGRAMS or not data:
            continue
        if data[:8] == METADATA_INITIALIZE and len(accounts) > 2 and accounts[2] == mint:
            extensions.append(19)
            values[19] = (accounts[1], data[8:])
            continue
        if data[:8] in GROUP_INITIALIZE and mint in accounts[:3]:
            extensions.append(GROUP_INITIALIZE[data[:8]])
            continue
        if not accounts or accounts[0] != mint:
            continue
        tag, sub = data[0], (data[1] if len(data) > 1 else None)
        if tag in (0, 20):
            if init is not None:
                reasons.append('mint_initialised_twice')
            init = (program, tag, data)
        elif (tag, sub) in EXTENSION_INIT or (tag, None) in EXTENSION_INIT:
            kind = EXTENSION_INIT.get((tag, sub), EXTENSION_INIT.get((tag, None)))
            if init is not None:
                reasons.append(f'extension_after_mint_initialisation:{policy.name(kind)}')
            extensions.append(kind)
            values.setdefault(kind, data[2:] if (tag, None) not in EXTENSION_INIT else data[1:])
            if kind == 1:
                out['transfer_fee_bps'] = _transfer_fee_bps(data)
        elif tag == 6:
            authority_type, has_new = (data[1], data[2]) if len(data) >= 3 else (None, None)
            if authority_type == 0 and has_new == 0 and len(data) == 3:
                mint_authority_revoked = True
            elif authority_type == 1 and has_new == 0 and len(data) == 3:
                freeze_revoked = True        # SetAuthority FreezeAccount -> None: final (MintCannotFreeze after)
            else:
                reasons.append(f'set_authority_on_mint:type_{authority_type}_new_{"some" if has_new else "none"}')
        elif tag in (7, 14):                                   # MintTo / MintToChecked at creation: supply
            continue
        elif tag in READ_ONLY_ON_MINT:                         # queries: they change nothing on the mint
            continue
        else:
            reasons.append(f'unexpected_instruction_on_mint:{_tag_name(tag)}')
    if init is None:
        out['reasons'] = ['mint_initialisation_not_in_creation_trace']
        return out
    program, tag, data = init
    out['token_program'] = TOKEN_PROGRAMS[program]
    # tag, decimals, mint authority (32), freeze authority COption: flag (1) + key (32 when present)
    if len(data) not in (35, 67) or data[34] not in (0, 1) or (data[34] == 1) != (len(data) == 67):
        reasons.append('initialize_mint_layout_unexpected')
    elif data[34] == 1 and not freeze_revoked:
        reasons.append('freeze_authority_present')
    if not mint_authority_revoked:
        reasons.append('mint_authority_not_revoked_at_creation')
    if out['token_program'] == 'spl':
        if extensions:
            reasons.append('extension_on_a_classic_mint')
        out.update(our_account_len=policy.SPL_ACCOUNT_LEN,
                   our_account_rent_lamports=policy.rent_exempt_lamports(policy.SPL_ACCOUNT_LEN))
    else:
        out.update(our_account_len=policy.T22_ATA_LEN,
                   our_account_rent_lamports=policy.rent_exempt_lamports(policy.T22_ATA_LEN))
        if len(set(extensions)) != len(extensions):
            reasons.append('duplicate_extension')
        reasons += [f'extension_refused:{policy.name(k)}' for k in extensions if k not in policy.MINT_ALLOW]
    out['extensions'] = [policy.name(k) for k in extensions]
    out['freeze_authority_final'] = 'present' if 'freeze_authority_present' in reasons else 'none'
    out['mint_authority_final'] = 'none' if mint_authority_revoked else 'present'
    out['reasons'] = reasons
    out['_rebuild'] = dict(decimals=data[1], extensions=list(extensions), values=values)
    if not reasons:
        out['class_'] = 'executable_now' if out['token_program'] == 'spl' else 'token2022_allowlisted'
    return out


def _canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def rebuild_mint(row):
    """Mint account bytes implied by the creation trace (state after creation), for the frozen reader."""
    import base64
    import struct
    info = row['_rebuild']
    base = bytearray(82)
    base[44], base[45] = info['decimals'], 1
    if row['mint_authority_final'] == 'present':
        struct.pack_into('<I', base, 0, 1)
    if row['freeze_authority_final'] == 'present':
        struct.pack_into('<I', base, 46, 1)
    raw = bytes(base)
    if row['token_program'] == 'token2022':
        tlv = b''
        for kind in info['extensions']:
            value = info['values'].get(kind, b'')
            if kind == 18:
                value = value[:64]
            elif kind == 19:
                authority, fields = value
                value = trace_b58decode32(authority) + trace_b58decode32(row['mint']) + fields + struct.pack('<I', 0)
            tlv += struct.pack('<HH', kind, len(value)) + value
        raw = raw + bytes(165 - 82) + b'\x01' + tlv
    owner = policy.TOKEN_2022_PROGRAM if row['token_program'] == 'token2022' else policy.TOKEN_PROGRAM
    return dict(owner=owner, executable=False, lamports=10**7, data=[base64.b64encode(raw).decode(), 'base64'])


def trace_b58decode32(text):
    raw = b58decode(text)
    return raw.rjust(32, b'\0')


def frozen_reader_decision(row):
    """Decision of the frozen ``decode_mint`` (+ frozen authority rule) on the rebuilt Token-2022 mint."""
    from bot.p3.token2022 import TokenEvidenceError, decode_mint
    try:
        facts, _raw = decode_mint(rebuild_mint(row), row['mint'])
    except TokenEvidenceError as exc:
        return f'refuses:{exc}'
    if facts['mint_authority_present'] or facts['freeze_authority_present']:
        return 'refuses:authority_present'
    return 'accepts'


def census(document, frozen_check=False):
    rows, disagreements = [], []
    for entry in sorted(document['pools'], key=lambda e: e['pool']):
        tx = entry.get('creation_transaction')
        row = dict(pool=entry['pool'], creation_signature=entry.get('creation_signature'),
                   creation_body_sha256=None if tx is None else _canonical_sha256(tx),
                   **classify_trace(tx, entry['mint']))
        rebuild = row.pop('_rebuild', None)
        if frozen_check and rebuild is not None and row['token_program'] == 'token2022':
            row['_rebuild'] = rebuild
            row['frozen_reader'] = frozen_reader_decision(row)
            del row['_rebuild']
            if (row['class_'] == 'token2022_allowlisted') != (row['frozen_reader'] == 'accepts'):
                disagreements.append(row['pool'])
        rows.append(row)
    counts = Counter(r['class_'] for r in rows)
    refusals = Counter(reason for r in rows for reason in r['reasons'])
    sets = Counter(tuple(r['extensions']) for r in rows if r['token_program'] == 'token2022')
    return dict(schema='t22pol-census-v1', source='creation_trace', t22pol_version=VERSION,
                policy_source_sha256=policy.SOURCE_SHA256, instruction_source_sha256=INSTRUCTION_SOURCE_SHA256,
                mint_allow=sorted(policy.name(k) for k in policy.MINT_ALLOW), pools=len(rows),
                classes=dict(sorted(counts.items())), refusal_reasons=dict(sorted(refusals.items())),
                extension_sets={' + '.join(k) or '(none)': v for k, v in sorted(sets.items())},
                frozen_check=frozen_check, disagreements_with_frozen_reader=disagreements,
                limits=['extensions and authority revocations read at creation are FINAL (token-2022 processor.rs '
                        '828-850, R02 02cdf353 / 545a06ef); only metadata fields and the metadata pointer can change '
                        'later, with no effect on transfers',
                        'frozen-reader check runs on mint bytes rebuilt from the trace, not on an archived account'],
                rows=rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Token-2022 census from creation transactions (descriptive)')
    parser.add_argument('pools', type=Path)
    parser.add_argument('--frozen-check', action='store_true', help='run from the frozen tree')
    a = parser.parse_args(argv)
    raw = a.pools.read_bytes()
    out = census(json.loads(raw), a.frozen_check)
    out['input_sha256'] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0 if not out['disagreements_with_frozen_reader'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
