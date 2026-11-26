"""Public market data access with provenance.

Every downloaded file is cached under ``research/r05/data/`` (git-ignored), verified against
the official ``.CHECKSUM`` file when the publisher provides one, and recorded in a manifest
(url, sha256, size, verification status, fetch time). Nothing here uses an API key.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
BINANCE_ARCHIVE = "https://data.binance.vision/data"
USER_AGENT = "r05-research/0.1 (public market data, paper only)"

_manifest_lock = threading.Lock()


class Manifest:
    """Append-only provenance log for one experiment family."""

    def __init__(self, name: str):
        self.name = name
        self.path = RESULTS_DIR / f"DATA_MANIFEST_{name}.json"
        self.entries: dict[str, dict] = {}
        if self.path.exists():
            for e in json.loads(self.path.read_text())["files"]:
                self.entries[e.get("key", e["url"])] = e

    def add(self, entry: dict) -> None:
        key = entry.get("key", entry["url"])
        with _manifest_lock:
            self.entries[key] = entry

    def save(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(self.entries.values(), key=lambda e: e.get("key", e["url"]))
        doc = {
            "manifest": self.name,
            "n_files": len(files),
            "n_checksum_verified": sum(1 for e in files if e.get("checksum") == "verified"),
            "n_missing": sum(1 for e in files if e.get("status") == "missing"),
            "files": files,
        }
        self.path.write_text(json.dumps(doc, indent=1, sort_keys=True))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _get(url: str, session: requests.Session, retries: int = 4, **kw) -> requests.Response:
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=60, headers={"User-Agent": USER_AGENT}, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code} {url}")
                time.sleep(2 ** i)
                continue
            return r
        except requests.RequestException as e:  # network hiccup: retry with backoff
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"download failed after {retries} tries: {url}: {last}")


def fetch_binance_file(rel: str, manifest: Manifest, session: requests.Session | None = None) -> Path | None:
    """Download ``rel`` (path under data.binance.vision/data) + verify official CHECKSUM.

    Returns the local path, or None if the publisher has no such file (HTTP 404, recorded).
    Raises on checksum mismatch (never silently accepted).
    """
    session = session or requests.Session()
    url = f"{BINANCE_ARCHIVE}/{rel}"
    local = DATA_DIR / "binance" / rel
    if local.exists() and url in manifest.entries and manifest.entries[url].get("status") == "ok":
        if sha256_bytes(local.read_bytes()) == manifest.entries[url]["sha256"]:
            return local
    r = _get(url, session)
    if r.status_code == 404:
        manifest.add({"url": url, "status": "missing", "http": 404})
        return None
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {url}")
    body = r.content
    digest = sha256_bytes(body)
    rc = _get(url + ".CHECKSUM", session)
    if rc.status_code == 200:
        expected = rc.text.strip().split()[0].lower()
        if expected != digest:
            raise RuntimeError(f"CHECKSUM MISMATCH {url}: {digest} != {expected}")
        check = "verified"
    else:
        check = f"unavailable_http_{rc.status_code}"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(body)
    manifest.add({
        "url": url, "status": "ok", "sha256": digest, "bytes": len(body), "checksum": check,
        "fetched_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return local


def month_range(start: str, end: str) -> list[str]:
    """Inclusive list of YYYY-MM between two YYYY-MM strings."""
    s = pd.Period(start, "M")
    e = pd.Period(end, "M")
    return [str(p) for p in pd.period_range(s, e, freq="M")]


def fetch_many(rels: list[str], manifest: Manifest, workers: int = 8) -> list[Path | None]:
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(lambda r: fetch_binance_file(r, manifest, session), rels))
    manifest.save()
    return out


KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "count", "taker_buy_base", "taker_buy_quote", "ignore"]


def _to_utc(ts: pd.Series) -> pd.DatetimeIndex:
    """Binance archive timestamps are ms until 2024-12 and µs from 2025-01 (spot)."""
    v = ts.astype("int64").to_numpy()
    v = np.where(v > 10**14, v // 1000, v)  # µs -> ms
    return pd.to_datetime(v, unit="ms", utc=True)


def read_klines_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        raw = z.read(name)
    first = raw.split(b"\n", 1)[0]
    header = 0 if first[:1].isalpha() else None
    df = pd.read_csv(io.BytesIO(raw), header=header, names=KLINE_COLS if header is None else None)
    if header == 0:
        df.columns = KLINE_COLS[: len(df.columns)]
    df.index = _to_utc(df["open_time"])
    df.index.name = "open_time"
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype(float)
    return df[["open", "high", "low", "close", "volume", "quote_volume", "count", "taker_buy_base"]]


def load_klines(market: str, symbol: str, interval: str, months: list[str], manifest: Manifest) -> pd.DataFrame:
    """market: 'spot' or 'futures/um'. Returns a de-duplicated, sorted frame."""
    rels = [f"{market}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{m}.zip" for m in months]
    paths = fetch_many(rels, manifest)
    frames = [read_klines_zip(p) for p in paths if p is not None]
    if not frames:
        raise RuntimeError(f"no kline data for {market} {symbol}")
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


def read_funding_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw))
    tcol = [c for c in df.columns if "time" in c.lower()][0]
    rcol = [c for c in df.columns if "rate" in c.lower()][0]
    out = pd.DataFrame({"rate": df[rcol].astype(float).to_numpy()}, index=_to_utc(df[tcol]))
    if "funding_interval_hours" in df.columns:
        out["interval_h"] = df["funding_interval_hours"].astype(float).to_numpy()
    out.index.name = "time"
    return out


def load_funding(symbol: str, months: list[str], manifest: Manifest) -> pd.DataFrame:
    rels = [f"futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{m}.zip" for m in months]
    paths = fetch_many(rels, manifest)
    frames = [read_funding_zip(p) for p in paths if p is not None]
    df = pd.concat(frames).sort_index()
    return df[~df.index.duplicated(keep="first")]


def json_get(url: str, manifest: Manifest, cache_name: str, params: dict | None = None,
             method: str = "GET", payload: dict | None = None, refresh: bool = False):
    """Fetch a public JSON endpoint once, cache the raw body, record its sha256."""
    local = DATA_DIR / "json" / cache_name
    if local.exists() and not refresh:
        return json.loads(local.read_text())
    s = requests.Session()
    for i in range(5):
        if method == "POST":
            r = s.post(url, json=payload, timeout=60, headers={"User-Agent": USER_AGENT})
        else:
            r = s.get(url, params=params, timeout=60, headers={"User-Agent": USER_AGENT})
        if r.status_code == 429:
            time.sleep(5 * (i + 1))
            continue
        break
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {url} {params or payload}")
    body = r.content
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(body)
    manifest.add({
        "key": f"{url}#{cache_name}",
        "url": r.url if method == "GET" else url, "request": payload if method == "POST" else params,
        "cache": cache_name, "status": "ok", "sha256": sha256_bytes(body), "bytes": len(body),
        "checksum": "none_published",
        "fetched_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return json.loads(body)
