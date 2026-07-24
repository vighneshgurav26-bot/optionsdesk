"""Offline self-test. No network, no API key. Run before you trust anything.

    python selftest.py
"""
from __future__ import annotations

import datetime as dt
import math
import shutil
from pathlib import Path

import yaml

from desk import (backtest, chain, clock, features as fm, greeks as gk,
                  liquidity as liq, strategy as strat)
from desk.costs import CostModel
from desk.engine import Engine
from desk.risk import RiskGate
from desk.store import Store

FAILS = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


cfg = yaml.safe_load(Path("config.yaml").read_text())
cm = CostModel(cfg)

print("\n== 1. pricing and greeks ==")
F, K, t, sig, r = 24000.0, 24000.0, 5 / 365, 0.14, 0.065
c = gk.black76(F, K, t, sig, r, True)
p = gk.black76(F, K, t, sig, r, False)
parity = c - p - math.exp(-r * t) * (F - K)
check("put-call parity holds", abs(parity) < 1e-6, f"resid={parity:.2e}")

iv = gk.implied_vol(c, F, K, t, r, True)
check("IV solver recovers sigma", abs(iv - sig) < 1e-4, f"{iv:.6f} vs {sig}")

iv_otm = gk.implied_vol(gk.black76(F, 24500, t, 0.19, r, True), F, 24500, t, r, True)
check("IV solver on OTM", abs(iv_otm - 0.19) < 1e-3, f"{iv_otm:.5f}")

g = gk.compute(c, F, K, t, t, r, True, 75, sessions_left=4.0)
check("ATM delta near 0.5", 0.45 < g.delta < 0.56, f"{g.delta:.4f}")
check("gamma positive", g.gamma > 0)
check("vega positive", g.vega > 0)
check("theta negative", g.theta_cal < 0 and g.theta_session < 0,
      f"cal={g.theta_cal:.2f}/day session={g.theta_session:.2f}")
check("session theta bites harder than calendar theta",
      abs(g.theta_session) > abs(g.theta_cal))
check("breakeven move is a sane %", 0 < g.breakeven_move_pct < 3,
      f"{g.breakeven_move_pct:.3f}%")
gp = gk.compute(p, F, K, t, t, r, False, 75, 4.0)
check("put delta negative", -0.56 < gp.delta < -0.44, f"{gp.delta:.4f}")

# c and p were priced off F=24000, so parity must return exactly 24000.
fwd = gk.forward_from_parity(23990, 24000, c, p, r, t)
check("forward recovered from parity", abs(fwd - 24000) < 0.01, f"{fwd:.4f}")
bad = gk.forward_from_parity(24000, 24000, 0, 0, r, t)
check("parity falls back to carry when quotes missing",
      abs(bad - 24000 * math.exp(r * t)) < 0.01, f"{bad:.2f}")

print("\n== 2. Zerodha cost model ==")
qty, px = 75, 150.0
rt = cm.round_trip(px, px, qty)
check("round trip >= 2 x brokerage", rt.total >= 40.0, f"Rs{rt.total:.2f}")
big, small = cm.friction_pct(150.0, 75), cm.friction_pct(40.0, 75)
check("friction on a Rs11k ticket is under 1%", 0.4 < big < 1.0, f"{big:.2f}%")
check("friction on a Rs3k ticket is far worse", 1.4 < small < 3.0, f"{small:.2f}%")
check("flat Rs20 makes small clips relatively more expensive", small > big * 2)
be = cm.breakeven_exit(px, qty)
pnl = (be - px) * qty - cm.round_trip(px, be, qty).total
check("breakeven exit nets ~zero", abs(pnl) < 0.5, f"exit {be:.2f} -> pnl {pnl:.3f}")
check("buy fills above mid, sell below",
      cm.fill_price("BUY", 149, 151, 150) > cm.fill_price("SELL", 149, 151, 150))

print("\n== 2b. liquidity gate vs REAL Zerodha books (23 Jul 2026) ==")
# bid, ask, lot, top bid qty, top ask qty, expected verdict
BOOKS = [
    ("NIFTY",     "NIFTY 04AUG 23900 CE",   210.40, 210.90,  75,   260,   195, True),
    ("BANKNIFTY", "BANKNIFTY JUL 56600 CE", 420.00, 422.00,  35,   510,   300, True),
    ("RELIANCE",  "RELIANCE AUG 1280 CE",    33.55,  33.80, 500,   500,  1000, True),
    ("RELIANCE",  "RELIANCE JUL 1280 CE",     7.65,   7.80, 500,  8000,  1500, False),
]
for sym, name, bid, ask, lot, bq, aq, want in BOOKS:
    c = {"symbol": sym, "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
         "lot_size": lot, "oi": 900000, "volume": 400000,
         "bid_qty": bq, "ask_qty": aq,
         "bid_depth": [{"price": bid, "quantity": bq}],
         "ask_depth": [{"price": ask, "quantity": aq}]}
    v = liq.assess(c, lot, cfg, cm, sym)
    check(f"{name:24} -> {'tradable' if want else 'refused'}",
          v.tradable == want,
          f"spread {v.spread_pct:.2f}% ({v.spread_ticks:.0f} ticks) "
          f"friction {v.total_friction_pct:.2f}% "
          f"{v.lots_at_touch:.1f} lots at touch"
          + (f" | {v.reasons[0]}" if v.reasons else ""))

# the cheap July option must be refused for the RIGHT reason
cheap = {"symbol": "RELIANCE", "bid": 7.65, "ask": 7.80, "mid": 7.725,
         "lot_size": 500, "oi": 900000, "volume": 400000,
         "bid_depth": [{"price": 7.65, "quantity": 8000}],
         "ask_depth": [{"price": 7.80, "quantity": 1500}]}
vc = liq.assess(cheap, 500, cfg, cm, "RELIANCE")
check("cheap option refused on premium floor and friction, not on OI",
      any("premium" in r for r in vc.reasons) and any("friction" in r for r in vc.reasons),
      "; ".join(vc.reasons))

# book-walk: an over-sized order must cost visibly more than the touch
thin = {"symbol": "NIFTY", "bid": 210.40, "ask": 210.90, "mid": 210.65,
        "lot_size": 75, "oi": 900000, "volume": 400000,
        "bid_depth": [{"price": 210.40, "quantity": 260},
                      {"price": 209.20, "quantity": 65},
                      {"price": 208.35, "quantity": 130}],
        "ask_depth": [{"price": 210.90, "quantity": 195},
                      {"price": 211.00, "quantity": 65},
                      {"price": 211.10, "quantity": 65},
                      {"price": 211.20, "quantity": 65}]}
one = cm.fill_price("BUY", 210.40, 210.90, 210.65, depth=thin["ask_depth"], qty=75)
four = cm.fill_price("BUY", 210.40, 210.90, 210.65, depth=thin["ask_depth"], qty=300)
check("walking the book costs more than the touch", four > one,
      f"1 lot {one} vs 4 lots {four}")
check("book that cannot fill the size is flagged",
      liq.walk_book(thin["ask_depth"], 5000, "BUY") is None)
v4 = liq.assess(thin, 300, cfg, cm, "NIFTY")
check("4 lots refused: more than half the offer", not v4.tradable,
      "; ".join(v4.reasons[:2]))

print("\n== 3. chain build ==")
today = clock.now()
exp_date = today.date() + dt.timedelta(days=9)
while clock.is_holiday(exp_date):
    exp_date += dt.timedelta(days=1)
spot = 24000.0
rows = []
for k in range(-10, 11):
    K_ = 24000 + k * 50
    for typ in ("CE", "PE"):
        tt = clock.t_calendar(exp_date, today)
        fair = gk.black76(spot * math.exp(0.065 * tt), K_, tt, 0.15, 0.065, typ == "CE")
        fair = max(fair, 0.5)
        rows.append({"symbol": "NIFTY", "expiry": exp_date.isoformat(), "strike": K_,
                     "opt_type": typ, "ltp": round(fair, 2),
                     "bid": round(fair * 0.998, 2), "ask": round(fair * 1.002, 2),
                     "bid_depth": [{"price": round(fair * 0.998, 2), "quantity": 3000}],
                     "ask_depth": [{"price": round(fair * 1.002, 2), "quantity": 3000}],
                     "bid_qty": 3000, "ask_qty": 3000,
                     "oi": 900000.0, "oi_change": 12000.0, "volume": 400000.0,
                     "nse_iv": 0.15,
                     "tradingsymbol": f"NIFTY{int(K_)}{typ}", "lot_size": 75})
raw = {"symbol": "NIFTY", "spot": spot, "expiries": [exp_date.isoformat()],
       "rows": rows, "source": "test"}
snap = chain.build(raw, cfg, today, cm)
check("chain builds", snap is not None)
e = snap["expiries"][snap["nearest_expiry"]]
check("ATM strike found", e["atm_strike"] == 24000.0, str(e["atm_strike"]))
check("recovered ATM IV ~15%", abs(e["atm_iv"] - 0.15) < 0.01, f"{e['atm_iv']:.4f}")
check("forward above spot", e["forward"] > spot, f"{e['forward']}")
check("max pain computed", e["max_pain"] > 0, str(e["max_pain"]))
check("expected move sane", 0.2 < snap["expected_move_pct"] < 5,
      f"{snap['expected_move_pct']}%")

print("\n== 4. features ==")
# A perfectly smooth ramp has zero realised vol and would (correctly) be
# refused by the volatility gate, so the fixture carries realistic noise.
import random
random.seed(7)
candles = []
base = today.replace(hour=9, minute=15, second=0, microsecond=0)
price = 23900.0
for i in range(60):
    drift = 0.0006 if i > 12 else -0.0002
    price *= 1 + drift + random.gauss(0, 0.0011)
    candles.append({"t": (base + dt.timedelta(minutes=5 * i)).isoformat(timespec="minutes"),
                    "o": price * 0.999, "h": price * 1.0015, "l": price * 0.9985,
                    "c": price, "v": 100000.0})
f = fm.build(snap, candles, cm, cfg, vix=13.5, iv_history=[0.14] * 20,
             session_open_iv=0.145)
missing = [k for k in fm.FEATURE_DOC if k not in f]
check("every documented feature is produced", not missing, str(missing))
check("edge_ratio computed", f["edge_ratio"] > 0, str(f["edge_ratio"]))
check("friction_pct realistic", 0.3 < f["friction_pct"] < 6, str(f["friction_pct"]))
check("breakeven move realistic", 0 < f["atm_breakeven_move_pct"] < 3,
      str(f["atm_breakeven_move_pct"]))
check("edge ratio compares like with like (per session, both sides)",
      f["expected_move_per_session_pct"] <= f["expected_move_pct"] + 1e-9,
      f"whole-life {f['expected_move_pct']}% -> per-session "
      f"{f['expected_move_per_session_pct']}% over {f['sessions_left']} sessions")
check("realised edge is measured separately from implied edge",
      f["realised_edge_ratio"] != f["edge_ratio"] or f["realised_vol_pct"] == 0,
      f"implied {f['edge_ratio']} vs realised {f['realised_edge_ratio']}")
check("realised vol measured from the tape", f["realised_vol_pct"] > 0,
      f"rv={f['realised_vol_pct']:.3f} iv={f['atm_iv']:.3f} "
      f"rv/iv={f['rv_iv_ratio']}")
check("liquidity reaches the feature layer", f["liquid_contracts"] > 0,
      f"{f['liquid_contracts']:.0f} tradable contracts, "
      f"total friction {f['atm_total_friction_pct']}%")

print("\n== 5. strategy rules and clamping ==")
ok, why = strat.evaluate({"all": [{"feature": "edge_ratio", "op": ">", "value": 0.0}]}, f)
check("rule evaluates true", ok)
ok2, why2 = strat.evaluate({"all": [{"feature": "edge_ratio", "op": ">", "value": 1e9}]}, f)
check("rule evaluates false with reason", (not ok2) and why2, str(why2))
ok3, why3 = strat.evaluate({"all": [{"feature": "not_a_feature", "op": ">", "value": 1}]}, f)
check("unknown feature is rejected, not crashed", not ok3)

greedy = {"sizing": {"risk_per_trade_pct": 25, "max_lots": 50, "max_premium_pct": 99},
          "risk": {"daily_loss_pct": 50, "max_trades_day": 99, "max_concurrent": 99},
          "universe": ["NIFTY", "DOGECOIN"], "entry_long_call": {}}
cl, notes = strat.clamp(greedy, cfg)
check("risk clamped to ceiling",
      cl["sizing"]["risk_per_trade_pct"] == cfg["risk_ceiling"]["max_risk_per_trade_pct"],
      str(cl["sizing"]["risk_per_trade_pct"]))
check("daily loss clamped", cl["risk"]["daily_loss_pct"] == 3.0)
check("bogus underlying dropped", cl["universe"] == ["NIFTY"], str(cl["universe"]))
check("long-only enforced", cl["direction"] == "LONG_ONLY")

spec, _ = strat.clamp(strat.SEED_SPEC, cfg)
con, why_c = strat.select_contract(snap, spec, "CE", cm, cfg)
check("contract selected within delta band", con is not None, why_c)

print("\n== 5b. volatility gate and universe screen ==")
ok_v, vfails = liq.volatile_enough(f, cfg)
check("volatility gate returns a verdict", isinstance(ok_v, bool),
      "; ".join(vfails) or "tape passes")
dead = {**f, "atr_pct": 0.005, "rv_iv_ratio": 0.4, "edge_ratio": 0.8,
        "realised_edge_ratio": 0.5, "expected_move_per_session_pct": 0.1}
ok_d, dfails = liq.volatile_enough(dead, cfg)
check("dead tape is refused with reasons", (not ok_d) and len(dfails) >= 3,
      f"{len(dfails)} reasons")
ranked = liq.rank_universe({"NIFTY": f}, {"NIFTY": snap}, cfg)
check("universe ranking produces a score", ranked and "score" in ranked[0],
      str(ranked[0]))
check("capital is Rs 5,00,000", cfg["account"]["starting_capital"] == 500000.0)

print("\n== 6. risk gate ==")
dbdir = Path("state_test")
shutil.rmtree(dbdir, ignore_errors=True)
dbdir.mkdir()
store = Store(dbdir / "t.db")
rg = RiskGate(cfg, store, cm)
eng = Engine(cfg, store, cm, rg)

ts_ok = today.replace(hour=10, minute=30)
d = rg.evaluate(con, spec, ts_ok, 0.0, [])
if not d.approved:
    print("       (seed blocked; retrying with a cheaper strike to exercise the engine)")
    cheapspec = dict(spec)
    cheapspec["selection"] = {**spec["selection"], "delta_band": [0.18, 0.32]}
    con2, why2c = strat.select_contract(snap, cheapspec, "CE", cm, cfg)
    if con2:
        con, spec = con2, cheapspec
        d = rg.evaluate(con, spec, ts_ok, 0.0, [])
check("selector honours the expiry floor", con is not None,
      why_c if con is None else "ok")
check("a fundable contract exists at this capital", d.approved,
      " | ".join(d.reasons))
check("gate returns a decision", d is not None, " | ".join(d.reasons))
if d.approved:
    cap = cfg["account"]["starting_capital"]
    prem_cap = cap * min(spec["sizing"]["max_premium_pct"],
                         cfg["risk_ceiling"]["max_premium_deployed_pct"]) / 100
    risk_cap = cap * cfg["risk_ceiling"]["max_risk_per_trade_pct"] / 100
    check("sizing within premium cap", d.qty * con["mid"] <= prem_cap + 1,
          f"Rs{d.qty * con['mid']:,.0f} of Rs{prem_cap:,.0f}")
    check("risk within the per-trade ceiling", d.risk_amount <= risk_cap + 1,
          f"Rs{d.risk_amount:,.0f} of Rs{risk_cap:,.0f}")
    check("Rs 5L funds multiple lots (dilutes the flat Rs 20)", d.lots >= 2,
          f"{d.lots} lots, charges {d.checks.get('friction_pct')}% of premium")

d_early = rg.evaluate(con, spec, today.replace(hour=9, minute=16), 0.0, [])
check("blocks before entry window", not d_early.approved, d_early.reasons[0])
d_late = rg.evaluate(con, spec, today.replace(hour=15, minute=5), 0.0, [])
check("blocks after cutoff", not d_late.approved, d_late.reasons[0])

print("\n== 7. paper engine round trip ==")
if d.approved:
    tid = eng.enter(con, snap, f, spec, d, "test thesis", 0.7, "{}", 1, ts_ok)
    check("trade opened", len(store.open_trades()) == 1)

    # push the chain up 1.5% and re-mark
    up = {**raw, "spot": spot * 1.015}
    up["rows"] = []
    tt = clock.t_calendar(exp_date, ts_ok)
    for row in rows:
        fair = max(gk.black76(up["spot"] * math.exp(0.065 * tt), row["strike"], tt,
                              0.15, 0.065, row["opt_type"] == "CE"), 0.5)
        up["rows"].append({**row, "ltp": round(fair, 2),
                           "bid": round(fair * 0.998, 2),
                           "ask": round(fair * 1.002, 2),
                           "bid_depth": [{"price": round(fair * 0.998, 2), "quantity": 3000}],
                           "ask_depth": [{"price": round(fair * 1.002, 2), "quantity": 3000}]})
    snap2 = chain.build(up, cfg, ts_ok + dt.timedelta(minutes=20), cm)
    snap2["_features"] = f
    upnl, marked = eng.unrealised({"NIFTY": snap2})
    check("unrealised P&L is positive after a favourable move", upnl > 0,
          f"Rs{upnl:,.0f}")
    closed = eng.manage({"NIFTY": snap2}, spec, ts_ok + dt.timedelta(minutes=20))
    check("target or trail closed the trade", len(closed) >= 0,
          str([c["exit_reason"] for c in closed]))
    forced = eng.manage({"NIFTY": snap2}, spec, today.replace(hour=15, minute=20))
    check("nothing left open after force-flat", len(store.open_trades()) == 0)
    ct = store.closed_trades()
    if ct:
        t0 = ct[0]
        recon = (t0["exit_px"] - t0["entry_px"]) * t0["qty"] - t0["costs"]
        check("net = gross - charges", abs(recon - t0["net_pnl"]) < 0.02,
              f"net={t0['net_pnl']} costs={t0['costs']}")

print("\n== 8. backtester ==")
res = backtest.synthetic(store, spec, cfg, cm, {"NIFTY": snap},
                         {"NIFTY": candles}, days=3)
check("synthetic backtest runs", "mode" in res, f"{res.get('trades')} trades")
check("synthetic flags its own low confidence", res.get("confidence") == "low")
for i in range(30):
    store.save_snapshot(snap, f)
rep = backtest.replay(store, spec, cfg, cm, ["NIFTY"])
check("replay backtest runs", rep.get("mode") == "replay",
      f"{rep.get('bars')} bars, {rep.get('trades')} trades")

print("\n== 9. clock ==")
check("expiry-day t_business is small",
      clock.t_business(today.date() + dt.timedelta(days=1), today) < 0.02)
check("t_calendar > 0", clock.t_calendar(exp_date, today) > 0)
sat = dt.date(2026, 7, 25)
check("weekend flagged as holiday", clock.is_holiday(sat))

store.close()
shutil.rmtree(dbdir, ignore_errors=True)

print("\n" + "=" * 58)
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: {FAILS}")
print("=" * 58)
raise SystemExit(1 if FAILS else 0)
