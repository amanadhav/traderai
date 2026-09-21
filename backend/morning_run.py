"""
Morning trading briefing - run every day before market decisions.
Usage: python morning_run.py
"""

from __future__ import annotations
import json
import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime, date as _date, timezone, timedelta
from pathlib import Path
from typing import Optional

# Hard cap: every network call (yfinance, requests) dies after 12s
# Prevents any single API call from hanging the briefing indefinitely
socket.setdefaulttimeout(12)

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

# ── Setup ──────────────────────────────────────────────────────────────────

# Path constants live in persistence.py (canonical home - file I/O module).
# Re-exported here for backward compat with older imports of these names.
from persistence import (
    BASE, POSITIONS_FILE, DAILY_BRIEF_FILE, HISTORY_FILE, TRADES_FILE,
    _load_data as _persistence_load_data,
    _save_data as _persistence_save_data,
    record_portfolio_snapshot as _persistence_record_snapshot,
    log_trade as _persistence_log_trade,
    write_daily_brief as _persistence_write_daily_brief,
)
TRACKER_FILE = BASE / "tracker.html"
console = Console(record=True)  # record=True → full output saved to morning_run_log.txt at end of run()


# ── Persistence wrappers (auto-pass console; logic lives in persistence.py) ──

def _load_data() -> dict:
    return _persistence_load_data()

def _save_data(data: dict) -> None:
    return _persistence_save_data(data, console=console)

def write_daily_brief(data, snapshots, market_snaps, probable_fills,
                      action_items, insider_signals=None, options_flows=None):
    return _persistence_write_daily_brief(
        data, snapshots, market_snaps, probable_fills, action_items,
        insider_signals=insider_signals, options_flows=options_flows,
        console=console,
    )

def record_portfolio_snapshot(data, snapshots):
    return _persistence_record_snapshot(data, snapshots)

def log_trade(account, ticker, shares, avg_cost, sell_price, entry_date=None):
    return _persistence_log_trade(account, ticker, shares, avg_cost, sell_price, entry_date)


COMPANY_NAMES = {
    "BJ": "BJ's Wholesale", "CRM": "Salesforce", "EPD": "Enterprise Products",
    "GLD": "SPDR Gold", "MDT": "Medtronic", "MP": "MP Materials",
    "NKE": "Nike", "NOC": "Northrop Grumman", "RTX": "Raytheon",
    "AAPL": "Apple", "AMD": "Advanced Micro", "AMZN": "Amazon",
    "ASML": "ASML Holding", "BBAI": "BigBear AI", "GOOGL": "Alphabet",
    "HII": "Huntington Ingalls",
    "META": "Meta Platforms", "MSFT": "Microsoft", "NFLX": "Netflix",
    "NVDA": "NVIDIA", "NVO": "Novo Nordisk", "TSM": "TSMC",
    # Watchlist candidates
    "DHR": "Danaher", "ABT": "Abbott Labs", "SYK": "Stryker", "LDOS": "Leidos",
}

ETF_WATCHLIST = ["ITA", "DFEN", "GLD", "XLE", "REMX", "ARKQ", "BOTZ", "NUCL", "LIT", "SMH", "SOXX", "ARKG"]


# ── Data fetching (moved to data_fetch.py - re-exported for back-compat) ────

from data_fetch import (
    load_env, market_status,
    get_rsi, get_macd_hist, get_bb_pct,
    _get_days_to_earnings,
    get_full_snapshot,
    get_ticker_news, get_macro_news, MACRO_QUERIES,
    get_market_indicators,
    get_dividend_info,
    MST_OFFSET, MARKET_OPEN_MST, MARKET_CLOSE_MST,
    NEWSAPI_KEY,
)


# ── Position state (moved to positions.py - re-exported for back-compat) ────

from positions import (
    load_positions, all_tickers, all_pending_orders,
    calc_pnl, check_gtc_proximity, check_probable_fills,
    _find_position,
)


# ── Alerts (moved to alerts_check.py - wrappers auto-pass console + save_fn) ─

from alerts_check import (
    detect_order_fills as _ac_detect_order_fills,
    check_watchlist_entries,
    print_probable_fills_terminal as _ac_print_probable_fills,
    print_watchlist_terminal as _ac_print_watchlist,
    print_lead_indicators_terminal as _ac_print_lead_indicators,
    LEAD_INDICATOR_SIGNALS,
)

def detect_order_fills(data, snapshots):
    return _ac_detect_order_fills(data, snapshots, save_data_fn=_save_data)

def print_probable_fills_terminal(alerts):
    return _ac_print_probable_fills(alerts, console=console)

def print_watchlist_terminal(results):
    return _ac_print_watchlist(results, console=console)

def print_lead_indicators_terminal(data, snapshots):
    return _ac_print_lead_indicators(data, snapshots, console=console)


# ── Terminal renderers (moved to terminal_ui.py - auto-pass console) ────────

from terminal_ui import (
    _gamma_walls_str,
    print_header               as _ui_print_header,
    print_positions_table      as _ui_print_positions_table,
    print_market_indicators    as _ui_print_market_indicators,
    print_news_section         as _ui_print_news_section,
    print_patterns_section     as _ui_print_patterns_section,
    print_alerts               as _ui_print_alerts,
    print_action_items_terminal as _ui_print_action_items,
)

def print_header(market_open, status_str, today):
    return _ui_print_header(market_open, status_str, today, console=console)

def print_positions_table(positions, snapshots, title, show_stop=True, options_flows=None):
    return _ui_print_positions_table(positions, snapshots, title,
                                     show_stop=show_stop, options_flows=options_flows,
                                     console=console)

def print_market_indicators(market_snaps):
    return _ui_print_market_indicators(market_snaps, console=console)

def print_news_section(ticker_news, macro_news):
    return _ui_print_news_section(ticker_news, macro_news, console=console)

def print_patterns_section(pattern_results, snapshots=None):
    return _ui_print_patterns_section(pattern_results, snapshots, console=console)

def print_alerts(alerts):
    return _ui_print_alerts(alerts, console=console)

def print_action_items_terminal(items):
    return _ui_print_action_items(items, console=console)


# ── HTML dashboard (moved to html_render.py - re-exported for back-compat) ──

from html_render import (
    POSITION_MACRO,
    generate_daily_read,
    render_daily_read_html,
    generate_html,
    _build_html,
)


# ── Main ───────────────────────────────────────────────────────────────────

def run():
    today = datetime.now().strftime("%Y-%m-%d")
    console.print()

    # 1. Market hours
    market_open, status_str = market_status()
    print_header(market_open, status_str, today)

    if not market_open:
        console.print("\n[yellow]Market closed. Running in planning mode - live prices may reflect prior close.[/]\n")

    # 2. Load positions
    console.print("[dim]Loading positions...[/]")
    data = load_positions()
    tickers = all_tickers(data)
    orders = all_pending_orders(data)

    # 3. Fetch live data - parallel with per-ticker timeout
    console.print(f"[dim]Fetching data for {len(tickers)} tickers + SPY/QQQ/VIX (parallel)...[/]")
    snapshots: dict[str, dict] = {}
    TICKER_TIMEOUT = 20  # seconds per ticker before giving up
    with ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {pool.submit(get_full_snapshot, t): t for t in tickers}
        for future in as_completed(future_map, timeout=TICKER_TIMEOUT * len(tickers)):
            t = future_map[future]
            try:
                snap = future.result(timeout=TICKER_TIMEOUT)
            except FuturesTimeout:
                snap = {"ticker": t, "error": "timeout"}
            except Exception as e:
                snap = {"ticker": t, "error": str(e)}
            snapshots[t] = snap
            status = "✓" if not snap.get("error") else f"✗ {snap.get('error','?')}"
            console.print(f"[dim]  {t}[/] {status}")

    # 4. Market indicators
    console.print("[dim]Fetching SPY/QQQ/VIX...[/]")
    market_snaps = get_market_indicators()
    vix_price = (market_snaps.get("^VIX") or {}).get("price") or 15

    # 4b. Auto-detect order fills from intraday OHLC
    auto_fills = detect_order_fills(data, snapshots)
    if auto_fills:
        console.rule("[bold green]🎯 AUTO-FILLS DETECTED[/]")
        for msg in auto_fills:
            console.print(f"  [bold green]{msg}[/]")
        console.print("[yellow]  ⚠️  Verify fills in Fidelity - positions.json auto-updated.[/]\n")

    # 5. Pattern analysis
    console.print("[dim]Running pattern detection...[/]")
    import patterns as pat
    pattern_results: dict[str, dict] = {}
    for t, snap in snapshots.items():
        if snap.get("error") or snap.get("prices") is None:
            continue
        prices = snap["prices"]
        rsi_s = snap.get("rsi_series")
        pr = pat.detect(prices, rsi_series=rsi_s)
        pattern_results[t] = pr

    # 5b. Enrich snapshots with data_client - parallel, capped at 30s total
    def _enrich_one(t: str) -> tuple[str, dict]:
        snap = snapshots.get(t, {})
        if snap.get("error"):
            return t, {}
        enriched: dict = {}
        try:
            import data_client as dc
            dc_status = dc.status()
            has_finnhub = dc_status["Finnhub"]["key"]
            has_twelve  = dc_status["TwelveData"]["key"]
            if has_finnhub or has_twelve:
                ind = dc.get_indicators(t)
                if ind.get("provider") not in (None, "yfinance", "none"):
                    for k in ("rsi", "macd_hist", "macd_prev", "bb_pct", "stoch_k", "stoch_d", "adx", "atr"):
                        if ind.get(k) is not None:
                            enriched[k] = ind[k]
                    enriched["indicator_provider"] = ind["provider"]
                sr = dc.get_support_resistance(t)
                enriched["support"]    = sr.get("support", [])
                enriched["resistance"] = sr.get("resistance", [])
                enriched["sr_provider"] = sr.get("provider")
                if has_finnhub:
                    enriched["candlestick_patterns"] = dc.get_candlestick_patterns(t)
                    enriched["insider"] = dc.get_insider_activity(t)
        except Exception:
            pass
        return t, enriched

    try:
        console.print("[dim]Enriching with external data providers (parallel, 30s cap)...[/]")
        with ThreadPoolExecutor(max_workers=6) as pool:
            enrich_futures = {pool.submit(_enrich_one, t): t for t in tickers if not snapshots.get(t, {}).get("error")}
            for f in as_completed(enrich_futures, timeout=30):
                try:
                    t, enriched = f.result(timeout=5)
                    snapshots[t].update(enriched)
                except Exception:
                    pass
    except Exception:
        pass  # enrichment failure never blocks briefing

    # 6. News - parallel, 25s cap
    console.print("[dim]Fetching news (parallel, 25s cap)...[/]")
    ticker_news: dict[str, list] = {}
    big_movers: list[str] = []

    def _fetch_news_one(t: str) -> tuple[str, list]:
        try:
            import data_client as dc
            if dc.status()["Finnhub"]["key"] and not dc.status()["Finnhub"]["exhausted"]:
                articles = dc.get_news_sentiment(t, limit=5)
                # Only use if we got real headlines (Finnhub can return blank on 401)
                if articles and any(a.get("headline") or a.get("title") for a in articles):
                    return t, articles
        except Exception:
            pass
        # Fallback: yfinance news (always works, no API key)
        return t, get_ticker_news(t)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            news_futures = {pool.submit(_fetch_news_one, t): t for t in tickers}
            for f in as_completed(news_futures, timeout=25):
                try:
                    t, articles = f.result(timeout=5)
                    ticker_news[t] = articles
                except Exception:
                    t = news_futures[f]
                    ticker_news[t] = []
    except Exception:
        for t in tickers:
            if t not in ticker_news:
                ticker_news[t] = []

    for t in tickers:
        pct = (snapshots.get(t) or {}).get("pct_chg_today") or 0
        if abs(pct) >= 2:
            big_movers.append(f"{t} {'+' if pct >= 0 else ''}{pct:.2f}%")
    # Explain big movers with news context (runs after ticker_news is populated)
    # Will be re-evaluated below once ticker_news is filled

    macro_results: dict[str, list] = {}
    # Try Finnhub real-time first (no 24h delay) - fall back to NewsAPI
    try:
        import news_engine as ne
        import requests, os
        fh_key = os.environ.get("FINNHUB_KEY")
        if fh_key:
            r = requests.get("https://finnhub.io/api/v1/news",
                             params={"category": "general", "token": fh_key}, timeout=10)
            if r.status_code == 200:
                fh_articles = r.json()
                from datetime import datetime as _dt, timezone as _tz
                # Bucket by macro keyword
                for theme_emoji, keywords in ne.MACRO_KEYWORDS.items():
                    matches = []
                    for a in fh_articles:
                        title_low = a.get("headline", "").lower()
                        if any(kw in title_low for kw in keywords):
                            matches.append({
                                "title":  a.get("headline", ""),
                                "source": a.get("source", ""),
                                "url":    a.get("url", ""),
                                "publishedAt": _dt.fromtimestamp(a.get("datetime", 0), tz=_tz.utc).isoformat() if a.get("datetime") else None,
                            })
                    if matches:
                        # strip emoji prefix to match old MACRO_QUERIES keys roughly
                        macro_results[theme_emoji] = matches[:5]
    except Exception as _e:
        pass

    # Fall back to NewsAPI for any themes still empty
    if NEWSAPI_KEY and NEWSAPI_KEY != "your_key_here":
        for narrative, query in MACRO_QUERIES.items():
            if narrative not in macro_results:
                macro_results[narrative] = get_macro_news(query, NEWSAPI_KEY)

    # 7. GTC proximity alerts
    gtc_alerts = check_gtc_proximity(orders, snapshots)

    # 7b. Probable fill detection - check yesterday's OHLC vs all open orders
    probable_fills = check_probable_fills(data, snapshots)

    # 8. Earnings alerts
    earn_alerts: list[str] = []
    for t, snap in snapshots.items():
        dte = snap.get("days_to_earnings")
        if dte is None:
            continue
        if 0 <= dte <= 3:
            earn_alerts.append(f"🚨 {t} EARNINGS IN {dte} DAYS - URGENT")
        elif 0 <= dte <= 15:
            earn_alerts.append(f"⚠️  {t} earnings in {dte} days (disqualifier for new entry)")

    # 9. Dividend info
    div_info: dict[str, dict] = {}
    for t in tickers:
        div_info[t] = get_dividend_info(t)

    # 9b. Insider buying signals - 24hr cache, never blocks run
    insider_signals: dict[str, dict] = {}
    try:
        console.print("[dim]Checking insider buying signals (cached)...[/]")
        from insider import get_insider_signals
        insider_signals = get_insider_signals(tickers, force_refresh=False, verbose=False)
    except Exception as _ie:
        console.print(f"[dim yellow]  Insider fetch skipped: {_ie}[/]")

    # 9c. Options flow - 4hr cache, never blocks run
    options_flows: dict[str, dict] = {}
    try:
        console.print("[dim]Checking options flow (cached)...[/]")
        from options_flow import get_options_flows
        dte_map = {t: snapshots.get(t, {}).get("days_to_earnings") for t in tickers}
        options_flows = get_options_flows(tickers, force_refresh=False, verbose=False,
                                          dte_map=dte_map)
    except Exception as _oe:
        console.print(f"[dim yellow]  Options flow skipped: {_oe}[/]")

    # 10. Build action items
    fill_alerts = [f"🎯 AUTO-FILL: {f}" for f in auto_fills]
    probable_fill_alerts = [
        f"🟡 PROBABLE FILL - CHECK FIDELITY: {a['ticker']} {a['side'].upper()} {a['shares']}sh @${a['limit_price']:.2f} [{a['account']}] - {a['note']}"
        for a in probable_fills
    ]
    insider_alerts = [
        f"🔥 INSIDER BUY [{sig['signal']}] {ticker}: {sig['description']}"
        for ticker, sig in insider_signals.items()
        if sig.get("has_signal")
    ]
    options_alerts = [
        f"🚀 UNUSUAL CALLS {ticker}: {flow['note']}"
        for ticker, flow in options_flows.items()
        if flow.get("signal") == "UNUSUAL_CALLS"
    ]
    # Max pain drift alerts: price >4% from max pain AND expiry ≤3 days
    max_pain_alerts = [
        f"📌 MAX PAIN DRIFT {ticker}: {flow['max_pain_signal']} "
        f"(currently ${flow.get('price',0):.2f})"
        for ticker, flow in options_flows.items()
        if flow.get("max_pain")
        and flow.get("max_pain_days") is not None
        and flow["max_pain_days"] <= 3
        and flow.get("max_pain_dist_pct") is not None
        and abs(flow["max_pain_dist_pct"]) >= 4
    ]
    # Big mover alerts - enriched with news context via explain_big_mover
    try:
        from news_sentiment import explain_big_mover as _explain_mover
        from score import TICKER_NARRATIVES as _tn
        big_mover_alerts = []
        for t in tickers:
            pct = (snapshots.get(t) or {}).get("pct_chg_today") or 0
            if abs(pct) >= 2:
                narrs = _tn.get(t, [])
                explanation = _explain_mover(t, pct, ticker_news.get(t, []), narrs)
                big_mover_alerts.append(f"🔴 {explanation}")
    except Exception:
        big_mover_alerts = [f"🔴 BIG MOVER: {m}" for m in big_movers]

    all_alerts = probable_fill_alerts + fill_alerts + earn_alerts + gtc_alerts + insider_alerts + options_alerts + max_pain_alerts + big_mover_alerts
    action_items: list[str] = list(all_alerts)
    if not action_items:
        action_items = ["Monitor positions - no urgent actions today"]

    # 11. Macro narrative status (simple heuristic based on news availability)
    macro_status: dict[str, dict] = {}
    for narrative in MACRO_QUERIES:
        articles = macro_results.get(narrative, [])
        macro_status[narrative] = {
            "status": "green" if articles else "yellow",
            "note": articles[0]["title"] if articles else "No recent news (set NEWSAPI_KEY for macro feed)",
        }

    # 12. Generate action items v3 - full 5-signal synthesis engine
    action_recs = generate_action_items_v3(
        data, snapshots, pattern_results, market_snaps, div_info,
        insider_signals=insider_signals,
        options_flows=options_flows,
        ticker_news=ticker_news,
        macro_results=macro_results,
    )

    # ── Print terminal report ──────────────────────────────────────────────

    console.print()
    print_market_indicators(market_snaps)
    console.print()

    # ── PROBABLE FILLS - highest priority, check before anything else ────────
    print_probable_fills_terminal(probable_fills)

    # ── EARNINGS AUDIT - always print, always verify ───────────────────────
    # Shows every held ticker's earnings date + which source provided it.
    # CONFLICT flag means sources disagreed by >7 days - extra caution needed.
    console.rule("[bold yellow]📅 EARNINGS DATES - VERIFIED[/]")
    today_d = datetime.now(timezone.utc).date()
    has_near = False
    for t, snap in sorted(snapshots.items()):
        dte = snap.get("days_to_earnings")
        src = snap.get("earnings_date_src", "none")
        if dte is None:
            console.print(f"  [dim]{t:6}[/] [dim]no earnings date found (src: {src})[/]")
        else:
            earn_d = today_d + timedelta(days=dte)
            if "CONFLICT" in src:
                color = "bold red"
                flag = " ⚠️  SOURCE CONFLICT - verify manually in Fidelity/Earnings Whispers"
            elif dte <= 0:
                color = "bold red"; flag = " 🚨 EARNINGS TODAY - do NOT add shares"; has_near = True
            elif dte <= 3:
                color = "bold red"; flag = " 🚨 URGENT"; has_near = True
            elif dte <= 15:
                color = "bold yellow"; flag = " ⚠️  DISQUALIFIER - no new shares"; has_near = True
            else:
                color = "dim"; flag = ""
            console.print(f"  [{color}]{t:6}[/] [{color}]{earn_d} ({dte:+d}d) via {src}{flag}[/]")
    if not has_near:
        console.print("  [green]No earnings within 15 days - all clear[/]")
    console.print()

    # Print action items FIRST - this is what the user acts on
    print_action_items_terminal(action_recs)

    # ── LEAD INDICATORS - upcoming earnings signal checklist ─────────────────
    print_lead_indicators_terminal(data, snapshots)

    # ── WATCHLIST - entry conditions check ───────────────────────────────────
    # Fetch snapshots for watchlist tickers not yet loaded
    watchlist_tickers = [w["ticker"] for w in data.get("watchlist", []) if w.get("ticker") not in snapshots]
    if watchlist_tickers:
        console.print(f"[dim]Fetching watchlist data: {', '.join(watchlist_tickers)}...[/]")
        with ThreadPoolExecutor(max_workers=4) as pool:
            wl_futures = {pool.submit(get_full_snapshot, t): t for t in watchlist_tickers}
            for f in as_completed(wl_futures, timeout=20):
                t = wl_futures[f]
                try:
                    snapshots[t] = f.result()
                except Exception:
                    pass

    watchlist_results = check_watchlist_entries(data, snapshots, market_snaps)
    print_watchlist_terminal(watchlist_results)

    if all_alerts:
        console.rule("[bold red]⚡ ALERTS[/]")
        print_alerts(all_alerts)
        console.print()

    console.rule("[bold cyan]ROTH IRA[/]")
    print_positions_table(data["accounts"]["ROTH"]["positions"], snapshots,
                          "ROTH IRA", show_stop=True,
                          options_flows=options_flows)

    console.rule("[bold cyan]Individual TOD[/]")
    print_positions_table(data["accounts"]["TOD"]["positions"], snapshots,
                          "Individual TOD", show_stop=False,
                          options_flows=options_flows)

    print_patterns_section(pattern_results, snapshots)

    # ── INSIDER BUYING SIGNALS ────────────────────────────────────────────────
    if insider_signals:
        console.rule("[bold blue]🔍 INSIDER BUYING (SEC Form 4 - last 90 days)[/]")
        tier_icons = {"STRONG": "🔥", "CLUSTER": "⚡", "NOTABLE": "👀",
                      "WEAK": "〰", "NONE": "-", "ERROR": "❌"}
        actionable = {t: s for t, s in insider_signals.items() if s.get("has_signal")}
        passive    = {t: s for t, s in insider_signals.items() if not s.get("has_signal")}
        if actionable:
            for ticker, sig in actionable.items():
                icon = tier_icons.get(sig["signal"], "?")
                color = {"STRONG": "bold green", "CLUSTER": "bold yellow", "NOTABLE": "cyan"}.get(sig["signal"], "white")
                console.print(f"  [{color}]{icon} {ticker:6s} [{sig['signal']:8s}] {sig['description']}[/]")
        if passive:
            none_tickers = "  -  " + "  ".join(
                f"[dim]{t}[/]" for t, s in passive.items() if s["signal"] == "NONE"
            )
            console.print(none_tickers)
        console.print()

    # ── OPTIONS FLOW ──────────────────────────────────────────────────────────
    if options_flows:
        from options_flow import SIGNAL_ICONS, SIGNAL_COLORS, format_strikes
        console.rule("[bold blue]📊 OPTIONS FLOW (P/C ratio + gamma walls)[/]")
        console.print("  [dim]P/C vol < 0.7 = calls dominating | > 1.3 = puts dominating | "
                      "Gamma walls = dealer magnet strikes[/]")
        console.print()
        # Show all tickers sorted: actionable first
        priority = ["UNUSUAL_CALLS", "BULLISH_FLOW", "BEARISH_FLOW",
                    "MILD_BULLISH", "HEDGING", "NEUTRAL", "NO_OPTIONS", "NO_DATA", "ERROR"]
        sorted_flows = sorted(
            options_flows.items(),
            key=lambda x: priority.index(x[1].get("signal", "ERROR"))
            if x[1].get("signal", "ERROR") in priority else 99
        )
        for ticker, flow in sorted_flows:
            signal = flow.get("signal", "ERROR")
            icon = SIGNAL_ICONS.get(signal, "?")
            color = SIGNAL_COLORS.get(signal, "dim")
            pcr_v = flow.get("pcr_vol")
            pcr_o = flow.get("pcr_oi")
            atm_iv = flow.get("atm_iv")
            pcr_str = f"P/C {pcr_v:.2f}v/{pcr_o:.2f}oi" if pcr_v is not None else ""
            iv_str  = f"IV {atm_iv:.0f}%" if atm_iv else ""
            strikes_str = format_strikes(flow, max_show=3)
            console.print(
                f"  [{color}]{icon} {ticker:6s} [{signal:15s}] "
                f"{pcr_str}  {iv_str}[/]"
            )
            if strikes_str and signal in ("UNUSUAL_CALLS", "BULLISH_FLOW", "BEARISH_FLOW"):
                console.print(f"          [dim]↳ {strikes_str}[/]")
        console.print()

    console.print()
    print_news_section(ticker_news, macro_results)

    # ── TODAY'S CANDIDATES - from overnight scan ──────────────────────────────
    scan_file = BASE / "scan_results.json"
    watchlist_file = BASE / "watchlist.json"
    try:
        scan_data = json.loads(scan_file.read_text(encoding="utf-8"))
        scan_ts   = scan_data.get("scanned_at", "unknown")
        candidates = scan_data.get("candidates", [])
        # Filter out tickers already in positions
        held = {p["ticker"] for acct in data["accounts"].values() for p in acct.get("positions", [])}
        candidates = [c for c in candidates if c["ticker"] not in held]
        strong_cands = [c for c in candidates if c.get("score", 0) >= 75 and not c.get("disqualified")]
        other_cands  = [c for c in candidates if 55 <= c.get("score", 0) < 75 and not c.get("disqualified")]

        console.rule("[bold magenta]🔍 TODAY'S SCAN CANDIDATES[/]")
        console.print(f"[dim]  Scan ran: {scan_ts} | Universe: {scan_data.get('universe_size','?')} tickers | Found: {len(candidates)} candidates[/]")
        if scan_data.get("watchlist_added"):
            console.print(f"[green]  ✅ Auto-added to watchlist: {', '.join(scan_data['watchlist_added'])}[/]")
        if scan_data.get("watchlist_removed"):
            console.print(f"[dim]  🗑️  Removed from watchlist: {', '.join(scan_data['watchlist_removed'])}[/]")
        console.print()

        if strong_cands:
            console.print("[bold green]  🟢 STRONG SIGNALS[/]")
            for c in strong_cands[:8]:
                dte_str = f" | earn {c['days_to_earnings']}d" if c.get("days_to_earnings") is not None else ""
                pct_str = f" {c['pct_chg_today']:+.1f}%" if c.get("pct_chg_today") is not None else ""
                console.print(f"  [bold green]{c['ticker']:6}[/] [{c['score']:3}] ${c['price']:<8.2f} RSI {c['rsi']:<5.1f} BB {c['bb_pct']:<5.1f}{pct_str}{dte_str}  {c['sector_label']}")
                for sig in c.get("signals", [])[:2]:
                    console.print(f"[dim]           → {sig}[/]")

        if other_cands:
            console.print("[bold yellow]  🟡 WATCH LIST CANDIDATES[/]")
            for c in other_cands[:10]:
                dte_str = f" | earn {c['days_to_earnings']}d" if c.get("days_to_earnings") is not None else ""
                pct_str = f" {c['pct_chg_today']:+.1f}%" if c.get("pct_chg_today") is not None else ""
                console.print(f"  [yellow]{c['ticker']:6}[/] [{c['score']:3}] ${c['price']:<8.2f} RSI {c['rsi']:<5.1f} BB {c['bb_pct']:<5.1f}{pct_str}{dte_str}  {c['sector_label']}")
                for sig in c.get("signals", [])[:1]:
                    console.print(f"[dim]           → {sig}[/]")

        if not strong_cands and not other_cands:
            console.print("[dim]  No candidates today - market may be overbought or scan not yet run.[/]")
            console.print(f"[dim]  Run manually: python3 scan_universe.py[/]")

    except FileNotFoundError:
        console.rule("[bold magenta]🔍 TODAY'S SCAN CANDIDATES[/]")
        console.print("[dim]  scan_results.json not found - scan hasn't run yet.[/]")
        console.print("[dim]  Runs automatically at 8:30 AM MST. Run manually: python3 scan_universe.py --quick[/]")
    except Exception as _se:
        pass

    # ── Dynamic watchlist ─────────────────────────────────────────────────────
    try:
        wl_data = json.loads(watchlist_file.read_text(encoding="utf-8"))
        if wl_data:
            console.rule("[bold magenta]📋 LIVE WATCHLIST[/]")
            for t, info in wl_data.items():
                days = info.get("days_on_list", 1)
                score = info.get("score", 0)
                sigs = " · ".join(info.get("signals", [])[:2])
                console.print(f"  [bold]{t:6}[/] score={score:3} | {info.get('sector','?')} | {days}d on list")
                if sigs:
                    console.print(f"[dim]           {sigs}[/]")
    except Exception:
        pass

    # Dividend calendar
    upcoming_divs = {t: d for t, d in div_info.items() if d.get("ex_date") or d.get("div_date")}
    if upcoming_divs:
        console.rule("[bold cyan]DIVIDEND CALENDAR[/]")
        for t, d in upcoming_divs.items():
            console.print(f"  [bold]{t}[/]  ex-date: {d.get('ex_date','?')}  pay: {d.get('div_date','?')}  yield: {d.get('div_yield')}%  annual: ${d.get('annual_div',0):.2f}/sh")

    # Earnings calendar
    console.rule("[bold cyan]EARNINGS CALENDAR[/]")
    for t, snap in snapshots.items():
        dte = snap.get("days_to_earnings")
        if dte is not None and 0 <= dte <= 45:
            flag = "🚨 URGENT" if dte <= 3 else ("⚠️  DISQUALIFIER" if dte <= 15 else "")
            console.print(f"  [bold]{t}[/]  {dte} days  {flag}")

    # Fetch ETF snapshots - parallel, 20s cap
    console.print("[dim]Fetching ETF watchlist data (parallel)...[/]")
    etf_snapshots: dict[str, dict] = {}
    etfs_to_fetch = [e for e in ETF_WATCHLIST if e not in snapshots]
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            etf_futures = {pool.submit(get_full_snapshot, e): e for e in etfs_to_fetch}
            for f in as_completed(etf_futures, timeout=20):
                e = etf_futures[f]
                try:
                    etf_snapshots[e] = f.result(timeout=5)
                except Exception:
                    etf_snapshots[e] = {"ticker": e, "error": "timeout"}
    except Exception:
        for e in etfs_to_fetch:
            if e not in etf_snapshots:
                etf_snapshots[e] = {"ticker": e, "error": "timeout"}

    # ── Generate HTML ──────────────────────────────────────────────────────
    console.print("\n[dim]Generating tracker.html...[/]")
    html = generate_html(
        data=data,
        snapshots=snapshots,
        market_open=market_open,
        market_status_str=status_str,
        alerts=all_alerts,
        action_items=action_items,
        macro_status=macro_status,
        div_info=div_info,
        today=today,
        ticker_news=ticker_news,
        pattern_results=pattern_results,
        etf_snapshots=etf_snapshots,
        market_snaps=market_snaps,
        insider_signals=insider_signals,
        options_flows=options_flows,
        macro_results=macro_results,
    )
    TRACKER_FILE.write_text(html, encoding="utf-8")
    TRACKER_FILE.chmod(0o600)  # owner-only - contains real position data
    console.print(f"[green]✅ tracker.html written[/]")

    # Record daily snapshot for equity curve
    record_portfolio_snapshot(data, snapshots)

    # ── Append every computed signal to the SQLite history (data/signals.db) ──
    # Additive log: queries + future ML training data. JSON stays source of truth.
    try:
        import guardian as _guardian
        import signal_store as _signal_store
        _violations = _guardian.check_all(
            data, {t: {"price": (s or {}).get("price")} for t, s in snapshots.items()})
        n_rows = _signal_store.record_day(
            snapshots, insider_signals=insider_signals,
            options_flows=options_flows, guardian_violations=_violations)
        console.print(f"[dim]signal_store: {n_rows} ticker rows + "
                      f"{len(_violations)} guardian entries recorded[/]")
        if _violations:
            console.print("[bold yellow]⚖️  DISCIPLINE GUARDIAN[/]")
            for v in _violations:
                color = "red" if v["severity"] == "URGENT" else "yellow"
                console.print(f"  [{color}]{v['severity']}[/] {v['message']}")
    except Exception as e:
        console.print(f"[yellow]signal_store skipped: {type(e).__name__}: {e}[/]")

    # ── Write daily_brief.json - context anchor ───────────────────────────────
    # This file is the STATELESS ANCHOR. Claude re-reads it any time context
    # is uncertain, session is long, or /anchor is called. It contains every
    # critical fact that must never be forgotten regardless of conversation length.
    write_daily_brief(data, snapshots, market_snaps, probable_fills, action_recs,
                      insider_signals=insider_signals,
                      options_flows=options_flows)

    console.print(f"\n[bold green]Briefing complete - {today}[/]\n")

    # ── Save full terminal output to log file ──────────────────────────────
    # Claude MUST read this file instead of relying on truncated bash output.
    # Never estimate prices from memory - always read morning_run_log.txt or daily_brief.json.
    log_file = BASE / "morning_run_log.txt"
    try:
        console.save_text(str(log_file))
        log_file.chmod(0o600)
    except Exception as e:
        console.print(f"[yellow]⚠️  Could not save log file: {e}[/]")

    try:
        import webbrowser
        webbrowser.open(TRACKER_FILE.as_uri())
    except Exception:
        pass  # opening the tracker is a convenience, never fail the run

# ── CLI subcommands (moved to cli_commands.py - re-exported for back-compat) ─

from cli_commands import (
    cmd_buy, cmd_sell, cmd_stop, cmd_score, cmd_positions,
    cmd_scan, cmd_news, cmd_breadth, cmd_server, cmd_help,
)


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        run()
    else:
        cmd = args[0].lower()
        rest = args[1:]
        if cmd == "buy":
            cmd_buy(rest)
        elif cmd == "sell":
            cmd_sell(rest)
        elif cmd == "stop":
            cmd_stop(rest)
        elif cmd == "score":
            cmd_score(rest)
        elif cmd in ("positions", "pos"):
            cmd_positions(rest)
        elif cmd in ("server", "serve", "app"):
            cmd_server(rest)
        elif cmd in ("scan",):
            cmd_scan(rest)
        elif cmd in ("news",):
            cmd_news(rest)
        elif cmd in ("breadth",):
            cmd_breadth(rest)
        elif cmd in ("etf", "etf-score", "score-etf"):
            import subprocess as _sp
            _sp.run([sys.executable, str(Path(__file__).parent / "etf_score.py")] + list(rest))
        elif cmd in ("help", "--help", "-h"):
            cmd_help()
        else:
            console.print(f"[red]Unknown command: {cmd}[/]")
            cmd_help()
