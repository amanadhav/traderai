"""
positions.py - Position state, P&L, pending-order analysis.

Operates on the dict returned by load_positions() (positions.json structure).
Pure logic; no live data fetching, no UI. Persistence I/O delegated to
persistence.py. Terminal/HTML rendering lives in terminal_ui.py and
html_render.py.

Functions:
  load_positions       - read positions.json
  all_tickers          - flat dedupe-preserving ticker list
  all_pending_orders   - flat list of every open order across all accounts
  calc_pnl             - single-position P&L given a price
  check_gtc_proximity  - orders within $0.50 of current → "near fill" alerts
  check_probable_fills - yesterday's OHLC crossed limit → probable fill
  _find_position       - locate a position by (account, ticker)
"""
from __future__ import annotations

import json
from typing import Optional

from persistence import POSITIONS_FILE


# ── Loaders ─────────────────────────────────────────────────────────────────

def load_positions() -> dict:
    """Read positions.json. Same source as persistence._load_data; kept under
    a domain-specific name for readability in the data pipeline."""
    with open(POSITIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


# ── Flat extractors ─────────────────────────────────────────────────────────

def all_tickers(data: dict) -> list[str]:
    """Every ticker held across all accounts, dedupe-preserving order."""
    tickers = []
    for acct in data["accounts"].values():
        for p in acct.get("positions", []):
            tickers.append(p["ticker"])
    return list(dict.fromkeys(tickers))


def all_pending_orders(data: dict) -> list[dict]:
    """Every open order - both inside positions and standalone watchlist orders."""
    orders = []
    for acct_name, acct in data["accounts"].items():
        for pos in acct.get("positions", []):
            for o in pos.get("pending_orders", []):
                orders.append({**o, "ticker": pos["ticker"], "account": acct_name})
        for o in acct.get("watchlist_orders", []):
            orders.append({**o, "account": acct_name})
    return orders


# ── P&L ─────────────────────────────────────────────────────────────────────

def calc_pnl(pos: dict, price: float) -> dict:
    """Single-position P&L. Returns {cost, value, gain, gain_pct}."""
    cost = pos["avg_cost"] * pos["shares"]
    value = price * pos["shares"]
    gain = value - cost
    gain_pct = (gain / cost) * 100 if cost else 0
    return {"cost": round(cost, 2), "value": round(value, 2),
            "gain": round(gain, 2), "gain_pct": round(gain_pct, 2)}


# ── Pending-order proximity & fill detection ────────────────────────────────

def check_gtc_proximity(orders: list[dict], snapshots: dict, threshold: float = 0.50) -> list[str]:
    """Return human-readable alerts for orders within $threshold of current price."""
    alerts = []
    for o in orders:
        t = o.get("ticker")
        price = o.get("price")
        if not t or not price:
            continue
        snap = snapshots.get(t, {})
        current = snap.get("price")
        if not current:
            continue
        gap = abs(current - price)
        if gap <= threshold:
            direction = "⬆️ BUY" if o.get("order") == "buy" else "⬇️ STOP"
            alerts.append(
                f"{direction} {t} limit ${price:.2f} - current ${current:.2f} - GAP ${gap:.2f} ⚠️ CLOSE TO FILL"
            )
    return alerts


def check_probable_fills(data: dict, snapshots: dict) -> list[dict]:
    """
    Return list of probable fill alerts based on yesterday's OHLC.
    Each alert: {ticker, account, order_type, side, limit_price,
                 prev_low, prev_high, note}.

    Triggers (each evaluated independently):
      - buy limit:  prev_low  <= limit  → likely FILLED
      - stop_loss:  prev_low  <= stop   → likely TRIGGERED
      - sell limit: prev_high >= limit  → likely FILLED
    """
    alerts = []
    for acct_name, acct in data["accounts"].items():
        # Orders embedded in positions
        for pos in acct.get("positions", []):
            ticker = pos["ticker"]
            snap = snapshots.get(ticker, {})
            prev_low  = snap.get("prev_low")
            prev_high = snap.get("prev_high")
            if prev_low is None or prev_high is None:
                continue
            for order in pos.get("pending_orders", []):
                if order.get("status") != "open":
                    continue
                limit = order.get("price")
                if not limit:
                    continue
                side = order.get("order", "")
                otype = order.get("type", "")
                shares = order.get("shares", pos.get("shares", 0))
                probable = False
                note = ""
                if side == "buy" and otype == "limit":
                    if prev_low <= limit:
                        probable = True
                        note = f"Yesterday low ${prev_low:.2f} ≤ limit ${limit:.2f} → likely FILLED"
                elif side == "sell" and otype == "stop_loss":
                    if prev_low <= limit:
                        probable = True
                        note = f"Yesterday low ${prev_low:.2f} ≤ stop ${limit:.2f} → likely TRIGGERED"
                elif side == "sell" and otype == "limit":
                    if prev_high >= limit:
                        probable = True
                        note = f"Yesterday high ${prev_high:.2f} ≥ limit ${limit:.2f} → likely FILLED"
                if probable:
                    alerts.append({
                        "ticker":      ticker,
                        "account":     acct_name,
                        "side":        side,
                        "order_type":  otype,
                        "shares":      shares,
                        "limit_price": limit,
                        "prev_low":    prev_low,
                        "prev_high":   prev_high,
                        "note":        note,
                    })
        # Standalone watchlist orders (not attached to positions)
        for order in acct.get("watchlist_orders", []):
            if order.get("status") != "open":
                continue
            ticker = order.get("ticker")
            if not ticker:
                continue
            snap = snapshots.get(ticker, {})
            prev_low  = snap.get("prev_low")
            prev_high = snap.get("prev_high")
            if prev_low is None or prev_high is None:
                continue
            limit = order.get("price")
            if not limit:
                continue
            side = order.get("order", "buy")
            shares = order.get("shares", 0)
            if side == "buy" and prev_low <= limit:
                alerts.append({
                    "ticker":      ticker,
                    "account":     acct_name,
                    "side":        "buy",
                    "order_type":  "limit",
                    "shares":      shares,
                    "limit_price": limit,
                    "prev_low":    prev_low,
                    "prev_high":   prev_high,
                    "note":        f"Yesterday low ${prev_low:.2f} ≤ limit ${limit:.2f} → likely FILLED (watchlist)",
                })
    return alerts


# ── Position lookup ─────────────────────────────────────────────────────────

def _find_position(data: dict, account: str, ticker: str) -> tuple[Optional[dict], Optional[list]]:
    """Locate a position by (account, ticker). Returns (pos_dict, position_list).
    Position list returned even when ticker not found, to support 'add new'."""
    acct = data["accounts"].get(account.upper())
    if not acct:
        return None, None
    for pos in acct.get("positions", []):
        if pos["ticker"].upper() == ticker.upper():
            return pos, acct["positions"]
    return None, acct["positions"]
