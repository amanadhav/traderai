"""
Chart pattern detection + technical indicator signals.
Uses 90-day price window for pattern detection.
Confidence threshold for actionable signals: >= 0.65
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional


# ── Indicator signals ──────────────────────────────────────────────────────

def trend_signals(prices: pd.Series) -> dict:
    """MA trend analysis - where price stands relative to key MAs."""
    ma50 = prices.rolling(50).mean()
    ma200 = prices.rolling(200).mean()
    price = prices.iloc[-1]
    m50 = ma50.iloc[-1]
    m200 = ma200.iloc[-1]

    above_50 = price > m50
    above_200 = price > m200
    ma50_above_ma200 = m50 > m200

    # Golden/death cross: 50MA crossed 200MA in last 10 sessions
    cross = None
    for i in range(-10, -1):
        try:
            if ma50.iloc[i-1] <= ma200.iloc[i-1] and ma50.iloc[i] > ma200.iloc[i]:
                cross = "golden_cross"
                break
            if ma50.iloc[i-1] >= ma200.iloc[i-1] and ma50.iloc[i] < ma200.iloc[i]:
                cross = "death_cross"
                break
        except IndexError:
            pass

    return {
        "price": round(price, 2),
        "ma50": round(m50, 2),
        "ma200": round(m200, 2),
        "above_50ma": above_50,
        "above_200ma": above_200,
        "ma50_above_ma200": ma50_above_ma200,
        "recent_cross": cross,
        "trend": (
            "strong_uptrend" if above_50 and above_200 and ma50_above_ma200
            else "uptrend" if above_50 and above_200
            else "mixed" if above_50 or above_200
            else "downtrend"
        ),
    }


def bb_squeeze(prices: pd.Series, period: int = 20, lookback: int = 252) -> dict:
    """Detect Bollinger Band squeeze - low volatility before explosive move."""
    sma = prices.rolling(period).mean()
    std = prices.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    bandwidth = (upper - lower) / sma * 100

    current_bw = bandwidth.iloc[-1]
    bw_10th = bandwidth.dropna().quantile(0.10)
    is_squeeze = current_bw < bw_10th

    return {
        "bandwidth": round(current_bw, 2),
        "bandwidth_10pct": round(bw_10th, 2),
        "squeeze": is_squeeze,
        "note": "BB squeeze - volatility contraction. Watch for breakout direction." if is_squeeze else "",
    }


def rsi_divergence(prices: pd.Series, rsi_series: pd.Series, window: int = 30) -> dict:
    """
    Detect RSI divergence over recent window.
    Bullish: price makes lower low, RSI makes higher low.
    Bearish: price makes higher high, RSI makes lower high.
    """
    p = prices.iloc[-window:]
    r = rsi_series.iloc[-window:]

    if p.empty or r.empty or len(p) < 10:
        return {"divergence": None}

    # Find local lows and highs
    price_min_idx = p.idxmin()
    price_max_idx = p.idxmax()
    prev_p_min = p.iloc[:len(p)//2].min()
    prev_p_max = p.iloc[:len(p)//2].max()
    last_p_min = p.iloc[len(p)//2:].min()
    last_p_max = p.iloc[len(p)//2:].max()

    prev_r_at_low = r.iloc[:len(r)//2].min()
    last_r_at_low = r.iloc[len(r)//2:].min()
    prev_r_at_high = r.iloc[:len(r)//2].max()
    last_r_at_high = r.iloc[len(r)//2:].max()

    bullish = last_p_min < prev_p_min and last_r_at_low > prev_r_at_low
    bearish = last_p_max > prev_p_max and last_r_at_high < prev_r_at_high

    if bullish:
        return {"divergence": "bullish", "note": "Bullish RSI divergence - price lower low, RSI higher low. Potential reversal up."}
    if bearish:
        return {"divergence": "bearish", "note": "Bearish RSI divergence - price higher high, RSI lower high. Potential reversal down."}
    return {"divergence": None, "note": ""}


def atr_volatility(prices: pd.Series, period: int = 14) -> dict:
    """ATR-based volatility classification."""
    high = prices.rolling(2).max()
    low = prices.rolling(2).min()
    tr = (high - low).abs()
    atr = tr.rolling(period).mean().iloc[-1]
    price = prices.iloc[-1]
    atr_pct = (atr / price) * 100

    if atr_pct < 1.5:
        vol_class = "low"
    elif atr_pct < 3.0:
        vol_class = "medium"
    else:
        vol_class = "high"

    return {"atr": round(atr, 2), "atr_pct": round(atr_pct, 2), "volatility": vol_class}


# ── Classical chart pattern detection ────────────────────────────────────

def _find_peaks_troughs(prices: np.ndarray, min_dist: int = 5) -> tuple[list, list]:
    """Simple peak/trough finder with minimum distance between extremes."""
    peaks, troughs = [], []
    n = len(prices)
    for i in range(min_dist, n - min_dist):
        window = prices[i-min_dist:i+min_dist+1]
        if prices[i] == window.max():
            peaks.append(i)
        if prices[i] == window.min():
            troughs.append(i)
    return peaks, troughs


def detect_double_top(prices: np.ndarray, tolerance: float = 0.02) -> dict:
    peaks, troughs = _find_peaks_troughs(prices)
    if len(peaks) < 2 or len(troughs) < 1:
        return {"pattern": None}

    p1, p2 = peaks[-2], peaks[-1]
    trough_between = [t for t in troughs if p1 < t < p2]
    if not trough_between:
        return {"pattern": None}

    h1, h2 = prices[p1], prices[p2]
    if abs(h1 - h2) / max(h1, h2) > tolerance:
        return {"pattern": None}

    neckline = prices[trough_between[0]]
    current = prices[-1]
    confirmed = current < neckline
    confidence = 0.70 if confirmed else 0.50

    return {
        "pattern": "double_top",
        "signal": "bearish",
        "confidence": confidence,
        "note": f"Double top ~${h1:.2f}. Neckline ${neckline:.2f}. {'CONFIRMED break below neckline.' if confirmed else 'Watching for neckline break.'}",
    }


def detect_double_bottom(prices: np.ndarray, tolerance: float = 0.02) -> dict:
    peaks, troughs = _find_peaks_troughs(prices)
    if len(troughs) < 2 or len(peaks) < 1:
        return {"pattern": None}

    t1, t2 = troughs[-2], troughs[-1]
    peak_between = [p for p in peaks if t1 < p < t2]
    if not peak_between:
        return {"pattern": None}

    l1, l2 = prices[t1], prices[t2]
    if abs(l1 - l2) / max(l1, l2) > tolerance:
        return {"pattern": None}

    neckline = prices[peak_between[0]]
    current = prices[-1]
    confirmed = current > neckline
    confidence = 0.75 if confirmed else 0.55

    return {
        "pattern": "double_bottom",
        "signal": "bullish",
        "confidence": confidence,
        "note": f"Double bottom ~${l1:.2f}. Neckline ${neckline:.2f}. {'CONFIRMED break above neckline.' if confirmed else 'Watching for neckline breakout.'}",
    }


def detect_head_shoulders(prices: np.ndarray, tolerance: float = 0.05) -> dict:
    peaks, troughs = _find_peaks_troughs(prices, min_dist=5)
    if len(peaks) < 3 or len(troughs) < 2:
        return {"pattern": None}

    ls, head, rs = peaks[-3], peaks[-2], peaks[-1]
    h_ls, h_head, h_rs = prices[ls], prices[head], prices[rs]

    if h_head <= h_ls or h_head <= h_rs:
        return {"pattern": None}
    if abs(h_ls - h_rs) / h_head > tolerance:
        return {"pattern": None}

    troughs_in = [t for t in troughs if ls < t < rs]
    if len(troughs_in) < 2:
        return {"pattern": None}

    neckline = (prices[troughs_in[0]] + prices[troughs_in[-1]]) / 2
    confirmed = prices[-1] < neckline
    confidence = 0.72 if confirmed else 0.52

    return {
        "pattern": "head_shoulders",
        "signal": "bearish",
        "confidence": confidence,
        "note": f"H&S: shoulders ~${h_ls:.2f}/{h_rs:.2f}, head ${h_head:.2f}. Neckline ~${neckline:.2f}. {'CONFIRMED.' if confirmed else 'Watching.'}",
    }


def detect_inverse_head_shoulders(prices: np.ndarray, tolerance: float = 0.05) -> dict:
    peaks, troughs = _find_peaks_troughs(prices, min_dist=5)
    if len(troughs) < 3 or len(peaks) < 2:
        return {"pattern": None}

    ls, head, rs = troughs[-3], troughs[-2], troughs[-1]
    l_ls, l_head, l_rs = prices[ls], prices[head], prices[rs]

    if l_head >= l_ls or l_head >= l_rs:
        return {"pattern": None}
    if abs(l_ls - l_rs) / abs(l_head) > tolerance:
        return {"pattern": None}

    peaks_in = [p for p in peaks if ls < p < rs]
    if len(peaks_in) < 2:
        return {"pattern": None}

    neckline = (prices[peaks_in[0]] + prices[peaks_in[-1]]) / 2
    confirmed = prices[-1] > neckline
    confidence = 0.75 if confirmed else 0.55

    return {
        "pattern": "inverse_head_shoulders",
        "signal": "bullish",
        "confidence": confidence,
        "note": f"Inv H&S: shoulders ~${l_ls:.2f}/{l_rs:.2f}, head ${l_head:.2f}. Neckline ~${neckline:.2f}. {'CONFIRMED breakout.' if confirmed else 'Watching neckline.'}",
    }


def detect_cup_and_handle(prices: np.ndarray) -> dict:
    n = len(prices)
    if n < 40:
        return {"pattern": None}

    cup = prices[:int(n * 0.75)]
    handle = prices[int(n * 0.75):]

    cup_left = cup[:len(cup)//4].mean()
    cup_bottom = cup[len(cup)//4:3*len(cup)//4].min()
    cup_right = cup[3*len(cup)//4:].mean()

    is_cup = (cup_left > cup_bottom * 1.05 and cup_right > cup_bottom * 1.05
              and abs(cup_left - cup_right) / cup_left < 0.10)

    if not is_cup:
        return {"pattern": None}

    handle_high = handle.max()
    handle_low = handle.min()
    handle_retracement = (handle_high - handle_low) / (cup_right - cup_bottom)
    is_handle = 0.10 < handle_retracement < 0.50

    if not is_handle:
        return {"pattern": None}

    confirmed = prices[-1] > cup_right
    confidence = 0.70 if confirmed else 0.60

    return {
        "pattern": "cup_and_handle",
        "signal": "bullish",
        "confidence": confidence,
        "note": f"Cup & handle. Cup base ~${cup_bottom:.2f}, resistance ~${cup_right:.2f}. {'Breakout confirmed.' if confirmed else 'Handle forming, watch for breakout.'}",
    }


def detect_ascending_triangle(prices: np.ndarray, volume: Optional[np.ndarray] = None) -> dict:
    n = len(prices)
    if n < 20:
        return {"pattern": None}

    peaks, troughs = _find_peaks_troughs(prices)
    if len(peaks) < 2 or len(troughs) < 2:
        return {"pattern": None}

    recent_peaks = [prices[p] for p in peaks[-3:]]
    recent_troughs = [prices[t] for t in troughs[-3:]]

    flat_resistance = max(recent_peaks) - min(recent_peaks) < max(recent_peaks) * 0.02
    rising_lows = all(recent_troughs[i] < recent_troughs[i+1] for i in range(len(recent_troughs)-1))

    if not (flat_resistance and rising_lows):
        return {"pattern": None}

    resistance = np.mean(recent_peaks)
    confirmed = prices[-1] > resistance
    confidence = 0.68 if confirmed else 0.55

    return {
        "pattern": "ascending_triangle",
        "signal": "bullish",
        "confidence": confidence,
        "note": f"Ascending triangle. Flat resistance ~${resistance:.2f}, rising lows. {'Breakout above resistance.' if confirmed else 'Coiling toward resistance.'}",
    }


def detect_descending_triangle(prices: np.ndarray) -> dict:
    peaks, troughs = _find_peaks_troughs(prices)
    if len(peaks) < 2 or len(troughs) < 2:
        return {"pattern": None}

    recent_peaks = [prices[p] for p in peaks[-3:]]
    recent_troughs = [prices[t] for t in troughs[-3:]]

    flat_support = max(recent_troughs) - min(recent_troughs) < max(recent_troughs) * 0.02
    falling_highs = all(recent_peaks[i] > recent_peaks[i+1] for i in range(len(recent_peaks)-1))

    if not (flat_support and falling_highs):
        return {"pattern": None}

    support = np.mean(recent_troughs)
    confirmed = prices[-1] < support
    confidence = 0.68 if confirmed else 0.52

    return {
        "pattern": "descending_triangle",
        "signal": "bearish",
        "confidence": confidence,
        "note": f"Descending triangle. Flat support ~${support:.2f}, falling highs. {'Break below support.' if confirmed else 'Compressing toward support.'}",
    }


def detect_flag(prices: np.ndarray) -> dict:
    n = len(prices)
    if n < 20:
        return {"pattern": None}

    pole = prices[:n//3]
    flag = prices[n//3:]

    pole_move = (pole.max() - pole.min()) / pole.min()
    flag_range = (flag.max() - flag.min()) / flag.mean()

    strong_pole = pole_move > 0.08
    tight_flag = flag_range < 0.05
    flag_trend = np.polyfit(range(len(flag)), flag, 1)[0]
    countertrend = flag_trend < 0 if pole[-1] > pole[0] else flag_trend > 0

    if not (strong_pole and tight_flag and countertrend):
        return {"pattern": None}

    signal = "bullish" if pole[-1] > pole[0] else "bearish"
    confidence = 0.65

    return {
        "pattern": "flag",
        "signal": signal,
        "confidence": confidence,
        "note": f"{'Bull' if signal == 'bullish' else 'Bear'} flag. Sharp {pole_move:.1%} pole move followed by tight consolidation.",
    }


# ── Main entry point ───────────────────────────────────────────────────────

def detect(prices: pd.Series, rsi_series: Optional[pd.Series] = None,
           volume: Optional[pd.Series] = None, window: int = 90) -> dict:
    """
    Run all pattern + indicator detection on price series.

    Returns the single highest-confidence pattern found, plus all indicator signals.
    """
    if len(prices) < window:
        window = len(prices)

    p = prices.iloc[-window:]
    arr = p.values.astype(float)

    results = {}

    # Indicators
    results["trend"] = trend_signals(prices)
    results["bb_squeeze"] = bb_squeeze(prices)
    results["atr"] = atr_volatility(prices)

    if rsi_series is not None and len(rsi_series) >= window:
        results["rsi_divergence"] = rsi_divergence(prices, rsi_series)
    else:
        results["rsi_divergence"] = {"divergence": None}

    # Chart patterns
    pattern_checks = [
        detect_double_bottom(arr),
        detect_inverse_head_shoulders(arr),
        detect_cup_and_handle(arr),
        detect_ascending_triangle(arr),
        detect_flag(arr),
        detect_double_top(arr),
        detect_head_shoulders(arr),
        detect_descending_triangle(arr),
    ]

    found = [p for p in pattern_checks if p.get("pattern")]
    if found:
        best = max(found, key=lambda x: x.get("confidence", 0))
        results["chart_pattern"] = best
    else:
        results["chart_pattern"] = {"pattern": None, "signal": None, "confidence": 0, "note": "No classical pattern detected."}

    return results


def summarize(results: dict, ticker: str = "") -> str:
    lines = [f"\n  {'─'*40}", f"  PATTERNS & INDICATORS: {ticker}"]

    t = results.get("trend", {})
    lines.append(f"  Trend: {t.get('trend','?').upper()} | Price ${t.get('price')} | 50MA ${t.get('ma50')} | 200MA ${t.get('ma200')}")
    if t.get("recent_cross"):
        icon = "🟡" if t["recent_cross"] == "golden_cross" else "⚠️"
        lines.append(f"  {icon} {t['recent_cross'].replace('_',' ').title()} detected in last 10 sessions!")

    sq = results.get("bb_squeeze", {})
    if sq.get("squeeze"):
        lines.append(f"  🔵 BB SQUEEZE active (BW {sq['bandwidth']:.1f} < 10th pct {sq['bandwidth_10pct']:.1f}) - breakout incoming")

    rd = results.get("rsi_divergence", {})
    if rd.get("divergence"):
        icon = "✅" if rd["divergence"] == "bullish" else "⚠️"
        lines.append(f"  {icon} RSI divergence: {rd['note']}")

    cp = results.get("chart_pattern", {})
    if cp.get("pattern"):
        conf = cp.get("confidence", 0)
        actionable = "★ ACTIONABLE" if conf >= 0.65 else "(low confidence)"
        signal_icon = "📈" if cp.get("signal") == "bullish" else "📉"
        lines.append(f"  {signal_icon} {cp['pattern'].replace('_',' ').title()} [{conf:.0%}] {actionable}")
        if cp.get("note"):
            lines.append(f"     {cp['note']}")
    else:
        lines.append("  No classical chart pattern detected.")

    return "\n".join(lines)
