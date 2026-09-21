"""
macro_data.py - Free macro regime data.

Two sources, both $0:
  - yfinance index tickers: ^TNX (10y yield), ^IRX (13-week yield), ^FVX (5y)
    → yield-curve spread and inversion flag with NO key at all
  - FRED (free API key from fred.stlouisfed.org): CPI YoY, Fed funds,
    unemployment. Skipped gracefully without FRED_API_KEY.

24h cache in macro_cache.json - one fetch per day, zero recurring cost.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from data_fetch import load_env

load_env()

BASE = Path(__file__).resolve().parents[1]
CACHE = BASE / "macro_cache.json"
CACHE_TTL = 24 * 3600

FRED_SERIES = {
    "cpi_yoy": ("CPIAUCSL", "pc1"),       # CPI, percent change from year ago
    "fed_funds": ("FEDFUNDS", "lin"),
    "unemployment": ("UNRATE", "lin"),
}


def _yields() -> dict:
    """Treasury yields via yfinance index tickers (no key needed)."""
    import yfinance as yf
    out = {}
    for key, tk in (("y10", "^TNX"), ("y5", "^FVX"), ("m3", "^IRX")):
        try:
            hist = yf.Ticker(tk).history(period="5d", interval="1d")
            if not hist.empty:
                out[key] = round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass
    return out


def _fred(series: str, units: str):
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series, "api_key": key, "file_type": "json",
                    "units": units, "sort_order": "desc", "limit": 1},
            timeout=12,
        )
        obs = r.json().get("observations", [])
        if obs and obs[0]["value"] not in (".", ""):
            return round(float(obs[0]["value"]), 2)
    except Exception:
        pass
    return None


def get_macro(force: bool = False) -> dict:
    """Macro snapshot with 24h cache."""
    if CACHE.exists() and not force:
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - cached.get("_fetched", 0) < CACHE_TTL:
                return cached
        except Exception:
            pass

    yields = _yields()
    y10, m3 = yields.get("y10"), yields.get("m3")
    spread = round(y10 - m3, 2) if (y10 is not None and m3 is not None) else None

    out = {
        "_fetched": time.time(),
        "yield_10y": y10,
        "yield_5y": yields.get("y5"),
        "yield_3m": m3,
        "curve_spread_10y_3m": spread,
        "curve_inverted": (spread is not None and spread < 0),
        "cpi_yoy": _fred(*FRED_SERIES["cpi_yoy"]),
        "fed_funds": _fred(*FRED_SERIES["fed_funds"]),
        "unemployment": _fred(*FRED_SERIES["unemployment"]),
        "fred_available": bool(os.environ.get("FRED_API_KEY")),
    }

    # One-line regime note the dashboard and briefing can show verbatim
    notes = []
    if spread is not None:
        notes.append("yield curve INVERTED - historical recession signal" if spread < 0
                     else f"yield curve normal (+{spread:.2f})")
    if out["cpi_yoy"] is not None:
        notes.append(f"CPI {out['cpi_yoy']:.1f}% YoY")
    if out["fed_funds"] is not None:
        notes.append(f"Fed funds {out['fed_funds']:.2f}%")
    if out["unemployment"] is not None:
        notes.append(f"unemployment {out['unemployment']:.1f}%")
    out["regime_note"] = " | ".join(notes) if notes else "macro data unavailable"

    try:
        CACHE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception:
        pass
    return out
