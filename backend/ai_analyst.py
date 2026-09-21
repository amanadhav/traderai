"""
ai_analyst.py - AI analyst features built on ai_client.py.

1. generate_briefing() - full AI morning briefing (markdown) from the system's
   own data: daily_brief.json anchor, live market indicators, per-ticker news.
   Includes mandatory pre-earnings decision cards for anything reporting ≤3 days.
2. chat() - portfolio chat with tool use: the model answers questions by
   actually running the system (snapshots, scorer, news, options, insider).

Both degrade cleanly: without ANTHROPIC_API_KEY they report unavailability
instead of failing.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path

import ai_client
from ai_client import MODEL_SMART, complete, chat_with_tools, model_for

BASE = Path(__file__).resolve().parents[1]
BRIEFING_FILE = BASE / "ai_briefing.json"
DAILY_BRIEF_FILE = BASE / "daily_brief.json"
POSITIONS_FILE = BASE / "positions.json"


# ── Data gathering ───────────────────────────────────────────────────────────

def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _positions_summary() -> list[dict]:
    data = _load_json(POSITIONS_FILE) or {"accounts": {}}
    rows = []
    for acct_name, acct in data.get("accounts", {}).items():
        for p in acct.get("positions", []):
            rows.append({
                "ticker": p["ticker"], "account": acct_name,
                "shares": p["shares"], "avg_cost": p["avg_cost"],
                "stop": p.get("stop"), "type": p.get("type"),
                "thesis": p.get("thesis", ""),
                "pending_orders": p.get("pending_orders", []),
            })
    return rows


def _gather_snapshots(tickers: list[str]) -> dict[str, dict]:
    """Live price/RSI/day-change/earnings-proximity per ticker, fetched in parallel."""
    from data_fetch import get_full_snapshot
    out: dict[str, dict] = {}

    def fetch(t):
        try:
            snap = get_full_snapshot(t)
            return t, {
                "price": snap.get("price"),
                "day_change_pct": snap.get("pct_chg_today"),
                "rsi": snap.get("rsi"),
                "days_to_earnings": snap.get("days_to_earnings"),
                "pct_from_52w_low": snap.get("pct_from_52w_low"),
            }
        except Exception:
            return t, {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch, t) for t in tickers]
        for f in as_completed(futures, timeout=120):
            t, snap = f.result()
            out[t] = snap
    return out


def _gather_news(tickers: list[str], per_ticker: int = 5) -> dict[str, list[str]]:
    from data_fetch import get_ticker_news
    out: dict[str, list[str]] = {}

    def fetch(t):
        try:
            arts = get_ticker_news(t, max_items=per_ticker)
            return t, [a.get("title") or a.get("headline") or "" for a in arts if a]
        except Exception:
            return t, []

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch, t) for t in tickers]
        for f in as_completed(futures, timeout=60):
            t, heads = f.result()
            out[t] = heads
    return out


def _user_rules_block() -> str:
    """Render the user's configured accounts + rules for AI system prompts."""
    from user_config import get_config
    cfg = get_config()
    rules = cfg["rules"]
    policy_desc = {
        "active": "active trading - stops required, positions managed",
        "lifetime": "lifetime compounding - never sold on volatility, no stops",
        "income": "income - dividend focus, low turnover",
        "spec": "speculation sandbox - small sizes, strict exit discipline",
    }
    lines = ["THE USER'S ACCOUNTS:"]
    for a in cfg["accounts"]:
        limits = ", ".join(f"max {v} {k}" for k, v in (a.get("sector_limits") or {}).items())
        lines.append(f"- {a['name']}: {policy_desc.get(a['policy'], a['policy'])}"
                     + (f" (sector limits: {limits})" if limits else ""))
    lines += [
        "",
        "THE USER'S TRADING RULES (enforce these in every recommendation):",
        f"- Never add within {rules['earnings_blackout_days']} days of earnings",
        f"- Entry requires score >= {rules['score_entry_threshold']} "
        f"(strong >= {rules['score_strong_threshold']}, conviction >= {rules['score_conviction_threshold']})",
        f"- Max risk per trade: {rules['max_risk_per_trade_pct']}% of equity | "
        f"max portfolio heat: {rules['max_portfolio_heat_pct']}% | "
        f"max single position: {rules['max_position_pct']}%",
        f"- Max drawdown tolerance: {rules['max_drawdown_pct']}% from peak",
        f"- Default stop distance: {rules['default_stop_pct']}% ({rules['stop_style']})",
        f"- Averaging down: {rules['averaging_down'].replace('_', ' ')}",
    ]
    if rules.get("cash_floor_pct"):
        lines.append(f"- Keep at least {rules['cash_floor_pct']}% cash")
    profile = cfg.get("profile", {})
    if profile.get("risk_tolerance"):
        lines.append(f"- Risk tolerance: {profile['risk_tolerance']} | objective: {profile.get('objective', 'balanced')}")
    ai_cfg = cfg.get("ai", {})
    if ai_cfg.get("recommendation_style") == "suggestive":
        lines.append("- Style: present options with trade-offs; the user decides")
    else:
        lines.append("- Style: give ONE explicit recommendation, never leave the decision open")
    if ai_cfg.get("briefing_tone") == "detailed":
        lines.append("- Tone: thorough, explain reasoning in full")
    else:
        lines.append("- Tone: terse and concrete, no filler")
    if cfg.get("paper_mode"):
        lines.append("- NOTE: this is a PAPER (simulated) portfolio")
    return "\n".join(lines)


_BRIEFING_SYSTEM_CORE = """You are the AI analyst for TraderAI, a personal trading system.

{user_rules}

Write the daily morning briefing in clean GitHub markdown. Rules:
- NEVER invent prices, RSI, or P&L. Only use numbers present in the data. \
If a value is missing, write "data unavailable" for it.
- For EVERY position with earnings within 3 days: a mandatory decision card - \
bull case (2 sentences), bear case (2 sentences), the position's stated P&L, \
and an explicit recommendation (hold all / trim N shares / add on dip). \
Never leave the decision to the reader.
- Map macro themes to specific held tickers with GREEN/YELLOW/RED status.
- End with a numbered "Today's Decisions" list in order of urgency.
- Be concrete and terse. No filler, no disclaimers beyond one line noting \
this is analysis, not licensed financial advice.

Sections, in order: Urgent, Market, Macro Thesis Status, Position Notes \
(only positions where news or signals changed something), Today's Decisions."""


def _briefing_system() -> str:
    return _BRIEFING_SYSTEM_CORE.format(user_rules=_user_rules_block())


def generate_briefing(force: bool = False) -> dict:
    """Generate (or return today's cached) AI morning briefing."""
    if not ai_client.ai_available():
        return {"available": False, "reason": "ANTHROPIC_API_KEY not configured in .env"}

    cached = _load_json(BRIEFING_FILE)
    today = date.today().isoformat()
    if cached and cached.get("date") == today and not force:
        return {"available": True, **cached, "cached": True}

    positions = _positions_summary()
    tickers = sorted({p["ticker"] for p in positions})

    # Live market pulse
    market = {}
    try:
        from data_fetch import get_market_indicators
        snaps = get_market_indicators()
        market = {
            "vix": (snaps.get("^VIX") or {}).get("price"),
            "spy_rsi": (snaps.get("SPY") or {}).get("rsi"),
            "qqq_rsi": (snaps.get("QQQ") or {}).get("rsi"),
        }
    except Exception:
        pass

    daily_brief = _load_json(DAILY_BRIEF_FILE)
    brief_note = None
    if daily_brief:
        if daily_brief.get("date") != today:
            brief_note = f"daily_brief.json is from {daily_brief.get('date')} - prices/P&L in it are stale; rely on it for structure (earnings, stops, actions), not prices."
        # strip meta noise to keep the prompt tight
        for k in ("_instructions", "context_anchor", "hard_rules"):
            daily_brief.pop(k, None)

    news = _gather_news(tickers)
    snapshots = _gather_snapshots(tickers)

    # Live P&L per position so the model never has to estimate
    for p in positions:
        price = (snapshots.get(p["ticker"]) or {}).get("price")
        if price:
            p["live_price"] = price
            p["pl_dollar"] = round((price - p["avg_cost"]) * p["shares"], 2)
            p["pl_pct"] = round((price - p["avg_cost"]) / p["avg_cost"] * 100, 2)

    # Earnings-call excerpts for anything reporting within a week (max 2 -
    # keeps the prompt and cost bounded)
    call_excerpts = {}
    try:
        import transcripts
        near_earnings = sorted(
            [t for t, s in snapshots.items()
             if s.get("days_to_earnings") is not None and 0 <= s["days_to_earnings"] <= 7],
            key=lambda t: snapshots[t]["days_to_earnings"])[:2]
        for t in near_earnings:
            tx = transcripts.get_transcript_excerpt(t, max_chars=3500)
            if tx:
                call_excerpts[t] = {"quarter": f"Q{tx['quarter']} {tx['year']}",
                                    "excerpt": tx["excerpt"]}
    except Exception:
        pass

    payload = {
        "today": today,
        "market_live": market,
        "positions": positions,
        "live_snapshots": snapshots,
        "daily_brief": daily_brief,
        "daily_brief_note": brief_note,
        "headlines_by_ticker": news,
        "last_earnings_calls": call_excerpts or None,
    }
    prompt = (
        "Produce today's morning briefing from this data:\n\n"
        + json.dumps(payload, default=str)
    )

    md = complete(prompt, system=_briefing_system(), model=model_for("briefing"), max_tokens=4000)
    if md is None:
        return {"available": False, "reason": "AI call failed - check key/network"}

    result = {
        "date": today,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "model": model_for("briefing"),
        "markdown": md,
        "tickers_covered": tickers,
        "usage_today": ai_client.usage_today(),
    }
    try:
        BRIEFING_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"available": True, **result, "cached": False}


def latest_briefing() -> dict:
    cached = _load_json(BRIEFING_FILE)
    if not cached:
        return {"available": False, "reason": "No briefing generated yet"}
    return {"available": True, **cached, "cached": True}


# ── Portfolio chat with tool use ─────────────────────────────────────────────

_CHAT_SYSTEM_CORE = """You are the AI analyst inside TraderAI, a personal trading \
system. You answer questions about the user's actual portfolio by CALLING THE \
TOOLS - never from memory.

{user_rules}

Additional rules:
- Never state a price, RSI, score, or P&L you did not just get from a tool.
- Never recommend a buy without running the score tool on that ticker first.
- Never recommend selling a lifetime-policy account's position on volatility alone.
- End with one line noting this is analysis, not licensed financial advice.
- Be concise. Markdown for structure only where it helps."""


def _chat_system() -> str:
    return _CHAT_SYSTEM_CORE.format(user_rules=_user_rules_block())

CHAT_TOOLS = [
    {
        "name": "get_portfolio",
        "description": "Current positions in both accounts: shares, avg cost, stops, type, thesis, pending orders, and account cash.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_market",
        "description": "Live market pulse: VIX, SPY/QQQ price and RSI.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_snapshot",
        "description": "Live snapshot for a ticker: price, day change, RSI, MACD, Bollinger %, 52w range, fundamentals, earnings date.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Stock symbol, e.g. NVDA"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_score",
        "description": "Run the system's 180-point entry scoring algorithm on a ticker (auto-routes small caps to the 150-point spec scorer). Returns total, disqualifiers, factor breakdown.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_news",
        "description": "Latest news headlines for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_options_flow",
        "description": "Options flow for a ticker: put/call ratio, unusual call buying, max pain, gamma walls (uses 4hr cache).",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_insider",
        "description": "SEC Form 4 insider buying signal for a ticker (STRONG/CLUSTER/NOTABLE/WEAK/NONE, uses 24hr cache).",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
]


def _tool_get_portfolio():
    data = _load_json(POSITIONS_FILE) or {}
    cash = {name: acct.get("cash") for name, acct in data.get("accounts", {}).items()}
    return {"positions": _positions_summary(), "cash": cash,
            "watchlist": data.get("watchlist", [])}


def _tool_get_market():
    from data_fetch import get_market_indicators
    snaps = get_market_indicators()
    return {
        "vix": (snaps.get("^VIX") or {}).get("price"),
        "spy_price": (snaps.get("SPY") or {}).get("price"),
        "spy_rsi": (snaps.get("SPY") or {}).get("rsi"),
        "qqq_price": (snaps.get("QQQ") or {}).get("price"),
        "qqq_rsi": (snaps.get("QQQ") or {}).get("rsi"),
    }


def _clean_snapshot(snap: dict) -> dict:
    for k in ("prices", "rsi_series", "volume"):
        snap.pop(k, None)
    return snap


def _tool_get_snapshot(ticker: str):
    from data_fetch import get_full_snapshot
    return _clean_snapshot(get_full_snapshot(ticker.upper()))


def _tool_get_score(ticker: str):
    import patterns as pat_mod
    import score as sc
    from data_fetch import get_full_snapshot
    snap = get_full_snapshot(ticker.upper())
    prices = snap.pop("prices", None)
    rsi_s = snap.pop("rsi_series", None)
    snap.pop("volume", None)
    pat_res = pat_mod.detect(prices, rsi_series=rsi_s) if prices is not None else {}
    result = sc.score_ticker(snap, pattern_result=pat_res)
    return {
        "ticker": ticker.upper(), "score": result.total,
        "disqualified": result.disqualified, "disqualify_reason": result.disqualify_reason,
        "signal": result.signal, "breakdown": result.breakdown,
    }


def _tool_get_news(ticker: str):
    from data_fetch import get_ticker_news
    return {"ticker": ticker.upper(), "articles": get_ticker_news(ticker.upper(), max_items=8)}


def _tool_get_options_flow(ticker: str):
    from options_flow import get_options_flows
    flows = get_options_flows([ticker.upper()], verbose=False)
    return flows.get(ticker.upper(), {"note": "no options data"})


def _tool_get_insider(ticker: str):
    from insider import get_insider_signals
    sigs = get_insider_signals([ticker.upper()], verbose=False)
    return sigs.get(ticker.upper(), {"note": "no insider data"})


CHAT_HANDLERS = {
    "get_portfolio": _tool_get_portfolio,
    "get_market": _tool_get_market,
    "get_snapshot": _tool_get_snapshot,
    "get_score": _tool_get_score,
    "get_news": _tool_get_news,
    "get_options_flow": _tool_get_options_flow,
    "get_insider": _tool_get_insider,
}


def chat(messages: list[dict]) -> dict:
    """
    messages: [{"role": "user"|"assistant", "content": str}, ...]
    Returns {"reply", "tool_calls", "rounds", "usage_today"}.
    """
    if not ai_client.ai_available():
        return {"reply": "AI is not configured - add ANTHROPIC_API_KEY to .env.",
                "tool_calls": [], "rounds": 0, "unavailable": True}
    out = chat_with_tools(
        messages,
        tools=CHAT_TOOLS,
        tool_handlers=CHAT_HANDLERS,
        system=_chat_system(),
        model=model_for("chat"),
        max_tokens=2048,
        max_rounds=10,
    )
    out["usage_today"] = ai_client.usage_today()
    return out


# ── Bull vs Bear earnings debate ─────────────────────────────────────────────
# Multi-agent pattern (TradingAgents-style): a bull advocate and a bear
# advocate argue from the SAME fetched data, then a judge issues the verdict.
# Three small calls - pennies on Haiku.

def earnings_debate(ticker: str) -> dict:
    if not ai_client.ai_available():
        return {"available": False, "reason": "ANTHROPIC_API_KEY not configured"}
    t = ticker.upper()

    snap = _tool_get_snapshot(t)
    news = _tool_get_news(t).get("articles", [])[:8]
    headlines = [a.get("title") or a.get("headline") or "" for a in news]
    try:
        flow = _tool_get_options_flow(t)
    except Exception:
        flow = {}
    try:
        insider = _tool_get_insider(t)
    except Exception:
        insider = {}

    position = None
    for p in _positions_summary():
        if p["ticker"] == t:
            position = p

    # Latest earnings-call transcript excerpt - the strongest free evidence
    transcript = None
    try:
        import transcripts
        tx = transcripts.get_transcript_excerpt(t, max_chars=5000)
        if tx:
            transcript = {"quarter": f"Q{tx['quarter']} {tx['year']}",
                          "excerpt": tx["excerpt"]}
    except Exception:
        pass

    evidence = json.dumps({
        "ticker": t, "snapshot": snap, "headlines": headlines,
        "options_flow": flow, "insider": insider, "position": position,
        "last_earnings_call": transcript,
    }, default=str)[:19000]

    def advocate(side: str):
        return complete(
            f"Evidence:\n{evidence}",
            system=(f"You are the {side} advocate for {t} going into its next earnings. "
                    f"Argue the {side} case in exactly 3 bullet points, each grounded in a "
                    "specific number or headline from the evidence. No hedging - argue your side."),
            model=model_for("debate"),
            max_tokens=400,
        )

    bull = advocate("BULL")
    bear = advocate("BEAR")
    if bull is None or bear is None:
        return {"available": False, "reason": "AI call failed or daily budget reached"}

    judge = complete(
        f"Evidence:\n{evidence}\n\nBULL case:\n{bull}\n\nBEAR case:\n{bear}",
        system=("You are the judge of an earnings debate. Weigh both cases against the "
                "evidence and the user's position (if any). Output: (1) which case is "
                "stronger and why in 2 sentences, (2) an explicit recommendation - "
                "hold all / trim N shares / add on dip / no position, stay out - with "
                "one line of reasoning. End with: 'Analysis, not licensed financial advice.'"),
        model=model_for("judge"),
        max_tokens=400,
    )
    return {
        "available": True, "ticker": t,
        "bull": bull, "bear": bear,
        "verdict": judge or "judge call failed",
        "position": position,
        "usage_today": ai_client.usage_today(),
    }


# ── Scan candidate explanations ──────────────────────────────────────────────
# One batched Haiku call for the top N scan candidates, cached per scan_time.

SCAN_EXPLAIN_CACHE = BASE / "scan_explanations.json"


def explain_scan_candidates(max_candidates: int = 10) -> dict:
    scan_file = BASE / "scan_results.json"
    if not scan_file.exists():
        return {"available": False, "reason": "no scan results - run scan_universe first"}
    scan = _load_json(scan_file) or {}
    scan_time = scan.get("scan_time") or scan.get("generated") or "unknown"

    cached = _load_json(SCAN_EXPLAIN_CACHE)
    if cached and cached.get("scan_time") == scan_time:
        return {"available": True, **cached, "cached": True}

    if not ai_client.ai_available():
        return {"available": False, "reason": "ANTHROPIC_API_KEY not configured"}

    candidates = (scan.get("candidates") or scan.get("results") or [])[:max_candidates]
    if not candidates:
        return {"available": False, "reason": "scan results empty"}

    payload = json.dumps(candidates, default=str)[:12000]
    raw = complete(
        f"Scan candidates:\n{payload}\n\n"
        "For EACH candidate output one line: TICKER: <one concrete sentence on why "
        "this setup scored well and what would confirm the entry>. "
        "Ground every sentence in the numbers given (RSI, score, BB%, upside). "
        "Output ONLY those lines, one per candidate.",
        system="You are a terse trading analyst. Never invent numbers.",
        model=model_for("explain"),
        max_tokens=800,
    )
    if raw is None:
        return {"available": False, "reason": "AI call failed or daily budget reached"}

    explanations = {}
    for line in raw.splitlines():
        if ":" in line:
            tick, _, text = line.partition(":")
            tick = tick.strip().upper().lstrip("-*• ").strip()
            if tick.isalpha() and len(tick) <= 6:
                explanations[tick] = text.strip()

    result = {"scan_time": scan_time, "explanations": explanations,
              "generated": datetime.now().isoformat(timespec="seconds")}
    try:
        SCAN_EXPLAIN_CACHE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"available": True, **result, "cached": False}


# ── Extra chat tools: trade setup, discipline, macro, backtest ───────────────

def _tool_get_trade_setup(ticker: str, equity: float = 10000.0):
    import risk_engine
    from data_fetch import get_full_snapshot
    snap = _clean_snapshot(get_full_snapshot(ticker.upper()))
    return risk_engine.build_trade_setup(snap, float(equity))


def _tool_check_discipline():
    import guardian
    from data_fetch import get_full_snapshot
    data = _load_json(POSITIONS_FILE) or {"accounts": {}}
    tickers = sorted({p["ticker"] for a in data.get("accounts", {}).values()
                      for p in a.get("positions", [])})
    prices = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(get_full_snapshot, t): t for t in tickers}
        for f in as_completed(futs, timeout=120):
            try:
                snap = f.result()
                prices[futs[f]] = {"price": snap.get("price")}
            except Exception:
                pass
    history = _load_json(BASE / "portfolio_history.json") or []
    return {"violations": guardian.check_all(data, prices, history)}


def _tool_get_macro():
    import macro_data
    return macro_data.get_macro()


def _tool_run_backtest(tickers: list[str], lookback: int = 365, hold: int = 60):
    """Run the real backtester on up to 8 tickers, synchronously (chat-scale)."""
    import os
    import subprocess
    import sys as _sys
    tickers = [t.upper() for t in tickers][:8]
    if not tickers:
        return {"error": "give me 1-8 tickers"}
    lookback = min(int(lookback), 730)
    cmd = [_sys.executable, str(Path(__file__).parent / "backtest.py"),
           "--tickers", *tickers, "--lookback", str(lookback),
           "--hold", str(int(hold)), "--save", "--quiet"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=420, env=env)
    if proc.returncode != 0:
        return {"error": f"backtest failed: {(proc.stdout or '')[-500:]}"}
    results = _load_json(BASE / "backtest_results.json") or {}
    entries = results.get("all_entries", [])
    return {
        "tickers": tickers, "lookback_days": lookback, "hold_days": int(hold),
        "n_entries": len(entries),
        "tiers": results.get("tiers", []),
        "spy_baseline": results.get("spy_baseline"),
        "note": "tier thresholds are on the 110-pt technical scale; multiply by ~1.64 for the live 180-pt scale",
    }


CHAT_TOOLS.extend([
    {
        "name": "get_trade_setup",
        "description": "Compute a structured trade setup for a ticker using the user's OWN risk rules: entry, ATR/fixed stop, target, risk-based share count, dollar risk/reward, R:R. All numbers computed by code, never estimated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "equity": {"type": "number", "description": "Account equity in dollars to size against (ask the user or use get_portfolio cash+positions)"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "check_discipline",
        "description": "Run the discipline guardian: checks the live portfolio against the user's configured rules (position caps, stops required, cash floor, portfolio heat, drawdown, stale swings). Returns violations.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_macro",
        "description": "Macro regime data: 10y/3m treasury yields, yield-curve spread and inversion flag, plus CPI/Fed funds/unemployment when FRED is configured.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_backtest",
        "description": "Run the real historical backtester on 1-8 tickers and return tier performance vs SPY. Use to answer 'would rule X have worked' questions with actual evidence. Takes 1-4 minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "lookback": {"type": "integer", "description": "days of history, max 730"},
                "hold": {"type": "integer", "description": "hold period in days"},
            },
            "required": ["tickers"],
        },
    },
])

CHAT_HANDLERS.update({
    "get_trade_setup": _tool_get_trade_setup,
    "check_discipline": _tool_check_discipline,
    "get_macro": _tool_get_macro,
    "run_backtest": _tool_run_backtest,
})
