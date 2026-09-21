"""
community_youtube.py - Tech-creator signal extractor (community_score Step 2/3).

Fetches video metadata for a ticker via YouTube Data API v3.
Categorizes by channel:
  - TECH_CREATOR allowlist (MKBHD, Lex Fridman, Acquired, Two Min Papers, etc.)
    → POSITIVE early signal. These channels cover tech BEFORE retail attention.
  - GENERAL channels → moderate weight (volume + sentiment).
  - PENNY_PUMP allowlist (known pump-and-dump channels) → fade signal.

Public API:
    fetch_youtube_signal(ticker, days=30) -> dict
    get_youtube_signals(tickers, force_refresh=False, verbose=False) -> dict[ticker, dict]

Returns per ticker:
    {
        "has_data":           bool,
        "total_videos":       int,
        "tech_creator_videos": list[{title, channel, published, url}],
        "general_videos":     list[...],
        "sentiment":          str,   # BULLISH / BEARISH / MIXED / NEUTRAL
        "fetched_at":         str,
        "note":               str,
    }

Quota:
    search.list = 100 units. Daily quota = 10K.
    26-ticker daily refresh = 2600 units. Plenty of headroom.

Caching:
    data/community_cache/{ticker}_youtube.json - 24h TTL.

Allowlist maintained as TECH_CREATOR_HANDLES at module top.
LAST_REVIEWED date - annual review of channel relevance.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# Ensure .env loaded so YOUTUBE_API_KEY + ANTHROPIC_API_KEY available
try:
    from data_fetch import load_env as _load_env
    _load_env()
except Exception:
    pass


BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE / "data" / "community_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CHANNEL_ID_CACHE = CACHE_DIR / "_channel_ids.json"

CACHE_TTL_HOURS = 24
HTTP_TIMEOUT = 12

# ── Allowlists ──────────────────────────────────────────────────────────────
# LAST_REVIEWED: 2026-05-09. Annual review - channels rebrand/decline/demonetize.
LAST_REVIEWED = "2026-05-09"

# Tech-creator channels - early-signal layer.
# Tiers:
#   tier_a: deep technical, 12-24mo lead time on real trends
#   tier_b: mainstream tech reviews, 3-6mo lead
#   tier_c: business/macro analysis, 1-3mo lead
TECH_CREATOR_HANDLES = {
    # Tier A - deep technical
    "@lexfridman":          "tier_a",   # Lex Fridman
    "@TwoMinutePapers":     "tier_a",   # AI/research papers
    "@AndrejKarpathy":      "tier_a",   # AI/LLM internals
    "@coldfustion":         "tier_a",   # Tech business deep dives (ColdFusion)
    # Tier B - mainstream tech reviews
    "@mkbhd":               "tier_b",   # Marques Brownlee
    "@EngineeringExplained":"tier_b",
    "@WendoverProductions": "tier_b",   # geopolitics/business explainers
    # Tier C - business/macro
    "@AcquiredFM":          "tier_c",   # Acquired Podcast
    "@allin":               "tier_c",   # All-In Podcast
}

# Penny-pump red flags. Videos from these channels = fade signal.
# Keep small, only well-known ones.
PENNY_PUMP_HANDLES = {
    "@PennyStockEgghead",
    "@MotleyFool",  # not penny-pump per se but heavy retail-late content
}


# ── Cache helpers ───────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker.upper()}_youtube.json"


def _is_fresh(path: Path, ttl_hours: float = CACHE_TTL_HOURS) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age < ttl_hours * 3600


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


# ── Channel ID resolution (one-time per handle, cached forever) ─────────────

def _load_channel_id_map() -> dict:
    if CHANNEL_ID_CACHE.exists():
        try:
            return json.loads(CHANNEL_ID_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_channel_id_map(m: dict) -> None:
    CHANNEL_ID_CACHE.write_text(json.dumps(m, indent=2), encoding="utf-8")


def _resolve_channel_id(handle: str, api_key: str) -> Optional[str]:
    """Resolve @handle → channel ID. Uses channels.list (1 unit). Cached forever."""
    cache = _load_channel_id_map()
    if handle in cache:
        return cache[handle]
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "id", "forHandle": handle, "key": api_key},
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if not items:
            return None
        cid = items[0]["id"]
        cache[handle] = cid
        _save_channel_id_map(cache)
        return cid
    except Exception:
        return None


def _build_channel_id_lookup(api_key: str) -> dict[str, tuple[str, str]]:
    """Returns {channel_id: (handle, tier)}. Resolves any missing handles."""
    out = {}
    for handle, tier in TECH_CREATOR_HANDLES.items():
        cid = _resolve_channel_id(handle, api_key)
        if cid:
            out[cid] = (handle, tier)
    for handle in PENNY_PUMP_HANDLES:
        cid = _resolve_channel_id(handle, api_key)
        if cid:
            out[cid] = (handle, "penny_pump")
    return out


# ── YouTube fetcher ─────────────────────────────────────────────────────────

def _search_videos(ticker: str, api_key: str, days: int = 30,
                   max_results: int = 25) -> list[dict]:
    """Search.list query. Cost = 100 units."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part":          "snippet",
                "q":             f"{ticker} stock",
                "type":          "video",
                "order":         "relevance",
                "maxResults":    max_results,
                "publishedAfter": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "key":           api_key,
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
    except Exception:
        return []

    videos = []
    for it in items:
        sn = it.get("snippet", {})
        title = (sn.get("title") or "").strip()
        # Loose ticker match - title or description must mention ticker
        desc = (sn.get("description") or "").strip()
        haystack = (title + " " + desc).upper()
        if ticker.upper() not in haystack and f"${ticker.upper()}" not in haystack:
            continue
        videos.append({
            "video_id":  it.get("id", {}).get("videoId", ""),
            "title":     title,
            "channel":   sn.get("channelTitle", ""),
            "channel_id": sn.get("channelId", ""),
            "published": sn.get("publishedAt", ""),
            "description": desc[:500],
        })
    return videos


# ── Sentiment via Haiku (graceful degrade) ──────────────────────────────────

def _classify_sentiment_haiku(ticker: str, videos: list[dict]) -> tuple[str, str]:
    if not videos:
        return "NEUTRAL", "no videos"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not api_key.startswith("sk-ant"):
        return "NEUTRAL", "no Anthropic key - sentiment skipped"

    sample = "\n".join(
        f"[{v['channel']}] {v['title']}: {v['description'][:200]}"
        for v in videos[:15]
    )[:8000]

    prompt = (
        f"Classify sentiment toward ${ticker} stock from these YouTube video "
        f"titles + descriptions. Reply with ONE WORD only: BULLISH, BEARISH, "
        f"MIXED, or NEUTRAL.\n\nVideos:\n{sample}"
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
            return result, f"haiku ({len(videos)} videos)"
        return "NEUTRAL", f"haiku returned {result!r} - defaulted"
    except Exception as e:
        return "NEUTRAL", f"haiku failed: {type(e).__name__}"


# ── Public API ──────────────────────────────────────────────────────────────

def fetch_youtube_signal(ticker: str, days: int = 30,
                         force_refresh: bool = False) -> dict:
    """Fetch + categorize YouTube videos for one ticker. Caches 24h.
    Cost: 100 quota units per fresh fetch."""
    ticker = ticker.upper()

    if not force_refresh:
        cached = _load_cache(ticker)
        if cached:
            return cached

    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        return {
            "has_data": False, "total_videos": 0,
            "tech_creator_videos": [], "general_videos": [],
            "sentiment": "NEUTRAL",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "no YOUTUBE_API_KEY set",
        }

    # Resolve allowlist channels (cached forever per handle)
    channel_lookup = _build_channel_id_lookup(api_key)

    videos = _search_videos(ticker, api_key, days=days)

    tech_videos: list[dict] = []
    general_videos: list[dict] = []
    penny_videos: list[dict] = []
    for v in videos:
        cid = v.get("channel_id", "")
        if cid in channel_lookup:
            handle, tier = channel_lookup[cid]
            v["tier"] = tier
            v["handle"] = handle
            if tier == "penny_pump":
                penny_videos.append(v)
            else:
                tech_videos.append(v)
        else:
            general_videos.append(v)

    sentiment, sent_note = _classify_sentiment_haiku(ticker, videos)

    # Strip large fields from cached output
    def slim(v):
        return {
            "title":     v.get("title", "")[:120],
            "channel":   v.get("channel", ""),
            "tier":      v.get("tier", ""),
            "published": v.get("published", "")[:10],
            "url":       f"https://youtube.com/watch?v={v.get('video_id','')}",
        }

    result = {
        "has_data":            True,
        "total_videos":        len(videos),
        "tech_creator_videos": [slim(v) for v in tech_videos[:5]],
        "general_videos":      [slim(v) for v in general_videos[:3]],
        "penny_pump_videos":   [slim(v) for v in penny_videos[:3]],
        "sentiment":           sentiment,
        "fetched_at":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note":                sent_note,
    }
    _save_cache(ticker, result)
    return result


def get_youtube_signals(tickers: list[str], force_refresh: bool = False,
                        verbose: bool = False) -> dict[str, dict]:
    """Fetch all signals. Quota cost ≈ 100 units × len(uncached tickers)."""
    results = {}
    for t in tickers:
        if verbose:
            print(f"  YouTube: {t}...", end=" ", flush=True)
        results[t.upper()] = fetch_youtube_signal(t, force_refresh=force_refresh)
        if verbose:
            r = results[t.upper()]
            tc = len(r.get("tech_creator_videos", []))
            print(f"{r['total_videos']} videos ({tc} tech-creator), "
                  f"{r['sentiment']}")
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python community_youtube.py TICKER [TICKER ...] [--refresh]")
        sys.exit(1)
    refresh = "--refresh" in sys.argv
    tickers = [a for a in sys.argv[1:] if not a.startswith("--")]
    sigs = get_youtube_signals(tickers, force_refresh=refresh, verbose=True)
    print()
    for t, r in sigs.items():
        print(f"  {t}  total={r['total_videos']}  "
              f"tech-creator={len(r['tech_creator_videos'])}  "
              f"sentiment={r['sentiment']}  ({r['note']})")
        for v in r["tech_creator_videos"]:
            print(f"    [TECH/{v['tier']}] {v['channel']}: {v['title']}")
        for v in r["general_videos"][:2]:
            print(f"    [gen] {v['channel']}: {v['title']}")
