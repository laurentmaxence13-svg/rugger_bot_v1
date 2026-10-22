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




LAUNCHLAB_PROGRAM = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"

def extract_launchlab_market_accounts_v21(tx, mint, creator, pool_state):
    """
    V21: récupère directement les comptes utilisés par l'instruction LaunchLab
    de création. On ne suppose pas arbitrairement lequel est le vault : on
    conserve les comptes writable de l'instruction, puis on les teste comme
    sources d'historique marché.
    """
    message = (tx.get("transaction", {}) or {}).get("message", {}) or {}
    raw_keys = message.get("accountKeys", []) or []
    keys = get_account_keys(tx)

    writable = {}
    signers = {}
    for i, raw in enumerate(raw_keys):
        if isinstance(raw, dict):
            writable[i] = bool(raw.get("writable", raw.get("isWritable", False)))
            signers[i] = bool(raw.get("signer", raw.get("isSigner", False)))
        else:
            writable[i] = True
            signers[i] = False

    program_blacklist = {
        LAUNCHLAB_PROGRAM,
        "11111111111111111111111111111111",
        "ComputeBudget111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "So11111111111111111111111111111111111111112",
        mint, creator, pool_state,
    }

    candidates = []
    instructions = message.get("instructions", []) or []

    for ix in instructions:
        pid = ix.get("programId")
        if pid is None and ix.get("programIdIndex") is not None:
            j = ix.get("programIdIndex")
            if isinstance(j, int) and 0 <= j < len(keys):
                pid = keys[j]
        if pid != LAUNCHLAB_PROGRAM:
            continue

        for account in ix.get("accounts", []) or []:
            if isinstance(account, int):
                idx = account
                pubkey = keys[idx] if 0 <= idx < len(keys) else None
            else:
                pubkey = account.get("pubkey") if isinstance(account, dict) else account
                try:
                    idx = keys.index(pubkey)
                except (ValueError, TypeError):
                    idx = None

            if not pubkey or pubkey in program_blacklist:
                continue
            if idx is not None and signers.get(idx, False):
                continue
            if idx is not None and not writable.get(idx, True):
                continue
            if pubkey not in candidates:
                candidates.append(pubkey)

    # Evite d'exploser le nombre de requêtes si une variante d'instruction
    # contient beaucoup de comptes. Les premiers writable sont les plus proches
    # de l'état/vaults de l'instruction.
    return candidates[:6]

async def get_multi_address_transactions_v21(
    rpc, rpc_url, addresses, start_time=None, end_time=None,
    max_signatures_per_address=5000,
):
    """
    V21: récupère les signatures de PLUSIEURS adresses avant de télécharger les tx.

    Pourquoi : pool_state seul ne voit pas toujours toute l'activité exploitable.
    Le mint SPL est aussi un compte de nombreuses instructions transferChecked.
    On fusionne donc pool_state + mint, on déduplique les signatures, puis on ne
    télécharge chaque transaction qu'une seule fois.
    """
    unique_sigs = {}
    source_counts = {}

    for address in dict.fromkeys(a for a in addresses if a):
        before = None
        collected_for_address = 0
        pages = 0

        while collected_for_address < max_signatures_per_address:
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
                print("Erreur RPC V21 adresse :", data["error"])
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

                sig = sig_item.get("signature")
                if not sig:
                    continue

                collected_for_address += 1
                rec = unique_sigs.setdefault(sig, {
                    "signature": sig,
                    "blockTime": t,
                    "sources": set(),
                })
                rec["sources"].add(address)
                if rec.get("blockTime") is None and t is not None:
                    rec["blockTime"] = t

            if start_time is not None and oldest_time is not None and oldest_time < start_time:
                break
            if len(page) < PAGE_SIZE:
                break

            before = page[-1].get("signature")
            if not before:
                break
            await asyncio.sleep(RPC_DELAY)

        source_counts[address] = collected_for_address

    sig_items = list(unique_sigs.values())
    sig_items.sort(key=lambda x: x.get("blockTime") or 0)

    items = []
    for i, sig_item in enumerate(sig_items, start=1):
        sig = sig_item["signature"]
        tx = await rpc.get_transaction(sig)
        if tx:
            items.append({
                "signature": sig,
                "time": sig_item.get("blockTime"),
                "tx": tx,
                "v20_sources": len(sig_item.get("sources") or []),
            })

        if i % 25 == 0:
            print(f"  [V21 tx {i}/{len(sig_items)}]", end="\r")
        await asyncio.sleep(RPC_DELAY)

    print(" " * 90, end="\r")
    items.sort(key=lambda x: x.get("time") or 0)
    return items, source_counts, len(sig_items)

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


def _owner_market_observation(tx, mint, creator):
    """Ancienne methode V10, conservee comme reference/fallback."""
    meta = tx.get("meta", {}) or {}
    owners = {
        x.get("owner")
        for side in ("preTokenBalances", "postTokenBalances")
        for x in (meta.get(side, []) or [])
        if x.get("mint") == mint and x.get("owner")
    }

    prices = []
    directions = []
    buyers = []

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
        if delta > 0:
            buyers.append(owner)

    if not prices:
        return None

    ordered = sorted(prices)
    return {
        "price": ordered[len(ordered) // 2],
        "direction": directions[0] if len(set(directions)) == 1 else "SWAP",
        "buyer": buyers[0] if buyers else None,
        "source": "OWNER",
    }


def _v16_market_observation(tx, mint):
    """
    V18: prix structurel V16 valide par V17.
    Garde-fou: une transaction n'est retenue que si les candidats V16
    decomposes sont mutuellement coherents a 2%.
    """
    candidates = [
        c for c in v16_structured_candidates(tx, mint)
        if c.get("decomposed") and c.get("price") and c["price"] > 0
    ]
    if not candidates:
        return None

    prices = sorted(c["price"] for c in candidates)
    median = prices[len(prices) // 2]

    if len(prices) > 1:
        spread = (max(prices) - min(prices)) / median if median else 999
        if spread > 0.02:
            return None

    return {
        "price": median,
        "direction": "SWAP",
        "buyer": None,
        "source": "V16",
    }


def get_v18_market_observation(tx, mint, creator):
    """
    Fusion conservative:
      1. si OWNER et V16 existent et concordent a <=5%, OWNER reste reference;
      2. si OWNER seul existe, on le garde;
      3. si V16 seul existe, on utilise V16 valide structurellement;
      4. s'ils divergent >5%, transaction rejetee.
    """
    owner = _owner_market_observation(tx, mint, creator)
    v16 = _v16_market_observation(tx, mint)

    if owner and v16:
        err = abs(owner["price"] - v16["price"]) / owner["price"]
        if err > 0.05:
            return None
        owner["source"] = "OWNER+V16"
        return owner

    return owner or v16


def build_market_price_series(pool_txs, mint, launch_time, launch_signature, creator):
    """
    V24 - courbe structurelle avec garde-fou economique.

    V23 a montre que retirer is_swap recupere de vrais points, mais OWNER seul peut
    aussi interpreter un transfert/distribution comme un prix et produire des valeurs
    quasi nulles. V24 fait donc deux passes :
      1) construit tous les points OWNER/V16 ;
      2) utilise les points les plus fiables (is_swap ou V16) comme ancrages et rejette
         les observations OWNER-only hors d'une enveloppe x5 / /5 de ces ancrages.

    Le seuil x5 est volontairement large : il ne cherche pas a lisser le marche, il
    bloque uniquement les erreurs d'unite / transferts techniques de plusieurs ordres
    de grandeur. Les points V16 restent soumis a leurs controles structurels internes.
    """
    raw = []

    for item in pool_txs:
        t = item.get("time")
        tx = item.get("tx")
        signature = item.get("signature")

        if tx is None or t is None or launch_time is None:
            continue
        if signature == launch_signature or t <= launch_time:
            continue
        if mint not in str(tx):
            continue

        obs = get_v18_market_observation(tx, mint, creator)
        if not obs or not obs.get("price") or obs["price"] <= 0:
            continue

        raw.append({
            "time": t,
            "price": float(obs["price"]),
            "signature": signature,
            "direction": obs["direction"],
            "source": obs["source"],
            "swap_flag": bool(is_swap(tx)),
        })

    raw.sort(key=lambda x: x["time"])
    if not raw:
        return []

    # Ancrages : transaction reconnue swap OU prix confirme par V16.
    anchors = [
        p for p in raw
        if p["swap_flag"] or "V16" in p.get("source", "")
    ]
    anchor_prices = sorted(p["price"] for p in anchors if p["price"] > 0)

    # Sans aucun ancrage, on refuse d'inventer une echelle de prix a partir d'un
    # simple OWNER-delta non-swap.
    if not anchor_prices:
        return []

    median_anchor = anchor_prices[len(anchor_prices) // 2]
    accepted = []

    for p in raw:
        price = p["price"]

        # Cherche d'abord l'ancrage temporel le plus proche. Cela permet de suivre
        # une vraie variation de marche sans comparer uniquement a une mediane globale.
        nearest = min(anchors, key=lambda a: abs(a["time"] - p["time"])) if anchors else None
        ref = nearest["price"] if nearest and nearest["price"] > 0 else median_anchor
        ratio = price / ref if ref > 0 else 0

        # Tous les points, y compris les ancrages, doivent rester dans une enveloppe
        # tres large autour de la mediane des ancrages. Ceci elimine notamment les
        # prix quasi nuls et les erreurs x1000/x100000 vues en V23.
        global_ratio = price / median_anchor if median_anchor > 0 else 0
        gross_outlier = global_ratio < 0.20 or global_ratio > 5.0

        # OWNER-only non-swap : garde-fou supplementaire par rapport a l'ancrage
        # temporel le plus proche.
        owner_only_nonswap = (p.get("source") == "OWNER" and not p["swap_flag"])
        local_outlier = owner_only_nonswap and (ratio < 0.20 or ratio > 5.0)

        if gross_outlier or local_outlier:
            continue

        q = dict(p)
        q.pop("swap_flag", None)
        accepted.append(q)

    return accepted

def find_first_market_buy_v18(pool_txs, mint, launch_time, launch_signature, creator):
    """
    Premiere observation de marche structurellement décodable apres launch.
    OWNER BUY est prefere. Si le premier point provient uniquement de V16,
    il est utilisable comme prix de marche mais marque V16.
    """
    series = build_market_price_series(
        pool_txs, mint, launch_time, launch_signature, creator
    )
    if not series:
        return None

    # Premier BUY explicite si disponible au meme instant que le premier point.
    first_time = series[0]["time"]
    same_time_buys = [
        p for p in series
        if p["time"] == first_time and p["direction"] == "BUY"
    ]
    p = same_time_buys[0] if same_time_buys else series[0]

    return {
        "time": p["time"],
        "price": p["price"],
        "signature": p["signature"],
        "buyer": None,
        "source": p.get("source", "OWNER"),
    }


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


def inspect_internal_flows(tx, target_mint):
    keys = get_account_keys(tx)
    owners = get_token_account_owners(tx, target_mint)
    target_accounts = set(owners.keys())
    flows = []

    for ix in get_all_instructions(tx):
        parsed = ix.get("parsed")
        if not isinstance(parsed, dict):
            continue
        if parsed.get("type") not in {"transfer", "transferChecked"}:
            continue

        info = parsed.get("info") or {}
        source = info.get("source")
        destination = info.get("destination")
        ix_mint = info.get("mint")

        token_amount = info.get("tokenAmount") or {}
        amount = token_amount.get("uiAmount")
        if amount is None and token_amount.get("amount") is not None:
            amount = int(token_amount["amount"]) / (10 ** int(token_amount.get("decimals", 0)))
        if amount is None:
            amount = info.get("amount")

        # transferChecked gives mint explicitly. For plain transfer, infer whether
        # source/destination is one of the target mint's token accounts.
        touches_target = (
            ix_mint == target_mint
            or source in target_accounts
            or destination in target_accounts
        )

        flows.append({
            "type": parsed.get("type"),
            "mint": ix_mint,
            "source": source,
            "destination": destination,
            "source_owner": owners.get(source),
            "destination_owner": owners.get(destination),
            "authority": info.get("authority"),
            "amount": amount,
            "touches_target": touches_target,
        })

    return flows

def program_ids_in_tx(tx):
    ids = set()
    for ix in get_all_instructions(tx):
        pid = ix.get("programId")
        if pid:
            ids.add(str(pid))
        program = ix.get("program")
        if program:
            ids.add(str(program))
    return sorted(ids)


def extract_internal_flow_price(tx, target_mint):
    """
    V14 experimental extractor.
    Uses parsed transferChecked flows only.
    A price is accepted only when:
      - target-mint flow is explicit,
      - WSOL flows are explicit,
      - there is a target-token authority,
      - WSOL counterpart can be associated with that authority,
      - amounts are positive.
    Returns diagnostic data even when no price can safely be produced.
    """
    flows = inspect_internal_flows(tx, target_mint)

    target = [
        f for f in flows
        if f["touches_target"]
        and f["mint"] == target_mint
        and f["amount"] is not None
        and float(f["amount"]) > 0
    ]
    wsol = [
        f for f in flows
        if f["mint"] == WSOL_MINT
        and f["amount"] is not None
        and float(f["amount"]) > 0
    ]

    result = {
        "target_flows": target,
        "wsol_flows": wsol,
        "price": None,
        "token_amount": None,
        "sol_amount": None,
        "method": None,
        "ambiguous": False,
    }

    if not target or not wsol:
        return result

    # Prefer a target flow with a real authority.
    target_with_auth = [f for f in target if f.get("authority")]
    if not target_with_auth:
        return result

    # Largest explicit target-mint transfer is normally the economic token leg.
    token_flow = max(target_with_auth, key=lambda f: float(f["amount"]))
    authority = token_flow.get("authority")
    token_amount = float(token_flow["amount"])

    # First try exact authority match on the WSOL leg.
    matched = [f for f in wsol if f.get("authority") == authority]

    # If no exact authority match, use WSOL transfers whose source/destination owner
    # matches the target authority. This remains conservative.
    if not matched:
        matched = [
            f for f in wsol
            if f.get("source_owner") == authority
            or f.get("destination_owner") == authority
        ]

    if not matched:
        return result

    # Multiple WSOL transfers can include wrapping/unwrapping or routing.
    # Use the largest matched economic leg, but flag ambiguity when several exist.
    sol_flow = max(matched, key=lambda f: float(f["amount"]))
    sol_amount = float(sol_flow["amount"])

    result["token_amount"] = token_amount
    result["sol_amount"] = sol_amount
    result["price"] = sol_amount / token_amount
    result["method"] = "internal_transfer_authority"
    result["ambiguous"] = len(matched) > 1
    return result


def grouped_parsed_transfers(tx, target_mint):
    """
    Preserve Solana execution structure:
    - outer_index: index of the parent top-level instruction
    - inner_order: execution order inside that parent
    This lets V15 test whether target-token and WSOL legs actually belong
    to the same instruction group instead of pairing transfers globally.
    """
    message = ((tx.get("transaction") or {}).get("message") or {})
    meta = tx.get("meta", {}) or {}
    owners = get_token_account_owners(tx, target_mint)
    target_accounts = set(owners.keys())
    groups = []

    # Top-level parsed instructions.
    for outer_index, ix in enumerate(message.get("instructions", []) or []):
        parsed = ix.get("parsed") if isinstance(ix, dict) else None
        if not isinstance(parsed, dict) or parsed.get("type") not in {"transfer", "transferChecked"}:
            continue
        info = parsed.get("info") or {}
        groups.append(_v15_transfer_row(
            parsed.get("type"), info, target_mint, target_accounts, owners,
            outer_index, -1, "outer"
        ))

    # Inner instructions, retaining their parent outer instruction index.
    for group in meta.get("innerInstructions", []) or []:
        outer_index = group.get("index")
        for inner_order, ix in enumerate(group.get("instructions", []) or []):
            parsed = ix.get("parsed") if isinstance(ix, dict) else None
            if not isinstance(parsed, dict) or parsed.get("type") not in {"transfer", "transferChecked"}:
                continue
            info = parsed.get("info") or {}
            groups.append(_v15_transfer_row(
                parsed.get("type"), info, target_mint, target_accounts, owners,
                outer_index, inner_order, "inner"
            ))
    return groups

def _v15_transfer_row(kind, info, target_mint, target_accounts, owners,
                      outer_index, inner_order, level):
    token_amount = info.get("tokenAmount") or {}
    amount = token_amount.get("uiAmount")
    if amount is None and token_amount.get("amount") is not None:
        amount = int(token_amount["amount"]) / (10 ** int(token_amount.get("decimals", 0)))
    if amount is None:
        amount = info.get("amount")

    mint = info.get("mint")
    source = info.get("source")
    destination = info.get("destination")
    touches_target = (
        mint == target_mint
        or source in target_accounts
        or destination in target_accounts
    )
    return {
        "level": level,
        "outer_index": outer_index,
        "inner_order": inner_order,
        "type": kind,
        "mint": mint,
        "amount": amount,
        "source": source,
        "destination": destination,
        "authority": info.get("authority"),
        "source_owner": owners.get(source),
        "destination_owner": owners.get(destination),
        "touches_target": touches_target,
    }

def v15_group_candidates(tx, target_mint):
    flows = grouped_parsed_transfers(tx, target_mint)
    by_group = {}
    for f in flows:
        by_group.setdefault(f["outer_index"], []).append(f)

    candidates = []
    for outer_index, group in sorted(by_group.items(), key=lambda x: (-1 if x[0] is None else x[0])):
        target = [
            f for f in group
            if f["mint"] == target_mint
            and f["amount"] is not None
            and float(f["amount"]) > 0
        ]
        wsol = [
            f for f in group
            if f["mint"] == WSOL_MINT
            and f["amount"] is not None
            and float(f["amount"]) > 0
        ]
        if not target or not wsol:
            continue

        # Conservative rule: only one explicit target leg and one explicit WSOL leg
        # in the same parent instruction group => structurally clean candidate.
        clean = len(target) == 1 and len(wsol) == 1
        token_amount = float(target[0]["amount"]) if len(target) == 1 else None
        sol_amount = float(wsol[0]["amount"]) if len(wsol) == 1 else None
        price = None
        if clean and token_amount and sol_amount:
            price = sol_amount / token_amount

        candidates.append({
            "outer_index": outer_index,
            "target": target,
            "wsol": wsol,
            "clean": clean,
            "price": price,
            "token_amount": token_amount,
            "sol_amount": sol_amount,
            "all_flows": group,
        })
    return candidates


def v16_structured_candidates(tx, target_mint):
    """
    Decode le motif observe en V16 dans chaque groupe parent:
      WSOL principal -> token cible -> petites jambes WSOL de frais/routage.

    Le candidat est accepte seulement si:
      - exactement une jambe du token cible est presente;
      - au moins une jambe WSOL est avant elle;
      - la jambe WSOL principale est la plus grande jambe precedente;
      - les autres jambes WSOL sont nettement plus petites.
    """
    flows = grouped_parsed_transfers(tx, target_mint)
    by_group = {}
    for f in flows:
        by_group.setdefault(f["outer_index"], []).append(f)

    candidates = []

    for outer_index, group in by_group.items():
        target = [
            f for f in group
            if f["mint"] == target_mint
            and f["amount"] is not None
            and float(f["amount"]) > 0
        ]
        wsol = [
            f for f in group
            if f["mint"] == WSOL_MINT
            and f["amount"] is not None
            and float(f["amount"]) > 0
        ]

        if len(target) != 1 or not wsol:
            continue

        token_leg = target[0]
        token_order = token_leg["inner_order"]
        before = [f for f in wsol if f["inner_order"] < token_order]

        if not before:
            continue

        principal = max(before, key=lambda f: float(f["amount"]))
        principal_amount = float(principal["amount"])
        token_amount = float(token_leg["amount"])

        if principal_amount <= 0 or token_amount <= 0:
            continue

        others = [f for f in wsol if f is not principal]
        other_total = sum(float(f["amount"]) for f in others)

        # V16: les autres flux doivent ressembler a des frais/routage,
        # pas a une deuxieme jambe economique de taille comparable.
        decomposed = (
            len(wsol) >= 2
            and principal["inner_order"] < token_order
            and all(float(f["amount"]) < principal_amount * 0.25 for f in others)
            and other_total < principal_amount * 0.25
        )

        candidates.append({
            "outer_index": outer_index,
            "token_leg": token_leg,
            "principal": principal,
            "other_wsol": others,
            "token_amount": token_amount,
            "sol_amount": principal_amount,
            "other_total": other_total,
            "price": principal_amount / token_amount,
            "decomposed": decomposed,
        })

    return candidates





def build_market_price_series_legacy_disabled(pool_txs, mint, launch_time, launch_signature, creator):
    """
    V20: ancienne reconstruction OWNER-only désactivée.

    Important:
    V18 définissait build_market_price_series() deux fois. La seconde définition
    écrasait silencieusement la version OWNER+V16 validée située plus haut dans
    le fichier. Elle est conservée ici uniquement pour comparaison/diagnostic,
    mais elle n'est plus appelée par le backtest V20.
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

        obs = _owner_market_observation(tx, mint, creator)
        if not obs:
            continue

        points.append({
            "time": t,
            "price": obs["price"],
            "signature": signature,
            "direction": obs["direction"],
            "source": "OWNER_LEGACY",
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



def diagnose_v22_pre_sale(row, creator):
    """
    V22 - Diagnostic du vrai goulot d'étranglement.
    On ne regarde QUE la fenêtre utile au trading:
        launch < transaction <= vente du relay

    Le but est de séparer clairement:
      - transactions récupérées trop tard (après la vente);
      - transactions sans le mint cible;
      - transactions avec mint mais non reconnues par is_swap();
      - transactions reconnues swap mais sans prix OWNER/V16;
      - points de prix réellement utilisables avant la vente.
    """
    txs = row.get("_market_txs_v22") or []
    launch_time = row.get("launch_time")
    sale_time = row.get("sale_time")
    launch_signature = row.get("launch_signature")
    mint = row.get("mint")

    d = {
        "all_retrieved": len(txs),
        "pre_sale_window": 0,
        "after_sale": 0,
        "mint_present": 0,
        "mint_absent": 0,
        "is_swap_true": 0,
        "is_swap_false": 0,
        "owner_obs": 0,
        "v16_obs": 0,
        "owner_or_v16": 0,
        "fusion_valid": 0,
        "fusion_rejected": 0,
        "swap_but_no_price": 0,
        "mint_but_not_swap_with_price": 0,
        "parsed_target_transfer": 0,
        "parsed_target_no_price": 0,
        "points_before_sale": 0,
        "legacy_points_before_sale": 0,
        "structural_points_before_sale": 0,
        "first_point_delay": None,
        "last_point_delay": None,
        "reasons": {},
        "examples": [],
    }

    if launch_time is None or sale_time is None or not mint:
        return d

    useful_points = []

    for item in txs:
        t = item.get("time")
        tx = item.get("tx")
        sig = item.get("signature")

        if tx is None or t is None:
            d["reasons"]["tx_ou_temps_absent"] = d["reasons"].get("tx_ou_temps_absent", 0) + 1
            continue
        if sig == launch_signature or t <= launch_time:
            d["reasons"]["launch_ou_avant_launch"] = d["reasons"].get("launch_ou_avant_launch", 0) + 1
            continue
        if t > sale_time:
            d["after_sale"] += 1
            continue

        d["pre_sale_window"] += 1

        mint_present = mint in str(tx)
        if mint_present:
            d["mint_present"] += 1
        else:
            d["mint_absent"] += 1
            continue

        swap_flag = is_swap(tx)
        if swap_flag:
            d["is_swap_true"] += 1
        else:
            d["is_swap_false"] += 1

        owner = _owner_market_observation(tx, mint, creator)
        v16 = _v16_market_observation(tx, mint)
        fusion = get_v18_market_observation(tx, mint, creator)

        if owner:
            d["owner_obs"] += 1
        if v16:
            d["v16_obs"] += 1
        if owner or v16:
            d["owner_or_v16"] += 1
        if owner and v16:
            err = abs(owner["price"] - v16["price"]) / owner["price"] if owner["price"] else 999
            if err > 0.05:
                d["fusion_rejected"] += 1

        # Détecte si le token cible apparaît réellement dans des transfers parsés,
        # même si le filtre is_swap() ne reconnaît pas la transaction.
        flows = grouped_parsed_transfers(tx, mint)
        target_flows = [
            f for f in flows
            if f.get("mint") == mint
            and f.get("amount") is not None
            and float(f.get("amount") or 0) > 0
        ]
        if target_flows:
            d["parsed_target_transfer"] += 1

        if fusion:
            d["fusion_valid"] += 1
            if not swap_flag:
                d["mint_but_not_swap_with_price"] += 1
            # V23 accepte toute observation structurelle OWNER/V16 cohérente.
            # On garde aussi le compteur legacy pour mesurer exactement le gain.
            if swap_flag:
                d["legacy_points_before_sale"] += 1
            useful_points.append((t, fusion["price"], sig, fusion.get("source")))
        else:
            if swap_flag:
                d["swap_but_no_price"] += 1
            if target_flows:
                d["parsed_target_no_price"] += 1

            if len(d["examples"]) < 4:
                reason = []
                if not swap_flag:
                    reason.append("IS_SWAP_FALSE")
                if not owner:
                    reason.append("NO_OWNER")
                if not v16:
                    reason.append("NO_V16")
                if target_flows:
                    reason.append("TARGET_TRANSFER_PRESENT")
                d["examples"].append({
                    "delay": t - launch_time,
                    "sig": sig,
                    "reason": "+".join(reason) if reason else "AUTRE",
                })

    useful_points.sort(key=lambda x: x[0])
    d["points_before_sale"] = len(useful_points)
    d["structural_points_before_sale"] = len(useful_points)
    if useful_points:
        d["first_point_delay"] = useful_points[0][0] - launch_time
        d["last_point_delay"] = useful_points[-1][0] - launch_time

    # Conclusion automatique par launch.
    if d["pre_sale_window"] == 0:
        dominant = "AUCUNE_TRANSACTION_AVANT_VENTE"
    elif d["mint_present"] == 0:
        dominant = "SOURCES_NE_CAPTENT_PAS_LE_MARCHE_AVANT_VENTE"
    elif d["is_swap_true"] == 0 and d["mint_present"] > 0:
        dominant = "FILTRE_IS_SWAP_TROP_STRICT"
    elif d["owner_or_v16"] == 0 and d["is_swap_true"] > 0:
        dominant = "DECODEUR_PRIX_INCAPABLE_SUR_SWAPS"
    elif d["points_before_sale"] <= 1:
        dominant = "DENSITE_PRIX_AVANT_VENTE_INSUFFISANTE"
    else:
        dominant = "OK_OU_PARTIEL"
    d["dominant"] = dominant
    return d


def print_v23_diagnostic(results, creator):
    print("\n" + "=" * 110)
    print("V24 - VALIDATION DU FILTRE STRUCTUREL")
    print("=" * 110)
    print("Fenêtre analysée : APRES le launch et AVANT/À la vente du relay uniquement.")
    print("C'est cette fenêtre qui compte réellement pour le paper trading.\n")

    diagnostics = []
    for r in results:
        if r.get("sale_time") is None or not r.get("_market_txs_v22"):
            continue
        d = diagnose_v22_pre_sale(r, creator)
        diagnostics.append((r, d))
        print(
            f"#{r['n']:02d} {r['mint'][:8]}.. | "
            f"tx_avant_vente={d['pre_sale_window']:>3} | "
            f"mint={d['mint_present']:>3} | swap={d['is_swap_true']:>3} | "
            f"OWNER/V16={d['owner_or_v16']:>3} | "
            f"prix legacy={d['legacy_points_before_sale']:>3} -> V23={d['structural_points_before_sale']:>3} | "
            f"1er={('T+' + str(d['first_point_delay']) + 's') if d['first_point_delay'] is not None else '-':>8} | "
            f"{d['dominant']}"
        )

    if not diagnostics:
        print("Aucun launch avec vente + transactions marché disponible.")
        return

    totals = {}
    keys = [
        "all_retrieved", "pre_sale_window", "after_sale", "mint_present", "mint_absent",
        "is_swap_true", "is_swap_false", "owner_obs", "v16_obs", "owner_or_v16",
        "fusion_valid", "fusion_rejected", "swap_but_no_price",
        "mint_but_not_swap_with_price", "parsed_target_transfer",
        "parsed_target_no_price", "points_before_sale", "legacy_points_before_sale",
        "structural_points_before_sale"
    ]
    for k in keys:
        totals[k] = sum(d[k] for _, d in diagnostics)

    print("\n" + "-" * 110)
    print("FUNNEL GLOBAL V23")
    print("-" * 110)
    print("Transactions récupérées au total              :", totals["all_retrieved"])
    print("Transactions APRÈS la vente relay             :", totals["after_sale"])
    print("Transactions dans la fenêtre launch->vente    :", totals["pre_sale_window"])
    print("  dont mint cible présent                      :", totals["mint_present"])
    print("  dont mint cible absent                       :", totals["mint_absent"])
    print("  dont is_swap=True                            :", totals["is_swap_true"])
    print("  dont is_swap=False                           :", totals["is_swap_false"])
    print("  prix OWNER trouvé                            :", totals["owner_obs"])
    print("  prix V16 trouvé                              :", totals["v16_obs"])
    print("  OWNER ou V16 trouvé                          :", totals["owner_or_v16"])
    print("  fusion OWNER/V16 rejetée >5%                 :", totals["fusion_rejected"])
    print("  swaps reconnus mais SANS prix                :", totals["swap_but_no_price"])
    print("  prix trouvable mais bloqué par is_swap=False :", totals["mint_but_not_swap_with_price"])
    print("  tx avec transfert parsé du token cible       :", totals["parsed_target_transfer"])
    print("  transfert cible mais aucun prix OWNER/V16    :", totals["parsed_target_no_price"])
    print("  points legacy avec is_swap=True              :", totals["legacy_points_before_sale"])
    print("  POINTS V23 structurels utilisables           :", totals["structural_points_before_sale"])
    print("  GAIN V23                                      :", totals["structural_points_before_sale"] - totals["legacy_points_before_sale"])

    sparse = [(r, d) for r, d in diagnostics if d["points_before_sale"] <= 1]
    print("\nLaunches avec <=1 point AVANT la vente :", len(sparse), "/", len(diagnostics))
    for r, d in sparse:
        print(
            f"  #{r['n']:02d} {r['mint'][:8]}.. : {d['dominant']} | "
            f"tx={d['pre_sale_window']} mint={d['mint_present']} swap={d['is_swap_true']} "
            f"legacy={d['legacy_points_before_sale']} V23={d['structural_points_before_sale']}"
        )
        for ex in d["examples"][:2]:
            print(f"      exemple T+{ex['delay']}s {str(ex['sig'])[:12]}.. -> {ex['reason']}")

    # Diagnostic automatique global, ordonné par cause technique.
    pre = totals["pre_sale_window"]
    mintp = totals["mint_present"]
    swaps = totals["is_swap_true"]
    points = totals["points_before_sale"]
    blocked_swap_filter = totals["mint_but_not_swap_with_price"]
    no_price = totals["swap_but_no_price"]

    print("\n" + "=" * 110)
    print("CONCLUSION AUTOMATIQUE V23")
    print("=" * 110)

    if pre == 0:
        print("PROBLEME IDENTIFIE : les sources d'adresses ne ramènent aucune transaction avant les ventes relay.")
        print("ACTION V24 : revoir les sources marché, car V23 ne reçoit aucune donnée utile.")
    elif mintp == 0:
        print("PROBLEME IDENTIFIE : les transactions sont récupérées, mais elles ne concernent pas le mint avant la vente.")
        print("ACTION V24 : identifier les vraies adresses/vaults de marché.")
    elif blocked_swap_filter > 0 and blocked_swap_filter >= max(2, points):
        print("PROBLEME IDENTIFIE : is_swap() élimine une quantité importante de transactions dont le prix est pourtant décodable.")
        print("V23 CONFIRME : ces transactions sont désormais admises par OWNER/V16.")
    elif swaps > 0 and no_price / swaps >= 0.50:
        print("PROBLEME IDENTIFIE : les swaps sont bien récupérés/reconnus, mais OWNER/V16 ne sait pas en extraire le prix dans la majorité des cas.")
        print("ACTION V24 : étendre le décodeur des jambes SOL/WSOL/token, pas les sources RPC.")
    elif points <= len(diagnostics):
        print("PROBLEME IDENTIFIE : la densité de prix AVANT les ventes reste <= ~1 point par launch.")
        print("Les transactions existent mais la chaîne source->filtre->prix en perd encore trop.")
        print("ACTION V24 : traiter uniquement les transactions encore sans prix structurel.")
    else:
        print("Le parseur fournit plusieurs points avant vente sur une part significative des launches.")
        print("ACTION V23 : reconstruire le backtest uniquement sur cette fenêtre et ajouter les garde-fous d'exécution.")




# ============================== V25 ==========================================
# Moteur de décision réaliste : aucune donnée postérieure à l'entrée n'est
# utilisée pour décider d'entrer. La sélection des paramètres se fait sur la
# partie ancienne de l'historique, puis est évaluée sur la partie récente.

def _v25_first_point_after(series, earliest_time, latest_time):
    pts = [p for p in (series or []) if p.get("time") is not None and p.get("price") and p["price"] > 0]
    pts.sort(key=lambda p: p["time"])
    for p in pts:
        if p["time"] >= earliest_time and (latest_time is None or p["time"] <= latest_time):
            return p
    return None

def _v25_execute(row, delay_s, tp_pct, sl_pct, timeout_s, latency_s=2, cost_side_pct=1.0):
    launch = row.get("launch_time")
    sale = row.get("sale_time")
    series = sorted(row.get("market_series") or [], key=lambda p: p.get("time") or 0)
    if launch is None or sale is None or not series:
        return None

    # Signal d'entrée : uniquement un prix réellement observé après le délai + latence.
    earliest = launch + delay_s + latency_s
    entry = _v25_first_point_after(series, earliest, sale)
    if not entry:
        return None
    et, raw_entry = entry["time"], entry["price"]
    if raw_entry <= 0:
        return None

    # Hypothèse d'exécution conservatrice : coût/slippage appliqué de chaque côté.
    entry_exec = raw_entry * (1.0 + cost_side_pct / 100.0)
    deadline = min(sale, et + timeout_s)
    points = [p for p in series if et <= p.get("time", -1) <= deadline and p.get("price", 0) > 0]
    if not points:
        return None

    tp_price = entry_exec * (1.0 + tp_pct / 100.0)
    sl_price = entry_exec * (1.0 - sl_pct / 100.0)
    chosen = None
    reason = None
    for p in points:
        px = p["price"] * (1.0 - cost_side_pct / 100.0)
        if px >= tp_price:
            chosen, reason = p, "TP"
            break
        if px <= sl_price:
            chosen, reason = p, "SL"
            break

    if chosen is None:
        # Sortie au dernier prix réellement observable avant relay/timeout.
        chosen = points[-1]
        reason = "RELAY" if deadline == sale else "TIMEOUT"

    exit_exec = chosen["price"] * (1.0 - cost_side_pct / 100.0)
    pnl = (exit_exec / entry_exec - 1.0) * 100.0
    return {
        "pnl_pct": pnl, "reason": reason, "entry_time": et,
        "exit_time": chosen["time"], "entry_price": entry_exec,
        "exit_price": exit_exec, "points": len(points),
    }

def _v25_score(rows, params, cost_side_pct):
    sims=[]
    for r in rows:
        s=_v25_execute(r, cost_side_pct=cost_side_pct, **params)
        if s: sims.append(s)
    if not sims:
        return None
    pnls=[s["pnl_pct"] for s in sims]
    return {
        "trades":len(sims), "avg":sum(pnls)/len(pnls),
        "wins":sum(x>0 for x in pnls), "losses":sum(x<0 for x in pnls),
        "total":sum(pnls), "sims":sims,
    }

def run_v25_decision_engine(results):
    print("\n" + "="*110)
    print("V25 - MOTEUR DE DECISION + VALIDATION CHRONOLOGIQUE HORS ECHANTILLON")
    print("="*110)
    rows=[r for r in results if r.get("launch_time") is not None and r.get("sale_time") is not None and r.get("market_series")]
    rows.sort(key=lambda r:r["launch_time"])
    if len(rows) < 6:
        print("Pas assez de launches exploitables pour une validation chronologique.")
        return

    split=max(4, int(len(rows)*0.65))
    train, test=rows[:split], rows[split:]
    print(f"Launches exploitables : {len(rows)} | apprentissage ancien : {len(train)} | test récent jamais utilisé pour choisir : {len(test)}")
    print("Règle anti-overfit : les paramètres sont choisis UNIQUEMENT sur la partie ancienne.")

    # Grille volontairement petite et prédéfinie : évite de fabriquer une stratégie sur 13 tokens.
    candidates=[]
    for delay in (2, 10, 30, 60):
        for tp, sl in ((10,10),(20,10),(20,15),(30,15)):
            for timeout in (120,300,600):
                candidates.append({"delay_s":delay,"tp_pct":tp,"sl_pct":sl,"timeout_s":timeout,"latency_s":2})

    # 1% par côté = scénario conservateur provisoire incluant slippage/coûts d'exécution.
    cost=1.0
    ranked=[]
    for p in candidates:
        sc=_v25_score(train,p,cost)
        if sc and sc["trades"] >= max(3, len(train)//2):
            ranked.append((sc["avg"], sc["trades"], p, sc))
    ranked.sort(key=lambda x:(x[0],x[1]), reverse=True)
    if not ranked:
        print("Aucune configuration n'a assez de trades sur l'échantillon d'apprentissage.")
        return

    _,_,best,train_sc=ranked[0]
    test_sc=_v25_score(test,best,cost)
    print("\nMeilleure règle sur données ANCIENNES (pas sur le test) :")
    print(f"  attente={best['delay_s']}s | TP={best['tp_pct']}% | SL={best['sl_pct']}% | timeout={best['timeout_s']}s | latence={best['latency_s']}s | coût/slippage={cost:.1f}% par côté")
    print(f"  TRAIN : {train_sc['trades']} trades | {train_sc['wins']} gagnants | P&L moyen net simulé={train_sc['avg']:+.2f}%")
    if test_sc:
        print(f"  TEST  : {test_sc['trades']} trades | {test_sc['wins']} gagnants | P&L moyen net simulé={test_sc['avg']:+.2f}%")
        print("\nDétail TEST :")
        ti=0
        for r in test:
            s=_v25_execute(r,cost_side_pct=cost,**best)
            if not s: continue
            ti+=1
            print(f"  #{r['n']:02d} {r['mint'][:8]}.. | entrée T+{s['entry_time']-r['launch_time']}s | sortie={s['reason']:<7} | P&L={s['pnl_pct']:+.2f}%")
    else:
        print("  TEST : aucun trade exécutable avec cette règle.")

    print("\nTEST DE ROBUSTESSE DES COÛTS sur la même règle (sans ré-optimiser) :")
    for c in (0.5,1.0,2.0,3.0):
        sc=_v25_score(test,best,c)
        if sc:
            print(f"  {c:.1f}%/côté -> {sc['trades']} trades | P&L moyen={sc['avg']:+.2f}% | gagnants={sc['wins']}/{sc['trades']}")
        else:
            print(f"  {c:.1f}%/côté -> aucun trade")

    print("\nINTERPRETATION V25")
    if not test_sc or test_sc["trades"] < 3:
        print("Échantillon test trop petit : aucune conclusion de rentabilité autorisée.")
    elif test_sc["avg"] <= 0:
        print("La logique testée ne démontre PAS d'avantage net hors échantillon. Le bot doit rester en simulation.")
    else:
        print("Signal positif hors échantillon, mais échantillon encore trop petit : validation paper trading temps réel obligatoire avant argent réel.")
    print("Aucun ordre réel n'est envoyé par V25.")


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
            market_accounts_v21 = extract_launchlab_market_accounts_v21(
                item["tx"],
                launch["mint"],
                creator,
                launch.get("pool_state"),
            )
            launches.append({
                "mint": launch["mint"],
                "pool_state": launch.get("pool_state"),
                "time": item["time"],
                "signature": item["signature"],
                "market_accounts_v21": market_accounts_v21,
            })

        launches.sort(key=lambda x: x["time"] or 0)
        print("\nLaunches trouvés :", len(launches))

        # Cache: several launches reuse the same relay wallet.
        wallet_cache = {}
        market_cache = {}
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
                "launch_signature": launch.get("signature"),
                "transfer_time": candidate["transfer_time"] if candidate else None,
                "sale_time": None,
                "sold_tokens": None,
                "received_tokens": None,
                "entry_time": None,
                "entry_price_sol": None,
                "entry_buyer": None,
                "entry_signature": None,
                "entry_source": None,
                "paper_return_pct": None,
                "market_series": [],
                "market_tx_count": 0,
                "market_unique_signatures": 0,
                "v21_launch_accounts": len(launch.get("market_accounts_v21") or []),
                "v21_source_addresses": 0,
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
                cache_key = (pool_state, mint, launch.get("time"))
                if cache_key not in market_cache:
                    # V21: pool_state + mint + comptes writable extraits
                    # directement de l'instruction LaunchLab de création.
                    v21_addresses = [pool_state, mint] + (launch.get("market_accounts_v21") or [])
                    merged_txs, source_counts, unique_sig_count = await get_multi_address_transactions_v21(
                        rpc,
                        settings.rpc_url,
                        v21_addresses,
                        start_time=launch["time"],
                        end_time=(launch["time"] + 21600) if launch["time"] is not None else None,
                        max_signatures_per_address=1500,
                    )
                    market_cache[cache_key] = {
                        "txs": merged_txs,
                        "source_counts": source_counts,
                        "unique_sig_count": unique_sig_count,
                    }

                market_txs = market_cache[cache_key]["txs"]

                entry = find_first_market_buy_v18(
                    market_txs,
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
                    row["entry_source"] = entry.get("source")

                row["market_series"] = build_market_price_series(
                    market_txs,
                    mint,
                    launch["time"],
                    launch["signature"],
                    creator,
                )
                row["market_tx_count"] = len(market_txs)
                row["market_unique_signatures"] = market_cache[cache_key]["unique_sig_count"]
                row["v21_source_addresses"] = len(market_cache[cache_key]["source_counts"])
                row["_market_txs_v22"] = market_txs

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
    print("V25 - BASE STABILISEE : ENTREE PREMIER PRIX STRUCTUREL -> VENTE RELAY")
    print("=" * 110)
    pools = [r for r in results if r.get("pool_state")]
    entries = [r for r in results if r.get("entry_price_sol") is not None]
    print("Launches avec pool_state :", len(pools), "/", len(results))
    print("Entrées marché détectées :", len(entries), "/", len(results))

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
    print("V24 - BACKTEST STABILISE AVEC GARDE-FOU ECONOMIQUE")
    print("=" * 110)

    analyzable = [
        r for r in results
        if r.get("entry_time") is not None
        and r.get("entry_price_sol") is not None
        and r.get("sale_time") is not None
        and r.get("market_series")
    ]

    print("Launches avec série de prix exploitable :", len(analyzable), "/", len(results))
    print("V24 source transactions : pool_state + mint SPL + comptes writable LaunchLab, signatures dédupliquées")
    if analyzable:
        print("Transactions marché récupérées :", sum(r.get("market_tx_count", 0) for r in analyzable))
        print("Signatures uniques candidates :", sum(r.get("market_unique_signatures", 0) for r in analyzable))

    point_counts = [len(r.get("market_series") or []) for r in analyzable]
    if point_counts:
        print("Points de prix total :", sum(point_counts))
        print("Points moyens par launch :", round(sum(point_counts) / len(point_counts), 1))
        print("Launches avec >= 5 points :", sum(n >= 5 for n in point_counts), "/", len(point_counts))
        print("Launches avec >= 10 points :", sum(n >= 10 for n in point_counts), "/", len(point_counts))
        all_points = [p for r in analyzable for p in (r.get("market_series") or [])]
        by_source = {}
        for p in all_points:
            by_source[p.get("source", "?")] = by_source.get(p.get("source", "?"), 0) + 1
        print("Répartition sources prix :", by_source)
        print(
            "V24 contrôle fusion :",
            "OWNER=", by_source.get("OWNER", 0),
            "| V16=", by_source.get("V16", 0),
            "| OWNER+V16=", by_source.get("OWNER+V16", 0),
        )

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
    print("MATRICE EXPLORATOIRE - PRIX V24 STABILISES (FRAIS/SLIPPAGE A INTEGRER APRES VALIDATION)")
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

    if robust:
        print("\nMATRICE QUALITE >=5 POINTS - BRUT")
        print(f"{'TP':>7} {'SL':>7} {'Trades':>8} {'Win':>6} {'Loss':>6} {'P&L moy':>11}")
        for tp_pct, sl_pct in strategies:
            sims = []
            for r in robust:
                sim = simulate_tp_sl(
                    r["market_series"], r["entry_time"], r["entry_price_sol"],
                    r["sale_time"], tp_pct, sl_pct,
                )
                if sim:
                    sims.append(sim)
            if sims:
                pnls = [x["pnl_pct"] for x in sims]
                print(
                    f"{tp_pct:>6}% {sl_pct:>6}% {len(sims):>8} "
                    f"{sum(x > 0 for x in pnls):>6} {sum(x < 0 for x in pnls):>6} "
                    f"{sum(pnls)/len(pnls):>+10.2f}%"
                )

    if len(robust) < len(analyzable):
        print(
            "Les résultats globaux restent exploratoires pour les launches ayant "
            "moins de 5 prix observés."
        )

    print("\nIMPORTANT : V24 n'exige plus is_swap=True pour construire un prix : OWNER/V16 devient le critère structurel.")
    print("Ils n'incluent PAS encore frais, slippage, latence d'exécution ni taille de position.")

    print_v23_diagnostic(results, creator)

    run_v25_decision_engine(results)


if __name__ == "__main__":
    asyncio.run(main())
