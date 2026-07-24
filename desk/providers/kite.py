"""Zerodha Kite Connect provider.

Kite gives you real depth (5 levels of bid/ask), which matters enormously for
option buying — the NSE public feed's top-of-book is often stale by seconds.
The catch is that the access token dies every morning around 07:30 IST and the
login is interactive, so this provider is the better data source but the worse
unattended one. Run `python -m desk.providers.kite login` each morning, or keep
the NSE provider as the fallback.

Env: KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

TOKEN_FILE = Path("state/kite_token.txt")


class KiteProvider:
    name = "kite"

    def __init__(self):
        from kiteconnect import KiteConnect  # imported lazily
        self.api_key = os.environ["KITE_API_KEY"]
        self.kite = KiteConnect(api_key=self.api_key)
        token = os.environ.get("KITE_ACCESS_TOKEN")
        if not token and TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text().strip()
        if not token:
            raise RuntimeError("No Kite access token. Run the login flow.")
        self.kite.set_access_token(token)
        self._instruments: list[dict] | None = None

    # ---------- instruments ----------
    def instruments(self) -> list[dict]:
        if self._instruments is None:
            self._instruments = self.kite.instruments("NFO")
        return self._instruments

    def lot_size(self, symbol: str) -> int:
        for i in self.instruments():
            if i["name"] == symbol and i["segment"] == "NFO-OPT":
                return int(i["lot_size"])
        return 0

    def chain(self, symbol: str, max_strikes: int = 25) -> dict | None:
        symbol = symbol.upper()
        opts = [i for i in self.instruments()
                if i["name"] == symbol and i["segment"] == "NFO-OPT"]
        if not opts:
            return None

        spot_sym = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
                    "FINNIFTY": "NSE:NIFTY FIN SERVICE",
                    "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT"}.get(
                        symbol, f"NSE:{symbol}")
        try:
            spot = float(self.kite.ltp([spot_sym])[spot_sym]["last_price"])
        except Exception:
            return None

        expiries = sorted({i["expiry"] for i in opts if i["expiry"]})
        near = expiries[:2]
        step = self._strike_step(opts)
        atm = round(spot / step) * step
        lo, hi = atm - max_strikes * step, atm + max_strikes * step

        sel = [i for i in opts if i["expiry"] in near and lo <= i["strike"] <= hi]
        keys = [f"NFO:{i['tradingsymbol']}" for i in sel]

        quotes: dict = {}
        for k in range(0, len(keys), 200):          # Kite caps the batch size
            quotes.update(self.kite.quote(keys[k:k + 200]))

        rows = []
        for i in sel:
            q = quotes.get(f"NFO:{i['tradingsymbol']}")
            if not q:
                continue
            depth = q.get("depth", {})
            buys = depth.get("buy") or [{}]
            sells = depth.get("sell") or [{}]
            bid = float(buys[0].get("price") or 0.0)
            ask = float(sells[0].get("price") or 0.0)
            ltp = float(q.get("last_price") or 0.0)
            if ltp <= 0 and bid <= 0:
                continue
            rows.append({
                "symbol": symbol,
                "expiry": i["expiry"].isoformat() if isinstance(i["expiry"], dt.date)
                          else str(i["expiry"]),
                "strike": float(i["strike"]),
                "opt_type": i["instrument_type"],
                "ltp": ltp,
                "bid": bid,
                "ask": ask,
                "bid_qty": float(buys[0].get("quantity") or 0.0),
                "ask_qty": float(sells[0].get("quantity") or 0.0),
                "total_bid_qty": sum(float(x.get("quantity") or 0) for x in buys),
                "total_ask_qty": sum(float(x.get("quantity") or 0) for x in sells),
                "oi": float(q.get("oi") or 0.0),
                "oi_change": float(q.get("oi") or 0.0) - float(q.get("oi_day_low") or 0.0),
                "volume": float(q.get("volume") or 0.0),
                "nse_iv": 0.0,
                "tradingsymbol": i["tradingsymbol"],
                "lot_size": int(i["lot_size"]),
            })

        if not rows:
            return None
        return {
            "symbol": symbol,
            "spot": spot,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "expiries": [e.isoformat() if isinstance(e, dt.date) else str(e)
                         for e in expiries],
            "rows": rows,
            "source": "kite",
        }

    @staticmethod
    def _strike_step(opts: list[dict]) -> float:
        strikes = sorted({float(i["strike"]) for i in opts})
        diffs = [b - a for a, b in zip(strikes, strikes[1:]) if b > a]
        return min(diffs) if diffs else 50.0

    def india_vix(self) -> float | None:
        try:
            k = "NSE:INDIA VIX"
            return float(self.kite.ltp([k])[k]["last_price"])
        except Exception:
            return None


def login_flow() -> None:
    """Interactive: prints the login URL, takes the request_token, saves it."""
    from kiteconnect import KiteConnect
    key, secret = os.environ["KITE_API_KEY"], os.environ["KITE_API_SECRET"]
    kite = KiteConnect(api_key=key)
    print("Open this, log in, then paste the request_token from the redirect:")
    print(kite.login_url())
    rt = input("request_token: ").strip()
    data = kite.generate_session(rt, api_secret=secret)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(data["access_token"])
    print("Saved to", TOKEN_FILE)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        login_flow()
