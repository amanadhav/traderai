"""
insider.py - Insider buying signal detector
Source: yfinance (SEC Form 4), Finnhub fallback
Cache: insider_cache.json (24hr TTL)

Signal tiers:
  STRONG  - CEO/CFO/President open market buy ≥$100K, last 90 days
  CLUSTER - 3+ insiders open market buy within 30-day window, last 90 days
  NOTABLE - Any officer/director open market buy ≥$50K, last 90 days
  WEAK    - Open market buy <$50K detected
  NONE    - No qualifying buys found
  ERROR   - Data fetch failed
"""

from __future__ import annotations

import json
import os
import re
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).resolve().parents[1]
CACHE = BASE / "insider_cache.json"
CACHE_TTL_HOURS = 24

# Open market purchase keywords (yfinance Text field)
BUY_KEYWORDS = ["purchase at price", "purchased at price"]
# Noise: stock awards, option exercises, gifts, tax withholding
IGNORE_KEYWORDS = [
    "stock award", "grant", "conversion", "exercise",
    "gift", "tax withholding", "rule 10b5", "automatic",
]

# Title tier detection
C_SUITE_KEYWORDS = [
    "chief executive", "ceo", "chief financial", "cfo",
    "chief operating", "coo", "president", "executive chairman",
]
OFFICER_KEYWORDS = [
    "officer", "director", "general counsel", "vp ", "vice president",
    "secretary", "treasurer", "controller",
]

socket.setdefaulttimeout(12)


# ── helpers ─────────────────────────────────────────────────────────────────

def _is_open_market_buy(text: str) -> bool:
    t = text.lower().strip()
    if not t:
        return False
    if any(k in t for k in IGNORE_KEYWORDS):
        return False
    return any(k in t for k in BUY_KEYWORDS)


def _title_tier(position: str) -> int:
    """1 = C-suite, 2 = officer/director, 0 = unknown"""
    p = position.lower()
    if any(k in p for k in C_SUITE_KEYWORDS):
        return 1
    if any(k in p for k in OFFICER_KEYWORDS):
        return 2
    return 0


def _parse_price(text: str, shares: int, value: float) -> float:
    """Extract price from text or derive from value/shares."""
    m = re.search(r"price\s+([\d.]+)", text.lower())
    if m:
        return float(m.group(1))
    if shares > 0 and value > 0:
        return value / shares
    return 0.0


def _parse_date(raw) -> datetime | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, str):
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return None
    try:
        return pd.Timestamp(raw).to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None


# ── signal tier logic ────────────────────────────────────────────────────────

def _compute_signal(buys: list[dict]) -> tuple[str, str]:
    """
    Given list of qualifying buy dicts, return (signal_tier, description).
    Priority: STRONG > CLUSTER > NOTABLE > WEAK
    """
    if not buys:
        return "NONE", ""

    # STRONG: C-suite buy ≥$100K
    csuite = [b for b in buys if b["title_tier"] == 1 and b["value"] >= 100_000]
    if csuite:
        b = max(csuite, key=lambda x: x["value"])
        return (
            "STRONG",
            f"{b['name']} ({b['position']}) bought ${b['value']:,.0f}"
            f" @ ${b['price']:.2f} on {b['date']}",
        )

    # CLUSTER: 3+ insiders within any 30-day window
    dated = sorted(buys, key=lambda x: x["date"])
    for i, anchor in enumerate(dated):
        anchor_dt = datetime.strptime(anchor["date"], "%Y-%m-%d")
        window = [
            b for b in dated
            if 0 <= (datetime.strptime(b["date"], "%Y-%m-%d") - anchor_dt).days <= 30
        ]
        if len(window) >= 3:
            names = [b["name"].split()[0] for b in window[:3]]
            total_val = sum(b["value"] for b in window)
            return (
                "CLUSTER",
                f"{len(window)} insiders bought within 30 days"
                f" - total ${total_val:,.0f} ({', '.join(names[:2])}, +)",
            )

    # NOTABLE: any buy ≥$50K
    notable = [b for b in buys if b["value"] >= 50_000]
    if notable:
        b = max(notable, key=lambda x: x["value"])
        return (
            "NOTABLE",
            f"{b['name']} ({b['position']}) bought ${b['value']:,.0f}"
            f" @ ${b['price']:.2f} on {b['date']}",
        )

    # WEAK: something detected but below thresholds
    total_val = sum(b["value"] for b in buys)
    return "WEAK", f"{len(buys)} small open-market buy(s) - total ${total_val:,.0f}"


# ── main fetch ───────────────────────────────────────────────────────────────

def fetch_insider_signal(ticker: str, days: int = 90) -> dict:
    """
    Fetch and score insider buying for one ticker.

    Returns dict with keys:
      ticker, signal, has_signal, description, buys, fetched_at
    """
    cutoff = datetime.now() - timedelta(days=days)

    def _empty(signal="NONE", desc="No data"):
        return {
            "ticker": ticker,
            "signal": signal,
            "has_signal": False,
            "description": desc,
            "buys": [],
            "fetched_at": datetime.now().isoformat(),
        }

    try:
        t = yf.Ticker(ticker)
        df = t.insider_transactions
    except Exception as e:
        return _empty("ERROR", str(e))

    if df is None or df.empty:
        return _empty()

    buys: list[dict] = []
    for _, row in df.iterrows():
        text = str(row.get("Text", ""))
        if not _is_open_market_buy(text):
            continue

        trade_date = _parse_date(row.get("Start Date"))
        if trade_date is None or trade_date < cutoff:
            continue

        shares = int(row.get("Shares", 0) or 0)
        raw_value = float(row.get("Value", 0) or 0)
        price = _parse_price(text, shares, raw_value)
        value = raw_value if raw_value > 0 else (shares * price)
        position = str(row.get("Position", ""))

        buys.append({
            "name": str(row.get("Insider", "")).title(),
            "position": position,
            "title_tier": _title_tier(position),
            "shares": shares,
            "value": value,
            "price": price,
            "date": trade_date.strftime("%Y-%m-%d"),
            "text": text[:100],
        })

    # If yfinance found nothing, try Finnhub (no position data but clean P-code)
    if not buys:
        buys = _try_finnhub(ticker, cutoff)

    buys.sort(key=lambda x: x["value"], reverse=True)
    signal, description = _compute_signal(buys)

    return {
        "ticker": ticker,
        "signal": signal,
        "has_signal": signal in ("STRONG", "CLUSTER", "NOTABLE"),
        "description": description,
        "buys": buys,
        "fetched_at": datetime.now().isoformat(),
    }


def _try_finnhub(ticker: str, cutoff: datetime) -> list[dict]:
    """Finnhub fallback - clean P-code, no position title."""
    import requests

    key = os.getenv("FINNHUB_KEY", "")
    if not key:
        return []

    try:
        url = (
            f"https://finnhub.io/api/v1/stock/insider-transactions"
            f"?symbol={ticker}&token={key}"
        )
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])
    except Exception:
        return []

    buys = []
    for t in data:
        if t.get("transactionCode") != "P":
            continue
        if t.get("isDerivative", False):
            continue
        change = t.get("change", 0)
        if change <= 0:
            continue
        trade_date = _parse_date(t.get("transactionDate", ""))
        if trade_date is None or trade_date < cutoff:
            continue

        price = float(t.get("transactionPrice", 0))
        value = change * price

        buys.append({
            "name": str(t.get("name", "")).title(),
            "position": "Officer/Director",  # Finnhub free tier has no title
            "title_tier": 2,
            "shares": change,
            "value": value,
            "price": price,
            "date": trade_date.strftime("%Y-%m-%d"),
            "text": f"Open market purchase (Finnhub P-code)",
        })

    return buys


# ── batch fetch with cache ───────────────────────────────────────────────────

def get_insider_signals(
    tickers: list[str],
    force_refresh: bool = False,
    verbose: bool = True,
) -> dict[str, dict]:
    """
    Batch fetch with 24hr cache.
    Returns {ticker: signal_dict} for all tickers.
    """
    # Load cache
    cache: dict = {}
    if CACHE.exists() and not force_refresh:
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    ttl = timedelta(hours=CACHE_TTL_HOURS)
    results: dict[str, dict] = {}
    to_fetch: list[str] = []

    # Check which are stale / missing
    for ticker in tickers:
        cached = cache.get(ticker)
        if cached and not force_refresh:
            try:
                fetched_at = datetime.fromisoformat(cached.get("fetched_at", "2000-01-01"))
                if datetime.now() - fetched_at < ttl:
                    results[ticker] = cached
                    continue
            except Exception:
                pass
        to_fetch.append(ticker)

    # Fetch stale / missing
    for ticker in to_fetch:
        if verbose:
            print(f"  [insider] fetching {ticker}...", flush=True)
        result = fetch_insider_signal(ticker)
        results[ticker] = result
        cache[ticker] = result

    # Save cache
    if to_fetch:
        try:
            CACHE.write_text(json.dumps(cache, indent=2, default=str), encoding="utf-8")
            CACHE.chmod(0o600)
        except Exception:
            pass

    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

def _signal_icon(signal: str) -> str:
    return {
        "STRONG": "🔥",
        "CLUSTER": "⚡",
        "NOTABLE": "👀",
        "WEAK": "〰",
        "NONE": "-",
        "ERROR": "❌",
    }.get(signal, "?")


def _print_report(signals: dict[str, dict]) -> None:
    print()
    print("🔍  INSIDER BUYING SIGNALS (last 90 days)")
    print("=" * 70)

    actionable = {k: v for k, v in signals.items() if v["has_signal"]}
    passive = {k: v for k, v in signals.items() if not v["has_signal"]}

    if actionable:
        print("  ACTIONABLE:")
        for ticker, sig in actionable.items():
            icon = _signal_icon(sig["signal"])
            print(f"  {icon} {ticker:6s}  [{sig['signal']:8s}]  {sig['description']}")
            if sig.get("buys"):
                b = sig["buys"][0]
                print(f"          ↳ Top buy: {b['shares']:,} sh @ ${b['price']:.2f}"
                      f"  ({b['position']})  {b['date']}")

    print()
    if passive:
        print("  NO SIGNAL:")
        for ticker, sig in passive.items():
            icon = _signal_icon(sig["signal"])
            print(f"  {icon} {ticker:6s}  [{sig['signal']:8s}]")

    print()
    print("  Source: SEC Form 4 via yfinance + Finnhub. Codes: P=open-market-buy.")
    print("  Filter: buys only (no awards, exercises, gifts). Value ≥$50K for NOTABLE.")
    print()


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    force = "--refresh" in args
    tickers_arg = [a for a in args if not a.startswith("--")]

    if not tickers_arg:
        # Default: all held tickers across both accounts
        tickers_arg = [
            # ROTH
            "BJ", "CRM", "EPD", "GLD", "MDT", "MP", "NKE", "NOC", "RTX",
            # TOD
            "AAPL", "AMD", "AMZN", "ASML", "BBAI", "GOOGL", "META",
            "MSFT", "NFLX", "NVDA", "NVO", "TSM",
        ]

    signals = get_insider_signals(tickers_arg, force_refresh=force, verbose=True)
    _print_report(signals)
