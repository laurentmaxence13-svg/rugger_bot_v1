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

    print("=" * 110)
    print("ANALYSE GLOBALE CREATOR -> LAUNCHES -> RELAYS -> VENTES")
    print("=" * 110)
    print("Creator :", creator)

    async with SolanaRPC(settings.rpc_url) as rpc:
        creator_signatures = await get_signatures(rpc, settings.rpc_url, creator)
        creator_txs = []

        for index, item in enumerate(creator_signatures, start=1):
            print(f"[Creator {index}/{len(creator_signatures)}]", end="\r")
            sig = item.get("signature")
            if not sig:
                continue
            tx = await rpc.get_transaction(sig)
            if tx:
                creator_txs.append({
                    "signature": sig,
                    "time": item.get("blockTime"),
                    "tx": tx,
                })
            await asyncio.sleep(RPC_DELAY)

        launches = []
        for item in creator_txs:
            launch = find_raydium_launch(item["tx"])
            if not launch or launch.get("creator") != creator or not launch.get("mint"):
                continue
            launches.append({
                "mint": launch["mint"],
                "time": item["time"],
                "signature": item["signature"],
            })

        launches.sort(key=lambda x: x["time"] or 0)
        print("\nLaunches trouvés :", len(launches))

        # Cache: several launches reuse the same relay wallet.
        wallet_cache = {}
        results = []

        for n, launch in enumerate(launches, start=1):
            mint = launch["mint"]
            print(f"\n[{n}/{len(launches)}] {mint}")

            # Find the first external creator transfer for THIS launch/token.
            candidate = None
            possible = []
            for item in creator_txs:
                if item["signature"] == launch["signature"]:
                    continue
                if launch["time"] is not None and item["time"] is not None and item["time"] < launch["time"]:
                    continue
                if mint not in str(item["tx"]):
                    continue
                transfers = find_external_transfers(item["tx"], mint, creator)
                for transfer in transfers:
                    possible.append({
                        "wallet": transfer["wallet"],
                        "token_account": transfer["token_account"],
                        "transfer_time": item["time"],
                        "signature": item["signature"],
                    })

            possible.sort(key=lambda x: x["transfer_time"] or 0)
            if possible:
                candidate = possible[0]

            row = {
                "n": n,
                "mint": mint,
                "relay": None,
                "transfer_delay": None,
                "sale_delay": None,
                "sold_pct": None,
                "sol_received": None,
                "sale_price_sol": None,
                "status": "",
            }

            if not candidate:
                row["status"] = "Aucun relay"
                results.append(row)
                print("  Aucun wallet relais détecté.")
                continue

            wallet = candidate["wallet"]
            row["relay"] = wallet
            if launch["time"] is not None and candidate["transfer_time"] is not None:
                row["transfer_delay"] = candidate["transfer_time"] - launch["time"]

            if wallet not in wallet_cache:
                sigs = await get_signatures(rpc, settings.rpc_url, wallet)
                txs = []
                for i, sig_item in enumerate(sigs, start=1):
                    print(f"  [Relay {i}/{len(sigs)}]", end="\r")
                    sig = sig_item.get("signature")
                    if not sig:
                        continue
                    tx = await rpc.get_transaction(sig)
                    if tx:
                        txs.append({
                            "signature": sig,
                            "time": sig_item.get("blockTime"),
                            "tx": tx,
                        })
                    await asyncio.sleep(RPC_DELAY)
                wallet_cache[wallet] = txs
                print(" " * 60, end="\r")

            events = []
            for item in wallet_cache[wallet]:
                tx = item["tx"]
                if mint not in str(tx):
                    continue
                pre = get_wallet_token_balance(tx, wallet, mint, "pre")
                post = get_wallet_token_balance(tx, wallet, mint, "post")
                change = post - pre
                if abs(change) < 1e-9:
                    continue
                if change > 0:
                    kind = "RECEPTION"
                elif is_swap(tx):
                    kind = "VENTE / SWAP"
                else:
                    kind = "TRANSFERT SORTANT"
                events.append({
                    "type": kind,
                    "change": change,
                    "pre": pre,
                    "post": post,
                    "time": item["time"],
                    "signature": item["signature"],
                    "tx": tx,
                })

            events.sort(key=lambda x: x["time"] or 0)
            sales = [
                e for e in events
                if e["type"] == "VENTE / SWAP"
                and (
                    candidate["transfer_time"] is None
                    or e["time"] is None
                    or e["time"] >= candidate["transfer_time"]
                )
            ]

            if not sales:
                row["status"] = "Relay sans vente détectée"
                results.append(row)
                print(f"  Relay {wallet[:8]}... | aucune vente détectée")
                continue

            sale = sales[0]
            if sale["time"] is not None and candidate["transfer_time"] is not None:
                row["sale_delay"] = sale["time"] - candidate["transfer_time"]

            received_balance = None
            receptions = [
                e for e in events
                if e["type"] == "RECEPTION"
                and (
                    candidate["transfer_time"] is None
                    or e["time"] is None
                    or e["time"] >= candidate["transfer_time"]
                )
            ]
            if receptions:
                received_balance = receptions[0]["post"]

            sold_tokens, received_assets, native_sol = analyze_sale_swap(
                sale["tx"], wallet, mint
            )

            if received_balance and received_balance > 0:
                row["sold_pct"] = min(100.0, sold_tokens / received_balance * 100.0)

            # Prefer native SOL. If WSOL was received, use that as SOL-equivalent.
            sol_received = native_sol if native_sol is not None and native_sol > 1e-12 else None
            if sol_received is None:
                for asset_mint, amount in received_assets:
                    if asset_mint == WSOL_MINT and amount > 0:
                        sol_received = amount
                        break

            row["sol_received"] = sol_received
            if sol_received is not None and sold_tokens > 0:
                row["sale_price_sol"] = sol_received / sold_tokens

            row["status"] = "Vente détectée"
            results.append(row)
            print(
                f"  Relay {wallet[:8]}... | "
                f"Tvente={row['sale_delay']}s | "
                f"vendu={row['sold_pct'] if row['sold_pct'] is not None else '?'}% | "
                f"SOL={row['sol_received'] if row['sol_received'] is not None else '?'}"
            )

    print("\n" + "=" * 110)
    print("TABLEAU GLOBAL")
    print("=" * 110)
    header = (
        f"{'#':>2}  {'MINT':<10} {'RELAY':<10} "
        f"{'Ttrans':>7} {'Tvente':>7} {'%vendu':>8} "
        f"{'SOL recu':>12} {'Prix SOL/token':>16}  STATUT"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        mint_short = r["mint"][:8] + ".."
        relay_short = (r["relay"][:8] + "..") if r["relay"] else "-"
        td = f"{r['transfer_delay']}s" if r["transfer_delay"] is not None else "-"
        sd = f"{r['sale_delay']}s" if r["sale_delay"] is not None else "-"
        pct = f"{r['sold_pct']:.1f}" if r["sold_pct"] is not None else "-"
        sol = f"{r['sol_received']:.9f}" if r["sol_received"] is not None else "-"
        price = f"{r['sale_price_sol']:.12f}" if r["sale_price_sol"] is not None else "-"
        print(
            f"{r['n']:>2}  {mint_short:<10} {relay_short:<10} "
            f"{td:>7} {sd:>7} {pct:>8} "
            f"{sol:>12} {price:>16}  {r['status']}"
        )

    relays = [r for r in results if r["relay"]]
    sold = [r for r in results if r["status"] == "Vente détectée"]
    print("\n" + "=" * 110)
    print("SYNTHESE")
    print("=" * 110)
    print("Launches analysés :", len(results))
    print("Launches avec relay :", len(relays))
    print("Relays avec vente détectée :", len(sold))
    if sold:
        delays = [r["sale_delay"] for r in sold if r["sale_delay"] is not None]
        if delays:
            print("Délai vente moyen après réception :", round(sum(delays) / len(delays), 1), "s")
            print("Ventes <= 60 s :", sum(d <= 60 for d in delays), "/", len(delays))
            print("Ventes <= 5 min :", sum(d <= 300 for d in delays), "/", len(delays))


if __name__ == "__main__":
    asyncio.run(main())
