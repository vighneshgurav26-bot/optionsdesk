"""Backtesting on two fuels.

REPLAY mode walks the desk's own archived chain snapshots — real premiums,
real spreads, real OI. It is the truth, but on day one there is none of it.

SYNTHETIC mode fills that gap: take free underlying candles, hold a vol surface
anchored to today's ATM IV, apply an intraday IV path (open elevated, mid-day
crush, close drift) and reprice with Black-76. Option P&L is then approximate
but the two things that kill intraday buyers — theta on the business clock and
Zerodha's charges — are modelled exactly.

Every result carries `mode` and `confidence`. The brain is told, in the prompt,
to discount synthetic results and to trust replay once there are enough
snapshots. A strategy is never promoted on synthetic evidence alone.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics

from . import clock, features as feat_mod, greeks as gk, strategy as strat


# --------------------------------------------------------------------------
def summarise(trades: list[dict], starting_capital: float) -> dict:
    if not trades:
        return {"trades": 0, "note": "no trades generated"}
    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))

    eq, peak, max_dd = starting_capital, starting_capital, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    exp = statistics.fmean(pnls)
    sd = statistics.pstdev(pnls) if len(pnls) > 1 else 0.0
    return {
        "trades": len(trades),
        "net_pnl": round(sum(pnls), 2),
        "return_pct": round(100.0 * sum(pnls) / starting_capital, 2),
        "win_rate_pct": round(100.0 * len(wins) / len(pnls), 1),
        "avg_win": round(statistics.fmean(wins), 2) if wins else 0.0,
        "avg_loss": round(statistics.fmean(losses), 2) if losses else 0.0,
        "expectancy": round(exp, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
        "max_drawdown": round(max_dd, 2),
        "max_dd_pct": round(100.0 * max_dd / starting_capital, 2),
        "sharpe_per_trade": round(exp / sd, 3) if sd > 0 else None,
        "total_costs": round(sum(t.get("costs", 0.0) for t in trades), 2),
        "cost_as_pct_of_gross": round(
            100.0 * sum(t.get("costs", 0) for t in trades)
            / max(sum(abs(t.get("gross_pnl", 0)) for t in trades), 1), 1),
        "exit_reasons": _counts([t.get("exit_reason", "?") for t in trades]),
        "by_symbol": _pnl_by(trades, "symbol"),
        "by_hour": _pnl_by(trades, "hour"),
    }


def _counts(xs: list[str]) -> dict:
    out: dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def _pnl_by(trades: list[dict], key: str) -> dict:
    out: dict[str, list[float]] = {}
    for t in trades:
        k = t.get("entry_ts", "")[11:13] if key == "hour" else str(t.get(key))
        out.setdefault(k, []).append(t["net_pnl"])
    return {k: {"n": len(v), "net": round(sum(v), 2)} for k, v in sorted(out.items())}


# --------------------------------------------------------------------------
def replay(store, spec: dict, cfg: dict, cost_model, symbols: list[str],
           risk_gate=None) -> dict:
    """Walk archived snapshots and simulate the spec against them."""
    capital = float(cfg["account"]["starting_capital"])
    trades: list[dict] = []
    bars = 0

    for sym in symbols:
        series = store.snapshot_series(sym, limit=4000)
        bars += len(series)
        if len(series) < 20:
            continue
        open_pos = None

        for row in series:
            f = row["features"]
            chain = row["chain"]
            if not f or not chain.get("contracts"):
                continue
            ts = dt.datetime.fromisoformat(row["ts"])

            if open_pos:
                c = _find(chain, open_pos["tradingsymbol"])
                if c:
                    px = cost_model.fill_price("SELL", c["bid"], c["ask"], c["mid"])
                    done = _check_exit(open_pos, px, ts, spec)
                    if done:
                        trades.append(_book(open_pos, px, done, ts, cost_model))
                        open_pos = None
                continue

            side = _side(spec, f)
            if not side:
                continue
            snap = {"symbol": sym, "spot": row["spot"], "ts": row["ts"],
                    "nearest_expiry": chain["expiry"],
                    "expiries": {chain["expiry"]: chain}}
            c, _ = strat.select_contract(snap, spec, side, cost_model, cfg)
            if not c:
                continue
            entry = cost_model.fill_price("BUY", c["bid"], c["ask"], c["mid"])
            lots = 1
            open_pos = _mk(sym, c, entry, lots, ts, spec)

    res = summarise(trades, capital)
    res.update({"mode": "replay", "bars": bars,
                "confidence": "high" if bars > 1500 else
                              ("medium" if bars > 400 else "low"),
                "symbols": symbols})
    return res


def synthetic(store, spec: dict, cfg: dict, cost_model, snapshots: dict,
              candle_map: dict[str, list[dict]], days: int = 5) -> dict:
    """Cold-start backtest: reprice options off underlying candles."""
    capital = float(cfg["account"]["starting_capital"])
    r = float(cfg["market"]["risk_free_rate"])
    trades: list[dict] = []
    bars = 0

    for sym, snap in snapshots.items():
        candles = candle_map.get(sym) or []
        if len(candles) < 60:
            continue
        exp_key = snap["nearest_expiry"]
        exp = snap["expiries"][exp_key]
        base_iv = exp["atm_iv"] or 0.15
        lot = next((c["lot_size"] for c in exp["contracts"] if c["lot_size"]), 0)
        if not lot:
            continue
        step = exp["strike_step"]

        # group candles into days so each simulated day gets its own expiry
        by_day: dict[str, list[dict]] = {}
        for c in candles:
            by_day.setdefault(c["t"][:10], []).append(c)

        for day, cs in sorted(by_day.items())[-days:]:
            if len(cs) < 30:
                continue
            bars += len(cs)
            day_date = dt.date.fromisoformat(day)
            # assume the option we'd have traded had the same sessions-to-expiry
            sim_expiry = day_date + dt.timedelta(days=max(exp["days_to_expiry"], 1))
            open_pos = None

            for i in range(20, len(cs)):
                window = cs[:i + 1]
                spot = window[-1]["c"]
                ts = dt.datetime.fromisoformat(window[-1]["t"]).replace(
                    tzinfo=clock.IST)
                iv = base_iv * _iv_path(ts)
                t_cal = clock.t_calendar(sim_expiry, ts)
                sess_left = clock.sessions_remaining(sim_expiry, ts)
                F = spot * math.exp(r * t_cal)
                atm = round(spot / step) * step

                if open_pos:
                    px = _reprice(open_pos, F, iv, t_cal, sess_left, r,
                                  cost_model, "SELL")
                    done = _check_exit(open_pos, px, ts, spec)
                    if done:
                        trades.append(_book(open_pos, px, done, ts, cost_model))
                        open_pos = None
                    continue

                f = _synth_features(window, snap, iv, base_iv, sess_left,
                                    atm, F, t_cal, r, lot, cost_model, ts)
                side = _side(spec, f)
                if not side:
                    continue
                band = spec.get("selection", {}).get("delta_band", [0.35, 0.65])
                K = _strike_for_delta(F, iv, t_cal, r, side, step,
                                      statistics.fmean(band))
                g = gk.compute(gk.black76(F, K, t_cal, iv, r, side == "CE"),
                               F, K, t_cal, t_cal, r, side == "CE", lot, sess_left)
                entry = cost_model.fill_price("BUY", 0, 0, g.price,
                                              "index_liquid")
                open_pos = _mk(sym, {"tradingsymbol": f"SYNTH{int(K)}{side}",
                                     "expiry": sim_expiry.isoformat(),
                                     "strike": K, "opt_type": side,
                                     "lot_size": lot, "iv": iv},
                               entry, 1, ts, spec)
                open_pos["_synth"] = True

            if open_pos:
                px = _reprice(open_pos, F, iv, max(t_cal, 1e-6), sess_left, r,
                              cost_model, "SELL")
                trades.append(_book(open_pos, px, "SESSION_CLOSE", ts, cost_model))

    res = summarise(trades, capital)
    res.update({"mode": "synthetic", "bars": bars, "confidence": "low",
                "caveat": ("option prices reconstructed from underlying candles "
                           "with a modelled IV path; treat direction and cost "
                           "drag as informative, absolute P&L as not")})
    return res


# ---------------- helpers ----------------
def _iv_path(ts: dt.datetime) -> float:
    """Typical NSE intraday IV shape: rich at open, crushed midday, firm at close."""
    m = clock.minutes_into_session(ts)
    if m < 30:
        return 1.10
    if m < 90:
        return 1.02
    if m < 240:
        return 0.94
    return 0.98


def _strike_for_delta(F, iv, t, r, side, step, target_delta):
    best, best_gap = F, 9e9
    for k in range(-15, 16):
        K = round(F / step) * step + k * step
        if K <= 0:
            continue
        g = gk.compute(gk.black76(F, K, t, iv, r, side == "CE"),
                       F, K, t, t, r, side == "CE", 1, 1.0)
        gap = abs(abs(g.delta) - target_delta)
        if gap < best_gap:
            best, best_gap = K, gap
    return best


def _reprice(pos, F, iv, t_cal, sess_left, r, cost_model, side):
    price = gk.black76(F, pos["strike"], t_cal, iv, r, pos["opt_type"] == "CE")
    return cost_model.fill_price(side, 0, 0, max(price, 0.05), "index_liquid")


def _synth_features(window, snap, iv, base_iv, sess_left, atm, F, t_cal, r,
                    lot, cost_model, ts):
    spot = window[-1]["c"]
    g = gk.compute(gk.black76(F, atm, t_cal, iv, r, True), F, atm, t_cal,
                   t_cal, r, True, lot, sess_left)
    closes = [c["c"] for c in window]
    today = window
    hi, lo = max(c["h"] for c in today), min(c["l"] for c in today)
    orb = today[:6]
    or_hi, or_lo = max(c["h"] for c in orb), min(c["l"] for c in orb)
    pv = sum(((c["h"] + c["l"] + c["c"]) / 3) * (c["v"] or 1) for c in today)
    vol = sum((c["v"] or 1) for c in today)
    vwap = pv / vol
    ef, es = feat_mod._ema(closes[-40:], 9), feat_mod._ema(closes[-60:], 21)

    f = {
        "spot": spot,
        "ret_5m_pct": feat_mod._pct(closes[-2], closes[-1]) if len(closes) > 1 else 0,
        "ret_15m_pct": feat_mod._pct(closes[-4], closes[-1]) if len(closes) > 3 else 0,
        "ret_open_pct": feat_mod._pct(today[0]["o"], spot),
        "atr_pct": feat_mod._atr_pct(window),
        "range_pos": (spot - lo) / (hi - lo) if hi > lo else 0.5,
        "vwap_dev_pct": feat_mod._pct(vwap, spot),
        "ema_fast_slow_pct": feat_mod._pct(es, ef),
        "adx_proxy": feat_mod._adx_proxy(window),
        "opening_range_break": 1.0 if spot > or_hi else (-1.0 if spot < or_lo else 0.0),
        "minutes_into_session": clock.minutes_into_session(ts),
        "minutes_to_close": clock.minutes_to_close(ts),
        "atm_iv": iv,
        "iv_vs_20d": iv / base_iv if base_iv else 1.0,
        "iv_change_pct": 100.0 * (iv / base_iv - 1.0) if base_iv else 0.0,
        "india_vix": 0.0, "vix_change_pct": 0.0,
        "expected_move_pct": 100.0 * (2 * g.price) / spot,
        "rr25": snap["expiries"][snap["nearest_expiry"]]["rr25"],
        "pcr_oi": snap["expiries"][snap["nearest_expiry"]]["pcr_oi"],
        "pcr_oi_change": 0.0,
        "max_pain_gap_pct": 0.0,
        "days_to_expiry": max(sess_left / 1.0, 0),
        "sessions_left": sess_left,
        "atm_theta_pct_per_session": 100.0 * abs(g.theta_session) / g.price
                                     if g.price > 0 else 0.0,
        "atm_breakeven_move_pct": g.breakeven_move_pct,
        "atm_spread_pct": 0.6,
        "friction_pct": cost_model.friction_pct(g.price, lot),
    }
    hurdle = f["atm_breakeven_move_pct"] + (f["friction_pct"] / 100.0) * \
        max(f["expected_move_pct"], 0.01)
    f["trend_score"] = round(
        max(-1, min(1, f["ema_fast_slow_pct"] / 0.25)) * 0.4
        + max(-1, min(1, f["vwap_dev_pct"] / 0.30)) * 0.3
        + f["opening_range_break"] * 0.3, 3)
    f["edge_ratio"] = f["expected_move_pct"] / hurdle if hurdle > 0 else 0.0
    return f


def _side(spec, f):
    ok_c, _ = strat.evaluate(spec.get("entry_long_call", {}), f)
    if ok_c and spec.get("entry_long_call"):
        return "CE"
    ok_p, _ = strat.evaluate(spec.get("entry_long_put", {}), f)
    if ok_p and spec.get("entry_long_put"):
        return "PE"
    return None


def _mk(sym, c, entry, lots, ts, spec):
    ex = spec.get("exit", {})
    return {
        "symbol": sym, "tradingsymbol": c["tradingsymbol"],
        "expiry": c["expiry"], "strike": c["strike"], "opt_type": c["opt_type"],
        "lots": lots, "qty": lots * int(c["lot_size"]),
        "entry_ts": ts.isoformat(timespec="seconds"), "entry_px": entry,
        "stop_px": round(entry * (1 - ex.get("stop_pct", 20) / 100.0), 2),
        "target_px": round(entry * (1 + ex.get("target_pct", 25) / 100.0), 2),
        "trail_px": round(entry * (1 - ex.get("stop_pct", 20) / 100.0), 2),
        "mfe_px": entry, "mae_px": entry,
    }


def _find(chain, tsym):
    for c in chain.get("contracts", []):
        if c["tradingsymbol"] == tsym:
            return c
    return None


def _check_exit(pos, px, ts, spec):
    ex = spec.get("exit", {})
    pos["mfe_px"] = max(pos["mfe_px"], px)
    pos["mae_px"] = min(pos["mae_px"], px)
    gain = 100.0 * (px - pos["entry_px"]) / pos["entry_px"]
    ta = ex.get("trail_after_pct")
    if ta and gain >= ta:
        give = ex.get("trail_giveback_pct", 40.0) / 100.0
        pos["trail_px"] = max(pos["trail_px"],
                              pos["entry_px"] + (pos["mfe_px"] - pos["entry_px"]) * (1 - give))
    held = (ts - dt.datetime.fromisoformat(pos["entry_ts"])).total_seconds() / 60.0
    force = clock.parse_hhmm(spec.get("session", {}).get("force_exit", "15:15"))
    if ts.time() >= force:
        return "SESSION_CLOSE"
    if px >= pos["target_px"]:
        return "TARGET"
    if px <= pos["trail_px"] and pos["trail_px"] > pos["stop_px"]:
        return "TRAIL"
    if px <= pos["stop_px"]:
        return "STOP"
    if ex.get("time_stop_min") and held >= ex["time_stop_min"] and gain < 5.0:
        return "TIME_STOP"
    return None


def _book(pos, px, reason, ts, cost_model):
    gross = (px - pos["entry_px"]) * pos["qty"]
    costs = cost_model.round_trip(pos["entry_px"], px, pos["qty"]).total
    return {**pos, "exit_ts": ts.isoformat(timespec="seconds"), "exit_px": px,
            "exit_reason": reason, "gross_pnl": round(gross, 2),
            "costs": round(costs, 2), "net_pnl": round(gross - costs, 2)}
