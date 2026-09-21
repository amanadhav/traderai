"""
alerts_check.py - Order fill detection, watchlist evaluation, lead-indicator
prompts, and the terminal renderers tightly coupled to those alerts.

Logic + presentation kept together because each detector has exactly one
matching renderer (no other caller would ever want a different format for
"probable fill" or "watchlist status"). Splitting them just adds friction.

Functions:
  detect_order_fills          - auto-detect fills from today's OHLC, mutate
                                positions.json via save_data callback
  check_watchlist_entries     - evaluate every watchlist candidate's entry
                                conditions (RSI, market, earnings, score)
  print_probable_fills_terminal     - Rich panel for yesterday-OHLC alerts
  print_watchlist_terminal           - Rich panel for entry-condition status
  print_lead_indicators_terminal     - pre-earnings research reminders

`console` is passed in so morning_run.py's recording Console (record=True)
captures output. Default: silent (no terminal print).
`save_data_fn` defaults to persistence._save_data so detect_order_fills
works standalone; morning_run.py passes its console-aware wrapper.
"""
from __future__ import annotations

from typing import Optional, Callable

from rich.panel import Panel

from persistence import _save_data as _default_save_data


# ── Order fill detection (mutates positions.json) ───────────────────────────

def detect_order_fills(
    data: dict,
    snapshots: dict,
    save_data_fn: Optional[Callable[[dict], None]] = None,
) -> list[str]:
    """
    Compare open pending orders against today's OHLC range.
    Auto-applies fills to positions.json via save_data_fn callback.
    Returns list of human-readable fill messages.

    Triggers:
      BUY  limit   → filled if day_low  <= limit_price
      SELL stop    → filled if day_low  <= stop_price
      SELL limit   → filled if day_high >= limit_price
    """
    if save_data_fn is None:
        save_data_fn = _default_save_data

    fills: list[str] = []
    changed = False

    for acct_name, acct in data["accounts"].items():
        for pos in acct.get("positions", []):
            t     = pos["ticker"]
            snap  = snapshots.get(t, {})
            d_low  = snap.get("day_low")
            d_high = snap.get("day_high")
            price  = snap.get("price")
            if not price:
                continue

            for order in pos.get("pending_orders", []):
                if order.get("status") != "open":
                    continue

                op       = order.get("order", "")
                op_type  = order.get("type", "")
                op_price = order.get("price", 0)
                op_sh    = order.get("shares", 0)
                note     = order.get("note", "")

                filled = False
                if op == "buy" and op_type == "limit" and d_low is not None:
                    filled = d_low <= op_price
                elif op == "sell" and op_type in ("stop_loss", "stop") and d_low is not None:
                    filled = d_low <= op_price
                elif op == "sell" and op_type == "limit" and d_high is not None:
                    filled = d_high >= op_price

                if not filled:
                    continue

                if op == "buy":
                    old_sh  = pos["shares"]
                    old_avg = pos["avg_cost"]
                    new_sh  = old_sh + op_sh
                    new_avg = round((old_sh * old_avg + op_sh * op_price) / new_sh, 4)
                    pos["shares"]   = new_sh
                    pos["avg_cost"] = new_avg
                    msg = (f"🎯 AUTO-FILL: {t} ({acct_name}) BUY {op_sh}sh @${op_price:.2f} - "
                           f"now {new_sh}sh @${new_avg:.2f} avg.")
                    if note:
                        msg += f" Note: {note}"
                    fills.append(msg)

                elif op == "sell":
                    old_sh    = pos["shares"]
                    remaining = old_sh - op_sh
                    avg       = pos["avg_cost"]
                    pl        = (op_price - avg) * op_sh
                    pl_pct    = (op_price - avg) / avg * 100
                    pos["shares"] = max(0, remaining)
                    msg = (f"🎯 AUTO-FILL: {t} ({acct_name}) SELL {op_sh}sh @${op_price:.2f} - "
                           f"P&L: {'+' if pl>=0 else ''}{pl_pct:.1f}% / ${pl:+.0f}. "
                           f"{remaining}sh remaining.")
                    fills.append(msg)

                order["status"] = "filled"
                changed = True

    if changed:
        save_data_fn(data)

    return fills


# ── Watchlist entry-condition evaluation ────────────────────────────────────

def check_watchlist_entries(data: dict, snapshots: dict, market_snaps: dict) -> list[dict]:
    """
    For each watchlist candidate, evaluate current entry conditions.
    Returns list of dicts with status (GREEN/YELLOW/RED), ticker, reasoning.
    """
    results = []
    watchlist = data.get("watchlist", [])
    if not watchlist:
        return results

    spy_rsi = (market_snaps.get("SPY") or {}).get("rsi") or 50.0
    market_overbought = spy_rsi > 65

    for candidate in watchlist:
        ticker = candidate.get("ticker", "")
        snap   = snapshots.get(ticker, {})
        rsi    = snap.get("rsi")
        price  = snap.get("price")
        dte    = snap.get("days_to_earnings")
        score_scan = candidate.get("score_at_scan", 0)

        issues:    list[str] = []
        positives: list[str] = []

        # Market condition
        if market_overbought:
            issues.append(f"Market overbought (SPY RSI {spy_rsi:.0f} > 65) - wait for pullback")
        else:
            positives.append(f"Market RSI {spy_rsi:.0f} - entry conditions open")

        # Ticker RSI
        if rsi is not None:
            if rsi < 30:
                positives.append(f"RSI {rsi:.1f} - EXTREME oversold ✅")
            elif rsi < 40:
                positives.append(f"RSI {rsi:.1f} - oversold ✅")
            elif rsi < 55:
                issues.append(f"RSI {rsi:.1f} - neutral, wait for dip")
            else:
                issues.append(f"RSI {rsi:.1f} - overbought, do NOT enter")

        # Earnings proximity
        if dte is not None:
            if 0 <= dte <= 15:
                issues.append(f"Earnings in {dte}d - DISQUALIFIED (rule: >15d required)")
            elif dte <= 30:
                issues.append(f"Earnings in {dte}d - approaching window, watch")
            else:
                positives.append(f"Earnings {dte}d away - clear ✅")

        # Score note
        if score_scan >= 80:
            positives.append(f"Score {score_scan} - HIGH CONVICTION")
        elif score_scan >= 60:
            positives.append(f"Score {score_scan} - candidate ✅")
        else:
            issues.append(f"Score {score_scan} - below threshold, re-run score.py")

        # Determine overall status
        has_earnings_block = any("DISQUALIFIED" in i for i in issues)
        has_market_block   = any("overbought" in i for i in issues)
        has_rsi_hot        = any("do NOT enter" in i for i in issues)

        if has_earnings_block or has_rsi_hot:
            status = "RED"
        elif has_market_block:
            status = "YELLOW"
        elif not issues:
            status = "GREEN"
        else:
            status = "YELLOW"

        results.append({
            "ticker":    ticker,
            "company":   candidate.get("company", ""),
            "slot":      candidate.get("slot", ""),
            "account":   candidate.get("account", ""),
            "score":     score_scan,
            "rsi":       rsi,
            "price":     price,
            "dte":       dte,
            "status":    status,
            "positives": positives,
            "issues":    issues,
            "thesis":    candidate.get("thesis", ""),
            "size":      candidate.get("size", ""),
        })

    return results


# ── Lead indicator signals (pre-earnings research prompts) ──────────────────

LEAD_INDICATOR_SIGNALS = {
    # Supply chain upstream signals → read quarter early
    "TSMC monthly revenue":    {"tickers": ["TSM", "AMD", "NVDA", "ASML"], "lag": "6-8 weeks early"},
    "Foxconn monthly revenue": {"tickers": ["AAPL", "MSFT"], "lag": "6-8 weeks early"},
    # Prediction markets - beat probability before earnings
    "Polymarket / Kalshi":     {"tickers": "all earnings", "lag": "0-7 days before"},
    # Sector comp sequencing - when upstream reports, read downstream
    "SMCI / INTC earnings":    {"tickers": ["AMD", "NVDA"], "lag": "2-4 weeks early"},
    "Apple supply chain":      {"tickers": ["AAPL", "TSM", "ASML"], "lag": "1-2 quarters early"},
    # Insider transactions - Form 4 filings
    "openinsider.com Form 4":  {"tickers": "all held", "lag": "1-3 months early"},
    # Options unusual activity
    "unusual_whales.com":      {"tickers": "all earnings", "lag": "1-5 days early"},
}


# ── Terminal renderers ──────────────────────────────────────────────────────

def print_probable_fills_terminal(alerts: list[dict], console=None) -> None:
    if not alerts or console is None:
        return
    console.print()
    console.print(Panel(
        "[bold red]⚠️  PROBABLE FILLS - CHECK FIDELITY NOW[/bold red]",
        style="bold red", expand=False
    ))
    for a in alerts:
        side_icon = "🟢 BUY" if a["side"] == "buy" else "🔴 SELL/STOP"
        console.print(
            f"  {side_icon}  [bold]{a['ticker']}[/bold]  {a['shares']}sh  @${a['limit_price']:.2f}"
            f"  [{a['account']}]"
        )
        console.print(f"     → {a['note']}")
        console.print(f"     Confirm fill in chat → I update positions.json")
    console.print()


def print_watchlist_terminal(results: list[dict], console=None) -> None:
    if not results or console is None:
        return

    status_style = {"GREEN": "bold green", "YELLOW": "bold yellow", "RED": "bold red"}
    status_icon  = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}

    console.rule("[bold cyan]👀 WATCHLIST - ENTRY CONDITIONS[/]")
    for r in results:
        style = status_style.get(r["status"], "white")
        icon  = status_icon.get(r["status"], "⚪")
        rsi_str   = f"RSI {r['rsi']:.1f}" if r["rsi"] else "RSI n/a"
        price_str = f"${r['price']:.2f}" if r["price"] else "price n/a"
        dte_str   = f"earn {r['dte']}d" if r["dte"] is not None else ""

        console.print(
            f"  [{style}]{icon} {r['ticker']} [{r['status']}][/]  "
            f"[dim]{r['company']} · {r['slot']} · {price_str} · {rsi_str}"
            + (f" · {dte_str}" if dte_str else "")
            + f" · score {r['score']}[/]"
        )
        for issue in r["issues"]:
            console.print(f"    [red]✗ {issue}[/]")
        for pos in r["positives"]:
            console.print(f"    [green]✓ {pos}[/]")

    # Print GREEN alerts prominently
    green = [r for r in results if r["status"] == "GREEN"]
    if green:
        console.print()
        console.print(Panel(
            "[bold green]⚡ ENTRY CONDITIONS MET - Run score.py before entering:[/bold green]\n"
            + "\n".join(f"  → {r['ticker']} ({r['company']}) · {r['slot']} · size {r['size']}" for r in green),
            style="green", expand=False
        ))
    console.print()


def print_lead_indicators_terminal(data: dict, snapshots: dict, console=None) -> None:
    """Print lead indicator reminders based on upcoming earnings."""
    if console is None:
        return

    upcoming = []
    for acct in data["accounts"].values():
        for pos in acct.get("positions", []):
            t   = pos["ticker"]
            dte = snapshots.get(t, {}).get("days_to_earnings")
            if dte is not None and 0 <= dte <= 14:
                upcoming.append((t, dte, pos.get("type", "")))

    if not upcoming:
        return

    console.rule("[bold magenta]🎯 LEAD INDICATORS - CHECK THESE BEFORE EARNINGS[/]")
    for t, dte, ptype in sorted(upcoming, key=lambda x: x[1]):
        console.print(f"  [bold]{t}[/] earnings in [bold yellow]{dte}d[/]")
        if t in ("AMD", "NVDA"):
            console.print("    → Check Polymarket.com for beat probability right now")
            console.print("    → Check unusual_whales.com for call/put flow last 3 days")
            console.print("    → TSMC monthly revenue (released ~10th each month) = upstream signal")
        elif t in ("AAPL",):
            console.print("    → Check Foxconn/Hon Hai monthly revenue (released ~10th)")
            console.print("    → Check Google Trends 'Apple' search volume vs last quarter")
            console.print("    → Check Polymarket beat probability")
        elif t in ("TSM", "ASML"):
            console.print("    → TSMC monthly revenue already IS the signal - check latest release")
            console.print("    → Check SK Hynix / Samsung HBM order news for demand signal")
        elif t in ("MDT", "ABT", "DHR", "SYK"):
            console.print("    → Check FDA device approval calendar (fda.gov/medical-devices)")
            console.print("    → Check hospital capex sentiment (big hospital chains reporting first)")
        elif t in ("CRM", "MSFT", "GOOGL", "META"):
            console.print("    → Check Polymarket beat probability")
            console.print("    → Read competitor earnings for AI spend signal (if GOOGL reports, signals MSFT)")
        elif t in ("NOC", "RTX", "HII", "LMT"):
            console.print("    → Check Congressional NDAA markup for contract names")
            console.print("    → Check DOD press releases (defense.gov) for contract announcements")
        elif t in ("NVO",):
            console.print("    → Check IQVIA / Symphony Health scripts data for Wegovy trends")
            console.print("    → Check Eli Lilly Mounjaro scripts vs Ozempic (competitor signal)")
        else:
            console.print("    → Check Polymarket for beat probability")
            console.print("    → Check unusual_whales.com for options flow")
        console.print()
