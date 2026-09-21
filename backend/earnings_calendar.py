"""
earnings_calendar.py - Standalone bulletproof earnings detection module.

4-source detection with conflict flagging, urgency classification,
and rich terminal output. Usable standalone or imported by morning_run.py.
"""

import socket
socket.setdefaulttimeout(12)

from pathlib import Path
from datetime import datetime, date as _date, timezone, timedelta
from typing import Optional
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box
import json

BASE = Path(__file__).resolve().parents[1]
console = Console()


def get_earnings_info(ticker: str) -> dict:
    """
    4-source bulletproof earnings date detection.

    Sources in priority order:
      1. yf.Ticker(t).calendar["Earnings Date"] - most reliable
      2. info.get("earningsTimestampStart")
      3. info.get("earningsTimestampEnd")
      4. info.get("earningsTimestamp") - legacy, least reliable

    Rules:
    - Discard dates >365d out or <-7d (stale)
    - Multiple future dates: take EARLIEST (most conservative)
    - CONFLICT if sources disagree by >7 days

    Returns:
      {ticker, next_date (str or None), days_to_earnings (int or None),
       source (str), conflict (bool), eps_estimate (float or None),
       time_of_day (str or None), disqualifier (bool),
       urgency: "TODAY"/"URGENT"/"DISQUALIFIER"/"WATCH"/"OK"/"UNKNOWN"}

    urgency logic:
    - days == 0: TODAY
    - days <= 3: URGENT
    - days <= 15: DISQUALIFIER  (no new shares rule)
    - days <= 30: WATCH
    - else: OK
    """
    result: dict = {
        "ticker": ticker,
        "next_date": None,
        "days_to_earnings": None,
        "source": "none",
        "conflict": False,
        "eps_estimate": None,
        "time_of_day": None,
        "disqualifier": False,
        "urgency": "UNKNOWN",
    }

    today = datetime.now(timezone.utc).date()
    candidates: list[tuple[int, str]] = []  # (days, source_label)

    def _add(d, src: str):
        if d is None:
            return
        try:
            if hasattr(d, "date"):
                d = d.date()
            days = (d - today).days
            if -7 <= days <= 365:
                candidates.append((days, src, d))
        except Exception:
            pass

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        result["source"] = f"error:{e}"
        return result

    # Source 1: calendar["Earnings Date"]
    try:
        cal = t.calendar
        if cal and "Earnings Date" in cal:
            ed = cal["Earnings Date"]
            if isinstance(ed, list):
                for d in ed:
                    _add(d, "calendar")
            else:
                _add(ed, "calendar")
    except Exception:
        pass

    # Source 2: earningsTimestampStart
    try:
        ts_start = info.get("earningsTimestampStart")
        if ts_start:
            _add(datetime.fromtimestamp(ts_start, tz=timezone.utc), "ts_start")
    except Exception:
        pass

    # Source 3: earningsTimestampEnd
    try:
        ts_end = info.get("earningsTimestampEnd")
        if ts_end:
            _add(datetime.fromtimestamp(ts_end, tz=timezone.utc), "ts_end")
    except Exception:
        pass

    # Source 4: earningsTimestamp (legacy)
    try:
        ts = info.get("earningsTimestamp")
        if ts:
            _add(datetime.fromtimestamp(ts, tz=timezone.utc), "ts_legacy")
    except Exception:
        pass

    # EPS estimate
    try:
        eps = info.get("forwardEps") or info.get("trailingEps")
        if eps is not None:
            result["eps_estimate"] = float(eps)
    except Exception:
        pass

    # Time of day from earningsCallTimestamp or earningsCallTime
    try:
        call_ts = info.get("earningsCallTimestamp")
        if call_ts:
            call_dt = datetime.fromtimestamp(call_ts, tz=timezone.utc)
            hour = call_dt.hour
            if hour < 10:
                result["time_of_day"] = "BMO"
            elif hour >= 16:
                result["time_of_day"] = "AMC"
            else:
                result["time_of_day"] = "during"
    except Exception:
        pass

    if not candidates:
        result["source"] = "none"
        result["urgency"] = "UNKNOWN"
        return result

    # Prefer future dates (days >= 0)
    future = [(d, s, dt) for d, s, dt in candidates if d >= 0]
    pool = future if future else candidates

    # Conservative: earliest first
    pool.sort(key=lambda x: x[0])
    days, src, best_date = pool[0]

    # Conflict check: if range of sources > 7 days
    conflict = False
    if len(pool) > 1 and (pool[-1][0] - pool[0][0]) > 7:
        conflict = True
        src = f"{src}[CONFLICT:{pool[-1][0]-pool[0][0]}d gap]"

    result["days_to_earnings"] = days
    result["next_date"] = str(best_date)
    result["source"] = src
    result["conflict"] = conflict

    # Urgency classification
    if days == 0:
        urgency = "TODAY"
    elif days <= 3:
        urgency = "URGENT"
    elif days <= 15:
        urgency = "DISQUALIFIER"
    elif days <= 30:
        urgency = "WATCH"
    else:
        urgency = "OK"

    result["urgency"] = urgency
    result["disqualifier"] = urgency in ("TODAY", "URGENT", "DISQUALIFIER")

    return result


def get_portfolio_earnings(positions_file: Path = BASE / "positions.json") -> dict[str, dict]:
    """Returns {ticker: earnings_info} for all positions in positions.json."""
    data = json.loads(positions_file.read_text(encoding="utf-8"))
    tickers = []
    for acct in data["accounts"].values():
        for p in acct.get("positions", []):
            tickers.append(p["ticker"])

    return {t: get_earnings_info(t) for t in tickers}


def print_earnings_calendar(earn_data: dict) -> None:
    """Rich terminal output, color coded by urgency. Always prints ALL tickers."""

    URGENCY_STYLE = {
        "TODAY":        ("bold red", "TODAY"),
        "URGENT":       ("bold red", "URGENT"),
        "DISQUALIFIER": ("bold yellow", "DISQUALIFIER"),
        "WATCH":        ("yellow", "WATCH"),
        "OK":           ("green", "OK"),
        "UNKNOWN":      ("dim", "UNKNOWN"),
    }

    table = Table(
        title="[bold]Earnings Calendar[/bold]",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        header_style="bold cyan",
        title_justify="left",
    )

    table.add_column("Ticker",   style="bold white",  width=8)
    table.add_column("Urgency",  width=14)
    table.add_column("Date",     width=12)
    table.add_column("Days",     justify="right", width=6)
    table.add_column("Time",     width=7)
    table.add_column("EPS Est.", justify="right", width=9)
    table.add_column("Source",   style="dim",     width=32)
    table.add_column("Conflict", width=9)

    # Sort: TODAY first, then URGENT, DISQUALIFIER, WATCH, OK, UNKNOWN
    order = {"TODAY": 0, "URGENT": 1, "DISQUALIFIER": 2, "WATCH": 3, "OK": 4, "UNKNOWN": 5}
    sorted_items = sorted(
        earn_data.items(),
        key=lambda kv: (
            order.get(kv[1].get("urgency", "UNKNOWN"), 5),
            kv[1].get("days_to_earnings") if kv[1].get("days_to_earnings") is not None else 9999,
        ),
    )

    for ticker, info in sorted_items:
        urgency = info.get("urgency", "UNKNOWN")
        style, label = URGENCY_STYLE.get(urgency, ("dim", urgency))

        days = info.get("days_to_earnings")
        days_str = str(days) if days is not None else "-"

        date_str = info.get("next_date") or "-"
        time_str = info.get("time_of_day") or "-"
        eps = info.get("eps_estimate")
        eps_str = f"{eps:.2f}" if eps is not None else "-"
        src = info.get("source") or "none"
        conflict_str = "[bold red]YES[/bold red]" if info.get("conflict") else "no"

        table.add_row(
            ticker,
            f"[{style}]{label}[/{style}]",
            date_str,
            f"[{style}]{days_str}[/{style}]",
            time_str,
            eps_str,
            src,
            conflict_str,
        )

    console.print()
    console.print(table)

    # Summary line
    today_count = sum(1 for v in earn_data.values() if v.get("urgency") == "TODAY")
    urgent_count = sum(1 for v in earn_data.values() if v.get("urgency") == "URGENT")
    disq_count = sum(1 for v in earn_data.values() if v.get("urgency") == "DISQUALIFIER")
    watch_count = sum(1 for v in earn_data.values() if v.get("urgency") == "WATCH")
    unknown_count = sum(1 for v in earn_data.values() if v.get("urgency") == "UNKNOWN")

    parts = []
    if today_count:
        parts.append(f"[bold red]{today_count} TODAY[/bold red]")
    if urgent_count:
        parts.append(f"[bold red]{urgent_count} URGENT[/bold red]")
    if disq_count:
        parts.append(f"[bold yellow]{disq_count} DISQUALIFIER[/bold yellow]")
    if watch_count:
        parts.append(f"[yellow]{watch_count} WATCH[/yellow]")
    if unknown_count:
        parts.append(f"[dim]{unknown_count} UNKNOWN[/dim]")

    console.print("  Summary: " + ("  |  ".join(parts) if parts else "[green]All clear[/green]"))
    console.print()


if __name__ == "__main__":
    data = json.loads((BASE / "positions.json").read_text(encoding="utf-8"))
    tickers = []
    for acct in data["accounts"].values():
        for p in acct.get("positions", []):
            tickers.append(p["ticker"])

    console.print(f"[dim]Fetching earnings for {len(tickers)} tickers…[/dim]")
    earn_data = {t: get_earnings_info(t) for t in tickers}
    print_earnings_calendar(earn_data)
