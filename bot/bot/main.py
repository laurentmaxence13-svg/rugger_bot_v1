import asyncio

from bot.config import get_settings
from bot.database.db import Database
from bot.solana.rpc import SolanaRPC
from bot.solana.websocket import stream_program_logs
from bot.scanner.launch_detector import parse_launch_candidate


# Protection du RPC Helius.
# V1 volontairement prudente pour éviter les erreurs 429.
RPC_DELAY_SECONDS = 0.35


async def run():
    settings = get_settings()
    db = Database(settings.db_path)

    print("=" * 62)
    print("RUGGER BOT V1 - OBSERVATION UNIQUEMENT / AUCUN TRADE REEL")
    print("Protocole V1 : Raydium Launchpad / LaunchLab")
    print(f"Base SQLite  : {settings.db_path}")
    print("=" * 62)

    # Empêche de retraiter plusieurs fois la même transaction
    # pendant une même session du bot.
    seen_signatures = set()

    async with SolanaRPC(settings.rpc_url) as rpc:

        async for event in stream_program_logs(
            settings.ws_url,
            settings.raydium_launchpad_program_id,
        ):
            signature = event["signature"]

            # Ignore les doublons
            if signature in seen_signatures:
                continue

            seen_signatures.add(signature)

            # Petite limitation volontaire des appels RPC.
            await asyncio.sleep(RPC_DELAY_SECONDS)

            tx = await rpc.get_transaction(signature)

            if tx is None:
                print(
                    f"[TX] {signature[:12]}... "
                    f"non disponible / limite RPC"
                )
                continue

            parsed = parse_launch_candidate(
                tx,
                event["received_at"],
            )

            mints = parsed["mints"] or [None]

            for mint in mints:
                inserted = db.save_candidate(
                    protocol="raydium_launchpad",
                    signature=(
                        signature
                        if len(mints) == 1
                        else f"{signature}:{mint}"
                    ),
                    slot=event["slot"],
                    block_time=parsed["block_time"],
                    detected_at=event["received_at"].isoformat(),
                    mint=mint,
                    deployer_candidate=parsed["deployer_candidate"],
                    detection_latency_ms=parsed[
                        "detection_latency_ms"
                    ],
                    status=parsed["status"],
                )

                if inserted and mint:
                    print("\n[NOUVEAU MINT CANDIDAT]")
                    print(f"Mint      : {mint}")
                    print(
                        f"Deployer* : "
                        f"{parsed['deployer_candidate']}"
                    )
                    print(f"Slot      : {event['slot']}")
                    print(f"TX        : {signature}")
                    print(
                        f"Latence~  : "
                        f"{parsed['detection_latency_ms']} ms"
                    )
                    print(
                        "* = fee payer/signataire candidat, "
                        "a confirmer par analyse ulterieure"
                    )

                elif inserted:
                    print(
                        f"[activite Launchpad] "
                        f"{signature[:16]}... "
                        "(pas d'initializeMint detecte)"
                    )


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nBot arrete.")


if __name__ == "__main__":
    main()