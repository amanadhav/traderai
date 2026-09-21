#!/usr/bin/env python
"""
ml_calibrate.py - Learn score thresholds from backtest evidence.

Reads backtest_results.json (written by `python backtest.py --save`) and:
  1. Fits a logistic regression of win probability vs entry score
     (pure numpy - no sklearn dependency).
  2. Sweeps entry thresholds and reports n / win rate / avg + median alpha.
  3. Recommends the threshold that maximizes median alpha with n >= MIN_N.

Usage:
    python backtest.py --full --lookback 730 --hold 60 --save   # produce data
    python ml_calibrate.py                                      # analyze
    python ml_calibrate.py --apply       # write recommendation to user_config
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "backtest_results.json"

MIN_N = 30  # minimum sample size for a threshold to be trusted

# The backtester scores on a technical-only subset (max 110); the live scorer
# runs the full 180-point model. Same mapping as backtest._live_equiv.
TECH_MAX_PTS = 110
LIVE_MAX_PTS = 180


def to_live_scale(tech_score: int) -> int:
    return int(tech_score / TECH_MAX_PTS * LIVE_MAX_PTS)


def load_entries() -> list[dict]:
    if not RESULTS.exists():
        sys.exit("backtest_results.json missing - run: python backtest.py --full --save")
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    entries = [e for e in data.get("all_entries", [])
               if e.get("tech_score") is not None and e.get("alpha") is not None]
    if len(entries) < MIN_N:
        sys.exit(f"only {len(entries)} usable entries - need >= {MIN_N}")
    return entries


def fit_logistic(scores: np.ndarray, wins: np.ndarray,
                 lr: float = 0.1, epochs: int = 5000) -> tuple[float, float]:
    """Logistic regression win ~ score via gradient descent on normalized x."""
    mu, sd = scores.mean(), scores.std() or 1.0
    x = (scores - mu) / sd
    w, b = 0.0, 0.0
    n = len(x)
    for _ in range(epochs):
        p = 1.0 / (1.0 + np.exp(-(w * x + b)))
        grad_w = ((p - wins) * x).mean()
        grad_b = (p - wins).mean()
        w -= lr * grad_w
        b -= lr * grad_b
    # return in raw-score space: p(win) = sigmoid(w/sd * score + (b - w*mu/sd))
    return w / sd, b - w * mu / sd


def win_prob(score: float, w: float, b: float) -> float:
    return float(1.0 / (1.0 + np.exp(-(w * score + b))))


def sweep(entries: list[dict], thresholds: list[int]) -> list[dict]:
    rows = []
    for th in thresholds:
        sel = [e for e in entries if e["tech_score"] >= th]
        if not sel:
            continue
        alphas = [e["alpha"] for e in sel]
        rows.append({
            "threshold": th,
            "n": len(sel),
            "win_rate": round(100 * sum(1 for e in sel if e.get("win")) / len(sel), 1),
            "avg_alpha": round(statistics.mean(alphas), 2),
            "median_alpha": round(statistics.median(alphas), 2),
        })
    return rows


def walk_forward(entries: list[dict]) -> dict:
    """
    Guard against in-sample overfitting (López de Prado): pick the threshold
    on the first 70% of entries by date, then report how that SAME threshold
    performed on the held-out final 30%. If train and test disagree wildly,
    the threshold is curve-fit, not edge.
    """
    ordered = sorted(entries, key=lambda e: e["entry_date"])
    split = int(len(ordered) * 0.7)
    train, test = ordered[:split], ordered[split:]
    if len(train) < MIN_N or len(test) < 10:
        return {"available": False, "reason": "not enough entries for a split"}

    train_rows = [r for r in sweep(train, [30, 40, 50, 60, 70]) if r["n"] >= MIN_N]
    if not train_rows:
        return {"available": False, "reason": "no trusted threshold in train set"}
    best = max(train_rows, key=lambda r: r["median_alpha"])
    th = best["threshold"]

    test_sel = [e for e in test if e["tech_score"] >= th]
    test_alphas = [e["alpha"] for e in test_sel]
    return {
        "available": True,
        "train_n": len(train), "test_n": len(test),
        "split_date": test[0]["entry_date"][:10],
        "threshold": th,
        "train_median_alpha": best["median_alpha"],
        "test_median_alpha": round(statistics.median(test_alphas), 2) if test_alphas else None,
        "test_n_at_threshold": len(test_sel),
        "test_win_rate": round(100 * sum(1 for e in test_sel if e.get("win")) / len(test_sel), 1)
                         if test_sel else None,
    }


def regime_report(entries: list[dict], threshold: int) -> list[dict]:
    """Alpha by market regime: was the edge real in BOTH bull and bear tape?
    Regime = SPY above/below its 200-day MA on the entry date."""
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY").history(period="3y", interval="1d")["Close"]
        ma200 = spy.rolling(200).mean()
        regime_by_day = {
            d.strftime("%Y-%m-%d"): ("bull" if c > m else "bear")
            for d, c, m in zip(spy.index, spy, ma200) if m == m
        }
    except Exception:
        return []

    buckets: dict[str, list[float]] = {"bull": [], "bear": []}
    for e in entries:
        if e["tech_score"] < threshold:
            continue
        regime = regime_by_day.get(e["entry_date"][:10])
        if regime:
            buckets[regime].append(e["alpha"])
    rows = []
    for regime, alphas in buckets.items():
        if alphas:
            rows.append({
                "regime": f"SPY {'above' if regime == 'bull' else 'below'} 200MA",
                "n": len(alphas),
                "median_alpha": round(statistics.median(alphas), 2),
                "avg_alpha": round(statistics.mean(alphas), 2),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the recommended entry threshold to user_config.json")
    args = ap.parse_args()

    entries = load_entries()
    scores = np.array([float(e["tech_score"]) for e in entries])
    wins = np.array([1.0 if e.get("win") else 0.0 for e in entries])

    w, b = fit_logistic(scores, wins)
    print(f"Entries: {len(entries)}  |  score range {scores.min():.0f}-{scores.max():.0f}")
    print(f"\nLogistic fit  p(win) vs score  (w={w:.4f}, b={b:.3f}):")
    for s in (30, 50, 70, 90, 110, 130):
        print(f"  score {s:>3} → p(win) {win_prob(s, w, b):.1%}")

    rows = sweep(entries, [20, 30, 40, 50, 60, 70, 80, 90, 100, 110])
    print(f"\n{'thresh':>6} {'n':>5} {'win%':>6} {'avg α':>7} {'med α':>7}")
    for r in rows:
        print(f"{r['threshold']:>6} {r['n']:>5} {r['win_rate']:>6} {r['avg_alpha']:>7} {r['median_alpha']:>7}")

    trusted = [r for r in rows if r["n"] >= MIN_N]
    if not trusted:
        print("\nNo threshold has enough samples - run a longer/wider backtest.")
        return
    best = max(trusted, key=lambda r: r["median_alpha"])
    live = to_live_scale(best["threshold"])
    print(f"\nRecommended entry threshold: {best['threshold']}/{TECH_MAX_PTS} tech "
          f"= ~{live}/{LIVE_MAX_PTS} live "
          f"(median alpha {best['median_alpha']}%, n={best['n']})")

    wf = walk_forward(entries)
    if wf.get("available"):
        print(f"\nWalk-forward check (train->test split at {wf['split_date']}):")
        print(f"  threshold {wf['threshold']} picked on {wf['train_n']} train entries "
              f"(median alpha {wf['train_median_alpha']}%)")
        print(f"  held-out test: median alpha {wf['test_median_alpha']}% | "
              f"win rate {wf['test_win_rate']}% | n={wf['test_n_at_threshold']}")
        if wf["test_median_alpha"] is not None and wf["test_median_alpha"] < 0 <= wf["train_median_alpha"]:
            print("  WARNING: threshold works in-sample but FAILS out-of-sample - treat as curve-fit")
    else:
        print(f"\nWalk-forward: {wf.get('reason')}")

    regimes = regime_report(entries, best["threshold"])
    if regimes:
        print(f"\nRegime robustness at threshold >={best['threshold']}:")
        for r in regimes:
            print(f"  {r['regime']:<18} n={r['n']:<4} median alpha {r['median_alpha']}% "
                  f"| avg {r['avg_alpha']}%")

    if args.apply:
        import user_config
        user_config.save_config({"rules": {"score_entry_threshold": live}})
        print(f"Applied: score_entry_threshold = {live} (live 180-pt scale) → user_config.json")


if __name__ == "__main__":
    main()
