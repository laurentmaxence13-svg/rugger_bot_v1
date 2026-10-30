"""Verify public Trawl checkout URLs and preset IDs using GET only.

No x402 payment, no POST scan and no wallet or authentication in this tool.
No inference that the page pre-populates the dates; user MUST check
start_epoch=1064 and end_epoch=1071 before manually paying.
"""
import json
import ssl
import sys
from urllib.request import Request,build_opener,HTTPSHandler,ProxyHandler,HTTPRedirectHandler

HOST="https://trawl.run"
TARGETS=(
    ("raydium-launchpad","LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"),
    ("raydium-cpmm","CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"),
)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("no_payment_checkout_redirect_refused")

def run():
    opener=build_opener(ProxyHandler({}),
        HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    rows=[]
    for slug,program in TARGETS:
        url=HOST+"/order?preset="+slug
        r=opener.open(Request(url,method="GET"),timeout=12)
        with r:
            status=r.status
            body=r.read(500_001)
        if len(body)>500000:
            raise ValueError("checkout_body_oversized")
        decoded=body.decode("utf-8",errors="replace")
        page_ok=status==200 and "Get a price" in decoded
        preset_url=HOST+"/presets/"+slug
        r=opener.open(Request(preset_url,method="GET"),timeout=12)
        with r:
            preset_status=r.status
            preset_raw=r.read(800_001)
        if len(preset_raw)>800000:
            raise ValueError("preset_body_oversized")
        preset_json=json.loads(preset_raw)
        if type(preset_json) is not dict:
            raise ValueError("unexpected_preset_JSON")
        # Program ID may be inside nested filter/IDL. Exact 44-character
        # base58 string must be present in JSON rather than guessed.
        program_confirmed=program in json.dumps(preset_json,separators=(",",":"))
        rows.append(dict(
            preset=slug,checkout_url=url,
            checkout_HTTP_status=status,checkout_page_has_quote_action=page_ok,
            preset_HTTP_status=preset_status,program_match=program_confirmed,
            program_id=program,no_payment_sent=True))
    return dict(schema="rugger-trawl-two-verified-checkout-links-v1",
        links=rows,all_ok=all(r["checkout_page_has_quote_action"]
            and r["preset_HTTP_status"]==200 and r["program_match"] for r in rows),
        start_epoch_to_set_manually=1064,
        end_epoch_to_set_manually=1071,
        no_payment_sent=True,no_job_ordered=True)
if __name__=="__main__":
    try:
        out=run();print(json.dumps(out,sort_keys=True));sys.exit(0 if out["all_ok"] else 2)
    except Exception as e:
        print(json.dumps(dict(status="REFUSED",error_class=type(e).__name__,
            no_payment_sent=True,no_job_ordered=True)))
        sys.exit(2)
