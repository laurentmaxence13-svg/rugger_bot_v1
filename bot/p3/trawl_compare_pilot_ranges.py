"""Compare only fixed post-consensus no-payment archive quotes and buy-page URLs.

Pre-registered window starts at Alpenglow activation epoch 1064. Latest must
come from GET /health; historical purchase price confirmed only by HTTP 402.
This script never sends X-PAYMENT and cannot order a scan.
"""
import json
import ssl
import sys
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler, HTTPRedirectHandler

from bot.p3.trawl_no_payment_quote import quote_nonpaying
from bot.p3.trawl_verify_purchase_window import _open_json, _latest_archive_epoch, HOST

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("unsafe_redirect_refused")

def run():
    opener=build_opener(ProxyHandler({}),
        HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    latest=_latest_archive_epoch(_open_json(HOST+"/health",opener))
    if latest is None or latest<1071:
        return dict(status="REFUSED_ARCHIVE_NOT_YET_AVAILABLE",
                    latest_archive_epoch=latest,no_payment_sent=True)
    # Same archived period for both programs, with a creation-only holdout
    # ending two epochs before latest. Larger archive scan doesn't imply
    # all migrations or closeouts in that same period are complete.
    options=[
        ("full_same_window_1064_1071",(1064,1071),(1064,1071)),
        ("creation_with_two_epoch_exit_tail",(1064,1069),(1064,1071)),
        ("narrower_low_cost_pilot",(1066,1069),(1066,1071)),
    ]
    quotes={}
    for label,L,C in options:
        entries=[];sum_cents=0;verified=True
        for preset,(start,end) in (("raydium-launchpad",L),
                                   ("raydium-cpmm",C)):
            q=quote_nonpaying(preset,start,end)
            raw=q.get("public_quote_fields",{}).get("quote_price")
            try:
                from decimal import Decimal
                price=Decimal(str(raw))
                cents=int(price*100)
                if price!=Decimal(cents)/100 or cents<400:
                    raise ValueError("quote_amount_invalid")
            except Exception:
                cents=0;verified=False
            if q.get("http_status")!=402 or q.get("quote_returned") is not True:
                verified=False
            entries.append(dict(program=preset,start_epoch=start,end_epoch=end,
                quote_usd=(f"{cents/100:.2f}" if cents else None),
                no_payment=True))
            sum_cents+=cents
        quotes[label]=dict(total_usd=(f"{sum_cents/100:.2f}" if verified else None),
            within_user_previously_discussed_14_98=verified and sum_cents<=1498,
            archived_period_confirmed=latest>=max(L[1],C[1]),
            individual=entries)
    return dict(schema="rugger-trawl-three-historical-pilot-price-options-v1",
        status="THREE_NO_PAYMENT_QUOTE_OPTIONS_VERIFIED",
        archive_latest_epoch=latest,
        alpenglow_consensus_boundary_epoch=1064,
        options=quotes,
        no_payment_sent=True,no_job_ordered=True,
        economic_edge_validated=False,live_ready_to_arm=False)

def main():
    try:
        out=run()
        print(json.dumps(out,sort_keys=True))
        return 0 if out["status"]=="THREE_NO_PAYMENT_QUOTE_OPTIONS_VERIFIED" else 2
    except Exception as exc:
        print(json.dumps(dict(status="REFUSED",error_class=type(exc).__name__,
            no_payment_sent=True,no_job_ordered=True)))
        return 2

if __name__=="__main__":
    sys.exit(main())
