import asyncio
from datetime import datetime, timezone

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC


# --------------------------------------------------
# TOKEN #14
# --------------------------------------------------

MINT = "87L44bmN2bcJX5LTgd8FaXCGUHQQkY2WdrVWVbaYKK6F"

SALE_SIGNATURE = (
    "3Q2kYHY1E21BGjJGitcd53uGkJm6EMWfWUGBRd6nSmwQPx"
    "AGrp5sQS3zQuvev72FdfS2YTGdUVAcfmfYuUKGPBzxw"
)


async def main():
    settings = get_settings()

    print("=" * 60)
    print("IMPACT PRIX - VENTE WALLET RELAIS")
    print("=" * 60)

    print(f"Token : {MINT}")
    print(f"Signature vente : {SALE_SIGNATURE}")

    # --------------------------------------------------
    # RECUPERER LA TRANSACTION DIRECTEMENT DE SOLANA
    # --------------------------------------------------

    async with SolanaRPC(settings.rpc_url) as rpc:
        tx = await rpc.get_transaction(SALE_SIGNATURE)

    if tx is None:
        print("\nERREUR : transaction introuvable.")
        return

    block_time = tx.get("blockTime")

    if block_time is None:
        print("\nERREUR : aucun blockTime dans la transaction.")
        return

    date_utc = datetime.fromtimestamp(
        block_time,
        tz=timezone.utc,
    )

    print()
    print("TRANSACTION TROUVEE")
    print(f"blockTime exact : {block_time}")
    print(f"Date UTC        : {date_utc.isoformat()}")
    print()

    # --------------------------------------------------
    # FENETRE DE PRIX
    # --------------------------------------------------

    time_from = block_time - 300
    time_to = block_time + 600

    print("FENETRE A ANALYSER")
    print(f"5 min avant : {time_from}")
    print(f"Vente       : {block_time}")
    print(f"10 min apres: {time_to}")

    print()
    print("=" * 60)
    print("ETAPE SOLANA TERMINEE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())