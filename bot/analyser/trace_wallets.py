import asyncio
import sqlite3

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import find_raydium_launch


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
            "params": [address, options],
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

        results.extend(page)

        print(
            f"Signatures récupérées : {len(results)}"
        )

        if len(page) < PAGE_SIZE:
            break

        before = page[-1].get("signature")

        if not before:
            break

        await asyncio.sleep(0.4)

    return results[:MAX_TRANSACTIONS]


def is_swap_transaction(tx):
    """
    Détecte si la transaction contient un swap.

    Important :
    une vente fait forcément bouger les tokens vers
    un autre compte, mais ce n'est PAS un transfert
    vers un wallet relais.
    """

    meta = tx.get("meta", {})

    # 1. Recherche dans tous les logs
    logs = meta.get("logMessages", []) or []

    swap_words = (
        "swap",
        "swapbaseinput",
        "swapbaseoutput",
        "instruction: buy",
        "instruction: sell",
    )

    for log in logs:
        lower = str(log).lower()

        if any(
            word in lower
            for word in swap_words
        ):
            return True

    # 2. Sécurité supplémentaire :
    # recherche dans toute la transaction.
    tx_text = str(tx).lower()

    if "swapbaseinput" in tx_text:
        return True

    if "swapbaseoutput" in tx_text:
        return True

    if "instruction: swap" in tx_text:
        return True

    return False


def get_token_account_owners(tx, mint):
    owners = {}

    meta = tx.get("meta", {})

    balances = (
        (meta.get("preTokenBalances", []) or [])
        + (meta.get("postTokenBalances", []) or [])
    )

    keys = (
        tx.get("transaction", {})
        .get("message", {})
        .get("accountKeys", [])
        or []
    )

    normalized_keys = []

    for key in keys:
        if isinstance(key, dict):
            normalized_keys.append(
                key.get("pubkey")
            )
        else:
            normalized_keys.append(key)

    for item in balances:
        if item.get("mint") != mint:
            continue

        index = item.get("accountIndex")
        owner = item.get("owner")

        if index is None or owner is None:
            continue

        if index >= len(normalized_keys):
            continue

        token_account = normalized_keys[index]

        if token_account:
            owners[token_account] = owner

    return owners


def get_all_instructions(tx):
    """
    Récupère instructions principales + internes.
    """

    instructions = []

    main = (
        tx.get("transaction", {})
        .get("message", {})
        .get("instructions", [])
        or []
    )

    instructions.extend(main)

    inner_groups = (
        tx.get("meta", {})
        .get("innerInstructions", [])
        or []
    )

    for group in inner_groups:
        instructions.extend(
            group.get("instructions", []) or []
        )

    return instructions


def find_creator_transfers(tx, mint, creator):
    """
    Recherche les transferts du token effectués
    avec le creator comme autorité.
    """

    transfers = []

    owners = get_token_account_owners(
        tx,
        mint,
    )

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

        authority = info.get("authority")

        if authority != creator:
            continue

        instruction_mint = info.get("mint")

        # Pour transferChecked le mint est disponible.
        if (
            instruction_mint is not None
            and instruction_mint != mint
        ):
            continue

        source = info.get("source")
        destination = info.get("destination")

        source_owner = owners.get(source)
        destination_owner = owners.get(destination)

        # Sécurité :
        # la source doit appartenir au creator
        # lorsque l'information est disponible.
        if (
            source_owner is not None
            and source_owner != creator
        ):
            continue

        token_amount = info.get("tokenAmount")

        amount = None

        if isinstance(token_amount, dict):
            amount = token_amount.get("uiAmount")

        if amount is None:
            raw_amount = info.get("amount")

            if raw_amount is not None:
                amount = raw_amount

        transfers.append(
            {
                "source_account": source,
                "destination_account": destination,
                "destination_owner": destination_owner,
                "amount": amount,
            }
        )

    return transfers


async def main():
    settings = get_settings()

    creator = get_latest_creator(settings)

    if creator is None:
        print("Aucun creator trouvé.")
        return

    print("=" * 70)
    print("TRACAGE DES WALLETS - VERSION CORRIGEE")
    print("=" * 70)

    print("Creator :", creator)
    print()

    async with SolanaRPC(
        settings.rpc_url
    ) as rpc:

        signatures = await get_signatures(
            rpc,
            settings.rpc_url,
            creator,
        )

        print()
        print(
            "Transactions creator :",
            len(signatures),
        )

        print("Chargement des transactions...")

        transactions = []

        for index, item in enumerate(
            signatures,
            start=1,
        ):
            print(
                f"[{index}/{len(signatures)}]",
                end="\r",
            )

            signature = item.get("signature")

            if not signature:
                continue

            tx = await rpc.get_transaction(
                signature
            )

            if tx is not None:
                transactions.append(
                    {
                        "signature": signature,
                        "time": item.get(
                            "blockTime"
                        ),
                        "slot": item.get("slot"),
                        "tx": tx,
                    }
                )

            await asyncio.sleep(RPC_DELAY)

    print()
    print()

    # ------------------------------------------------
    # IDENTIFICATION DES LAUNCHES
    # ------------------------------------------------

    launches = {}

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

        launches[mint] = {
            "mint": mint,
            "time": item["time"],
            "slot": item["slot"],
            "signature": item["signature"],
        }

    launches_list = sorted(
        launches.values(),
        key=lambda x: x["time"] or 0,
    )

    print(
        "Launches détectés :",
        len(launches_list),
    )

    # ------------------------------------------------
    # RECHERCHE DES VRAIS TRANSFERTS
    # ------------------------------------------------

    total_external = 0
    tokens_with_external = 0
    swaps_ignored = 0

    for number, launch in enumerate(
        launches_list,
        start=1,
    ):
        mint = launch["mint"]

        print()
        print("=" * 70)

        print(
            f"[{number}/{len(launches_list)}] "
            f"{mint}"
        )

        external = []

        for item in transactions:

            # Ne jamais analyser le launch lui-même
            # comme transfert post-launch.
            if (
                item["signature"]
                == launch["signature"]
            ):
                continue

            # Ignorer transactions antérieures.
            if (
                launch["time"] is not None
                and item["time"] is not None
                and item["time"] < launch["time"]
            ):
                continue

            tx = item["tx"]

            if mint not in str(tx):
                continue

            transfers = find_creator_transfers(
                tx,
                mint,
                creator,
            )

            if not transfers:
                continue

            # IMPORTANT :
            # si ces mouvements appartiennent à un
            # swap, ce n'est pas un wallet relais.
            if is_swap_transaction(tx):
                swaps_ignored += 1

                print(
                    "SWAP ignoré :",
                    item["signature"][:12] + "...",
                )

                continue

            for transfer in transfers:
                destination_owner = (
                    transfer[
                        "destination_owner"
                    ]
                )

                # Transfert entre comptes appartenant
                # au creator lui-même.
                if destination_owner == creator:
                    continue

                delay = None

                if (
                    launch["time"] is not None
                    and item["time"] is not None
                ):
                    delay = (
                        item["time"]
                        - launch["time"]
                    )

                external.append(
                    {
                        "delay": delay,
                        "amount":
                            transfer["amount"],
                        "wallet":
                            destination_owner,
                        "token_account":
                            transfer[
                                "destination_account"
                            ],
                        "signature":
                            item["signature"],
                    }
                )

        if not external:
            print(
                "Aucun transfert externe "
                "hors swap détecté."
            )
            continue

        tokens_with_external += 1
        total_external += len(external)

        print(
            "TRANSFERTS EXTERNES REELS :",
            len(external),
        )

        for transfer in external:
            print()

            if transfer["delay"] is not None:
                print(
                    "Délai : "
                    f"T+{transfer['delay']}s"
                )
            else:
                print("Délai : inconnu")

            print(
                "Montant :",
                transfer["amount"],
            )

            print(
                "Wallet destination :",
                (
                    transfer["wallet"]
                    or "owner non résolu"
                ),
            )

            print(
                "Token account :",
                transfer["token_account"],
            )

            print(
                "Signature :",
                transfer["signature"],
            )

    # ------------------------------------------------
    # RESUME
    # ------------------------------------------------

    print()
    print("=" * 70)
    print("RESUME")
    print("=" * 70)

    print(
        "Launches analysés :",
        len(launches_list),
    )

    print(
        "Transactions de swap ignorées :",
        swaps_ignored,
    )

    print(
        "Tokens avec transfert externe :",
        tokens_with_external,
    )

    print(
        "Transferts externes hors swap :",
        total_external,
    )

    print()
    print(
        "Un transfert externe hors swap "
        "est un candidat wallet relais, "
        "pas une preuve qu'il appartient au creator."
    )


if __name__ == "__main__":
    asyncio.run(main())