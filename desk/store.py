"""Persistence. One SQLite file holds everything the desk knows.

Chain snapshots are archived on every run because there is no free source of
historical Indian option premiums — the desk builds its own history, and the
backtester gets more honest every day it runs.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("state/desk.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, symbol TEXT NOT NULL, spot REAL,
  expiry TEXT, atm_iv REAL, features TEXT, chain TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(symbol, ts);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_version INTEGER, symbol TEXT, tradingsymbol TEXT,
  expiry TEXT, strike REAL, opt_type TEXT, lots INTEGER, qty INTEGER,
  entry_ts TEXT, entry_px REAL, exit_ts TEXT, exit_px REAL,
  status TEXT DEFAULT 'OPEN', exit_reason TEXT,
  stop_px REAL, target_px REAL, trail_px REAL, mfe_px REAL, mae_px REAL,
  gross_pnl REAL, costs REAL, net_pnl REAL,
  entry_greeks TEXT, exit_greeks TEXT, entry_features TEXT, thesis TEXT,
  liquidity_at_entry TEXT,
  confidence REAL, debate TEXT
);
CREATE INDEX IF NOT EXISTS ix_trade_status ON trades(status);

CREATE TABLE IF NOT EXISTS equity (
  ts TEXT PRIMARY KEY, equity REAL, realised REAL, unrealised REAL,
  open_positions INTEGER, day_pnl REAL
);

CREATE TABLE IF NOT EXISTS strategies (
  version INTEGER PRIMARY KEY, created_ts TEXT, name TEXT,
  spec TEXT, rationale TEXT, backtest TEXT, status TEXT, retired_ts TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, trigger TEXT,
  from_version INTEGER, to_version INTEGER, stats TEXT,
  lessons TEXT, changes TEXT, raw TEXT
);

CREATE TABLE IF NOT EXISTS journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT,
  symbol TEXT, headline TEXT, detail TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_journal ON journal(ts);
"""


class Store:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------- snapshots ----------
    def save_snapshot(self, snap: dict, feats: dict, keep_chain: bool = True) -> None:
        exp = snap["expiries"][snap["nearest_expiry"]]
        thin = {k: v for k, v in exp.items() if k != "contracts"}
        thin["contracts"] = [c for c in exp["contracts"]
                             if abs(c["dist_from_atm"]) <= 8] if keep_chain else []
        self.db.execute(
            "INSERT INTO snapshots(ts,symbol,spot,expiry,atm_iv,features,chain)"
            " VALUES(?,?,?,?,?,?,?)",
            (snap["ts"], snap["symbol"], snap["spot"], snap["nearest_expiry"],
             exp["atm_iv"], json.dumps(feats), json.dumps(thin)))
        self.db.commit()

    def snapshot_series(self, symbol: str, limit: int = 2000) -> list[dict]:
        rows = self.db.execute(
            "SELECT ts,spot,atm_iv,features,chain FROM snapshots"
            " WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, limit)).fetchall()
        out = []
        for r in reversed(rows):
            out.append({"ts": r["ts"], "spot": r["spot"], "atm_iv": r["atm_iv"],
                        "features": json.loads(r["features"] or "{}"),
                        "chain": json.loads(r["chain"] or "{}")})
        return out

    def iv_history(self, symbol: str, limit: int = 200) -> list[float]:
        rows = self.db.execute(
            "SELECT atm_iv FROM snapshots WHERE symbol=? ORDER BY ts DESC LIMIT ?",
            (symbol, limit)).fetchall()
        return [r["atm_iv"] for r in reversed(rows) if r["atm_iv"]]

    def session_open_iv(self, symbol: str, day: str) -> float | None:
        r = self.db.execute(
            "SELECT atm_iv FROM snapshots WHERE symbol=? AND ts LIKE ?"
            " ORDER BY ts ASC LIMIT 1", (symbol, f"{day}%")).fetchone()
        return r["atm_iv"] if r else None

    # ---------- trades ----------
    def open_trades(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM trades WHERE status='OPEN'").fetchall()]

    def closed_trades(self, limit: int = 500, version: int | None = None) -> list[dict]:
        q = "SELECT * FROM trades WHERE status='CLOSED'"
        args: list = []
        if version is not None:
            q += " AND strategy_version=?"
            args.append(version)
        q += " ORDER BY exit_ts DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(q, args).fetchall()]

    def insert_trade(self, t: dict) -> int:
        cols = ",".join(t)
        cur = self.db.execute(
            f"INSERT INTO trades({cols}) VALUES({','.join('?' * len(t))})",
            list(t.values()))
        self.db.commit()
        return cur.lastrowid

    def update_trade(self, trade_id: int, **fields) -> None:
        sets = ",".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE trades SET {sets} WHERE id=?",
                        [*fields.values(), trade_id])
        self.db.commit()

    def trades_today(self, day: str) -> int:
        r = self.db.execute(
            "SELECT COUNT(*) c FROM trades WHERE entry_ts LIKE ?", (f"{day}%",)
        ).fetchone()
        return r["c"]

    def realised_today(self, day: str) -> float:
        r = self.db.execute(
            "SELECT COALESCE(SUM(net_pnl),0) s FROM trades"
            " WHERE status='CLOSED' AND exit_ts LIKE ?", (f"{day}%",)).fetchone()
        return float(r["s"])

    def realised_total(self) -> float:
        r = self.db.execute(
            "SELECT COALESCE(SUM(net_pnl),0) s FROM trades WHERE status='CLOSED'"
        ).fetchone()
        return float(r["s"])

    def realised_since(self, ts: str) -> float:
        r = self.db.execute(
            "SELECT COALESCE(SUM(net_pnl),0) s FROM trades"
            " WHERE status='CLOSED' AND exit_ts>=?", (ts,)).fetchone()
        return float(r["s"])

    def closed_count_since_version(self, version: int) -> int:
        r = self.db.execute(
            "SELECT COUNT(*) c FROM trades WHERE status='CLOSED'"
            " AND strategy_version=?", (version,)).fetchone()
        return r["c"]

    def last_trade_ts(self) -> str | None:
        r = self.db.execute("SELECT MAX(entry_ts) m FROM trades").fetchone()
        return r["m"]

    # ---------- equity ----------
    def mark_equity(self, ts: str, equity: float, realised: float,
                    unrealised: float, n_open: int, day_pnl: float) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO equity VALUES(?,?,?,?,?,?)",
            (ts, equity, realised, unrealised, n_open, day_pnl))
        self.db.commit()

    def equity_curve(self, limit: int = 3000) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM equity ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def peak_equity(self, default: float) -> float:
        r = self.db.execute("SELECT MAX(equity) m FROM equity").fetchone()
        return float(r["m"]) if r and r["m"] is not None else default

    # ---------- strategies ----------
    def active_strategy(self) -> dict | None:
        r = self.db.execute(
            "SELECT * FROM strategies WHERE status='ACTIVE'"
            " ORDER BY version DESC LIMIT 1").fetchone()
        if not r:
            return None
        d = dict(r)
        d["spec"] = json.loads(d["spec"])
        return d

    def save_strategy(self, version: int, name: str, spec: dict,
                      rationale: str, backtest: dict, ts: str) -> None:
        self.db.execute("UPDATE strategies SET status='RETIRED', retired_ts=?"
                        " WHERE status='ACTIVE'", (ts,))
        self.db.execute(
            "INSERT OR REPLACE INTO strategies"
            "(version,created_ts,name,spec,rationale,backtest,status)"
            " VALUES(?,?,?,?,?,?, 'ACTIVE')",
            (version, ts, name, json.dumps(spec), rationale, json.dumps(backtest)))
        self.db.commit()

    def next_version(self) -> int:
        r = self.db.execute("SELECT COALESCE(MAX(version),0) v FROM strategies").fetchone()
        return int(r["v"]) + 1

    def strategy_history(self, limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            "SELECT version,name,rationale,status,created_ts,backtest"
            " FROM strategies ORDER BY version DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- reviews & journal ----------
    def save_review(self, ts: str, trigger: str, frm: int, to: int,
                    stats: dict, lessons: str, changes: str, raw: str) -> None:
        self.db.execute(
            "INSERT INTO reviews(ts,trigger,from_version,to_version,stats,"
            "lessons,changes,raw) VALUES(?,?,?,?,?,?,?,?)",
            (ts, trigger, frm, to, json.dumps(stats), lessons, changes, raw))
        self.db.commit()

    def reviews(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def log(self, ts: str, kind: str, headline: str, detail: str = "",
            symbol: str = "", payload: dict | None = None) -> None:
        self.db.execute(
            "INSERT INTO journal(ts,kind,symbol,headline,detail,payload)"
            " VALUES(?,?,?,?,?,?)",
            (ts, kind, symbol, headline, detail, json.dumps(payload or {})))
        self.db.commit()
        print(f"[{kind}] {headline}" + (f" — {detail}" if detail else ""))

    def journal(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
