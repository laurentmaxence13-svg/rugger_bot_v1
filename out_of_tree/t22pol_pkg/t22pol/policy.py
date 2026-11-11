"""Every Token-2022 extension type, its effect on a buy or a sale, and the decision.

Source: solana-program/token-2022, interface/src/extension/mod.rs (``ExtensionType``, ``repr(u16)``,
``get_account_type``, ``required_init_account_extensions``), sha256 d273a87617b06f4a…, the same
file the frozen ``bot.p3.token2022`` pins. Values are the enum order.
"""
import base64
import struct

TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022_PROGRAM = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
SOURCE_SHA256 = 'd273a87617b06f4a813a2c3c3bbab8180a0a4c657d836a95475259eca9e40f5a'
LAMPORTS_PER_BYTE_YEAR, EXEMPTION_YEARS, ACCOUNT_STORAGE_OVERHEAD = 3480, 2, 128
SPL_ACCOUNT_LEN = 165
T22_ATA_LEN = 170            # 165 + AccountType (1) + ImmutableOwner TLV header (4) + 0 bytes of data

# (value, name, account kind, decision, reason)
EXTENSIONS = (
    (0, 'Uninitialized', '-', 'IGNORE', 'padding marker, carries nothing'),
    (1, 'TransferFeeConfig', 'mint', 'REFUSE', 'a fee is withheld on every transfer, including our buy and our sale; '
        'its authority can raise it up to the configured maximum after two epochs'),
    (2, 'TransferFeeAmount', 'account', 'REFUSE', 'exists only with TransferFeeConfig'),
    (3, 'MintCloseAuthority', 'mint', 'REFUSE', 'not needed by any launch seen; refused until shown harmless on data'),
    (4, 'ConfidentialTransferMint', 'mint', 'REFUSE', 'balances may move outside the public amount'),
    (5, 'ConfidentialTransferAccount', 'account', 'REFUSE', 'confidential balances'),
    (6, 'DefaultAccountState', 'mint', 'REFUSE', 'new accounts may start frozen: a buy would land in a frozen account'),
    (7, 'ImmutableOwner', 'account', 'ALLOW_ON_OUR_ACCOUNT', 'added by the associated token account program on '
        'every Token-2022 ATA; it only forbids changing the owner'),
    (8, 'MemoTransfer', 'account', 'REFUSE', 'requires a memo on incoming transfers; never on our accounts'),
    (9, 'NonTransferable', 'mint', 'REFUSE', 'the token cannot be transferred: no sale is possible'),
    (10, 'InterestBearingConfig', 'mint', 'REFUSE', 'display amount differs from the raw amount'),
    (11, 'CpiGuard', 'account', 'REFUSE', 'restricts calls through programs; never on our accounts'),
    (12, 'PermanentDelegate', 'mint', 'REFUSE', 'a third party can transfer or burn our tokens at any time'),
    (13, 'NonTransferableAccount', 'account', 'REFUSE', 'exists only with NonTransferable'),
    (14, 'TransferHook', 'mint', 'REFUSE', 'an arbitrary program runs on every transfer and can make the sale fail'),
    (15, 'TransferHookAccount', 'account', 'REFUSE', 'exists only with TransferHook'),
    (16, 'ConfidentialTransferFeeConfig', 'mint', 'REFUSE', 'confidential fees'),
    (17, 'ConfidentialTransferFeeAmount', 'account', 'REFUSE', 'confidential fees'),
    (18, 'MetadataPointer', 'mint', 'ALLOW', 'points to metadata; no effect on amounts, transfers or holders'),
    (19, 'TokenMetadata', 'mint', 'ALLOW', 'name, symbol, URI; no effect on amounts, transfers or holders'),
    (20, 'GroupPointer', 'mint', 'REFUSE', 'neutral by design but not accepted by the frozen reader; not seen yet'),
    (21, 'TokenGroup', 'mint', 'REFUSE', 'same'),
    (22, 'GroupMemberPointer', 'mint', 'REFUSE', 'same'),
    (23, 'TokenGroupMember', 'mint', 'REFUSE', 'same'),
    (24, 'ConfidentialMintBurn', 'mint', 'REFUSE', 'supply may change confidentially'),
    (25, 'ScaledUiAmount', 'mint', 'REFUSE', 'display amount scaled by an authority-set multiplier'),
    (26, 'Pausable', 'mint', 'REFUSE', 'an authority can pause every transfer: the sale would be blocked'),
    (27, 'PausableAccount', 'account', 'REFUSE', 'exists only with Pausable'),
    (28, 'PermissionedBurn', 'mint', 'REFUSE', 'burn controlled by an authority; not analysed'),
)
BY_VALUE = {row[0]: row for row in EXTENSIONS}
MINT_ALLOW = frozenset(v for v, _n, kind, decision, _r in EXTENSIONS if kind == 'mint' and decision == 'ALLOW')
OUR_ACCOUNT_ALLOW = frozenset(v for v, _n, _k, decision, _r in EXTENSIONS if decision == 'ALLOW_ON_OUR_ACCOUNT')


def rent_exempt_lamports(data_len):
    return (data_len + ACCOUNT_STORAGE_OVERHEAD) * LAMPORTS_PER_BYTE_YEAR * EXEMPTION_YEARS


def extension_types(raw):
    """Every extension type of a Token-2022 mint (in TLV order), or [] for a base mint; never refuses."""
    if len(raw) <= 82:
        return []
    if len(raw) < 166 or raw[165] != 1:
        raise ValueError('not_a_token2022_mint_layout')
    found, offset = [], 166
    while offset + 4 <= len(raw) and any(raw[offset:]):
        kind, size = struct.unpack_from('<HH', raw, offset)
        found.append(kind)
        offset += 4 + size
    return found


def name(kind):
    return BY_VALUE[kind][1] if kind in BY_VALUE else f'unknown_{kind}'


def classify(mint_account, mint_address):
    """Decision for one launched token: executable_now / token2022_allowlisted / refused, with every reason.

    executable_now        SPL Token mint (what the frozen chain trades today);
    token2022_allowlisted Token-2022 mint that the frozen reader accepts (extensions 18 / 19 only) with
                          no mint and no freeze authority: no extension can affect a transfer;
    refused               anything else, unknown or unreadable included.
    """
    out = dict(mint=mint_address, token_program=None, extensions=[], reasons=[], class_=None,
               our_account_len=None, our_account_rent_lamports=None)
    if type(mint_account) is not dict or mint_account.get('executable') is not False:
        out.update(class_='refused', reasons=['mint_account_missing_or_invalid'])
        return out
    owner = mint_account.get('owner')
    try:
        raw = base64.b64decode(mint_account['data'][0], validate=True)
    except (KeyError, IndexError, TypeError, ValueError):
        out.update(class_='refused', reasons=['mint_data_unreadable'])
        return out
    if len(raw) < 82 or raw[45] != 1:
        out.update(class_='refused', reasons=['mint_not_initialized'])
        return out
    mint_authority = struct.unpack_from('<I', raw, 0)[0] == 1
    freeze_authority = struct.unpack_from('<I', raw, 46)[0] == 1
    if owner == TOKEN_PROGRAM:
        out.update(token_program='spl', our_account_len=SPL_ACCOUNT_LEN,
                   our_account_rent_lamports=rent_exempt_lamports(SPL_ACCOUNT_LEN))
        reasons = []
    elif owner == TOKEN_2022_PROGRAM:
        out.update(token_program='token2022', our_account_len=T22_ATA_LEN,
                   our_account_rent_lamports=rent_exempt_lamports(T22_ATA_LEN))
        try:
            kinds = extension_types(raw)
        except ValueError as exc:
            out.update(class_='refused', reasons=[str(exc)])
            return out
        out['extensions'] = [name(k) for k in kinds]
        reasons = [f'extension_refused:{name(k)}' for k in kinds if k not in MINT_ALLOW]
        if len(set(kinds)) != len(kinds):
            reasons.append('duplicate_extension')
    else:
        out.update(class_='refused', reasons=['mint_owner_not_a_token_program'])
        return out
    if mint_authority:
        reasons.append('mint_authority_present')
    if freeze_authority:
        reasons.append('freeze_authority_present')
    out['reasons'] = reasons
    out['class_'] = 'refused' if reasons else ('executable_now' if out['token_program'] == 'spl'
                                               else 'token2022_allowlisted')
    return out
