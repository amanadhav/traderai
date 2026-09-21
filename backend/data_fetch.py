"""
data_fetch.py - Pure data-fetching layer.

yfinance snapshots, technical indicators (RSI/MACD/BB), earnings detection,
news (yfinance + NewsAPI), market indicators (VIX/SPY/QQQ), dividend calendar.

Pure functions. No portfolio state. No file I/O beyond reading .env.
Other modules import what they need from here.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, date as _date, timezone, timedelta
from typing import Optional

import yfinance as yf

from persistence import BASE


# ── .env loader ─────────────────────────────────────────────────────────────

def load_env():
    """Load BASE/.env into os.environ if present. Idempotent.
    Overrides empty-string env vars (e.g. shell-exported `KEY=`) but preserves
    any non-empty value already set in the parent shell."""
    env_file = BASE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            existing = os.environ.get(k)
            if not existing:  # None or empty → load from .env
                os.environ[k] = v


load_env()
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")


# ── Market hours ────────────────────────────────────────────────────────────

MST_OFFSET = timedelta(hours=-7)  # Arizona MST = UTC-7 (no DST)
MARKET_OPEN_MST = (6, 30)
MARKET_CLOSE_MST = (13, 0)


def market_status() -> tuple[bool, str]:
    now_utc = datetime.now(timezone.utc)
    now_mst = now_utc + MST_OFFSET
    is_weekday = now_mst.weekday() < 5
    after_open = (now_mst.hour, now_mst.minute) >= MARKET_OPEN_MST
    before_close = (now_mst.hour, now_mst.minute) < MARKET_CLOSE_MST
    is_open = is_weekday and after_open and before_close
    status = (
        f"OPEN - {now_mst.strftime('%I:%M %p')} MST"
        if is_open else
        f"CLOSED - {now_mst.strftime('%I:%M %p')} MST"
        + (" (weekend)" if not is_weekday else
           " (pre-market)" if not after_open else " (after-hours)")
    )
    return is_open, status


# ── Technical indicators (pure pandas math) ─────────────────────────────────

def get_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def get_macd_hist(prices):
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return hist.iloc[-1], hist.iloc[-2]


def get_bb_pct(prices, period=20):
    sma = prices.rolling(period).mean()
    std = prices.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    denom = upper.iloc[-1] - lower.iloc[-1]
    if denom == 0:
        return 50.0
    return (prices.iloc[-1] - lower.iloc[-1]) / denom * 100


# ── Earnings date detection (4-source, conservative) ────────────────────────

def _get_days_to_earnings(ticker: str, yf_ticker, info: dict) -> tuple[Optional[int], str]:
    """
    Bulletproof earnings date detection.
    Uses 4 sources, validates each, takes the MOST CONSERVATIVE (earliest future date).
    Returns (days_to_earnings, source_label) - source_label used for audit trail.

    Rules:
    - Discard any date >365 days out (clearly wrong)
    - Discard any date <-7 days (stale past earnings, not next quarter)
    - When sources conflict, use the EARLIEST (most conservative = safer disqualifier)
    - Manual override in positions.json earnings_override wins all sources
    - Returns None only if all 4 sources fail
    """
    today = datetime.now(timezone.utc).date()
    candidates: list[tuple[int, str]] = []

    def _add(d: Optional[_date], src: str):
        if d is None:
            return
        try:
            if hasattr(d, "date"):
                d = d.date()
            days = (d - today).days
            if -7 <= days <= 365:
                candidates.append((days, src))
        except Exception:
            pass

    # Source 1: yf.Ticker.calendar - most reliable confirmed date
    try:
        cal = yf_ticker.calendar
        if cal and "Earnings Date" in cal:
            ed = cal["Earnings Date"]
            if isinstance(ed, list):
                for d in ed:
                    _add(d, "calendar")
            else:
                _add(ed, "calendar")
    except Exception:
        pass

    # Source 2: earningsTimestampStart
    try:
        ts_start = info.get("earningsTimestampStart")
        if ts_start:
            _add(datetime.fromtimestamp(ts_start, tz=timezone.utc), "ts_start")
    except Exception:
        pass

    # Source 3: earningsTimestampEnd
    try:
        ts_end = info.get("earningsTimestampEnd")
        if ts_end:
            _add(datetime.fromtimestamp(ts_end, tz=timezone.utc), "ts_end")
    except Exception:
        pass

    # Source 4: earningsTimestamp (legacy, last resort)
    try:
        ts = info.get("earningsTimestamp")
        if ts:
            _add(datetime.fromtimestamp(ts, tz=timezone.utc), "ts_legacy")
    except Exception:
        pass

    if not candidates:
        return None, "none"

    future = [(d, s) for d, s in candidates if d >= 0]
    pool = future if future else candidates

    pool.sort(key=lambda x: x[0])
    days, src = pool[0]

    # Conflict check: if sources disagree by >7 days, flag it
    if len(pool) > 1 and (pool[-1][0] - pool[0][0]) > 7:
        src = f"{src}[CONFLICT:{pool[-1][0]-pool[0][0]}d gap]"

    return days, src


# ── Full snapshot (price/rsi/macd/bb/earnings/fundamentals) ──────────────────

def get_full_snapshot(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period="1y", interval="1d")
        if hist.empty:
            return {"error": f"No data for {ticker}"}
        prices = hist["Close"]
        volume = hist["Volume"]
        price = prices.iloc[-1]
        rsi_series = get_rsi(prices)
        rsi = rsi_series.iloc[-1]
        macd_now, macd_prev = get_macd_hist(prices)
        bb_pct = get_bb_pct(prices)
        vol_today = volume.iloc[-1]
        vol_avg = info.get("averageDailyVolume3Month", 1) or 1
        vol_ratio = vol_today / vol_avg

        days_to_earnings, earnings_date_src = _get_days_to_earnings(ticker, t, info)

        # ATR(14) - average true range, the risk engine's volatility unit
        atr = None
        try:
            import pandas as pd
            prev_close = hist["Close"].shift(1)
            tr = pd.concat([
                hist["High"] - hist["Low"],
                (hist["High"] - prev_close).abs(),
                (hist["Low"] - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr_val = tr.rolling(14).mean().iloc[-1]
            if atr_val == atr_val:  # not NaN
                atr = round(float(atr_val), 3)
        except Exception:
            pass

        sp_change = (info.get("SandP52WeekChange") or 0) * 100
        stock_52w = (info.get("52WeekChange") or 0) * 100
        low_52 = info.get("fiftyTwoWeekLow") or price
        high_52 = info.get("fiftyTwoWeekHigh") or price

        return {
            "ticker": ticker,
            "price": round(float(price), 2),
            "rsi": round(float(rsi), 1) if not (rsi != rsi) else None,
            "ma50": round(float(prices.rolling(50).mean().iloc[-1]), 2),
            "ma200": round(float(prices.rolling(200).mean().iloc[-1]), 2),
            "macd_hist": round(float(macd_now), 3),
            "macd_prev": round(float(macd_prev), 3),
            "macd_crossover": bool(macd_now > 0 and macd_prev < 0),
            "macd_improving": bool(macd_now > macd_prev),
            "bb_pct": round(float(bb_pct), 1),
            "vol_ratio": round(float(vol_ratio), 2),
            "days_to_earnings": days_to_earnings,
            "earnings_date_src": earnings_date_src,
            "atr": atr,
            "atr_pct": round(atr / float(price) * 100, 2) if atr else None,
            "short_pct_float": round((info.get("shortPercentOfFloat") or 0) * 100, 1),
            "analyst_rating": info.get("averageAnalystRating"),
            "forward_pe": info.get("forwardPE"),
            "trailing_pe": info.get("trailingPE"),
            "peg_ratio": info.get("pegRatio"),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cash_flow": info.get("freeCashflow"),
            "market_cap": info.get("marketCap"),
            "revenue_growth": info.get("revenueGrowth"),
            "total_cash": info.get("totalCash"),
            "operating_cashflow": info.get("operatingCashflow"),
            "industry": info.get("industry"),
            "sector": info.get("sector"),
            "beta": info.get("beta"),
            "rel_strength_vs_sp": round(stock_52w - sp_change, 1),
            "div_yield": round((info.get("trailingAnnualDividendYield") or 0) * 100, 2),
            "52w_high": round(float(high_52), 2),
            "52w_low": round(float(low_52), 2),
            "pct_from_52w_low": round(((float(price) - float(low_52)) / float(low_52)) * 100, 1),
            "pct_chg_today": round((float(prices.iloc[-1]) - float(prices.iloc[-2])) / float(prices.iloc[-2]) * 100, 2),
            "day_low":  round(float(hist["Low"].iloc[-1]),  2),
            "day_high": round(float(hist["High"].iloc[-1]), 2),
            "day_open": round(float(hist["Open"].iloc[-1]), 2),
            "prev_low":  round(float(hist["Low"].iloc[-2]),  2) if len(hist) >= 2 else None,
            "prev_high": round(float(hist["High"].iloc[-2]), 2) if len(hist) >= 2 else None,
            "prev_close": round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else None,
            "prices": prices,
            "rsi_series": rsi_series,
            "volume": volume,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


# ── News ────────────────────────────────────────────────────────────────────

def get_ticker_news(ticker: str, max_items: int = 5) -> list[dict]:
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
        results = []
        for item in news[:max_items]:
            content = item.get("content", {})
            title = content.get("title", "") or item.get("title", "")
            pub = content.get("pubDate", "") or ""
            url = ((content.get("canonicalUrl") or {}).get("url")
                   or (content.get("clickThroughUrl") or {}).get("url")
                   or item.get("link") or "")
            source = ((content.get("provider") or {}).get("displayName")
                      or item.get("publisher") or "")
            results.append({"title": title, "published": pub,
                            "url": url, "source": source})
        return results
    except Exception:
        return []


def get_macro_news(query: str, key: str, days_back: int = 2) -> list[dict]:
    if not key or key == "your_key_here":
        return []
    try:
        from newsapi import NewsApiClient
        client = NewsApiClient(api_key=key)
        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        resp = client.get_everything(
            q=query,
            from_param=from_date,
            language="en",
            sort_by="relevancy",
            page_size=5,
        )
        articles = resp.get("articles", [])
        return [{"title": a.get("title", ""), "source": a.get("source", {}).get("name", "")}
                for a in articles]
    except Exception:
        return []


MACRO_QUERIES = {
    "Iran War / Hormuz": "Iran oil Hormuz strait war shipping",
    "Europe Rearmament": "Europe defense spending NATO rearmament",
    "Rare Earth Decoupling": "rare earth China export ban decoupling US",
    "AI Infrastructure": "artificial intelligence data center infrastructure chip",
    "Nuclear Energy": "nuclear energy SMR uranium power",
}


# ── Market indicators (VIX, SPY, QQQ) ───────────────────────────────────────

def get_market_indicators() -> dict:
    results = {}
    for sym in ["^VIX", "SPY", "QQQ"]:
        snap = get_full_snapshot(sym)
        results[sym] = snap
    return results


# ── Dividend calendar ───────────────────────────────────────────────────────

def get_dividend_info(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info
        cal = t.calendar
        ex_date = None
        div_date = None
        if cal is not None and not (hasattr(cal, "empty") and cal.empty):
            if hasattr(cal, "get"):
                ex_date = cal.get("Ex-Dividend Date")
                div_date = cal.get("Dividend Date")
            elif hasattr(cal, "loc"):
                try:
                    ex_date = cal.loc["Ex-Dividend Date"].iloc[0] if "Ex-Dividend Date" in cal.index else None
                    div_date = cal.loc["Dividend Date"].iloc[0] if "Dividend Date" in cal.index else None
                except Exception:
                    pass
        annual_div = (info.get("trailingAnnualDividendRate") or 0)
        return {
            "ticker": ticker,
            "annual_div": annual_div,
            "ex_date": str(ex_date) if ex_date else None,
            "div_date": str(div_date) if div_date else None,
            "div_yield": round((info.get("trailingAnnualDividendYield") or 0) * 100, 2),
        }
    except Exception:
        return {"ticker": ticker, "annual_div": 0, "ex_date": None, "div_date": None, "div_yield": 0}
