import asyncio
import sqlite3

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import find_raydium_launch


LIMIT = 100
DELAY_SECONDS = 0.5




async def main():
    settings = get_settings()

    # Récupère le dernier creator détecté dans SQLite
    connection = sqlite3.connect(settings.db_path)

    row = connection.execute(
        """
        SELECT deployer_candidate
        FROM launch_candidates
        WHERE mint IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    connection.close()

    if row is None:
        print("Aucun creator trouvé dans la base.")
        return

    creator = row[0]

    print("=" * 60)
    print("ANALYSE HISTORIQUE CREATOR")
    print(f"Creator : {creator}")
    print("=" * 60)

    async with SolanaRPC(settings.rpc_url) as rpc:

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                creator,
                {"limit": LIMIT},
            ],
        }

        async with rpc.session.post(
            settings.rpc_url,
            json=payload,
        ) as response:
            data = await response.json()

        signatures = data.get("result", [])

        print(
            f"\nTransactions récupérées : "
            f"{len(signatures)}"
        )

        launches = []

        for index, item in enumerate(signatures, start=1):
            signature = item["signature"]

            print(
                f"[{index}/{len(signatures)}] Analyse...",
                end=" ",
            )

            tx = await rpc.get_transaction(signature)

            if tx is None:
                print("TX indisponible")
                continue

            launch = find_raydium_launch(tx)

            if launch and launch.get("creator") == creator:
                launches.append(
                    {
                        "mint": launch.get("mint"),
                        "signature": signature,
                        "slot": item.get("slot"),
                    }
                )

                print(
                    f"LAUNCH -> {launch.get('mint')}"
                )

            else:
                print("pas un launch")

            await asyncio.sleep(DELAY_SECONDS)

    print("\n" + "=" * 60)
    print(f"LAUNCHES TROUVES : {len(launches)}")
    print("=" * 60)

    for number, launch in enumerate(launches, start=1):
        print(
            f"{number}. {launch['mint']} "
            f"(slot {launch['slot']})"
        )


if __name__ == "__main__":
    asyncio.run(main())
