import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BIRDEYE_API_KEY")

MINT = "So11111111111111111111111111111111111111112"

url = "https://public-api.birdeye.so/defi/price"

headers = {
    "X-API-KEY": API_KEY,
    "x-chain": "solana",
}

params = {
    "address": MINT,
}

print("Envoi de la requete...")

try:
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )

    print("HTTP :", response.status_code)
    print("REPONSE :", response.text)

except requests.exceptions.Timeout:
    print("ERREUR : Birdeye timeout")

except requests.exceptions.RequestException as error:
    print("ERREUR :", error)