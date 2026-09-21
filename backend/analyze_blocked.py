#!/usr/bin/env python3
"""
analyze_blocked.py - Test the falling-knife guard hypothesis.

Question: is the guard filtering winners along with losers, or genuinely catching falling knives?

Method:
  Load backtest_results.json
  Re-derive guard_pass for each entry (deterministic from ticker + tech_score)
  Split entries with tech_score >= 50 (where guard fires) into:
    - BLOCKED: tech>=50 AND no macro narrative match
    - PASSED:  tech>=50 AND macro narrative match
  Compare forward alpha distributions.
  Bootstrap CI on the difference of medians.

Verdict:
  If BLOCKED group median alpha > 0 → guard removes winners → DO NOT SHIP
  If BLOCKED group median alpha < 0 → guard removes losers → SHIP
  If overlapping CI → inconclusive, sample too small for confidence
"""

import json
import sys
from collections import Counter
from pathlib import Path
import numpy as np

# Reuse guard logic from backtest.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import passes_falling_knife_guard
from score   import TICKER_NARRATIVES, ACTIVE_NARRATIVES


def median_ci(samples: list[float], n_boot: int = 5000, ci: float = 0.95) -> tuple[float, float, float]:
    """Bootstrap CI for median. Returns (median, lo, hi)."""
    if len(samples) < 5:
        m = float(np.median(samples)) if samples else 0.0
        return m, m, m
    arr = np.array(samples)
    rng = np.random.default_rng(42)
    boots = [float(np.median(rng.choice(arr, size=len(arr), replace=True))) for _ in range(n_boot)]
    boots.sort()
    lo = boots[int(n_boot * (1 - ci) / 2)]
    hi = boots[int(n_boot * (1 + ci) / 2)]
    return float(np.median(arr)), lo, hi


def summary(samples: list[float]) -> dict:
    if not samples:
        return {"n": 0, "median": 0, "mean": 0, "win_rate": 0, "ci_lo": 0, "ci_hi": 0}
    arr = np.array(samples)
    med, lo, hi = median_ci(samples)
    return {
        "n":        len(samples),
        "median":   round(med, 3),
        "ci_lo":    round(lo, 3),
        "ci_hi":    round(hi, 3),
        "mean":     round(float(arr.mean()), 3),
        "win_rate": round(float((arr > 0).mean()) * 100, 1),
    }


def main():
    path = Path(__file__).resolve().parents[1] / "backtest_results.json"
    if not path.exists():
        print("ERROR: backtest_results.json missing. Run: python3 backtest.py --full --lookback 730 --hold 60 --save")
        sys.exit(1)

    data = json.load(open(path, encoding="utf-8"))
    hold_days = data["hold_days"]
    entries   = data["all_entries"]

    print(f"\n{'━'*72}")
    print(f"  BLOCKED-ENTRY HYPOTHESIS TEST  ({hold_days}d hold, n={len(entries)})")
    print(f"{'━'*72}")
    print("  Loaded TICKER_NARRATIVES coverage:")
    print(f"    {len(TICKER_NARRATIVES)} tickers in narrative dict")
    print(f"    {len(ACTIVE_NARRATIVES)} active narratives")
    print()

    # Group by tech tier (guard only fires at tech>=50)
    for tier_floor in [30, 50, 65]:
        tier_entries = [e for e in entries if e["tech_score"] >= tier_floor and e["alpha"] is not None]
        if not tier_entries:
            continue

        blocked = [e for e in tier_entries if not passes_falling_knife_guard(e["ticker"], e["tech_score"])]
        passed  = [e for e in tier_entries if     passes_falling_knife_guard(e["ticker"], e["tech_score"])]

        b_alphas = [e["alpha"] for e in blocked]
        p_alphas = [e["alpha"] for e in passed]
        b_stats  = summary(b_alphas)
        p_stats  = summary(p_alphas)

        print(f"  ━━━ Tier ≥{tier_floor}/110  (n={len(tier_entries)}) ━━━")
        print(f"  {'Group':<12} {'N':>5} {'Median α':>10} {'95% CI':>20} {'Mean α':>10} {'Win%':>7}")
        print(f"  {'─'*12} {'─'*5} {'─'*10} {'─'*20} {'─'*10} {'─'*7}")
        if b_alphas:
            ci_str = f"[{b_stats['ci_lo']:+.2f}, {b_stats['ci_hi']:+.2f}]"
            verdict = ("WINNERS! ⚠"  if b_stats["median"] > 0.5 else
                       "losers ✓"     if b_stats["median"] < -0.5 else
                       "neutral")
            print(f"  {'BLOCKED':<12} {b_stats['n']:>5} {b_stats['median']:>+9.2f}% "
                  f"{ci_str:>20} {b_stats['mean']:>+9.2f}% {b_stats['win_rate']:>6.0f}%  "
                  f"← {verdict}")
        if p_alphas:
            ci_str = f"[{p_stats['ci_lo']:+.2f}, {p_stats['ci_hi']:+.2f}]"
            print(f"  {'PASSED':<12} {p_stats['n']:>5} {p_stats['median']:>+9.2f}% "
                  f"{ci_str:>20} {p_stats['mean']:>+9.2f}% {p_stats['win_rate']:>6.0f}%")

        # Difference of medians + CI overlap check
        if b_alphas and p_alphas:
            diff      = p_stats["median"] - b_stats["median"]
            overlap   = not (b_stats["ci_hi"] < p_stats["ci_lo"] or p_stats["ci_hi"] < b_stats["ci_lo"])
            print(f"  Δ median (P − B): {diff:+.2f}%  |  CI overlap: {'YES (inconclusive)' if overlap else 'NO (significant)'}")
        print()

    # Hypothesis verdict - focus on tier ≥50 (where guard actually fires)
    print(f"  {'─'*72}")
    print("  HYPOTHESIS TEST: 'guard filters winners due to coverage gaps'")
    print(f"  {'─'*72}")
    tier50 = [e for e in entries if e["tech_score"] >= 50 and e["alpha"] is not None]
    blocked = [e for e in tier50 if not passes_falling_knife_guard(e["ticker"], e["tech_score"])]
    if not blocked:
        print("  No blocked entries at tech>=50. Cannot test.")
        return
    b_alphas = [e["alpha"] for e in blocked]
    b_stats  = summary(b_alphas)

    print(f"  Blocked entries (tech>=50, no narrative): n={b_stats['n']}")
    print(f"    Median forward alpha: {b_stats['median']:+.2f}%  CI [{b_stats['ci_lo']:+.2f}, {b_stats['ci_hi']:+.2f}]")
    print(f"    Mean forward alpha:   {b_stats['mean']:+.2f}%")
    print(f"    Win rate vs SPY:      {b_stats['win_rate']:.0f}%")
    print()

    if b_stats["ci_hi"] < 0:
        print("  ✓ VERDICT: blocked entries are losers (CI fully below 0). Guard is doing its job. SHIP.")
    elif b_stats["ci_lo"] > 0:
        print("  ✗ VERDICT: blocked entries are winners (CI fully above 0). Guard filters winners. DO NOT SHIP.")
    else:
        print("  ⚠ VERDICT: inconclusive (CI straddles 0).")
        if b_stats["median"] > 0:
            print(f"    Median is {b_stats['median']:+.2f}% (positive) - leans toward filtering winners.")
            print( "    Recommendation: soften guard from hard-cap-at-60 to -10pt penalty.")
        else:
            print(f"    Median is {b_stats['median']:+.2f}% (negative) - leans toward catching losers.")
            print( "    Recommendation: ship guard as-is, accept inconclusive backtest signal.")

    # ── Soft guard tier-impact reanalysis ──────────────────────────────────
    print(f"\n  {'─'*72}")
    print("  SOFT GUARD (-10pt penalty) - TIER IMPACT")
    print(f"  {'─'*72}")
    print(f"  {'Tier':<14} {'Raw N':>7} {'Soft N':>7} {'Med α raw':>11} {'Med α soft':>12} {'Δ':>9}")
    print(f"  {'─'*14} {'─'*7} {'─'*7} {'─'*11} {'─'*12} {'─'*9}")

    for thresh in [30, 50, 65, 80]:
        raw_subset = [e for e in entries
                      if e["tech_score"] >= thresh and e["alpha"] is not None]
        # Apply -10 penalty to entries that fail guard
        soft_subset = [e for e in entries if e["alpha"] is not None
                       and (e["tech_score"]
                            - (10 if not passes_falling_knife_guard(e["ticker"], e["tech_score"])
                               else 0)) >= thresh]
        if not raw_subset:
            continue
        raw_med  = float(np.median([e["alpha"] for e in raw_subset])) if raw_subset else 0
        soft_med = float(np.median([e["alpha"] for e in soft_subset])) if soft_subset else 0
        delta    = soft_med - raw_med
        arrow    = "↑" if delta > 0.1 else ("↓" if delta < -0.1 else "·")
        print(f"  ≥{thresh}/110{'':<7} {len(raw_subset):>7} {len(soft_subset):>7}  "
              f"{raw_med:>+9.2f}%  {soft_med:>+10.2f}%  {delta:>+7.2f}% {arrow}")
    print()

    # Most-blocked tickers
    print()
    print(f"  {'─'*72}")
    print("  TICKERS MOST FREQUENTLY BLOCKED")
    print(f"  {'─'*72}")
    blocked_tickers = Counter(e["ticker"] for e in blocked)
    for ticker, count in blocked_tickers.most_common(15):
        ticker_blocks = [e for e in blocked if e["ticker"] == ticker]
        med_alpha = float(np.median([e["alpha"] for e in ticker_blocks]))
        in_dict   = "in_dict" if ticker.upper() in TICKER_NARRATIVES else "MISSING"
        marker    = " ⚠ winner" if med_alpha > 1 else " ✓ loser" if med_alpha < -1 else ""
        print(f"    {ticker:<8} blocked {count}x  median α {med_alpha:+.2f}%  ({in_dict}){marker}")
    print()


if __name__ == "__main__":
    main()
