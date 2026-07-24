"""Tradability: is this contract liquid enough, and is this tape volatile
enough, to justify buying premium?

Calibrated against real Zerodha books (23 Jul 2026):

    contract                   mid    spread   spread%  charges  total friction
    NIFTY 04AUG 23900 CE    210.65     0.50     0.24%    0.54%       0.77%
    BANKNIFTY JUL 56600 CE  421.00     2.00     0.48%    0.56%       1.03%
    RELIANCE AUG 1280 CE     33.67     0.25     0.74%    0.52%       1.26%
    RELIANCE JUL 1280 CE      7.72     0.15     1.94%    1.46%       3.40%

The last row is the whole lesson. Same underlying as the row above it, nearer
expiry, and it costs 2.7x as much to trade. Two things do that: the tick is
fixed at Rs 0.05, so on a Rs 7.72 option one tick is already 0.65% and the
narrowest quotable spread is expensive; and the flat Rs 20 brokerage is a far
bigger share of a Rs 3,862 ticket than a Rs 15,799 one.

So the highest-leverage liquidity rule is not open interest. It is a MINIMUM
PREMIUM. Cheap options look attractive - small ticket, big percentage moves -
and are the most reliably unprofitable thing an intraday buyer can hold.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

TICK = 0.05


@dataclass
class Verdict:
    tradable: bool = True
    reasons: list[str] = field(default_factory=list)
    spread_pct: float = 0.0
    spread_ticks: float = 0.0
    impact_pct: float = 0.0            # extra cost from walking the book
    total_friction_pct: float = 0.0    # charges + spread + impact, round trip
    lots_at_touch: float = 0.0
    score: float = 0.0

    def fail(self, why: str) -> "Verdict":
        self.tradable = False
        self.reasons.append(why)
        return self

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def rules_for(cfg: dict, symbol: str) -> dict:
    liq = cfg["liquidity"]
    kind = "index" if symbol.upper() in set(cfg["universe"]["indices"]) else "stock"
    return {**liq["common"], **liq[kind]}


def walk_book(depth: list[dict], qty: int, side: str = "BUY") -> float | None:
    """VWAP fill for `qty` against real 5-level depth. None if the book cannot
    fill it - which is itself a reason not to trade."""
    if not depth:
        return None
    levels = sorted(depth, key=lambda d: float(d["price"]),
                    reverse=(side == "SELL"))
    need, cost = qty, 0.0
    for lv in levels:
        take = min(need, int(lv.get("quantity") or 0))
        if take <= 0:
            continue
        cost += take * float(lv["price"])
        need -= take
        if need <= 0:
            return cost / qty
    return None


def assess(contract: dict, qty: int, cfg: dict, cost_model,
           symbol: str | None = None) -> Verdict:
    """One contract, one intended order size."""
    v = Verdict()
    sym = symbol or contract.get("symbol", "")
    R = rules_for(cfg, sym)

    bid = float(contract.get("bid") or 0.0)
    ask = float(contract.get("ask") or 0.0)
    mid = float(contract.get("mid") or contract.get("ltp") or 0.0)
    if mid <= 0:
        return v.fail("no price")

    # --- 1. minimum premium: the tick and the flat Rs 20 both bite here ---
    if mid < R["min_premium"]:
        v.fail(f"premium Rs{mid:.2f} below the Rs{R['min_premium']} floor "
               f"(one tick alone is {100 * TICK / mid:.2f}% here)")
    if mid > R["max_premium"]:
        v.fail(f"premium Rs{mid:.2f} above the Rs{R['max_premium']} cap")

    # --- 2. spread, in percent and in ticks ---
    if bid > 0 and ask > bid:
        v.spread_pct = 100.0 * (ask - bid) / mid
        v.spread_ticks = round((ask - bid) / TICK, 1)
    else:
        v.spread_pct = R["max_spread_pct"] * 2
        v.spread_ticks = 99.0
        v.fail("no two-sided quote")
    if v.spread_pct > R["max_spread_pct"]:
        v.fail(f"spread {v.spread_pct:.2f}% over the {R['max_spread_pct']}% limit")

    # --- 3. depth: can the book absorb our size at the touch? ---
    ask_depth = contract.get("ask_depth") or []
    bid_depth = contract.get("bid_depth") or []
    top_ask_qty = int((ask_depth[0]["quantity"] if ask_depth
                       else contract.get("ask_qty", 0)) or 0)
    lot = int(contract.get("lot_size") or 1)
    v.lots_at_touch = round(top_ask_qty / lot, 2) if lot else 0.0
    if top_ask_qty and qty > top_ask_qty * R["max_share_of_touch"]:
        v.fail(f"order of {qty} is more than {R['max_share_of_touch']:.0%} of "
               f"the {top_ask_qty} resting on the offer")

    fill_in = walk_book(ask_depth, qty, "BUY")
    fill_out = walk_book(bid_depth, qty, "SELL")
    if fill_in is None and ask_depth:
        v.fail("book cannot fill this size on the offer")
    if fill_in and fill_out and mid > 0:
        v.impact_pct = 100.0 * ((fill_in - ask) + (bid - fill_out)) / mid
        if v.impact_pct > R["max_impact_pct"]:
            v.fail(f"walking the book adds another {v.impact_pct:.2f}%")

    # --- 4. open interest and traded volume ---
    if float(contract.get("oi") or 0) < R["min_oi"]:
        v.fail(f"OI {float(contract.get('oi') or 0):,.0f} below {R['min_oi']:,}")
    if float(contract.get("volume") or 0) < R["min_volume"]:
        v.fail(f"volume {float(contract.get('volume') or 0):,.0f} "
               f"below {R['min_volume']:,}")

    # --- 5. the number that actually decides it ---
    charges = cost_model.friction_pct(mid, qty)
    v.total_friction_pct = round(charges + v.spread_pct + v.impact_pct, 4)
    if v.total_friction_pct > R["max_total_friction_pct"]:
        v.fail(f"round-trip friction {v.total_friction_pct:.2f}% over the "
               f"{R['max_total_friction_pct']}% limit "
               f"(charges {charges:.2f} + spread {v.spread_pct:.2f} "
               f"+ impact {v.impact_pct:.2f})")

    v.score = round(
        (float(contract.get("oi") or 0) / 1e6) * 2.0
        + min(v.lots_at_touch / 5.0, 2.0)
        - v.total_friction_pct * 1.5, 3)
    return v


def volatile_enough(feats: dict, cfg: dict) -> tuple[bool, list[str]]:
    """Is the tape moving enough to pay for the premium we would be buying?"""
    V = cfg["volatility"]
    fails = []
    if feats.get("atr_pct", 0) < V["min_atr_pct"]:
        fails.append(f"ATR {feats.get('atr_pct')}% under {V['min_atr_pct']}% "
                     f"- dead tape")
    if feats.get("expected_move_per_session_pct", 0) < V["min_expected_move_per_session_pct"]:
        fails.append(f"implied move/session "
                     f"{feats.get('expected_move_per_session_pct')}% too small")
    if feats.get("rv_iv_ratio", 0) < V["min_rv_iv_ratio"]:
        fails.append(f"realised/implied {feats.get('rv_iv_ratio')} under "
                     f"{V['min_rv_iv_ratio']} - options priced above what the "
                     f"tape is actually delivering")
    if feats.get("edge_ratio", 0) < V["min_edge_ratio"]:
        fails.append(f"edge ratio {feats.get('edge_ratio')} under "
                     f"{V['min_edge_ratio']}")
    if feats.get("realised_edge_ratio", 0) < V["min_realised_edge_ratio"]:
        fails.append(f"realised edge {feats.get('realised_edge_ratio')} under "
                     f"{V['min_realised_edge_ratio']} - the tape is not "
                     f"delivering what the premium costs")
    return (not fails), fails


def book_is_representative(ts) -> tuple[bool, str]:
    """Spreads at the open and into the closing auction are not the spreads you
    will actually trade. Measured 24-Jul-2026: BANKNIFTY 56700CE quoted 1.62%
    at 15:29, against 0.48% on the same contract at 12:47 the same day - a
    3x difference driven entirely by market makers stepping away. Any screen
    run outside the middle of the session should be treated as advisory."""
    from . import clock
    m = clock.minutes_into_session(ts)
    if m < 30:
        return False, "first 30 min - spreads not yet settled"
    if m > 345:
        return False, "closing auction - market makers withdrawing, spreads inflated"
    return True, ""


def rank_universe(feats_by_symbol: dict, snapshots: dict, cfg: dict) -> list[dict]:
    """Score every candidate underlying on liquidity x volatility, best first.
    Only the top N are handed to the strategy each cycle."""
    out = []
    for sym, f in feats_by_symbol.items():
        snap = snapshots.get(sym)
        if not snap:
            continue
        exp = snap["expiries"][snap["nearest_expiry"]]
        atm = [c for c in exp["contracts"]
               if abs(c.get("dist_from_atm", 99)) <= 2
               and (c.get("liquidity") or {}).get("tradable")]
        ok_vol, vol_fails = volatile_enough(f, cfg)
        if not atm:
            out.append({"symbol": sym, "score": -99.0, "tradable": False,
                        "why": ["no liquid near-ATM contract"] + vol_fails})
            continue
        liq = sum(c["liquidity"]["score"] for c in atm) / len(atm)
        friction = sum(c["liquidity"]["total_friction_pct"] for c in atm) / len(atm)
        vol = (f.get("edge_ratio", 0) + f.get("rv_iv_ratio", 0) * 1.5
               + f.get("atr_pct", 0) * 2.0)
        out.append({
            "symbol": sym,
            "score": round(liq + vol - (0.0 if ok_vol else 50.0), 3),
            "tradable": ok_vol,
            "liquidity_score": round(liq, 3),
            "avg_friction_pct": round(friction, 3),
            "liquid_atm_contracts": len(atm),
            "why": vol_fails,
        })
    out.sort(key=lambda x: -x["score"])
    return out
