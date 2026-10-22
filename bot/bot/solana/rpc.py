import asyncio
import aiohttp


class SolanaRPC:
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()

    async def get_transaction(self, signature: str, retries: int = 6):
        assert self.session is not None

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "commitment": "confirmed",
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 1,
                },
            ],
        }

        for attempt in range(retries):
            try:
                async with self.session.post(
                    self.rpc_url,
                    json=payload
                ) as resp:

                    if resp.status == 429:
                        wait_time = min(2 ** attempt, 10)
                        print(
                            f"[RPC] Limite Helius atteinte (429). "
                            f"Attente {wait_time}s..."
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    resp.raise_for_status()
                    data = await resp.json()

                    if data.get("error"):
                        raise RuntimeError(
                            f"RPC error: {data['error']}"
                        )

                    if data.get("result") is not None:
                        return data["result"]

            except aiohttp.ClientError as e:
                wait_time = min(2 ** attempt, 10)
                print(
                    f"[RPC] Erreur réseau: {e}. "
                    f"Nouvelle tentative dans {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

        return None
    