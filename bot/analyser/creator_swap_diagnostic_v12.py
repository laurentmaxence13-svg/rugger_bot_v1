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



MAX_EXAMPLES = 20

def ui_amount(item):
    t = item.get("uiTokenAmount") or {}
    if t.get("uiAmount") is not None:
        return float(t["uiAmount"])
    if t.get("amount") is None:
        return 0.0
    return int(t["amount"]) / (10 ** int(t.get("decimals", 0)))

def account_deltas(tx, mint):
    meta = tx.get("meta", {}) or {}
    def rows(key):
        return {
            x.get("accountIndex"): {
                "owner": x.get("owner"), "amount": ui_amount(x)
            }
            for x in meta.get(key, []) or [] if x.get("mint") == mint
        }
    pre, post = rows("preTokenBalances"), rows("postTokenBalances")
    out=[]
    for idx in set(pre) | set(post):
        a,b=pre.get(idx,{}),post.get(idx,{})
        x,y=a.get("amount",0.0),b.get("amount",0.0)
        out.append((idx,a.get("owner"),b.get("owner"),x,y,y-x))
    return out

def parsed_transfers(tx):
    out=[]
    for ix in get_all_instructions(tx):
        p=ix.get("parsed")
        if not isinstance(p,dict) or p.get("type") not in {"transfer","transferChecked"}:
            continue
        info=p.get("info") or {}
        out.append((p.get("type"),info.get("mint"),info.get("authority")))
    return out

async def main():
    settings=get_settings()
    creator=get_latest_creator(settings)
    if not creator:
        print("Aucun creator trouve.")
        return
    print("="*105)
    print("V12 - DIAGNOSTIC DETAILLE DES 192 SWAPS SANS VARIATION TOKEN")
    print("="*105)
    print("Creator :",creator)

    totals={"swaps":0,"no_delta":0,"account_delta":0,"owner_change":0,"transfers":0,"zero":0}
    examples=[]

    async with SolanaRPC(settings.rpc_url) as rpc:
        sigs=await get_signatures(rpc,settings.rpc_url,creator)
        creator_txs=[]
        for i,item in enumerate(sigs,1):
            print(f"[Creator {i}/{len(sigs)}]",end="\r")
            sig=item.get("signature")
            if not sig: continue
            tx=await rpc.get_transaction(sig)
            if tx:
                creator_txs.append({"signature":sig,"time":item.get("blockTime"),"tx":tx})
            await asyncio.sleep(RPC_DELAY)

        launches=[]
        for item in creator_txs:
            launch=find_raydium_launch(item["tx"])
            if launch and launch.get("creator")==creator and launch.get("mint"):
                launches.append({"mint":launch["mint"],"pool_state":launch.get("pool_state"),
                                 "time":item["time"],"signature":item["signature"]})
        launches.sort(key=lambda x:x["time"] or 0)
        print("\nLaunches trouves :",len(launches))

        for n,launch in enumerate(launches,1):
            if not launch["pool_state"]: continue
            mint=launch["mint"]
            print(f"\n[{n}/{len(launches)}] {mint[:12]}..")
            txs=await get_address_transactions(
                rpc,settings.rpc_url,launch["pool_state"],
                start_time=launch["time"],
                end_time=launch["time"]+21600 if launch["time"] else None)
            loc_swaps=loc_no=loc_acc=0
            for item in txs:
                t,tx,sig=item.get("time"),item.get("tx"),item.get("signature")
                if tx is None or t is None or launch["time"] is None: continue
                if sig==launch["signature"] or t<=launch["time"]: continue
                if mint not in str(tx) or not is_swap(tx): continue
                totals["swaps"]+=1; loc_swaps+=1
                meta=tx.get("meta",{}) or {}
                owners={x.get("owner") for side in ("preTokenBalances","postTokenBalances")
                        for x in meta.get(side,[]) or []
                        if x.get("mint")==mint and x.get("owner") and x.get("owner")!=creator}
                found=False
                for owner in owners:
                    if abs(get_wallet_token_balance(tx,owner,mint,"post")-
                           get_wallet_token_balance(tx,owner,mint,"pre"))>=1e-12:
                        found=True; break
                if found: continue

                totals["no_delta"]+=1; loc_no+=1
                rows=account_deltas(tx,mint)
                nz=[r for r in rows if abs(r[5])>=1e-12]
                changes=[r for r in rows if r[1]!=r[2]]
                transfers=parsed_transfers(tx)
                if nz: totals["account_delta"]+=1; loc_acc+=1
                else: totals["zero"]+=1
                if changes: totals["owner_change"]+=1
                if transfers: totals["transfers"]+=1
                if len(examples)<MAX_EXAMPLES:
                    examples.append((n,mint,sig,t-launch["time"],rows,transfers))
            print(f"  swaps={loc_swaps} | sans_delta_V11={loc_no} | delta_par_compte={loc_acc}")

    print("\n"+"="*105)
    print("RESULTAT V12")
    print("="*105)
    print("Swaps candidats :",totals["swaps"])
    print("Rejets V11 sans variation owner :",totals["no_delta"])
    print("Variation visible par accountIndex :",totals["account_delta"])
    print("Owner change entre pre/post :",totals["owner_change"])
    print("Au moins un transfer SPL parse :",totals["transfers"])
    print("Tous les soldes du mint identiques :",totals["zero"])

    print("\n"+"="*105)
    print("20 EXEMPLES MAXIMUM")
    print("="*105)
    for k,(n,mint,sig,delay,rows,transfers) in enumerate(examples,1):
        print(f"\n[{k}] launch #{n:02d} T+{delay}s {mint[:12]}..")
        print("signature :",sig)
        for idx,opre,opost,pre,post,delta in rows:
            print(f" idx={idx} owner_pre={str(opre)[:12]} owner_post={str(opost)[:12]} "
                  f"pre={pre:.9f} post={post:.9f} delta={delta:+.9f}")
        print("transfers SPL parses :",len(transfers))

    print("\n"+"="*105)
    print("CONCLUSION AUTOMATIQUE")
    print("="*105)
    if totals["account_delta"]:
        print("Des mouvements existent par compte mais s'annulent par owner : corriger l'agregation owner.")
    elif totals["transfers"]:
        print("Pas de delta net, mais des transferts internes existent : reconstruire les swaps depuis les flux.")
    else:
        print("Pas de mouvement net du mint : inspecter les programmes/instructions avant de compter ces tx comme trades.")

if __name__=="__main__":
    asyncio.run(main())
