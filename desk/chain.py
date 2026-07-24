"""Turn a raw option chain into a decision-grade snapshot.

For each expiry we back out a forward from ATM put-call parity, solve implied
vol per contract from the MID (not the LTP — LTP on an illiquid strike can be
minutes stale), then attach the full greek surface plus tradability metrics.
Contracts that fail liquidity are kept but flagged, so the journal can later
show what was rejected and why.
"""
from __future__ import annotations

import datetime as dt
import statistics

from . import clock, greeks as gk, liquidity as liq, lots as lotmod


def _mid(row: dict) -> float:
    b, a = row.get("bid", 0.0), row.get("ask", 0.0)
    if b > 0 and a > b:
        return 0.5 * (b + a)
    return row.get("ltp", 0.0)


def build(raw: dict, cfg: dict, ts: dt.datetime | None = None,
          cost_model=None, provider=None) -> dict | None:
    """raw = provider.chain(symbol) -> enriched snapshot dict."""
    if not raw or not raw.get("rows"):
        return None
    ts = ts or clock.now()
    r = float(cfg["market"]["risk_free_rate"])
    symbol = raw["symbol"]
    spot = float(raw["spot"])

    by_exp: dict[str, list[dict]] = {}
    for row in raw["rows"]:
        by_exp.setdefault(row["expiry"], []).append(row)

    # Lot sizes come from config (NSE revised these for the Jan 2026 series);
    # Kite's instrument dump overrides them when available.
    lot_default, lot_source = lotmod.resolve(symbol, provider)
    expiries_out = {}

    for exp_str, rows in sorted(by_exp.items()):
        expiry = dt.date.fromisoformat(exp_str)
        if clock.expiry_datetime(expiry) <= ts:
            continue
        t_cal = clock.t_calendar(expiry, ts)
        t_bus = clock.t_business(expiry, ts)
        sess_left = clock.sessions_remaining(expiry, ts)

        strikes = sorted({row["strike"] for row in rows})
        if len(strikes) < 3:
            continue
        step = min((b - a) for a, b in zip(strikes, strikes[1:]) if b > a)
        atm = min(strikes, key=lambda k: abs(k - spot))

        ce = {row["strike"]: row for row in rows if row["opt_type"] == "CE"}
        pe = {row["strike"]: row for row in rows if row["opt_type"] == "PE"}
        F = gk.forward_from_parity(
            spot, atm, _mid(ce.get(atm, {})), _mid(pe.get(atm, {})), r, t_cal)

        contracts = []
        for row in rows:
            mid = _mid(row)
            if mid <= 0:
                continue
            lot = int(row.get("lot_size") or lot_default)
            g = gk.compute(mid, F, row["strike"], t_cal, t_bus, r,
                           row["opt_type"] == "CE", lot, sess_left)
            spread_pct = (100.0 * (row["ask"] - row["bid"]) / mid
                          if row.get("bid", 0) > 0 and row.get("ask", 0) > row["bid"]
                          else None)
            c = dict(row)
            c.setdefault("bid_qty", 0.0)
            c.setdefault("ask_qty", 0.0)
            c.setdefault("total_bid_qty", 0.0)
            c.setdefault("total_ask_qty", 0.0)
            c.update({
                "mid": round(mid, 2),
                "lot_size": lot,
                "premium_per_lot": round(mid * lot, 2),
                "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
                "dist_from_atm": int(round((row["strike"] - atm) / step)),
                "t_cal": t_cal,
                "t_bus": t_bus,
                "sessions_left": round(sess_left, 3),
                **g.to_dict(),
            })
            if cost_model is not None and lot:
                # Assessed at ONE lot here. The risk gate re-assesses at the
                # real order size, because a contract that is liquid for one
                # lot may not be for four.
                c["liquidity"] = liq.assess(c, lot, cfg, cost_model,
                                            symbol).to_dict()
                c["tradable"] = c["liquidity"]["tradable"]
            contracts.append(c)

        if not contracts:
            continue

        ivs = [c["iv"] for c in contracts if 0.01 < c["iv"] < 3.0]
        atm_ce = next((c for c in contracts
                       if c["strike"] == atm and c["opt_type"] == "CE"), None)
        atm_pe = next((c for c in contracts
                       if c["strike"] == atm and c["opt_type"] == "PE"), None)
        atm_iv = statistics.fmean([x["iv"] for x in (atm_ce, atm_pe) if x]) \
            if (atm_ce or atm_pe) else (statistics.fmean(ivs) if ivs else 0.0)

        # 25-delta risk reversal: the cleanest read on directional skew.
        def near_delta(target: float, kind: str):
            pool = [c for c in contracts if c["opt_type"] == kind and c["iv"] > 0]
            return min(pool, key=lambda c: abs(abs(c["delta"]) - target),
                       default=None)
        c25, p25 = near_delta(0.25, "CE"), near_delta(0.25, "PE")
        rr25 = (c25["iv"] - p25["iv"]) if (c25 and p25) else 0.0

        tot_ce_oi = sum(c["oi"] for c in contracts if c["opt_type"] == "CE")
        tot_pe_oi = sum(c["oi"] for c in contracts if c["opt_type"] == "PE")
        d_ce_oi = sum(c["oi_change"] for c in contracts if c["opt_type"] == "CE")
        d_pe_oi = sum(c["oi_change"] for c in contracts if c["opt_type"] == "PE")

        max_pain = _max_pain(contracts, strikes)

        expiries_out[exp_str] = {
            "expiry": exp_str,
            "days_to_expiry": (expiry - ts.date()).days,
            "sessions_left": round(sess_left, 3),
            "t_cal": t_cal,
            "forward": round(F, 2),
            "basis_pct": round(100.0 * (F / spot - 1.0), 4) if spot else 0.0,
            "atm_strike": atm,
            "strike_step": step,
            "atm_iv": round(atm_iv, 4),
            "iv_min": round(min(ivs), 4) if ivs else 0.0,
            "iv_max": round(max(ivs), 4) if ivs else 0.0,
            "rr25": round(rr25, 4),
            "pcr_oi": round(tot_pe_oi / tot_ce_oi, 3) if tot_ce_oi else 0.0,
            "pcr_oi_change": round(d_pe_oi / d_ce_oi, 3) if d_ce_oi else 0.0,
            "max_pain": max_pain,
            "max_pain_gap_pct": round(100.0 * (spot - max_pain) / spot, 3)
                                if (max_pain and spot) else 0.0,
            "straddle_price": round((atm_ce["mid"] if atm_ce else 0)
                                    + (atm_pe["mid"] if atm_pe else 0), 2),
            "contracts": contracts,
        }

    if not expiries_out:
        return None

    near = min(expiries_out)
    straddle = expiries_out[near]["straddle_price"]
    return {
        "symbol": symbol,
        "spot": spot,
        "ts": ts.isoformat(timespec="seconds"),
        "source": raw.get("source", "?"),
        "nearest_expiry": near,
        # The straddle is the market's own quote for today's range. Anything
        # the strategy expects to capture has to be a plausible fraction of it.
        "expected_move_pct": round(100.0 * straddle / spot, 3) if spot else 0.0,
        "lot_size": lot_default,
        "lot_source": lot_source,
        "expiries": expiries_out,
    }


def _max_pain(contracts: list[dict], strikes: list[float]) -> float:
    best, best_pain = 0.0, None
    for k in strikes:
        pain = 0.0
        for c in contracts:
            if c["opt_type"] == "CE":
                pain += max(k - c["strike"], 0.0) * c["oi"]
            else:
                pain += max(c["strike"] - k, 0.0) * c["oi"]
        if best_pain is None or pain < best_pain:
            best, best_pain = k, pain
    return best


def pick(snapshot: dict, expiry: str, opt_type: str,
         offset: int = 0) -> dict | None:
    """Contract `offset` strikes away from ATM (+ = OTM for calls)."""
    exp = snapshot["expiries"].get(expiry)
    if not exp:
        return None
    want = offset if opt_type == "CE" else -offset
    for c in exp["contracts"]:
        if c["opt_type"] == opt_type and c["dist_from_atm"] == want:
            return c
    return None
