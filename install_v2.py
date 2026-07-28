"""ONE-SHOT: install the v3 relaxed strategy. Run once, then delete."""
import json, sys
sys.path.insert(0, ".")
import yaml
from desk import clock
from desk import strategy as strat
from desk.store import Store

V3 = json.loads(r"""{"name": "V3_WideOpen_HardRiskOnly", "rationale": "v3: signal filters relaxed hard to generate trade data. rv/iv 0.85->0.70, friction cap 1.55->1.90%, liquid contracts 6->4, time-to-close 75->45min. Directional thresholds roughly halved (trend 0.40->0.20, vwap 0.06->0.03, adx 22->15) and realised_edge moved from mandatory into the any-of tier at 1.05. What is deliberately NOT relaxed: stops, targets, position sizing, the 1.5% risk cap, the 3%/day halt, the kill switch. Cost and liquidity floors are eased but kept, because trades filled at 3% friction on an illiquid strike produce garbage data, not learning.", "universe": ["NIFTY", "BANKNIFTY", "RELIANCE", "ICICIBANK"], "session": {"start": "09:30", "no_new_after": "14:45", "force_exit": "15:15"}, "selection": {"expiry": "skip_expiry_day", "min_sessions_left": 2.0, "delta_band": [0.3, 0.65], "max_spread_pct": 0.9, "min_oi": 100000, "max_premium_per_lot": 60000}, "entry_long_call": {"all": [{"feature": "rv_iv_ratio", "op": ">", "value": 0.7}, {"feature": "atm_total_friction_pct", "op": "<", "value": 1.9}, {"feature": "liquid_contracts", "op": ">=", "value": 4}, {"feature": "minutes_to_close", "op": ">", "value": 45}], "any": [{"feature": "trend_score", "op": ">", "value": 0.2}, {"feature": "vwap_dev_pct", "op": ">", "value": 0.03}, {"feature": "opening_range_break", "op": ">", "value": 0.5}, {"feature": "ema_fast_slow_pct", "op": ">", "value": 0.05}, {"feature": "adx_proxy", "op": ">", "value": 15}, {"feature": "realised_edge_ratio", "op": ">", "value": 1.05}], "none": [{"feature": "iv_vs_20d", "op": ">", "value": 1.5}, {"feature": "atm_one_tick_pct", "op": ">", "value": 0.2}]}, "entry_long_put": {"all": [{"feature": "rv_iv_ratio", "op": ">", "value": 0.7}, {"feature": "atm_total_friction_pct", "op": "<", "value": 1.9}, {"feature": "liquid_contracts", "op": ">=", "value": 4}, {"feature": "minutes_to_close", "op": ">", "value": 45}], "any": [{"feature": "trend_score", "op": "<", "value": -0.2}, {"feature": "vwap_dev_pct", "op": "<", "value": -0.03}, {"feature": "opening_range_break", "op": "<", "value": -0.5}, {"feature": "ema_fast_slow_pct", "op": "<", "value": -0.05}, {"feature": "adx_proxy", "op": ">", "value": 15}, {"feature": "realised_edge_ratio", "op": ">", "value": 1.05}], "none": [{"feature": "iv_vs_20d", "op": ">", "value": 1.5}, {"feature": "atm_one_tick_pct", "op": ">", "value": 0.2}]}, "exit": {"target_pct": 26.0, "stop_pct": 14.0, "trail_after_pct": 15.0, "trail_giveback_pct": 40.0, "time_stop_min": 50, "underlying_invalidation": {"feature": "vwap_dev_pct", "flip": true}, "iv_crush_exit_pct": 8.0}, "sizing": {"risk_per_trade_pct": 1.5, "max_lots": 4, "max_premium_pct": 20.0}, "risk": {"daily_loss_pct": 3.0, "max_trades_day": 4, "max_concurrent": 2, "cooldown_min_after_loss": 20}, "direction": "LONG_ONLY"}""")

cfg = yaml.safe_load(open("config.yaml"))
spec, notes = strat.clamp(V3, cfg)
st = Store()
nv = st.next_version()
st.save_strategy(nv, spec["name"], spec, spec["rationale"],
                 {"mode": "v3_relaxed"}, clock.now().isoformat(timespec="seconds"))
st.log(clock.now().isoformat(timespec="seconds"), "STRATEGY",
       "Installed v%d: %s" % (nv, spec["name"]),
       spec["rationale"][:300] + ((" | clamps: %s" % notes) if notes else ""))
print("Installed and activated v%d: %s" % (nv, spec["name"]))
