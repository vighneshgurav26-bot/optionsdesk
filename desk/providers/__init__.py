"""Data providers: option chains, underlying candles, provider selection."""
from __future__ import annotations

import datetime as dt

import requests

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"

YAHOO_MAP = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    "INDIAVIX": "^INDIAVIX",
}

_UA = {"User-Agent": "Mozilla/5.0 (compatible; optionsdesk/1.0)"}


def yahoo_symbol(symbol: str) -> str:
    return YAHOO_MAP.get(symbol.upper(), f"{symbol.upper()}.NS")


def candles(symbol: str, interval: str = "5m", days: int = 5) -> list[dict]:
    """Intraday OHLCV for the UNDERLYING. Free, delayed ~15min on some feeds,
    which is fine for regime features but never used for fills."""
    url = YAHOO.format(sym=yahoo_symbol(symbol))
    try:
        r = requests.get(url, params={"interval": interval, "range": f"{days}d"},
                         headers=_UA, timeout=12)
        r.raise_for_status()
        js = r.json()["chart"]["result"][0]
    except Exception:
        return []

    ts = js.get("timestamp") or []
    q = js["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        out.append({
            "t": dt.datetime.fromtimestamp(t).isoformat(timespec="minutes"),
            "o": float(o), "h": float(h), "l": float(l), "c": float(c),
            "v": float(q.get("volume", [0] * len(ts))[i] or 0.0),
        })
    return out


def get_provider(cfg: dict):
    """auto -> try Kite if credentials exist, else NSE public."""
    want = cfg.get("data", {}).get("provider", "auto")
    if want in ("kite", "auto"):
        try:
            from .kite import KiteProvider
            return KiteProvider()
        except Exception as exc:
            if want == "kite":
                raise
            print(f"[providers] kite unavailable ({exc}); using NSE public feed")
    from .nse import NSEProvider
    return NSEProvider()
