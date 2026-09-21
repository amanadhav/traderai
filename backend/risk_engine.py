"""
risk_engine.py - ATR-based stops, risk-based position sizing, trade setups.

The point: make the user's risk rules *computable* instead of advisory.
Every number here is arithmetic over fetched data - the AI writes theses,
this module writes the numbers.

  suggest_stop()      - stop price from the user's stop_style (fixed % or ATR)
  position_size()     - shares from max_risk_per_trade_pct: risk a fixed slice
                        of equity per trade, scaled by the ticker's volatility
  build_trade_setup() - full structured setup: entry, stop, target, shares,
                        dollar risk/reward, R:R - ready to render or hand to AI
  stale_positions()   - swing positions held past swing_max_hold_days
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from user_config import get_config, rule


def suggest_stop(entry: float, atr: Optional[float]) -> dict:
    """Stop price + basis per the user's configured stop style."""
    style = rule("stop_style") or "fixed_pct"
    if style == "none":
        return {"stop": None, "basis": "no default stops (user setting)"}
    if style == "atr" and atr:
        mult = float(rule("atr_stop_multiple") or 2.0)
        stop = entry - mult * atr
        return {"stop": round(max(stop, 0.01), 2),
                "basis": f"{mult:g}x ATR (${atr:.2f}) below entry"}
    # fixed_pct and trailing both anchor at a fixed % below entry
    pct = float(rule("default_stop_pct") or 15.0)
    label = "trailing, initial" if style == "trailing" else "fixed"
    return {"stop": round(entry * (1 - pct / 100), 2),
            "basis": f"{pct:g}% below entry ({label})"}


def position_size(equity: float, entry: float, stop: Optional[float]) -> dict:
    """
    Risk-based sizing: risk max_risk_per_trade_pct of equity between entry
    and stop, capped by max_position_pct of equity. This is what makes the
    'max risk per trade' rule real instead of a suggestion.
    """
    risk_pct = float(rule("max_risk_per_trade_pct") or 1.5)
    cap_pct = float(rule("max_position_pct") or 20.0)
    risk_budget = equity * risk_pct / 100

    if stop and stop < entry:
        per_share_risk = entry - stop
        shares_by_risk = int(risk_budget / per_share_risk)
    else:
        # no stop → treat the whole position as at-risk, size very small
        shares_by_risk = int(risk_budget / entry) if entry else 0

    shares_by_cap = int(equity * cap_pct / 100 / entry) if entry else 0
    shares = max(0, min(shares_by_risk, shares_by_cap))
    return {
        "shares": shares,
        "risk_budget": round(risk_budget, 2),
        "capped_by": "position cap" if shares_by_cap < shares_by_risk else "risk budget",
        "position_value": round(shares * entry, 2),
    }


def build_trade_setup(snapshot: dict, equity: float) -> dict:
    """Structured trade setup - all numbers computed, none generated."""
    entry = snapshot.get("price")
    if not entry:
        return {"error": "no price in snapshot"}
    atr = snapshot.get("atr")
    stop_info = suggest_stop(entry, atr)
    stop = stop_info["stop"]
    rr = float(rule("reward_risk_target") or 2.0)

    risk_per_share = round(entry - stop, 2) if stop else None
    target = round(entry + rr * risk_per_share, 2) if risk_per_share else None
    sizing = position_size(equity, entry, stop)
    shares = sizing["shares"]

    return {
        "ticker": snapshot.get("ticker"),
        "entry": round(entry, 2),
        "stop": stop,
        "stop_basis": stop_info["basis"],
        "target": target,
        "reward_risk": rr if target else None,
        "shares": shares,
        "position_value": sizing["position_value"],
        "dollar_risk": round(shares * risk_per_share, 2) if risk_per_share else None,
        "dollar_reward": round(shares * rr * risk_per_share, 2) if risk_per_share else None,
        "atr": atr,
        "atr_pct": snapshot.get("atr_pct"),
        "equity_used": equity,
        "rules_applied": {
            "max_risk_per_trade_pct": rule("max_risk_per_trade_pct"),
            "max_position_pct": rule("max_position_pct"),
            "stop_style": rule("stop_style"),
        },
    }


def _held_days(entry_date: Optional[str]) -> Optional[int]:
    if not entry_date:
        return None
    try:
        d = datetime.strptime(entry_date[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def stale_positions(positions_data: dict) -> list[dict]:
    """Swing (S) positions held past swing_max_hold_days - time exits matter."""
    max_days = int(rule("swing_max_hold_days") or 60)
    out = []
    for acct_name, acct in positions_data.get("accounts", {}).items():
        for p in acct.get("positions", []):
            if p.get("type") != "S":
                continue
            days = _held_days(p.get("entry_date"))
            if days is not None and days > max_days:
                out.append({
                    "ticker": p["ticker"], "account": acct_name,
                    "held_days": days, "max_days": max_days,
                    "message": f"{p['ticker']} is a Swing position held {days}d "
                               f"(rule: {max_days}d max) - take profit, cut, or reclassify",
                })
    return out
