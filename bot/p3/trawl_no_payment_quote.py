"""Public, unauthenticated, NONPAYING Trawl quote discovery.

Send POST /scan with NO X-PAYMENT / no wallet / no x402 client / no
credentials. By documented contract HTTP 402 returns a firm quote and
DOES NOT start a scan. HTTP 202 or any job_id is an unexpected condition
and must be treated as a fatal, unapproved operation. Never pay automatically.
"""
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HOST="https://trawl.run/scan"
PRESETS=("raydium-launchpad","raydium-cpmm")
EPOCH_WINDOWS=((1058,1058),(1058,1063))


def _public_quote_fields(data):
    """Read economic metadata ONLY, never emit x402 payment data or URLs."""
    if type(data) is not dict:
        raise ValueError("trawl_quote_JSON_object_required")
    if data.get("job_id") or data.get("status") in ("running","done","queued"):
        raise ValueError("unapproved_trawl_job_in_quote_response")
    fields=("price","price_usd","amount_usd","total_usd","total",
            "tb","terabytes","archive_tb","estimated_tb","estimated_jobs",
            "jobs","estimated_time_hours","duration_hours","currency")
    out={}
    for field in fields:
        v=data.get(field)
        if type(v) in (str,int,float) and len(str(v))<=75:
            out[field]=v
    q=data.get("quote")
    if type(q) is dict:
        for field in fields:
            v=q.get(field)
            if type(v) in (str,int,float) and len(str(v))<=75:
                out["quote_"+field]=v
    elif type(q) in (str,int,float) and len(str(q))<=75:
        out["quote"]=q
    return out


def quote_nonpaying(preset,start,end,*,opener=urlopen):
    if preset not in PRESETS or type(start) is not int or type(end) is not int or not 0<=start<=end<=1200 or end-start>7:
        raise ValueError("fixed_nonpaying_preset_or_epoch_invalid")
    data=json.dumps(dict(preset=preset,start_epoch=start,end_epoch=end)).encode()
    request=Request(HOST,data=data,method="POST",
                    headers={"Content-Type":"application/json","Accept":"application/json"})
    # Never add authorization or payment header. This cannot start a scan
    # under the documented x402 API contract.
    if request.has_header("X-payment") or request.has_header("Authorization"):
        raise ValueError("unapproved_auth_header")
    try:
        response=opener(request,timeout=12)
    except HTTPError as e:
        if e.code != 402:
            return dict(preset=preset,epoch_start=start,epoch_end=end,
                        quote_returned=False,http_status=e.code,
                        no_payment_sent=True,no_job_started_by_client=True)
        payload=e.read(30000)
        if len(payload)>=30000:
            raise ValueError("quote_response_oversized")
        reply=json.loads(payload)
        return dict(preset=preset,epoch_start=start,epoch_end=end,
                    quote_returned=True,http_status=402,
                    public_quote_fields=_public_quote_fields(reply),
                    quote_response_top_level_keys=[
                        k for k in reply.keys() if k in ("quote","price","network","total")],
                    no_payment_sent=True,no_job_started_by_client=True)
    else:
        status=getattr(response,"status",None)
        try:response.close()
        except Exception:pass
        # 2xx may create a paid job: this is not a valid quote response.
        raise ValueError("trawl_unexpected_non402_"+str(status))


def main():
    reports=[]
    for preset in PRESETS:
        for start,end in EPOCH_WINDOWS:
            try:
                report=quote_nonpaying(preset,start,end)
            except Exception as error:
                # Avoid outputting raw HTTP error URLs or provider body.
                report=dict(preset=preset,epoch_start=start,epoch_end=end,
                    quote_returned=False,safe_error_class=type(error).__name__,
                    no_payment_sent=True,no_job_started_by_client=True)
            reports.append(report)
            print(json.dumps(report,sort_keys=True),flush=True)
    print(json.dumps(dict(schema="rugger-trawl-nonpaying-quote-v1",
        no_payment_sent=True,no_scan_ordered=True,
        quotes_received=sum(x["quote_returned"] for x in reports),
        requests=len(reports),economic_edge_validated=False,
        live_ready_to_arm=False),sort_keys=True))
    return 0 if any(x["quote_returned"] for x in reports) else 2


if __name__=="__main__":
    sys.exit(main())
