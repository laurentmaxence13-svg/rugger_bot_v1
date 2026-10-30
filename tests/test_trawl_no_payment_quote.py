"""Simulated HTTP 402 quotes never become x402 payment or financial GO."""
import io
import json
from urllib.error import HTTPError
import pytest
from tools.trawl_no_payment_quote import quote_nonpaying,PRESETS,HOST


def make_error(code, body):
    return HTTPError(HOST,code,"simulated",{},io.BytesIO(json.dumps(body).encode()))


def test_http402_extracts_price_without_accepts_or_payment_metadata():
    inspected=[]
    def opener(request,timeout):
        inspected.append(request)
        assert request.full_url==HOST
        assert request.get_method()=="POST"
        assert timeout==12
        assert request.get_header("X-payment") is None
        assert request.get_header("Authorization") is None
        data=json.loads(request.data)
        assert data==dict(preset="raydium-launchpad",start_epoch=1058,end_epoch=1058)
        raise make_error(402,dict(quote=dict(price_usd="4.00",archive_tb="0.7"),
                   accepts=[dict(payTo="DO_NOT_SHOW",amount="NEVER_AUTHORIZE")]))
    report=quote_nonpaying("raydium-launchpad",1058,1058,opener=opener)
    assert len(inspected)==1
    assert report["http_status"]==402
    assert report["quote_returned"] is True
    assert report["public_quote_fields"]==dict(quote_price_usd="4.00",quote_archive_tb="0.7")
    assert "DO_NOT_SHOW" not in str(report)
    assert report["no_payment_sent"] is True
    assert report["no_job_started_by_client"] is True


@pytest.mark.parametrize("status",[400,403,429,500])
def test_unexpected_http_status_does_not_return_a_quote(status):
    def opener(request,timeout):
        raise make_error(status,dict(error="refused"))
    r=quote_nonpaying("raydium-cpmm",1058,1063,opener=opener)
    assert r["http_status"]==status
    assert r["quote_returned"] is False


def test_http202_rejected_to_avoid_silent_paid_scan():
    class Response:
        status=202
        def close(self):pass
    with pytest.raises(ValueError,match="unexpected_non402"):
        quote_nonpaying("raydium-launchpad",1058,1058,opener=lambda *_a,**_k:Response())


@pytest.mark.parametrize("bad_preset",["pumpfun","raydium-clmm","anything"])
def test_only_two_checked_programs(bad_preset):
    with pytest.raises(ValueError,match="fixed_nonpaying"):
        quote_nonpaying(bad_preset,1058,1058,opener=lambda *a,**k:None)


def test_no_quote_that_has_a_job_id():
    def opener(*args,**kwargs):
        raise make_error(402,dict(job_id="unexpected",quote=dict(price_usd=4)))
    with pytest.raises(ValueError,match="unapproved_trawl_job"):
        quote_nonpaying(PRESETS[0],1058,1058,opener=opener)
