"""One bounded no-key Raydium quote-only route probe for a REAL signed SOL creator.

This is deliberately NOT a Master PAPER fill, nor an admission of historical
S1 price availability. Two GET /compute/swap-base-in only. No wallet,
transaction building, signing, simulator, paid provider or send method.
A provider's current response is indicative; unknown source slot, fees,
liquidity impact, state transition, and historical clocks remain unqualified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from bot.analyser.artifacts import atomic_write_json
from bot.p3.quotes import SOL_MINT

SCHEMA="rugger-independent-quote-probe-real-signed-sol-mint-v1"
ORIGIN="https://transaction-v1.raydium.io/compute/swap-base-in"
MINT="ChWZ8yNvMh31yHtkZh3fSjWZaQiv62bHr1WPnUPLvuLF"
POOL="EBA8nnnHuFRMHd3Ac9HMMCNTi52E3GXT7HDreXwvhnCu"
SOURCE_CREATION_SIGNATURE="5qqLenzDgNbLkuN482pPEzoZLyygQYsdLzdMZ2cuKqbpXyXRbXZCASRGw2gWNK91cpBZgorjThhJAhiCtwJk6hUk"
SOURCE_CREATION_SLOT=464432476
BUY_LOT_LAMPORTS=50_000_000
SLIPPAGE_BPS=50
MAX_RESPONSE=150_000
MAX_CALLS=2

class RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("quote_redirect_forbidden")


def _digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _quote(side,input_atomic,*,opener=None):
    if side not in ("BUY","SELL") or type(input_atomic) is not int or not 1<=input_atomic<=10**18:
        raise ValueError("exact_source_lot_required")
    src,dst=(SOL_MINT,MINT) if side=="BUY" else (MINT,SOL_MINT)
    params=dict(inputMint=src,outputMint=dst,amount=str(input_atomic),
                slippageBps=str(SLIPPAGE_BPS),txVersion="V0")
    url=ORIGIN+"?"+urlencode(params)
    opener=opener or build_opener(ProxyHandler({}),HTTPSHandler(),RefuseRedirect())
    request=Request(url,method="GET",headers={
        "Accept":"application/json",
        "User-Agent":"RuggerSignedSourceReadOnlyQuote/1.0"})
    try:
        with opener.open(request,timeout=8) as response:
            if response.status!=200 or response.geturl()!=url:
                raise ValueError("quote_http_status_or_redirect_refused")
            raw=response.read(MAX_RESPONSE+1)
    except HTTPError as error:
        # Never print provider error content or URL.
        if error.code in (401,403,404,429,503):
            raise ValueError("quote_provider_http_"+str(error.code)) from None
        raise ValueError("quote_http_status_or_redirect_refused") from None
    except (URLError,OSError,TimeoutError):
        raise ValueError("quote_provider_network_unavailable") from None
    if len(raw)>MAX_RESPONSE:
        raise ValueError("quote_provider_response_too_large")
    try:
        payload=json.loads(raw)
    except (UnicodeDecodeError,ValueError):
        raise ValueError("quote_provider_json_invalid") from None
    if (type(payload) is not dict or payload.get("success") is not True
            or type(payload.get("data")) is not dict):
        raise ValueError("quote_provider_no_route_or_unqualified_envelope")
    quote=payload["data"]
    if (quote.get("inputMint")!=src or quote.get("outputMint")!=dst
            or str(quote.get("inputAmount"))!=str(input_atomic)
            or str(quote.get("slippageBps"))!=str(SLIPPAGE_BPS)):
        raise ValueError("quote_provider_identity_lot_or_slippage_mismatch")
    amount=quote.get("outputAmount")
    if (type(amount) is not str or not amount.isascii() or not amount.isdigit()
            or not 1<=int(amount)<=10**18):
        raise ValueError("quote_provider_output_not_exact_atomic")
    route=quote.get("routePlan")
    if (type(route) is not list or not route
            or any(type(item) is not dict for item in route)):
        raise ValueError("quote_provider_route_missing")
    pools=[item.get("poolId") for item in route]
    if len(route)!=1 or pools!=[POOL]:
        raise ValueError("quote_provider_not_exact_signed_launchlab_pool")
    return dict(side=side,input_mint=src,output_mint=dst,
        input_atomic=str(input_atomic),output_atomic=amount,
        requested_slippage_bps=SLIPPAGE_BPS,
        source_quote_sha256=_digest(payload),
        received_at_utc_ms=time.time_ns()//1_000_000,
        provider_produced_at_ms=None,provider_source_slot=None,
        provider_route_pool=POOL,
        independent_quote_indicative_only=True,
        hypothetical_lot_was_never_executed=True,
        fully_costed_trade=False,actual_fill=False)


def probe(*,quote=_quote):
    result=dict(schema=SCHEMA,source="FREE_RAYDIUM_READONLY_COMPUTE_QUOTE",
        verified_signed_creation_signature=SOURCE_CREATION_SIGNATURE,
        signed_creation_slot=SOURCE_CREATION_SLOT,mint=MINT,pool=POOL,
        max_no_key_requests=MAX_CALLS,
        buy_lot_lamports=BUY_LOT_LAMPORTS,
        provider_response="UNAVAILABLE_OR_UNQUALIFIED",
        buy_quote=None,sell_quote=None,
        independent_exact_lot_quote_pair_present=False,
        quote_source_clocks_and_slots_verified=False,
        actual_master_PAPER_entry_qualified=False,
        actual_master_PAPER_buy_sell_verified=False,
        independently_executable_prices_at_original_S1=False,
        qualified_master_economic_cycles=0,master_net_pnl_lamports=None,
        financial_order_submitted=False,live_trading_enabled=False,
        no_transaction_builder_or_wallet=True)
    calls=0
    try:
        buy=quote("BUY",BUY_LOT_LAMPORTS)
        calls+=1
        result["buy_quote"]=buy
        sell=quote("SELL",int(buy["output_atomic"]))
        calls+=1
        result["sell_quote"]=sell
        result["independent_exact_lot_quote_pair_present"]=True
        result["provider_response"]="CURRENT_INDICATIVE_ROUTE_PAIR_NOT_MASTER_PAPER_FILL"
    except Exception as error:
        # Fixed categorical refusal only, no raw provider payload, quote
        # response body, address-bearing URL, or exception representation.
        known=frozenset(("exact_source_lot_required","quote_redirect_forbidden",
          "quote_http_status_or_redirect_refused","quote_provider_http_401",
          "quote_provider_http_403","quote_provider_http_404",
          "quote_provider_http_429","quote_provider_http_503",
          "quote_provider_network_unavailable",
          "quote_provider_response_too_large","quote_provider_json_invalid",
          "quote_provider_no_route_or_unqualified_envelope",
          "quote_provider_identity_lot_or_slippage_mismatch",
          "quote_provider_output_not_exact_atomic",
          "quote_provider_route_missing",
          "quote_provider_not_exact_signed_launchlab_pool"))
        result["safe_refusal_code"]=str(error) if type(error) is ValueError and str(error) in known else "OTHER_"+type(error).__name__
        result["provider_response"]="CURRENT_ROUTE_NOT_VERIFIED"
    result["requests_successfully_returned"]=calls
    # No route quote is equivalent to a verified executable fill; a
    # hypothetical buy changes reserves and was never actually placed.
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--output-file",type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.network:
        print("RAYDIUM_READONLY_QUOTE_REFUSED:EXPLICIT_NETWORK_OPT_IN_REQUIRED")
        return 2
    if args.output_file.exists() or args.output_file.is_symlink():
        print("RAYDIUM_READONLY_QUOTE_REFUSED:NEW_OUTPUT_FILE_REQUIRED")
        return 2
    result=probe()
    atomic_write_json(args.output_file,result,sort_keys=True,allow_nan=False)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
