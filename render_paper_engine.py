"""Rugger public-market PAPER research. No signing or financial RPC methods.

Quotes are *indicative* DexScreener SOL-pair observations. Virtual fills
include labelled hypothetical friction: they are NOT executable swap quotes.
The existing Master is evaluated independently with missing features intact,
and cannot inherit this experimental strategy's orders.
Render Free may suspend this web service and erase its ephemeral filesystem.
"""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen

SOL_MINT = "So11111111111111111111111111111111111111112"
PROFILE_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
PRICE_URL = "https://api.dexscreener.com/tokens/v1/solana/"
INITIAL_SOL = 10.0
STAKE_SOL = 0.05
BUY_FRICTION = 0.01
SELL_FRICTION = 0.01
NETWORK_FEE_SOL = 0.00001
MAX_POSITIONS = 1
MAX_ENTRIES_DAY = 20
MAX_DAILY_LOSS_SOL = 0.25
MIN_LIQUIDITY_USD = 3500.0
MAX_TRACKED = 25
POLL_SECONDS = 20
STALE_SECONDS = 90
HOLD_SECONDS = 90
STATE_PATH = Path("/tmp/rugger_master_paper_v1.json")


def now_ms():
    return time.time_ns() // 1_000_000


def finite_positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _mint(value):
    if not isinstance(value, str) or not 32 <= len(value) <= 44:
        return False
    return all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in value)


def _fetch_json(url):
    if not (url == PROFILE_URL or
            url.startswith(PRICE_URL) and len(url) < 1600 and
            all(_mint(m) for m in url[len(PRICE_URL):].split(","))):
        raise ValueError("unexpected_public_data_endpoint")
    req = Request(url, headers={"Accept": "application/json",
                                "User-Agent": "RuggerResearchPaper/1.0"})
    with urlopen(req, timeout=8) as response:
        if response.status != 200:
            raise ValueError("provider_http_error")
        raw = response.read(1200001)
    if len(raw) > 1200000:
        raise ValueError("provider_response_exceeded_limit")
    return json.loads(raw)


def select_profiles(payload, maximum=MAX_TRACKED):
    """Token profiles are promotional discovery, NOT verified launches."""
    if not isinstance(payload, list):
        raise ValueError("invalid_token_profile_response")
    selected = []
    seen = set()
    for row in payload[:250]:
        if not isinstance(row, dict) or row.get("chainId") != "solana":
            continue
        mint = row.get("tokenAddress")
        if not _mint(mint) or mint in seen or mint == SOL_MINT:
            continue
        selected.append(mint)
        seen.add(mint)
        if len(selected) >= maximum:
            break
    return selected


def select_sol_pairs(payload, allowed):
    """Only token/SOL pairs, largest displayed liquidity per mint."""
    if not isinstance(payload, list):
        raise ValueError("invalid_token_price_response")
    result = {}
    for p in payload[:1500]:
        if not isinstance(p, dict) or p.get("chainId") != "solana":
            continue
        base = p.get("baseToken") or {}
        quote = p.get("quoteToken") or {}
        mint = base.get("address")
        if mint not in allowed or quote.get("address") != SOL_MINT:
            continue
        price = finite_positive(p.get("priceNative"))
        liquidity = finite_positive((p.get("liquidity") or {}).get("usd"))
        pair = p.get("pairAddress")
        if (price is None or liquidity is None
                or not isinstance(pair, str) or not _mint(pair)):
            continue
        if liquidity < MIN_LIQUIDITY_USD:
            continue
        item = {"mint": mint, "pair": pair, "price_sol": price,
                "liquidity_usd": liquidity,
                "symbol": str(base.get("symbol") or "?")[:24],
                "dex": str(p.get("dexId") or "?")[:32],
                "source": "DexScreener indicative SOL-pair market",
                "executable": False}
        if mint not in result or result[mint]["liquidity_usd"] < liquidity:
            result[mint] = item
    return result


def _fresh_state():
    return {
        "schema": "rugger-render-public-paper-v1",
        "cash_sol": INITIAL_SOL,
        "positions": [],
        "closed": [],
        "events": [],
        "observations": {},
        "master_shadow": [],
        "candidates": [],
        "polls": 0,
        "last_success_ms": None,
        "last_poll_ms": None,
        "last_error": None,
        "day": datetime.now(timezone.utc).date().isoformat(),
        "entries_today": 0,
        "realized_today_sol": 0.0,
        "next_id": 1,
    }


def _safe_state(state):
    if not isinstance(state, dict) or state.get("schema") != "rugger-render-public-paper-v1":
        return _fresh_state()
    if (not isinstance(state.get("positions"), list) or
            not isinstance(state.get("closed"), list) or
            not isinstance(state.get("events"), list) or
            not isinstance(state.get("cash_sol"), (int, float)) or
            not math.isfinite(state["cash_sol"]) or
            state["cash_sol"] < 0):
        return _fresh_state()
    return state


class PaperState:
    """Single writer and explicit source provenance; virtual capital only."""
    def __init__(self, *, path=STATE_PATH, clock=now_ms):
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.RLock()
        self.state = _fresh_state()
        try:
            if self.path.is_file() and not self.path.is_symlink():
                self.state = _safe_state(json.loads(self.path.read_text()))
        except (OSError, ValueError):
            self.state = _fresh_state()
        self.state["events"] = self.state["events"][-120:]
        self.state["closed"] = self.state["closed"][-120:]

    def _event(self, kind, details):
        self.state["events"].append({"at_ms": self.clock(), "kind": kind,
                                     "details": details})
        self.state["events"] = self.state["events"][-120:]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(self.state, allow_nan=False, separators=(",", ":")))
        os.replace(temp, self.path)

    def snapshot(self):
        with self.lock:
            state = deepcopy(self.state)
        now = self.clock()
        age = None if state["last_success_ms"] is None else (now - state["last_success_ms"]) // 1000
        state["service"] = {
            "mode": "READ_ONLY_MASTER_PLUS_SEPARATE_EXPERIMENTAL_PAPER",
            "live_trading_enabled": False,
            "financial_order_submitted": False,
            "wallet_connected": False,
            "quotes_are_executable": False,
            "master_trades_executed": False,
            "paper_strategy": "SEPARATE_EXPERIMENT_NOT_MASTER",
            "paper_state_persistence": "EPHEMERAL_RENDER_FREE_DISK",
            "paper_total_capital_initial_sol": INITIAL_SOL,
            "last_source_age_seconds": age,
            "source_fresh": age is not None and 0 <= age <= STALE_SECONDS,
            "render_free_can_sleep": True,
            "fees_basis": "MODEL_ASSUMPTION_1PCT_PER_SIDE_PLUS_0.00001_SOL_PER_SIDE",
        }
        return state

    def error(self, code):
        with self.lock:
            self.state["last_poll_ms"] = self.clock()
            self.state["last_error"] = str(code)[:90]
            self._event("DATA_ERROR", self.state["last_error"])
            self._save()

    def on_quotes(self, quotes, *, at_ms=None, master=None):
        at_ms = self.clock() if at_ms is None else at_ms
        if not isinstance(quotes, dict) or not isinstance(at_ms, int) or at_ms <= 0:
            raise ValueError("invalid_paper_observation")
        with self.lock:
            s = self.state
            today = datetime.fromtimestamp(at_ms/1000, timezone.utc).date().isoformat()
            if today != s["day"]:
                s["day"] = today
                s["entries_today"] = 0
                s["realized_today_sol"] = 0.0
            s["polls"] += 1
            s["last_poll_ms"] = at_ms
            s["last_success_ms"] = at_ms
            s["last_error"] = None
            if master is not None:
                s["master_shadow"] = master[:5]
            s["candidates"] = list(quotes.values())[:15]
            observed = s["observations"]
            for mint, q in quotes.items():
                if not isinstance(q, dict) or not _mint(mint):
                    continue
                price = finite_positive(q.get("price_sol"))
                if price is None or not isinstance(q.get("pair"), str):
                    continue
                previous = observed.get(mint)
                samples = (int(previous.get("samples", 0)) + 1
                           if previous and previous.get("pair") == q["pair"]
                           and at_ms - previous.get("at_ms", 0) <= STALE_SECONDS*1000
                           and at_ms > previous.get("at_ms", 0) else 1)
                observed[mint] = {
                    "pair": q["pair"], "price": price,
                    "at_ms": at_ms, "samples": min(samples, 10000),
                    "liquidity_usd": q.get("liquidity_usd")}
            for mint in list(observed):
                if at_ms - observed[mint]["at_ms"] > 180000:
                    del observed[mint]
            # Close only on an observed same-pool quote, never a fabricated tick.
            for position in list(s["positions"]):
                q = quotes.get(position["mint"])
                if not q or q.get("pair") != position["pair"]:
                    continue
                p = finite_positive(q.get("price_sol"))
                if p is None:
                    continue
                gross = position["quantity"] * p
                net = max(0.0, gross * (1-SELL_FRICTION) - NETWORK_FEE_SOL)
                pnl = net - position["spent_sol"]
                age_ms = at_ms - position["opened_ms"]
                reason = ("TAKE_PROFIT" if pnl/position["spent_sol"] >= 0.08 else
                          "STOP_LOSS" if pnl/position["spent_sol"] <= -0.06 else
                          "TIME_EXIT" if age_ms >= HOLD_SECONDS*1000 else None)
                if reason:
                    s["cash_sol"] += net
                    position.update(closed_ms=at_ms, close_price_sol=p,
                                    proceeds_sol=net, pnl_sol=pnl,
                                    closed_reason=reason,
                                    execution="HYPOTHETICAL_INDICATIVE_PRICE")
                    s["positions"].remove(position)
                    s["closed"].append(position)
                    s["closed"] = s["closed"][-120:]
                    s["realized_today_sol"] += pnl
                    self._event("PAPER_SELL", {"mint":position["mint"],
                                              "reason":reason,"pnl_sol":round(pnl, 9)})
            # Entry is demonstrative research logic, NOT a Master authorization.
            if (len(s["positions"]) < MAX_POSITIONS
                    and s["entries_today"] < MAX_ENTRIES_DAY
                    and s["realized_today_sol"] > -MAX_DAILY_LOSS_SOL
                    and s["cash_sol"] >= STAKE_SOL):
                active_mints = {v["mint"] for v in s["positions"]}
                for mint, q in sorted(quotes.items(),
                                       key=lambda x:(-x[1]["liquidity_usd"],x[0])):
                    obs = observed.get(mint)
                    if (mint in active_mints or not obs or obs["samples"] < 2
                            or obs["pair"] != q.get("pair")
                            or q["liquidity_usd"] < MIN_LIQUIDITY_USD):
                        continue
                    # Reserve a fixed 0.05 SOL inclusive of hypothetical fees.
                    price = obs["price"]
                    qty = (STAKE_SOL*(1-BUY_FRICTION)-NETWORK_FEE_SOL)/price
                    if not math.isfinite(qty) or qty <= 0:
                        continue
                    ident=s["next_id"];s["next_id"]+=1
                    pos={"id":ident,"mint":mint,"pair":obs["pair"],
                         "symbol":q.get("symbol","?"),
                         "opened_ms":at_ms,"open_price_sol":price,
                         "quantity":qty,"spent_sol":STAKE_SOL,
                         "execution":"HYPOTHETICAL_INDICATIVE_PRICE",
                         "master_decision": "NOT_A_MASTER_TRADE",
                         "liquidity_usd_at_entry":q["liquidity_usd"]}
                    s["cash_sol"] -= STAKE_SOL
                    s["positions"].append(pos)
                    s["entries_today"] += 1
                    self._event("PAPER_BUY",{"mint":mint,"spent_sol":STAKE_SOL,
                                             "strategy":"SEPARATE_EXPERIMENT"})
                    break
            self._save()


def master_diagnostics(quotes, *, clock=now_ms):
    """Invoke actual Master on incomplete public quotes: no invented features."""
    from bot.master_decision import MasterDecisionOrchestrator
    master = MasterDecisionOrchestrator()
    at = clock()
    out = []
    for mint, q in list(quotes.items())[:5]:
        frame = {"id": "public-quote-%s-%s" % (mint,at),
                 "mint": mint, "pool": q["pair"],
                 "source_kind": "DEXSCREENER_UNVERIFIED_INDICATIVE",
                 "available_at_ms": at,
                 "data_kind":"market_observation"}
        result = master.evaluate(frame, health=None, capital=None)
        if result["action"] not in ("WAIT", "NO_TRADE"):
            raise ValueError("unverified_public_quote_must_not_authorize_master")
        out.append({"mint": mint,"action":result["action"],
                    "reasons":result.get("reasons",[])[:8],
                    "policy_sha256":result.get("policy_sha256"),
                    "source_verified":False,
                    "entry_authorized":False})
    return out


def observe_public_cycle(state, *, fetch=_fetch_json, clock=now_ms):
    """One real HTTP observation cycle; all API results remain untrusted."""
    profiles=select_profiles(fetch(PROFILE_URL))
    if not profiles:
        state.error("NO_PUBLIC_SOLANA_PROFILES")
        return
    # Profiles can rotate; retaining previous candidates prevents churn from
    # stopping consecutive price observations. No future data selects entries.
    previous=state.snapshot().get("observations",{})
    tracked=list(dict.fromkeys(profiles[:15] + list(previous)[:10]))[:MAX_TRACKED]
    payload=fetch(PRICE_URL + ",".join(tracked))
    prices=select_sol_pairs(payload,set(tracked))
    if not prices:
        state.error("NO_LIQUID_SOL_PAIRS_FROM_PROVIDER")
        return
    try:
        decisions=master_diagnostics(prices,clock=clock)
    except (ImportError,ValueError,TypeError,KeyError,AttributeError) as error:
        decisions=[{"action":"MASTER_UNAVAILABLE","reason":type(error).__name__,
                    "entry_authorized":False}]
    state.on_quotes(prices, at_ms=clock(), master=decisions)


def run_public_worker(state, *, stop_event=None, sleep_seconds=POLL_SECONDS):
    stop_event=stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            observe_public_cycle(state)
        except Exception as error:
            # Never log URLs, credentials or data payloads. Only error class.
            state.error(type(error).__name__)
        stop_event.wait(sleep_seconds)
