"""The risk gate. Nothing reaches the paper book without a PASS from here.

Order matters: kill switch, then drawdown, then session, then count, then
exposure, then sizing. The first BLOCK short-circuits — a blocked trade is
recorded with its reason so the review loop can see what the rules cost.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import clock, liquidity as liq


@dataclass
class Decision:
    approved: bool = False
    lots: int = 0
    qty: int = 0
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    stop_px: float = 0.0
    target_px: float = 0.0
    risk_amount: float = 0.0

    def block(self, why: str) -> "Decision":
        self.approved = False
        self.reasons.append(why)
        return self


class RiskGate:
    def __init__(self, cfg: dict, store, cost_model):
        self.cfg = cfg
        self.cap = cfg["risk_ceiling"]
        self.store = store
        self.costs = cost_model
        self.start_capital = float(cfg["account"]["starting_capital"])

    # ---------- account state ----------
    def equity(self, unrealised: float = 0.0) -> float:
        return self.start_capital + self.store.realised_total() + unrealised

    def drawdown_pct(self, equity: float) -> float:
        peak = max(self.store.peak_equity(self.start_capital), self.start_capital)
        return 100.0 * (peak - equity) / peak if peak > 0 else 0.0

    def halted(self, equity: float, day: str) -> tuple[bool, str]:
        dd = self.drawdown_pct(equity)
        if dd >= self.cap["kill_switch_drawdown_pct"]:
            return True, (f"KILL SWITCH: drawdown {dd:.2f}% >= "
                          f"{self.cap['kill_switch_drawdown_pct']}%. "
                          "Manual reset required.")
        day_pnl = self.store.realised_today(day)
        day_limit = -self.start_capital * self.cap["max_daily_loss_pct"] / 100.0
        if day_pnl <= day_limit:
            return True, (f"Daily loss halt: {day_pnl:,.0f} <= {day_limit:,.0f}")
        week_start = (dt.date.fromisoformat(day)
                      - dt.timedelta(days=dt.date.fromisoformat(day).weekday()))
        wk = self.store.realised_since(week_start.isoformat())
        wk_limit = -self.start_capital * self.cap["max_weekly_loss_pct"] / 100.0
        if wk <= wk_limit:
            return True, f"Weekly loss halt: {wk:,.0f} <= {wk_limit:,.0f}"
        return False, ""

    # ---------- the gate ----------
    def evaluate(self, contract: dict, spec: dict, ts: dt.datetime,
                 unrealised: float, open_positions: list[dict]) -> Decision:
        d = Decision()
        day = ts.date().isoformat()
        eq = self.equity(unrealised)
        d.checks["equity"] = round(eq, 2)

        halted, why = self.halted(eq, day)
        d.checks["kill_switch"] = "HALT" if halted else "PASS"
        if halted:
            return d.block(why)

        # --- session windows ---
        sess = spec.get("session", {})
        t = ts.time()
        if t < clock.parse_hhmm(sess.get("start", "09:20")):
            return d.block(f"before entry window ({sess.get('start')})")
        if t >= clock.parse_hhmm(sess.get("no_new_after", "14:45")):
            return d.block(f"past no-new-entry time ({sess.get('no_new_after')})")
        d.checks["session"] = "PASS"

        # --- trade count / concurrency / cooldown ---
        n_today = self.store.trades_today(day)
        max_today = min(spec.get("risk", {}).get("max_trades_day", 99),
                        self.cap["max_trades_per_day"])
        if n_today >= max_today:
            return d.block(f"trade count {n_today}/{max_today} for today")
        max_conc = min(spec.get("risk", {}).get("max_concurrent", 99),
                       self.cap["max_concurrent_positions"])
        if len(open_positions) >= max_conc:
            return d.block(f"concurrency {len(open_positions)}/{max_conc}")
        if any(p["tradingsymbol"] == contract["tradingsymbol"] for p in open_positions):
            return d.block("already long this exact contract")
        d.checks["counts"] = f"{n_today}/{max_today} today, {len(open_positions)}/{max_conc} open"

        cool = spec.get("risk", {}).get("cooldown_min_after_loss", 0)
        if cool:
            recent = self.store.closed_trades(limit=1)
            if recent and (recent[0].get("net_pnl") or 0) < 0 and recent[0].get("exit_ts"):
                gap = (ts - clock.to_ist(dt.datetime.fromisoformat(
                    recent[0]["exit_ts"]))).total_seconds() / 60.0
                if 0 <= gap < cool:
                    return d.block(f"cooldown after loss: {gap:.0f}/{cool} min")
        d.checks["cooldown"] = "PASS"

        # --- sizing off the stop, not off a fixed lot count ---
        sizing = spec.get("sizing", {})
        risk_pct = min(sizing.get("risk_per_trade_pct", 1.0),
                       self.cap["max_risk_per_trade_pct"])
        stop_pct = float(spec.get("exit", {}).get("stop_pct", 20.0))
        lot = int(contract["lot_size"] or 0)
        if lot <= 0:
            return d.block("unknown lot size")
        entry = self.costs.fill_price(
            "BUY", contract.get("bid", 0.0), contract.get("ask", 0.0),
            contract["mid"], depth=contract.get("ask_depth"), qty=lot)

        risk_budget = eq * risk_pct / 100.0
        risk_per_lot = entry * (stop_pct / 100.0) * lot \
            + self.costs.round_trip(entry, entry * (1 - stop_pct / 100.0), lot).total
        if risk_per_lot <= 0:
            return d.block("degenerate risk per lot")

        lots = int(risk_budget // risk_per_lot)
        lots = min(lots, sizing.get("max_lots", 1), self.cap["max_lots_per_position"])
        d.checks["risk_per_lot"] = round(risk_per_lot, 2)
        d.checks["risk_budget"] = round(risk_budget, 2)
        if lots < 1:
            need_pct = 100.0 * risk_per_lot / eq
            need_stop = 100.0 * (risk_budget - self.costs.round_trip(
                entry, entry, lot).total) / (entry * lot)
            d.checks["min_risk_pct_for_1_lot"] = round(need_pct, 2)
            d.checks["max_stop_pct_at_current_risk"] = round(max(need_stop, 0), 2)
            return d.block(
                f"1 lot risks Rs{risk_per_lot:,.0f} > budget Rs{risk_budget:,.0f}. "
                f"Needs risk_per_trade_pct >= {need_pct:.2f} or stop_pct <= "
                f"{max(need_stop, 0):.1f}, or a cheaper contract "
                f"(premium/lot Rs{entry * lot:,.0f})")

        # --- premium exposure ---
        premium = entry * lot * lots
        open_prem = sum((p.get("entry_px", 0) or 0) * (p.get("qty", 0) or 0)
                        for p in open_positions)
        max_prem = eq * min(sizing.get("max_premium_pct", 100.0),
                            self.cap["max_premium_deployed_pct"]) / 100.0
        if premium + open_prem > max_prem:
            return d.block(f"premium exposure Rs{premium + open_prem:,.0f} > "
                           f"cap Rs{max_prem:,.0f}")
        d.checks["premium_deployed"] = round(premium + open_prem, 2)

        # --- liquidity, re-checked at the ACTUAL size ---
        # Chain-build assessed this contract at one lot. Four lots is a
        # different question: it may be more than the touch can absorb, and
        # walking the book turns a 0.24% spread into something much worse.
        v = liq.assess(contract, lot * lots, self.cfg, self.costs,
                       contract.get("symbol"))
        d.checks["liquidity_at_size"] = v.to_dict()
        if not v.tradable:
            # Try to salvage it by cutting size rather than skipping outright.
            for smaller in range(lots - 1, 0, -1):
                v2 = liq.assess(contract, lot * smaller, self.cfg, self.costs,
                                contract.get("symbol"))
                if v2.tradable:
                    lots, v = smaller, v2
                    d.reasons.append(f"size cut to {smaller} lot(s) to fit the book")
                    premium = entry * lot * lots
                    break
            else:
                return d.block("book too thin at any size: " + "; ".join(v.reasons[:2]))

        # --- friction sanity: never pay a tax that eats half the target ---
        friction = v.total_friction_pct
        target_pct = float(spec.get("exit", {}).get("target_pct", 25.0))
        if friction > target_pct * 0.35:
            return d.block(f"round-trip friction {friction:.2f}% against a "
                           f"{target_pct:.0f}% target — not worth the ticket")
        d.checks["friction_pct"] = round(friction, 3)

        d.approved = True
        d.lots, d.qty = lots, lot * lots
        d.stop_px = round(entry * (1 - stop_pct / 100.0), 2)
        d.target_px = round(entry * (1 + target_pct / 100.0), 2)
        d.risk_amount = round(risk_per_lot * lots, 2)
        d.reasons.append(
            f"{lots} lot(s) x {lot} = {d.qty}, premium Rs{premium:,.0f}, "
            f"risk Rs{d.risk_amount:,.0f} ({risk_pct}%), charges {friction:.2f}%")
        return d
