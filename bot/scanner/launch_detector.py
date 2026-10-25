from datetime import datetime, timezone

from bot.scanner.transaction_parser import (
    find_initialized_mints,
    find_fee_payer,
    find_signers,
    find_raydium_launch,
    find_raydium_launches,
)


def parse_launch_candidate(
    tx: dict,
    received_at: datetime,
) -> dict:

    block_time = tx.get("blockTime")
    latency_ms = None

    if block_time is not None:
        block_dt = datetime.fromtimestamp(
            block_time,
            tz=timezone.utc,
        )

        latency_ms = max(
            0,
            int(
                (received_at - block_dt).total_seconds()
                * 1000
            ),
        )

    # Informations générales de la transaction
    fee_payer = find_fee_payer(tx)
    signers = find_signers(tx)

    # Authoritative per-creation records. Legacy fields below retain their
    # singular projection, including the historical external-first ordering.
    launches = find_raydium_launches(tx)
    # Décodage spécifique du lancement Raydium
    raydium_launch = find_raydium_launch(tx)

    if raydium_launch:
        mint = raydium_launch.get("mint")
        creator = raydium_launch.get("creator")
        pool_state = raydium_launch.get("pool_state")

        mints = [mint] if mint else []

    else:
        # Une instruction SPL initializeMint isolée ne prouve PAS une
        # création LaunchLab. Ignorer tous les swaps / autres programmes.
        mints = []
        creator = None
        pool_state = None

    return {
        "launches": launches,
        "block_time": block_time,
        "mints": mints,

        # Le vrai creator Raydium lorsqu'il est identifiable
        "creator": creator,

        # Compatibilité temporaire avec la base actuelle
        "deployer_candidate": creator,

        "fee_payer": fee_payer,
        "signers": signers,
        "pool_state": pool_state,

        "detection_latency_ms": latency_ms,

        "status": (
            "creator_identified"
            if raydium_launch and creator
            else "not_launch"
        ),
    }
