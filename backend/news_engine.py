"""
News intelligence engine - smart use of NewsAPI + Finnhub.

Strategy:
  1. Whitelist trusted sources (filter out junk SEO sites)
  2. Three sweeps per day:
     - Pre-market (5:30-6:30am MST) - overnight + Asia/Europe news
     - Market hours (every 2hrs) - breaking news
     - After-close (1pm MST) - earnings, analyst calls
  3. Per-position sentiment via Finnhub (good/bad/neutral classification)
  4. Cross-reference news → portfolio impact mapping
  5. De-duplicate stories (same headline from 5 sources = 1 entry)

Usage:
  python news_engine.py macro       # 5 macro themes
  python news_engine.py portfolio   # all your positions
  python news_engine.py breaking    # last 60 min only, all themes + positions
  python news_engine.py morning     # full briefing
"""
from __future__ import annotations
import sys, time, json, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import data_client as dc

BASE = Path(__file__).resolve().parents[1]

# ── Trusted sources (whitelist) ───────────────────────────────────────────────

TRUSTED_SOURCES = {
    "tier1": [  # major financial/news outlets
        "Reuters", "Bloomberg", "Wall Street Journal", "Financial Times",
        "CNBC", "Associated Press", "Yahoo Entertainment", "Yahoo",
        "MarketWatch", "Barron's", "The Economist", "Bloomberg.com",
        "Cnbc.com", "Reuters.com", "Wsj.com", "Ft.com",
    ],
    "tier2": [  # solid secondary sources
        "Seeking Alpha", "SeekingAlpha", "Barrons.com", "Investors Business Daily",
        "The Motley Fool", "Forbes", "Business Insider", "Benzinga",
        "Investing.com", "ETF.com", "Markets Insider",
        "Investopedia", "Zacks Investment Research", "Schaeffersresearch.com",
        "Finnhub", "Finnhub.io", "ChartMill",
    ],
    "tier3_reputable": [  # geopolitical/macro reputable
        "Al Jazeera", "Al Jazeera English", "BBC News", "The Guardian",
        "The Irish Times", "The Times of India", "South China Morning Post",
        "New York Post", "Politico", "Axios", "The Hill",
    ],
}

# Sources that are mostly junk for trading
BLOCKED_SOURCES = {
    "Erickimphotography.com", "Wattsupwiththat.com", "Naturalnews.com",
    "Super-memory.com", "Freerepublic.com", "Raw Story",
}

def source_tier(source: str) -> str:
    if not source:
        return "unknown"
    if source in BLOCKED_SOURCES:
        return "blocked"
    for tier, names in TRUSTED_SOURCES.items():
        if source in names:
            return tier
    return "unverified"

# ── Macro queries (refined for signal-to-noise) ──────────────────────────────

MACRO_QUERIES = {
    "🛢️ Iran/Hormuz": '("Iran" AND ("Hormuz" OR "oil" OR "tanker" OR "strike")) NOT (movie OR film)',
    "🇨🇳 China decoupling": '("China" AND ("rare earth" OR "tariff" OR "sanctions" OR "Taiwan"))',
    "🛡️ Defense rearmament": '("NATO" OR "rearmament" OR "Pentagon" OR "defense spending")',
    "🏛️ Fed/Rates": '("Federal Reserve" OR "Fed chair" OR "rate cut" OR "inflation") AND (Powell OR Trump OR FOMC)',
    "🤖 AI/Semis": '("AI capex" OR "data center" OR "semiconductor" OR "TSMC" OR "NVIDIA") AND (earnings OR demand)',
    "⚛️ Nuclear": '("nuclear" AND ("PPA" OR "SMR" OR "reactor" OR "uranium"))',
    "🥇 Gold/dollar": '("gold price" OR "dollar weakening" OR "DXY" OR "BRICS")',
}

# ── Story deduplication ─────────────────────────────────────────────────────

def dedupe(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate stories by headline similarity."""
    seen = set()
    out = []
    for a in articles:
        title = (a.get('title') or a.get('headline') or '').lower()
        if not title:
            continue
        # Hash first 8 words - catches "Iran strikes US base" duplicates from 5 sources
        key = " ".join(title.split()[:8])
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out

# ── Sentiment scoring (keyword-based, fast, no extra API calls) ──────────────

BULLISH_WORDS = {
    "beat", "surge", "rally", "breakout", "upgrade", "outperform", "record high",
    "growth", "expand", "innovate", "win", "approval", "boom", "soar", "jump",
}
BEARISH_WORDS = {
    "miss", "plunge", "crash", "downgrade", "underperform", "loss", "decline",
    "lawsuit", "fraud", "investigation", "halt", "recall", "cut", "warning",
    "fall", "drop", "tumble", "sell-off", "selloff",
}

def quick_sentiment(text: str) -> str:
    if not text:
        return "neutral"
    t = text.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in t)
    bear = sum(1 for w in BEARISH_WORDS if w in t)
    if bull > bear + 1:
        return "🟢 bullish"
    if bear > bull + 1:
        return "🔴 bearish"
    return "⚪ neutral"

# ── Recency filter ───────────────────────────────────────────────────────────

def parse_when(article: dict) -> datetime | None:
    p = article.get('publishedAt') or article.get('datetime')
    if not p:
        return None
    try:
        if isinstance(p, (int, float)):
            return datetime.fromtimestamp(p, tz=timezone.utc)
        return datetime.fromisoformat(p.replace('Z', '+00:00'))
    except Exception:
        return None

def is_recent(article: dict, max_age_hours: int) -> bool:
    when = parse_when(article)
    if not when:
        return False
    age = datetime.now(timezone.utc) - when
    return age < timedelta(hours=max_age_hours)

# ── Filter pipeline ──────────────────────────────────────────────────────────

def filter_articles(articles: list[dict], max_age_hours: int = 24,
                    min_tier: str = "tier3_reputable") -> list[dict]:
    """Apply trust + recency + dedup filters."""
    tier_rank = {"tier1": 3, "tier2": 2, "tier3_reputable": 1, "unverified": 0,
                 "blocked": -1, "unknown": 0}
    min_rank = tier_rank.get(min_tier, 1)

    filtered = []
    for a in articles:
        source = a.get('source') or ''
        if source_tier(source) == "blocked":
            continue
        if tier_rank.get(source_tier(source), 0) < min_rank:
            continue
        if not is_recent(a, max_age_hours):
            continue
        filtered.append(a)
    return dedupe(filtered)

# ── Print helpers ────────────────────────────────────────────────────────────

def print_article(a: dict, indent: str = "  "):
    title  = a.get('title') or a.get('headline') or ''
    source = a.get('source') or ''
    when   = parse_when(a)
    age    = ""
    if when:
        delta = datetime.now(timezone.utc) - when
        if delta.total_seconds() < 3600:
            age = f"{int(delta.total_seconds()/60)}m ago"
        elif delta.total_seconds() < 86400:
            age = f"{int(delta.total_seconds()/3600)}h ago"
        else:
            age = f"{delta.days}d ago"
    sent = quick_sentiment(title)
    print(f"{indent}{sent}  [{age:>6}] {title[:110]}")
    print(f"{indent}        ↳ {source}")

# ── Sweeps ───────────────────────────────────────────────────────────────────

MACRO_KEYWORDS = {
    "🛢️ Iran/Hormuz":       ["iran", "hormuz", "tanker", "oil strike", "saudi"],
    "🇨🇳 China decoupling":  ["china", "rare earth", "tariff", "taiwan", "semiconductor export"],
    "🛡️ Defense":           ["nato", "rearmament", "pentagon", "patriot", "missile defense"],
    "🏛️ Fed/Rates":         ["federal reserve", "rate cut", "inflation", "fomc", "powell", "warsh"],
    "🤖 AI/Semis":          ["ai capex", "data center", "semiconductor", "tsmc", "nvidia", "ai infrastructure"],
    "⚛️ Nuclear":            ["nuclear", "smr", "reactor", "uranium", "ppa"],
    "🥇 Gold/dollar":        ["gold price", "dxy", "brics", "dollar reserve"],
}

def sweep_macro_finnhub(max_age_hours: int = 12):
    """Real-time macro via Finnhub general feed (no 24h NewsAPI delay)."""
    import requests, os
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        print("No Finnhub key. Falling back to NewsAPI (24h delayed).")
        return sweep_macro_newsapi(max_age_hours)

    print("=" * 100)
    print("📰 MACRO NEWS - REAL-TIME (Finnhub general feed)")
    print("=" * 100)

    try:
        r = requests.get("https://finnhub.io/api/v1/news",
                         params={"category": "general", "token": key}, timeout=10)
        all_articles = r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"Finnhub error: {e}")
        return

    # Convert to common format
    converted = [{
        "title":       a.get("headline", ""),
        "source":      a.get("source", ""),
        "publishedAt": datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc).isoformat() if a.get("datetime") else None,
        "url":         a.get("url", ""),
    } for a in all_articles]

    # Filter to recent only
    recent = [a for a in converted if is_recent(a, max_age_hours)]
    recent = dedupe(recent)

    # Bucket by macro theme
    for theme, keywords in MACRO_KEYWORDS.items():
        matches = []
        for a in recent:
            title_lower = (a.get("title") or "").lower()
            if any(kw in title_lower for kw in keywords):
                matches.append(a)
        if not matches:
            continue
        print(f"\n── {theme} ──")
        for a in matches[:5]:
            print_article(a)

def sweep_macro_newsapi(max_age_hours: int = 36):
    """Archive macro via NewsAPI - 24h delayed, broader coverage for context."""
    print("=" * 100)
    print("📰 MACRO NEWS - ARCHIVE (NewsAPI, 24h delayed)")
    print("=" * 100)
    for theme, q in MACRO_QUERIES.items():
        print(f"\n── {theme} ──")
        raw = dc.get_macro_news(q, page_size=8)
        good = filter_articles(raw, max_age_hours=max_age_hours, min_tier="tier3_reputable")
        if not good:
            print("  (no recent trusted-source articles)")
            continue
        for a in good[:5]:
            print_article(a)

def sweep_macro(max_age_hours: int = 12):
    """Default: real-time first, then archive backfill."""
    sweep_macro_finnhub(max_age_hours=max_age_hours)
    print("\n")
    sweep_macro_newsapi(max_age_hours=36)

def sweep_portfolio(max_age_hours: int = 24):
    print("=" * 100)
    print("💼 PORTFOLIO NEWS SWEEP")
    print("=" * 100)
    with open(BASE / "positions.json", encoding="utf-8") as f:
        data = json.load(f)
    tickers = []
    for acct in data["accounts"].values():
        for p in acct.get("positions", []):
            tickers.append(p["ticker"])

    for t in tickers:
        raw = dc.get_news_sentiment(t, limit=10)
        good = filter_articles(raw, max_age_hours=max_age_hours, min_tier="tier3_reputable")
        if not good:
            continue
        print(f"\n── {t} ──")
        for a in good[:3]:
            print_article(a)

def sweep_breaking():
    """Last 60 minutes only - Finnhub real-time only (NewsAPI is 24h delayed)."""
    print("=" * 100)
    print("⚡ BREAKING - LAST 60 MIN (Finnhub real-time)")
    print("=" * 100)

    import requests, os
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        print("No Finnhub key set.")
        return

    try:
        r = requests.get("https://finnhub.io/api/v1/news",
                         params={"category": "general", "token": key}, timeout=10)
        articles = r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"Finnhub error: {e}")
        return

    converted = [{
        "title":       a.get("headline", ""),
        "source":      a.get("source", ""),
        "publishedAt": datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc).isoformat() if a.get("datetime") else None,
        "url":         a.get("url", ""),
    } for a in articles if is_recent(a.get("datetime") and {"publishedAt": datetime.fromtimestamp(a["datetime"], tz=timezone.utc).isoformat()} or {}, 1)]
    converted = dedupe(converted)

    if not converted:
        print("\n  (no breaking news in last 60 min)")
        # Widen to 3hr if nothing in 60min
        print("\n[Last 3hrs instead]")
        widened = [{
            "title":       a.get("headline", ""),
            "source":      a.get("source", ""),
            "publishedAt": datetime.fromtimestamp(a.get("datetime", 0), tz=timezone.utc).isoformat() if a.get("datetime") else None,
            "url":         a.get("url", ""),
        } for a in articles if is_recent(a.get("datetime") and {"publishedAt": datetime.fromtimestamp(a["datetime"], tz=timezone.utc).isoformat()} or {}, 3)]
        widened = dedupe(widened)
        converted = widened

    # Bucket by theme
    for theme_emoji, keywords in MACRO_KEYWORDS.items():
        matches = [a for a in converted if any(kw in a.get("title", "").lower() for kw in keywords)]
        if matches:
            print(f"\n  {theme_emoji}")
            for a in matches[:3]:
                print_article(a, indent="    ")

    # Also show top 5 unbucketed
    if not any(any(kw in a.get("title", "").lower() for kws in MACRO_KEYWORDS.values() for kw in kws) for a in converted):
        print("\n  [Top headlines]")
        for a in converted[:5]:
            print_article(a, indent="    ")

# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if cmd == "macro":
        sweep_macro(max_age_hours=24)
    elif cmd == "portfolio":
        sweep_portfolio(max_age_hours=48)
    elif cmd == "breaking":
        sweep_breaking()
    elif cmd == "morning":
        sweep_macro(max_age_hours=18)
        print()
        sweep_portfolio(max_age_hours=24)
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python news_engine.py [macro|portfolio|breaking|morning]")
        sys.exit(1)

    print(f"\n{'=' * 100}")
    print(f"API usage: {dc.status()}")
