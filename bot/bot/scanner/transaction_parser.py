from typing import Any


RAYDIUM_LAUNCHPAD_PROGRAM_ID = (
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
)

TOKEN_PROGRAM_IDS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}


def _all_instructions(tx: dict[str, Any]) -> list[dict[str, Any]]:
    instructions: list[dict[str, Any]] = []

    message = tx.get("transaction", {}).get("message", {})
    instructions.extend(message.get("instructions", []) or [])

    for group in tx.get("meta", {}).get("innerInstructions", []) or []:
        instructions.extend(group.get("instructions", []) or [])

    return instructions


def find_initialized_mints(tx: dict[str, Any]) -> list[str]:
    mints: list[str] = []

    for ix in _all_instructions(tx):
        parsed = ix.get("parsed")

        if not isinstance(parsed, dict):
            continue

        if parsed.get("type") not in {
            "initializeMint",
            "initializeMint2",
        }:
            continue

        program_id = ix.get("programId")
        program_name = ix.get("program")

        if (
            program_id not in TOKEN_PROGRAM_IDS
            and program_name not in {"spl-token", "spl-token-2022"}
        ):
            continue

        mint = parsed.get("info", {}).get("mint")

        if mint and mint not in mints:
            mints.append(mint)

    return mints


def find_fee_payer(tx: dict[str, Any]) -> str | None:
    keys = (
        tx.get("transaction", {})
        .get("message", {})
        .get("accountKeys", [])
        or []
    )

    if not keys:
        return None

    first = keys[0]

    if isinstance(first, dict):
        return first.get("pubkey")

    if isinstance(first, str):
        return first

    return None


def find_signers(tx: dict[str, Any]) -> list[str]:
    keys = (
        tx.get("transaction", {})
        .get("message", {})
        .get("accountKeys", [])
        or []
    )

    signers: list[str] = []

    for key in keys:
        if isinstance(key, dict) and key.get("signer"):
            pubkey = key.get("pubkey")

            if pubkey:
                signers.append(pubkey)

    return signers


def find_raydium_launch(
    tx: dict[str, Any],
) -> dict[str, str | None] | None:

    if not isinstance(tx, dict) or (tx.get("meta") or {}).get("err") is not None:
        return None

    instructions = (
        tx.get("transaction", {})
        .get("message", {})
        .get("instructions", [])
        or []
    )

    for ix in instructions:

        if ix.get("programId") != RAYDIUM_LAUNCHPAD_PROGRAM_ID:
            continue

        accounts = ix.get("accounts", []) or []

        # Raydium LaunchLab initialize:
        # 0 = payer
        # 1 = creator
        # 5 = pool_state
        # 6 = base_mint
        if len(accounts) < 7:
            continue

        # Une instruction LaunchLab peut aussi être un swap. Ne qualifier de
        # lancement que la transaction qui initialise réellement ce mint.
        if accounts[6] not in find_initialized_mints(tx):
            continue

        return {
            "payer": accounts[0],
            "creator": accounts[1],
            "pool_state": accounts[5],
            "mint": accounts[6],
        }

    return None
