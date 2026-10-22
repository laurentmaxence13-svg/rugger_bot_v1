import asyncio
import os
import sqlite3
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

from bot.config import get_settings
from bot.solana.rpc import SolanaRPC
from bot.scanner.transaction_parser import find_raydium_launch


LIMIT = 100
RPC_DELAY = 0.5
BIRDEYE_DELAY = 1.1

load_dotenv()
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY")


async def get_creator_launches():
    settings = get_settings()

    connection = sqlite3.connect(settings.db_path)

    row = connection.execute(
        """
        SELECT deployer_candidate
        FROM launch_candidates
        WHERE mint IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    connection.close()

    if row is None:
        return None, []

    creator = row[0]

    async with SolanaRPC(settings.rpc_url) as rpc:

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [
                creator,
                {"limit": LIMIT},
            ],
        }

        async with rpc.session.post(
            settings.rpc_url,
            json=payload,
        ) as response:
            data = await response.json()

        signatures = data.get("result", [])

        launches = []

        for item in signatures:
            signature = item["signature"]

            tx = await rpc.get_transaction(signature)

            if tx is None:
                continue

            launch = find_raydium_launch(tx)

            if launch and launch.get("creator") == creator:
                mint = launch.get("mint")

                if mint:
                    launches.append(
                        {
                            "mint": mint,
                            "slot": item.get("slot"),
                            "block_time": item.get("blockTime"),
                        }
                    )

            await asyncio.sleep(RPC_DELAY)

    return creator, launches


def get_price_history(mint, block_time):

    if block_time is None:
        return []

    url = "https://public-api.birdeye.so/defi/history_price"

    headers = {
        "X-API-KEY": BIRDEYE_API_KEY,
        "x-chain": "solana",
    }

    params = {
        "address": mint,
        "address_type": "token",
        "type": "1m",
        "time_from": block_time,
        "time_to": block_time + (24 * 60 * 60),
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=20,
        )

        if response.status_code != 200:
            print(
                f"   -> Birdeye HTTP "
                f"{response.status_code}"
            )
            return []

        data = response.json()

        return (
            data.get("data", {})
            .get("items", [])
        )

    except requests.RequestException as error:
        print(f"   -> Erreur Birdeye : {error}")
        return []


def price_at_delay(history, first_time, delay_seconds):

    target = first_time + delay_seconds

    available = [
        item
        for item in history
        if item.get("unixTime") is not None
        and item.get("value") is not None
        and item["unixTime"] <= target
    ]

    if not available:
        return None

    return available[-1]["value"]


def analyse_history(history, block_time):

    valid = [
        item
        for item in history
        if item.get("unixTime") is not None
        and item.get("value") is not None
        and item["value"] > 0
    ]

    valid.sort(key=lambda item: item["unixTime"])

    if not valid:
        return None

    first = valid[0]

    first_time = first["unixTime"]
    first_price = first["value"]

    delay_seconds = max(
        0,
        first_time - block_time,
    )

    ath_item = max(
        valid,
        key=lambda item: item["value"],
    )

    ath = ath_item["value"]
    ath_time = ath_item["unixTime"]

    multiplier = ath / first_price

    time_to_ath = max(
        0,
        ath_time - first_time,
    )

    last_price = valid[-1]["value"]

    drawdown_from_ath = (
        ((last_price / ath) - 1) * 100
        if ath > 0
        else 0
    )

    return {
        "points": len(valid),
        "first_time": first_time,
        "first_price": first_price,
        "delay_seconds": delay_seconds,
        "ath": ath,
        "multiplier": multiplier,
        "time_to_ath": time_to_ath,
        "last_price": last_price,
        "drawdown": drawdown_from_ath,
        "price_5m": price_at_delay(
            valid, first_time, 5 * 60
        ),
        "price_15m": price_at_delay(
            valid, first_time, 15 * 60
        ),
        "price_1h": price_at_delay(
            valid, first_time, 60 * 60
        ),
        "price_6h": price_at_delay(
            valid, first_time, 6 * 60 * 60
        ),
        "price_24h": valid[-1]["value"],
    }


def format_multiplier(price, initial):

    if price is None or initial <= 0:
        return "N/A"

    return f"x{price / initial:.2f}"


def format_duration(seconds):

    if seconds < 60:
        return f"{seconds} sec"

    if seconds < 3600:
        return f"{seconds / 60:.1f} min"

    return f"{seconds / 3600:.2f} h"


async def main():

    print("=" * 65)
    print("ANALYSE PERFORMANCE CREATOR")
    print("=" * 65)

    creator, launches = await get_creator_launches()

    if creator is None:
        print("Aucun creator trouvé.")
        return

    print(f"Creator : {creator}")
    print(f"Launches trouvés : {len(launches)}")
    print()

    for index, launch in enumerate(
        launches,
        start=1,
    ):

        mint = launch["mint"]
        block_time = launch["block_time"]

        print("=" * 65)
        print(
            f"[{index}/{len(launches)}] {mint}"
        )

        if block_time:
            launch_date = datetime.fromtimestamp(
                block_time
            )

            print(
                "Launch :",
                launch_date.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            )

        history = get_price_history(
            mint,
            block_time,
        )

        if not history:
            print(
                "-> Aucun historique Birdeye"
            )
            print()
            time.sleep(BIRDEYE_DELAY)
            continue

        result = analyse_history(
            history,
            block_time,
        )

        if result is None:
            print(
                "-> Historique inexploitable"
            )
            print()
            time.sleep(BIRDEYE_DELAY)
            continue

        initial = result["first_price"]

        print(
            f"Points : {result['points']}"
        )

        print(
            "Delai launch -> premiere donnee :",
            format_duration(
                result["delay_seconds"]
            ),
        )

        print(
            f"Premier prix Birdeye : "
            f"{initial:.12g}"
        )

        print(
            f"ATH 24h : "
            f"{result['ath']:.12g}"
        )

        print(
            f"Multiplicateur max : "
            f"x{result['multiplier']:.2f}"
        )

        print(
            "Temps jusqu'a ATH :",
            format_duration(
                result["time_to_ath"]
            ),
        )

        print(
            "Performance 5 min :",
            format_multiplier(
                result["price_5m"],
                initial,
            ),
        )

        print(
            "Performance 15 min :",
            format_multiplier(
                result["price_15m"],
                initial,
            ),
        )

        print(
            "Performance 1 h :",
            format_multiplier(
                result["price_1h"],
                initial,
            ),
        )

        print(
            "Performance 6 h :",
            format_multiplier(
                result["price_6h"],
                initial,
            ),
        )

        print(
            "Performance 24 h :",
            format_multiplier(
                result["price_24h"],
                initial,
            ),
        )

        print(
            "Chute ATH -> fin : "
            f"{result['drawdown']:.1f}%"
        )

        print(
            "Seuils :",
            f"x2={'OUI' if result['multiplier'] >= 2 else 'NON'} |",
            f"x5={'OUI' if result['multiplier'] >= 5 else 'NON'} |",
            f"x10={'OUI' if result['multiplier'] >= 10 else 'NON'}",
        )

        print()

        time.sleep(BIRDEYE_DELAY)


if __name__ == "__main__":
    asyncio.run(main())