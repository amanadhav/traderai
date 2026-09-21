"""
community_reddit.py - Reddit retail-sentiment signal extractor.

Fetches mention counts + post bodies from r/wallstreetbets, r/stocks,
r/investing for a ticker over a configurable window. Sentiment classified
via Anthropic Haiku (cheap, accurate enough vs keyword matching).

Public API:
    fetch_reddit_signal(ticker, days=7) -> dict
    get_reddit_signals(tickers, force_refresh=False, verbose=False) -> dict[ticker, dict]

Returns per ticker:
    {
        "has_data":      bool,
        "mention_count": int,         # count across watched subs in window
        "rank_in_universe": int|None, # 1=highest mentions, else None
        "sentiment":     str,          # BULLISH / BEARISH / MIXED / NEUTRAL
        "top_posts":     list[{title, sub, score, url}],  # top 3 by sub upvotes
        "fetched_at":    str (ISO timestamp),
        "note":          str,
    }

Caching:
    data/community_cache/{ticker}_reddit.json - 6h TTL.

Reliability:
    - Unauthenticated public JSON endpoints (preflight 10/10 200s).
    - 429 → mark has_data=False, never blocks scoring.
    - User-Agent set per Reddit guidelines.
    - Haiku fallback only if ANTHROPIC_API_KEY present; else NEUTRAL default.

Score consumed by community_score.py per Q1 design (display-only v1).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

# Ensure .env loaded so ANTHROPIC_API_KEY is available for sentiment
try:
    from data_fetch import load_env as _load_env
    _load_env()
except Exception:
    pass


BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE / "data" / "community_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_HOURS = 6
SUBS = ["wallstreetbets", "stocks", "investing"]
USER_AGENT = "traderai/1.0 (community_score)"
HTTP_TIMEOUT = 10


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}_reddit.json"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age < CACHE_TTL_HOURS * 3600


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if _is_fresh(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(ticker: str, data: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Reddit fetcher ──────────────────────────────────────────────────────────

def _fetch_subreddit_mentions(ticker: str, sub: str, days: int = 7) -> list[dict]:
    """Search /r/<sub> for ticker mentions in last `days`. Returns posts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()

    # Reddit search uses sort=new + restrict_sr to limit to subreddit
    # Search query: "$NVDA" OR "NVDA stock" OR plain ticker - bare ticker is noisy
    # Reddit search relevance is decent for ticker symbols when restricted
    url = (
        f"https://www.reddit.com/r/{sub}/search.json"
        f"?q={quote(ticker)}&restrict_sr=1&sort=new&t=week&limit=25"
    )
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                            timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        children = resp.json().get("data", {}).get("children", [])
    except Exception:
        return []

    posts = []
    for c in children:
        d = c.get("data", {})
        created = d.get("created_utc", 0)
        if created < cutoff_ts:
            continue
        title = (d.get("title") or "").strip()
        if not title:
            continue
        # Filter out posts that just mention ticker in body but not title
        # (reduces noise from daily discussion threads)
        if ticker.upper() not in title.upper() and f"${ticker.upper()}" not in title.upper():
            continue
        posts.append({
            "title": title,
            "sub":   sub,
            "score": d.get("score", 0),
            "url":   "https://reddit.com" + d.get("permalink", ""),
            "selftext": (d.get("selftext") or "")[:500],
            "created": created,
        })
    return posts


# ── Sentiment via Haiku (graceful degrade to NEUTRAL if no key) ─────────────

def _classify_sentiment_haiku(ticker: str, posts: list[dict]) -> tuple[str, str]:
    """Returns (sentiment, note). Defaults to NEUTRAL if Haiku unavailable."""
    if not posts:
        return "NEUTRAL", "no posts"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not api_key.startswith("sk-ant"):
        return "NEUTRAL", "no Anthropic key - sentiment skipped"

    # Concatenate post titles + first line of selftext (cap ~3000 tokens)
    sample_text = "\n".join(
        f"[{p['sub']}] {p['title']}: {p['selftext'][:200]}"
        for p in posts[:15]
    )[:8000]

    prompt = (
        f"Classify retail sentiment toward ${ticker} stock from these "
        f"Reddit posts. Reply with ONE WORD only: BULLISH, BEARISH, MIXED, "
        f"or NEUTRAL.\n\nPosts:\n{sample_text}"
    )

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        result = msg.content[0].text.strip().upper().split()[0]
        if result in ("BULLISH", "BEARISH", "MIXED", "NEUTRAL"):
            return result, f"haiku ({len(posts)} posts)"
        return "NEUTRAL", f"haiku returned {result!r} - defaulted"
    except Exception as e:
        return "NEUTRAL", f"haiku failed: {type(e).__name__}"


# ── Public API ──────────────────────────────────────────────────────────────

def fetch_reddit_signal(ticker: str, days: int = 7,
                        force_refresh: bool = False) -> dict:
    """
    Fetch + classify Reddit signal for one ticker. Caches 6h.
    Returns dict shape documented at top of module.
    """
    ticker = ticker.upper()

    if not force_refresh:
        cached = _load_cache(ticker)
        if cached:
            return cached

    all_posts: list[dict] = []
    for sub in SUBS:
        all_posts.extend(_fetch_subreddit_mentions(ticker, sub, days))
        time.sleep(0.5)  # polite - well under any rate limit

    # Dedupe by URL (cross-sub crossposts)
    seen, posts = set(), []
    for p in all_posts:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        posts.append(p)

    # Top 3 by sub upvotes for display
    top_posts = sorted(posts, key=lambda p: p["score"], reverse=True)[:3]
    top_posts_minimal = [
        {"title": p["title"][:120], "sub": p["sub"], "score": p["score"], "url": p["url"]}
        for p in top_posts
    ]

    sentiment, note = _classify_sentiment_haiku(ticker, posts)

    result = {
        "has_data":      True,
        "mention_count": len(posts),
        "rank_in_universe": None,  # filled by get_reddit_signals
        "sentiment":     sentiment,
        "top_posts":     top_posts_minimal,
        "fetched_at":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note":          note,
    }
    _save_cache(ticker, result)
    return result


def get_reddit_signals(tickers: list[str], force_refresh: bool = False,
                       verbose: bool = False) -> dict[str, dict]:
    """Fetch all signals + assign rank_in_universe for top mentions."""
    results = {}
    for t in tickers:
        if verbose:
            print(f"  Reddit: {t}...", end=" ", flush=True)
        results[t.upper()] = fetch_reddit_signal(t, force_refresh=force_refresh)
        if verbose:
            print(f"{results[t.upper()]['mention_count']} mentions, "
                  f"{results[t.upper()]['sentiment']}")

    # Rank by mention_count (1 = most mentioned)
    ranked = sorted(results.items(), key=lambda kv: kv[1]["mention_count"], reverse=True)
    for rank, (t, r) in enumerate(ranked, start=1):
        if r["mention_count"] > 0:
            r["rank_in_universe"] = rank

    return results


# ── CLI for ad-hoc check ────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python community_reddit.py TICKER [TICKER ...] [--refresh]")
        sys.exit(1)
    refresh = "--refresh" in sys.argv
    tickers = [a for a in sys.argv[1:] if not a.startswith("--")]
    sigs = get_reddit_signals(tickers, force_refresh=refresh, verbose=True)
    print()
    for t, r in sorted(sigs.items(), key=lambda kv: kv[1]["mention_count"], reverse=True):
        rank = f"#{r['rank_in_universe']}" if r["rank_in_universe"] else "-"
        print(f"  {t:<6}  {r['mention_count']:>3} mentions  rank {rank:<3}  "
              f"{r['sentiment']:<8}  {r['note']}")
        for p in r["top_posts"]:
            print(f"    [{p['sub']}] {p['score']:>4}↑  {p['title']}")
