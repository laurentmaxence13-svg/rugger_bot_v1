"""Read-only LaunchLab curve quotes from verified on-chain account state.

Supports constant-product (0), fixed-price (1), and linear (2) curves.
No synthetic quotes are returned when pool/config/FX data is unavailable.
"""
import base64
import math
import struct
import time

import aiohttp

from bot.analyser.paper_trader import MarketQuote

RPC_URL = 'https://api.mainnet-beta.solana.com'
LAUNCHLAB = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
SOL = 'So11111111111111111111111111111111111111112'
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_fx_cache = {'value': None, 'at': 0.0}
_diagnostic_cache = {}

def _diag(mint, reason):
    key = (mint, reason)
    now = time.monotonic()
    if now - _diagnostic_cache.get(key, -1e10) >= 120:
        _diagnostic_cache[key] = now
        print(f'[ONCHAIN] {mint[:12]} -> {reason}', flush=True)



def b58encode(data):
    n = int.from_bytes(data, 'big')
    chars = ''
    while n:
        n, r = divmod(n, 58)
        chars = _BASE58[r] + chars
    return '1' * (len(data) - len(data.lstrip(b'\0'))) + chars


def decode_pool(data, expected_mint):
    """Offsets follow Raydium SDK V2 LaunchpadPool layout (8-byte discriminator)."""
    if len(data) < 269:
        return None
    status, decimals_a, decimals_b = data[17], data[18], data[19]
    if status not in (0, 1, 2) or decimals_a > 18 or decimals_b > 18:
        return None
    supply, total_sell, virtual_a, virtual_b, real_a, real_b = struct.unpack_from('<6Q', data, 21)
    config = b58encode(data[141:173])
    mint_a = b58encode(data[205:237])
    mint_b = b58encode(data[237:269])
    if mint_a != expected_mint or not config or not mint_b or not virtual_a or not virtual_b:
        return None
    if not supply or not total_sell or real_a > supply or real_b > 10**18:
        return None
    return dict(status=status, config=config, mint_b=mint_b, decimals_a=decimals_a,
                decimals_b=decimals_b, virtual_a=virtual_a, virtual_b=virtual_b,
                real_a=real_a, real_b=real_b)


def price_in_quote(pool, curve_type):
    if curve_type == 0:
        # Raydium SDK LaunchConstantProductCurve.getPoolPrice: virtualA - realA.
        denominator = pool['virtual_a'] - pool['real_a']
        numerator = pool['virtual_b'] + pool['real_b']
    elif curve_type == 1:
        denominator = pool['virtual_a']
        numerator = pool['virtual_b']
    elif curve_type == 2:
        # Raydium SDK LinearPriceCurve.getPoolPrice (Q64 fixed point).
        denominator = 1 << 64
        numerator = pool['virtual_a'] * pool['real_a']
    else:
        return None
    if denominator <= 0 or numerator <= 0:
        return None
    price = numerator / denominator * 10 ** (pool['decimals_a'] - pool['decimals_b'])
    return price if math.isfinite(price) and price > 0 else None


async def _account(session, address):
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'getAccountInfo',
               'params': [address, {'encoding': 'base64', 'commitment': 'confirmed'}]}
    try:
        async with session.post(RPC_URL, json=payload,
                                timeout=aiohttp.ClientTimeout(total=5)) as response:
            if response.status != 200:
                return None
            result = await response.json(content_type=None)
        value = (result.get('result') or {}).get('value')
        if not isinstance(value, dict):
            return None
        data = value.get('data')
        if not isinstance(data, list) or len(data) != 2 or data[1] != 'base64':
            return None
        return value.get('owner'), base64.b64decode(data[0], validate=True)
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
        return None


async def _sol_usd(session):
    if _fx_cache['value'] and time.monotonic() - _fx_cache['at'] < 60:
        return _fx_cache['value']
    try:
        async with session.get('https://api.dexscreener.com/token-pairs/v1/solana/' + SOL,
                               timeout=aiohttp.ClientTimeout(total=5)) as response:
            response.raise_for_status()
            pairs = await response.json(content_type=None)
        candidates = [p for p in pairs if isinstance(p, dict) and
                      p.get('baseToken', {}).get('address') == SOL and
                      float(p.get('priceUsd') or 0) > 0 and
                      float((p.get('liquidity') or {}).get('usd') or 0) >= 100000]
        if candidates:
            best = max(candidates, key=lambda p: float(p['liquidity']['usd']))
            value = float(best['priceUsd'])
            if math.isfinite(value) and 1 < value < 100000:
                _fx_cache.update(value=value, at=time.monotonic())
                return value
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, KeyError):
        pass
    return None


async def fetch_onchain_quote(session, mint, pool_address):
    if not pool_address:
        return None
    pool_account = await _account(session, pool_address)
    if not pool_account or pool_account[0] != LAUNCHLAB:
        _diag(mint, 'POOL_RPC_INDISPONIBLE_OU_OWNER_INVALIDE')
        return None
    pool = decode_pool(pool_account[1], mint)
    if not pool:
        _diag(mint, 'POOL_LAYOUT_OU_MINT_INVALIDE')
        return None
    if pool['status'] != 0:
        # 1 = funding complete, 2 = migrated; use post-migration market quote.
        _diag(mint, f"POOL_STATUS_{pool['status']}_FALLBACK_MARCHE")
        return None
    config_account = await _account(session, pool['config'])
    if not config_account or config_account[0] != LAUNCHLAB or len(config_account[1]) < 17:
        _diag(mint, 'CONFIG_RPC_INDISPONIBLE_OU_INVALIDE')
        return None
    curve_type = config_account[1][16]
    spot = price_in_quote(pool, curve_type)
    if spot is None:
        _diag(mint, f'COURBE_{curve_type}_PRIX_INVALIDE')
        return None
    if pool['mint_b'] == USDC:
        usd_rate = 1.0
    elif pool['mint_b'] == SOL:
        usd_rate = await _sol_usd(session)
    else:
        return None  # Unknown quote currency: do not fabricate USD.
    if usd_rate is None:
        _diag(mint, 'TAUX_SOL_USD_INDISPONIBLE')
        return None
    price = spot * usd_rate
    # LaunchLab is a bonding curve, not a DEX LP. real_b is funding already
    # committed to the curve; calling it DEX 'liquidity' made the strategy
    # compare two different concepts. Preserve it explicitly as funding_usd.
    funding_usd = pool['real_b'] / 10 ** pool['decimals_b'] * usd_rate
    if not math.isfinite(price) or price <= 0:
        return None
    return MarketQuote(
        liquidity_usd=funding_usd, price_usd=price, pair_address=pool_address,
        quote_source='launchlab_curve', funding_usd=funding_usd,
    )
