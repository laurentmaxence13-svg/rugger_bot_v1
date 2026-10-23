import asyncio
import json
import time
from datetime import datetime, timezone

import websockets


PUBLIC_SOLANA_WS = "wss://api.mainnet-beta.solana.com"


class SubscriptionRejected(RuntimeError):
    pass


def _is_rate_limit(exc):
    """Return True when the WebSocket handshake was rejected with HTTP 429."""
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    return status == 429 or "429" in str(exc)


async def stream_program_logs(ws_url: str, program_id: str, *, on_state=None):
    """Stream LaunchLab logs without depending exclusively on Helius WebSocket.

    Helius HTTP RPC remains the source used by the scanner to fetch and parse
    transactions. If the Helius WebSocket handshake is rate-limited, this
    stream switches to Solana's public WebSocket for log notifications.
    No signing or transaction submission is performed.
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [program_id]},
            {"commitment": "confirmed"},
        ],
    }

    current_url = ws_url
    using_fallback = False

    async def report(state, reason=None):
        if on_state is not None:
            await on_state({'state': state, 'reason': reason})

    while True:
        try:
            await report('subscribing')
            async with websockets.connect(
                current_url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                open_timeout=12,
                max_size=4_000_000,
                max_queue=16,
            ) as ws:
                await ws.send(json.dumps(request))
                # A live TCP connection is not proof of a successful subscription.
                ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
                if (not isinstance(ack, dict) or ack.get('id') != 1
                        or 'error' in ack or not isinstance(ack.get('result'), int)
                        or isinstance(ack.get('result'), bool) or ack['result'] < 0):
                    code = (ack.get('error') or {}).get('code') if isinstance(ack, dict) and isinstance(ack.get('error'), dict) else None
                    await report('subscription_refused', f'RPC_{code}')
                    raise SubscriptionRejected(f'logsSubscribe refused (RPC {code})')
                subscription = ack['result']
                await report('subscribed')

                source = "SOLANA PUBLIC" if using_fallback else "HELIUS"
                print(f"[WS] Abonnement confirme via {source}: {subscription}. Programme surveille: {program_id}")

                # Diagnostic: count actual program notifications, not just subscriptions.
                seen_logs = 0
                seen_launches = 0
                last_report = time.monotonic()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        print(f"[WS DIAG] 30s sans notification | logs={seen_logs} lancements={seen_launches}", flush=True)
                        continue
                    received_at = datetime.now(timezone.utc)
                    msg = json.loads(raw)

                    if "result" in msg and msg.get("id") == 1:
                        print(f"[WS] Abonnement actif: {msg['result']}")
                        continue

                    if msg.get("method") != "logsNotification":
                        continue
                    if msg.get('params', {}).get('subscription') != subscription:
                        continue

                    result = msg["params"]["result"]
                    value = result["value"]
                    if value.get("err") is not None:
                        continue

                    seen_logs += 1
                    logs = value.get("logs", [])

                    # logsSubscribe est deja limite au programme LaunchLab.
                    # Ne pas deviner le nom texte de l'instruction ici :
                    # chaque transaction reussie est transmise au parseur,
                    # qui verifie ensuite structurellement initializeMint +
                    # l'instruction Raydium et ses comptes.
                    if time.monotonic() - last_report >= 30:
                        print(
                            f"[WS DIAG] 30s | notifications={seen_logs} "
                            f"transmises={seen_launches}",
                            flush=True,
                        )
                        last_report = time.monotonic()

                    seen_launches += 1
                    yield {
                        "signature": value["signature"],
                        "slot": result["context"]["slot"],
                        "logs": logs,
                        "received_at": received_at,
                    }

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await report('disconnected', type(exc).__name__)
            if not using_fallback and _is_rate_limit(exc):
                using_fallback = True
                current_url = PUBLIC_SOLANA_WS
                print(
                    "[WS] Helius limite le WebSocket (HTTP 429). "
                    "Bascule automatique vers Solana public..."
                )
                await asyncio.sleep(1)
                continue

            source = "Solana public" if using_fallback else "Helius"
            print(f"[WS] {source} indisponible: {type(exc).__name__}. Reconnexion dans 15 s...")
            await asyncio.sleep(15)
