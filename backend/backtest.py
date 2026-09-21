#!/usr/bin/env python3
"""
backtest.py - Historical threshold validation for the 180-pt scoring system.

Reconstructs 7 technical factors from OHLCV history (110pt max out of 180):
  RSI(25) + MACD(20) + BB%(20) + Volume(10) + RelStr(10) + Below200MA(10) + 52Wlow(5)

Cannot reconstruct historically:
  Upside(20), Div(10), FCF(10), Macro(10), Analyst(5), Short(5), Insider(10) = 70pts skipped

For each ticker × each eligible trading day:
  - Compute tech score using only OHLCV-derivable signals
  - If score >= entry threshold AND no re-entry within cooldown: record entry
  - Measure return at hold_days later vs SPY baseline
  - Report win_rate / avg_alpha / avg_return / n_entries per threshold tier

Usage:
    python3 backtest.py                          # positions + watchlist, 365d lookback, 30d hold
    python3 backtest.py --tickers NVDA AMD CRM   # specific tickers only
    python3 backtest.py --hold 60                # 60-day hold period
    python3 backtest.py --hold 30 60             # test multiple hold periods
    python3 backtest.py --lookback 730           # 2-year lookback
    python3 backtest.py --full                   # all scan universe tickers (~350)
    python3 backtest.py --save                   # write results to backtest_results.json
    python3 backtest.py --quiet                  # skip per-ticker detail, summary only
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands

# Reuse narrative lookup from live system (only fundamental factor
# reconstructible historically - narrative dicts are static config).
# get_narratives combines TICKER_NARRATIVES (explicit) + SECTOR_NARRATIVES.
try:
    from score import TICKER_NARRATIVES, ACTIVE_NARRATIVES, get_narratives  # type: ignore
except Exception:
    TICKER_NARRATIVES, ACTIVE_NARRATIVES = {}, set()
    def get_narratives(ticker, sector="", industry=""):  # type: ignore
        return TICKER_NARRATIVES.get(ticker.upper(), [])

# Cache yfinance industry/sector per ticker (one fetch per backtest run)
_industry_cache: dict[str, tuple[str, str]] = {}

def _get_sector_industry(ticker: str) -> tuple[str, str]:
    if ticker in _industry_cache:
        return _industry_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        sector   = info.get("sector", "") or ""
        industry = info.get("industry", "") or ""
    except Exception:
        sector, industry = "", ""
    _industry_cache[ticker] = (sector, industry)
    return sector, industry

warnings.filterwarnings("ignore")

# ── Constants ─────────────────────────────────────────────────────────────────

TECH_MAX_PTS   = 110   # max achievable from reconstructible factors
LIVE_MAX_PTS   = 180   # full live score max
MIN_HISTORY    = 260   # trading days needed before first scored entry (200MA + 52W)
COOLDOWN_DAYS  = 30    # re-entry cooldown per ticker after a signal fires
DATA_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest_cache"
DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Default universe ──────────────────────────────────────────────────────────

POSITIONS_UNIVERSE = [
    # ROTH positions
    "BJ", "CRM", "EPD", "GLD", "MDT", "MP", "NKE", "NOC", "RTX",
    # TOD positions
    "AAPL", "AMD", "AMZN", "ASML", "BBAI", "GOOGL", "META", "MSFT",
    "NFLX", "NVDA", "NVO", "TSM", "HII",
    # Active watchlist
    "DHR", "ABT", "SYK", "LDOS",
    # Benchmark
    "SPY",
]

# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BacktestEntry:
    ticker:       str
    entry_date:   date
    entry_price:  float
    tech_score:   int
    breakdown:    dict = field(default_factory=dict)
    hold_days:    int  = 30
    exit_date:    Optional[date]  = None
    exit_price:   Optional[float] = None
    return_pct:   Optional[float] = None
    spy_return:   Optional[float] = None
    alpha:        Optional[float] = None
    win:          Optional[bool]  = None
    guard_pass:   bool  = True   # True = passes falling-knife guard


def passes_falling_knife_guard(ticker: str, tech_score: int) -> bool:
    """
    Mirror of score.py guard. Uses combined narrative lookup
    (TICKER_NARRATIVES explicit + SECTOR_NARRATIVES sector-default).
    Pass if tech<50 OR ticker has active macro narrative match.
    """
    if tech_score < 50:
        return True
    sector, industry = _get_sector_industry(ticker)
    narratives = get_narratives(ticker, sector=sector, industry=industry)
    return any(n in ACTIVE_NARRATIVES for n in narratives)

@dataclass
class TierResult:
    threshold:    int
    hold_days:    int
    n_entries:    int
    win_rate:     float
    avg_return:   float
    avg_alpha:    float
    median_alpha: float
    best_alpha:   float
    worst_alpha:  float

# ── Score computation from OHLCV ─────────────────────────────────────────────

def compute_tech_score(
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    idx: int,
) -> tuple[int, dict]:
    """
    Compute reconstructible technical score at position `idx` in df.

    df must have columns: Open, High, Low, Close, Volume
    spy_df must be aligned (same index, pre-sliced to idx).
    Returns (score, breakdown_dict).
    """
    if idx < MIN_HISTORY:
        return 0, {}

    window = df.iloc[: idx + 1]
    close  = window["Close"]
    volume = window["Volume"]
    breakdown: dict[str, int] = {}

    # ── RSI (25pts) ──────────────────────────────────────────────────────────
    try:
        rsi_val = float(RSIIndicator(close, window=14).rsi().iloc[-1])
        if rsi_val < 30:
            pts = 25
        elif rsi_val < 40:
            pts = 15
        elif rsi_val < 50:
            pts = 5
        else:
            pts = 0
    except Exception:
        rsi_val, pts = 50.0, 0
    breakdown["RSI"] = pts

    # ── MACD (20pts) - crossover or improving histogram ─────────────────────
    try:
        macd_obj  = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        hist      = macd_obj.macd_diff().dropna()
        if len(hist) >= 4:
            h_now  = float(hist.iloc[-1])
            h_prev = float(hist.iloc[-2])
            h_3ago = float(hist.iloc[-4])
            crossover  = (h_prev < 0) and (h_now >= 0)
            improving  = (h_now > h_3ago) and (h_now > h_prev)
            if crossover:
                pts = 20
            elif improving:
                pts = 10
            else:
                pts = 0
        else:
            pts = 0
    except Exception:
        pts = 0
    breakdown["MACD"] = pts

    # ── Bollinger Band % (20pts) ─────────────────────────────────────────────
    try:
        bb   = BollingerBands(close, window=20, window_dev=2)
        high = float(bb.bollinger_hband().iloc[-1])
        low  = float(bb.bollinger_lband().iloc[-1])
        cur  = float(close.iloc[-1])
        if high != low:
            bb_pct = (cur - low) / (high - low) * 100
        else:
            bb_pct = 50.0
        if bb_pct < 20:
            pts = 20
        elif bb_pct < 40:
            pts = 10
        else:
            pts = 0
    except Exception:
        bb_pct, pts = 50.0, 0
    breakdown["BB%"] = pts

    # ── Volume confirmation (10pts) - elevated vol on down day ──────────────
    try:
        today_close = float(close.iloc[-1])
        prev_close  = float(close.iloc[-2])
        today_vol   = float(volume.iloc[-1])
        avg_vol     = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else float(volume.mean())
        pct_chg     = (today_close - prev_close) / prev_close * 100
        vol_ratio   = today_vol / avg_vol if avg_vol > 0 else 1.0
        if pct_chg < 0:
            if vol_ratio > 1.5:
                pts = 10
            elif vol_ratio >= 1.0:
                pts = 5
            else:
                pts = 0
        else:
            pts = 0
    except Exception:
        pts = 0
    breakdown["Volume"] = pts

    # ── Relative strength vs SPY (10pts) - 20d outperformance ───────────────
    try:
        spy_window = spy_df.iloc[: idx + 1]
        if len(spy_window) >= 21:
            ticker_ret = float(close.iloc[-1]) / float(close.iloc[-21]) - 1
            spy_ret    = float(spy_window["Close"].iloc[-1]) / float(spy_window["Close"].iloc[-21]) - 1
            rel        = (ticker_ret - spy_ret) * 100  # percentage points
            if rel > 5:
                pts = 10
            elif rel >= 0:
                pts = 5
            else:
                pts = 0
        else:
            pts = 0
    except Exception:
        pts = 0
    breakdown["Rel strength"] = pts

    # ── Below 200MA (10pts) ──────────────────────────────────────────────────
    try:
        ma200 = float(close.rolling(200).mean().iloc[-1])
        cur   = float(close.iloc[-1])
        pts   = 10 if (not np.isnan(ma200) and cur < ma200) else 0
    except Exception:
        pts = 0
    breakdown["Below 200MA"] = pts

    # ── Near 52W low (5pts) - within 10% of rolling 252-day low ─────────────
    try:
        low_252 = float(close.rolling(252).min().iloc[-1])
        cur     = float(close.iloc[-1])
        pct_from_low = (cur - low_252) / low_252 * 100 if low_252 > 0 else 100
        pts = 5 if pct_from_low < 10 else 0
    except Exception:
        pts = 0
    breakdown["52W low"] = pts

    score = sum(breakdown.values())
    return score, breakdown


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_ticker_data(ticker: str, lookback_days: int) -> Optional[pd.DataFrame]:
    """Download OHLCV. Needs lookback + MIN_HISTORY trading days of buffer."""
    extra_buffer = int((lookback_days + MIN_HISTORY) * 1.6)  # calendar days
    start = date.today() - timedelta(days=extra_buffer)

    cache_file = DATA_CACHE_DIR / f"{ticker}_{date.today().isoformat()}.csv"
    if cache_file.exists():
        try:
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if len(df) >= MIN_HISTORY + 30:
                return df
        except Exception:
            cache_file.unlink(missing_ok=True)

    try:
        df = yf.download(ticker, start=start.isoformat(), auto_adjust=True,
                         progress=False)
        if df is None or len(df) < MIN_HISTORY + 30:
            return None
        # Flatten multi-level columns (yfinance v0.2+)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.to_csv(cache_file)
        return df
    except Exception:
        return None


# ── Core backtest ─────────────────────────────────────────────────────────────

def run_backtest_for_ticker(
    ticker: str,
    ticker_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    lookback_days: int,
    hold_days: int,
) -> list[BacktestEntry]:
    """
    Scan every eligible trading day in lookback window.
    Fire on score threshold ≥ 1 (caller filters by threshold).
    Returns all entries with outcome measured.
    """
    entries: list[BacktestEntry] = []

    # Align spy_df to ticker_df dates
    shared_dates = ticker_df.index.intersection(spy_df.index)
    ticker_df = ticker_df.loc[shared_dates].copy()
    spy_df    = spy_df.loc[shared_dates].copy()

    total_rows  = len(ticker_df)
    cutoff_date = date.today() - timedelta(days=hold_days + 1)

    # Determine scan start: need MIN_HISTORY rows before first entry
    scan_start_idx = MIN_HISTORY
    # Also limit to lookback window
    lookback_start = date.today() - timedelta(days=int(lookback_days * 1.45))

    last_entry_idx = -999  # cooldown tracker

    for idx in range(scan_start_idx, total_rows):
        row_date = ticker_df.index[idx].date()

        # Only scan within lookback window
        if row_date < lookback_start:
            continue
        # Need hold_days of future data
        if row_date > cutoff_date:
            break
        # Enforce cooldown
        if idx - last_entry_idx < COOLDOWN_DAYS:
            continue

        score, breakdown = compute_tech_score(ticker_df, spy_df, idx)
        if score == 0:
            continue

        entry_price = float(ticker_df["Close"].iloc[idx])

        # Find exit
        exit_idx = idx + hold_days
        if exit_idx >= total_rows:
            continue
        exit_price = float(ticker_df["Close"].iloc[exit_idx])
        exit_date  = ticker_df.index[exit_idx].date()

        # SPY return same period
        spy_entry = float(spy_df["Close"].iloc[idx])
        spy_exit  = float(spy_df["Close"].iloc[exit_idx])
        spy_ret   = (spy_exit - spy_entry) / spy_entry * 100

        ret  = (exit_price - entry_price) / entry_price * 100
        alpha = ret - spy_ret

        entries.append(BacktestEntry(
            ticker      = ticker,
            entry_date  = row_date,
            entry_price = entry_price,
            tech_score  = score,
            breakdown   = breakdown,
            hold_days   = hold_days,
            exit_date   = exit_date,
            exit_price  = exit_price,
            return_pct  = round(ret, 3),
            spy_return  = round(spy_ret, 3),
            alpha       = round(alpha, 3),
            win         = ret > spy_ret,
            guard_pass  = passes_falling_knife_guard(ticker, score),
        ))
        last_entry_idx = idx

    return entries


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyze_by_threshold(
    all_entries: list[BacktestEntry],
    thresholds: tuple[int, ...],
    hold_days: int,
    guard_only: bool = False,
) -> list[TierResult]:
    """Group entries by score tier and compute statistics.
    guard_only=True filters to entries passing falling-knife guard.
    """
    results: list[TierResult] = []

    for thresh in sorted(thresholds):
        subset = [e for e in all_entries if e.tech_score >= thresh
                  and e.hold_days == hold_days
                  and e.alpha is not None
                  and (not guard_only or e.guard_pass)]
        if not subset:
            results.append(TierResult(thresh, hold_days, 0, 0, 0, 0, 0, 0, 0))
            continue

        returns = [e.return_pct for e in subset]
        alphas  = [e.alpha for e in subset]
        wins    = [e.win for e in subset]

        results.append(TierResult(
            threshold    = thresh,
            hold_days    = hold_days,
            n_entries    = len(subset),
            win_rate     = round(sum(wins) / len(wins) * 100, 1),
            avg_return   = round(float(np.mean(returns)), 2),
            avg_alpha    = round(float(np.mean(alphas)), 2),
            median_alpha = round(float(np.median(alphas)), 2),
            best_alpha   = round(float(np.max(alphas)), 2),
            worst_alpha  = round(float(np.min(alphas)), 2),
        ))
    return results


def compute_spy_baseline(spy_df: pd.DataFrame, hold_days: int, n_samples: int = 500) -> TierResult:
    """Random-entry baseline: pick N random dates, measure SPY hold_days return."""
    closes   = spy_df["Close"].values
    max_idx  = len(closes) - hold_days - 1
    if max_idx < 50:
        return TierResult(0, hold_days, 0, 0, 0, 0, 0, 0, 0)

    rng = np.random.default_rng(42)
    idxs = rng.integers(MIN_HISTORY, max_idx, size=min(n_samples, max_idx))
    rets = []
    for i in idxs:
        entry = closes[i]
        exit_ = closes[i + hold_days]
        rets.append((exit_ - entry) / entry * 100)

    return TierResult(
        threshold    = 0,
        hold_days    = hold_days,
        n_entries    = len(rets),
        win_rate     = round(float(np.mean([r > 0 for r in rets])) * 100, 1),
        avg_return   = round(float(np.mean(rets)), 2),
        avg_alpha    = 0.0,
        median_alpha = 0.0,
        best_alpha   = round(float(np.max(rets)), 2),
        worst_alpha  = round(float(np.min(rets)), 2),
    )


# ── Output ────────────────────────────────────────────────────────────────────

def _bar(val: float, scale: float = 1.0, width: int = 20) -> str:
    """ASCII bar for visualizing magnitude."""
    filled = min(width, max(0, int(abs(val) * scale)))
    char   = "█" if val >= 0 else "░"
    return char * filled + " " * (width - filled)


def print_results(
    tier_results: list[TierResult],
    spy_baseline: TierResult,
    hold_days: int,
    all_entries: list[BacktestEntry],
    tickers: list[str],
    lookback_days: int,
    quiet: bool = False,
) -> None:
    """Rich terminal output - summary table + optional detail."""
    try:
        from rich.console import Console
        from rich.table   import Table
        from rich         import box
        con = Console()
        USE_RICH = True
    except ImportError:
        USE_RICH = False

    total_entries = len([e for e in all_entries if e.hold_days == hold_days])

    header = (
        f"\n{'━'*72}\n"
        f"  BACKTEST - 180-pt Technical Subsystem ({TECH_MAX_PTS}pt reconstructible)\n"
        f"  Universe: {len(tickers)} tickers  │  Lookback: {lookback_days}d  │  Hold: {hold_days}d  │  Entries scanned: {total_entries}\n"
        f"  Factors: RSI(25) + MACD(20) + BB%(20) + Vol(10) + RelStr(10) + Below200MA(10) + 52Wlow(5)\n"
        f"  ⚠  Cannot reconstruct: Upside(20) Div(10) FCF(10) Macro(10) Analyst(5) Short(5) Insider(10)\n"
        f"  ⚠  Survivorship bias: only current tickers tested (delisted excluded)\n"
        f"{'━'*72}"
    )
    print(header)

    # Summary table
    if USE_RICH:
        t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold cyan")
        t.add_column("Threshold",   style="bold")
        t.add_column("Tech equiv",  style="dim")
        t.add_column("Entries",     justify="right")
        t.add_column("Win rate",    justify="right")
        t.add_column("Avg return",  justify="right")
        t.add_column("Avg alpha",   justify="right")
        t.add_column("Med alpha",   justify="right")
        t.add_column("Best",        justify="right")
        t.add_column("Worst",       justify="right")

        # Baseline row
        t.add_row(
            "SPY base", "(random)",
            str(spy_baseline.n_entries),
            f"{spy_baseline.win_rate:.0f}%",
            f"{spy_baseline.avg_return:+.2f}%",
            "-", "-",
            f"{spy_baseline.best_alpha:+.1f}%",
            f"{spy_baseline.worst_alpha:+.1f}%",
        )

        for tr in tier_results:
            if tr.n_entries == 0:
                t.add_row(f"≥{tr.threshold}/{TECH_MAX_PTS}", _live_equiv(tr.threshold),
                          "0", "-", "-", "-", "-", "-", "-")
                continue
            win_str    = f"[green]{tr.win_rate:.0f}%[/green]" if tr.win_rate >= 60 else \
                         f"[yellow]{tr.win_rate:.0f}%[/yellow]" if tr.win_rate >= 50 else \
                         f"[red]{tr.win_rate:.0f}%[/red]"
            alpha_str  = f"[green]{tr.avg_alpha:+.2f}%[/green]" if tr.avg_alpha > 1 else \
                         f"[yellow]{tr.avg_alpha:+.2f}%[/yellow]" if tr.avg_alpha > 0 else \
                         f"[red]{tr.avg_alpha:+.2f}%[/red]"
            t.add_row(
                f"≥{tr.threshold}/{TECH_MAX_PTS}", _live_equiv(tr.threshold),
                str(tr.n_entries),
                win_str,
                f"{tr.avg_return:+.2f}%",
                alpha_str,
                f"{tr.median_alpha:+.2f}%",
                f"[green]{tr.best_alpha:+.1f}%[/green]",
                f"[red]{tr.worst_alpha:+.1f}%[/red]",
            )
        con.print(t)
    else:
        # Fallback plain text
        fmt = "{:<12} {:<12} {:>8} {:>9} {:>11} {:>10} {:>10}"
        print(fmt.format("Threshold", "~Live equiv", "Entries", "Win rate", "Avg return", "Avg alpha", "Med alpha"))
        print("-" * 72)
        print(fmt.format("SPY base", "(random)", spy_baseline.n_entries,
                         f"{spy_baseline.win_rate:.0f}%", f"{spy_baseline.avg_return:+.2f}%", "-", "-"))
        for tr in tier_results:
            if tr.n_entries == 0:
                print(fmt.format(f"≥{tr.threshold}", _live_equiv(tr.threshold), 0, "-", "-", "-", "-"))
            else:
                print(fmt.format(f"≥{tr.threshold}", _live_equiv(tr.threshold),
                                 tr.n_entries, f"{tr.win_rate:.0f}%",
                                 f"{tr.avg_return:+.2f}%", f"{tr.avg_alpha:+.2f}%",
                                 f"{tr.median_alpha:+.2f}%"))

    # Factor contribution analysis
    print(f"\n{'─'*72}")
    print("  FACTOR CONTRIBUTION - avg score by tier")
    factor_names = ["RSI", "MACD", "BB%", "Volume", "Rel strength", "Below 200MA", "52W low"]
    scored = [e for e in all_entries if e.hold_days == hold_days and e.breakdown]
    if scored:
        # Show avg factor points for positive-alpha entries vs negative-alpha entries
        pos_entries = [e for e in scored if e.alpha is not None and e.alpha > 0]
        neg_entries = [e for e in scored if e.alpha is not None and e.alpha <= 0]
        print(f"  {'Factor':<16} {'Avg(winners)':>14} {'Avg(losers)':>13} {'Max':>7}")
        factor_maxes = {"RSI": 25, "MACD": 20, "BB%": 20, "Volume": 10,
                        "Rel strength": 10, "Below 200MA": 10, "52W low": 5}
        for f in factor_names:
            pos_avg = np.mean([e.breakdown.get(f, 0) for e in pos_entries]) if pos_entries else 0
            neg_avg = np.mean([e.breakdown.get(f, 0) for e in neg_entries]) if neg_entries else 0
            mx      = factor_maxes.get(f, 0)
            indicator = " ✓" if pos_avg > neg_avg + 0.5 else "  "
            print(f"  {f:<16} {pos_avg:>10.1f}/{mx}   {neg_avg:>9.1f}/{mx}{indicator}")

    # Per-ticker breakdown (unless quiet)
    if not quiet and all_entries:
        print(f"\n{'─'*72}")
        print("  PER-TICKER RESULTS (all entries, all thresholds)")
        from collections import defaultdict
        by_ticker: dict[str, list[BacktestEntry]] = defaultdict(list)
        for e in all_entries:
            if e.hold_days == hold_days and e.alpha is not None:
                by_ticker[e.ticker].append(e)

        rows = []
        for tkr, es in sorted(by_ticker.items()):
            alphas   = [e.alpha for e in es]
            avg_sc   = np.mean([e.tech_score for e in es])
            avg_alph = np.mean(alphas)
            wr       = sum(1 for e in es if e.win) / len(es) * 100
            rows.append((tkr, len(es), avg_sc, wr, avg_alph))

        rows.sort(key=lambda x: x[4], reverse=True)
        print(f"  {'Ticker':<8} {'N':>5} {'AvgScore':>10} {'WinRate':>9} {'AvgAlpha':>10}")
        print(f"  {'─'*8} {'─'*5} {'─'*10} {'─'*9} {'─'*10}")
        for tkr, n, sc, wr, alph in rows:
            marker = " ✓" if alph > 2 else " ✗" if alph < -2 else "  "
            print(f"  {tkr:<8} {n:>5} {sc:>9.0f}/{TECH_MAX_PTS} {wr:>8.0f}% {alph:>+9.2f}%{marker}")

    print(f"{'━'*72}\n")


def _live_equiv(tech_score: int) -> str:
    """Rough live 180pt equivalent for a given tech score."""
    pct   = tech_score / TECH_MAX_PTS
    equiv = int(pct * LIVE_MAX_PTS)
    return f"~{equiv}/180"


# ── Save results ──────────────────────────────────────────────────────────────

def save_results(
    all_entries: list[BacktestEntry],
    tier_results: list[TierResult],
    spy_baseline: TierResult,
    tickers: list[str],
    lookback_days: int,
    hold_days: int,
) -> None:
    out = {
        "run_date":      date.today().isoformat(),
        "tickers":       tickers,
        "lookback_days": lookback_days,
        "hold_days":     hold_days,
        "tech_max_pts":  TECH_MAX_PTS,
        "spy_baseline": {
            "n_entries":   spy_baseline.n_entries,
            "win_rate":    spy_baseline.win_rate,
            "avg_return":  spy_baseline.avg_return,
        },
        "tiers": [
            {
                "threshold":    tr.threshold,
                "live_equiv":   _live_equiv(tr.threshold),
                "n_entries":    tr.n_entries,
                "win_rate":     tr.win_rate,
                "avg_return":   tr.avg_return,
                "avg_alpha":    tr.avg_alpha,
                "median_alpha": tr.median_alpha,
                "best_alpha":   tr.best_alpha,
                "worst_alpha":  tr.worst_alpha,
            }
            for tr in tier_results
        ],
        "all_entries": [
            {
                "ticker":      e.ticker,
                "entry_date":  e.entry_date.isoformat(),
                "entry_price": e.entry_price,
                "tech_score":  e.tech_score,
                "exit_date":   e.exit_date.isoformat() if e.exit_date else None,
                "return_pct":  e.return_pct,
                "spy_return":  e.spy_return,
                "alpha":       e.alpha,
                "win":         e.win,
            }
            for e in all_entries
        ],
    }
    path = Path(__file__).resolve().parents[1] / "backtest_results.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  Results saved → {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_full_universe() -> list[str]:
    """Load all tickers from scan_universe.py USER_WATCHLIST + BASE_UNIVERSE."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "scan_universe",
            Path(__file__).resolve().parents[1] / "scan_universe.py"
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore
        spec.loader.exec_module(mod)  # type: ignore
        return list(set(
            getattr(mod, "BASE_UNIVERSE", []) +
            getattr(mod, "USER_WATCHLIST", []) +
            POSITIONS_UNIVERSE
        ))
    except Exception:
        return POSITIONS_UNIVERSE


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest 180-pt technical scoring thresholds")
    parser.add_argument("--tickers",   nargs="+", default=None,
                        help="Specific tickers to test (default: positions + watchlist)")
    parser.add_argument("--hold",      nargs="+", type=int, default=[30],
                        metavar="DAYS", help="Hold period(s) in days (default: 30)")
    parser.add_argument("--lookback",  type=int,  default=365,
                        help="Lookback window in days (default: 365)")
    parser.add_argument("--thresholds", nargs="+", type=int,
                        default=[30, 50, 65, 80, 95],
                        help="Tech score thresholds to test (default: 30 50 65 80 95)")
    parser.add_argument("--full",      action="store_true",
                        help="Use full scan universe (~350 tickers, slow)")
    parser.add_argument("--save",      action="store_true",
                        help="Save results to backtest_results.json")
    parser.add_argument("--quiet",     action="store_true",
                        help="Skip per-ticker breakdown, show summary only")
    args = parser.parse_args()

    # Determine ticker universe
    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    elif args.full:
        tickers = _load_full_universe()
        print(f"[Full universe mode: {len(tickers)} tickers - this may take 10-20 minutes]")
    else:
        tickers = POSITIONS_UNIVERSE

    # Ensure SPY is always present (needed for rel strength calc)
    if "SPY" not in tickers:
        tickers = tickers + ["SPY"]

    print(f"\nDownloading data for {len(tickers)} tickers...")

    # Fetch SPY first
    spy_df = fetch_ticker_data("SPY", args.lookback)
    if spy_df is None:
        print("ERROR: Could not download SPY data. Check connection.")
        sys.exit(1)

    # Fetch all tickers and run backtest
    all_entries: list[BacktestEntry] = []
    success_tickers: list[str] = []
    failed: list[str] = []

    for i, ticker in enumerate(tickers):
        if ticker == "SPY":
            continue
        print(f"  [{i+1}/{len(tickers)}] {ticker}...", end=" ", flush=True)

        df = fetch_ticker_data(ticker, args.lookback)
        if df is None:
            print("SKIP (no data)")
            failed.append(ticker)
            continue

        for hold in args.hold:
            entries = run_backtest_for_ticker(
                ticker, df, spy_df, args.lookback, hold
            )
            all_entries.extend(entries)

        n = len([e for e in all_entries if e.ticker == ticker])
        print(f"{n} entries")
        success_tickers.append(ticker)

    if not all_entries:
        print("\nNo entries generated. Try --lookback 730 or add more tickers.")
        sys.exit(0)

    # Analyze and print for each hold period
    for hold in args.hold:
        tier_results = analyze_by_threshold(all_entries, tuple(args.thresholds), hold)
        spy_baseline  = compute_spy_baseline(spy_df, hold)
        print_results(
            tier_results, spy_baseline, hold, all_entries,
            success_tickers, args.lookback, args.quiet
        )

        # ── Falling-knife guard comparison ──
        guard_results = analyze_by_threshold(all_entries, tuple(args.thresholds),
                                             hold, guard_only=True)
        print(f"\n  ━━ FALLING-KNIFE GUARD IMPACT ({hold}d hold) ━━")
        print(f"  {'Threshold':<14}{'NoGuard N':>11}{'Guard N':>9}"
              f"{'Med α (no)':>13}{'Med α (G)':>12}{'Δ Med':>10}")
        print(f"  {'─'*14}{'─'*11}{'─'*9}{'─'*13}{'─'*12}{'─'*10}")
        for tr_no, tr_g in zip(tier_results, guard_results):
            if tr_no.n_entries == 0:
                continue
            delta = tr_g.median_alpha - tr_no.median_alpha if tr_g.n_entries else 0.0
            arrow = "↑" if delta > 0.1 else ("↓" if delta < -0.1 else "·")
            print(f"  ≥{tr_no.threshold}/{TECH_MAX_PTS:<11}{tr_no.n_entries:>11}"
                  f"{tr_g.n_entries:>9}{tr_no.median_alpha:>+12.2f}%"
                  f"{tr_g.median_alpha:>+11.2f}%{delta:>+8.2f}% {arrow}")
        n_blocked = sum(1 for e in all_entries
                        if e.hold_days == hold and not e.guard_pass)
        n_total   = sum(1 for e in all_entries if e.hold_days == hold)
        print(f"  Guard blocked {n_blocked}/{n_total} entries "
              f"({n_blocked/max(n_total,1)*100:.0f}%) - tech≥50pts with no macro narrative")
        print()

        # Calibration verdict
        print("  THRESHOLD VERDICT")
        print("  ─────────────────")
        valid = [tr for tr in tier_results if tr.n_entries >= 10]
        if not valid:
            print("  Insufficient entries for verdict. Use --lookback 730 or --full.\n")
            continue

        best = max(valid, key=lambda t: t.avg_alpha)
        print(f"  Best threshold by avg alpha: ≥{best.threshold}/{TECH_MAX_PTS} "
              f"({_live_equiv(best.threshold)})  →  "
              f"alpha {best.avg_alpha:+.2f}%  win rate {best.win_rate:.0f}%")

        # Check monotonicity
        sorted_valid = sorted(valid, key=lambda t: t.threshold)
        alphas_by_thresh = [t.avg_alpha for t in sorted_valid]
        is_monotonic = all(
            alphas_by_thresh[i] <= alphas_by_thresh[i + 1]
            for i in range(len(alphas_by_thresh) - 1)
        )
        if is_monotonic:
            print("  ✓ Monotonic: higher score → higher alpha. Thresholds directionally correct.")
        else:
            print("  ✗ Non-monotonic: score doesn't consistently predict alpha.")
            print("    → Consider recalibrating weights or threshold boundaries.")

        spy_base_return = spy_baseline.avg_return
        outperform_count = sum(1 for tr in valid if tr.avg_return > spy_base_return)
        print(f"  {outperform_count}/{len(valid)} tiers beat SPY baseline ({spy_base_return:+.2f}%)")
        print()

    if failed:
        print(f"  Skipped ({len(failed)} tickers with no data): {', '.join(failed[:10])}"
              + (" ..." if len(failed) > 10 else ""))

    if args.save:
        for hold in args.hold:
            tier_results = analyze_by_threshold(all_entries, tuple(args.thresholds), hold)
            spy_baseline  = compute_spy_baseline(spy_df, hold)
            save_results(all_entries, tier_results, spy_baseline,
                         success_tickers, args.lookback, hold)


if __name__ == "__main__":
    main()
