"""Offline strict no-keys quote route: never an executed Master PAPER trade."""
from copy import deepcopy
from io import BytesIO
import json
from urllib.error import HTTPError
from unittest.mock import Mock

import pytest
from bot.p3 import real_signed_sol_exactlot_quote_probe as p


class FakeResponse:
    status=200
    def __init__(self,body,url):
        self.data=BytesIO(json.dumps(body).encode())
        self.url=url
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return None
    def geturl(self):
        return self.url
    def read(self,limit):
        assert limit==p.MAX_RESPONSE+1
        return self.data.read(limit)


class FakeOpener:
    def __init__(self,*,route=True,success=True):
        self.calls=[]
        self.route=route
        self.success=success
    def open(self,req,timeout):
        assert req.get_method()=="GET"
        assert timeout==8
        assert req.full_url.startswith(p.ORIGIN+"?")
        assert not any("key" in key.lower() for key in req.headers)
        from urllib.parse import urlparse,parse_qs
        u=parse_qs(urlparse(req.full_url).query)
        side="BUY" if u["inputMint"]==[p.SOL_MINT] else "SELL"
        assert u["slippageBps"]==[str(p.SLIPPAGE_BPS)]
        assert u["txVersion"]==["V0"]
        self.calls.append(side)
        data=dict(inputMint=u["inputMint"][0],
            outputMint=u["outputMint"][0],
            inputAmount=u["amount"][0],
            outputAmount="132000000" if side=="BUY" else "48000000",
            slippageBps=p.SLIPPAGE_BPS,
            routePlan=[dict(poolId=p.POOL if self.route else "wrong-route")])
        return FakeResponse(dict(success=self.success,data=data),req.full_url)


def test_two_indicative_quotes_are_never_master_paper_trades():
    opener=FakeOpener()
    result=p.probe(quote=lambda side,amount:p._quote(
        side,amount,opener=opener))
    assert opener.calls==["BUY","SELL"]
    assert result["buy_quote"]["input_atomic"]=="50000000"
    assert result["buy_quote"]["output_atomic"]=="132000000"
    assert result["sell_quote"]["input_atomic"]=="132000000"
    assert result["sell_quote"]["output_atomic"]=="48000000"
    assert result["provider_response"]=="CURRENT_INDICATIVE_ROUTE_PAIR_NOT_MASTER_PAPER_FILL"
    assert result["independent_exact_lot_quote_pair_present"] is True
    assert result["quote_source_clocks_and_slots_verified"] is False
    assert result["independently_executable_prices_at_original_S1"] is False
    assert result["actual_master_PAPER_buy_sell_verified"] is False
    assert result["master_net_pnl_lamports"] is None
    assert result["financial_order_submitted"] is False
    assert result["no_transaction_builder_or_wallet"] is True


def test_routing_to_other_pool_not_accepted_as_signed_launchlab_quote():
    opener=FakeOpener(route=False)
    r=p.probe(quote=lambda side,lot:p._quote(side,lot,opener=opener))
    assert opener.calls==["BUY"]
    assert r["safe_refusal_code"]=="quote_provider_not_exact_signed_launchlab_pool"
    assert r["independent_exact_lot_quote_pair_present"] is False
    assert r["master_net_pnl_lamports"] is None


def test_provider_lacks_liquidity_and_fee_proof_never_claims_profit():
    opener=FakeOpener(success=False)
    r=p.probe(quote=lambda side,lot:p._quote(side,lot,opener=opener))
    assert r["safe_refusal_code"]=="quote_provider_no_route_or_unqualified_envelope"
    assert r["financial_order_submitted"] is False
    assert r["qualified_master_economic_cycles"]==0


def test_status_403_is_a_refusal_not_an_invitation_to_purchase():
    class Refuse:
        def open(self,req,timeout):
            raise HTTPError(req.full_url,403,"refused",None,None)
    r=p.probe(quote=lambda side,lot:p._quote(side,lot,opener=Refuse()))
    assert r["safe_refusal_code"]=="quote_provider_http_403"
    assert r["provider_response"]=="CURRENT_ROUTE_NOT_VERIFIED"
    assert r["master_net_pnl_lamports"] is None


def test_default_cli_cannot_make_network_requests(monkeypatch,capsys,tmp_path):
    network=Mock(side_effect=AssertionError("no network"))
    monkeypatch.setattr(p,"probe",network)
    assert p.main(["--output-file",str(tmp_path/"quote.json")])==2
    network.assert_not_called()
    assert "NETWORK_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_quote_exact_atomic_input_must_be_numeric_not_fractional():
    with pytest.raises(ValueError,match="exact_source_lot_required"):
        p._quote("BUY",50_000_000.5)
    with pytest.raises(ValueError,match="exact_source_lot_required"):
        p._quote("SEND",50_000_000)


def test_non_route_response_fails_closed_with_no_secret_echo(monkeypatch):
    marker="SECRET_PROBE_STRING_IN_PROVIDER_BODY_NOT_TO_LOG"
    opener=FakeOpener()
    def bad_open(req,timeout):
        return FakeResponse(dict(success=True,data={"marker":marker}),req.full_url)
    opener.open=bad_open
    r=p.probe(quote=lambda side,lot:p._quote(side,lot,opener=opener))
    assert marker not in json.dumps(r)
    assert r["independent_exact_lot_quote_pair_present"] is False
    assert r["financial_order_submitted"] is False
