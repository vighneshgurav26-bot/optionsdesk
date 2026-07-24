"""Paper execution and position management.

Fills cross the spread in the realistic direction and pay slippage on both
legs; charges are the exact Zerodha schedule. Nothing about the P&L is
optimistic — if the desk can't clear this bar it doesn't have an edge worth
risking real money on.
"""
from __future__ import annotations

import datetime as dt
import json

from . import clock


class Engine:
    def __init__(self, cfg, store, cost_model, risk_gate):
        self.cfg = cfg
        self.store = store
        self.costs = cost_model
        self.risk = risk_gate

    # ---------------- marking ----------------
    def find_live(self, snapshots: dict, trade: dict) -> dict | None:
        snap = snapshots.get(trade["symbol"])
        if not snap:
            return None
        exp = snap["expiries"].get(trade["expiry"])
        if not exp:
            return None
        for c in exp["contracts"]:
            if c["tradingsymbol"] == trade["tradingsymbol"]:
                return c
        for c in exp["contracts"]:
            if c["strike"] == trade["strike"] and c["opt_type"] == trade["opt_type"]:
                return c
        return None

    def unrealised(self, snapshots: dict) -> tuple[float, list[dict]]:
        total, marked = 0.0, []
        for t in self.store.open_trades():
            c = self.find_live(snapshots, t)
            if not c:
                marked.append({**t, "live_px": t["entry_px"], "upnl": 0.0})
                continue
            exit_px = self.costs.fill_price("SELL", c["bid"], c["ask"], c["mid"],
                                            depth=c.get("bid_depth"),
                                            qty=t["qty"])
            gross = (exit_px - t["entry_px"]) * t["qty"]
            chg = self.costs.round_trip(t["entry_px"], exit_px, t["qty"]).total
            upnl = gross - chg
            total += upnl
            marked.append({**t, "live_px": exit_px, "upnl": upnl,
                           "live_greeks": c})
        return total, marked

    # ---------------- entries ----------------
    def enter(self, contract: dict, snapshot: dict, feats: dict, spec: dict,
              decision, thesis: str, confidence: float, debate: str,
              version: int, ts: dt.datetime) -> int:
        entry_px = self.costs.fill_price(
            "BUY", contract.get("bid", 0.0), contract.get("ask", 0.0),
            contract["mid"], depth=contract.get("ask_depth"), qty=decision.qty)
        trade = {
            "strategy_version": version,
            "symbol": snapshot["symbol"],
            "tradingsymbol": contract["tradingsymbol"],
            "expiry": contract["expiry"],
            "strike": contract["strike"],
            "opt_type": contract["opt_type"],
            "lots": decision.lots,
            "qty": decision.qty,
            "entry_ts": ts.isoformat(timespec="seconds"),
            "entry_px": entry_px,
            "status": "OPEN",
            "stop_px": decision.stop_px,
            "target_px": decision.target_px,
            "trail_px": decision.stop_px,
            "mfe_px": entry_px,
            "mae_px": entry_px,
            "entry_greeks": json.dumps({
                k: contract.get(k) for k in
                ("iv", "delta", "gamma", "vega", "theta_session", "theta_per_min",
                 "vanna", "vomma", "charm", "breakeven_move_pct",
                 "gamma_theta_ratio", "spread_pct", "oi", "mid")}),
            "liquidity_at_entry": json.dumps(
                contract.get("_liquidity_at_size") or contract.get("liquidity") or {}),
            "entry_features": json.dumps(feats),
            "thesis": thesis,
            "confidence": confidence,
            "debate": debate,
        }
        tid = self.store.insert_trade(trade)
        premium = entry_px * decision.qty
        self.store.log(
            ts.isoformat(timespec="seconds"), "ENTRY",
            f"BUY {decision.lots}x {contract['tradingsymbol']} @ {entry_px}",
            f"premium Rs{premium:,.0f} | stop {decision.stop_px} "
            f"target {decision.target_px} | delta {contract['delta']:.2f} "
            f"IV {contract['iv']:.1%} | {thesis[:180]}",
            snapshot["symbol"], {"trade_id": tid, "checks": decision.checks})
        return tid

    # ---------------- exits ----------------
    def manage(self, snapshots: dict, spec: dict, ts: dt.datetime) -> list[dict]:
        closed = []
        force_at = clock.parse_hhmm(
            spec.get("session", {}).get("force_exit",
                                        self.cfg["session"]["force_flat_at"]))
        ex = spec.get("exit", {})

        for t in self.store.open_trades():
            c = self.find_live(snapshots, t)
            if not c:
                if ts.time() >= force_at:
                    closed.append(self._close(t, t["entry_px"], "NO_QUOTE_FORCED", ts))
                continue

            px = self.costs.fill_price("SELL", c["bid"], c["ask"], c["mid"],
                                       depth=c.get("bid_depth"), qty=t["qty"])
            mfe = max(t.get("mfe_px") or px, px)
            mae = min(t.get("mae_px") or px, px)
            trail = t.get("trail_px") or t["stop_px"]

            gain_pct = 100.0 * (px - t["entry_px"]) / t["entry_px"]
            after = clock.to_ist(dt.datetime.fromisoformat(t["entry_ts"]))
            held_min = (ts - after).total_seconds() / 60.0

            # trail: once the move pays, give back only part of it
            trail_after = ex.get("trail_after_pct")
            if trail_after and gain_pct >= trail_after:
                give = ex.get("trail_giveback_pct", 40.0) / 100.0
                new_trail = t["entry_px"] + (mfe - t["entry_px"]) * (1 - give)
                trail = max(trail, round(new_trail, 2))

            self.store.update_trade(t["id"], mfe_px=mfe, mae_px=mae, trail_px=trail)

            reason = None
            if ts.time() >= force_at:
                reason = "SESSION_CLOSE"
            elif px >= t["target_px"]:
                reason = "TARGET"
            elif px <= trail and trail > t["stop_px"]:
                reason = "TRAIL"
            elif px <= t["stop_px"]:
                reason = "STOP"
            elif ex.get("time_stop_min") and held_min >= ex["time_stop_min"] \
                    and gain_pct < ex.get("time_stop_min_gain_pct", 5.0):
                reason = "TIME_STOP"
            else:
                entry_g = json.loads(t.get("entry_greeks") or "{}")
                crush = ex.get("iv_crush_exit_pct")
                if crush and entry_g.get("iv"):
                    drop = 100.0 * (entry_g["iv"] - c["iv"]) / entry_g["iv"]
                    if drop >= crush:
                        reason = "IV_CRUSH"
                inv = ex.get("underlying_invalidation")
                if not reason and inv and inv.get("flip"):
                    ef = json.loads(t.get("entry_features") or "{}")
                    name = inv.get("feature", "vwap_dev_pct")
                    now_v = snapshots[t["symbol"]].get("_features", {}).get(name)
                    was = ef.get(name)
                    if now_v is not None and was is not None and was * now_v < 0:
                        reason = "THESIS_INVALIDATED"

            if reason:
                closed.append(self._close(t, px, reason, ts, c))

        return closed

    def _close(self, t: dict, px: float, reason: str, ts: dt.datetime,
               contract: dict | None = None) -> dict:
        gross = (px - t["entry_px"]) * t["qty"]
        cb = self.costs.round_trip(t["entry_px"], px, t["qty"])
        net = gross - cb.total
        self.store.update_trade(
            t["id"], status="CLOSED", exit_ts=ts.isoformat(timespec="seconds"),
            exit_px=px, exit_reason=reason, gross_pnl=round(gross, 2),
            costs=round(cb.total, 2), net_pnl=round(net, 2),
            exit_greeks=json.dumps({k: contract.get(k) for k in
                                    ("iv", "delta", "gamma", "theta_session", "mid")}
                                   if contract else {}))
        held = (ts - clock.to_ist(dt.datetime.fromisoformat(t["entry_ts"]))
                ).total_seconds() / 60.0
        self.store.log(
            ts.isoformat(timespec="seconds"), "EXIT",
            f"SELL {t['tradingsymbol']} @ {px} — {reason}",
            f"net Rs{net:,.0f} (gross {gross:,.0f} - charges {cb.total:,.0f}) "
            f"| held {held:.0f}m | MFE {t.get('mfe_px')} MAE {t.get('mae_px')}",
            t["symbol"], {"trade_id": t["id"], "costs": cb.to_dict()})
        return {**t, "exit_px": px, "net_pnl": net, "exit_reason": reason}
