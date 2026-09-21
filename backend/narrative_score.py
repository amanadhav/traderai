"""
narrative_score.py - Multi-signal narrative combiner (final layer).

Aggregates the lead-time-aware signal stack into one display surface:

  arXiv research        (12-24mo lead)  → innovation_score.py
  USPTO patents         (12-36mo lead)  → deferred v1.1
  Tech-creator YouTube  (3-6mo lead)    → community_score.py
  Insider buying        (1-3mo lead)    → existing insider.py
  Options flow          (1-7d lead)     → existing options_flow.py
  WSB retail            (0-7d, fade)    → community_score.py
  Macro narratives      (structural)    → score.py TICKER_NARRATIVES
  Price/RSI/MACD/BB     (lagging)       → score.py 180pt

v1 ships display-only. NARRATIVE_MODE pluggable per user directive
2026-05-09 - promotion to additive after 60d forward-log evaluation.

Per ROADMAP item #4:
  - SignalLayer schema locks contract before more sources added
  - Decay weighted by lead_time_months
  - Double-count detection: clustered timestamps → one event, not many

Public API:
    score_narrative(ticker, layers=None, snapshots=None) -> NarrativeScoreResult
    get_narrative_scores(tickers, snapshots=None) -> dict[ticker, dict]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE / "data" / "narrative_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
FORWARD_LOG = CACHE_DIR / "_forward_log.jsonl"


# ── v1 mode flags (per user directive 2026-05-09) ───────────────────────────
# Each sub-signal can be: "additive" | "display_only" | "gate" | "disabled"
# Default v1: all display_only. Promote individually after forward eval.
NARRATIVE_MODE   = "display_only"   # output of narrative_score itself
COMMUNITY_MODE   = "display_only"   # how community signal contributes
INNOVATION_MODE  = "display_only"   # how innovation signal contributes


# ── SignalLayer schema (locked) ──────────────────────────────────────────────

@dataclass
class SignalLayer:
    """One contributing signal in the narrative stack.

    Lock contract before adding more sources (avoid 130 vs 180 ceiling drift).
    """
    source:           str    # "arxiv" | "youtube" | "wsb" | "insider" | "options" | "macro"
    raw_score:        int    # 0..max_score
    max_score:        int    # cap (stays within sub-signal's domain)
    lead_time_months: float  # rough lead - used for decay weighting
    weight:           float  # post-decay weight in final aggregation [0..1]
    timestamp:        str    # ISO date when signal recorded
    evidence:         str    # one-line description for audit


@dataclass
class NarrativeScoreResult:
    ticker:    str
    score:     int = 0          # normalized 0-100
    raw_score: int = 0          # raw weighted sum
    max_raw:   int = 0          # max possible weighted sum
    layers:    list[dict] = field(default_factory=list)
    sentiment: str = "NEUTRAL"
    notes:     list[str] = field(default_factory=list)
    has_data:  bool = False

    def __str__(self):
        bar = "█" * (self.score // 5) + "░" * (20 - self.score // 5)
        lines = [
            f"{self.ticker} NARRATIVE {self.score}/100  ({self.sentiment})",
            f"  {bar}",
        ]
        for layer in self.layers:
            sign = "+"
            lines.append(f"  [{layer['source']:<10}] {sign}{layer['raw_score']}/{layer['max_score']} "
                         f"(lead {layer['lead_time_months']:.0f}mo, w={layer['weight']:.2f})")
            lines.append(f"    → {layer['evidence']}")
        return "\n".join(lines)


# ── Lead-time decay weighting ───────────────────────────────────────────────
# Longer lead = bigger weight, but capped - too much weight on noisy frontier
# signals would drown out actionable lagging signals.
# Half-life: 6 months. weight = 0.5^(now_age_months / 6) clipped [0.2, 1.0].

def _lead_time_weight(lead_time_months: float) -> float:
    """Newer signals get full weight. Decay tapered, floored at 0.2."""
    # For "lead time", treat as how-far-ahead-it-points-of-real-events.
    # Rather than time-decay, use a tier: structural=1.0, mid=0.7, near=0.5
    if lead_time_months >= 12:
        return 1.0
    if lead_time_months >= 3:
        return 0.7
    if lead_time_months >= 0.5:
        return 0.5
    return 0.3


def _double_count_check(layers: list[SignalLayer]) -> list[str]:
    """Detect timestamp clustering - if 3+ signals fire within 7 days they
    likely all reflect the same event, not 3 independent confirmations.
    Returns list of warning notes."""
    warnings = []
    dates = sorted((l.timestamp[:10] for l in layers if l.timestamp))
    if len(dates) >= 3:
        # Check if any 3 dates fall within 7-day window
        from datetime import datetime as _dt
        try:
            parsed = [_dt.fromisoformat(d) for d in dates]
            for i in range(len(parsed) - 2):
                window = (parsed[i + 2] - parsed[i]).days
                if window <= 7:
                    warnings.append(
                        f"3+ signals clustered within 7d ({dates[i]}..{dates[i+2]}) - "
                        f"may be same event echoed across layers"
                    )
                    break
        except Exception:
            pass
    return warnings


# ── Builders for each source ────────────────────────────────────────────────

def _layer_from_innovation(innov: dict, today: str) -> Optional[SignalLayer]:
    if not innov or not innov.get("has_data"):
        return None
    return SignalLayer(
        source="arxiv",
        raw_score=innov.get("score", 0),
        max_score=100,
        lead_time_months=18.0,
        weight=_lead_time_weight(18.0),
        timestamp=today,
        evidence=f"{innov.get('paper_count', 0)} papers, "
                 f"cats={innov.get('categories', [])[:3]}",
    )


def _layer_from_community(comm: dict, today: str) -> list[SignalLayer]:
    """Community has TWO sub-signals: tech-creator (mid lead) and WSB (near lead)."""
    if not comm or not comm.get("has_data"):
        return []
    layers = []
    breakdown = comm.get("breakdown", {})
    # Tech-creator
    yt = breakdown.get("YT tech-creator", 0) + breakdown.get("YT general", 0)
    layers.append(SignalLayer(
        source="youtube",
        raw_score=max(0, yt),
        max_score=50,
        lead_time_months=4.5,
        weight=_lead_time_weight(4.5),
        timestamp=today,
        evidence=f"YT tech={breakdown.get('YT tech-creator',0)} gen={breakdown.get('YT general',0)}",
    ))
    # WSB retail (can be negative - fade signal)
    wsb = breakdown.get("WSB retail", 0)
    layers.append(SignalLayer(
        source="wsb",
        raw_score=wsb,           # may be negative - fade signal
        max_score=10,
        lead_time_months=0.25,
        weight=_lead_time_weight(0.25),
        timestamp=today,
        evidence=f"WSB sentiment={comm.get('sentiment_summary', 'NEUTRAL')}, "
                 f"raw={wsb}",
    ))
    return layers


def _layer_from_insider(insider: dict, today: str) -> Optional[SignalLayer]:
    if not insider or not insider.get("has_signal"):
        return None
    sig = insider.get("signal", "")
    score_map = {"STRONG": 100, "CLUSTER": 75, "NOTABLE": 50}
    return SignalLayer(
        source="insider",
        raw_score=score_map.get(sig, 0),
        max_score=100,
        lead_time_months=2.0,
        weight=_lead_time_weight(2.0),
        timestamp=today,
        evidence=f"insider {sig}: {insider.get('description', '')[:80]}",
    )


def _layer_from_options(opt_flow: dict, today: str) -> Optional[SignalLayer]:
    if not opt_flow or not opt_flow.get("signal"):
        return None
    sig = opt_flow.get("signal", "")
    score_map = {
        "BULLISH_FLOW":   75, "UNUSUAL_CALLS": 90,
        "BEARISH_FLOW":  -75, "UNUSUAL_PUTS": -90,
        "NEUTRAL":         0,
    }
    return SignalLayer(
        source="options",
        raw_score=score_map.get(sig, 0),
        max_score=100,
        lead_time_months=0.25,
        weight=_lead_time_weight(0.25),
        timestamp=today,
        evidence=f"options {sig}, P/C vol={opt_flow.get('pcr_vol', 'n/a')}",
    )


# ── Combiner ────────────────────────────────────────────────────────────────

def score_narrative(
    ticker: str,
    innovation_signal: Optional[dict] = None,
    community_signal: Optional[dict] = None,
    insider_signal: Optional[dict] = None,
    options_signal: Optional[dict] = None,
) -> NarrativeScoreResult:
    """Combine all narrative-layer signals into one display score."""
    result = NarrativeScoreResult(ticker=ticker.upper())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    layers: list[SignalLayer] = []

    if INNOVATION_MODE != "disabled":
        l = _layer_from_innovation(innovation_signal, today)
        if l:
            layers.append(l)

    if COMMUNITY_MODE != "disabled":
        layers.extend(_layer_from_community(community_signal, today))

    # Insider + options always considered (they're proven signals,
    # not subject to forward-log evaluation)
    insider_layer = _layer_from_insider(insider_signal, today)
    if insider_layer:
        layers.append(insider_layer)
    options_layer = _layer_from_options(options_signal, today)
    if options_layer:
        layers.append(options_layer)

    if not layers:
        result.notes.append("no signal layers available - narrative empty")
        return result

    result.has_data = True

    # Weighted aggregation. Each layer contributes:
    #   weighted_score = (raw_score / max_score) * weight
    # Sum and renormalize to 0-100.
    weighted_sum, weight_sum = 0.0, 0.0
    for l in layers:
        norm = l.raw_score / l.max_score if l.max_score else 0
        weighted_sum += norm * l.weight
        weight_sum   += l.weight
    if weight_sum > 0:
        result.score = max(0, min(100, round((weighted_sum / weight_sum) * 100)))

    # Determine sentiment from layer mix
    bullish = sum(1 for l in layers if l.raw_score > l.max_score * 0.5)
    bearish = sum(1 for l in layers if l.raw_score < 0)
    if bearish >= 2:
        result.sentiment = "BEARISH"
    elif bullish >= 2:
        result.sentiment = "BULLISH"
    elif bullish == 1 and bearish == 0:
        result.sentiment = "BULLISH"
    elif bearish == 1 and bullish == 0:
        result.sentiment = "BEARISH"
    else:
        result.sentiment = "MIXED" if (bullish + bearish > 0) else "NEUTRAL"

    # Double-count check
    result.notes.extend(_double_count_check(layers))

    result.layers = [asdict(l) for l in layers]
    result.raw_score = sum(l.raw_score * l.weight for l in layers)
    result.max_raw   = sum(l.max_score * l.weight for l in layers)
    return result


# ── Forward log ─────────────────────────────────────────────────────────────

def write_forward_log(ticker: str, score: int, sentiment: str,
                      layer_count: int, price: Optional[float]) -> None:
    row = {
        "ticker":      ticker.upper(),
        "date":        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "score":       score,
        "sentiment":   sentiment,
        "layer_count": layer_count,
        "price":       round(price, 2) if price else None,
    }
    with open(FORWARD_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ── Public API: get_narrative_scores ────────────────────────────────────────

def get_narrative_scores(tickers: list[str], snapshots: Optional[dict] = None,
                         force_refresh: bool = False, verbose: bool = False,
                         log_forward: bool = True) -> dict[str, dict]:
    """Pull from all sources, build narrative score per ticker."""
    snapshots = snapshots or {}
    if NARRATIVE_MODE == "disabled":
        return {}

    # Pull each sub-signal - modules handle their own caching
    from innovation_score import get_innovation_scores
    from community_score  import get_community_scores

    inn_sigs = get_innovation_scores(tickers, snapshots=snapshots,
                                     force_refresh=force_refresh,
                                     verbose=verbose, log_forward=False)
    com_sigs = get_community_scores(tickers, snapshots=snapshots,
                                    force_refresh=force_refresh,
                                    verbose=verbose, log_forward=False)

    # Insider + options - try to load from cache, don't refetch (heavy)
    insider_sigs = {}
    options_sigs = {}
    try:
        from insider import get_insider_signals
        insider_sigs = get_insider_signals(tickers, force_refresh=False, verbose=False)
    except Exception:
        pass
    try:
        from options_flow import get_options_flows
        options_sigs = get_options_flows(tickers, force_refresh=False, verbose=False)
    except Exception:
        pass

    results = {}
    for t in tickers:
        result = score_narrative(
            t,
            innovation_signal=inn_sigs.get(t.upper()),
            community_signal=com_sigs.get(t.upper()),
            insider_signal=insider_sigs.get(t.upper()),
            options_signal=options_sigs.get(t.upper()),
        )
        results[t.upper()] = asdict(result)
        if log_forward and result.has_data:
            price = (snapshots.get(t.upper()) or {}).get("price")
            write_forward_log(t, result.score, result.sentiment,
                              len(result.layers), price)
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python narrative_score.py TICKER [...] [--refresh] [--no-log]")
        sys.exit(1)
    refresh = "--refresh" in sys.argv
    no_log = "--no-log" in sys.argv
    tickers = [a for a in sys.argv[1:] if not a.startswith("--")]

    from data_fetch import get_full_snapshot
    snaps = {t.upper(): get_full_snapshot(t) for t in tickers}

    scores = get_narrative_scores(tickers, snapshots=snaps,
                                   force_refresh=refresh, verbose=True,
                                   log_forward=not no_log)
    print()
    for t, s in sorted(scores.items(), key=lambda kv: kv[1]["score"], reverse=True):
        if not s["has_data"]:
            print(f"  {t:<6} -  no narrative layers")
            continue
        bar = "█" * (s["score"] // 5) + "░" * (20 - s["score"] // 5)
        print(f"  {t:<6} {s['score']:>3}/100  {s['sentiment']:<8}  {bar}  "
              f"layers={len(s['layers'])}")
        for l in s["layers"]:
            print(f"    [{l['source']:<10}] {l['raw_score']}/{l['max_score']} "
                  f"(lead {l['lead_time_months']:.0f}mo, w={l['weight']:.2f}) - {l['evidence'][:80]}")
        for note in s["notes"]:
            print(f"    ⚠  {note}")
