import asyncio
import json
import sqlite3

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC


TARGET_SLOT = 447200526

# Token #7 : x8.12
MINT = "2PLLwbwC6xjdiAtVGrxp5eKoc2VSrY5nY6AcoiE94iuH"

LIMIT = 100


def get_latest_creator(settings):
    connection = sqlite3.connect(settings.db_path)

    row = connection.execute(
        """
        SELECT deployer_candidate
        FROM launch_candidates
        WHERE mint IS NOT NULL
        AND deployer_candidate IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    connection.close()

    if row is None:
        return None

    return row[0]


def show_token_balances(tx, creator):
    meta = tx.get("meta", {})

    print()
    print("=" * 70)
    print("TOKEN #7 - SOLDES AVANT / APRES")
    print("=" * 70)

    print("\nAVANT :")

    for item in meta.get("preTokenBalances", []):

        if item.get("mint") == MINT:
            print(
                "Owner :",
                item.get("owner"),
            )
            print(
                "Montant :",
                item.get(
                    "uiTokenAmount",
                    {},
                ).get("uiAmount"),
            )

    print("\nAPRES :")

    for item in meta.get("postTokenBalances", []):

        if item.get("mint") == MINT:
            print(
                "Owner :",
                item.get("owner"),
            )
            print(
                "Montant :",
                item.get(
                    "uiTokenAmount",
                    {},
                ).get("uiAmount"),
            )

    print()
    print("=" * 70)
    print("TOKENS DU CREATOR")
    print("=" * 70)

    print("\nAVANT :")

    for item in meta.get("preTokenBalances", []):

        if item.get("owner") == creator:
            print(
                item.get("mint"),
                ":",
                item.get(
                    "uiTokenAmount",
                    {},
                ).get("uiAmount"),
            )

    print("\nAPRES :")

    for item in meta.get("postTokenBalances", []):

        if item.get("owner") == creator:
            print(
                item.get("mint"),
                ":",
                item.get(
                    "uiTokenAmount",
                    {},
                ).get("uiAmount"),
            )


def show_instructions(tx):
    print()
    print("=" * 70)
    print("INSTRUCTIONS PRINCIPALES")
    print("=" * 70)

    instructions = (
        tx.get("transaction", {})
        .get("message", {})
        .get("instructions", [])
        or []
    )

    for number, instruction in enumerate(
        instructions,
        start=1,
    ):
        print()
        print(
            f"--- INSTRUCTION {number} ---"
        )

        print(
            json.dumps(
                instruction,
                indent=2,
            )
        )


def show_inner_instructions(tx):
    print()
    print("=" * 70)
    print("INNER INSTRUCTIONS")
    print("=" * 70)

    groups = (
        tx.get("meta", {})
        .get("innerInstructions", [])
        or []
    )

    for group in groups:

        print()
        print(
            "INDEX :",
            group.get("index"),
        )

        for instruction in group.get(
            "instructions",
            [],
        ):

            parsed = instruction.get("parsed")

            if parsed:
                print(
                    json.dumps(
                        parsed,
                        indent=2,
                    )
                )


def show_interesting_logs(tx):
    print()
    print("=" * 70)
    print("LOGS IMPORTANTS")
    print("=" * 70)

    logs = (
        tx.get("meta", {})
        .get("logMessages", [])
        or []
    )

    keywords = [
        "buy",
        "sell",
        "swap",
        "transfer",
        "launch",
    ]

    found = False

    for log in logs:

        lower = log.lower()

        if any(
            word in lower
            for word in keywords
        ):
            print(log)
            found = True

    if not found:
        print(
            "Aucun mot-clé buy/sell/swap/transfer."
        )


async def main():
    settings = get_settings()

    creator = get_latest_creator(settings)

    if creator is None:
        print("Aucun creator trouvé.")
        return

    print("=" * 70)
    print("RECHERCHE DE LA TRANSACTION")
    print("=" * 70)

    print("Creator :", creator)
    print("Slot recherché :", TARGET_SLOT)
    print()

    target_signature = None

    async with SolanaRPC(
        settings.rpc_url
    ) as rpc:

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                creator,
                {
                    "limit": LIMIT,
                },
            ],
        }

        async with rpc.session.post(
            settings.rpc_url,
            json=payload,
        ) as response:
            data = await response.json()

        signatures = data.get(
            "result",
            [],
        )

        print(
            "Transactions trouvées :",
            len(signatures),
        )

        for item in signatures:

            if item.get("slot") == TARGET_SLOT:

                target_signature = item.get(
                    "signature"
                )

                break

        if target_signature is None:
            print(
                "Transaction du slot "
                f"{TARGET_SLOT} introuvable."
            )
            return

        print()
        print("TRANSACTION TROUVEE")
        print(
            "Signature :",
            target_signature,
        )

        tx = await rpc.get_transaction(
            target_signature
        )

    if tx is None:
        print(
            "Impossible de récupérer "
            "la transaction."
        )
        return

    print(
        "Block time :",
        tx.get("blockTime"),
    )

    print(
        "Erreur transaction :",
        tx.get(
            "meta",
            {},
        ).get("err"),
    )

    show_token_balances(
        tx,
        creator,
    )

    show_instructions(tx)

    show_inner_instructions(tx)

    show_interesting_logs(tx)


if __name__ == "__main__":
    asyncio.run(main())