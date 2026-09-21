"""
recap.py - Monthly + all-time performance recap from trade history.

Usage:
    python3 recap.py                        # current month recap
    python3 recap.py --month 3 --year 2026  # specific month
    python3 recap.py --all-time             # all-time stats
"""

import socket
socket.setdefaulttimeout(12)

from pathlib import Path
from datetime import datetime
from typing import Optional
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
import argparse

BASE = Path(__file__).resolve().parents[1]
TRADES_FILE    = BASE / "trades_log.json"
HISTORY_FILE   = BASE / "portfolio_history.json"
POSITIONS_FILE = BASE / "positions.json"
console = Console()


# ── Data loaders ──────────────────────────────────────────────────────────

def load_trades() -> list[dict]:
    """Load trades_log.json, return [] if missing/empty."""
    if not TRADES_FILE.exists():
        return []
    try:
        data = json.loads(TRADES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def load_history() -> list[dict]:
    """Load portfolio_history.json, return [] if missing/empty."""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def load_positions() -> dict:
    """Load positions.json."""
    if not POSITIONS_FILE.exists():
        return {}
    try:
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Live portfolio valuation ───────────────────────────────────────────────

def get_current_portfolio_value() -> dict:
    """
    Fetch live prices for all positions, compute total value.
    Returns {roth_value, tod_value, total_value, roth_cash, tod_cash,
             positions: [{ticker, shares, avg_cost, price, value, pl_dollar, pl_pct}]}
    Falls back to avg_cost if yfinance fails.
    """
    data = load_positions()
    accounts = data.get("accounts", {})
    roth = accounts.get("ROTH", {})
    tod  = accounts.get("TOD", {})

    all_tickers = [
        p["ticker"]
        for acct in [roth, tod]
        for p in acct.get("positions", [])
    ]

    # Fetch live prices via yfinance
    prices: dict[str, float] = {}
    if all_tickers:
        try:
            import yfinance as yf
            raw = yf.download(
                " ".join(all_tickers),
                period="2d",
                interval="1d",
                auto_adjust=True,
                progress=False,
            )
            close = raw["Close"] if "Close" in raw.columns else raw
            if len(all_tickers) == 1:
                ticker = all_tickers[0]
                prices[ticker] = float(close.dropna().iloc[-1])
            else:
                for t in all_tickers:
                    if t in close.columns:
                        series = close[t].dropna()
                        if not series.empty:
                            prices[t] = float(series.iloc[-1])
        except Exception:
            pass  # fall through to avg_cost fallback

    def build_position_rows(acct: dict) -> tuple[list[dict], float]:
        rows = []
        total = acct.get("cash", 0.0)
        for p in acct.get("positions", []):
            ticker    = p["ticker"]
            shares    = p.get("shares", 0)
            avg_cost  = p.get("avg_cost", 0.0)
            price     = prices.get(ticker, avg_cost)
            value     = round(price * shares, 2)
            pl_dollar = round((price - avg_cost) * shares, 2)
            pl_pct    = round((price - avg_cost) / avg_cost * 100, 2) if avg_cost else 0.0
            total    += value
            rows.append({
                "ticker":    ticker,
                "shares":    shares,
                "avg_cost":  avg_cost,
                "price":     price,
                "value":     value,
                "pl_dollar": pl_dollar,
                "pl_pct":    pl_pct,
                "live":      ticker in prices,
            })
        return rows, round(total, 2)

    roth_rows, roth_total = build_position_rows(roth)
    tod_rows,  tod_total  = build_position_rows(tod)

    roth_cash = roth.get("cash", 0.0)
    tod_cash  = tod.get("cash", 0.0)

    return {
        "roth_value":  roth_total,
        "tod_value":   tod_total,
        "total_value": round(roth_total + tod_total, 2),
        "roth_cash":   roth_cash,
        "tod_cash":    tod_cash,
        "positions":   roth_rows + tod_rows,
    }


# ── Analytics ─────────────────────────────────────────────────────────────

def _parse_exit_date(trade: dict) -> Optional[datetime]:
    """Parse exit_date or date field from a trade dict."""
    raw = trade.get("exit_date") or trade.get("date")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            pass
    return None


def get_monthly_recap(month: int = None, year: int = None) -> dict:
    """
    Default = current month/year.
    Filters trades by exit_date (or date) in that month/year.
    Returns {month_str, trades_closed, wins, losses, win_rate,
             total_pl_dollar, best_trade, worst_trade,
             portfolio_start, portfolio_end, portfolio_change_pct,
             avg_hold_days, closed_trades}
    Handles empty gracefully.
    """
    now   = datetime.now()
    month = month or now.month
    year  = year  or now.year

    month_str = datetime(year, month, 1).strftime("%B %Y")

    all_trades = load_trades()
    closed = [
        t for t in all_trades
        if (d := _parse_exit_date(t)) and d.month == month and d.year == year
    ]

    if not closed:
        return {
            "month_str":           month_str,
            "trades_closed":       0,
            "wins":                0,
            "losses":              0,
            "win_rate":            0.0,
            "total_pl_dollar":     0.0,
            "best_trade":          None,
            "worst_trade":         None,
            "portfolio_start":     None,
            "portfolio_end":       None,
            "portfolio_change_pct": None,
            "avg_hold_days":       None,
            "closed_trades":       [],
        }

    wins   = [t for t in closed if t.get("pl_dollar", 0) > 0]
    losses = [t for t in closed if t.get("pl_dollar", 0) <= 0]

    total_pl = round(sum(t.get("pl_dollar", 0) for t in closed), 2)
    best     = max(closed, key=lambda t: t.get("pl_dollar", 0))
    worst    = min(closed, key=lambda t: t.get("pl_dollar", 0))

    hold_days_list = [
        t.get("hold_days") or t.get("days_held")
        for t in closed
        if (t.get("hold_days") or t.get("days_held")) is not None
    ]
    avg_hold = round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else None

    # Portfolio value at start/end of month from history
    history = load_history()
    month_prefix_start = f"{year:04d}-{month:02d}-01"
    month_prefix_end   = f"{year:04d}-{month:02d}"

    month_entries = [h for h in history if h.get("date", "").startswith(month_prefix_end)]
    port_start = month_entries[0].get("total")  if month_entries else None
    port_end   = month_entries[-1].get("total") if month_entries else None
    port_chg   = None
    if port_start and port_end and port_start != 0:
        port_chg = round((port_end - port_start) / port_start * 100, 2)

    return {
        "month_str":            month_str,
        "trades_closed":        len(closed),
        "wins":                 len(wins),
        "losses":               len(losses),
        "win_rate":             round(len(wins) / len(closed) * 100, 1),
        "total_pl_dollar":      total_pl,
        "best_trade":           best,
        "worst_trade":          worst,
        "portfolio_start":      port_start,
        "portfolio_end":        port_end,
        "portfolio_change_pct": port_chg,
        "avg_hold_days":        avg_hold,
        "closed_trades":        closed,
    }


def get_all_time_stats() -> dict:
    """
    All trades ever.
    Returns {total_trades, wins, losses, win_rate, total_pl_dollar,
             best_trade, worst_trade, avg_hold_days,
             by_ticker: {ticker: {trades, pl_dollar, win_rate}}}
    """
    all_trades = load_trades()
    if not all_trades:
        return {
            "total_trades":  0,
            "wins":          0,
            "losses":        0,
            "win_rate":      0.0,
            "total_pl_dollar": 0.0,
            "best_trade":    None,
            "worst_trade":   None,
            "avg_hold_days": None,
            "by_ticker":     {},
        }

    wins   = [t for t in all_trades if t.get("pl_dollar", 0) > 0]
    losses = [t for t in all_trades if t.get("pl_dollar", 0) <= 0]
    total_pl = round(sum(t.get("pl_dollar", 0) for t in all_trades), 2)
    best  = max(all_trades, key=lambda t: t.get("pl_dollar", 0))
    worst = min(all_trades, key=lambda t: t.get("pl_dollar", 0))

    hold_days_list = [
        t.get("hold_days") or t.get("days_held")
        for t in all_trades
        if (t.get("hold_days") or t.get("days_held")) is not None
    ]
    avg_hold = round(sum(hold_days_list) / len(hold_days_list), 1) if hold_days_list else None

    # Per-ticker breakdown
    by_ticker: dict[str, dict] = {}
    for t in all_trades:
        ticker = t.get("ticker", "?")
        if ticker not in by_ticker:
            by_ticker[ticker] = {"trades": 0, "pl_dollar": 0.0, "wins": 0}
        by_ticker[ticker]["trades"]   += 1
        by_ticker[ticker]["pl_dollar"] = round(by_ticker[ticker]["pl_dollar"] + t.get("pl_dollar", 0), 2)
        if t.get("pl_dollar", 0) > 0:
            by_ticker[ticker]["wins"] += 1

    for ticker, stats in by_ticker.items():
        stats["win_rate"] = round(stats["wins"] / stats["trades"] * 100, 1) if stats["trades"] else 0.0

    return {
        "total_trades":    len(all_trades),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(len(wins) / len(all_trades) * 100, 1),
        "total_pl_dollar": total_pl,
        "best_trade":      best,
        "worst_trade":     worst,
        "avg_hold_days":   avg_hold,
        "by_ticker":       by_ticker,
    }


# ── Rich output ───────────────────────────────────────────────────────────

def _pl_color(val: float) -> str:
    return "green" if val >= 0 else "red"


def _fmt_pl(val: float, prefix: str = "$") -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{prefix}{val:,.2f}"


def print_monthly_recap(month: int = None, year: int = None) -> None:
    """Rich output: summary panel + trades table."""
    r = get_monthly_recap(month, year)

    # ── Summary panel ──
    pl      = r["total_pl_dollar"]
    pl_clr  = _pl_color(pl)
    wrate   = r["win_rate"]
    w_clr   = "green" if wrate >= 50 else "red"

    lines = [f"[bold]{r['month_str']}[/bold]  -  closed trades recap\n"]

    if r["trades_closed"] == 0:
        lines.append("[dim]No closed trades yet - keep building the record.[/dim]")
    else:
        lines.append(
            f"Closed trades : [bold]{r['trades_closed']}[/bold]  "
            f"([green]{r['wins']}W[/green] / [red]{r['losses']}L[/red])"
        )
        lines.append(f"Win rate      : [{w_clr}]{wrate}%[/{w_clr}]")
        lines.append(f"Net P&L       : [{pl_clr}]{_fmt_pl(pl)}[/{pl_clr}]")

        if r["avg_hold_days"] is not None:
            lines.append(f"Avg hold      : {r['avg_hold_days']} days")

        if r["portfolio_start"] is not None and r["portfolio_end"] is not None:
            chg_clr = _pl_color(r["portfolio_change_pct"] or 0)
            lines.append(
                f"Portfolio     : ${r['portfolio_start']:,.0f} → ${r['portfolio_end']:,.0f}  "
                f"[{chg_clr}]({_fmt_pl(r['portfolio_change_pct'] or 0, prefix='')}%)[/{chg_clr}]"
            )

        if r["best_trade"]:
            b = r["best_trade"]
            lines.append(
                f"Best trade    : [green]{b.get('ticker','?')}[/green]  "
                f"[green]{_fmt_pl(b.get('pl_dollar',0))}  ({_fmt_pl(b.get('pl_pct',0),'')}{'' if b.get('pl_pct',0) < 0 else ''}%)[/green]"
            )
        if r["worst_trade"] and r["worst_trade"] != r["best_trade"]:
            w = r["worst_trade"]
            lines.append(
                f"Worst trade   : [red]{w.get('ticker','?')}[/red]  "
                f"[red]{_fmt_pl(w.get('pl_dollar',0))}  ({_fmt_pl(w.get('pl_pct',0),'')}{'' if w.get('pl_pct',0) < 0 else ''}%)[/red]"
            )

    console.print(Panel("\n".join(lines), border_style="blue", padding=(0, 1)))

    # ── Trades table ──
    if not r["closed_trades"]:
        return

    tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    tbl.add_column("Date",    style="dim",   width=12)
    tbl.add_column("Acct",    width=6)
    tbl.add_column("Ticker",  style="bold",  width=8)
    tbl.add_column("Shares",  justify="right", width=7)
    tbl.add_column("Entry",   justify="right", width=8)
    tbl.add_column("Exit",    justify="right", width=8)
    tbl.add_column("P&L $",   justify="right", width=10)
    tbl.add_column("P&L %",   justify="right", width=8)
    tbl.add_column("Days",    justify="right", width=6)

    for t in sorted(r["closed_trades"], key=lambda x: _parse_exit_date(x) or datetime.min):
        pl_d  = t.get("pl_dollar", 0)
        pl_p  = t.get("pl_pct", 0)
        clr   = _pl_color(pl_d)
        sign  = "+" if pl_d >= 0 else ""
        hold  = str(t.get("hold_days") or t.get("days_held") or "-")
        entry = t.get("entry_price") or t.get("avg_cost") or 0
        exit_ = t.get("exit_price") or t.get("sell_price") or 0
        date_ = (t.get("exit_date") or t.get("date") or "")[:10]
        tbl.add_row(
            date_,
            t.get("account", "-"),
            t.get("ticker", "-"),
            str(t.get("shares", "-")),
            f"${entry:.2f}",
            f"${exit_:.2f}",
            f"[{clr}]{sign}${pl_d:,.2f}[/{clr}]",
            f"[{clr}]{sign}{pl_p:.1f}%[/{clr}]",
            hold,
        )

    console.print(tbl)


def print_all_time_stats() -> None:
    """Rich output: overall stats + per-ticker breakdown."""
    s = get_all_time_stats()

    # ── Summary panel ──
    lines = ["[bold]All-Time Performance[/bold]\n"]

    if s["total_trades"] == 0:
        lines.append("[dim]No closed trades yet - keep building the record.[/dim]")
        console.print(Panel("\n".join(lines), border_style="magenta", padding=(0, 1)))
        return

    pl     = s["total_pl_dollar"]
    pl_clr = _pl_color(pl)
    w_clr  = "green" if s["win_rate"] >= 50 else "red"

    lines.append(
        f"Total trades  : [bold]{s['total_trades']}[/bold]  "
        f"([green]{s['wins']}W[/green] / [red]{s['losses']}L[/red])"
    )
    lines.append(f"Win rate      : [{w_clr}]{s['win_rate']}%[/{w_clr}]")
    lines.append(f"Net P&L       : [{pl_clr}]{_fmt_pl(pl)}[/{pl_clr}]")

    if s["avg_hold_days"] is not None:
        lines.append(f"Avg hold      : {s['avg_hold_days']} days")

    if s["best_trade"]:
        b = s["best_trade"]
        lines.append(
            f"Best trade    : [green]{b.get('ticker','?')}[/green]  "
            f"[green]{_fmt_pl(b.get('pl_dollar',0))}  ({b.get('pl_pct',0):+.1f}%)[/green]"
        )
    if s["worst_trade"] and s["worst_trade"] is not s["best_trade"]:
        w = s["worst_trade"]
        lines.append(
            f"Worst trade   : [red]{w.get('ticker','?')}[/red]  "
            f"[red]{_fmt_pl(w.get('pl_dollar',0))}  ({w.get('pl_pct',0):+.1f}%)[/red]"
        )

    console.print(Panel("\n".join(lines), border_style="magenta", padding=(0, 1)))

    # ── Per-ticker breakdown ──
    if not s["by_ticker"]:
        return

    tbl = Table(
        title="[bold]Per-Ticker Breakdown[/bold]",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold cyan",
    )
    tbl.add_column("Ticker",   style="bold", width=10)
    tbl.add_column("Trades",   justify="right", width=8)
    tbl.add_column("Net P&L",  justify="right", width=12)
    tbl.add_column("Win Rate", justify="right", width=10)

    sorted_tickers = sorted(
        s["by_ticker"].items(),
        key=lambda x: x[1]["pl_dollar"],
        reverse=True,
    )

    for ticker, stats in sorted_tickers:
        pl_d  = stats["pl_dollar"]
        clr   = _pl_color(pl_d)
        sign  = "+" if pl_d >= 0 else ""
        wr    = stats["win_rate"]
        w_clr = "green" if wr >= 50 else "red"
        tbl.add_row(
            ticker,
            str(stats["trades"]),
            f"[{clr}]{sign}${pl_d:,.2f}[/{clr}]",
            f"[{w_clr}]{wr}%[/{w_clr}]",
        )

    console.print(tbl)


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Trading recap - monthly or all-time performance from trades_log.json"
    )
    parser.add_argument("--month",    type=int, default=None, help="Month number (1-12)")
    parser.add_argument("--year",     type=int, default=None, help="Year (e.g. 2026)")
    parser.add_argument("--all-time", action="store_true",    help="Show all-time stats")
    args = parser.parse_args()

    if args.all_time:
        print_all_time_stats()
    else:
        print_monthly_recap(args.month, args.year)
