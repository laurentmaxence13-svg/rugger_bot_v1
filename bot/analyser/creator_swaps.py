import asyncio
import sqlite3

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC


MINT = "2PLLwbwC6xjdiAtVGrxp5eKoc2VSrY5nY6AcoiE94iuH"

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

LIMIT = 100
RPC_DELAY = 0.4


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

    return row[0] if row else None


def get_owner_balances(tx, owner):

    meta = tx.get("meta", {})

    pre = {}
    post = {}

    for item in meta.get(
        "preTokenBalances",
        [],
    ):
        if item.get("owner") != owner:
            continue

        mint = item.get("mint")

        amount = (
            item.get("uiTokenAmount", {})
            .get("uiAmount")
        )

        if mint and amount is not None:
            pre[mint] = (
                pre.get(mint, 0)
                + float(amount)
            )

    for item in meta.get(
        "postTokenBalances",
        [],
    ):
        if item.get("owner") != owner:
            continue

        mint = item.get("mint")

        amount = (
            item.get("uiTokenAmount", {})
            .get("uiAmount")
        )

        if mint and amount is not None:
            post[mint] = (
                post.get(mint, 0)
                + float(amount)
            )

    return pre, post


def get_changes(tx, owner):

    pre, post = get_owner_balances(
        tx,
        owner,
    )

    mints = set(pre) | set(post)

    changes = {}

    for mint in mints:

        before = pre.get(mint, 0)
        after = post.get(mint, 0)

        change = after - before

        if abs(change) > 0.000000001:
            changes[mint] = change

    return changes


def has_swap_log(tx):

    logs = (
        tx.get("meta", {})
        .get("logMessages", [])
        or []
    )

    for log in logs:

        lower = log.lower()

        if (
            "swap" in lower
            or "buy" in lower
            or "sell" in lower
        ):
            return True

    return False


def asset_name(mint):

    if mint == USDC_MINT:
        return "USDC"

    return mint


async def main():

    settings = get_settings()

    creator = get_latest_creator(
        settings
    )

    if creator is None:
        print("Aucun creator trouvé.")
        return

    print("=" * 70)
    print("DETECTION AUTOMATIQUE DES SWAPS")
    print("=" * 70)

    print("Creator :", creator)
    print("Token   :", MINT)
    print()

    async with SolanaRPC(
        settings.rpc_url
    ) as rpc:

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method":
                "getSignaturesForAddress",
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
            "Transactions analysées :",
            len(signatures),
        )

        print()

        events = []

        for index, item in enumerate(
            signatures,
            start=1,
        ):

            signature = item.get(
                "signature"
            )

            if not signature:
                continue

            tx = await rpc.get_transaction(
                signature
            )

            if tx is None:
                continue

            # Ignore les transactions
            # qui ne concernent pas notre token.
            if MINT not in str(tx):
                await asyncio.sleep(
                    RPC_DELAY
                )
                continue

            changes = get_changes(
                tx,
                creator,
            )

            token_change = changes.get(
                MINT,
                0,
            )

            swap = has_swap_log(tx)

            event_type = "AUTRE"

            received = []

            spent = []

            for mint, change in (
                changes.items()
            ):

                if mint == MINT:
                    continue

                if change > 0:
                    received.append(
                        (
                            mint,
                            change,
                        )
                    )

                elif change < 0:
                    spent.append(
                        (
                            mint,
                            abs(change),
                        )
                    )

            # Le creator perd le memecoin
            # pendant un swap.
            if token_change < 0 and swap:
                event_type = "VENTE"

            # Le creator reçoit le memecoin
            # pendant un swap.
            elif token_change > 0 and swap:
                event_type = "ACHAT"

            # Variation sans log de swap.
            elif token_change < 0:
                event_type = (
                    "SORTIE TOKEN"
                )

            elif token_change > 0:
                event_type = (
                    "RECEPTION TOKEN"
                )

            events.append(
                {
                    "type": event_type,
                    "time":
                        item.get(
                            "blockTime"
                        ),
                    "slot":
                        item.get("slot"),
                    "signature":
                        signature,
                    "token_change":
                        token_change,
                    "received":
                        received,
                    "spent":
                        spent,
                }
            )

            print(
                f"[{index}/"
                f"{len(signatures)}] "
                f"{event_type}"
            )

            await asyncio.sleep(
                RPC_DELAY
            )

    events.sort(
        key=lambda event:
            event["time"] or 0
    )

    if not events:
        print(
            "Aucune activité trouvée."
        )
        return

    launch_time = events[0]["time"]

    print()
    print("=" * 70)
    print("CHRONOLOGIE DES EVENEMENTS")
    print("=" * 70)

    for number, event in enumerate(
        events,
        start=1,
    ):

        delay = None

        if (
            launch_time is not None
            and event["time"] is not None
        ):
            delay = (
                event["time"]
                - launch_time
            )

        print()
        print(
            f"{number}. "
            f"{event['type']}"
        )

        if delay is not None:
            print(
                f"   T+{delay} sec"
            )

        print(
            "   Variation memecoin :",
            f"{event['token_change']:+.6f}",
        )

        if event["received"]:

            print(
                "   RECU :"
            )

            for mint, amount in (
                event["received"]
            ):

                print(
                    "      ",
                    asset_name(mint),
                    f"+{amount:.6f}",
                )

        if event["spent"]:

            print(
                "   DEPENSE :"
            )

            for mint, amount in (
                event["spent"]
            ):

                print(
                    "      ",
                    asset_name(mint),
                    f"-{amount:.6f}",
                )

        print(
            "   Slot :",
            event["slot"],
        )

    print()
    print("=" * 70)
    print("VENTES DETECTEES")
    print("=" * 70)

    sales = [
        event
        for event in events
        if event["type"] == "VENTE"
    ]

    print(
        "Nombre de ventes :",
        len(sales),
    )

    for sale in sales:

        delay = (
            sale["time"] - launch_time
            if sale["time"]
            and launch_time
            else 0
        )

        print()
        print(
            f"T+{delay} sec"
        )

        print(
            "Tokens vendus :",
            f"{abs(sale['token_change']):.6f}",
        )

        for mint, amount in (
            sale["received"]
        ):

            print(
                "Reçu :",
                f"{amount:.6f}",
                asset_name(mint),
            )


if __name__ == "__main__":
    asyncio.run(main())