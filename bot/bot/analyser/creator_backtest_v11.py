import asyncio
import sqlite3

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import find_raydium_launch


PAGE_SIZE = 100
MAX_TRANSACTIONS = 2000
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


def get_swap_price_sol(tx, wallet, mint):
    """
    Prix SOL/token observé dans une transaction swap pour un wallet donné.
    Retourne None si la contrepartie SOL/WSOL n'est pas mesurable proprement.
    """
    pre_token = get_wallet_token_balance(tx, wallet, mint, "pre")
    post_token = get_wallet_token_balance(tx, wallet, mint, "post")
    token_delta = post_token - pre_token
    if abs(token_delta) < 1e-12:
        return None

    pre_assets = _owner_balances(tx, wallet, "pre")
    post_assets = _owner_balances(tx, wallet, "post")
    wsol_delta = post_assets.get(WSOL_MINT, 0.0) - pre_assets.get(WSOL_MINT, 0.0)

    keys = get_account_keys(tx)
    native_delta = None
    try:
        i = keys.index(wallet)
        meta = tx.get("meta", {}) or {}
        pre_lamports = (meta.get("preBalances") or [])[i]
        post_lamports = (meta.get("postBalances") or [])[i]
        fee = float(meta.get("fee") or 0)
        # Neutralise le fee payé par ce wallet afin d'estimer le flux économique SOL.
        native_delta = (post_lamports - pre_lamports + fee) / 1_000_000_000
    except (ValueError, IndexError, TypeError):
        pass

    sol_delta = wsol_delta
    if abs(sol_delta) < 1e-12 and native_delta is not None:
        sol_delta = native_delta

    if abs(sol_delta) < 1e-12:
        return None

    return abs(sol_delta) / abs(token_delta)


def find_first_observable_entry(creator_txs, mint, launch_time, launch_signature, creator):
    """
    V7: cherche uniquement un swap exploitable APRES la transaction de launch.
    La transaction de création/initialisation est explicitement exclue.
    Le creator lui-même n'est pas accepté comme acheteur externe.
    """
    observations = []

    for item in creator_txs:
        t = item.get("time")
        tx = item.get("tx")
        signature = item.get("signature")

        if tx is None or t is None or launch_time is None:
            continue

        # Exclusion absolue de la transaction d'initialisation.
        if signature == launch_signature:
            continue

        # Un blockTime identique au launch n'est pas assez précis pour prouver
        # que le swap était exécutable après le lancement.
        if t <= launch_time:
            continue

        if mint not in str(tx) or not is_swap(tx):
            continue

        owners = {
            x.get("owner")
            for side in ("preTokenBalances", "postTokenBalances")
            for x in ((tx.get("meta", {}) or {}).get(side, []) or [])
            if x.get("mint") == mint and x.get("owner")
        }

        for owner in owners:
            if owner == creator:
                continue

            pre = get_wallet_token_balance(tx, owner, mint, "pre")
            post = get_wallet_token_balance(tx, owner, mint, "post")

            # On veut une vraie entrée acheteuse: le wallet doit gagner le token.
            if post <= pre:
                continue

            price = get_swap_price_sol(tx, owner, mint)
            if price is not None and price > 0:
                observations.append(
                    (t, price, signature, owner)
                )

    observations.sort(key=lambda x: x[0])
    return observations[0] if observations else None


async def get_address_transactions(rpc, rpc_url, address, start_time=None, end_time=None):
    """
    V10 pool-history fetcher.
    Pages backwards through the pool address history until it has crossed
    start_time, instead of blindly truncating an active pool at 500 signatures.
    """
    collected = []
    before = None
    pages = 0
    max_pool_signatures = 5000

    while len(collected) < max_pool_signatures:
        options = {"limit": PAGE_SIZE}
        if before:
            options["before"] = before

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [address, options],
        }

        async with rpc.session.post(rpc_url, json=payload) as response:
            data = await response.json()

        if "error" in data:
            print("Erreur RPC pool :", data["error"])
            break

        page = data.get("result", []) or []
        if not page:
            break

        pages += 1
        oldest_time = None

        for sig_item in page:
            t = sig_item.get("blockTime")
            if t is not None:
                oldest_time = t if oldest_time is None else min(oldest_time, t)

            if start_time is not None and t is not None and t < start_time:
                continue
            if end_time is not None and t is not None and t > end_time:
                continue

            collected.append(sig_item)

        # Once this page has reached/passed launch time, older pages are irrelevant.
        if start_time is not None and oldest_time is not None and oldest_time < start_time:
            break

        if len(page) < PAGE_SIZE:
            break

        before = page[-1].get("signature")
        if not before:
            break

        await asyncio.sleep(0.35)

    # Deduplicate signatures and fetch only transactions inside our time window.
    unique = {}
    for item in collected:
        sig = item.get("signature")
        if sig:
            unique[sig] = item

    sig_items = list(unique.values())
    sig_items.sort(key=lambda x: x.get("blockTime") or 0)

    items = []
    for i, sig_item in enumerate(sig_items, start=1):
        sig = sig_item.get("signature")
        if not sig:
            continue

        tx = await rpc.get_transaction(sig)
        if tx:
            items.append({
                "signature": sig,
                "time": sig_item.get("blockTime"),
                "tx": tx,
            })

        if i % 25 == 0:
            print(
                f"  [Pool {i}/{len(sig_items)} | pages={pages}]",
                end="\r",
            )
        await asyncio.sleep(RPC_DELAY)

    print(" " * 80, end="\r")
    items.sort(key=lambda x: x["time"] or 0)
    return items


def find_first_market_buy(pool_txs, mint, launch_time, launch_signature, creator):
    """
    Find the first observable external BUY after launch among transactions
    mentioning the Raydium pool_state.
    """
    observations = []

    for item in pool_txs:
        t = item.get("time")
        tx = item.get("tx")
        signature = item.get("signature")

        if tx is None or t is None or launch_time is None:
            continue
        if signature == launch_signature:
            continue
        if t <= launch_time:
            continue
        if mint not in str(tx):
            continue
        if not is_swap(tx):
            continue

        meta = tx.get("meta", {}) or {}
        owners = {
            x.get("owner")
            for side in ("preTokenBalances", "postTokenBalances")
            for x in (meta.get(side, []) or [])
            if x.get("mint") == mint and x.get("owner")
        }

        for owner in owners:
            if owner == creator:
                continue

            pre = get_wallet_token_balance(tx, owner, mint, "pre")
            post = get_wallet_token_balance(tx, owner, mint, "post")

            # External buyer must gain the launched token.
            if post <= pre:
                continue

            price = get_swap_price_sol(tx, owner, mint)
            if price is None or price <= 0:
                continue

            observations.append({
                "time": t,
                "price": price,
                "signature": signature,
                "buyer": owner,
                "tokens_bought": post - pre,
            })

    observations.sort(key=lambda x: x["time"])
    return observations[0] if observations else None


def build_market_price_series(pool_txs, mint, launch_time, launch_signature, creator):
    """
    Reconstruct observable SOL/token prices from external swaps after launch.
    One representative price per transaction is kept (median if several owners
    yield a valid price in the same transaction).
    """
    points = []

    for item in pool_txs:
        t = item.get("time")
        tx = item.get("tx")
        signature = item.get("signature")

        if tx is None or t is None or launch_time is None:
            continue
        if signature == launch_signature or t <= launch_time:
            continue
        if mint not in str(tx) or not is_swap(tx):
            continue

        meta = tx.get("meta", {}) or {}
        owners = {
            x.get("owner")
            for side in ("preTokenBalances", "postTokenBalances")
            for x in (meta.get(side, []) or [])
            if x.get("mint") == mint and x.get("owner")
        }

        prices = []
        directions = []

        for owner in owners:
            if not owner or owner == creator:
                continue

            pre = get_wallet_token_balance(tx, owner, mint, "pre")
            post = get_wallet_token_balance(tx, owner, mint, "post")
            delta = post - pre
            if abs(delta) < 1e-12:
                continue

            price = get_swap_price_sol(tx, owner, mint)
            if price is None or price <= 0:
                continue

            prices.append(price)
            directions.append("BUY" if delta > 0 else "SELL")

        if not prices:
            continue

        ordered = sorted(prices)
        price = ordered[len(ordered) // 2]
        direction = directions[0] if len(set(directions)) == 1 else "SWAP"

        points.append({
            "time": t,
            "price": price,
            "signature": signature,
            "direction": direction,
        })

    points.sort(key=lambda x: x["time"])
    return points


def simulate_tp_sl(series, entry_time, entry_price, sale_time, tp_pct, sl_pct):
    """
    Paper simulation using only observed on-chain swap prices.
    Exit at the first observed point reaching TP or SL; otherwise exit at the
    last observable market point at/before relay sale.
    """
    if entry_time is None or entry_price is None or entry_price <= 0:
        return None

    usable = [
        p for p in series
        if p["time"] >= entry_time
        and (sale_time is None or p["time"] <= sale_time)
    ]
    if not usable:
        return None

    tp_price = entry_price * (1.0 + tp_pct / 100.0)
    sl_price = entry_price * (1.0 - sl_pct / 100.0)

    peak = max(p["price"] for p in usable)
    trough = min(p["price"] for p in usable)

    exit_point = None
    reason = "FIN_FENETRE"

    for p in usable:
        if p["price"] >= tp_price:
            exit_point = p
            reason = "TP"
            break
        if p["price"] <= sl_price:
            exit_point = p
            reason = "SL"
            break

    if exit_point is None:
        exit_point = usable[-1]

    pnl = (exit_point["price"] / entry_price - 1.0) * 100.0
    peak_pct = (peak / entry_price - 1.0) * 100.0
    trough_pct = (trough / entry_price - 1.0) * 100.0

    return {
        "pnl_pct": pnl,
        "reason": reason,
        "exit_time": exit_point["time"],
        "exit_price": exit_point["price"],
        "peak_pct": peak_pct,
        "trough_pct": trough_pct,
        "points": len(usable),
    }


def diagnose_pool_transactions(pool_txs, mint, launch_time, launch_signature, creator):
    stats = {
        "total": 0, "after_launch": 0, "mint_visible": 0,
        "swap_detected": 0, "has_external_owner": 0,
        "has_token_delta": 0, "price_ok": 0,
        "fail_not_swap": 0, "fail_no_mint": 0,
        "fail_no_owner": 0, "fail_no_delta": 0,
        "fail_no_sol_price": 0,
    }

    for item in pool_txs:
        stats["total"] += 1
        t, tx, sig = item.get("time"), item.get("tx"), item.get("signature")

        if tx is None or t is None or launch_time is None:
            continue
        if sig == launch_signature or t <= launch_time:
            continue
        stats["after_launch"] += 1

        if mint not in str(tx):
            stats["fail_no_mint"] += 1
            continue
        stats["mint_visible"] += 1

        if not is_swap(tx):
            stats["fail_not_swap"] += 1
            continue
        stats["swap_detected"] += 1

        meta = tx.get("meta", {}) or {}
        owners = {
            x.get("owner")
            for side in ("preTokenBalances", "postTokenBalances")
            for x in (meta.get(side, []) or [])
            if x.get("mint") == mint and x.get("owner") and x.get("owner") != creator
        }

        if not owners:
            stats["fail_no_owner"] += 1
            continue
        stats["has_external_owner"] += 1

        found_delta = False
        found_price = False
        for owner in owners:
            pre = get_wallet_token_balance(tx, owner, mint, "pre")
            post = get_wallet_token_balance(tx, owner, mint, "post")
            if abs(post - pre) < 1e-12:
                continue
            found_delta = True
            price = get_swap_price_sol(tx, owner, mint)
            if price is not None and price > 0:
                found_price = True
                break

        if not found_delta:
            stats["fail_no_delta"] += 1
            continue
        stats["has_token_delta"] += 1

        if not found_price:
            stats["fail_no_sol_price"] += 1
            continue
        stats["price_ok"] += 1

    return stats


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
                "pool_state": launch.get("pool_state"),
                "time": item["time"],
                "signature": item["signature"],
            })

        launches.sort(key=lambda x: x["time"] or 0)
        print("\nLaunches trouvés :", len(launches))

        # Cache: several launches reuse the same relay wallet.
        wallet_cache = {}
        pool_cache = {}
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
                "pool_state": launch.get("pool_state"),
                "relay": None,
                "transfer_delay": None,
                "sale_delay": None,
                "sold_pct": None,
                "sol_received": None,
                "sale_price_sol": None,
                "launch_time": launch["time"],
                "transfer_time": candidate["transfer_time"] if candidate else None,
                "sale_time": None,
                "sold_tokens": None,
                "received_tokens": None,
                "entry_time": None,
                "entry_price_sol": None,
                "entry_buyer": None,
                "entry_signature": None,
                "paper_return_pct": None,
                "market_series": [],
                "status": "",
            }

            if not candidate:
                row["status"] = "Aucun relay"
                results.append(row)
                print("  Aucun wallet relais détecté.")
                continue

            wallet = candidate["wallet"]
            row["relay"] = wallet

            pool_state = launch.get("pool_state")

            if pool_state:
                if pool_state not in pool_cache:
                    # We only need market activity from launch until the relay sale window.
                    # Use a generous +1 hour fallback here; the actual sale is resolved below.
                    pool_cache[pool_state] = await get_address_transactions(
                        rpc,
                        settings.rpc_url,
                        pool_state,
                        start_time=launch["time"],
                        end_time=(launch["time"] + 21600) if launch["time"] is not None else None,
                    )

                entry = find_first_market_buy(
                    pool_cache[pool_state],
                    mint,
                    launch["time"],
                    launch["signature"],
                    creator,
                )
                if entry:
                    row["entry_time"] = entry["time"]
                    row["entry_price_sol"] = entry["price"]
                    row["entry_buyer"] = entry["buyer"]
                    row["entry_signature"] = entry["signature"]

                row["market_series"] = build_market_price_series(
                    pool_cache[pool_state],
                    mint,
                    launch["time"],
                    launch["signature"],
                    creator,
                )

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
            row["sale_time"] = sale["time"]
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
                row["received_tokens"] = received_balance

            sold_tokens, received_assets, native_sol = analyze_sale_swap(
                sale["tx"], wallet, mint
            )

            row["sold_tokens"] = sold_tokens
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

            if (
                row["entry_price_sol"] is not None
                and row["entry_price_sol"] > 0
                and row["sale_price_sol"] is not None
            ):
                row["paper_return_pct"] = (
                    row["sale_price_sol"] / row["entry_price_sol"] - 1.0
                ) * 100.0

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

    print("\n" + "=" * 110)
    print("DONNEES PRETES POUR LE BACKTEST")
    print("=" * 110)
    complete = [
        r for r in results
        if r.get("launch_time") is not None
        and r.get("transfer_time") is not None
        and r.get("sale_time") is not None
        and r.get("sold_tokens") is not None
        and r.get("sale_price_sol") is not None
    ]
    print("Launches avec chaîne complète launch -> relay -> vente -> prix :", len(complete), "/", len(results))
    for r in complete:
        print(
            f"#{r['n']:02d} {r['mint'][:8]}.. | "
            f"launch={r['launch_time']} | "
            f"relay={r['relay'][:8]}.. | "
            f"vente={r['sale_time']} | "
            f"tokens={r['sold_tokens']:.6f} | "
            f"prix={r['sale_price_sol']:.12f} SOL/token"
        )


    print("\n" + "=" * 110)
    print("BACKTEST V8 - PREMIER ACHAT DU MARCHE VIA POOL RAYDIUM -> VENTE RELAY")
    print("=" * 110)
    pools = [r for r in results if r.get("pool_state")]
    entries = [r for r in results if r.get("entry_price_sol") is not None]
    print("Launches avec pool_state :", len(pools), "/", len(results))
    print("Premiers achats marché détectés :", len(entries), "/", len(results))

    backtests = [
        r for r in results
        if r.get("entry_price_sol") is not None
        and r.get("sale_price_sol") is not None
        and r.get("paper_return_pct") is not None
    ]

    print("Trades simulables avec les données actuellement récupérées :", len(backtests), "/", len(results))
    for r in backtests:
        delay_entry = (
            r["entry_time"] - r["launch_time"]
            if r.get("entry_time") is not None and r.get("launch_time") is not None
            else None
        )
        print(
            f"#{r['n']:02d} {r['mint'][:8]}.. | "
            f"entrée=T+{delay_entry}s | "
            f"prix entrée={r['entry_price_sol']:.12f} | "
            f"prix sortie={r['sale_price_sol']:.12f} | "
            f"P&L={r['paper_return_pct']:+.2f}%"
        )

    if backtests:
        returns = [r["paper_return_pct"] for r in backtests]
        print("-" * 110)
        print("Trades :", len(returns))
        print("Gagnants :", sum(x > 0 for x in returns))
        print("Perdants :", sum(x < 0 for x in returns))
        print("P&L moyen brut :", f"{sum(returns) / len(returns):+.2f}%")
    else:
        print(
            "Aucun achat externe exploitable trouvé via les pool_state récupérés. "
            "Ne pas calculer de P&L: il faudra inspecter la structure exacte des swaps "
            "LaunchLab/pool pour améliorer le parseur."
        )


    print("\n" + "=" * 110)
    print("V10 - HISTORIQUE POOL ELARGI + EVOLUTION DU PRIX + TP/SL")
    print("=" * 110)

    analyzable = [
        r for r in results
        if r.get("entry_time") is not None
        and r.get("entry_price_sol") is not None
        and r.get("sale_time") is not None
        and r.get("market_series")
    ]

    print("Launches avec série de prix exploitable :", len(analyzable), "/", len(results))

    point_counts = [len(r.get("market_series") or []) for r in analyzable]
    if point_counts:
        print("Points de prix total :", sum(point_counts))
        print("Points moyens par launch :", round(sum(point_counts) / len(point_counts), 1))
        print("Launches avec >= 5 points :", sum(n >= 5 for n in point_counts), "/", len(point_counts))
        print("Launches avec >= 10 points :", sum(n >= 10 for n in point_counts), "/", len(point_counts))

    for r in analyzable:
        sim = simulate_tp_sl(
            r["market_series"],
            r["entry_time"],
            r["entry_price_sol"],
            r["sale_time"],
            tp_pct=10_000.0,   # unreachable diagnostic TP in normal cases
            sl_pct=99.0,
        )
        if sim:
            print(
                f"#{r['n']:02d} {r['mint'][:8]}.. | "
                f"points={sim['points']} | "
                f"pic={sim['peak_pct']:+.2f}% | "
                f"creux={sim['trough_pct']:+.2f}%"
            )

    strategies = [
        (10, 10),
        (20, 10),
        (30, 10),
        (50, 10),
        (100, 10),
        (20, 20),
        (50, 20),
        (100, 20),
        (50, 30),
        (100, 30),
    ]

    print("\n" + "-" * 110)
    print("MATRICE DE STRATEGIES BRUTES - SANS FRAIS NI SLIPPAGE")
    print("-" * 110)
    print(
        f"{'TP':>7} {'SL':>7} {'Trades':>8} {'Win':>6} "
        f"{'Loss':>6} {'TP hit':>7} {'SL hit':>7} {'P&L moy':>11}"
    )

    for tp_pct, sl_pct in strategies:
        sims = []
        for r in analyzable:
            sim = simulate_tp_sl(
                r["market_series"],
                r["entry_time"],
                r["entry_price_sol"],
                r["sale_time"],
                tp_pct,
                sl_pct,
            )
            if sim:
                sims.append(sim)

        if not sims:
            continue

        pnls = [s["pnl_pct"] for s in sims]
        wins = sum(x > 0 for x in pnls)
        losses = sum(x < 0 for x in pnls)
        tp_hits = sum(s["reason"] == "TP" for s in sims)
        sl_hits = sum(s["reason"] == "SL" for s in sims)
        avg = sum(pnls) / len(pnls)

        print(
            f"{tp_pct:>6}% {sl_pct:>6}% {len(sims):>8} {wins:>6} "
            f"{losses:>6} {tp_hits:>7} {sl_hits:>7} {avg:>+10.2f}%"
        )

    robust = [
        r for r in analyzable
        if len(r.get("market_series") or []) >= 5
    ]

    print("\n" + "-" * 110)
    print("CONTROLE QUALITE DES DONNEES")
    print("-" * 110)
    print("Launches retenus avec au moins 5 points :", len(robust), "/", len(analyzable))
    if len(robust) < len(analyzable):
        print(
            "Les résultats globaux restent exploratoires pour les launches ayant "
            "moins de 5 prix observés."
        )

    print("\nIMPORTANT : ces résultats utilisent les prix des swaps observés.")
    print("Ils n'incluent PAS encore frais, slippage, latence d'exécution ni taille de position.")


    print("\n" + "=" * 110)
    print("V11 - DIAGNOSTIC DU PARSEUR DE SWAPS")
    print("=" * 110)

    keys = [
        "total", "after_launch", "mint_visible", "swap_detected",
        "has_external_owner", "has_token_delta", "price_ok",
        "fail_not_swap", "fail_no_mint", "fail_no_owner",
        "fail_no_delta", "fail_no_sol_price",
    ]
    aggregate = {key: 0 for key in keys}
    diagnosed = 0

    for r in results:
        pool_state = r.get("pool_state")
        if not pool_state or pool_state not in pool_cache:
            continue

        launch = launches[r["n"] - 1]
        stats = diagnose_pool_transactions(
            pool_cache[pool_state], r["mint"], r["launch_time"],
            launch["signature"], creator,
        )
        diagnosed += 1
        for key in keys:
            aggregate[key] += stats[key]

        print(
            f"#{r['n']:02d} {r['mint'][:8]}.. | "
            f"tx={stats['after_launch']} | mint={stats['mint_visible']} | "
            f"swap={stats['swap_detected']} | delta={stats['has_token_delta']} | "
            f"prix={stats['price_ok']} | sans_prix_SOL={stats['fail_no_sol_price']}"
        )

    print("\n" + "-" * 110)
    print("TOTAL DIAGNOSTIC")
    print("-" * 110)
    print("Pools diagnostiques :", diagnosed)
    print("Transactions recuperees :", aggregate["total"])
    print("Transactions apres launch :", aggregate["after_launch"])
    print("Transactions contenant le mint :", aggregate["mint_visible"])
    print("Transactions reconnues comme swap :", aggregate["swap_detected"])
    print("Transactions avec owner externe :", aggregate["has_external_owner"])
    print("Transactions avec variation du token :", aggregate["has_token_delta"])
    print("Transactions converties en prix SOL/token :", aggregate["price_ok"])
    print("\nREJETS DU PARSEUR")
    print("Mint non visible :", aggregate["fail_no_mint"])
    print("Non reconnu comme swap :", aggregate["fail_not_swap"])
    print("Owner externe introuvable :", aggregate["fail_no_owner"])
    print("Variation token introuvable :", aggregate["fail_no_delta"])
    print("Prix SOL/WSOL impossible a calculer :", aggregate["fail_no_sol_price"])


if __name__ == "__main__":
    asyncio.run(main())
