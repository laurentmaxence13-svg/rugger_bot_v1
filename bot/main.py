import asyncio

from bot.analyser.multi_creator_research_engine import (
    AdaptiveRPCGate,
    cache_put,
    ensure_schema,
    rpc_json,
)
from bot.config import get_settings
from bot.database.db import Database
from bot.solana.rpc import SolanaRPC
from bot.solana.websocket import stream_program_logs
from bot.scanner.launch_detector import parse_launch_candidate


# Protection du RPC Helius. Une porte adaptative ralentit encore après un 429.
RPC_DELAY_SECONDS = 1.10


async def run(rpc_gate=None, db_path=None):
    settings = get_settings()
    db = Database(db_path or settings.db_path)
    # Keep live scanner transactions in the same research cache used by the
    # historical dataset builder.  Without this bridge, paper_prices from a
    # live launch could never be matched to a research event later.
    ensure_schema(db.path)

    print("=" * 62)
    print("RUGGER BOT V1 - OBSERVATION UNIQUEMENT / AUCUN TRADE REEL")
    print("Protocole V1 : Raydium Launchpad / LaunchLab")
    print(f"Base SQLite  : {settings.db_path}")
    print("=" * 62)

    # Empêche de retraiter plusieurs fois la même transaction
    # pendant une même session du bot.
    seen_signatures = set()
    gate = rpc_gate or AdaptiveRPCGate(RPC_DELAY_SECONDS)

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

            try:
                tx = await rpc_json(
                    rpc,
                    settings.rpc_url,
                    gate,
                    "getTransaction",
                    [
                        signature,
                        {
                            "commitment": "confirmed",
                            "encoding": "jsonParsed",
                            "maxSupportedTransactionVersion": 1,
                        },
                    ],
                )
            except Exception as exc:
                print(f"[TX] récupération indisponible : {type(exc).__name__}")
                continue

            if tx is None:
                print(
                    f"[TX] {signature[:12]}... "
                    f"non disponible / limite RPC"
                )
                continue

            # Cache the exact parsed transaction once.  This is still
            # read-only RPC usage and never signs or sends anything.
            try:
                cache_put(db.path, signature, tx)
            except Exception as exc:
                print(f"[CACHE] écriture différée : {type(exc).__name__}", flush=True)

            parsed = parse_launch_candidate(
                tx,
                event["received_at"],
            )

            mints = parsed["mints"]
            if not mints:
                # Éviter de remplir la base avec des ventes LaunchLab.
                continue

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
                    pool_state=parsed.get("pool_state"),
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
