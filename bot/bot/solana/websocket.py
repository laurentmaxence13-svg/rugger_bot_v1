import asyncio
import json
from datetime import datetime, timezone

import websockets


async def stream_program_logs(ws_url: str, program_id: str):
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [program_id]},
            {"commitment": "confirmed"},
        ],
    }

    while True:
        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=4_000_000,
            ) as ws:

                await ws.send(json.dumps(request))

                print(
                    f"[WS] Connecte. Programme surveille: "
                    f"{program_id}"
                )

                async for raw in ws:
                    received_at = datetime.now(timezone.utc)
                    msg = json.loads(raw)

                    # Confirmation de l'abonnement WebSocket
                    if "result" in msg and msg.get("id") == 1:
                        print(
                            f"[WS] Abonnement actif: "
                            f"{msg['result']}"
                        )
                        continue

                    # Ignore tout ce qui n'est pas un log Solana
                    if msg.get("method") != "logsNotification":
                        continue

                    result = msg["params"]["result"]
                    value = result["value"]

                    # Ignore les transactions en erreur
                    if value.get("err") is not None:
                        continue

                    logs = value.get("logs", [])

                    # FILTRE IMPORTANT :
                    # on ne garde que les créations Launchpad
                    is_new_launch = any(
                        "Instruction: InitializeV2" in log
                        for log in logs
                    )

                    if not is_new_launch:
                        continue

                    print(
                        "[FILTRE] Nouveau lancement "
                        "Raydium potentiel detecte"
                    )

                    yield {
                        "signature": value["signature"],
                        "slot": result["context"]["slot"],
                        "logs": logs,
                        "received_at": received_at,
                    }

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[WS] Deconnexion: {exc}. "
                "Reconnexion dans 2 s..."
            )
            await asyncio.sleep(2)