"""
innovation_score.py - Research/innovation signal combiner (innovation_score Step 2/2 v1).

v1 spec (mirrors community_score design decisions):
  - Display-only - does NOT enter score.py 180pt math.
  - Pluggable INNOVATION_MODE constant for future promotion to additive.
  - Forward log to data/innovation_cache/_forward_log.jsonl for 60d evaluation.
  - Sparse-by-design: only frontier-tech tickers in ARXIV_SEARCH_TERMS get a score.

Factors (raw 0..+50, normalized 0-100):
  arXiv paper count (12mo):
    >50  → +25  (firehose research output, frontier player)
    25-50 → +20
    10-25 → +15
    5-10  → +10
    1-5   → +5
    0     → 0
  arXiv category breadth:
    >=4 categories  → +15  (broad research portfolio)
    2-3 categories  → +10
    1 category      → +5
  Frontier category match:
    cs.AI / cs.LG / quant-ph / cs.RO present → +10  (touching active narratives)

USPTO patent signal: deferred to v1.1 (PatentsView API redesign 2024;
arXiv signal alone is meaningful for eligible tickers).

Public API:
    score_innovation(ticker, arxiv_signal=None) -> InnovationScoreResult
    get_innovation_scores(tickers, force_refresh=False) -> dict[ticker, dict]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE / "data" / "innovation_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
FORWARD_LOG = CACHE_DIR / "_forward_log.jsonl"


# ── v1 mode flag (per user directive 2026-05-09) ─────────────────────────────
# "additive" | "display_only" | "gate" | "disabled"
# v1 ships display_only. After 60d forward observation, evaluate promotion.
INNOVATION_MODE = "display_only"


# Frontier categories - match indicates exposure to active narratives
FRONTIER_CATEGORIES = {
    "cs.AI", "cs.LG",        # AI / machine learning → ai_infra narrative
    "cs.CL",                  # NLP / LLMs → ai_infra
    "cs.RO",                  # robotics
    "quant-ph",               # quantum → quantum narrative
    "physics.comp-ph",        # computational physics
    "cs.ET",                  # emerging tech (quantum-adjacent)
    "q-bio",                  # quantitative biology → biotech catalysts
    "cs.CR",                  # crypto / security → defense_it
}


@dataclass
class InnovationScoreResult:
    ticker:    str
    score:     int = 0          # normalized 0-100
    raw_score: int = 0          # raw 0..+50
    breakdown: dict[str, int] = field(default_factory=dict)
    notes:     list[str] = field(default_factory=list)
    has_data:  bool = False
    paper_count: int = 0
    categories:  list[str] = field(default_factory=list)

    def __str__(self):
        bar = "█" * (self.score // 5) + "░" * (20 - self.score // 5)
        lines = [
            f"{self.ticker} INNOVATION {self.score}/100  ({self.paper_count} papers)",
            f"  {bar}  cats: {self.categories[:3]}",
        ]
        for k, v in self.breakdown.items():
            sign = "+" if v >= 0 else ""
            lines.append(f"  {k}: {sign}{v}")
        return "\n".join(lines)


# ── Factor scorers ──────────────────────────────────────────────────────────

def _score_paper_volume(count: int) -> tuple[int, str]:
    if count >= 50:
        return 25, f"firehose research output ({count} papers/12mo)"
    if count >= 25:
        return 20, f"strong research output ({count} papers)"
    if count >= 10:
        return 15, f"moderate research output ({count} papers)"
    if count >= 5:
        return 10, f"light research output ({count} papers)"
    if count >= 1:
        return 5, f"minimal research output ({count} papers)"
    return 0, "no papers in 12mo"


def _score_category_breadth(categories: list[str]) -> tuple[int, str]:
    n = len(categories)
    if n >= 4:
        return 15, f"broad research portfolio ({n} categories)"
    if n >= 2:
        return 10, f"focused research ({n} categories)"
    if n == 1:
        return 5, f"single-category research"
    return 0, "no categories"


def _score_frontier_match(categories: list[str]) -> tuple[int, str]:
    matches = [c for c in categories if c in FRONTIER_CATEGORIES]
    if not matches:
        return 0, "no frontier-category match"
    return 10, f"frontier match: {matches}"


# ── Combiner ────────────────────────────────────────────────────────────────

def score_innovation(ticker: str,
                     arxiv_signal: Optional[dict] = None) -> InnovationScoreResult:
    """Compute innovation score for one ticker. Display-only per v1."""
    result = InnovationScoreResult(ticker=ticker.upper())

    if not arxiv_signal or not arxiv_signal.get("has_data"):
        result.notes.append("no arXiv data (ticker not in ARXIV_SEARCH_TERMS map)")
        return result

    result.has_data = True
    result.paper_count = arxiv_signal.get("paper_count", 0)
    result.categories  = arxiv_signal.get("categories", [])

    # 1. Paper volume
    pts, note = _score_paper_volume(result.paper_count)
    result.breakdown["arXiv volume"] = pts
    result.notes.append(note)

    # 2. Category breadth
    pts, note = _score_category_breadth(result.categories)
    result.breakdown["arXiv breadth"] = pts
    result.notes.append(note)

    # 3. Frontier category match
    pts, note = _score_frontier_match(result.categories)
    result.breakdown["Frontier match"] = pts
    result.notes.append(note)

    # Aggregate. Raw 0..+50 (volume 25 + breadth 15 + frontier 10).
    result.raw_score = sum(result.breakdown.values())
    result.score = max(0, min(100, round(result.raw_score / 50 * 100)))

    return result


# ── Forward-log (60d evaluation per ROADMAP design pattern) ─────────────────

def write_forward_log(ticker: str, score: int, raw_score: int,
                      breakdown: dict, paper_count: int,
                      price: Optional[float]) -> None:
    row = {
        "ticker":      ticker.upper(),
        "date":        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "score":       score,
        "raw_score":   raw_score,
        "breakdown":   breakdown,
        "paper_count": paper_count,
        "price":       round(price, 2) if price else None,
    }
    with open(FORWARD_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ── Public API ──────────────────────────────────────────────────────────────

def get_innovation_scores(tickers: list[str], snapshots: Optional[dict] = None,
                          force_refresh: bool = False, verbose: bool = False,
                          log_forward: bool = True) -> dict[str, dict]:
    snapshots = snapshots or {}

    from innovation_arxiv import get_arxiv_signals
    arxiv_sigs = get_arxiv_signals(tickers, force_refresh=force_refresh,
                                    verbose=verbose)

    results = {}
    for t in tickers:
        result = score_innovation(t, arxiv_signal=arxiv_sigs.get(t.upper()))
        results[t.upper()] = asdict(result)
        if log_forward and result.has_data:
            price = (snapshots.get(t.upper()) or {}).get("price")
            write_forward_log(t, result.score, result.raw_score,
                              result.breakdown, result.paper_count, price)
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python innovation_score.py TICKER [...] [--refresh] [--no-log]")
        sys.exit(1)
    refresh = "--refresh" in sys.argv
    no_log = "--no-log" in sys.argv
    tickers = [a for a in sys.argv[1:] if not a.startswith("--")]

    scores = get_innovation_scores(tickers, force_refresh=refresh, verbose=True,
                                    log_forward=not no_log)
    print()
    for t, s in sorted(scores.items(), key=lambda kv: kv[1]["score"], reverse=True):
        if not s["has_data"]:
            print(f"  {t:<6} -  not in arXiv map (no signal expected)")
            continue
        bar = "█" * (s["score"] // 5) + "░" * (20 - s["score"] // 5)
        print(f"  {t:<6} {s['score']:>3}/100  papers={s['paper_count']:>3}  "
              f"{bar}  cats={s['categories'][:3]}")
        for k, v in s["breakdown"].items():
            sign = "+" if v >= 0 else ""
            print(f"    {k}: {sign}{v}")
