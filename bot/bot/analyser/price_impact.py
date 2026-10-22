import os
import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("BIRDEYE_API_KEY")

# Token #14 déjà vérifié dans notre analyse
MINT = "87L44bmN2bcJX5LTgd8FaXCGUHQQkY2WdrVWVbaYKK6F"

# Heure connue :
# le wallet relais reçoit les tokens,
# puis les vend 108 secondes plus tard.
#
# On récupérera automatiquement l'heure exacte
# depuis Solana dans l'étape suivante.
#
# Pour ce premier test, on vérifie d'abord
# que Birdeye renvoie correctement l'historique.
SALE_TIME = 1789320674

TIME_FROM = SALE_TIME - 300
TIME_TO = SALE_TIME + 600


def get_history():
    if not API_KEY:
        print("ERREUR : BIRDEYE_API_KEY introuvable.")
        return

    url = (
        "https://public-api.birdeye.so/"
        "defi/history_price"
    )

    headers = {
        "X-API-KEY": API_KEY,
        "x-chain": "solana",
        "accept": "application/json",
    }

    params = {
        "address": MINT,
        "address_type": "token",
        "type": "1m",
        "time_from": TIME_FROM,
        "time_to": TIME_TO,
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    print("=" * 60)
    print("TEST IMPACT PRIX WALLET RELAIS")
    print("=" * 60)

    print("HTTP :", response.status_code)
    print("Token :", MINT)

    if response.status_code != 200:
        print("ERREUR BIRDEYE")
        print(response.text)
        return

    data = response.json()

    if not data.get("success"):
        print("Réponse Birdeye invalide :")
        print(data)
        return

    items = (
        data.get("data", {})
        .get("items", [])
    )

    print(
        "Points de prix récupérés :",
        len(items),
    )

    if not items:
        print(
            "Aucun historique de prix "
            "pour cette période."
        )
        return

    print()
    print("PREMIERS POINTS")
    print("-" * 60)

    for item in items[:10]:
        print(
            "Timestamp :",
            item.get("unixTime"),
            "| Prix :",
            item.get("value"),
        )

    print()
    print("DERNIERS POINTS")
    print("-" * 60)

    for item in items[-10:]:
        print(
            "Timestamp :",
            item.get("unixTime"),
            "| Prix :",
            item.get("value"),
        )


if __name__ == "__main__":
    get_history()