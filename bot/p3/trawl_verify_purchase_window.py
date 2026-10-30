"""Read-only Trawl pre-purchase audit for Raydium LaunchLab and CPMM.

GET /health determines newest historical epoch actually in Old Faithful.
POST /scan WITHOUT X-PAYMENT only accepts 402 quote; no job, no purchase.
The phase-1 cohort window is selected independently of observed outcomes:
recent archived epochs after Solana consensus change (1064), with a 2-epoch
post-creation CPMM exit tail whenever the archive provides enough history.
"""
import json
import sys
import ssl
from urllib.request import Request,build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from bot.p3.trawl_no_payment_quote import quote_nonpaying

HOST="https://trawl.run"
MIN_POST_UPGRADE_EPOCH=1064

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("unexpected_redirect_not_followed")

def _open_json(url, opener):
    req=Request(url,method="GET",headers={"Accept":"application/json"})
    if req.full_url not in (HOST+"/health",):
        raise ValueError("unapproved_GET_route")
    with opener.open(req,timeout=12) as result:
        if result.status!=200 or result.geturl()!=url:
            raise ValueError("health_bad_response")
        raw=result.read(12001)
    if len(raw)>12000:
        raise ValueError("health_response_too_large")
    val=json.loads(raw)
    if type(val) is not dict:
        raise ValueError("health_JSON_object_required")
    return val

def _latest_archive_epoch(doc):
    # Only accept documented integer fields; unknown schema cannot authorize
    # a range. Quoting an unavailable epoch would be a costly error.
    for key in ("latest_epoch","newest_epoch","archive_latest_epoch",
                "archive_epoch","max_epoch","archived_epoch"):
        val=doc.get(key)
        if type(val) is int and MIN_POST_UPGRADE_EPOCH<=val<=1500:
            return val
    nested=doc.get("archive")
    if type(nested) is dict:
        return _latest_archive_epoch(nested)
    return None

def audit(*,opener=None,quote=quote_nonpaying):
    opener=opener or build_opener(ProxyHandler({}),
        HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    doc=_open_json(HOST+"/health",opener)
    latest=_latest_archive_epoch(doc)
    report=dict(schema="rugger-trawl-two-program-prepurchase-v1",
        health_http_status=200,
        health_keys=sorted(x for x in doc if type(x) is str)[:25],
        archive_latest_epoch=latest,
        post_upgraded_epoch_1064_floor=True,
        no_payment_sent=True,no_job_ordered=True,
        quote_windows=[],purchase_ready=False,
        recommendation="REFUSED_UNTIL_ARCHIVE_WINDOW_VERIFIED",
        live_ready_to_arm=False)
    if latest is None or latest<1069:
        return report
    # Pre-declared consecutive launch window (4 epochs), CPMM exit tail
    # extends another two epochs. Minimum end=1069 ensures post-1064 start.
    creation_start=latest-5
    if creation_start<MIN_POST_UPGRADE_EPOCH:
        creation_start=MIN_POST_UPGRADE_EPOCH
    creation_end=latest-2
    if creation_end<creation_start:
        return report
    price_total=0
    all_good=True
    for preset,start,end in (
        ("raydium-launchpad",creation_start,creation_end),
        ("raydium-cpmm",creation_start,latest),
    ):
        data=quote(preset,start,end)
        if data.get("http_status")!=402 or data.get("quote_returned") is not True:
            all_good=False
        q=data.get("public_quote_fields",{})
        price=q.get("quote_price") if type(q) is dict else None
        try:
            from decimal import Decimal
            d=Decimal(str(price))
            if d<0 or d>1000 or d.as_tuple().exponent < -2:
                raise ValueError("invalid_fixed_quote_price")
            cents=int(d*100)
        except Exception:
            cents=None
            all_good=False
        if cents is not None:
            price_total+=cents
        report["quote_windows"].append(dict(preset=preset,
            start_epoch=start,end_epoch=end,
            http_status=data.get("http_status"),
            price_usd=str(d) if cents is not None else None,
            no_payment_sent=True,
            no_job_started_by_client=True))
    report.update(total_usd=(f"{price_total/100:.2f}" if all_good else None),
        purchase_ready=bool(all_good and price_total<=1498),
        recommendation=(
            "TWO_JOB_PILOT_WITHIN_14_98_BUDGET" if all_good and price_total<=1498
            else "PRICE_OR_COVERAGE_REQUIRES_USER_REVIEW"),
        creation_outcome_window_includes_two_extra_CPmm_epochs=True,
        not_proof_of_complete_outcomes=True,
        not_guaranteed_to_have_50_independent_creators=True)
    return report

def main():
    try:
        val=audit()
        print(json.dumps(val,sort_keys=True))
        return 0 if val["purchase_ready"] else 2
    except Exception as e:
        # Do not expose network headers or payment details.
        print(json.dumps(dict(schema="rugger-trawl-two-program-prepurchase-v1",
            status="REFUSED",
            safe_error=type(e).__name__,
            no_payment_sent=True,no_job_ordered=True,
            purchase_ready=False,live_ready_to_arm=False)))
        return 2

if __name__=="__main__":
    sys.exit(main())
