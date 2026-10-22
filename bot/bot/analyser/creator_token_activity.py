import asyncio
import sqlite3
from datetime import datetime

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC


# Token #7 : environ x8.12 dans notre analyse Birdeye
MINT = "2PLLwbwC6xjdiAtVGrxp5eKoc2VSrY5nY6AcoiE94iuH"

LIMIT = 100
RPC_DELAY = 0.4
LAMPORTS_PER_SOL = 1_000_000_000


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


def get_account_keys(tx):

    keys = (
        tx.get("transaction", {})
        .get("message", {})
        .get("accountKeys", [])
        or []
    )

    result = []

    for key in keys:

        if isinstance(key, dict):
            result.append(key.get("pubkey"))

        elif isinstance(key, str):
            result.append(key)

    return result


def get_sol_change(tx, creator):

    keys = get_account_keys(tx)

    if creator not in keys:
        return None

    index = keys.index(creator)

    meta = tx.get("meta", {})

    pre = meta.get("preBalances", [])
    post = meta.get("postBalances", [])

    if index >= len(pre) or index >= len(post):
        return None

    change_lamports = post[index] - pre[index]

    return change_lamports / LAMPORTS_PER_SOL


def get_token_balance(
    balances,
    creator,
    mint,
):

    total = 0.0

    for item in balances or []:

        if item.get("owner") != creator:
            continue

        if item.get("mint") != mint:
            continue

        ui_amount = (
            item.get("uiTokenAmount", {})
            .get("uiAmount")
        )

        if ui_amount is not None:
            total += float(ui_amount)

    return total


def get_token_change(
    tx,
    creator,
    mint,
):

    meta = tx.get("meta", {})

    pre = get_token_balance(
        meta.get("preTokenBalances", []),
        creator,
        mint,
    )

    post = get_token_balance(
        meta.get("postTokenBalances", []),
        creator,
        mint,
    )

    return post - pre


def contains_mint(tx, mint):
    return mint in str(tx)


def classify_transaction(
    sol_change,
    token_change,
):

    if sol_change is None:
        return "INCONNU"

    # Achat :
    # le creator reçoit des tokens
    # et son SOL diminue.
    if token_change > 0 and sol_change < 0:
        return "ACHAT"

    # Vente :
    # le creator perd des tokens
    # et son SOL augmente.
    if token_change < 0 and sol_change > 0:
        return "VENTE"

    if token_change > 0:
        return "RECEPTION TOKEN"

    if token_change < 0:
        return "SORTIE TOKEN"

    return "AUTRE / LAUNCH"


async def main():

    settings = get_settings()

    creator = get_latest_creator(settings)

    if creator is None:
        print("Aucun creator trouvé.")
        return

    print("=" * 70)
    print("ANALYSE ON-CHAIN DU CREATOR")
    print("=" * 70)

    print("Creator :", creator)
    print("Mint    :", MINT)
    print()

    async with SolanaRPC(settings.rpc_url) as rpc:

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

        if "error" in data:
            print("Erreur RPC :", data["error"])
            return

        signatures = data.get("result", [])

        print(
            "Transactions creator :",
            len(signatures),
        )

        print()

        matches = []

        for index, item in enumerate(
            signatures,
            start=1,
        ):

            signature = item.get("signature")

            if not signature:
                continue

            print(
                f"[{index}/{len(signatures)}]",
                end=" ",
            )

            tx = await rpc.get_transaction(
                signature
            )

            if tx is None:
                print("TX indisponible")
                await asyncio.sleep(RPC_DELAY)
                continue

            if not contains_mint(tx, MINT):
                print("-")
                await asyncio.sleep(RPC_DELAY)
                continue

            sol_change = get_sol_change(
                tx,
                creator,
            )

            token_change = get_token_change(
                tx,
                creator,
                MINT,
            )

            transaction_type = classify_transaction(
                sol_change,
                token_change,
            )

            matches.append(
                {
                    "signature": signature,
                    "slot": item.get("slot"),
                    "block_time": item.get(
                        "blockTime"
                    ),
                    "sol_change": sol_change,
                    "token_change": token_change,
                    "type": transaction_type,
                }
            )

            print(transaction_type)

            await asyncio.sleep(RPC_DELAY)

    # Ordre chronologique
    matches.sort(
        key=lambda x: x["block_time"] or 0
    )

    if not matches:
        print()
        print(
            "Aucune transaction liée au token."
        )
        return

    launch_time = matches[0]["block_time"]

    print()
    print("=" * 70)
    print("CHRONOLOGIE")
    print("=" * 70)

    for number, tx in enumerate(
        matches,
        start=1,
    ):

        block_time = tx["block_time"]

        if (
            launch_time is not None
            and block_time is not None
        ):
            delay = block_time - launch_time
        else:
            delay = None

        if block_time:
            date = datetime.fromtimestamp(
                block_time
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            date = "N/A"

        print()
        print(
            f"{number}. {tx['type']}"
        )

        print(
            f"   Date : {date}"
        )

        if delay is not None:
            print(
                f"   Temps depuis 1ere TX : "
                f"{delay} sec"
            )

        if tx["sol_change"] is not None:
            print(
                f"   Variation SOL : "
                f"{tx['sol_change']:+.9f} SOL"
            )

        print(
            f"   Variation token : "
            f"{tx['token_change']:+.6f}"
        )

        print(
            f"   Slot : {tx['slot']}"
        )

        print(
            f"   Signature : "
            f"{tx['signature']}"
        )

    print()
    print("=" * 70)
    print("RESUME")
    print("=" * 70)

    buys = [
        tx
        for tx in matches
        if tx["type"] == "ACHAT"
    ]

    sells = [
        tx
        for tx in matches
        if tx["type"] == "VENTE"
    ]

    sol_spent = sum(
        abs(tx["sol_change"])
        for tx in buys
        if tx["sol_change"] is not None
    )

    sol_received = sum(
        tx["sol_change"]
        for tx in sells
        if tx["sol_change"] is not None
    )

    print(
        "Transactions liées :",
        len(matches),
    )

    print(
        "Achats détectés :",
        len(buys),
    )

    print(
        "Ventes détectées :",
        len(sells),
    )

    print(
        f"SOL sortis sur achats : "
        f"{sol_spent:.6f}"
    )

    print(
        f"SOL reçus sur ventes : "
        f"{sol_received:.6f}"
    )


if __name__ == "__main__":
    asyncio.run(main())