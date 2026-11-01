"""Offline safety tests for the deployed Render public-price PAPER experiment."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from bot.ops import render_paper_engine as bot

MINT = "BuTkXR6hhPrNgyH1ZJchsbTimbFoNCm6smkM3yLTbonk"
PAIR = "EUcMrcmVJPLyeH9xw7NSGsdHyzLTVywvNNieP4FcYq2X"
OTHER = "xvyZPSHvRDQfba5t5MJaNqDdifoAoXD8QgxDcg9bonk"


def q(mint=MINT, pair=PAIR, price=0.0001):
    return dict(mint=mint,pair=pair,price_sol=price,liquidity_usd=10000.0,
                dex="raydium",symbol="TEST",executable=False)


def test_public_source_is_promotion_not_verified_creation():
    profiles=[{"chainId":"ethereum","tokenAddress":MINT},
              {"chainId":"solana","tokenAddress":MINT},
              {"chainId":"solana","tokenAddress":MINT},
              {"chainId":"solana","tokenAddress":"invalid"}]
    assert bot.select_profiles(profiles)==[MINT]
    with pytest.raises(ValueError,match="invalid_token_profile"):
        bot.select_profiles({"fake":"result"})


def test_sol_quote_selection_requires_exact_identity_and_liquidity():
    raw=[
        dict(chainId="solana",baseToken={"address":MINT,"symbol":"M"},
             quoteToken={"address":bot.SOL_MINT},priceNative="0.0001",
             liquidity={"usd":11000},pairAddress=PAIR,dexId="raydium"),
        dict(chainId="solana",baseToken={"address":MINT},
             quoteToken={"address":"other-quote"},priceNative="2",
             liquidity={"usd":900000},pairAddress=OTHER),
        dict(chainId="solana",baseToken={"address":MINT},
             quoteToken={"address":bot.SOL_MINT},priceNative="nan",
             liquidity={"usd":900000},pairAddress=OTHER)]
    result=bot.select_sol_pairs(raw,{MINT})
    assert result[MINT]["pair"]==PAIR
    assert result[MINT]["price_sol"]==0.0001
    assert result[MINT]["executable"] is False


def test_real_price_paper_cycle_entry_exit_and_replay(tmp_path):
    now=[1730419200000]
    db=tmp_path/"research.json"
    book=bot.PaperState(path=db,clock=lambda:now[0])
    quote={MINT:q()}
    book.on_quotes(quote,at_ms=now[0],master=[{"action":"WAIT"}])
    assert book.snapshot()["positions"]==[]
    assert book.snapshot()["cash_sol"]==10
    now[0]+=20_000
    book.on_quotes(quote,at_ms=now[0])
    state=book.snapshot()
    assert len(state["positions"])==1
    assert state["cash_sol"]==9.95
    assert state["positions"][0]["master_decision"]=="NOT_A_MASTER_TRADE"
    # No price -> no invented exit or fabricated profit.
    now[0]+=100_000
    book.on_quotes({},at_ms=now[0])
    assert len(book.snapshot()["closed"])==0
    assert len(book.snapshot()["positions"])==1
    # Same-mint and pair observed -> deterministic TIME_EXIT.
    now[0]+=20_000
    book.on_quotes({MINT:q(price=0.0001)},at_ms=now[0])
    done=book.snapshot()
    assert done["positions"]==[]
    assert len(done["closed"])==1
    assert done["closed"][0]["closed_reason"]=="TIME_EXIT"
    assert done["closed"][0]["pnl_sol"] < 0
    assert len([e for e in done["events"] if e["kind"]=="PAPER_BUY"])==1
    assert len([e for e in done["events"] if e["kind"]=="PAPER_SELL"])==1
    assert done["service"]["financial_order_submitted"] is False
    assert done["service"]["master_trades_executed"] is False
    # Local on-disk restoration is NOT Render durable storage.
    loaded=bot.PaperState(path=db,clock=lambda:now[0]).snapshot()
    assert loaded["cash_sol"]==done["cash_sol"]
    assert len(loaded["closed"])==1


def test_exit_requires_exact_same_pool_observation(tmp_path):
    now=[1730419200000]
    book=bot.PaperState(path=tmp_path/"book.json",clock=lambda:now[0])
    book.on_quotes({MINT:q()},at_ms=now[0])
    now[0]+=20000
    book.on_quotes({MINT:q()},at_ms=now[0])
    assert book.snapshot()["positions"]
    now[0]+=100000
    book.on_quotes({MINT:q(pair=OTHER,price=0.0002)},at_ms=now[0])
    assert len(book.snapshot()["positions"])==1
    assert book.snapshot()["closed"]==[]


def test_tampered_or_missing_prices_never_create_a_trade(tmp_path):
    now=[1730419200000]
    book=bot.PaperState(path=tmp_path/"book.json",clock=lambda:now[0])
    for n in range(3):
        now[0]+=20000
        item=q(price=float("nan")) if n==1 else q(price=-1)
        book.on_quotes({MINT:item},at_ms=now[0])
    assert book.snapshot()["positions"]==[]
    assert book.snapshot()["cash_sol"]==10.0
    assert bot.finite_positive("inf") is None
    assert bot.finite_positive(0) is None


def test_master_fails_closed_without_verified_features():
    out=bot.master_diagnostics({MINT:q()},clock=lambda:1730419200000)
    assert len(out)==1
    assert out[0]["action"] in ("WAIT","NO_TRADE")
    assert out[0]["entry_authorized"] is False
    assert out[0]["source_verified"] is False


def test_observer_uses_exact_public_apis_and_does_not_send_transactions(tmp_path):
    now=[1730419200000]
    book=bot.PaperState(path=tmp_path/"book.json",clock=lambda:now[0])
    requests=[]
    def fetch(url):
        requests.append(url)
        if url==bot.PROFILE_URL:
            return [{"chainId":"solana","tokenAddress":MINT}]
        if url.startswith(bot.PRICE_URL):
            return [dict(chainId="solana",baseToken={"address":MINT,"symbol":"M"},
                quoteToken={"address":bot.SOL_MINT},priceNative="0.0001",
                liquidity={"usd":11000},pairAddress=PAIR,dexId="raydium")]
        raise AssertionError("not an allowed endpoint")
    bot.observe_public_cycle(book,fetch=fetch,clock=lambda:now[0])
    now[0]+=20000
    bot.observe_public_cycle(book,fetch=fetch,clock=lambda:now[0])
    assert requests==[bot.PROFILE_URL,bot.PRICE_URL+MINT,bot.PRICE_URL+MINT]
    assert len(book.snapshot()["positions"])==1
    assert book.snapshot()["master_shadow"][0]["entry_authorized"] is False
    assert book.snapshot()["service"]["financial_order_submitted"] is False


def test_live_send_disabled_in_service():
    from bot.ops.render_readonly_service import Observer
    assert Observer(env={}).snapshot()["live_trading_enabled"] is False


def test_open_position_can_sell_when_discovery_or_group_quotes_fail(tmp_path):
    """Existing inventory is always checked first, even under provider churn."""
    now=[1730419200000]
    book=bot.PaperState(path=tmp_path/"fallback.json",clock=lambda:now[0])
    raw=[dict(chainId="solana",baseToken={"address":MINT,"symbol":"M"},
              quoteToken={"address":bot.SOL_MINT},priceNative="0.0001",
              liquidity={"usd":11000},pairAddress=PAIR,dexId="raydium")]
    calls=[]
    def fetch(url):
        calls.append(url)
        if url==bot.PROFILE_URL:return [{"chainId":"solana","tokenAddress":MINT}]
        if url.startswith(bot.PAIR_FALLBACK_URL):return raw
        if url.startswith(bot.PRICE_URL) and len(calls)<=3:return raw
        if url.startswith(bot.PRICE_URL):raise TimeoutError("market grouped endpoint unavailable")
        raise AssertionError("unexpected endpoint")
    bot.observe_public_cycle(book,fetch=fetch,clock=lambda:now[0])
    now[0]+=20000
    bot.observe_public_cycle(book,fetch=fetch,clock=lambda:now[0])
    assert len(book.snapshot()["positions"])==1
    now[0]+=100000
    bot.observe_public_cycle(book,fetch=fetch,clock=lambda:now[0])
    state=book.snapshot()
    assert len(state["closed"])==1
    assert len(state["positions"])==0
    assert state["closed"][0]["closed_reason"]=="TIME_EXIT"
    assert bot.PAIR_FALLBACK_URL+MINT in calls
    assert state["service"]["financial_order_submitted"] is False
