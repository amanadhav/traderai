"""
Dividend calendar module - standalone, no dependencies on morning_run.py.
Usage: python dividends.py
"""

from __future__ import annotations

import socket
socket.setdefaulttimeout(12)

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box

BASE = Path(__file__).resolve().parents[1]
console = Console()


# ── Core per-ticker lookup ─────────────────────────────────────────────────

def get_dividend_info(ticker: str) -> dict:
    """
    Returns a dict with dividend data for a single ticker.

    Keys:
        ticker          str
        ex_date         str YYYY-MM-DD or None
        pay_date        str YYYY-MM-DD or None
        days_to_ex      int (negative = already passed) or None
        annual_rate     float  $/sh/yr  (trailingAnnualDividendRate or dividendRate)
        div_yield       float  % (trailingAnnualDividendYield * 100)
        frequency       int or None  (payments per year, inferred from rate / last amount)
        last_div_amount float  $/sh per payment
        has_dividend    bool
    """
    result: dict = {
        "ticker": ticker,
        "ex_date": None,
        "pay_date": None,
        "days_to_ex": None,
        "annual_rate": 0.0,
        "div_yield": 0.0,
        "frequency": None,
        "last_div_amount": 0.0,
        "has_dividend": False,
    }

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # ── ex-dividend date ──────────────────────────────────────────────
        ex_ts = info.get("exDividendDate")
        if ex_ts:
            try:
                ex_dt = datetime.fromtimestamp(int(ex_ts)).date()
                result["ex_date"] = ex_dt.isoformat()
                today = datetime.now().date()
                result["days_to_ex"] = (ex_dt - today).days
            except (OSError, OverflowError, ValueError):
                pass

        # ── pay date ─────────────────────────────────────────────────────
        pay_ts = info.get("dividendDate")
        if pay_ts:
            try:
                pay_dt = datetime.fromtimestamp(int(pay_ts)).date()
                result["pay_date"] = pay_dt.isoformat()
            except (OSError, OverflowError, ValueError):
                pass

        # ── rates ────────────────────────────────────────────────────────
        annual_rate = info.get("trailingAnnualDividendRate") or info.get("dividendRate") or 0.0
        result["annual_rate"] = float(annual_rate)

        raw_yield = info.get("trailingAnnualDividendYield") or 0.0
        result["div_yield"] = round(float(raw_yield) * 100, 3)

        # ── last dividend amount from history ─────────────────────────────
        try:
            hist = t.dividends
            if hist is not None and not hist.empty:
                last_amt = float(hist.iloc[-1])
                result["last_div_amount"] = last_amt
                # infer frequency: annualRate / last_amount ≈ payments/yr
                if last_amt > 0 and annual_rate > 0:
                    freq_raw = round(annual_rate / last_amt)
                    result["frequency"] = int(freq_raw) if 1 <= freq_raw <= 52 else None
        except Exception:
            pass

        # ── has_dividend ──────────────────────────────────────────────────
        result["has_dividend"] = result["annual_rate"] > 0 or result["last_div_amount"] > 0

    except Exception as exc:
        console.print(f"[dim red]  {ticker}: fetch error - {exc}[/]")

    return result


# ── Portfolio-wide lookup ──────────────────────────────────────────────────

def get_portfolio_dividends(
    positions_file: Path = BASE / "positions.json",
) -> dict[str, dict]:
    """
    Loads all positions from positions_file, fetches dividend info for each
    unique ticker, and returns {ticker: dividend_info_dict}.
    """
    with open(positions_file, encoding="utf-8") as f:
        data = json.load(f)

    tickers: list[str] = []
    for account in data.get("accounts", {}).values():
        for pos in account.get("positions", []):
            t = pos.get("ticker")
            if t and t not in tickers:
                tickers.append(t)

    results: dict[str, dict] = {}
    for ticker in tickers:
        console.print(f"[dim]  Fetching {ticker}...[/]", end="\r")
        results[ticker] = get_dividend_info(ticker)

    # clear the carriage-return line
    console.print(" " * 40, end="\r")
    return results


# ── Upcoming ex-dates ──────────────────────────────────────────────────────

def upcoming_ex_dates(
    div_data: dict,
    positions_data: dict,
    days_ahead: int = 30,
) -> list[dict]:
    """
    Returns a list of upcoming ex-dividend events within `days_ahead` days,
    sorted by days_to_ex ascending.

    Each item: {ticker, ex_date, days_to_ex, shares, projected_payout}
    projected_payout = shares * last_div_amount
    """
    # Build a {ticker: shares} map across all accounts
    shares_map: dict[str, float] = {}
    for account in positions_data.get("accounts", {}).values():
        for pos in account.get("positions", []):
            t = pos.get("ticker", "")
            if t:
                shares_map[t] = shares_map.get(t, 0) + pos.get("shares", 0)

    upcoming: list[dict] = []
    for ticker, info in div_data.items():
        days = info.get("days_to_ex")
        if days is None:
            continue
        if 0 <= days <= days_ahead:
            shares = shares_map.get(ticker, 0)
            last_amt = info.get("last_div_amount", 0.0)
            upcoming.append(
                {
                    "ticker": ticker,
                    "ex_date": info["ex_date"],
                    "days_to_ex": days,
                    "shares": shares,
                    "projected_payout": round(shares * last_amt, 2),
                }
            )

    upcoming.sort(key=lambda x: x["days_to_ex"])
    return upcoming


# ── Rich terminal output ───────────────────────────────────────────────────

def print_dividend_calendar(div_data: dict, positions_data: dict) -> None:
    """
    Prints a Rich terminal table showing dividend info for all portfolio positions.
    Rows with no dividend are shown in dim style. Upcoming ex-dates get a highlight.
    """
    # Build shares map
    shares_map: dict[str, float] = {}
    account_map: dict[str, str] = {}
    for acct_name, account in positions_data.get("accounts", {}).items():
        for pos in account.get("positions", []):
            t = pos.get("ticker", "")
            if t:
                shares_map[t] = shares_map.get(t, 0) + pos.get("shares", 0)
                account_map[t] = acct_name

    today = datetime.now().date()

    # ── Full calendar table ────────────────────────────────────────────────
    table = Table(
        title=f"[bold]Dividend Calendar[/bold]  [dim]{today.isoformat()}[/dim]",
        box=box.SIMPLE_HEAD,
        show_lines=False,
        header_style="bold cyan",
        expand=False,
    )
    table.add_column("Ticker", style="bold", width=7)
    table.add_column("Acct", width=5)
    table.add_column("Shares", justify="right", width=7)
    table.add_column("Ex-Date", width=12)
    table.add_column("Days", justify="right", width=6)
    table.add_column("Pay-Date", width=12)
    table.add_column("$/sh/yr", justify="right", width=8)
    table.add_column("Yield %", justify="right", width=8)
    table.add_column("$/pmt", justify="right", width=7)
    table.add_column("Freq", justify="right", width=5)
    table.add_column("Proj Payout", justify="right", width=12)

    # Sort: dividend payers first (by days_to_ex), then non-payers alphabetically
    def sort_key(item):
        ticker, info = item
        has_div = info.get("has_dividend", False)
        days = info.get("days_to_ex")
        if not has_div:
            return (2, 9999, ticker)
        if days is not None:
            return (0, days, ticker)
        return (1, 9999, ticker)

    for ticker, info in sorted(div_data.items(), key=sort_key):
        shares = shares_map.get(ticker, 0)
        acct = account_map.get(ticker, "")
        has_div = info.get("has_dividend", False)
        days = info.get("days_to_ex")
        ex_date = info.get("ex_date") or "-"
        pay_date = info.get("pay_date") or "-"
        annual_rate = info.get("annual_rate", 0.0)
        div_yield = info.get("div_yield", 0.0)
        last_amt = info.get("last_div_amount", 0.0)
        freq = info.get("frequency")
        proj = round(shares * last_amt, 2) if last_amt else 0.0

        # Days styling
        if days is None:
            days_str = "-"
            days_style = "dim"
        elif days < 0:
            days_str = f"{days}d"
            days_style = "dim"
        elif days <= 7:
            days_str = f"{days}d"
            days_style = "bold red"
        elif days <= 14:
            days_str = f"{days}d"
            days_style = "bold yellow"
        else:
            days_str = f"{days}d"
            days_style = "green"

        row_style = "dim" if not has_div else ""

        table.add_row(
            ticker,
            acct,
            str(int(shares)),
            ex_date,
            f"[{days_style}]{days_str}[/{days_style}]",
            pay_date,
            f"${annual_rate:.2f}" if annual_rate else "-",
            f"{div_yield:.2f}%" if div_yield else "-",
            f"${last_amt:.4f}" if last_amt else "-",
            str(freq) if freq else "-",
            f"${proj:.2f}" if proj else "-",
            style=row_style,
        )

    console.print()
    console.print(table)

    # ── Upcoming ex-dates panel ────────────────────────────────────────────
    upcoming = upcoming_ex_dates(div_data, positions_data, days_ahead=30)
    if upcoming:
        up_table = Table(
            title="[bold yellow]Upcoming Ex-Dividend Dates (next 30 days)[/bold yellow]",
            box=box.SIMPLE_HEAD,
            header_style="bold yellow",
            expand=False,
        )
        up_table.add_column("Ticker", style="bold", width=7)
        up_table.add_column("Ex-Date", width=12)
        up_table.add_column("Days", justify="right", width=6)
        up_table.add_column("Shares", justify="right", width=7)
        up_table.add_column("Proj Payout", justify="right", width=12)

        for item in upcoming:
            d = item["days_to_ex"]
            d_style = "bold red" if d <= 7 else ("bold yellow" if d <= 14 else "green")
            up_table.add_row(
                item["ticker"],
                item["ex_date"],
                f"[{d_style}]{d}d[/{d_style}]",
                str(int(item["shares"])),
                f"${item['projected_payout']:.2f}",
            )

        console.print(up_table)
    else:
        console.print("[dim]No ex-dividend dates in the next 30 days.[/dim]\n")

    # ── Summary line ──────────────────────────────────────────────────────
    payers = [t for t, i in div_data.items() if i.get("has_dividend")]
    total_annual = sum(
        shares_map.get(t, 0) * div_data[t].get("annual_rate", 0.0)
        for t in payers
    )
    console.print(
        f"[bold]Portfolio dividend income:[/bold] "
        f"[green]${total_annual:.2f}/yr[/green]  "
        f"[dim]({len(payers)} of {len(div_data)} positions pay dividends)[/dim]\n"
    )


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    positions_file = BASE / "positions.json"

    console.print("[bold cyan]Loading positions...[/bold cyan]")
    with open(positions_file, encoding="utf-8") as f:
        positions_data = json.load(f)

    console.print("[bold cyan]Fetching dividend data from yfinance...[/bold cyan]")
    div_data = get_portfolio_dividends(positions_file)

    print_dividend_calendar(div_data, positions_data)
