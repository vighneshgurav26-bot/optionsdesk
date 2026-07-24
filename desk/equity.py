"""Cash segment — intraday (MIS) on NIFTY 50 bluechips, long or short.

Why this exists alongside the options book: on a Rs 2,00,000 clip the equity
round trip costs ~0.06% of turnover. The same directional view expressed in a
cheap stock option costs ~1.4% in charges plus ~1.9% in spread. When the option
book is thin or the premium is low, the stock is simply the better instrument
for the same idea — and unlike an option it doesn't bleed theta while you wait.

What you give up is convexity and defined risk. A long option can only lose the
premium; a stock position can gap through a stop. The risk gate treats them
differently for that reason.
"""
from __future__ import annotations

import datetime as dt

from . import clock, features as feat_mod, providers

# Assumed spread in basis points when the feed gives no depth. NIFTY 50 names
# quote 1-5 bps in normal conditions; this is deliberately pessimistic.
ASSUMED_SPREAD_BPS = 6.0


def quote(symbol: str, provider) -> dict | None:
    """Last price plus depth if the provider has it."""
    kite = getattr(provider, "kite", None)
    if kite is not None:
        try:
            k = f"NSE:{symbol}"
            q = kite.quote([k])[k]
            d = q.get("depth", {})
            bid = float((d.get("buy") or [{}])[0].get("price") or 0.0)
            ask = float((d.get("sell") or [{}])[0].get("price") or 0.0)
            return {
                "symbol": symbol, "ltp": float(q.get("last_price") or 0.0),
                "bid": bid, "ask": ask,
                "bid_qty": float((d.get("buy") or [{}])[0].get("quantity") or 0),
                "ask_qty": float((d.get("sell") or [{}])[0].get("quantity") or 0),
                "volume": float(q.get("volume") or 0.0),
                "ohlc": q.get("ohlc", {}), "source": "kite",
            }
        except Exception:
            pass

    cs = providers.candles(symbol, "5m", 2)
    if not cs:
        return None
    last = cs[-1]
    return {"symbol": symbol, "ltp": last["c"], "bid": 0.0, "ask": 0.0,
            "bid_qty": 0.0, "ask_qty": 0.0,
            "volume": sum(c["v"] for c in cs if c["t"][:10] == last["t"][:10]),
            "ohlc": {}, "source": "yahoo"}


def screen(symbols: list[str], provider, cfg: dict) -> list[dict]:
    """Which bluechips are liquid AND moving enough to trade intraday today."""
    E = cfg["equity_intraday"]
    out = []
    for sym in symbols:
        q = quote(sym, provider)
        if not q or q["ltp"] <= 0:
            continue
        cs = providers.candles(sym, "5m", 5)
        if len(cs) < 30:
            continue
        atr = feat_mod._atr_pct(cs)
        turnover_cr = q["ltp"] * q["volume"] / 1e7
        spread_bps = (1e4 * (q["ask"] - q["bid"]) / q["ltp"]
                      if q["bid"] > 0 and q["ask"] > q["bid"] else ASSUMED_SPREAD_BPS)

        fails = []
        if atr < E["min_atr_pct"]:
            fails.append(f"ATR {atr:.2f}% < {E['min_atr_pct']}%")
        if turnover_cr and turnover_cr < E["min_turnover_cr"]:
            fails.append(f"turnover Rs{turnover_cr:.0f}cr < {E['min_turnover_cr']}cr")
        if spread_bps > E["max_spread_bps"]:
            fails.append(f"spread {spread_bps:.1f}bps > {E['max_spread_bps']}bps")

        out.append({"symbol": sym, "ltp": q["ltp"], "atr_pct": round(atr, 3),
                    "turnover_cr": round(turnover_cr, 1),
                    "spread_bps": round(spread_bps, 2),
                    "tradable": not fails, "fails": fails,
                    "candles": cs, "quote": q,
                    "score": round(atr * (1.0 - spread_bps / 40.0), 3)})
    out.sort(key=lambda x: -x["score"])
    return out


def features(row: dict, cfg: dict, cost_model) -> dict:
    """Price-regime features only — no greeks, no expiry, no theta."""
    cs, q = row["candles"], row["quote"]
    closes = [c["c"] for c in cs]
    today = [c for c in cs if c["t"][:10] == cs[-1]["t"][:10]] or cs[-40:]
    spot = q["ltp"]

    hi, lo = max(c["h"] for c in today), min(c["l"] for c in today)
    orb = today[:6]
    or_hi, or_lo = max(c["h"] for c in orb), min(c["l"] for c in orb)
    pv = sum(((c["h"] + c["l"] + c["c"]) / 3) * (c["v"] or 1) for c in today)
    vol = sum((c["v"] or 1) for c in today)
    vwap = pv / vol
    ef, es = feat_mod._ema(closes[-40:], 9), feat_mod._ema(closes[-60:], 21)
    ts = clock.now()

    f = {
        "spot": spot,
        "ret_5m_pct": feat_mod._pct(closes[-2], closes[-1]) if len(closes) > 1 else 0.0,
        "ret_15m_pct": feat_mod._pct(closes[-4], closes[-1]) if len(closes) > 3 else 0.0,
        "ret_open_pct": feat_mod._pct(today[0]["o"], spot),
        "atr_pct": row["atr_pct"],
        "range_pos": round((spot - lo) / (hi - lo), 3) if hi > lo else 0.5,
        "vwap_dev_pct": round(feat_mod._pct(vwap, spot), 4),
        "ema_fast_slow_pct": round(feat_mod._pct(es, ef), 4),
        "adx_proxy": feat_mod._adx_proxy(cs),
        "opening_range_break": 1.0 if spot > or_hi else (-1.0 if spot < or_lo else 0.0),
        "minutes_into_session": round(clock.minutes_into_session(ts), 1),
        "minutes_to_close": round(clock.minutes_to_close(ts), 1),
        "spread_bps": row["spread_bps"],
        "turnover_cr": row["turnover_cr"],
        "friction_pct": round(cost_model.friction_pct(spot, max(int(50000 / spot), 1)), 4),
    }
    f["trend_score"] = round(
        max(-1, min(1, f["ema_fast_slow_pct"] / 0.25)) * 0.4
        + max(-1, min(1, f["vwap_dev_pct"] / 0.30)) * 0.3
        + f["opening_range_break"] * 0.3, 3)
    return f


def size(row: dict, spec: dict, cfg: dict, cost_model, equity: float,
         open_equity_exposure: float) -> tuple[int, float, dict]:
    """Shares to trade. Cash equity sizes in single shares, so unlike options
    the desk can nearly always express a position at the risk it wants."""
    E = cfg["equity_intraday"]
    cap = cfg["risk_ceiling"]
    px = row["ltp"]
    sizing = spec.get("equity_sizing", spec.get("sizing", {}))
    risk_pct = min(sizing.get("risk_per_trade_pct", 1.0), cap["max_risk_per_trade_pct"])
    stop_pct = float(spec.get("equity_exit", {}).get("stop_pct", 0.6))

    risk_budget = equity * risk_pct / 100.0
    risk_per_share = px * stop_pct / 100.0
    if risk_per_share <= 0:
        return 0, 0.0, {"why": "degenerate stop"}

    qty = int(risk_budget / risk_per_share)
    # exposure caps: per-book share and the global ceiling
    book_cap = equity * E["capital_share_pct"] / 100.0
    global_cap = equity * cap["max_equity_exposure_pct"] / 100.0
    room = max(0.0, min(book_cap, global_cap) - open_equity_exposure)
    qty = min(qty, int(room / px) if px > 0 else 0)

    if qty < 1:
        return 0, 0.0, {"why": f"no room: budget Rs{risk_budget:,.0f}, "
                               f"exposure room Rs{room:,.0f}"}

    notional = qty * px
    friction = cost_model.friction_pct(px, qty)
    target_pct = float(spec.get("equity_exit", {}).get("target_pct", 1.2))
    if friction > target_pct * 0.35:
        return 0, 0.0, {"why": f"charges {friction:.3f}% vs {target_pct}% target"}

    return qty, notional, {
        "risk_budget": round(risk_budget, 2),
        "risk_amount": round(qty * risk_per_share, 2),
        "notional": round(notional, 2),
        "friction_pct": round(friction, 4),
        "exposure_room": round(room, 2),
    }


def fill(side: str, row: dict, cost_model) -> float:
    q = row["quote"]
    return cost_model.fill_price(side, q["bid"], q["ask"], q["ltp"],
                                 ASSUMED_SPREAD_BPS / 100.0)
