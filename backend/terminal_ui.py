"""
terminal_ui.py - Rich terminal renderers (read-only output).

All print/format functions for the morning briefing's terminal section.
No business logic; pulls data from caller-supplied dicts and prints.

`console` is passed in as a kwarg so morning_run.py's recording Console
(record=True) captures output for morning_run_log.txt. Default: silent.

Functions:
  print_header                 - top banner with market state
  print_positions_table        - Rich Table for ROTH or TOD account
  print_market_indicators      - VIX / SPY / QQQ panel
  print_news_section           - ticker headlines + macro narratives
  print_patterns_section       - detected patterns + S/R + insider + stoch/ADX
  print_alerts                 - GTC proximity warnings
  print_action_items_terminal  - numbered action list (URGENT/ACTION/WATCH/INFO)

Helper:
  _gamma_walls_str             - compact gamma wall + max pain string
                                 (used by print_positions_table)
"""
from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich import box

from positions import calc_pnl


# ── Header ──────────────────────────────────────────────────────────────────

def print_header(market_open: bool, status_str: str, today: str, console=None):
    if console is None:
        return
    color = "green" if market_open else "yellow"
    console.print(Panel(
        f"[bold white]📊 MORNING BRIEFING - {today}[/]\n"
        f"[{color}]{'● MARKET OPEN' if market_open else '● MARKET CLOSED'} - {status_str}[/]",
        border_style="bright_blue",
        padding=(0, 2),
    ))


# ── Helper: compact gamma walls + max pain ──────────────────────────────────

def _gamma_walls_str(ticker: str, price: float, options_flows: dict) -> str:
    """
    Returns compact string: ↑$45 ↓$42 | MP$44(1d)
    - Nearest gamma wall above + below (dealer hedging magnets)
    - Max pain strike + days to expiry (institutional pin target)
    """
    flow = options_flows.get(ticker, {})
    strikes = flow.get("key_strikes", [])

    relevant = [s for s in strikes[:8] if abs(s["dist_pct"]) <= 20]
    above = [s for s in relevant if s["dist_pct"] > 0.5]
    below = [s for s in relevant if s["dist_pct"] < -0.5]
    near_above = min(above, key=lambda x: x["dist_pct"]) if above else None
    near_below = max(below, key=lambda x: x["dist_pct"]) if below else None

    parts = []
    if near_above:
        parts.append(f"[green]↑${near_above['strike']:.0f}[/]")
    if near_below:
        parts.append(f"[red]↓${near_below['strike']:.0f}[/]")

    mp = flow.get("max_pain")
    mp_days = flow.get("max_pain_days")
    mp_dist = flow.get("max_pain_dist_pct")
    if mp:
        day_str = f"{mp_days}d" if mp_days else "?"
        if mp_dist is not None and mp_dist > 1.5:
            mp_color = "green"
        elif mp_dist is not None and mp_dist < -1.5:
            mp_color = "red"
        else:
            mp_color = "dim"
        parts.append(f"[{mp_color}]MP${mp:.0f}({day_str})[/]")

    return " ".join(parts) if parts else "-"


# ── Positions table ─────────────────────────────────────────────────────────

def print_positions_table(positions: list, snapshots: dict, title: str,
                          show_stop: bool = True,
                          options_flows: dict | None = None,
                          console=None):
    if console is None:
        return
    table = Table(title=title, box=box.SIMPLE_HEAVY, border_style="bright_blue",
                  header_style="bold cyan")
    cols = ["Ticker", "Shares", "Avg $", "Price", "Day%", "P&L $", "P&L%", "RSI", "Walls", "Type"]
    if show_stop:
        cols.insert(-2, "Stop")
    for c in cols:
        table.add_column(c, no_wrap=True)

    for p in positions:
        t = p["ticker"]
        s = snapshots.get(t, {})
        price = s.get("price") or p["avg_cost"]
        pnl = calc_pnl(p, price)
        day_pct = s.get("pct_chg_today") or 0
        rsi = s.get("rsi")
        stop = p.get("stop")

        day_str = f"[green]+{day_pct:.2f}%[/]" if day_pct >= 0 else f"[red]{day_pct:.2f}%[/]"
        gain_str = f"[green]+${pnl['gain']:.2f}[/]" if pnl["gain"] >= 0 else f"[red]-${abs(pnl['gain']):.2f}[/]"
        pct_str = f"[green]+{pnl['gain_pct']:.2f}%[/]" if pnl["gain_pct"] >= 0 else f"[red]{pnl['gain_pct']:.2f}%[/]"
        rsi_str = f"{rsi:.1f}" if rsi else "-"
        if rsi:
            if rsi < 30:
                rsi_str = f"[green]{rsi:.1f}[/]"
            elif rsi > 70:
                rsi_str = f"[red]{rsi:.1f}[/]"
        stop_str = f"${stop:.2f}" if stop else "-"
        walls_str = _gamma_walls_str(t, price, options_flows or {})

        row = [t, str(p["shares"]), f"${p['avg_cost']:.2f}", f"${price:.2f}",
               day_str, gain_str, pct_str, rsi_str, walls_str, p["type"]]
        if show_stop:
            row.insert(-2, stop_str)
        table.add_row(*row)

    console.print(table)


# ── Market indicators ───────────────────────────────────────────────────────

def print_market_indicators(market_snaps: dict, console=None):
    if console is None:
        return
    vix_snap = market_snaps.get("^VIX", {})
    spy_snap = market_snaps.get("SPY", {})
    qqq_snap = market_snaps.get("QQQ", {})

    vix = vix_snap.get("price")
    spy_rsi = spy_snap.get("rsi")
    qqq_rsi = qqq_snap.get("rsi")

    lines = []
    if vix:
        if vix > 35:
            lines.append(f"[bold red]⚠️  VIX {vix:.1f} > 35 - REDUCE ALL POSITIONS 50%[/]")
        elif vix > 25:
            lines.append(f"[yellow]⚡ VIX {vix:.1f} > 25 - reduce sizing 25%[/]")
        else:
            lines.append(f"[green]✅ VIX {vix:.1f} - normal[/]")
    if spy_rsi:
        if spy_rsi > 75:
            lines.append(f"[red]⚠️  SPY RSI {spy_rsi:.1f} > 75 - no new lump sum entries[/]")
        elif spy_rsi < 35:
            lines.append(f"[green]🚀 SPY RSI {spy_rsi:.1f} < 35 - BUY AGGRESSIVELY[/]")
        else:
            lines.append(f"  SPY RSI {spy_rsi:.1f}")
    if qqq_rsi:
        if qqq_rsi > 75:
            lines.append(f"[red]⚠️  QQQ RSI {qqq_rsi:.1f} > 75[/]")
        elif qqq_rsi < 35:
            lines.append(f"[green]🚀 QQQ RSI {qqq_rsi:.1f} < 35 - aggressive buy zone[/]")
        else:
            lines.append(f"  QQQ RSI {qqq_rsi:.1f}")

    console.print(Panel("\n".join(lines) or "Market data unavailable",
                        title="[bold]Market Indicators[/]", border_style="cyan"))


# ── News ────────────────────────────────────────────────────────────────────

def print_news_section(ticker_news: dict, macro_news: dict, console=None):
    if console is None:
        return
    console.rule("[bold cyan]NEWS[/]")
    for ticker, articles in ticker_news.items():
        if articles:
            console.print(f"\n  [bold]{ticker}[/]")
            for a in articles[:3]:
                title = a.get('title') or a.get('headline') or str(a)[:120]
                console.print(f"    · {title}")

    if macro_news:
        console.print("\n  [bold]MACRO NARRATIVES[/]")
        for narrative, articles in macro_news.items():
            if articles:
                console.print(f"\n  [cyan]{narrative}[/]")
                for a in articles[:2]:
                    title = a.get('title') or a.get('headline') or str(a)[:120]
                    console.print(f"    · {title} [{a.get('source','')}]")


# ── Patterns + technicals + insider + stoch/ADX ─────────────────────────────

def print_patterns_section(pattern_results: dict, snapshots: dict | None = None, console=None):
    if console is None:
        return
    console.rule("[bold cyan]PATTERNS & TECHNICALS[/]")
    for ticker, pr in pattern_results.items():
        import patterns as pat
        summary = pat.summarize(pr, ticker)
        console.print(summary)

        snap = (snapshots or {}).get(ticker, {})

        # Support / resistance levels
        support    = snap.get("support", [])
        resistance = snap.get("resistance", [])
        sr_prov    = snap.get("sr_provider", "")
        if support or resistance:
            s_str = "  ".join([f"${v}" for v in support[:3]])    or "-"
            r_str = "  ".join([f"${v}" for v in resistance[:3]]) or "-"
            console.print(f"  [cyan]S/R ({sr_prov}):[/] support [{s_str}]  resistance [{r_str}]")

        # Candlestick patterns from Finnhub
        candles = snap.get("candlestick_patterns", [])
        for c in candles[:3]:
            sig = c.get("signal", "")
            color = "green" if "bull" in sig.lower() else "red" if "bear" in sig.lower() else "yellow"
            console.print(f"  [{color}]🕯 {c['pattern']} ({sig})[/]")

        # Insider activity
        insiders = snap.get("insider", [])
        buys  = [i for i in insiders if i.get("transaction", "").startswith("P")]
        sells = [i for i in insiders if i.get("transaction", "").startswith("S")]
        if buys:
            console.print(f"  [green]👤 Insider BUY: {buys[0]['name']} {buys[0]['shares']:,}sh @${buys[0]['price']} ({buys[0]['date']})[/]")
        if sells and not buys:
            console.print(f"  [red]👤 Insider SELL: {sells[0]['name']} {sells[0]['shares']:,}sh ({sells[0]['date']})[/]")

        # Stoch / ADX
        stoch_k = snap.get("stoch_k")
        adx     = snap.get("adx")
        extras  = []
        if stoch_k is not None:
            color = "green" if stoch_k < 20 else "red" if stoch_k > 80 else "dim"
            extras.append(f"[{color}]Stoch {stoch_k:.0f}[/]")
        if adx is not None:
            extras.append(f"ADX {adx:.0f}" + (" [bold](trending)[/]" if adx > 25 else ""))
        if extras:
            console.print("  " + "  ".join(extras))


# ── GTC alerts ──────────────────────────────────────────────────────────────

def print_alerts(alerts: list[str], console=None):
    if console is None:
        return
    if not alerts:
        console.print("[green]✅ No urgent GTC alerts[/]")
        return
    for a in alerts:
        console.print(f"[bold yellow]{a}[/]")


# ── Action items ────────────────────────────────────────────────────────────

def print_action_items_terminal(items: list[dict], console=None) -> None:
    if console is None:
        return
    prio_style = {"URGENT": "bold red", "ACTION": "bold green",
                  "WATCH": "bold yellow", "INFO": "blue"}
    console.rule("[bold white]📋 TODAY'S ACTION ITEMS[/]")
    if not items:
        console.print("  [dim]No urgent actions today.[/]")
        return
    for item in items:
        p     = item.get("priority", "INFO")
        style = prio_style.get(p, "white")
        num   = item.get("num", "")
        tick  = item.get("ticker", "")
        acct  = item.get("account", "")
        verb  = item.get("verb", "")
        det   = item.get("detail", "")
        sigs  = item.get("signals", "")
        console.print(f"  [{style}]{num:>2}. [{p}] {tick} ({acct})[/]  [bold]{verb}[/]")
        console.print(f"      [dim]{det}[/]")
        if sigs:
            console.print(f"      [dim cyan]↳ {sigs}[/]")
    console.print()
