"""Entrypoint. One call = one full cycle of the desk.

    python -m desk.run              # one cycle (use with cron / GH Actions)
    python -m desk.run --loop       # continuous, for a VPS
    python -m desk.run --review     # force a strategy review now
    python -m desk.run --backtest   # backtest the active spec, trade nothing
    python -m desk.run --reset      # wipe state and start fresh

Cycle: collect -> research -> debate -> risk gate -> paper trade -> journal,
with a self-review folded in when the trade count or idle clock says so.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

import yaml

from . import (backtest, chain, clock, features as feat_mod, journal,
               liquidity as liq, lots, providers, strategy as strat)
from .brain import Brain
from .costs import CostModel
from .engine import Engine
from .risk import RiskGate
from .store import Store

CFG_PATH = Path("config.yaml")


def load_cfg() -> dict:
    return yaml.safe_load(CFG_PATH.read_text())


# --------------------------------------------------------------------------
class Desk:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = Store()
        self.costs = CostModel(cfg)
        self.risk = RiskGate(cfg, self.store, self.costs)
        self.engine = Engine(cfg, self.store, self.costs, self.risk)
        self.brain = Brain(cfg)
        self.provider = providers.get_provider(cfg)
        try:
            cached = lots.refresh(self.provider)
            self.store.log(clock.now().isoformat(timespec="seconds"), "DATA",
                           f"Lot sizes from {cached['source']}",
                           f"{len(cached['lots'])} symbols cached")
        except Exception as exc:
            self.store.log(clock.now().isoformat(timespec="seconds"), "DATA",
                           "Lot size refresh failed, using cache/fallback",
                           str(exc)[:160])

    # ---------- collect ----------
    def collect(self, symbols: list[str], ts: dt.datetime):
        snaps, feats, candles = {}, {}, {}
        vix = None
        try:
            vix = self.provider.india_vix()
        except Exception:
            pass

        for sym in symbols:
            try:
                raw = self.provider.chain(sym)
            except Exception as exc:
                self.store.log(ts.isoformat(), "DATA", f"{sym}: chain fetch failed",
                               str(exc)[:200], sym)
                continue
            snap = chain.build(raw, self.cfg, ts, self.costs,
                               self.provider) if raw else None
            if not snap:
                self.store.log(ts.isoformat(), "DATA", f"{sym}: no usable chain",
                               "provider returned nothing tradable", sym)
                continue
            cs = providers.candles(sym, "5m", 5)
            candles[sym] = cs
            f = feat_mod.build(
                snap, cs, self.costs, self.cfg, vix,
                self.store.iv_history(sym),
                self.store.session_open_iv(sym, ts.date().isoformat()))
            snap["_features"] = f
            snaps[sym], feats[sym] = snap, f
            self.store.save_snapshot(snap, f)
        return snaps, feats, candles, vix

    # ---------- screening: liquidity x volatility ----------
    def screen(self, feats: dict, snaps: dict, ts: dt.datetime) -> list[str]:
        """Rank every underlying we have data for and keep the best N.

        This runs BEFORE the strategy rules, and the strategy cannot override
        it. An underlying with a wide book, a thin offer or a dead tape never
        reaches the entry logic no matter what the brain thinks of it.
        """
        ranked = liq.rank_universe(feats, snaps, self.cfg)
        keep = [r["symbol"] for r in ranked
                if r["tradable"] and r["score"] > 0][: self.cfg["universe"]["max_underlyings_live"]]
        self.store.log(
            ts.isoformat(timespec="seconds"), "SCREEN",
            f"Tradable now: {keep or 'none'}",
            " | ".join(
                f"{r['symbol']} score={r['score']} "
                f"friction={r.get('avg_friction_pct', '?')}% "
                f"liquid={r.get('liquid_atm_contracts', 0)}"
                + (f" REJECTED: {r['why'][0]}" if r.get("why") else "")
                for r in ranked),
            payload={"ranking": ranked})
        return keep

    # ---------- strategy bootstrap ----------
    def ensure_strategy(self, ts: dt.datetime) -> dict:
        active = self.store.active_strategy()
        if active:
            return active
        spec, notes = strat.clamp(strat.SEED_SPEC, self.cfg)
        self.store.save_strategy(1, spec["name"], spec, spec["rationale"],
                                 {"mode": "seed"}, ts.isoformat(timespec="seconds"))
        self.store.log(ts.isoformat(), "STRATEGY", "Seeded strategy v1",
                       spec["name"] + (f" | clamps: {notes}" if notes else ""))
        return self.store.active_strategy()

    # ---------- one cycle ----------
    def cycle(self, force_review: bool = False) -> None:
        ts = clock.now()
        active = self.ensure_strategy(ts)
        spec = active["spec"]
        version = active["version"]
        # Collect a wider pool than the strategy asked for, so the screen has
        # something to choose between and the brain can see what it is missing.
        pool = list(dict.fromkeys(
            (spec.get("universe") or [])
            + self.cfg["universe"]["indices"]
            + self.cfg["universe"]["stocks"][:6]))
        symbols = pool[:10]

        if not clock.is_market_open(ts):
            self.store.log(ts.isoformat(timespec="seconds"), "IDLE",
                           "Market closed", f"{ts:%a %d %b %H:%M} IST")
            if force_review or self._review_due(version, ts):
                self.review_and_evolve(version, spec, ts, {}, {})
            journal.write_all(self.store, self.cfg)
            return

        snaps, feats, candles, vix = self.collect(symbols, ts)
        if not snaps:
            self.store.log(ts.isoformat(timespec="seconds"), "IDLE",
                           "No market data this cycle",
                           "provider blocked or returned nothing")
            journal.write_all(self.store, self.cfg)
            return

        # 1. manage what's already open
        self.engine.manage(snaps, spec, ts)

        # 1b. screen for liquidity and volatility BEFORE any strategy logic
        tradable = self.screen(feats, snaps, ts)

        # 2. mark the book
        upnl, marked = self.engine.unrealised(snaps)
        eq = self.risk.equity(upnl)
        day = ts.date().isoformat()
        self.store.mark_equity(ts.isoformat(timespec="seconds"), eq,
                               self.store.realised_total(), upnl, len(marked),
                               self.store.realised_today(day))

        halted, why = self.risk.halted(eq, day)
        if halted:
            self.store.log(ts.isoformat(timespec="seconds"), "RISK", "Trading halted", why)
            journal.write_all(self.store, self.cfg)
            return

        # 3. does any rule fire at all? Cheap check before spending tokens.
        candidates = []
        for sym in tradable:
            f = feats.get(sym)
            if not f:
                continue
            for side, key in (("CE", "entry_long_call"), ("PE", "entry_long_put")):
                ok, fails = strat.evaluate(spec.get(key, {}), f)
                if ok:
                    want = spec.get("sizing", {}).get("max_lots", 1)
                    c, why_c = strat.select_contract(
                        snaps[sym], spec, side, self.costs, self.cfg, want)
                    if c:
                        candidates.append((sym, side, c, why_c))
                    else:
                        self.store.log(ts.isoformat(timespec="seconds"), "SKIP",
                                       f"{sym} {side} signal but no tradable contract",
                                       why_c, sym)

        if not candidates:
            self.store.log(
                ts.isoformat(timespec="seconds"), "SCAN",
                "No entry rule fired" if tradable else "Nothing passed the screen",
                " | ".join(f"{s}: edge={feats[s].get('edge_ratio')} "
                           f"rv/iv={feats[s].get('rv_iv_ratio')} "
                           f"trend={feats[s].get('trend_score')} "
                           f"friction={feats[s].get('atm_total_friction_pct')}%"
                           for s in tradable))
        else:
            self._consider(candidates, feats, snaps, spec, version, vix, ts, marked)

        # 4. learn
        if force_review or self._review_due(version, ts):
            self.review_and_evolve(version, spec, ts, snaps, candles)

        journal.write_all(self.store, self.cfg, {
            "features": feats, "india_vix": vix,
            "market_open": True, "marked": [
                {k: v for k, v in m.items() if k != "live_greeks"} for m in marked]})

    # ---------- research + debate + gate ----------
    def _consider(self, candidates, feats, snaps, spec, version, vix, ts, marked):
        if not self.brain.available:
            self.store.log(ts.isoformat(timespec="seconds"), "SKIP",
                           "Signal fired but ANTHROPIC_API_KEY is not set",
                           "the debate layer is mandatory before any entry")
            return
        try:
            brief = self.brain.research_brief(feats, snaps, vix)
        except Exception as exc:
            self.store.log(ts.isoformat(timespec="seconds"), "ERROR",
                           "Research call failed", str(exc)[:200])
            return
        self.store.log(ts.isoformat(timespec="seconds"), "RESEARCH",
                       "Research brief", brief[:1200])

        for sym, side, contract, why_c in candidates[:2]:
            try:
                d = self.brain.debate(sym, brief, feats[sym], side, contract, spec)
            except Exception as exc:
                self.store.log(ts.isoformat(timespec="seconds"), "ERROR",
                               f"Debate failed for {sym}", str(exc)[:200], sym)
                continue

            self.store.log(
                ts.isoformat(timespec="seconds"), "DEBATE",
                f"{sym} {side} -> {d['verdict']} ({d.get('confidence', 0):.2f})",
                f"BULL: {d.get('bull', '')[:500]}\n\nBEAR: {d.get('bear', '')[:500]}",
                sym, {"contract": why_c})

            if d["verdict"] != "TAKE" or d.get("confidence", 0) < 0.55:
                continue

            open_pos = self.store.open_trades()
            upnl, _ = self.engine.unrealised(snaps)
            decision = self.risk.evaluate(contract, spec, ts, upnl, open_pos)
            self.store.log(
                ts.isoformat(timespec="seconds"),
                "RISK", f"{sym} {side} gate: {'PASS' if decision.approved else 'BLOCK'}",
                " | ".join(decision.reasons), sym, {"checks": decision.checks})

            if decision.approved:
                self.engine.enter(contract, snaps[sym], feats[sym], spec, decision,
                                  d.get("thesis", ""), d.get("confidence", 0),
                                  json.dumps({"bull": d.get("bull"),
                                              "bear": d.get("bear"),
                                              "key_risk": d.get("key_risk"),
                                              "invalidation": d.get("invalidation")}),
                                  version, ts)
                return

    # ---------- review ----------
    def _review_due(self, version: int, ts: dt.datetime) -> bool:
        n = self.store.closed_count_since_version(version)
        if n >= self.cfg["brain"]["review_every_n_trades"]:
            return True
        last = self.store.last_trade_ts()
        idle_h = self.cfg["brain"]["review_after_idle_hours"]
        if last is None:
            active = self.store.active_strategy()
            created = active["created_ts"] if active else None
            if created:
                age = (ts - clock.to_ist(dt.datetime.fromisoformat(created))
                       ).total_seconds() / 3600.0
                return age >= idle_h
            return False
        gap = (ts - clock.to_ist(dt.datetime.fromisoformat(last))).total_seconds() / 3600.0
        return gap >= idle_h

    def review_and_evolve(self, version: int, spec: dict, ts: dt.datetime,
                          snaps: dict, candles: dict) -> None:
        if not self.brain.available:
            return
        closed = self.store.closed_trades(limit=200, version=version)
        stats = backtest.summarise(closed, self.cfg["account"]["starting_capital"])
        traded = len(closed)
        trigger = "trade_count" if traded >= self.cfg["brain"]["review_every_n_trades"] \
            else "idle"

        context = {
            "trigger": trigger,
            "current_strategy": spec,
            "current_version": version,
            "performance": stats,
            "recent_trades": [{k: t.get(k) for k in (
                "symbol", "tradingsymbol", "entry_ts", "exit_ts", "entry_px",
                "exit_px", "exit_reason", "mfe_px", "mae_px", "gross_pnl",
                "costs", "net_pnl", "confidence", "thesis")} for t in closed[:40]],
            "entry_greeks_sample": [json.loads(t.get("entry_greeks") or "{}")
                                    for t in closed[:15]],
            "blocked_and_skipped": [
                {"ts": j["ts"], "kind": j["kind"], "headline": j["headline"],
                 "detail": j["detail"][:300]}
                for j in self.store.journal(120)
                if j["kind"] in ("SKIP", "RISK", "SCAN")][:40],
            "past_versions": self.store.strategy_history(8),
            "past_reviews": [{"ts": r["ts"], "lessons": r["lessons"],
                              "changes": r["changes"]}
                             for r in self.store.reviews(4)],
            "hard_ceilings": self.cfg["risk_ceiling"],
            "note": ("If the desk has not traded, the entry rules are too tight. "
                     "A strategy that never fires learns nothing."
                     if traded == 0 else ""),
        }

        try:
            rv = self.brain.review(context)
        except Exception as exc:
            self.store.log(ts.isoformat(timespec="seconds"), "ERROR",
                           "Review call failed", str(exc)[:200])
            return
        if not rv:
            return

        self.store.log(ts.isoformat(timespec="seconds"), "REVIEW",
                       f"v{version} review: {rv.get('action')}",
                       (rv.get("lessons", "") + "\n\nDIAGNOSIS: "
                        + rv.get("diagnosis", ""))[:1500])

        if rv.get("action") == "KEEP":
            self.store.save_review(ts.isoformat(timespec="seconds"), trigger,
                                   version, version, stats, rv.get("lessons", ""),
                                   "kept", json.dumps(rv))
            return

        context["review"] = rv
        try:
            proposed = self.brain.author_strategy(context)
        except Exception as exc:
            self.store.log(ts.isoformat(timespec="seconds"), "ERROR",
                           "Strategy authoring failed", str(exc)[:200])
            return
        if not proposed:
            return

        new_spec, notes = strat.clamp(proposed, self.cfg)

        # Champion/challenger: the proposal must beat the incumbent on the same
        # data before it is allowed to trade. This is the guard against the bot
        # "learning" its way into an overfit that only looks good in prose.
        symbols = new_spec.get("universe", ["NIFTY"])
        bt_new = backtest.replay(self.store, new_spec, self.cfg, self.costs, symbols)
        bt_old = backtest.replay(self.store, spec, self.cfg, self.costs, symbols)
        if bt_new.get("trades", 0) == 0 and snaps:
            bt_new = backtest.synthetic(self.store, new_spec, self.cfg,
                                        self.costs, snaps, candles)
            bt_old = backtest.synthetic(self.store, spec, self.cfg,
                                        self.costs, snaps, candles)

        promo = self.cfg["brain"]["promotion"]
        reasons = []
        enough = bt_new.get("trades", 0) >= promo["min_backtest_trades"]
        better = (bt_new.get("expectancy") or -1e9) > (bt_old.get("expectancy") or -1e9)
        positive = (bt_new.get("expectancy") or 0) > 0

        if not enough:
            reasons.append(f"only {bt_new.get('trades', 0)} backtest trades "
                           f"(need {promo['min_backtest_trades']})")
        if not better:
            reasons.append("does not beat the incumbent's expectancy")
        if promo["require_positive_expectancy"] and not positive:
            reasons.append("expectancy is not positive")

        # A version that never trades is worse than a mediocre one that does:
        # allow promotion out of a zero-trade incumbent even on weak evidence.
        rescue = (bt_old.get("trades", 0) == 0 and bt_new.get("trades", 0) > 0)

        if reasons and not rescue:
            self.store.log(ts.isoformat(timespec="seconds"), "STRATEGY",
                           f"Rejected proposal '{proposed.get('name')}'",
                           "; ".join(reasons), payload={"backtest": bt_new})
            self.store.save_review(ts.isoformat(timespec="seconds"), trigger,
                                   version, version, stats, rv.get("lessons", ""),
                                   "proposal rejected: " + "; ".join(reasons),
                                   json.dumps({"review": rv, "proposal": proposed}))
            return

        nv = self.store.next_version()
        self.store.save_strategy(nv, new_spec.get("name", f"v{nv}"), new_spec,
                                 new_spec.get("rationale", ""), bt_new,
                                 ts.isoformat(timespec="seconds"))
        self.store.save_review(ts.isoformat(timespec="seconds"), trigger, version,
                               nv, stats, rv.get("lessons", ""),
                               rv.get("changes", ""), json.dumps(rv))
        self.store.log(
            ts.isoformat(timespec="seconds"), "STRATEGY",
            f"Promoted v{nv}: {new_spec.get('name')}",
            f"{new_spec.get('rationale', '')[:400]} | backtest: "
            f"{bt_new.get('trades')} trades, expectancy {bt_new.get('expectancy')}, "
            f"PF {bt_new.get('profit_factor')} ({bt_new.get('mode')}/"
            f"{bt_new.get('confidence')})"
            + (f" | clamps: {notes}" if notes else "")
            + (" | RESCUE: incumbent never traded" if rescue else ""),
            payload={"backtest": bt_new})


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=0)
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    cfg = load_cfg()

    if a.reset:
        for p in (Path("state/desk.db"), Path("docs/data.json")):
            if p.exists():
                p.unlink()
        print("State cleared.")
        return 0

    desk = Desk(cfg)

    if a.backtest:
        spec = desk.ensure_strategy(clock.now())["spec"]
        syms = spec.get("universe", ["NIFTY"])
        rep = backtest.replay(desk.store, spec, cfg, desk.costs, syms)
        print(json.dumps(rep, indent=2))
        if rep.get("trades", 0) == 0:
            snaps, feats, candles, _ = desk.collect(syms, clock.now())
            print(json.dumps(backtest.synthetic(desk.store, spec, cfg, desk.costs,
                                                snaps, candles), indent=2))
        return 0

    interval = a.interval or cfg["data"]["snapshot_interval_sec"]
    while True:
        try:
            desk.cycle(force_review=a.review)
        except Exception:
            traceback.print_exc()
            desk.store.log(clock.now().isoformat(timespec="seconds"), "ERROR",
                           "Cycle crashed", traceback.format_exc()[-800:])
        if not a.loop:
            break
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
