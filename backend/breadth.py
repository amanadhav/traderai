"""
Market breadth indicators - how broad is the move?

Tracks:
  - % of S&P 500 above 50MA / 200MA (trend health)
  - Advance/decline ratio (today's movers)
  - New 52w highs vs new 52w lows
  - % of stocks with RSI < 30 (oversold breadth)
  - % of stocks with RSI > 70 (overbought breadth)
  - VIX regime (calm / fear / panic)

Reading:
  - >70% above 50MA = healthy uptrend (broad participation)
  - <30% above 50MA = broad weakness (rotation or sell-off)
  - A/D ratio < 0.5 = bearish day (big tech can mask broad weakness)
  - New_lows > new_highs sustained = bear market
  - >20% RSI<30 = capitulation territory (high probability bounce)
"""
from __future__ import annotations
import json
import socket
from datetime import datetime
from pathlib import Path
import yfinance as yf
import pandas as pd
import requests
from io import StringIO

socket.setdefaulttimeout(12)

BASE = Path(__file__).resolve().parents[1]

def get_sp500_tickers() -> list[str]:
    """Reuse scan.py's multi-source fallback."""
    try:
        df = pd.read_csv("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv")
        return [t.replace('.', '-') for t in df['Symbol'].tolist()]
    except Exception:
        return []

def calculate_breadth(sample_size: int = 100) -> dict:
    """
    Sample S&P 500 (default 100 tickers for speed) and compute breadth.
    Full sample = ~5 min, 100 sample = ~30 sec.
    """
    tickers = get_sp500_tickers()
    if not tickers:
        return {"error": "Could not fetch S&P 500 tickers"}

    # Sample for speed (statistical breadth doesn't need every ticker)
    if sample_size and len(tickers) > sample_size:
        import random
        random.seed(42)  # reproducible
        tickers = random.sample(tickers, sample_size)

    above_50ma = 0
    above_200ma = 0
    advancing = 0
    declining = 0
    new_highs = 0
    new_lows = 0
    oversold = 0   # RSI < 30
    overbought = 0  # RSI > 70
    counted = 0

    print(f"Computing breadth across {len(tickers)} tickers...")

    for i, t in enumerate(tickers):
        try:
            hist = yf.Ticker(t).history(period="1y")
            if hist.empty or len(hist) < 200:
                continue
            closes = hist["Close"]
            price = float(closes.iloc[-1])
            prev  = float(closes.iloc[-2])
            ma50  = float(closes.rolling(50).mean().iloc[-1])
            ma200 = float(closes.rolling(200).mean().iloc[-1])
            high52 = float(hist["High"].max())
            low52  = float(hist["Low"].min())

            # RSI calc (simple)
            delta = closes.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rs = gain / loss.replace(0, 1e-10)
            rsi = float((100 - 100 / (1 + rs)).iloc[-1])

            counted += 1
            if price > ma50:  above_50ma  += 1
            if price > ma200: above_200ma += 1
            if price > prev:  advancing += 1
            elif price < prev: declining += 1
            if abs(price - high52) / high52 < 0.01: new_highs += 1
            if abs(price - low52)  / low52  < 0.01: new_lows  += 1
            if rsi < 30: oversold += 1
            if rsi > 70: overbought += 1

            if (i+1) % 20 == 0:
                print(f"  [{i+1}/{len(tickers)}]")
        except Exception:
            continue

    if counted == 0:
        return {"error": "No tickers returned data"}

    # VIX
    try:
        vix_hist = yf.Ticker("^VIX").history(period="5d")
        vix = float(vix_hist["Close"].iloc[-1])
    except Exception:
        vix = None

    pct = lambda n: round(n / counted * 100, 1)

    result = {
        "computed_at": datetime.now().isoformat(),
        "sample_size": counted,
        "above_50ma_pct":  pct(above_50ma),
        "above_200ma_pct": pct(above_200ma),
        "advancing_pct":   pct(advancing),
        "declining_pct":   pct(declining),
        "ad_ratio":        round(advancing / max(declining, 1), 2),
        "new_highs":       new_highs,
        "new_lows":        new_lows,
        "oversold_pct":    pct(oversold),
        "overbought_pct":  pct(overbought),
        "vix":             vix,
    }

    # Regime classification
    if pct(above_50ma) > 70:
        regime = "🟢 HEALTHY_UPTREND - broad participation"
    elif pct(above_50ma) > 50:
        regime = "🟡 MIXED - neutral/rotation"
    elif pct(above_50ma) > 30:
        regime = "🟠 WEAK - distribution underway"
    else:
        regime = "🔴 BROAD_SELLOFF - capitulation territory"

    if pct(oversold) > 20:
        regime += " · 🔥 oversold breadth (high prob bounce)"
    if pct(overbought) > 25:
        regime += " · ⚠️ overbought breadth (top forming)"
    if vix and vix > 30:
        regime += " · 😱 VIX panic"
    elif vix and vix > 25:
        regime += " · 😟 VIX fear"

    result["regime"] = regime
    return result


def print_breadth(b: dict):
    if "error" in b:
        print(f"❌ {b['error']}")
        return
    print(f"\n{'═' * 80}")
    print(f"  MARKET BREADTH - {b['computed_at'][:16]}  (sample: {b['sample_size']} stocks)")
    print(f"{'═' * 80}")
    print(f"\n  {b['regime']}\n")
    print(f"  TREND HEALTH")
    print(f"    Above 50MA:  {b['above_50ma_pct']}%   (>70 healthy, <30 sell-off)")
    print(f"    Above 200MA: {b['above_200ma_pct']}%   (long-term trend)")
    print(f"\n  TODAY'S BREADTH")
    print(f"    Advancing:   {b['advancing_pct']}%")
    print(f"    Declining:   {b['declining_pct']}%")
    print(f"    A/D ratio:   {b['ad_ratio']}   (>1 bullish day, <1 bearish)")
    print(f"\n  EXTREMES")
    print(f"    New 52w highs: {b['new_highs']}")
    print(f"    New 52w lows:  {b['new_lows']}")
    print(f"    RSI < 30:      {b['oversold_pct']}%   (>20 = capitulation)")
    print(f"    RSI > 70:      {b['overbought_pct']}%   (>25 = top forming)")
    print(f"\n  VOLATILITY")
    print(f"    VIX: {b['vix']:.1f}" if b.get('vix') else "    VIX: -")


if __name__ == "__main__":
    import sys
    sample = 100 if "--quick" in sys.argv else 200
    b = calculate_breadth(sample_size=sample)
    print_breadth(b)
    out = BASE / "breadth_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(b, f, indent=2)
    print(f"\nSaved → {out}")
