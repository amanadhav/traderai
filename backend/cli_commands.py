"""
cli_commands.py - Subcommand handlers for the `trading` CLI.

Each cmd_* function: parses its own argparse args, mutates positions.json
via persistence module, prints results to its own Console.

Decoupled from morning_run.py - does NOT share its recording Console
because cmd_* run as one-shot invocations (no morning_run_log.txt
capture needed). Cleaner imports.

Subcommands:
  cmd_buy        - add shares (or new position) to ROTH/TOD
  cmd_sell       - close shares, log trade
  cmd_stop       - set GTC stop on a position
  cmd_score      - run 180pt or spec scorer on any ticker
  cmd_positions  - show all positions (no live fetch)
  cmd_scan       - invoke scan.py for full market scan
  cmd_news       - invoke news.py for headline sweep
  cmd_breadth    - invoke breadth.py for market breadth
  cmd_server     - start API + React frontend at localhost:5173
  cmd_help       - usage text
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console

from persistence import (
    BASE, POSITIONS_FILE,
    _load_data, _save_data, log_trade,
)
from positions import _find_position
from data_fetch import get_full_snapshot
from terminal_ui import print_positions_table

console = Console()


def cmd_buy(args: list[str]) -> None:
    """
    trading buy ACCOUNT TICKER SHARES PRICE [--stop STOP] [--type TYPE] [--thesis TEXT]
    Examples:
      trading buy ROTH RTX 4 160.00
      trading buy TOD TSLA 5 250.00 --stop 212.50 --type L --thesis "EV + autonomous"
    """
    import argparse
    p = argparse.ArgumentParser(prog="trading buy")
    p.add_argument("account")
    p.add_argument("ticker")
    p.add_argument("shares", type=float)
    p.add_argument("price", type=float)
    p.add_argument("--stop", type=float, default=None)
    p.add_argument("--type", dest="ptype", default=None,
                   choices=["S", "L", "I", "Lifetime", "Spec"])
    p.add_argument("--thesis", default="")
    p.add_argument("--notes", default="")
    ns = p.parse_args(args)

    data   = _load_data()
    ticker = ns.ticker.upper()
    acct   = ns.account.upper()
    shares = ns.shares
    price  = ns.price

    pos, pos_list = _find_position(data, acct, ticker)

    if pos:
        # Update existing position - weighted avg cost
        old_sh  = pos["shares"]
        old_avg = pos["avg_cost"]
        new_sh  = old_sh + shares
        new_avg = round((old_sh * old_avg + shares * price) / new_sh, 4)
        pos["shares"]   = new_sh
        pos["avg_cost"] = new_avg
        if ns.stop is not None:
            pos["stop"] = ns.stop
        console.print(f"[cyan]Updated {ticker} in {acct}:[/] {old_sh}sh @${old_avg:.2f} + {shares}sh @${price:.2f} → {new_sh}sh @${new_avg:.2f}")
    else:
        # New position
        ptype   = ns.ptype or ("Spec" if shares * price < 600 else "L")
        new_pos = {
            "ticker":       ticker,
            "shares":       shares,
            "avg_cost":     round(price, 4),
            "stop":         ns.stop,
            "stop_type":    "GTC Stop Market" if ns.stop else None,
            "stop_shares":  shares if ns.stop else 0,
            "type":         ptype,
            "entry_date":   datetime.now().strftime("%Y-%m-%d"),
            "thesis":       ns.thesis,
            "notes":        ns.notes,
            "pending_orders": [],
        }
        data["accounts"][acct]["positions"].append(new_pos)
        console.print(f"[green]Added {ticker} to {acct}:[/] {shares}sh @${price:.2f} | type={ptype} | stop=${ns.stop}")
        if not ns.stop:
            console.print("[yellow]⚠️  No stop set - add one: trading stop ACCOUNT TICKER STOP_PRICE[/]")

    _save_data(data)


def cmd_sell(args: list[str]) -> None:
    """
    trading sell ACCOUNT TICKER SHARES PRICE
    Example: trading sell ROTH NKE 4 53.00
    """
    import argparse
    p = argparse.ArgumentParser(prog="trading sell")
    p.add_argument("account")
    p.add_argument("ticker")
    p.add_argument("shares", type=float)
    p.add_argument("price", type=float)
    ns = p.parse_args(args)

    data   = _load_data()
    ticker = ns.ticker.upper()
    acct   = ns.account.upper()

    pos, pos_list = _find_position(data, acct, ticker)
    if not pos:
        console.print(f"[red]❌ {ticker} not found in {acct}[/]")
        return

    shares_sold = ns.shares
    sell_price  = ns.price
    avg_cost    = pos["avg_cost"]
    old_shares  = pos["shares"]

    if shares_sold > old_shares:
        console.print(f"[red]❌ Can't sell {shares_sold}sh - only have {old_shares}sh[/]")
        return

    pl_per_sh = sell_price - avg_cost
    pl_total  = pl_per_sh * shares_sold
    pl_pct    = (pl_per_sh / avg_cost) * 100
    pl_color  = "green" if pl_total >= 0 else "red"

    console.print(
        f"[{pl_color}]{'📈' if pl_total >= 0 else '📉'} TRADE: SELL {shares_sold}sh {ticker} @${sell_price:.2f}[/]\n"
        f"   Avg cost: ${avg_cost:.2f} | P&L: {'+' if pl_total >= 0 else ''}{pl_pct:.1f}% | "
        f"${'+' if pl_total >= 0 else ''}{pl_total:.2f}"
    )

    remaining = old_shares - shares_sold
    if remaining == 0:
        pos_list.remove(pos)
        console.print(f"[dim]Position closed - {ticker} removed from {acct}[/]")
    else:
        pos["shares"] = remaining
        console.print(f"[dim]{remaining}sh remaining @${avg_cost:.2f}[/]")

    log_trade(acct, ticker, shares_sold, avg_cost, sell_price, pos.get("entry_date"))
    _save_data(data)


def cmd_stop(args: list[str]) -> None:
    """
    trading stop ACCOUNT TICKER STOP_PRICE [SHARES]
    Example: trading stop ROTH RTX 147.00 10
    """
    import argparse
    p = argparse.ArgumentParser(prog="trading stop")
    p.add_argument("account")
    p.add_argument("ticker")
    p.add_argument("stop_price", type=float)
    p.add_argument("shares", type=float, nargs="?", default=None)
    ns = p.parse_args(args)

    data   = _load_data()
    ticker = ns.ticker.upper()
    acct   = ns.account.upper()

    pos, _ = _find_position(data, acct, ticker)
    if not pos:
        console.print(f"[red]❌ {ticker} not found in {acct}[/]")
        return

    pos["stop"]       = ns.stop_price
    pos["stop_type"]  = "GTC Stop Market"
    pos["stop_shares"] = ns.shares if ns.shares is not None else pos["shares"]
    console.print(f"[green]✅ {ticker} stop set → ${ns.stop_price:.2f} on {pos['stop_shares']}sh[/]")
    _save_data(data)


def cmd_score(args: list[str]) -> None:
    """
    trading score TICKER
    Example: trading score TSLA
    """
    if not args:
        console.print("[red]Usage: trading score TICKER[/]")
        return
    ticker = args[0].upper()
    console.print(f"[dim]Fetching data for {ticker}...[/]")
    snap = get_full_snapshot(ticker)
    if snap.get("error"):
        console.print(f"[red]❌ Failed to fetch {ticker}: {snap['error']}[/]")
        return

    import score as sc
    import patterns as pat_mod
    prices  = snap.get("prices")
    rsi_s   = snap.get("rsi_series")
    pat_res = pat_mod.detect(prices, rsi_series=rsi_s) if prices is not None else {}
    result  = sc.score_ticker(snap, pattern_result=pat_res)
    console.print(sc.explain_score(result))


def cmd_positions(args: list[str]) -> None:
    """Print current positions without fetching live prices."""
    data = _load_data()
    for acct_name, acct in data["accounts"].items():
        console.rule(f"[bold cyan]{acct_name}[/]")
        t = Table(box=box.SIMPLE)
        t.add_column("Ticker", style="bold")
        t.add_column("Shares")
        t.add_column("Avg Cost")
        t.add_column("Stop")
        t.add_column("Type")
        t.add_column("Thesis", max_width=50)
        for pos in acct.get("positions", []):
            stop = f"${pos['stop']:.2f}" if pos.get("stop") else "-"
            t.add_row(
                pos["ticker"],
                str(pos["shares"]),
                f"${pos['avg_cost']:.2f}",
                stop,
                pos.get("type", ""),
                pos.get("thesis", "")[:60],
            )
        console.print(t)
        console.print(f"  Cash: ${acct.get('cash', 0):,.2f}\n")


def cmd_scan(args: list[str]) -> None:
    """Run full US market scan using scan.py."""
    import subprocess
    scan_script = Path(__file__).parent / "scan.py"
    if not scan_script.exists():
        console.print("[red]scan.py not found in trading directory[/]")
        return
    subprocess.run([sys.executable, str(scan_script)] + args)


def cmd_news(args: list[str]) -> None:
    """Run news_engine.py - real-time macro + portfolio news."""
    import subprocess
    news_script = Path(__file__).parent / "news_engine.py"
    if not news_script.exists():
        console.print("[red]news_engine.py not found[/]")
        return
    if not args:
        args = ["morning"]
    subprocess.run([sys.executable, str(news_script)] + args)


def cmd_breadth(args: list[str]) -> None:
    """Run breadth.py - market breadth indicators."""
    import subprocess
    breadth_script = Path(__file__).parent / "breadth.py"
    if not breadth_script.exists():
        console.print("[red]breadth.py not found[/]")
        return
    subprocess.run([sys.executable, str(breadth_script)] + args)


def cmd_server(args: list[str]) -> None:
    """Start FastAPI backend + Vite frontend, open browser."""
    import subprocess
    import threading
    import time
    import webbrowser

    fe_dir = BASE / "frontend"
    fe_built = fe_dir / "dist" / "index.html"

    # Start API server
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--reload", "--port", "8000"],
        cwd=BASE,
    )

    # Start Vite dev server if dist not built
    fe_proc = None
    if (fe_dir / "package.json").exists():
        npm = "npm.cmd" if os.name == "nt" else "npm"
        fe_proc = subprocess.Popen(
            [npm, "run", "dev"],
            cwd=fe_dir,
        )
        url = "http://localhost:5173"
    else:
        url = "http://localhost:8000"

    console.print(f"[green]API:[/]      http://localhost:8000")
    console.print(f"[green]Frontend:[/] {url}")
    console.print("[dim]Press Ctrl+C to stop[/]")

    time.sleep(2)
    webbrowser.open(url)

    try:
        api_proc.wait()
    except KeyboardInterrupt:
        api_proc.terminate()
        if fe_proc:
            fe_proc.terminate()


def cmd_help() -> None:
    console.print("""
[bold]trading[/]              Morning briefing - live prices, action items, tracker.html
[bold]trading server[/]       Start web app at localhost:5173 (API + React frontend)
[bold]trading scan[/]         Full US market scan via scan.py (finds new candidates)
[bold]trading scan --quick[/] S&P 500 only scan (~8 min)
[bold]trading news[/]         Real-time macro + portfolio news (Finnhub + NewsAPI)
[bold]trading news breaking[/] Last 60 min only
[bold]trading breadth[/]      Market breadth: % above 50MA, A/D ratio, regime classification
[bold]trading breadth --quick[/] 100-stock sample (~30s)
[bold]trading positions[/]    Show all positions (no live fetch)
[bold]trading buy[/]  ACCT TICKER SHARES PRICE [--stop N] [--type S|L|I|Lifetime|Spec] [--thesis "..."]
[bold]trading sell[/] ACCT TICKER SHARES PRICE
[bold]trading stop[/] ACCT TICKER STOP_PRICE [SHARES]
[bold]trading score[/] TICKER        Run 180-pt entry score on any stock ticker
[bold]trading etf[/] TICKER          ETF sector thesis score (5-factor, 0-100)
[bold]trading etf --all[/]           Score all ETFs in knowledge base
[bold]trading etf --sector energy[/] Score all energy ETFs (defense / ai / healthcare / materials / macro)

Accounts: ROTH | TOD
Examples:
  trading server
  trading buy ROTH RTX 4 160.00 --stop 147.00
  trading sell ROTH NKE 4 53.00
  trading stop ROTH MDT 72.68 20
  trading score TSLA
  trading etf NUCL
  trading etf --sector energy
  trading etf --all
""")
