"""
persistence.py - File I/O for trading state.

Owns all reads/writes to:
  - positions.json     → portfolio source of truth
  - daily_brief.json   → context anchor for Claude sessions
  - portfolio_history.json → daily portfolio totals time series
  - trades_log.json    → closed-trade ledger

Pure I/O. No business logic. No live data fetching. Other modules import
the path constants and functions from here.

`console` is passed in as a param where needed so morning_run.py's recording
Console (record=True) captures output. Default: silent.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows consoles/pipes default to cp1252, which can't encode the arrows and
# emoji this system prints. Force UTF-8 once, here, in the most-imported module.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# ── Canonical file paths ─────────────────────────────────────────────────────
BASE             = Path(__file__).resolve().parents[1]
POSITIONS_FILE   = BASE / "positions.json"
DAILY_BRIEF_FILE = BASE / "daily_brief.json"
HISTORY_FILE     = BASE / "portfolio_history.json"
TRADES_FILE      = BASE / "trades_log.json"


# ── positions.json ───────────────────────────────────────────────────────────

def positions_lock():
    """Cross-process lock guarding positions.json read-modify-write cycles."""
    from filelock import FileLock
    return FileLock(str(POSITIONS_FILE) + ".lock", timeout=10)


def _load_data() -> dict:
    """Read positions.json. Source of truth for portfolio state."""
    with open(POSITIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_data(data: dict, console=None) -> None:
    """Write positions.json with updated `last_updated` timestamp."""
    data["last_updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    if console is not None:
        console.print("[green]✅ positions.json updated[/]")


# ── portfolio_history.json ───────────────────────────────────────────────────

def record_portfolio_snapshot(data: dict, snapshots: dict) -> None:
    """Append today's portfolio totals to portfolio_history.json.
    Replaces same-day entry if already present (idempotent per day)."""
    today = datetime.now().strftime("%Y-%m-%d")
    history = []
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
    if history and history[-1]["date"] == today:
        history.pop()

    def acct_total(acct):
        total = acct.get("cash", 0)
        for p in acct.get("positions", []):
            price = (snapshots.get(p["ticker"]) or {}).get("price") or p["avg_cost"]
            total += price * p["shares"]
        return round(total, 2)

    roth_val = acct_total(data["accounts"]["ROTH"])
    tod_val  = acct_total(data["accounts"]["TOD"])
    history.append({"date": today, "roth": roth_val, "tod": tod_val,
                    "total": round(roth_val + tod_val, 2)})
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


# ── trades_log.json ──────────────────────────────────────────────────────────

def log_trade(account: str, ticker: str, shares: float, avg_cost: float,
              sell_price: float, entry_date: Optional[str] = None) -> None:
    """Append a closed trade to trades_log.json with P/L computed."""
    trades = []
    if TRADES_FILE.exists():
        with open(TRADES_FILE, encoding="utf-8") as f:
            trades = json.load(f)
    pl_dollar = round((sell_price - avg_cost) * shares, 2)
    pl_pct    = round((sell_price - avg_cost) / avg_cost * 100, 2)
    hold_days = None
    if entry_date:
        try:
            d0 = datetime.strptime(entry_date, "%Y-%m-%d")
            hold_days = (datetime.now() - d0).days
        except Exception:
            pass
    trades.append({
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "account":    account,
        "ticker":     ticker,
        "shares":     shares,
        "avg_cost":   avg_cost,
        "sell_price": sell_price,
        "pl_dollar":  pl_dollar,
        "pl_pct":     pl_pct,
        "hold_days":  hold_days,
    })
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2)


# ── daily_brief.json - context anchor ────────────────────────────────────────

def write_daily_brief(
    data: dict,
    snapshots: dict,
    market_snaps: dict,
    probable_fills: list[dict],
    action_items: list[dict],
    insider_signals: Optional[dict] = None,
    options_flows: Optional[dict] = None,
    console=None,
) -> None:
    """
    Write daily_brief.json - the CONTEXT ANCHOR.

    This file survives context window resets. Claude reads it (DAILY_BRIEF_FILE
    in this repo's root) whenever:
    - Session has been running long (>20 messages)
    - Any trading decision is being made mid-session
    - User says "anchor" or "/anchor"
    - Uncertainty about any position state

    Never trust conversation memory over this file.
    Code = ground truth. Conversation = unreliable cache.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().astimezone().isoformat(timespec="seconds")

    # ── Earnings alerts (≤21 days) - pre-earnings decisions ─────────────────
    earnings_alerts = []
    for t, snap in snapshots.items():
        dte = snap.get("days_to_earnings")
        if dte is not None and 0 <= dte <= 21:
            pos_data = None
            acct_name = None
            for acct_n, acct in data["accounts"].items():
                for p in acct.get("positions", []):
                    if p["ticker"] == t:
                        pos_data = p
                        acct_name = acct_n
            price = snap.get("price", 0)
            avg = pos_data["avg_cost"] if pos_data else 0
            shares = pos_data["shares"] if pos_data else 0
            pnl_pct = ((price - avg) / avg * 100) if avg else 0
            pnl_dollar = (price - avg) * shares if avg else 0
            urgency = "TODAY" if dte == 0 else ("TOMORROW" if dte == 1 else f"IN {dte}D")
            earnings_alerts.append({
                "ticker":     t,
                "dte":        dte,
                "urgency":    urgency,
                "account":    acct_name,
                "shares":     shares,
                "avg_cost":   avg,
                "price":      round(price, 2),
                "pnl_pct":    round(pnl_pct, 1),
                "pnl_dollar": round(pnl_dollar, 2),
                "mandatory":  "MANDATORY - deliver bull case, bear case, explicit recommendation before bell"
                              if dte <= 1 else
                              "FLAG - research lead indicators (Polymarket, earningswhispers, options flow)",
            })
    earnings_alerts.sort(key=lambda x: x["dte"])

    # ── Positions near stop (≤8%) ─────────────────────────────────────────
    stop_alerts = []
    for acct_n, acct in data["accounts"].items():
        for p in acct.get("positions", []):
            t = p["ticker"]
            stop = p.get("stop")
            if not stop:
                continue
            price = (snapshots.get(t) or {}).get("price") or p["avg_cost"]
            gap_pct = ((price - stop) / price * 100) if price else 100
            if gap_pct <= 8:
                stop_alerts.append({
                    "ticker":   t,
                    "account":  acct_n,
                    "price":    round(price, 2),
                    "stop":     stop,
                    "gap_pct":  round(gap_pct, 1),
                    "urgency":  "IMMINENT (<3%)" if gap_pct < 3 else "NEAR (3-8%)",
                })

    # ── All positions snapshot ─────────────────────────────────────────────
    positions_snapshot = {}
    for acct_n, acct in data["accounts"].items():
        for p in acct.get("positions", []):
            t = p["ticker"]
            snap = snapshots.get(t, {})
            price = snap.get("price") or p["avg_cost"]
            avg = p["avg_cost"]
            shares = p["shares"]
            pnl_pct = ((price - avg) / avg * 100) if avg else 0
            rsi = snap.get("rsi")
            if rsi is None:
                rsi_signal = "NO DATA"
            elif rsi < 30:
                rsi_signal = "OVERSOLD"
            elif rsi < 40:
                rsi_signal = "NEAR OVERSOLD"
            elif rsi < 60:
                rsi_signal = "NEUTRAL"
            elif rsi < 70:
                rsi_signal = "NEAR OVERBOUGHT"
            else:
                rsi_signal = "OVERBOUGHT"
            positions_snapshot[t] = {
                "account":          acct_n,
                "type":             p.get("type", ""),
                "shares":           shares,
                "avg_cost":         avg,
                "price":            round(price, 2),
                "pnl_pct":          round(pnl_pct, 1),
                "pnl_dollar":       round((price - avg) * shares, 2),
                "stop":             p.get("stop"),
                "thesis":           p.get("thesis", "")[:80],
                # ── Live technicals ── never estimate these, always from snap ──
                "rsi":              round(rsi, 1) if rsi is not None else None,
                "rsi_signal":       rsi_signal,
                "day_change_pct":   snap.get("pct_chg_today"),
                "days_to_earnings": snap.get("days_to_earnings"),
                "macd_improving":   snap.get("macd_improving"),
                "ma50":             snap.get("ma50"),
                "ma200":            snap.get("ma200"),
                "52w_high":         snap.get("52w_high"),
                "52w_low":          snap.get("52w_low"),
                "bb_pct":           snap.get("bb_pct"),
                "data_ok":          not bool(snap.get("error")),
                # ── Options flow (gamma walls) ──────────────────────────────
                "options_signal":   (options_flows or {}).get(t, {}).get("signal"),
                "pcr_vol":          (options_flows or {}).get(t, {}).get("pcr_vol"),
                "pcr_oi":           (options_flows or {}).get(t, {}).get("pcr_oi"),
                "gamma_wall_above": next(
                    (s["strike"] for s in (options_flows or {}).get(t, {}).get("key_strikes", [])
                     if s["dist_pct"] > 0.5), None),
                "gamma_wall_below": next(
                    (s["strike"] for s in sorted(
                        (options_flows or {}).get(t, {}).get("key_strikes", []),
                        key=lambda x: x["dist_pct"], reverse=True)
                     if s["dist_pct"] < -0.5), None),
                "max_pain":         (options_flows or {}).get(t, {}).get("max_pain"),
                "max_pain_days":    (options_flows or {}).get(t, {}).get("max_pain_days"),
                "max_pain_dist_pct":(options_flows or {}).get(t, {}).get("max_pain_dist_pct"),
                "max_pain_signal":  (options_flows or {}).get(t, {}).get("max_pain_signal", ""),
            }

    # ── Portfolio totals ───────────────────────────────────────────────────
    roth_total = data["accounts"]["ROTH"].get("cash", 0)
    tod_total  = data["accounts"]["TOD"].get("cash", 0)
    for acct_n, acct in data["accounts"].items():
        for p in acct.get("positions", []):
            price = (snapshots.get(p["ticker"]) or {}).get("price") or p["avg_cost"]
            val = price * p["shares"]
            if acct_n == "ROTH":
                roth_total += val
            else:
                tod_total += val

    # ── Market state ───────────────────────────────────────────────────────
    vix     = (market_snaps.get("^VIX") or {}).get("price")
    spy_rsi = (market_snaps.get("SPY")  or {}).get("rsi")
    qqq_rsi = (market_snaps.get("QQQ")  or {}).get("rsi")
    if spy_rsi and spy_rsi > 75:
        market_regime = "OVERBOUGHT - no new lump-sum entries"
    elif spy_rsi and spy_rsi < 35:
        market_regime = "OVERSOLD - buy aggressively"
    else:
        market_regime = "NORMAL"

    # ── Top action items ──────────────────────────────────────────────────
    top_actions = [
        {"priority": a["priority"], "ticker": a["ticker"],
         "verb": a["verb"], "detail": a["detail"][:120]}
        for a in (action_items or [])[:5]
    ]

    # ── Watchlist status ──────────────────────────────────────────────────
    watchlist_summary = [
        {"ticker": w["ticker"], "company": w.get("company",""),
         "slot": w.get("slot",""), "score": w.get("score_at_scan",0),
         "entry_conditions": w.get("entry_conditions","")}
        for w in data.get("watchlist", [])
    ]

    brief = {
        "generated":           now_str,
        "date":                today,
        "context_anchor":      True,
        "_instructions":       (
            "CLAUDE: Read this file whenever context is uncertain, session is long, "
            "or user says 'anchor'. This is ground truth. Never trust conversation "
            "memory over this file. If earnings_alerts is non-empty, deliver "
            "bull/bear/decision for EVERY ticker listed - no exceptions."
        ),

        # ── CRITICAL - these must never be forgotten ──────────────────────
        "earnings_alerts":     earnings_alerts,
        "probable_fills":      probable_fills,
        "stop_alerts":         stop_alerts,

        # ── Portfolio state ───────────────────────────────────────────────
        "portfolio": {
            "roth_total":  round(roth_total, 2),
            "tod_total":   round(tod_total, 2),
            "grand_total": round(roth_total + tod_total, 2),
            "roth_cash":   data["accounts"]["ROTH"].get("cash", 0),
            "tod_cash":    data["accounts"]["TOD"].get("cash", 0),
        },

        # ── Market conditions ──────────────────────────────────────────────
        "market": {
            "vix":         round(vix, 1) if vix else None,
            "spy_rsi":     round(spy_rsi, 1) if spy_rsi else None,
            "qqq_rsi":     round(qqq_rsi, 1) if qqq_rsi else None,
            "regime":      market_regime,
        },

        # ── All positions ─────────────────────────────────────────────────
        "positions":           positions_snapshot,

        # ── Today's top actions ───────────────────────────────────────────
        "top_actions":         top_actions,

        # ── Watchlist ─────────────────────────────────────────────────────
        "watchlist":           watchlist_summary,

        # ── Insider buying signals ────────────────────────────────────────
        "insider_signals": {
            t: {"signal": s["signal"], "has_signal": s["has_signal"], "description": s["description"]}
            for t, s in (insider_signals or {}).items()
        },

        # ── Options flow ──────────────────────────────────────────────────
        "options_flow": {
            t: {
                "signal": f["signal"], "pcr_vol": f.get("pcr_vol"),
                "pcr_oi": f.get("pcr_oi"), "atm_iv": f.get("atm_iv"),
                "note": f.get("note", ""),
                "key_strikes": f.get("key_strikes", [])[:3],
            }
            for t, f in (options_flows or {}).items()
        },

        # ── Hard rules reminder ───────────────────────────────────────────
        "hard_rules": [
            "Never recommend buy without running score.py TICKER first",
            "Never add defense to ROTH (2/2 FULL - RTX + NOC)",
            "Never add shares within 15 days of earnings",
            "ROTH Healthcare slot: 1/2 open (DHR or ABT or SYK - pick highest score on entry day)",
            "TOD = Lifetime holds: NEVER set stop. Exit only on thesis collapse.",
            "MDT: HOLD - Q3 strongest revenue in 10 quarters, PFA +80%. Next earnings June 3.",
            "NKE: HOLD - insider cluster buy ($4M Elliott Hill + Tim Cook at $42). Dead money 6mo+.",
            "NVDA: earnings May 20 - 14 days. Mandatory pre-earnings decision on May 20 morning.",
            "AMD: just beat +16%. Lifetime hold. Post-earnings: did thesis accelerate? Consider adding on dip.",
        ],
    }

    with open(DAILY_BRIEF_FILE, "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2)

    # Print compact anchor summary to terminal
    if console is None:
        return
    console.print()
    console.rule("[bold magenta]🔒 CONTEXT ANCHOR - daily_brief.json written[/]")
    if earnings_alerts:
        for ea in earnings_alerts:
            color = "bold red" if ea["dte"] <= 1 else "bold yellow"
            console.print(f"  [{color}]🚨 {ea['ticker']} earnings {ea['urgency']} - {ea['mandatory']}[/]")
    if probable_fills:
        console.print(f"  [bold red]⚠️  {len(probable_fills)} probable fill(s) - check Fidelity[/]")
    if stop_alerts:
        for sa in stop_alerts:
            console.print(f"  [bold red]🔴 {sa['ticker']} stop {sa['urgency']} - ${sa['price']:.2f} vs stop ${sa['stop']:.2f}[/]")
    console.print(f"  [dim]Portfolio: ROTH ${roth_total:,.0f} | TOD ${tod_total:,.0f} | Total ${roth_total+tod_total:,.0f}[/]")
    vix_str = f"{vix:.1f}" if vix else "n/a"
    spy_str = f"{spy_rsi:.1f}" if spy_rsi else "n/a"
    console.print(f"  [dim]Market: VIX {vix_str} | SPY RSI {spy_str} - {market_regime}[/]")
    console.print(f"  [dim]Re-anchor anytime: cat {DAILY_BRIEF_FILE}[/]")
    console.print()
