"""Zerodha cost model for NSE option orders.

Charges are per EXECUTED ORDER, not per lot, which is why the desk is biased
toward fewer, bigger clips. Measured against real books on 23 Jul 2026:

    NIFTY 04AUG 23900 CE  1 lot (75)   Rs 15,799 ticket -> charges 0.54%
    RELIANCE JUL 1280 CE  1 lot (500)  Rs  3,862 ticket -> charges 1.46%

Same schedule, 2.7x the drag, purely because the flat Rs 20 is a bigger share
of a small ticket. Every backtest and every paper fill runs through here.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class CostBreakdown:
    brokerage: float = 0.0
    stt: float = 0.0
    txn: float = 0.0
    sebi: float = 0.0
    ipft: float = 0.0
    stamp: float = 0.0
    gst: float = 0.0
    slippage: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict:
        return {k: round(v, 2) for k, v in asdict(self).items()}

    def __add__(self, other: "CostBreakdown") -> "CostBreakdown":
        return CostBreakdown(**{k: getattr(self, k) + getattr(other, k)
                                for k in asdict(self)})


class CostModel:
    def __init__(self, cfg: dict):
        c = cfg["costs"]
        self.brokerage = float(c["brokerage_per_order"])
        self.stt_sell = float(c["stt_sell_pct"]) / 100.0
        self.txn = float(c["txn_charge_pct"]) / 100.0
        self.sebi = float(c["sebi_pct"]) / 100.0
        self.ipft = float(c["ipft_pct"]) / 100.0
        self.stamp_buy = float(c["stamp_buy_pct"]) / 100.0
        self.gst = float(c["gst_pct"]) / 100.0
        self.slippage_ticks = int(c["slippage_ticks"])
        self.tick = float(c["tick_size"])
        self.synthetic_spread = c["synthetic_spread_pct"]

    # ---------------- fills ----------------
    def fill_price(self, side: str, bid: float, ask: float, ltp: float,
                   kind: str = "index_liquid", depth: list | None = None,
                   qty: int = 0) -> float:
        """Buys lift the ask, sells hit the bid, both pay slippage ticks.

        When 5-level depth is available and the order is bigger than the touch,
        the fill is the VWAP of walking the book — which is what actually
        happens, and what makes an over-sized order visibly expensive.
        """
        base = None
        if depth and qty > 0:
            from .liquidity import walk_book
            base = walk_book(depth, qty, side)
        if base is None:
            if bid and ask and ask > bid > 0:
                base = ask if side == "BUY" else bid
            else:
                half = ltp * (self.synthetic_spread.get(kind, 1.0) / 100.0) / 2.0
                base = ltp + half if side == "BUY" else ltp - half
        slip = self.slippage_ticks * self.tick
        px = base + slip if side == "BUY" else base - slip
        return round(max(round(px / self.tick) * self.tick, self.tick), 2)

    def spread_pct(self, bid: float, ask: float, ltp: float) -> float:
        if bid and ask and ask > bid > 0:
            mid = 0.5 * (bid + ask)
            return 100.0 * (ask - bid) / mid if mid > 0 else 999.0
        return 999.0

    # ---------------- charges ----------------
    def leg_cost(self, side: str, price: float, qty: int) -> CostBreakdown:
        """One executed order. qty = lot_size * lots (number of shares)."""
        turnover = price * qty
        b = CostBreakdown()
        b.brokerage = self.brokerage
        b.txn = turnover * self.txn
        b.sebi = turnover * self.sebi
        b.ipft = turnover * self.ipft
        if side == "SELL":
            b.stt = turnover * self.stt_sell
        else:
            b.stamp = turnover * self.stamp_buy
        b.gst = (b.brokerage + b.sebi + b.txn) * self.gst
        b.total = b.brokerage + b.stt + b.txn + b.sebi + b.ipft + b.stamp + b.gst
        return b

    def round_trip(self, entry_px: float, exit_px: float,
                   qty: int) -> CostBreakdown:
        return self.leg_cost("BUY", entry_px, qty) + \
            self.leg_cost("SELL", exit_px, qty)

    def breakeven_exit(self, entry_px: float, qty: int,
                       tol: float = 0.01, iters: int = 40) -> float:
        """Exit premium at which the trade nets exactly zero after all charges.
        Solved rather than approximated, because STT scales with the exit."""
        lo, hi = entry_px, entry_px * 2.0 + 50.0
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            pnl = (mid - entry_px) * qty - self.round_trip(entry_px, mid, qty).total
            if abs(pnl) < tol:
                return mid
            lo, hi = (mid, hi) if pnl < 0 else (lo, mid)
        return 0.5 * (lo + hi)

    def friction_pct(self, entry_px: float, qty: int) -> float:
        """Round-trip charges as a % of premium paid. The hurdle rate."""
        notional = entry_px * qty
        if notional <= 0:
            return 100.0
        return 100.0 * self.round_trip(entry_px, entry_px, qty).total / notional
