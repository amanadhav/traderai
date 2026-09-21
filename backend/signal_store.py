"""
signal_store.py - SQLite history of every signal the system computes.

The morning pipeline calculates scores, RSI, ATR, options flow, insider
signals, and guardian violations every day - and used to throw them away.
This module records them, additively:

  - positions.json and the JSON anchors remain the source of truth
  - this database is a pure APPEND log for queries and future ML training
    ("show me every day NVDA's RSI was under 35", "signal values → 60d returns")

sqlite3 is in the standard library - zero infra, zero cost, one file
(data/signals.db, gitignored).
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parents[1]
DB_FILE = BASE / "data" / "signals.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_signals (
    date            TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    price           REAL,
    change_pct      REAL,
    rsi             REAL,
    macd_hist       REAL,
    bb_pct          REAL,
    atr_pct         REAL,
    vol_ratio       REAL,
    days_to_earnings INTEGER,
    pc_ratio        REAL,
    options_signal  TEXT,
    insider_signal  TEXT,
    PRIMARY KEY (date, ticker)
);
CREATE TABLE IF NOT EXISTS guardian_log (
    date     TEXT NOT NULL,
    severity TEXT,
    rule     TEXT,
    ticker   TEXT,
    account  TEXT,
    message  TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON daily_signals (ticker, date);
"""


def _connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.executescript(_SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def record_day(snapshots: dict, insider_signals: Optional[dict] = None,
               options_flows: Optional[dict] = None,
               guardian_violations: Optional[list] = None,
               day: Optional[str] = None) -> int:
    """Upsert today's signal row per ticker. Returns rows written."""
    day = day or date.today().isoformat()
    insider_signals = insider_signals or {}
    options_flows = options_flows or {}
    rows = []
    for t, snap in (snapshots or {}).items():
        if not isinstance(snap, dict) or snap.get("price") is None:
            continue
        flow = options_flows.get(t) or {}
        ins = insider_signals.get(t) or {}
        rows.append((
            day, t, snap.get("price"), snap.get("pct_chg_today"),
            snap.get("rsi"), snap.get("macd_hist"), snap.get("bb_pct"),
            snap.get("atr_pct"), snap.get("vol_ratio"), snap.get("days_to_earnings"),
            flow.get("pc_ratio") or flow.get("pcr_vol"), flow.get("signal"),
            ins.get("signal"),
        ))
    if not rows and not guardian_violations:
        return 0
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO daily_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        if guardian_violations:
            conn.execute("DELETE FROM guardian_log WHERE date = ?", (day,))
            conn.executemany(
                "INSERT INTO guardian_log VALUES (?,?,?,?,?,?)",
                [(day, v.get("severity"), v.get("rule"), v.get("ticker"),
                  v.get("account"), v.get("message")) for v in guardian_violations],
            )
    return len(rows)


def history(ticker: str, days: int = 90) -> list[dict]:
    """Most recent N daily signal rows for a ticker, oldest first."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM daily_signals WHERE ticker = ? ORDER BY date DESC LIMIT ?",
            (ticker.upper(), days),
        )
        return [dict(r) for r in reversed(cur.fetchall())]


def guardian_history(days: int = 30) -> list[dict]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM guardian_log ORDER BY date DESC LIMIT 200",
        )
        return [dict(r) for r in cur.fetchall()][: days * 20]


def stats() -> dict:
    with _connect() as conn:
        days = conn.execute("SELECT COUNT(DISTINCT date) FROM daily_signals").fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM daily_signals").fetchone()[0]
        tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM daily_signals").fetchone()[0]
        first = conn.execute("SELECT MIN(date) FROM daily_signals").fetchone()[0]
    return {"days_recorded": days, "rows": rows, "tickers": tickers, "since": first}
