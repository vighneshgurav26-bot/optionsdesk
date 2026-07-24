"""NSE public option-chain provider (no broker login required).

nseindia.com hands out data only after you've picked up a session cookie from
the HTML page first, and it rate-limits aggressively. We warm a session, back
off on 401/403, and cache for the snapshot interval. Cloud IPs (including
GitHub-hosted runners) are frequently blocked outright — if you see repeated
403s, run the desk somewhere with an Indian residential/VPS IP, or switch
data.provider to "kite".
"""
from __future__ import annotations

import datetime as dt
import time

import requests

BASE = "https://www.nseindia.com"
INDEX_URL = BASE + "/api/option-chain-indices?symbol={sym}"
EQ_URL = BASE + "/api/option-chain-equities?symbol={sym}"
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/option-chain",
    "Connection": "keep-alive",
}


class NSEProvider:
    name = "nse"

    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self._warmed = 0.0

    def _warm(self, force: bool = False) -> None:
        if not force and time.time() - self._warmed < 240:
            return
        try:
            self.s.get(BASE, timeout=self.timeout)
            self.s.get(BASE + "/option-chain", timeout=self.timeout)
            self._warmed = time.time()
        except requests.RequestException:
            pass

    def _get(self, url: str) -> dict | None:
        for attempt in range(3):
            self._warm(force=attempt > 0)
            try:
                r = self.s.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (401, 403, 429):
                    time.sleep(1.5 * (attempt + 1))
                    continue
            except (requests.RequestException, ValueError):
                time.sleep(1.0 * (attempt + 1))
        return None

    def raw_chain(self, symbol: str) -> dict | None:
        symbol = symbol.upper()
        url = (INDEX_URL if symbol in INDICES else EQ_URL).format(sym=symbol)
        return self._get(url)

    def chain(self, symbol: str) -> dict | None:
        """Normalised chain: {symbol, spot, fetched_at, expiries, rows[]}."""
        raw = self.raw_chain(symbol)
        if not raw or "records" not in raw:
            return None
        rec = raw["records"]
        spot = float(rec.get("underlyingValue") or 0.0)
        if spot <= 0:
            return None

        expiries = []
        for e in rec.get("expiryDates", []):
            try:
                expiries.append(dt.datetime.strptime(e, "%d-%b-%Y").date())
            except ValueError:
                continue
        expiries.sort()

        rows = []
        for item in rec.get("data", []):
            try:
                exp = dt.datetime.strptime(item["expiryDate"], "%d-%b-%Y").date()
            except (KeyError, ValueError):
                continue
            strike = float(item.get("strikePrice") or 0)
            for opt_type, key in (("CE", "CE"), ("PE", "PE")):
                leg = item.get(key)
                if not leg:
                    continue
                ltp = float(leg.get("lastPrice") or 0.0)
                bid = float(leg.get("bidprice") or 0.0)
                ask = float(leg.get("askPrice") or 0.0)
                if ltp <= 0 and bid <= 0:
                    continue
                rows.append({
                    "symbol": symbol,
                    "expiry": exp.isoformat(),
                    "strike": strike,
                    "opt_type": opt_type,
                    "ltp": ltp,
                    "bid": bid,
                    "ask": ask,
                    "bid_qty": float(leg.get("bidQty") or 0.0),
                    "ask_qty": float(leg.get("askQty") or 0.0),
                    "total_bid_qty": 0.0,   # public feed shows top of book only
                    "total_ask_qty": 0.0,
                    "oi": float(leg.get("openInterest") or 0.0),
                    "oi_change": float(leg.get("changeinOpenInterest") or 0.0),
                    "volume": float(leg.get("totalTradedVolume") or 0.0),
                    "nse_iv": float(leg.get("impliedVolatility") or 0.0) / 100.0,
                    "tradingsymbol": f"{symbol}{exp:%y%b}".upper()
                                     + f"{int(strike)}{opt_type}",
                    "lot_size": 0,
                })

        if not rows:
            return None
        return {
            "symbol": symbol,
            "spot": spot,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "expiries": [e.isoformat() for e in expiries],
            "rows": rows,
            "source": "nse",
        }

    def india_vix(self) -> float | None:
        data = self._get(BASE + "/api/allIndices")
        if not data:
            return None
        for idx in data.get("data", []):
            if "VIX" in str(idx.get("index", "")).upper():
                try:
                    return float(idx.get("last"))
                except (TypeError, ValueError):
                    return None
        return None
