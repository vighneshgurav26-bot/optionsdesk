"""Trading journal: markdown for reading, CSV for spreadsheets, JSON for the
dashboard.

The journal records the reasoning, not just the fills — entry thesis, the
bull/bear debate, the greeks at entry and exit, the risk-gate checks, and every
blocked trade with its reason. A journal that only lists P&L can't teach the
next version anything.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from . import backtest

DOCS = Path("docs")
OUT = Path("state")


def write_all(store, cfg: dict, extra: dict | None = None) -> None:
    DOCS.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    capital = float(cfg["account"]["starting_capital"])
    closed = store.closed_trades(limit=2000)
    stats = backtest.summarise(closed, capital)
    curve = store.equity_curve()
    active = store.active_strategy()

    payload = {
        "generated": (curve[-1]["ts"] if curve else ""),
        "capital": capital,
        "equity": (curve[-1]["equity"] if curve else capital),
        "stats": stats,
        "open": store.open_trades(),
        "closed": closed[:60],
        "curve": [{"ts": c["ts"], "equity": c["equity"]} for c in curve][-500:],
        "strategy": {
            "version": active["version"] if active else 0,
            "name": active["name"] if active else "none",
            "rationale": active["rationale"] if active else "",
            "spec": active["spec"] if active else {},
            "backtest": json.loads(active["backtest"]) if active and active.get("backtest") else {},
        },
        "history": store.strategy_history(),
        "reviews": store.reviews(10),
        "journal": store.journal(120),
        **(extra or {}),
    }
    (DOCS / "data.json").write_text(json.dumps(payload, indent=1, default=str))

    _markdown(store, stats, active, closed)
    _csv(closed)


def _markdown(store, stats, active, closed) -> None:
    L = ["# Options Desk — Trading Journal", ""]
    if active:
        L += [f"**Strategy v{active['version']} — {active['name']}**", "",
              active["rationale"] or "", ""]
    L += ["## Performance", ""]
    for k, v in stats.items():
        if isinstance(v, dict):
            L.append(f"- **{k}**: " + ", ".join(f"{a}={b}" for a, b in v.items()))
        else:
            L.append(f"- **{k}**: {v}")
    L += ["", "## Strategy versions", "",
          "| v | name | status | created |", "|---|---|---|---|"]
    for s in store.strategy_history():
        L.append(f"| {s['version']} | {s['name']} | {s['status']} | {s['created_ts']} |")

    L += ["", "## Reviews", ""]
    for r in store.reviews(6):
        L += [f"### {r['ts']} — {r['trigger']} (v{r['from_version']} -> v{r['to_version']})",
              r["lessons"] or "", "", f"*Changes:* {r['changes'] or '-'}", ""]

    L += ["## Closed trades", "",
          "| entry | symbol | contract | lots | in | out | why | gross | charges | net |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for t in closed[:150]:
        L.append(
            f"| {t['entry_ts']} | {t['symbol']} | {t['tradingsymbol']} | {t['lots']} "
            f"| {t['entry_px']} | {t['exit_px']} | {t['exit_reason']} "
            f"| {t.get('gross_pnl')} | {t.get('costs')} | **{t.get('net_pnl')}** |")

    L += ["", "## Reasoning log", ""]
    for t in closed[:25]:
        L += [f"**{t['tradingsymbol']}** ({t['entry_ts']}) — net {t.get('net_pnl')}",
              "", f"> {t.get('thesis') or '-'}", ""]

    (OUT / "JOURNAL.md").write_text("\n".join(L))


def _csv(closed) -> None:
    if not closed:
        return
    cols = ["id", "strategy_version", "symbol", "tradingsymbol", "expiry",
            "strike", "opt_type", "lots", "qty", "entry_ts", "entry_px",
            "exit_ts", "exit_px", "exit_reason", "mfe_px", "mae_px",
            "gross_pnl", "costs", "net_pnl", "confidence", "thesis"]
    with (OUT / "trades.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(closed)
