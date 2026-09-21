"""
transcripts.py - Latest earnings-call transcript excerpts (free).

Uses the earningscall package (earningscall.biz free tier - roughly S&P 500
coverage, rate limited). 7-day file cache so each ticker fetches at most once
a week. Excerpts are trimmed for prompts: prepared remarks open the call, the
Q&A (the part analysts actually trade on) closes it, so we keep head + tail.

Degrades to None for uncovered tickers or when the API is unreachable -
callers simply proceed without transcript evidence.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE / "data" / "transcripts_cache"
CACHE_TTL = 7 * 24 * 3600


def get_transcript_excerpt(ticker: str, max_chars: int = 6000) -> Optional[dict]:
    """
    {"ticker", "year", "quarter", "excerpt", "full_length"} or None.
    Excerpt = first 40% + last 60% of the budget (opening remarks + Q&A tail).
    """
    t = ticker.upper()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{t}.json"

    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - cached.get("_fetched", 0) < CACHE_TTL:
                return cached if cached.get("excerpt") else None
        except Exception:
            pass

    result: dict = {"_fetched": time.time(), "ticker": t}
    try:
        from earningscall import get_company
        company = get_company(t)
        events = list(company.events())
        if company and events:
            event = events[0]  # most recent quarter
            transcript = company.get_transcript(event=event)
            text = (transcript.text or "") if transcript else ""
            if text:
                head_budget = int(max_chars * 0.4)
                tail_budget = max_chars - head_budget
                excerpt = text[:head_budget]
                if len(text) > max_chars:
                    excerpt += "\n[...]\n" + text[-tail_budget:]
                result.update({
                    "year": event.year, "quarter": event.quarter,
                    "excerpt": excerpt, "full_length": len(text),
                })
    except Exception:
        pass  # uncovered ticker, rate limit, or offline - cache the miss too

    try:
        cache_file.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result if result.get("excerpt") else None
