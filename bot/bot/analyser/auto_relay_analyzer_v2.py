import asyncio
import sqlite3

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
            "params": [address, options],
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
        word in text or word in full
        for word in keywords
    )


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
            result.append(
                key.get("pubkey")
            )
        else:
            result.append(key)

    return result


def get_token_account_owners(tx, mint):
    owners = {}

    keys = get_account_keys(tx)

    meta = tx.get("meta", {})

    balances = (
        (meta.get(
            "preTokenBalances",
            [],
        ) or [])
        +
        (meta.get(
            "postTokenBalances",
            [],
        ) or [])
    )

    for item in balances:
        if item.get("mint") != mint:
            continue

        index = item.get(
            "accountIndex"
        )

        owner = item.get("owner")

        if (
            index is None
            or owner is None
            or index >= len(keys)
        ):
            continue

        token_account = keys[index]

        if token_account:
            owners[token_account] = owner

    return owners


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
        parsed = instruction.get(
            "parsed"
        )

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

        source = info.get("source")

        destination = info.get(
            "destination"
        )

        source_owner = owners.get(source)

        destination_owner = owners.get(
            destination
        )

        if (
            source_owner is not None
            and source_owner != creator
        ):
            continue

        if destination_owner == creator:
            continue

        if not destination_owner:
            continue

        transfers.append(
            {
                "wallet":
                    destination_owner,
                "token_account":
                    destination,
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




WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

def _owner_balances(tx, wallet, side):
    meta = tx.get("meta", {}) or {}
    key = "preTokenBalances" if side == "pre" else "postTokenBalances"
    out = {}
    for item in meta.get(key, []) or []:
        if item.get("owner") != wallet:
            continue
        mint = item.get("mint")
        amount = (item.get("uiTokenAmount") or {}).get("uiAmount")
        if mint and amount is not None:
            out[mint] = out.get(mint, 0.0) + float(amount)
    return out

def analyze_sale_swap(tx, wallet, sold_mint):
    pre = _owner_balances(tx, wallet, "pre")
    post = _owner_balances(tx, wallet, "post")
    sold = max(0.0, pre.get(sold_mint, 0.0) - post.get(sold_mint, 0.0))
    received = []
    for asset_mint in set(pre) | set(post):
        if asset_mint == sold_mint:
            continue
        delta = post.get(asset_mint, 0.0) - pre.get(asset_mint, 0.0)
        if delta > 1e-12:
            received.append((asset_mint, delta))

    keys = get_account_keys(tx)
    native_sol_delta = None
    try:
        i = keys.index(wallet)
        meta = tx.get("meta", {}) or {}
        pre_lamports = (meta.get("preBalances") or [])[i]
        post_lamports = (meta.get("postBalances") or [])[i]
        fee = float(meta.get("fee") or 0)
        native_sol_delta = (post_lamports - pre_lamports + fee) / 1_000_000_000
    except (ValueError, IndexError, TypeError):
        pass
    return sold, received, native_sol_delta

def asset_name(mint):
    return {WSOL_MINT: "SOL/WSOL", USDC_MINT: "USDC"}.get(mint, mint)


async def main():
    settings = get_settings()

    creator = get_latest_creator(settings)

    if not creator:
        print("Aucun creator trouvé.")
        return

    print("=" * 70)
    print("FOLLOW WALLET AUTOMATIQUE")
    print("=" * 70)
    print("Creator :", creator)

    async with SolanaRPC(settings.rpc_url) as rpc:
        # --------------------------------
        # HISTORIQUE CREATOR
        # --------------------------------
        creator_signatures = await get_signatures(
            rpc,
            settings.rpc_url,
            creator,
        )

        print("Transactions creator :", len(creator_signatures))

        creator_txs = []

        for index, item in enumerate(creator_signatures, start=1):
            print(
                f"[Creator {index}/{len(creator_signatures)}]",
                end="\r",
            )

            signature = item.get("signature")
            if not signature:
                continue

            tx = await rpc.get_transaction(signature)

            if tx:
                creator_txs.append(
                    {
                        "signature": signature,
                        "time": item.get("blockTime"),
                        "tx": tx,
                    }
                )

            await asyncio.sleep(RPC_DELAY)

        print()
        print()

        # --------------------------------
        # TROUVER LES LAUNCHES
        # --------------------------------
        launches = []

        for item in creator_txs:
            launch = find_raydium_launch(item["tx"])

            if not launch:
                continue

            if launch.get("creator") != creator:
                continue

            mint = launch.get("mint")
            if not mint:
                continue

            launches.append(
                {
                    "mint": mint,
                    "time": item["time"],
                    "signature": item["signature"],
                }
            )

        launches.sort(key=lambda x: x["time"] or 0)
        print("Launches trouvés :", len(launches))

        # --------------------------------
        # TROUVER AUTOMATIQUEMENT
        # UN VRAI WALLET DESTINATION
        # --------------------------------
        candidate = None

        for launch in reversed(launches):
            mint = launch["mint"]

            for item in creator_txs:
                if item["signature"] == launch["signature"]:
                    continue

                if (
                    launch["time"] is not None
                    and item["time"] is not None
                    and item["time"] < launch["time"]
                ):
                    continue

                if mint not in str(item["tx"]):
                    continue

                transfers = find_external_transfers(
                    item["tx"],
                    mint,
                    creator,
                )

                if not transfers:
                    continue

                transfer = transfers[0]
                candidate = {
                    "mint": mint,
                    "wallet": transfer["wallet"],
                    "token_account": transfer["token_account"],
                    "transfer_time": item["time"],
                    "launch_time": launch["time"],
                    "signature": item["signature"],
                }
                break

            if candidate:
                break

        if not candidate:
            print("Aucun wallet destination hors swap trouvé.")
            return

        wallet = candidate["wallet"]
        mint = candidate["mint"]

        print()
        print("=" * 70)
        print("WALLET TROUVE AUTOMATIQUEMENT")
        print("=" * 70)
        print("Token :", mint)
        print("Wallet :", wallet)
        print("Longueur adresse :", len(wallet))
        print("Token account :", candidate["token_account"])

        if (
            candidate["launch_time"] is not None
            and candidate["transfer_time"] is not None
        ):
            print(
                "Transfert : T+"
                f"{candidate['transfer_time'] - candidate['launch_time']}s"
            )

        print("Signature transfert :", candidate["signature"])

        # --------------------------------
        # HISTORIQUE DU WALLET TROUVE
        # --------------------------------
        print()
        print("Récupération historique du wallet...")

        wallet_signatures = await get_signatures(
            rpc,
            settings.rpc_url,
            wallet,
        )

        print("Transactions wallet :", len(wallet_signatures))

        events = []

        for index, item in enumerate(wallet_signatures, start=1):
            print(
                f"[Wallet {index}/{len(wallet_signatures)}]",
                end="\r",
            )

            signature = item.get("signature")
            if not signature:
                continue

            tx = await rpc.get_transaction(signature)
            if tx is None:
                continue

            if mint not in str(tx):
                await asyncio.sleep(RPC_DELAY)
                continue

            pre = get_wallet_token_balance(tx, wallet, mint, "pre")
            post = get_wallet_token_balance(tx, wallet, mint, "post")
            change = post - pre

            if abs(change) < 1e-9:
                await asyncio.sleep(RPC_DELAY)
                continue

            if change > 0:
                event_type = "RECEPTION"
            elif is_swap(tx):
                event_type = "VENTE / SWAP"
            else:
                event_type = "TRANSFERT SORTANT"

            events.append(
                {
                    "type": event_type,
                    "change": change,
                    "pre": pre,
                    "post": post,
                    "time": item.get("blockTime"),
                    "signature": signature,
                }
            )

            await asyncio.sleep(RPC_DELAY)

    # ------------------------------------
    # RESULTATS
    # ------------------------------------
    events.sort(key=lambda x: x["time"] or 0)

    print()
    print()
    print("=" * 70)
    print("CHRONOLOGIE WALLET RELAIS")
    print("=" * 70)

    if not events:
        print("Aucun mouvement trouvé.")
        return

    for number, event in enumerate(events, start=1):
        print()
        print(f"{number}. {event['type']}")

        if (
            candidate["transfer_time"] is not None
            and event["time"] is not None
        ):
            delay = event["time"] - candidate["transfer_time"]
            print(f"Depuis réception : T+{delay}s")
        else:
            print("Depuis réception : inconnu")

        print(f"BlockTime exact : {event['time']}")
        print(f"Signature exacte : {event['signature']}")
        print("Variation :", f"{event['change']:+.6f}")
        print("Solde avant :", f"{event['pre']:.6f}")
        print("Solde après :", f"{event['post']:.6f}")

    sells = [
        event
        for event in events
        if event["type"] == "VENTE / SWAP"
    ]

    outgoing = [
        event
        for event in events
        if event["type"] == "TRANSFERT SORTANT"
    ]

    if sells:
        print()
        print("=" * 70)
        print("ANALYSE AUTOMATIQUE DE LA VENTE")
        print("=" * 70)
        for sale_number, sale in enumerate(sells, start=1):
            sold_tokens, received, native_sol = analyze_sale_swap(
                sale["tx"], wallet, mint
            )
            print(f"Vente #{sale_number}")
            print(f"Tokens vendus : {sold_tokens:.6f}")
            for received_mint, received_amount in received:
                name = asset_name(received_mint)
                print("Actif reçu :", name, f"| Montant : {received_amount:.9f}")
                if sold_tokens > 0:
                    print(
                        "Prix implicite par token :",
                        f"{received_amount / sold_tokens:.12f}",
                        name,
                    )
            if native_sol is not None and native_sol > 1e-12:
                print(f"SOL natif reçu (frais neutralisés) : {native_sol:.9f}")
                if sold_tokens > 0:
                    print(
                        "Prix implicite par token :",
                        f"{native_sol / sold_tokens:.12f} SOL",
                    )

    print()
    print("=" * 70)
    print("RESUME")
    print("=" * 70)
    print("Wallet analysé :", wallet)
    print("Token :", mint)
    print("Ventes détectées :", len(sells))
    print("Transferts suivants :", len(outgoing))

    if events:
        print("Solde final observé :", f"{events[-1]['post']:.6f}")


if __name__ == "__main__":
    asyncio.run(main())
