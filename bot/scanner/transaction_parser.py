"""Détection stricte des créations LaunchLab (pas des swaps).

Les discriminators sont ceux des instructions Anchor LaunchLab. Les comptes
proviennent de l'IDL Raydium: payer=0, creator=1, pool_state=5, base_mint=6.
"""
import hashlib
from typing import Any

RAYDIUM_LAUNCHPAD_PROGRAM_ID = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
TOKEN_PROGRAM_IDS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
# Raydium IDL: initialize_v2, initialize_with_token2022, initialize (ancien).
_CREATE_NAMES = (
    "initialize_v2",
    "initialize_with_token2022",
    "initialize_with_token_2022",
    "initialize",
)
_CREATE_DISCRIMINATORS = {
    hashlib.sha256(("global:" + name).encode()).digest()[:8]
    for name in _CREATE_NAMES
}
# Discriminators vérifiés par des décodeurs LaunchLab publics.
_CREATE_DISCRIMINATORS.update({
    bytes([67, 153, 175, 39, 218, 16, 38, 32]),
    bytes([37, 190, 126, 222, 44, 154, 171, 17]),
})


def _all_instructions(tx: dict[str, Any]) -> list[dict[str, Any]]:
    msg = (tx.get("transaction") or {}).get("message") or {}
    meta = tx.get("meta") or {}
    result = list(msg.get("instructions") or [])
    for group in meta.get("innerInstructions") or []:
        result.extend(group.get("instructions") or [])
    return result


def _decode_base58(data: str) -> bytes:
    value = 0
    for ch in data:
        value = value * 58 + _BASE58.index(ch)
    prefix = len(data) - len(data.lstrip("1"))
    return b"\x00" * prefix + (value.to_bytes((value.bit_length() + 7) // 8, "big") if value else b"")


def _is_launch_instruction(ix: dict[str, Any]) -> bool:
    if ix.get("programId") != RAYDIUM_LAUNCHPAD_PROGRAM_ID:
        return False
    data = ix.get("data")
    if isinstance(data, str):
        try:
            return _decode_base58(data)[:8] in _CREATE_DISCRIMINATORS
        except (ValueError, TypeError):
            return False
    # On n'accepte une instruction sans données que si elle est explicitement
    # décodée par le fournisseur. Jamais sur la seule présence du programme.
    parsed = ix.get("parsed")
    return isinstance(parsed, dict) and parsed.get("type") in _CREATE_NAMES


def find_initialized_mints(tx: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for ix in _all_instructions(tx):
        parsed = ix.get("parsed")
        if not isinstance(parsed, dict) or parsed.get("type") not in {"initializeMint", "initializeMint2"}:
            continue
        if ix.get("programId") not in TOKEN_PROGRAM_IDS and ix.get("program") not in {"spl-token", "spl-token-2022"}:
            continue
        mint = (parsed.get("info") or {}).get("mint")
        if mint and mint not in result:
            result.append(mint)
    return result


def find_fee_payer(tx: dict[str, Any]) -> str | None:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    first = keys[0] if keys else None
    return first.get("pubkey") if isinstance(first, dict) else first if isinstance(first, str) else None


def find_signers(tx: dict[str, Any]) -> list[str]:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    return [k["pubkey"] for k in keys if isinstance(k, dict) and k.get("signer") and k.get("pubkey")]


def find_raydium_launch(tx: dict[str, Any]) -> dict[str, str] | None:
    if not isinstance(tx, dict) or (tx.get("meta") or {}).get("err") is not None:
        return None
    for ix in _all_instructions(tx):
        if not _is_launch_instruction(ix):
            continue
        accounts = ix.get("accounts") or []
        if len(accounts) < 7 or not all(isinstance(a, str) and a for a in accounts[:7]):
            continue
        return {
            "payer": accounts[0],
            "creator": accounts[1],
            "pool_state": accounts[5],
            "mint": accounts[6],
        }
    return None


class ConflictingLaunchMetadata(ValueError):
    """The same mint has incompatible creation identities; reject the batch."""


def unique_launches(launches: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the first identical identity; never merge contradictory fields."""
    by_mint = {}
    for launch in launches:
        if not isinstance(launch, dict) or not all(
                isinstance(launch.get(key), str) and launch[key]
                for key in ('mint', 'creator', 'payer', 'pool_state')):
            raise ValueError('Incomplete LaunchLab creation identity')
        identity = {key: launch[key] for key in ('payer', 'creator', 'pool_state', 'mint')}
        previous = by_mint.get(identity['mint'])
        if previous is not None and previous != identity:
            raise ConflictingLaunchMetadata('Contradictory LaunchLab creation metadata')
        by_mint.setdefault(identity['mint'], identity)
    return list(by_mint.values())


def find_raydium_launches(tx: dict[str, Any]) -> list[dict[str, str]]:
    """All creations in invocation order, with independent identity metadata.

    Visit each outer instruction then its inner instructions in provider order.
    Unattached inner groups follow in their supplied order, preserving support
    for historical inner-only fixtures. The legacy singular API is unchanged.
    """
    if not isinstance(tx, dict) or (tx.get('meta') or {}).get('err') is not None:
        return []
    outer = ((tx.get('transaction') or {}).get('message') or {}).get('instructions') or []
    groups = (tx.get('meta') or {}).get('innerInstructions') or []
    attached = {}
    unattached = []
    for group in groups:
        index = group.get('index')
        target = attached.setdefault(index, []) if type(index) is int and 0 <= index < len(outer) else unattached
        target.extend(group.get('instructions') or [])
    ordered = []
    for index, instruction in enumerate(outer):
        ordered.append(instruction)
        ordered.extend(attached.get(index, []))
    ordered.extend(unattached)
    launches = []
    for ix in ordered:
        if not _is_launch_instruction(ix):
            continue
        accounts = ix.get('accounts') or []
        if len(accounts) < 7 or not all(isinstance(a, str) and a for a in accounts[:7]):
            continue
        launches.append(dict(payer=accounts[0], creator=accounts[1],
                             pool_state=accounts[5], mint=accounts[6]))
    return unique_launches(launches)
