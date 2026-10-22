import asyncio
import sqlite3

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import find_raydium_launch


USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

PAGE_SIZE = 100
MAX_TRANSACTIONS = 1000
RPC_DELAY = 0.35


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


async def get_all_signatures(rpc, rpc_url, creator):
    all_signatures = []
    before = None

    while len(all_signatures) < MAX_TRANSACTIONS:

        options = {
            "limit": PAGE_SIZE,
        }

        if before:
            options["before"] = before

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                creator,
                options,
            ],
        }

        async with rpc.session.post(
            rpc_url,
            json=payload,
        ) as response:
            data = await response.json()

        if "error" in data:
            print("Erreur RPC :", data["error"])
            break

        page = data.get("result", [])

        if not page:
            break

        all_signatures.extend(page)

        print(
            f"Signatures récupérées : "
            f"{len(all_signatures)}"
        )

        if len(page) < PAGE_SIZE:
            break

        before = page[-1].get("signature")

        if not before:
            break

        await asyncio.sleep(0.5)

    return all_signatures[:MAX_TRANSACTIONS]


def get_owner_balances(tx, owner):
    meta = tx.get("meta", {})

    pre = {}
    post = {}

    for item in meta.get(
        "preTokenBalances",
        [],
    ) or []:

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
    ) or []:

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

    changes = {}

    for mint in set(pre) | set(post):

        change = (
            post.get(mint, 0)
            - pre.get(mint, 0)
        )

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
            or "instruction: buy" in lower
            or "instruction: sell" in lower
        ):
            return True

    return False


async def main():
    settings = get_settings()

    creator = get_latest_creator(settings)

    if creator is None:
        print("Aucun creator trouvé.")
        return

    print("=" * 70)
    print("PROFIL COMPLET DU CREATOR")
    print("=" * 70)

    print("Creator :", creator)
    print()

    async with SolanaRPC(
        settings.rpc_url
    ) as rpc:

        # ------------------------------------
        # 1. Historique paginé
        # ------------------------------------

        signatures = await get_all_signatures(
            rpc,
            settings.rpc_url,
            creator,
        )

        print()
        print(
            "TOTAL SIGNATURES :",
            len(signatures),
        )

        print()
        print(
            "Chargement des transactions..."
        )

        transactions = []

        for index, item in enumerate(
            signatures,
            start=1,
        ):

            signature = item.get(
                "signature"
            )

            if not signature:
                continue

            print(
                f"[{index}/{len(signatures)}]",
                end="\r",
            )

            tx = await rpc.get_transaction(
                signature
            )

            if tx is not None:
                transactions.append(
                    {
                        "signature":
                            signature,
                        "slot":
                            item.get("slot"),
                        "block_time":
                            item.get(
                                "blockTime"
                            ),
                        "tx":
                            tx,
                    }
                )

            await asyncio.sleep(
                RPC_DELAY
            )

    print()
    print()

    # ----------------------------------------
    # 2. Identifier les launches
    # ----------------------------------------

    launches_by_mint = {}

    for item in transactions:

        launch = find_raydium_launch(
            item["tx"]
        )

        if not launch:
            continue

        if launch.get("creator") != creator:
            continue

        mint = launch.get("mint")

        if not mint:
            continue

        launches_by_mint[mint] = {
            "mint": mint,
            "launch_time":
                item["block_time"],
            "launch_slot":
                item["slot"],
            "launch_signature":
                item["signature"],
        }

    launches = list(
        launches_by_mint.values()
    )

    launches.sort(
        key=lambda x:
            x["launch_time"] or 0
    )

    print(
        "LAUNCHES DETECTES :",
        len(launches),
    )

    # ----------------------------------------
    # 3. Analyse de chaque token
    # ----------------------------------------

    results = []

    for number, launch in enumerate(
        launches,
        start=1,
    ):

        mint = launch["mint"]

        launch_signature = (
            launch["launch_signature"]
        )

        launch_time = (
            launch["launch_time"]
        )

        events = []

        for item in transactions:

            # IMPORTANT :
            # on exclut explicitement
            # la transaction de création.
            if (
                item["signature"]
                == launch_signature
            ):
                continue

            event_time = item["block_time"]

            # On ignore tout ce qui est
            # antérieur au lancement.
            if (
                launch_time is not None
                and event_time is not None
                and event_time < launch_time
            ):
                continue

            tx = item["tx"]

            if mint not in str(tx):
                continue

            changes = get_changes(
                tx,
                creator,
            )

            token_change = changes.get(
                mint,
                0,
            )

            if abs(token_change) < 0.000000001:
                continue

            usdc_change = changes.get(
                USDC_MINT,
                0,
            )

            swap = has_swap_log(tx)

            delay = None

            if (
                launch_time is not None
                and event_time is not None
            ):
                delay = (
                    event_time
                    - launch_time
                )

            if swap and token_change > 0:
                event_type = "ACHAT"

            elif swap and token_change < 0:
                event_type = "VENTE"

            elif token_change > 0:
                event_type = (
                    "RECEPTION / TRANSFERT"
                )

            else:
                event_type = (
                    "SORTIE / TRANSFERT"
                )

            events.append(
                {
                    "type":
                        event_type,
                    "delay":
                        delay,
                    "token_change":
                        token_change,
                    "usdc_change":
                        usdc_change,
                    "signature":
                        item["signature"],
                }
            )

        events.sort(
            key=lambda x:
                (
                    x["delay"]
                    if x["delay"]
                    is not None
                    else 999999999
                )
        )

        buys = [
            e for e in events
            if e["type"] == "ACHAT"
        ]

        sells = [
            e for e in events
            if e["type"] == "VENTE"
        ]

        transfers_in = [
            e for e in events
            if e["type"]
            == "RECEPTION / TRANSFERT"
        ]

        transfers_out = [
            e for e in events
            if e["type"]
            == "SORTIE / TRANSFERT"
        ]

        first_buy = min(
            (
                e["delay"]
                for e in buys
                if e["delay"] is not None
            ),
            default=None,
        )

        first_sell = min(
            (
                e["delay"]
                for e in sells
                if e["delay"] is not None
            ),
            default=None,
        )

        usdc_spent = sum(
            abs(e["usdc_change"])
            for e in buys
            if e["usdc_change"] < 0
        )

        usdc_received = sum(
            e["usdc_change"]
            for e in sells
            if e["usdc_change"] > 0
        )

        tokens_bought = sum(
            e["token_change"]
            for e in buys
        )

        tokens_sold = sum(
            abs(e["token_change"])
            for e in sells
        )

        result = {
            "mint": mint,
            "buys": len(buys),
            "sells": len(sells),
            "transfers_in":
                len(transfers_in),
            "transfers_out":
                len(transfers_out),
            "first_buy":
                first_buy,
            "first_sell":
                first_sell,
            "usdc_spent":
                usdc_spent,
            "usdc_received":
                usdc_received,
            "tokens_bought":
                tokens_bought,
            "tokens_sold":
                tokens_sold,
        }

        results.append(result)

        print()
        print("=" * 70)

        print(
            f"[{number}/{len(launches)}] "
            f"{mint}"
        )

        print(
            "ACHATS APRES LAUNCH :",
            len(buys),
        )

        print(
            "VENTES APRES LAUNCH :",
            len(sells),
        )

        print(
            "TRANSFERTS RECUS :",
            len(transfers_in),
        )

        print(
            "TRANSFERTS SORTANTS :",
            len(transfers_out),
        )

        print(
            "Premier achat :",
            (
                f"T+{first_buy}s"
                if first_buy is not None
                else "aucun"
            ),
        )

        print(
            "Première vente :",
            (
                f"T+{first_sell}s"
                if first_sell is not None
                else "aucune"
            ),
        )

        print(
            f"USDC dépensés : "
            f"{usdc_spent:.6f}"
        )

        print(
            f"USDC reçus : "
            f"{usdc_received:.6f}"
        )

    # ----------------------------------------
    # 4. Profil global
    # ----------------------------------------

    total = len(results)

    with_buy = sum(
        r["buys"] > 0
        for r in results
    )

    with_sell = sum(
        r["sells"] > 0
        for r in results
    )

    sell_60 = sum(
        r["first_sell"] is not None
        and 0 <= r["first_sell"] <= 60
        for r in results
    )

    sell_300 = sum(
        r["first_sell"] is not None
        and 0 <= r["first_sell"] <= 300
        for r in results
    )

    print()
    print("=" * 70)
    print("PROFIL GLOBAL CORRIGE")
    print("=" * 70)

    print(
        "Launches analysés :",
        total,
    )

    print(
        "Avec achat APRES launch :",
        with_buy,
    )

    print(
        "Avec vente APRES launch :",
        with_sell,
    )

    if total:

        print(
            "% achat après launch :",
            f"{with_buy / total * 100:.1f}%",
        )

        print(
            "% vente après launch :",
            f"{with_sell / total * 100:.1f}%",
        )

        print(
            "% première vente <= 60 sec :",
            f"{sell_60 / total * 100:.1f}%",
        )

        print(
            "% première vente <= 5 min :",
            f"{sell_300 / total * 100:.1f}%",
        )

    print(
        "USDC dépensés détectés :",
        f"{sum(r['usdc_spent'] for r in results):.6f}",
    )

    print(
        "USDC reçus détectés :",
        f"{sum(r['usdc_received'] for r in results):.6f}",
    )

    print()
    print(
        "La transaction de création de chaque "
        "token est exclue des achats/ventes."
    )


if __name__ == "__main__":
    asyncio.run(main())