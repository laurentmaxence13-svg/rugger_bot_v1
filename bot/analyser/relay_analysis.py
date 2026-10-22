import asyncio
import sqlite3
from collections import Counter

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import find_raydium_launch

PAGE_SIZE = 100
MAX_TRANSACTIONS = 500
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


async def get_signatures(rpc, rpc_url, address):
    results = []
    before = None

    while len(results) < MAX_TRANSACTIONS:
        options = {"limit": PAGE_SIZE}

        if before:
            options["before"] = before

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                address,
                options,
            ],
        }

        async with rpc.session.post(
            rpc_url,
            json=payload,
        ) as response:
            data = await response.json()

        if "error" in data:
            print(
                "Erreur RPC :",
                data["error"],
            )
            break

        page = data.get("result", [])

        if not page:
            break

        results.extend(page)

        if len(page) < PAGE_SIZE:
            break

        before = page[-1].get("signature")

        if not before:
            break

        await asyncio.sleep(0.4)

    return results[:MAX_TRANSACTIONS]


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
        else:
            result.append(key)

    return result


def get_all_instructions(tx):
    result = []

    main = (
        tx.get("transaction", {})
        .get("message", {})
        .get("instructions", [])
        or []
    )

    result.extend(main)

    groups = (
        tx.get("meta", {})
        .get("innerInstructions", [])
        or []
    )

    for group in groups:
        result.extend(
            group.get(
                "instructions",
                [],
            )
            or []
        )

    return result


def is_swap(tx):
    logs = (
        tx.get("meta", {})
        .get("logMessages", [])
        or []
    )

    text = " ".join(
        str(log).lower()
        for log in logs
    )

    full = str(tx).lower()

    keywords = (
        "swap",
        "swapbaseinput",
        "swapbaseoutput",
        "instruction: buy",
        "instruction: sell",
    )

    return any(
        keyword in text
        or keyword in full
        for keyword in keywords
    )


def get_token_account_owners(tx, mint):
    owners = {}

    keys = get_account_keys(tx)

    meta = tx.get("meta", {})

    balances = (
        (
            meta.get(
                "preTokenBalances",
                [],
            )
            or []
        )
        +
        (
            meta.get(
                "postTokenBalances",
                [],
            )
            or []
        )
    )

    for item in balances:
        if item.get("mint") != mint:
            continue

        index = item.get("accountIndex")
        owner = item.get("owner")

        if (
            index is None
            or owner is None
            or index >= len(keys)
        ):
            continue

        account = keys[index]

        if account:
            owners[account] = owner

    return owners


def find_external_transfers(
    tx,
    mint,
    creator,
):
    if is_swap(tx):
        return []

    owners = get_token_account_owners(
        tx,
        mint,
    )

    transfers = []

    for instruction in get_all_instructions(tx):
        parsed = instruction.get("parsed")

        if not isinstance(parsed, dict):
            continue

        if parsed.get("type") not in {
            "transfer",
            "transferChecked",
        }:
            continue

        info = parsed.get("info", {})

        if info.get("authority") != creator:
            continue

        ix_mint = info.get("mint")

        if (
            ix_mint is not None
            and ix_mint != mint
        ):
            continue

        destination = info.get(
            "destination"
        )

        wallet = owners.get(
            destination
        )

        if not wallet:
            continue

        if wallet == creator:
            continue

        transfers.append(
            {
                "wallet": wallet,
                "token_account": destination,
            }
        )

    return transfers


def get_wallet_token_balance(
    tx,
    wallet,
    mint,
    side,
):
    meta = tx.get("meta", {})

    if side == "pre":
        balances = (
            meta.get(
                "preTokenBalances",
                [],
            )
            or []
        )
    else:
        balances = (
            meta.get(
                "postTokenBalances",
                [],
            )
            or []
        )

    total = 0.0

    for item in balances:
        if item.get("owner") != wallet:
            continue

        if item.get("mint") != mint:
            continue

        amount = (
            item.get(
                "uiTokenAmount",
                {},
            )
            .get("uiAmount")
        )

        if amount is not None:
            total += float(amount)

    return total


async def load_transactions(
    rpc,
    signatures,
    label,
):
    transactions = []

    total = len(signatures)

    for index, item in enumerate(
        signatures,
        start=1,
    ):
        print(
            f"[{label} {index}/{total}]",
            end="\r",
        )

        signature = item.get(
            "signature"
        )

        if not signature:
            continue

        tx = await rpc.get_transaction(
            signature
        )

        if tx:
            transactions.append(
                {
                    "signature": signature,
                    "time": item.get(
                        "blockTime"
                    ),
                    "tx": tx,
                }
            )

        await asyncio.sleep(
            RPC_DELAY
        )

    print()

    return transactions


async def analyse_relay(
    rpc,
    rpc_url,
    wallet,
    mint,
    reception_time,
):
    signatures = await get_signatures(
        rpc,
        rpc_url,
        wallet,
    )

    first_sale = None
    final_balance = None

    for item in signatures:
        block_time = item.get(
            "blockTime"
        )

        if (
            reception_time is not None
            and block_time is not None
            and block_time < reception_time
        ):
            continue

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

        if mint not in str(tx):
            await asyncio.sleep(
                RPC_DELAY
            )
            continue

        pre = get_wallet_token_balance(
            tx,
            wallet,
            mint,
            "pre",
        )

        post = get_wallet_token_balance(
            tx,
            wallet,
            mint,
            "post",
        )

        change = post - pre

        final_balance = post

        if (
            change < 0
            and is_swap(tx)
        ):
            delay = None

            if (
                reception_time is not None
                and block_time is not None
            ):
                delay = (
                    block_time
                    - reception_time
                )

            sale = {
                "delay": delay,
                "amount": abs(change),
                "pre": pre,
                "post": post,
                "signature": signature,
            }

            if (
                first_sale is None
                or (
                    delay is not None
                    and (
                        first_sale["delay"]
                        is None
                        or delay
                        < first_sale["delay"]
                    )
                )
            ):
                first_sale = sale

        await asyncio.sleep(
            RPC_DELAY
        )

    return {
        "sale": first_sale,
        "final_balance": final_balance,
    }


async def main():
    settings = get_settings()

    creator = get_latest_creator(
        settings
    )

    if not creator:
        print("Aucun creator trouvé.")
        return

    print("=" * 70)
    print("ANALYSE GLOBALE DES WALLETS RELAIS")
    print("=" * 70)
    print("Creator :", creator)

    async with SolanaRPC(
        settings.rpc_url
    ) as rpc:

        signatures = await get_signatures(
            rpc,
            settings.rpc_url,
            creator,
        )

        print(
            "Transactions creator :",
            len(signatures),
        )

        transactions = (
            await load_transactions(
                rpc,
                signatures,
                "Creator",
            )
        )

        launches = []

        for item in transactions:
            launch = find_raydium_launch(
                item["tx"]
            )

            if not launch:
                continue

            if (
                launch.get("creator")
                != creator
            ):
                continue

            mint = launch.get("mint")

            if not mint:
                continue

            launches.append(
                {
                    "mint": mint,
                    "time": item["time"],
                    "signature":
                        item["signature"],
                }
            )

        launches.sort(
            key=lambda x:
                x["time"] or 0
        )

        print(
            "Launches détectés :",
            len(launches),
        )

        results = []

        for number, launch in enumerate(
            launches,
            start=1,
        ):
            mint = launch["mint"]

            print()
            print("=" * 70)
            print(
                f"[{number}/{len(launches)}] "
                f"{mint}"
            )

            candidates = []

            for item in transactions:
                if (
                    item["signature"]
                    == launch["signature"]
                ):
                    continue

                if (
                    launch["time"] is not None
                    and item["time"] is not None
                    and item["time"]
                    < launch["time"]
                ):
                    continue

                if mint not in str(
                    item["tx"]
                ):
                    continue

                transfers = (
                    find_external_transfers(
                        item["tx"],
                        mint,
                        creator,
                    )
                )

                for transfer in transfers:
                    candidates.append(
                        {
                            "wallet":
                                transfer[
                                    "wallet"
                                ],
                            "time":
                                item["time"],
                            "signature":
                                item[
                                    "signature"
                                ],
                        }
                    )

            if not candidates:
                print(
                    "Aucun wallet relais "
                    "détecté."
                )

                results.append(
                    {
                        "mint": mint,
                        "wallet": None,
                        "sale": None,
                    }
                )

                continue

            candidates.sort(
                key=lambda x:
                    x["time"] or 0
            )

            candidate = candidates[0]

            wallet = candidate["wallet"]

            delay_transfer = None

            if (
                launch["time"] is not None
                and candidate["time"]
                is not None
            ):
                delay_transfer = (
                    candidate["time"]
                    - launch["time"]
                )

            print(
                "Wallet relais :",
                wallet,
            )

            print(
                "Transfert après launch :",
                (
                    f"T+{delay_transfer}s"
                    if delay_transfer
                    is not None
                    else "inconnu"
                ),
            )

            relay = await analyse_relay(
                rpc,
                settings.rpc_url,
                wallet,
                mint,
                candidate["time"],
            )

            sale = relay["sale"]

            if sale:
                print(
                    "VENTE DETECTEE : OUI"
                )

                print(
                    "Délai après réception :",
                    (
                        f"T+{sale['delay']}s"
                        if sale["delay"]
                        is not None
                        else "inconnu"
                    ),
                )

                print(
                    "Tokens vendus :",
                    f"{sale['amount']:.6f}",
                )

                if sale["pre"] > 0:
                    percentage = (
                        sale["amount"]
                        / sale["pre"]
                        * 100
                    )

                    print(
                        "% du solde vendu :",
                        f"{percentage:.1f}%",
                    )

            else:
                print(
                    "VENTE DETECTEE : NON"
                )

            results.append(
                {
                    "mint": mint,
                    "wallet": wallet,
                    "sale": sale,
                    "launch_time": launch["time"],
                    "relay_reception_time": candidate["time"],
                    "sale_time": (
                        candidate["time"] + sale["delay"]
                        if (
                            sale is not None
                            and sale["delay"] is not None
                            and candidate["time"] is not None
                        )
                        else None
                    ),
                }
            )
            if sale:
                print(
                    f"Timestamp exact vente : "
                    f"{results[-1]['sale_time']}"
                )

        # ---------------------------------
        # STATISTIQUES
        # ---------------------------------
        with_relay = [result for result in results if result["wallet"]]
        with_sale = [result for result in results if result["sale"]]

        print("\nTIMESTAMPS EXACTS DES VENTES")
        print("=" * 50)
        for result in with_sale:
            print(
                f"Mint : {result['mint']} | "
                f"Timestamp vente : {result['sale_time']}"
            )

        sale_under_60 = [
            result for result in with_sale
            if result["sale"]["delay"] is not None
            and result["sale"]["delay"] <= 60
        ]
        sale_under_300 = [
            result for result in with_sale
            if result["sale"]["delay"] is not None
            and result["sale"]["delay"] <= 300
        ]
        wallets = [result["wallet"] for result in with_relay]
        wallet_counts = Counter(wallets)
        recurring = {
            wallet: count
            for wallet, count in wallet_counts.items()
            if count > 1
        }

        print()
        print("=" * 70)
        print("PROFIL WALLETS RELAIS")
        print("=" * 70)
        print("Launches analysés :", len(results))
        print("Launches avec wallet relais :", len(with_relay))
        print("Wallet relais ayant vendu :", len(with_sale))

        if with_relay:
            print(
                "% relais ayant vendu :",
                f"{len(with_sale) / len(with_relay) * 100:.1f}%",
            )
        if with_sale:
            print("Ventes <= 60 sec :", f"{len(sale_under_60)}/{len(with_sale)}")
            print("Ventes <= 5 min :", f"{len(sale_under_300)}/{len(with_sale)}")

        print("Wallets relais uniques :", len(wallet_counts))
        print("Wallets relais récurrents :", len(recurring))
        if recurring:
            print()
            print("WALLETS RECURRENTS")
            for wallet, count in sorted(
                recurring.items(), key=lambda x: x[1], reverse=True
            ):
                print(f"{wallet} -> {count} launches")

        print()
        print(
            "NOTE : un wallet relais récurrent "
            "reste un indice comportemental, "
            "pas une preuve d'identité commune."
        )


if __name__ == "__main__":
    asyncio.run(main())
