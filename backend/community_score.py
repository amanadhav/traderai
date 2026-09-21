"""
community_score.py - Combiner for Reddit + YouTube community signals.

v1 spec (per Q1/Q2/Q3 design decisions):
  - display-only - does NOT enter score.py 180pt math.
  - WSB-fade with RSI gate (top-5 + bullish + RSI buckets → +10/0/-20).
  - Tech-creator absence penalty -10 only for whitelisted consumer-facing sectors.
  - Promote to additive after 60d forward observation.

Factors (raw range −30 to +60, normalized to 0-100):
    YT tech-creator early    : 0..+30
    YT general coverage      : 0..+20
    WSB retail (RSI-gated)   : -20..+10
    Tech-creator absence     : -10..0   (whitelisted sectors only)

Public API:
    score_community(ticker, rsi=None, reddit_signal=None, youtube_signal=None,
                    universe_signals=None) -> CommunityScoreResult
    get_community_scores(tickers, snapshots=None) -> dict[ticker, dict]

Forward-log (per ROADMAP decision 2026-05-09): every score written to
data/community_cache/_forward_log.jsonl with (ticker, score, factors,
price, rsi, date) so 60-day evaluation has data to validate against.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE / "data" / "community_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
FORWARD_LOG = CACHE_DIR / "_forward_log.jsonl"


# ── Q3 sector whitelist (community-eligible sectors) ────────────────────────
# Hand-curated, not derived from yfinance sector strings (those mix NVDA + CRM
# under "Technology"). Same pattern as TICKER_NARRATIVES - explicit control.

COMMUNITY_ELIGIBLE_SECTORS = {
    "semiconductors", "consumer_electronics", "auto_ev",
    "gaming", "biotech_consumer", "aerospace_consumer",
    "quantum", "robotics",
}

TICKER_SECTOR: dict[str, str] = {
    # Semis
    "NVDA": "semiconductors", "AMD": "semiconductors", "TSM": "semiconductors",
    "ASML": "semiconductors", "INTC": "semiconductors", "AVGO": "semiconductors",
    "MRVL": "semiconductors", "ALAB": "semiconductors", "FN": "semiconductors",
    "CRDO": "semiconductors", "NVMI": "semiconductors", "SNDK": "semiconductors",
    "STX": "semiconductors", "WDC": "semiconductors", "SMH": "semiconductors",
    "SOXX": "semiconductors", "QCOM": "semiconductors", "MU": "semiconductors",
    # Consumer electronics
    "AAPL": "consumer_electronics",
    # Auto / EV
    "TSLA": "auto_ev", "RIVN": "auto_ev", "LCID": "auto_ev", "NIO": "auto_ev",
    "F": "auto_ev", "GM": "auto_ev",
    # Gaming
    "NFLX": "gaming",  # streaming-as-entertainment
    # Mass-market biotech / GLP-1
    "NVO": "biotech_consumer", "LLY": "biotech_consumer",
    # Aerospace consumer-facing
    "RKLB": "aerospace_consumer", "SPCE": "aerospace_consumer",
    "JOBY": "aerospace_consumer", "ACHR": "aerospace_consumer",
    "ASTS": "aerospace_consumer", "BA": "aerospace_consumer",
    # Quantum
    "IONQ": "quantum", "RGTI": "quantum", "QBTS": "quantum", "QUBT": "quantum",
    # Robotics
    "ISRG": "robotics", "SYM": "robotics",
}


# ── Result dataclass ────────────────────────────────────────────────────────

@dataclass
class CommunityScoreResult:
    ticker:    str
    score:     int = 0          # normalized 0-100
    raw_score: int = 0          # raw -30 to +60
    breakdown: dict[str, int] = field(default_factory=dict)
    notes:     list[str] = field(default_factory=list)
    sentiment_summary: str = "NEUTRAL"  # combined yt+reddit
    has_data:  bool = False     # False if both reddit + youtube failed

    def __str__(self):
        bar = "█" * (self.score // 5) + "░" * (20 - self.score // 5)
        lines = [
            f"{self.ticker} COMMUNITY {self.score}/100  ({self.sentiment_summary})",
            f"  {bar}",
        ]
        for k, v in self.breakdown.items():
            sign = "+" if v >= 0 else ""
            lines.append(f"  {k}: {sign}{v}")
        for n in self.notes:
            lines.append(f"  · {n}")
        return "\n".join(lines)


# ── Factor scorers ──────────────────────────────────────────────────────────

def _score_tech_creator(yt_signal: Optional[dict]) -> tuple[int, str]:
    """Tier_a video → +30, tier_b → +20, tier_c → +15, none → 0."""
    if not yt_signal or not yt_signal.get("has_data"):
        return 0, "no YT data"
    tech_videos = yt_signal.get("tech_creator_videos", [])
    if not tech_videos:
        return 0, "no tech-creator coverage"
    tiers = [v.get("tier", "") for v in tech_videos]
    if "tier_a" in tiers:
        return 30, f"tier_a: {[v['channel'] for v in tech_videos if v.get('tier')=='tier_a'][:2]}"
    if "tier_b" in tiers:
        return 20, f"tier_b: {[v['channel'] for v in tech_videos if v.get('tier')=='tier_b'][:2]}"
    if "tier_c" in tiers:
        return 15, f"tier_c: {[v['channel'] for v in tech_videos if v.get('tier')=='tier_c'][:2]}"
    return 0, "tech-creator videos but no tier match"


def _score_general_youtube(yt_signal: Optional[dict]) -> tuple[int, str]:
    """0..+20 based on volume + sentiment of general YT coverage."""
    if not yt_signal or not yt_signal.get("has_data"):
        return 0, "no YT data"
    total = yt_signal.get("total_videos", 0)
    sent  = yt_signal.get("sentiment", "NEUTRAL")
    if sent == "BEARISH":
        return 0, f"general YT BEARISH ({total} videos)"
    if total >= 10 and sent == "BULLISH":
        return 20, f"strong YT volume + BULLISH ({total} videos)"
    if total >= 5 and sent == "BULLISH":
        return 10, f"moderate YT volume + BULLISH ({total} videos)"
    return 0, f"low YT volume or mixed ({total} videos, {sent})"


def _score_wsb_retail(reddit_signal: Optional[dict],
                      rsi: Optional[float]) -> tuple[int, str]:
    """Q2: WSB-fade with RSI gate.
    Top-5 mentions + BULLISH + RSI<50  → +10  (real awakening)
    Top-5 mentions + BULLISH + RSI 50-70 → 0  (mature)
    Top-5 mentions + BULLISH + RSI>70  → -20 (euphoric peak fade)
    Otherwise: 0."""
    if not reddit_signal or not reddit_signal.get("has_data"):
        return 0, "no Reddit data"
    rank = reddit_signal.get("rank_in_universe")
    sent = reddit_signal.get("sentiment", "NEUTRAL")
    mention_count = reddit_signal.get("mention_count", 0)

    if not rank or rank > 5 or sent != "BULLISH":
        return 0, f"WSB rank={rank} sent={sent} - no fade trigger"

    # Top-5 + bullish - RSI gate
    if rsi is None:
        return 0, f"WSB top-{rank} BULLISH but no RSI - gate skipped"
    if rsi < 50:
        return +10, f"WSB top-{rank} BULLISH + RSI {rsi:.0f}<50 → real awakening (+10)"
    if rsi <= 70:
        return 0, f"WSB top-{rank} BULLISH + RSI {rsi:.0f} → mature, neutral"
    return -20, f"WSB top-{rank} BULLISH + RSI {rsi:.0f}>70 → EUPHORIC PEAK, FADE (-20)"


def _score_absence_penalty(ticker: str, yt_signal: Optional[dict]) -> tuple[int, str]:
    """Q3: -10 penalty if community-eligible sector ticker has 0 tech-creator
    coverage in last 30d. Whitelist-gated."""
    sector = TICKER_SECTOR.get(ticker.upper())
    if sector not in COMMUNITY_ELIGIBLE_SECTORS:
        return 0, f"sector {sector!r} not community-eligible - penalty N/A"
    if not yt_signal or not yt_signal.get("has_data"):
        return 0, "YT fetch failed - cannot apply penalty"
    tech_videos = yt_signal.get("tech_creator_videos", [])
    if tech_videos:
        return 0, f"{sector} ticker has tech-creator coverage - no penalty"
    return -10, f"{sector} ticker, ZERO tech-creator coverage in 30d → -10 penalty"


# ── Combiner ────────────────────────────────────────────────────────────────

def _combined_sentiment(yt_signal: Optional[dict],
                        reddit_signal: Optional[dict]) -> str:
    """Combine yt + reddit sentiment. Mismatches → MIXED."""
    yt = (yt_signal or {}).get("sentiment", "NEUTRAL")
    rd = (reddit_signal or {}).get("sentiment", "NEUTRAL")
    if yt == rd:
        return yt
    if yt == "NEUTRAL":
        return rd
    if rd == "NEUTRAL":
        return yt
    return "MIXED"


def score_community(
    ticker: str,
    rsi: Optional[float] = None,
    reddit_signal: Optional[dict] = None,
    youtube_signal: Optional[dict] = None,
) -> CommunityScoreResult:
    """Compute community score for one ticker. Display-only per Q1."""
    result = CommunityScoreResult(ticker=ticker.upper())

    has_yt     = bool(youtube_signal and youtube_signal.get("has_data"))
    has_reddit = bool(reddit_signal and reddit_signal.get("has_data"))
    if not has_yt and not has_reddit:
        result.has_data = False
        result.notes.append("no community data fetched (both Reddit + YT failed)")
        return result

    result.has_data = True

    # 1. Tech-creator early signal
    pts, note = _score_tech_creator(youtube_signal)
    result.breakdown["YT tech-creator"] = pts
    result.notes.append(note)

    # 2. General YouTube coverage
    pts, note = _score_general_youtube(youtube_signal)
    result.breakdown["YT general"] = pts
    result.notes.append(note)

    # 3. WSB retail (RSI-gated)
    pts, note = _score_wsb_retail(reddit_signal, rsi)
    result.breakdown["WSB retail"] = pts
    result.notes.append(note)

    # 4. Absence penalty (whitelisted sectors only)
    pts, note = _score_absence_penalty(ticker, youtube_signal)
    result.breakdown["Tech-creator absence"] = pts
    result.notes.append(note)

    # Aggregate
    result.raw_score = sum(result.breakdown.values())
    # Normalize -30..+60 → 0..100
    result.score = max(0, min(100, round((result.raw_score + 30) / 90 * 100)))
    result.sentiment_summary = _combined_sentiment(youtube_signal, reddit_signal)

    return result


# ── Forward-log (per ROADMAP decision: 60d observation) ─────────────────────

def write_forward_log(ticker: str, score: int, raw_score: int,
                      breakdown: dict, price: Optional[float],
                      rsi: Optional[float]) -> None:
    """Append one row to data/community_cache/_forward_log.jsonl."""
    row = {
        "ticker":    ticker.upper(),
        "date":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "score":     score,
        "raw_score": raw_score,
        "breakdown": breakdown,
        "price":     round(price, 2) if price else None,
        "rsi":       round(rsi, 1) if rsi else None,
    }
    with open(FORWARD_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ── Public API: get_community_scores ────────────────────────────────────────

def get_community_scores(tickers: list[str], snapshots: Optional[dict] = None,
                         force_refresh: bool = False, verbose: bool = False,
                         log_forward: bool = True) -> dict[str, dict]:
    """Fetch + score all tickers. snapshots provides RSI for WSB-fade gate.
    Logs every score to forward log for 60d evaluation per design decision."""
    snapshots = snapshots or {}

    # Fetch signals - modules handle their own caching
    from community_reddit import get_reddit_signals
    from community_youtube import get_youtube_signals

    reddit_sigs = get_reddit_signals(tickers, force_refresh=force_refresh, verbose=verbose)
    yt_sigs     = get_youtube_signals(tickers, force_refresh=force_refresh, verbose=verbose)

    results = {}
    for t in tickers:
        snap = snapshots.get(t.upper(), {})
        rsi  = snap.get("rsi")
        price = snap.get("price")
        result = score_community(
            t,
            rsi=rsi,
            reddit_signal=reddit_sigs.get(t.upper()),
            youtube_signal=yt_sigs.get(t.upper()),
        )
        results[t.upper()] = asdict(result)
        if log_forward and result.has_data:
            write_forward_log(t, result.score, result.raw_score,
                              result.breakdown, price, rsi)
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python community_score.py TICKER [TICKER ...] [--refresh] [--no-log]")
        sys.exit(1)
    refresh = "--refresh" in sys.argv
    no_log = "--no-log" in sys.argv
    tickers = [a for a in sys.argv[1:] if not a.startswith("--")]

    # Pull RSI from yfinance via data_fetch
    from data_fetch import get_full_snapshot
    snapshots = {}
    for t in tickers:
        snap = get_full_snapshot(t)
        snapshots[t.upper()] = snap

    scores = get_community_scores(tickers, snapshots=snapshots,
                                  force_refresh=refresh, verbose=True,
                                  log_forward=not no_log)
    print()
    for t, s in sorted(scores.items(), key=lambda kv: kv[1]["score"], reverse=True):
        bar = "█" * (s["score"] // 5) + "░" * (20 - s["score"] // 5)
        print(f"  {t:<6} {s['score']:>3}/100  raw={s['raw_score']:>+3}  "
              f"{bar}  {s['sentiment_summary']}")
        for k, v in s["breakdown"].items():
            sign = "+" if v >= 0 else ""
            print(f"    {k}: {sign}{v}")
