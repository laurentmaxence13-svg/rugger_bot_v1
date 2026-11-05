from dataclasses import dataclass
from pathlib import Path
import os
try:
    from dotenv import load_dotenv
except ImportError:  # Permet les tests qui n'ont pas besoin de charger .env.
    def load_dotenv(*_args, **_kwargs):
        return False

BASE_DIR = Path(__file__).resolve().parent.parent
# Offline demo/report entry points opt out before importing the engine.
# Normal supervised PAPER operation preserves the existing configuration path.
if os.getenv("RUGGER_NO_DOTENV") != "1":
    load_dotenv(BASE_DIR / ".env")

@dataclass(frozen=True)
class Settings:
    api_key: str
    rpc_url: str
    ws_url: str
    raydium_launchpad_program_id: str
    db_path: Path

def get_settings() -> Settings:
    api_key = os.getenv("HELIUS_API_KEY", "").strip()
    if not api_key or api_key == "COLLE_TA_CLE_ICI":
        raise RuntimeError(
            "Clé Helius absente. Copie .env.example en .env puis ajoute HELIUS_API_KEY."
        )

    program_id = os.getenv(
        "RAYDIUM_LAUNCHPAD_PROGRAM_ID",
        "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
    ).strip()

    return Settings(
        api_key=api_key,
        rpc_url=f"https://mainnet.helius-rpc.com/?api-key={api_key}",
        ws_url=f"wss://mainnet.helius-rpc.com/?api-key={api_key}",
        raydium_launchpad_program_id=program_id,
        db_path=BASE_DIR / "data" / "rugger_bot.db",
    )
