"""
Unified market data client with provider fallback chain.

Priority order (per data type):
  Indicators (RSI/MACD/BB/etc) : Finnhub → Twelve Data → yfinance
  Patterns (candlestick/chart)  : Finnhub → yfinance (patterns.py)
  Support/Resistance            : Finnhub → manual (swing-low calc)
  News + sentiment              : Finnhub → NewsAPI → yfinance
  Fundamentals (FCF/PE/DE)      : Alpha Vantage → yfinance
  Earnings calendar             : Finnhub → yfinance
  Insider activity              : Finnhub only (no fallback needed)

Usage tracking:
  - 429 / rate-limit response → mark provider exhausted, try next
  - Counts tracked per process lifetime (not persisted)
"""
from __future__ import annotations
import os, time, requests, json
from datetime import datetime, date
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

FINNHUB_KEY      = os.getenv("FINNHUB_KEY", "")
TWELVEDATA_KEY   = os.getenv("TWELVEDATA_KEY", "")
ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_KEY", "")
NEWSAPI_KEY      = os.getenv("NEWSAPI_KEY", "")

# ── Rate-limit state (per process) ────────────────────────────────────────────

class _ProviderState:
    def __init__(self, name: str, daily_limit: int, per_min_limit: int):
        self.name        = name
        self.daily_limit = daily_limit
        self.per_min     = per_min_limit
        self.daily_used  = 0
        self.min_used    = 0
        self.min_reset   = time.time() + 60
        self.exhausted   = False   # set True on 429 or daily limit

    def available(self) -> bool:
        if self.exhausted:
            return False
        if self.daily_limit and self.daily_used >= self.daily_limit:
            self.exhausted = True
            return False
        now = time.time()
        if now > self.min_reset:
            self.min_used  = 0
            self.min_reset = now + 60
        if self.per_min and self.min_used >= self.per_min:
            return False   # rate-limited but not exhausted - will free next minute
        return True

    def record_call(self):
        self.daily_used += 1
        self.min_used   += 1

    def on_rate_limit(self):
        print(f"[data_client] {self.name} rate-limited - switching provider")
        self.exhausted = True

_FINNHUB  = _ProviderState("Finnhub",      daily_limit=0,   per_min_limit=60)
_TWELVE   = _ProviderState("TwelveData",   daily_limit=800, per_min_limit=8)
_ALPHA    = _ProviderState("AlphaVantage", daily_limit=25,  per_min_limit=5)
_NEWSAPI  = _ProviderState("NewsAPI",      daily_limit=100, per_min_limit=0)

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _get(url: str, params: dict, state: _ProviderState, timeout=10) -> dict | None:
    if not state.available():
        return None
    try:
        r = requests.get(url, params=params, timeout=timeout)
        state.record_call()
        if r.status_code == 429:
            state.on_rate_limit()
            return None
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

# ── Finnhub calls ──────────────────────────────────────────────────────────────

def _fh(endpoint: str, params: dict) -> dict | None:
    if not FINNHUB_KEY:
        return None
    base = "https://finnhub.io/api/v1"
    return _get(f"{base}/{endpoint}", {**params, "token": FINNHUB_KEY}, _FINNHUB)

def _fh_indicators(ticker: str, indicator: str, resolution="D", count=50) -> dict | None:
    now = int(time.time())
    ago = now - count * 86400 * 2  # extra buffer for weekends
    return _fh("indicator", {
        "symbol": ticker, "resolution": resolution,
        "from": ago, "to": now, "indicator": indicator,
        "timeperiod": 14,
    })

# ── Twelve Data calls ──────────────────────────────────────────────────────────

def _td(endpoint: str, params: dict) -> dict | None:
    if not TWELVEDATA_KEY:
        return None
    base = "https://api.twelvedata.com"
    return _get(f"{base}/{endpoint}", {**params, "apikey": TWELVEDATA_KEY}, _TWELVE)

# ── Alpha Vantage calls ────────────────────────────────────────────────────────

def _av(function: str, params: dict) -> dict | None:
    if not ALPHAVANTAGE_KEY:
        return None
    base = "https://www.alphavantage.co/query"
    return _get(base, {"function": function, **params, "apikey": ALPHAVANTAGE_KEY}, _ALPHA)

# ── yfinance fallback ──────────────────────────────────────────────────────────

def _yf_snapshot(ticker: str) -> dict:
    """Always works - last resort."""
    try:
        import morning_run as mr
        return mr.get_full_snapshot(ticker)
    except Exception:
        return {}

# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def get_indicators(ticker: str) -> dict:
    """
    Returns: { rsi, macd_hist, macd_prev, bb_pct, stoch_k, stoch_d,
               adx, atr, provider }
    Falls back: Finnhub → Twelve Data → yfinance
    """
    result = {"provider": None}

    # ── Twelve Data (cleanest indicator API) ──────────────────────────────────
    if _TWELVE.available() and TWELVEDATA_KEY:
        try:
            def td_ind(ind, **kw):
                return _td(ind, {"symbol": ticker, "interval": "1day",
                                 "outputsize": 30, **kw})

            rsi_r   = td_ind("rsi",  time_period=14)
            macd_r  = td_ind("macd", fast_period=12, slow_period=26, signal_period=9)
            bb_r    = td_ind("bbands", time_period=20, sd=2)
            stoch_r = td_ind("stoch", fast_k_period=14, slow_k_period=3, slow_d_period=3)
            adx_r   = td_ind("adx",  time_period=14)
            atr_r   = td_ind("atr",  time_period=14)

            def val(d, *keys):
                try:
                    v = d
                    for k in keys:
                        v = v[k]
                    return float(v[0] if isinstance(v, list) else v)
                except Exception:
                    return None

            rsi   = val(rsi_r,   "values", 0, "rsi")   if rsi_r   else None
            mhist = val(macd_r,  "values", 0, "macd_hist")  if macd_r  else None
            mprev = val(macd_r,  "values", 1, "macd_hist")  if macd_r  else None
            price = val(bb_r,    "values", 0, "close")      if bb_r    else None
            bbu   = val(bb_r,    "values", 0, "upper_band") if bb_r    else None
            bbl   = val(bb_r,    "values", 0, "lower_band") if bb_r    else None
            bb_pct = round((price - bbl) / (bbu - bbl) * 100, 1) if all([price, bbu, bbl]) else None
            sk    = val(stoch_r, "values", 0, "slow_k") if stoch_r else None
            sd    = val(stoch_r, "values", 0, "slow_d") if stoch_r else None
            adx   = val(adx_r,  "values", 0, "adx")    if adx_r   else None
            atr   = val(atr_r,  "values", 0, "atr")    if atr_r   else None

            if rsi is not None:
                result.update({
                    "rsi": rsi, "macd_hist": mhist, "macd_prev": mprev,
                    "bb_pct": bb_pct, "stoch_k": sk, "stoch_d": sd,
                    "adx": adx, "atr": atr, "provider": "TwelveData",
                })
                return result
        except Exception:
            pass

    # ── Finnhub ───────────────────────────────────────────────────────────────
    if FINNHUB_KEY and _FINNHUB.available():
        try:
            rsi_r  = _fh_indicators(ticker, "rsi")
            macd_r = _fh_indicators(ticker, "macd")
            bb_r   = _fh_indicators(ticker, "bbands")

            def fh_last(d, key):
                try:
                    return float(d[key][-1])
                except Exception:
                    return None

            rsi = fh_last(rsi_r, "rsi") if rsi_r else None
            if rsi is not None:
                mhist = fh_last(macd_r, "macdHist") if macd_r else None
                mprev = float(macd_r["macdHist"][-2]) if (macd_r and len(macd_r.get("macdHist", [])) > 1) else None
                upper = fh_last(bb_r, "upperband") if bb_r else None
                lower = fh_last(bb_r, "lowerband") if bb_r else None
                mid   = fh_last(bb_r, "middleband") if bb_r else None
                bb_pct = round((mid - lower) / (upper - lower) * 100, 1) if all([mid, upper, lower]) else None
                result.update({
                    "rsi": rsi, "macd_hist": mhist, "macd_prev": mprev,
                    "bb_pct": bb_pct, "stoch_k": None, "stoch_d": None,
                    "adx": None, "atr": None, "provider": "Finnhub",
                })
                return result
        except Exception:
            pass

    # ── yfinance fallback ─────────────────────────────────────────────────────
    snap = _yf_snapshot(ticker)
    result.update({
        "rsi":       snap.get("rsi"),
        "macd_hist": snap.get("macd_hist"),
        "macd_prev": snap.get("macd_prev"),
        "bb_pct":    snap.get("bb_pct"),
        "stoch_k":   None,
        "stoch_d":   None,
        "adx":       None,
        "atr":       None,
        "provider":  "yfinance",
    })
    return result


def get_support_resistance(ticker: str) -> dict:
    """
    Returns: { support: [levels], resistance: [levels], provider }
    Falls back: Finnhub → manual swing-low calc
    """
    # ── Finnhub S/R ───────────────────────────────────────────────────────────
    if FINNHUB_KEY and _FINNHUB.available():
        try:
            r = _fh("scan/support-resistance", {"symbol": ticker, "resolution": "D"})
            if r and r.get("levels"):
                levels = sorted([float(x) for x in r["levels"]])
                snap   = _yf_snapshot(ticker)
                price  = snap.get("price", 0)
                return {
                    "support":    [l for l in levels if l < price],
                    "resistance": [l for l in levels if l > price],
                    "provider":   "Finnhub",
                }
        except Exception:
            pass

    # ── Manual fallback from yfinance OHLC ───────────────────────────────────
    try:
        import yfinance as yf
        import numpy as np
        df = yf.download(ticker, period="6mo", interval="1d",
                         progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        lows   = df["Low"].values.flatten().astype(float)
        highs  = df["High"].values.flatten().astype(float)
        closes = df["Close"].values.flatten().astype(float)
        price  = float(closes[-1])

        support, resistance = [], []
        for i in range(3, len(lows) - 3):
            if lows[i] == min(lows[i-3:i+4]):
                support.append(round(float(lows[i]), 2))
            if highs[i] == max(highs[i-3:i+4]):
                resistance.append(round(float(highs[i]), 2))

        support    = sorted(set([s for s in support    if s < price]), reverse=True)[:5]
        resistance = sorted(set([r for r in resistance if r > price]))[:5]
        return {"support": support, "resistance": resistance, "provider": "yfinance-manual"}
    except Exception:
        return {"support": [], "resistance": [], "provider": "none"}


def get_candlestick_patterns(ticker: str) -> list[dict]:
    """
    Returns list of { pattern, signal, description }
    Finnhub only (no fallback - yfinance has no pattern API)
    """
    if not (FINNHUB_KEY and _FINNHUB.available()):
        return []
    try:
        r = _fh("scan/pattern", {"symbol": ticker, "resolution": "D"})
        if not r or not r.get("points"):
            return []
        results = []
        for pt in r["points"]:
            results.append({
                "pattern":     pt.get("patternname", ""),
                "signal":      pt.get("patterntype", ""),
                "aprice":      pt.get("aprice"),
                "end_date":    pt.get("atime"),
            })
        return results
    except Exception:
        return []


def get_news_sentiment(ticker: str, limit: int = 10) -> list[dict]:
    """
    Returns list of { headline, source, sentiment, url, datetime }
    Falls back: Finnhub → yfinance news
    """
    # ── Finnhub company news ─────────────────────────────────────────────────
    if FINNHUB_KEY and _FINNHUB.available():
        try:
            today = date.today().isoformat()
            week  = date.fromordinal(date.today().toordinal() - 7).isoformat()
            r = _fh("company-news", {"symbol": ticker, "from": week, "to": today})
            if r and isinstance(r, list):
                out = []
                for a in r[:limit]:
                    out.append({
                        "headline":  a.get("headline", ""),
                        "source":    a.get("source", ""),
                        "sentiment": a.get("sentiment", None),  # finnhub adds this
                        "url":       a.get("url", ""),
                        "datetime":  a.get("datetime", 0),
                        "provider":  "Finnhub",
                    })
                if out:
                    return out
        except Exception:
            pass

    # ── yfinance fallback ─────────────────────────────────────────────────────
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        news = t.news or []
        return [{
            "headline":  n.get("title", ""),
            "source":    n.get("publisher", ""),
            "sentiment": None,
            "url":       n.get("link", ""),
            "datetime":  n.get("providerPublishTime", 0),
            "provider":  "yfinance",
        } for n in news[:limit]]
    except Exception:
        return []


def get_earnings_calendar(ticker: str) -> dict:
    """
    Returns: { next_date, days_away, eps_est, rev_est, provider }
    Falls back: Finnhub → yfinance
    """
    if FINNHUB_KEY and _FINNHUB.available():
        try:
            today = date.today().isoformat()
            ahead = date.fromordinal(date.today().toordinal() + 90).isoformat()
            r = _fh("calendar/earnings", {"from": today, "to": ahead, "symbol": ticker})
            if r and r.get("earningsCalendar"):
                e = r["earningsCalendar"][0]
                d = e.get("date", "")
                days = (date.fromisoformat(d) - date.today()).days if d else None
                return {
                    "next_date": d,
                    "days_away": days,
                    "eps_est":   e.get("epsEstimate"),
                    "rev_est":   e.get("revenueEstimate"),
                    "provider":  "Finnhub",
                }
        except Exception:
            pass

    try:
        import yfinance as yf
        t    = yf.Ticker(ticker)
        cal  = t.calendar
        if cal is not None and hasattr(cal, 'get'):
            d = cal.get("Earnings Date")
            if d and len(d) > 0:
                ed   = d[0]
                days = (ed.date() - date.today()).days if hasattr(ed, 'date') else None
                return {"next_date": str(ed)[:10], "days_away": days,
                        "eps_est": None, "rev_est": None, "provider": "yfinance"}
    except Exception:
        pass

    return {"next_date": None, "days_away": None, "eps_est": None,
            "rev_est": None, "provider": "none"}


def get_insider_activity(ticker: str) -> list[dict]:
    """
    Returns list of { name, shares, price, transaction, date }
    Finnhub only.
    """
    if not (FINNHUB_KEY and _FINNHUB.available()):
        return []
    try:
        r = _fh("stock/insider-transactions", {"symbol": ticker})
        if not r or not r.get("data"):
            return []
        out = []
        for tx in r["data"][:10]:
            out.append({
                "name":        tx.get("name", ""),
                "shares":      tx.get("share", 0),
                "price":       tx.get("transactionPrice", 0),
                "transaction": tx.get("transactionCode", ""),
                "date":        tx.get("transactionDate", ""),
            })
        return out
    except Exception:
        return []


def get_fundamentals(ticker: str) -> dict:
    """
    Returns: { pe, eps, fcf, de_ratio, revenue, profit_margin, provider }
    Falls back: Alpha Vantage → yfinance
    """
    # ── Alpha Vantage ─────────────────────────────────────────────────────────
    if ALPHAVANTAGE_KEY and _ALPHA.available():
        try:
            ov = _av("OVERVIEW", {"symbol": ticker})
            if ov and ov.get("Symbol"):
                def safe(k):
                    try: return float(ov[k])
                    except Exception: return None
                return {
                    "pe":            safe("PERatio"),
                    "eps":           safe("EPS"),
                    "fcf":           safe("OperatingCashflowTTM"),
                    "de_ratio":      safe("DebtToEquityRatio"),
                    "revenue":       safe("RevenueTTM"),
                    "profit_margin": safe("ProfitMargin"),
                    "provider":      "AlphaVantage",
                }
        except Exception:
            pass

    # ── yfinance fallback ─────────────────────────────────────────────────────
    try:
        import yfinance as yf
        t   = yf.Ticker(ticker)
        inf = t.info or {}
        fcf = inf.get("freeCashflow") or inf.get("operatingCashflow")
        return {
            "pe":            inf.get("trailingPE") or inf.get("forwardPE"),
            "eps":           inf.get("trailingEps"),
            "fcf":           fcf,
            "de_ratio":      inf.get("debtToEquity"),
            "revenue":       inf.get("totalRevenue"),
            "profit_margin": inf.get("profitMargins"),
            "provider":      "yfinance",
        }
    except Exception:
        return {"pe": None, "eps": None, "fcf": None, "de_ratio": None,
                "revenue": None, "profit_margin": None, "provider": "none"}


def get_macro_news(query: str, page_size: int = 5) -> list[dict]:
    """
    Pull macro narrative news from NewsAPI.
    Falls back: NewsAPI → Finnhub general news (filtered)
    """
    if NEWSAPI_KEY and _NEWSAPI.available():
        try:
            r = requests.get("https://newsapi.org/v2/everything",
                             params={"q": query, "apiKey": NEWSAPI_KEY,
                                     "pageSize": page_size, "language": "en",
                                     "sortBy": "publishedAt"}, timeout=10)
            _NEWSAPI.record_call()
            if r.status_code == 429:
                _NEWSAPI.on_rate_limit()
            elif r.status_code == 200:
                data = r.json()
                return [{"title": a["title"], "source": a["source"]["name"],
                         "url": a["url"], "publishedAt": a["publishedAt"],
                         "provider": "NewsAPI"}
                        for a in data.get("articles", [])[:page_size]]
        except Exception:
            pass

    # Fallback: Finnhub general feed, filter by query keywords
    if FINNHUB_KEY and _FINNHUB.available():
        try:
            r = _fh("news", {"category": "general"})
            if r and isinstance(r, list):
                kw = query.lower().split()
                matches = [n for n in r if any(k in n.get("headline", "").lower() for k in kw)]
                return [{"title": n.get("headline", ""), "source": n.get("source", ""),
                         "url": n.get("url", ""), "publishedAt": n.get("datetime", 0),
                         "provider": "Finnhub-general"}
                        for n in matches[:page_size]]
        except Exception:
            pass
    return []


def status() -> dict:
    """Return current usage state for all providers."""
    return {
        "Finnhub":      {"daily_used": _FINNHUB.daily_used, "limit": "60/min, no daily",
                         "exhausted": _FINNHUB.exhausted,   "key": bool(FINNHUB_KEY)},
        "TwelveData":   {"daily_used": _TWELVE.daily_used,  "limit": "800/day, 8/min",
                         "exhausted": _TWELVE.exhausted,    "key": bool(TWELVEDATA_KEY)},
        "AlphaVantage": {"daily_used": _ALPHA.daily_used,   "limit": "25/day",
                         "exhausted": _ALPHA.exhausted,     "key": bool(ALPHAVANTAGE_KEY)},
        "NewsAPI":      {"daily_used": _NEWSAPI.daily_used, "limit": "100/day",
                         "exhausted": _NEWSAPI.exhausted,   "key": bool(NEWSAPI_KEY)},
    }
