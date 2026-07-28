"""Flat feature dictionary - the only vocabulary the strategy rules may use.

Keeping this a flat {name: float} map is what makes the self-learning loop
safe: the brain writes JSON rules that reference feature names, never
executable code. Anything the brain wants to condition on has to exist here,
which also means every rule is automatically backtestable.
"""
from __future__ import annotations

import math
import statistics

from . import clock
from datetime import datetime as _dt
from . import kite_resample, kronos_forecast

# Names exposed to the brain. Keep this and build() in sync.
FEATURE_DOC = {
    # --- price regime ---
    "spot": "underlying last price",
    "ret_5m_pct": "% change over the last 5m candle",
    "ret_15m_pct": "% change over the last 3 candles",
    "ret_open_pct": "% change from today's open",
    "atr_pct": "14-period ATR as % of price",
    "range_pos": "0-1, where price sits in today's range",
    "vwap_dev_pct": "% distance from session VWAP",
    "ema_fast_slow_pct": "% gap between EMA9 and EMA21",
    "trend_score": "-1..1 composite of EMA gap, VWAP side and opening range",
    "adx_proxy": "0-100, directional persistence over the last 20 candles",
    "opening_range_break": "-1 below OR low, 0 inside, +1 above OR high",
    "minutes_into_session": "minutes since 09:15",
    "minutes_to_close": "minutes until 15:30",

    # --- volatility ---
    "atm_iv": "ATM implied vol of the traded expiry (decimal)",
    "realised_vol_pct": "annualised realised vol from the last 40 5m bars",
    "rv_iv_ratio": ("realised vol / ATM implied vol. Above 1 the tape delivers "
                    "more than options charge for - the regime where buying "
                    "premium is structurally cheap. Below 0.85 you are paying "
                    "for movement that is not happening."),
    "iv_vs_20d": "ATM IV divided by its own 20-session mean",
    "iv_change_pct": "% change in ATM IV since session open",
    "india_vix": "India VIX level",
    "vix_change_pct": "% change in India VIX today",
    "expected_move_pct": "ATM straddle as % of spot for the WHOLE life of the near expiry",
    "expected_move_per_session_pct": "the above scaled to one session (/sqrt(sessions))",
    "realised_move_per_session_pct": "what the tape actually delivered per session",

    # --- flow ---
    "rr25": "25-delta risk reversal (call IV minus put IV)",
    "pcr_oi": "put/call open interest ratio",
    "pcr_oi_change": "put/call ratio of TODAY's OI change",
    "max_pain_gap_pct": "% spot is above (+) or below (-) max pain",
    "days_to_expiry": "calendar days to the traded expiry",
    "sessions_left": "trading sessions left, fractional",

    # --- what it costs to be here ---
    "atm_theta_pct_per_session": "ATM option's session theta as % of premium",
    "atm_breakeven_move_pct": "% underlying move needed to cover one session of theta",
    "atm_spread_pct": "bid-ask spread of the ATM option, % of mid",
    "atm_one_tick_pct": "one Rs 0.05 tick as % of the ATM premium",
    "friction_pct": "round-trip Zerodha charges as % of premium, 1 lot ATM",
    "atm_total_friction_pct": "charges + spread + book impact, round trip, 1 lot",
    "atm_top_of_book_lots": "lots resting on the ATM offer",
    "liquid_contracts": "contracts in this chain passing the liquidity gate",
    "edge_ratio": ("per-session IMPLIED move divided by the full per-session cost "
                   "hurdle (theta + charges + spread + impact). What the option "
                   "would need to deliver to pay for itself."),
    "realised_edge_ratio": ("same hurdle, but against what the tape has ACTUALLY "
                            "been delivering. This is the honest one: edge_ratio "
                            "can look fine purely because options are expensive."),

    # --- Kronos (optional AI forecast opinion, never required for a trade) ---
    "kronos_bull_score": "0-1, how bullish Kronos's forecast is (0 if no signal or bearish)",
    "kronos_bear_score": "0-1, how bearish Kronos's forecast is (0 if no signal or bullish)",
}


# ---------------------------------------------------------------- helpers
def _ema(vals: list[float], n: int) -> float:
    if not vals:
        return 0.0
    k = 2.0 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _atr_pct(cs: list[dict], n: int = 14) -> float:
    if len(cs) < 2:
        return 0.0
    trs = []
    for prev, cur in zip(cs[-n - 1:-1], cs[-n:]):
        trs.append(max(cur["h"] - cur["l"],
                       abs(cur["h"] - prev["c"]), abs(cur["l"] - prev["c"])))
    if not trs or cs[-1]["c"] <= 0:
        return 0.0
    return 100.0 * statistics.fmean(trs) / cs[-1]["c"]


def _adx_proxy(cs: list[dict], n: int = 20) -> float:
    """Net directional travel over gross travel. 0 = chop, 100 = clean trend."""
    w = cs[-n:]
    if len(w) < 3:
        return 0.0
    gross = sum(abs(b["c"] - a["c"]) for a, b in zip(w, w[1:]))
    net = abs(w[-1]["c"] - w[0]["c"])
    return round(100.0 * net / gross, 2) if gross > 0 else 0.0


def _realised_vol(closes: list[float], bars: int = 40) -> float:
    """Annualised close-to-close vol from 5-minute bars."""
    w = closes[-(bars + 1):]
    rets = [math.log(b / a) for a, b in zip(w, w[1:]) if a > 0 and b > 0]
    if len(rets) < 8:
        return 0.0
    return statistics.pstdev(rets) * math.sqrt(75 * 252)   # 75 bars/session


def _pct(a: float | None, b: float | None) -> float:
    if not a or not b or a == 0:
        return 0.0
    return 100.0 * (b - a) / a


def _kronos_scores(candles: list[dict]) -> tuple[float, float]:
    """Ask Kronos its opinion. If ANYTHING goes wrong - model missing, bad
    data, not enough history, whatever - both scores come back 0.0, which
    is invisible to every existing rule and can never break a run or block
    a trade. Kronos is a bonus opinion here, never a gatekeeper."""
    try:
        conv = [{"date": _dt.fromisoformat(c["t"]), "open": c["o"],
                 "high": c["h"], "low": c["l"], "close": c["c"],
                 "volume": c["v"]} for c in candles]
        cleaned = kite_resample.clean_and_flag_gaps(conv)
        window = kite_resample.latest_unbroken_window(cleaned)
        sig = kronos_forecast.get_kronos_signal(window)
        if not sig["available"]:
            return 0.0, 0.0
        conf = sig["confidence"]
        if sig["direction"] == "bullish":
            return round(conf, 3), 0.0
        if sig["direction"] == "bearish":
            return 0.0, round(conf, 3)
        return 0.0, 0.0
    except Exception:
        return 0.0, 0.0


# ---------------------------------------------------------------- builder
def build(snapshot: dict, candles: list[dict], cost_model, cfg: dict,
          vix: float | None = None, iv_history: list[float] | None = None,
          session_open_iv: float | None = None,
          vix_prev_close: float | None = None) -> dict:
    f: dict[str, float] = {}
    spot = snapshot["spot"]
    f["spot"] = spot

    # ---------- price regime ----------
    today = [c for c in candles if c["t"][:10] == snapshot["ts"][:10]] \
        or candles[-75:]
    closes = [c["c"] for c in candles]
    f["ret_5m_pct"] = _pct(closes[-2], closes[-1]) if len(closes) >= 2 else 0.0
    f["ret_15m_pct"] = _pct(closes[-4], closes[-1]) if len(closes) >= 4 else 0.0
    f["ret_open_pct"] = _pct(today[0]["o"], spot) if today else 0.0
    f["atr_pct"] = round(_atr_pct(candles), 4)

    if today:
        hi = max(c["h"] for c in today)
        lo = min(c["l"] for c in today)
        f["range_pos"] = round((spot - lo) / (hi - lo), 3) if hi > lo else 0.5
        pv = sum(((c["h"] + c["l"] + c["c"]) / 3) * c["v"] for c in today)
        vol = sum(c["v"] for c in today)
        vwap = pv / vol if vol > 0 else statistics.fmean([c["c"] for c in today])
        f["vwap_dev_pct"] = round(_pct(vwap, spot), 4)
        orb = today[:6]                       # first 30 minutes
        or_hi, or_lo = max(c["h"] for c in orb), min(c["l"] for c in orb)
        f["opening_range_break"] = 1.0 if spot > or_hi else (
            -1.0 if spot < or_lo else 0.0)
    else:
        f["range_pos"], f["vwap_dev_pct"], f["opening_range_break"] = 0.5, 0.0, 0.0

    ef, es = _ema(closes[-40:], 9), _ema(closes[-60:], 21)
    f["ema_fast_slow_pct"] = round(_pct(es, ef), 4)
    f["adx_proxy"] = _adx_proxy(candles)
    f["trend_score"] = round(
        max(-1.0, min(1.0, f["ema_fast_slow_pct"] / 0.25)) * 0.4
        + max(-1.0, min(1.0, f["vwap_dev_pct"] / 0.30)) * 0.3
        + f["opening_range_break"] * 0.3, 3)

    ts = clock.to_ist(clock.now())
    f["minutes_into_session"] = round(clock.minutes_into_session(ts), 1)
    f["minutes_to_close"] = round(clock.minutes_to_close(ts), 1)

    # ---------- volatility ----------
    exp = snapshot["expiries"][snapshot["nearest_expiry"]]
    f["atm_iv"] = exp["atm_iv"]
    f["expected_move_pct"] = snapshot["expected_move_pct"]
    f["realised_vol_pct"] = round(_realised_vol(closes), 4)
    f["rv_iv_ratio"] = round(f["realised_vol_pct"] / exp["atm_iv"], 3) \
        if exp["atm_iv"] > 0 else 0.0

    hist = [v for v in (iv_history or []) if v > 0]
    f["iv_vs_20d"] = round(exp["atm_iv"] / statistics.fmean(hist[-20:]), 3) \
        if hist else 1.0
    f["iv_change_pct"] = round(_pct(session_open_iv, exp["atm_iv"]), 3) \
        if session_open_iv else 0.0
    f["india_vix"] = float(vix or 0.0)
    f["vix_change_pct"] = round(_pct(vix_prev_close, vix), 3) \
        if (vix and vix_prev_close) else 0.0

    # ---------- flow ----------
    f["rr25"] = exp["rr25"]
    f["pcr_oi"] = exp["pcr_oi"]
    f["pcr_oi_change"] = exp["pcr_oi_change"]
    f["max_pain_gap_pct"] = exp["max_pain_gap_pct"]
    f["days_to_expiry"] = float(exp["days_to_expiry"])
    f["sessions_left"] = exp["sessions_left"]

    # ---------- cost of being here ----------
    atm = [c for c in exp["contracts"] if c["strike"] == exp["atm_strike"]]
    if atm:
        ce = next((c for c in atm if c["opt_type"] == "CE"), atm[0])
        prem = ce["mid"]
        lm = ce.get("liquidity") or {}
        qty = ce["lot_size"] or 1
        f["atm_theta_pct_per_session"] = round(
            100.0 * abs(ce["theta_session"]) / prem, 3) if prem > 0 else 0.0
        f["atm_breakeven_move_pct"] = ce["breakeven_move_pct"]
        f["atm_spread_pct"] = ce["spread_pct"] if ce["spread_pct"] is not None \
            else lm.get("spread_pct", 99.0)
        f["atm_one_tick_pct"] = round(100.0 * 0.05 / prem, 3) if prem > 0 else 99.0
        f["friction_pct"] = round(cost_model.friction_pct(prem, qty), 3)
        f["atm_total_friction_pct"] = lm.get(
            "total_friction_pct", f["friction_pct"] + f["atm_spread_pct"])
        f["atm_top_of_book_lots"] = lm.get("lots_at_touch", 0.0)
    else:
        f["atm_theta_pct_per_session"] = 0.0
        f["atm_breakeven_move_pct"] = 0.0
        f["atm_spread_pct"] = 99.0
        f["atm_one_tick_pct"] = 99.0
        f["friction_pct"] = 99.0
        f["atm_total_friction_pct"] = 99.0
        f["atm_top_of_book_lots"] = 0.0

    f["liquid_contracts"] = float(sum(
        1 for c in exp["contracts"] if (c.get("liquidity") or {}).get("tradable")))

    # The sanity number. Hurdle = one session of theta expressed as an
    # underlying move, plus every cost of getting in and back out. On the real
    # books, spread often exceeds charges - so it belongs in here, not beside it.
    sess = max(f["sessions_left"], 0.25)
    f["expected_move_per_session_pct"] = round(
        f["expected_move_pct"] / math.sqrt(sess), 4)
    # Realised vol is annualised; one session is 1/252 of a year.
    f["realised_move_per_session_pct"] = round(
        100.0 * f["realised_vol_pct"] / math.sqrt(252.0), 4)

    # Hurdle, per session: theta expressed as an underlying move, plus the
    # round-trip friction amortised over the expected holding period.
    friction_as_move = (f["atm_total_friction_pct"] / 100.0) * \
        max(f["expected_move_per_session_pct"], 0.01)
    cost_hurdle = f["atm_breakeven_move_pct"] + friction_as_move
    f["edge_ratio"] = round(
        f["expected_move_per_session_pct"] / cost_hurdle, 3) if cost_hurdle > 0 else 0.0
    f["realised_edge_ratio"] = round(
        f["realised_move_per_session_pct"] / cost_hurdle, 3) if cost_hurdle > 0 else 0.0

    # ---------- Kronos (optional AI forecast, purely additive) ----------
    f["kronos_bull_score"], f["kronos_bear_score"] = _kronos_scores(candles)

    return {k: (round(v, 5) if isinstance(v, float) and math.isfinite(v) else v)
            for k, v in f.items()}
