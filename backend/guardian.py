"""
guardian.py - Discipline guardian: checks the portfolio against the user's
own configured rules and reports violations.

"Hard risk gates + visible actions": the rules in user_config stop being
advisory text and become a compliance report. No AI, no cost - arithmetic.

check_all() returns a list of violations:
  {"severity": "URGENT"|"WARN", "rule": str, "ticker": str|None,
   "account": str|None, "message": str}
"""
from __future__ import annotations

from typing import Optional

from user_config import get_config, rule, account_policy
import risk_engine


def _account_value(acct: dict, prices: dict) -> float:
    val = acct.get("cash") or 0
    for p in acct.get("positions", []):
        price = (prices.get(p["ticker"]) or {}).get("price") or p["avg_cost"]
        val += price * p["shares"]
    return val


def check_all(positions_data: dict, prices: dict,
              history: Optional[list] = None) -> list[dict]:
    v: list[dict] = []
    cfg = get_config()
    accounts = positions_data.get("accounts", {})

    total_positions = 0
    grand_total = 0.0

    for acct_name, acct in accounts.items():
        policy = account_policy(acct_name)
        acct_value = _account_value(acct, prices)
        grand_total += acct_value
        cash = acct.get("cash") or 0
        positions = acct.get("positions", [])
        total_positions += len(positions)

        # Cash floor
        floor_pct = float(rule("cash_floor_pct") or 0)
        if floor_pct and acct_value > 0 and (cash / acct_value * 100) < floor_pct:
            v.append({"severity": "WARN", "rule": "cash_floor", "ticker": None,
                      "account": acct_name,
                      "message": f"{acct_name} cash is {cash / acct_value * 100:.1f}% "
                                 f"of account - your floor is {floor_pct:g}%"})

        # Per-position checks
        max_pos_pct = float(rule("max_position_pct") or 100)
        heat = 0.0
        for p in positions:
            t = p["ticker"]
            price = (prices.get(t) or {}).get("price") or p["avg_cost"]
            value = price * p["shares"]

            # Position concentration
            if acct_value > 0 and (value / acct_value * 100) > max_pos_pct:
                v.append({"severity": "WARN", "rule": "max_position_pct", "ticker": t,
                          "account": acct_name,
                          "message": f"{t} is {value / acct_value * 100:.1f}% of {acct_name} "
                                     f"- your max is {max_pos_pct:g}%"})

            # Stops required by account policy (Income positions exempt)
            if policy.get("stops_required") and not p.get("stop") and p.get("type") not in ("I",):
                v.append({"severity": "URGENT", "rule": "stop_required", "ticker": t,
                          "account": acct_name,
                          "message": f"{t} has no stop - {acct_name} policy requires stops "
                                     f"on {p.get('type', '?')}-type positions"})

            # Portfolio heat: open risk to the stop (no stop = full position at risk)
            if p.get("stop") and p["stop"] < price:
                heat += (price - p["stop"]) * p["shares"]
            elif policy.get("policy") != "lifetime":
                heat += value * 0.15  # proxy: assume 15% at risk when unstopped

        max_heat = float(rule("max_portfolio_heat_pct") or 100)
        if acct_value > 0 and (heat / acct_value * 100) > max_heat:
            v.append({"severity": "WARN", "rule": "portfolio_heat", "ticker": None,
                      "account": acct_name,
                      "message": f"{acct_name} open risk is {heat / acct_value * 100:.1f}% "
                                 f"of account - your heat limit is {max_heat:g}%"})

    # Max total positions
    max_positions = int(rule("max_positions") or 999)
    if total_positions > max_positions:
        v.append({"severity": "WARN", "rule": "max_positions", "ticker": None,
                  "account": None,
                  "message": f"{total_positions} open positions - your max is {max_positions}"})

    # Drawdown from peak equity
    if history:
        totals = [h.get("total") for h in history if h.get("total")]
        if grand_total:
            totals = totals + [grand_total]
        if len(totals) >= 2:
            peak = max(totals)
            dd = (peak - totals[-1]) / peak * 100 if peak else 0
            max_dd = float(rule("max_drawdown_pct") or 100)
            if dd > max_dd:
                v.append({"severity": "URGENT", "rule": "max_drawdown", "ticker": None,
                          "account": None,
                          "message": f"Portfolio is {dd:.1f}% below peak "
                                     f"(${peak:,.0f}) - your hard stop is {max_dd:g}%. "
                                     "Per your own rules: reduce exposure."})

    # Stale swing positions (time exits)
    v.extend({"severity": "WARN", "rule": "swing_max_hold", **s}
             for s in risk_engine.stale_positions(positions_data))
    for item in v:
        item.setdefault("ticker", None)
        item.setdefault("account", None)
        item.pop("held_days", None)
        item.pop("max_days", None)
    return v
