"""Lot size resolution.

SEBI revises F&O market lots periodically and a wrong lot size silently
corrupts every P&L number downstream, so this resolves in order of authority:

  1. Kite instruments dump  - authoritative, updated daily by the broker
  2. NSE market-lot CSV     - authoritative, published by the exchange
  3. the table below        - a fallback, and NOT to be trusted blindly

Whichever source answered is recorded, and the risk gate refuses to size a
trade whose lot size came from the fallback table unless you have confirmed it.
Run `python -m desk.lots refresh` to pull and cache the live list.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import requests

CACHE = Path("state/lots.json")
NSE_CSV = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"

# Fallback only. Verify before trusting: Kite > NSE CSV > this.
FALLBACK: dict[str, int] = {
    # Verified against Kite instruments 24-Jul-2026: NIFTY is 65, not 75.
    # Treat every other line here as unverified until lots refresh runs.
    "NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 140,
    "RELIANCE": 500, "HDFCBANK": 550, "ICICIBANK": 700, "INFY": 400,
    "TCS": 175, "SBIN": 750, "AXISBANK": 625, "KOTAKBANK": 400,
    "BHARTIARTL": 475, "LT": 150, "ITC": 1600, "BAJFINANCE": 750,
    "MARUTI": 50, "TATAMOTORS": 800, "TATASTEEL": 5500, "HINDALCO": 1400,
    "ADANIENT": 300, "SUNPHARMA": 350, "TITAN": 175, "M&M": 200,
}


def _load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(d: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(d, indent=1, sort_keys=True))


def from_nse_csv() -> dict[str, int]:
    """Exchange-published market lots. Layout has changed before, so this is
    written defensively and returns {} rather than guessing."""
    try:
        r = requests.get(NSE_CSV, timeout=15, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"})
        r.raise_for_status()
        rows = list(csv.reader(io.StringIO(r.text)))
    except Exception:
        return {}
    out: dict[str, int] = {}
    for row in rows:
        cells = [c.strip() for c in row if c.strip()]
        if len(cells) < 3:
            continue
        sym = cells[1].upper() if len(cells) > 1 else ""
        for cell in cells[2:]:
            if cell.isdigit() and sym.isalnum():
                out[sym] = int(cell)
                break
    return out


def refresh(provider=None) -> dict:
    """Pull the freshest list available and cache it with its provenance."""
    table, source = {}, None
    if provider is not None and getattr(provider, "name", "") == "kite":
        try:
            for i in provider.instruments():
                if i.get("segment") == "NFO-OPT" and i.get("name"):
                    table[i["name"].upper()] = int(i["lot_size"])
            source = "kite" if table else None
        except Exception:
            table = {}
    if not table:
        table = from_nse_csv()
        source = "nse_csv" if table else None
    if not table:
        table, source = dict(FALLBACK), "fallback"

    cache = {"source": source, "lots": table}
    _save_cache(cache)
    return cache


def resolve(symbol: str, provider=None) -> tuple[int, str]:
    """Returns (lot_size, source). source == 'fallback' means unverified."""
    symbol = symbol.upper()
    cache = _load_cache()
    if symbol in (cache.get("lots") or {}):
        return int(cache["lots"][symbol]), cache.get("source", "cache")
    if provider is not None and getattr(provider, "name", "") == "kite":
        try:
            n = provider.lot_size(symbol)
            if n:
                cache.setdefault("lots", {})[symbol] = n
                cache.setdefault("source", "kite")
                _save_cache(cache)
                return n, "kite"
        except Exception:
            pass
    return FALLBACK.get(symbol, 0), "fallback"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        c = refresh()
        print(f"source={c['source']}  symbols={len(c['lots'])}")
        for k in sorted(c["lots"])[:30]:
            print(f"  {k:14} {c['lots'][k]}")
