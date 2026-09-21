"""
options_flow.py - Options flow + gamma exposure tracker
Source: yfinance options chain (free, no API key)
Cache: options_flow_cache.json (4hr TTL - options change intraday)

What it measures:
  Put/Call volume ratio  - who's betting which direction (near-term sentiment)
  Put/Call OI ratio      - where money is PARKED (dealer positioning)
  Key gamma strikes      - highest OI strikes = dealer magnet levels (price pins here)
  IV rank (approx)       - current ATM IV vs near-term expiry spread

Signal tiers:
  BULLISH_FLOW   - calls dominating vol + OI (PCR_vol < 0.7, PCR_OI < 0.8)
  UNUSUAL_CALLS  - call vol > 3x put vol AND OI also bullish (whale accumulation)
  BEARISH_FLOW   - puts dominating (PCR_vol > 1.3 OR PCR_OI > 1.5)
  HEDGING        - PCR_OI high near earnings (institutions buying puts = fear, not prediction)
  NEUTRAL        - balanced flow, no dominant signal

Why this matters:
  Market makers MUST delta-hedge. When call OI is massive at a strike,
  MMs buy stock as price rises toward it → self-fulfilling magnet.
  Same in reverse for put walls. These levels are real, not coincidence.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE = Path(__file__).resolve().parents[1]
CACHE = BASE / "options_flow_cache.json"
CACHE_TTL_HOURS = 4  # options flow changes intraday - shorter TTL than insider

socket.setdefaulttimeout(12)


# ── signal classification ────────────────────────────────────────────────────

def _classify_flow(
    pcr_vol: float,
    pcr_oi: float,
    call_vol: int,
    put_vol: int,
    days_to_earnings: int | None,
) -> tuple[str, str]:
    """
    Returns (signal, note).
    Earnings proximity matters: high put OI near earnings = hedging not bearish.
    """
    near_earnings = days_to_earnings is not None and 0 <= days_to_earnings <= 14

    # UNUSUAL_CALLS: call vol > 3x put vol, OI also skewed bullish
    if call_vol > 0 and put_vol >= 0:
        call_dom = call_vol / (put_vol + 1)
        if call_dom >= 3.0 and pcr_oi < 0.8:
            return (
                "UNUSUAL_CALLS",
                f"Calls {call_dom:.1f}x puts - unusual accumulation. "
                f"P/C vol {pcr_vol:.2f} | OI {pcr_oi:.2f}",
            )

    # BEARISH_FLOW
    if pcr_vol > 1.5 or pcr_oi > 1.8:
        if near_earnings:
            return (
                "HEDGING",
                f"High put OI (PCR {pcr_oi:.2f}) likely pre-earnings hedge, not directional. "
                f"Earnings in {days_to_earnings}d.",
            )
        return (
            "BEARISH_FLOW",
            f"Puts dominating - P/C vol {pcr_vol:.2f} | OI {pcr_oi:.2f}. "
            "Institutional protection buying or directional bear bet.",
        )

    # BULLISH_FLOW
    if pcr_vol < 0.7 and pcr_oi < 0.8:
        return (
            "BULLISH_FLOW",
            f"Calls dominating - P/C vol {pcr_vol:.2f} | OI {pcr_oi:.2f}. "
            "Bullish options positioning.",
        )

    # Mild bullish
    if pcr_vol < 0.85 and pcr_oi < 0.9:
        return (
            "MILD_BULLISH",
            f"Slightly call-skewed - P/C vol {pcr_vol:.2f} | OI {pcr_oi:.2f}.",
        )

    return (
        "NEUTRAL",
        f"Balanced flow - P/C vol {pcr_vol:.2f} | OI {pcr_oi:.2f}.",
    )


# ── max pain calculation ─────────────────────────────────────────────────────

def calc_max_pain(calls_df, puts_df) -> float | None:
    """
    Max pain = strike where total intrinsic value paid to option buyers is MINIMUM.
    = strike where market makers (option sellers) keep maximum premium.
    = where price gravitates by expiry (institutions pin it here).

    Math:
      For each candidate strike S:
        call_pain = sum of (S - K) * OI * 100 for all calls with K < S  (ITM calls)
        put_pain  = sum of (K - S) * OI * 100 for all puts  with K > S  (ITM puts)
        total_pain(S) = call_pain + put_pain
      Max pain strike = S with MINIMUM total_pain
    """
    import pandas as pd

    try:
        calls = calls_df.fillna(0)
        puts  = puts_df.fillna(0)
        all_strikes = sorted(set(
            calls["strike"].tolist() + puts["strike"].tolist()
        ))
        if not all_strikes:
            return None

        call_strikes = calls["strike"].values
        call_oi      = calls["openInterest"].values
        put_strikes  = puts["strike"].values
        put_oi       = puts["openInterest"].values

        min_pain = float("inf")
        max_pain_strike = None

        for s in all_strikes:
            cp = sum(
                (s - k) * oi * 100
                for k, oi in zip(call_strikes, call_oi)
                if k < s and oi > 0
            )
            pp = sum(
                (k - s) * oi * 100
                for k, oi in zip(put_strikes, put_oi)
                if k > s and oi > 0
            )
            total = cp + pp
            if total < min_pain:
                min_pain = total
                max_pain_strike = s

        return float(max_pain_strike) if max_pain_strike is not None else None

    except Exception:
        return None


def _max_pain_signal(price: float, mp: float, days_to_exp: int) -> str:
    """Human-readable drift signal based on distance from max pain."""
    if price <= 0 or mp <= 0:
        return ""
    dist_pct = ((mp - price) / price) * 100
    urgency = "TODAY" if days_to_exp <= 1 else f"{days_to_exp}d"
    if dist_pct > 4:
        return f"DRIFT UP → ${mp:.0f} ({dist_pct:+.1f}%, exp {urgency})"
    elif dist_pct < -4:
        return f"DRIFT DOWN → ${mp:.0f} ({dist_pct:+.1f}%, exp {urgency})"
    elif abs(dist_pct) <= 1.5:
        return f"PINNED near ${mp:.0f} (exp {urgency})"
    elif dist_pct > 0:
        return f"mild drift up → ${mp:.0f} ({dist_pct:+.1f}%, exp {urgency})"
    else:
        return f"mild drift down → ${mp:.0f} ({dist_pct:+.1f}%, exp {urgency})"


# ── main fetch ───────────────────────────────────────────────────────────────

def fetch_options_flow(
    ticker: str,
    num_expiries: int = 3,
    days_to_earnings: int | None = None,
) -> dict:
    """
    Fetch and analyze options flow for one ticker.

    Returns dict with:
      ticker, price, signal, note, pcr_vol, pcr_oi,
      call_vol, put_vol, call_oi, put_oi,
      key_strikes (list of {strike, oi, dist_pct}),
      atm_iv, fetched_at
    """
    def _empty(signal="ERROR", note=""):
        return {
            "ticker": ticker, "price": None, "signal": signal, "note": note,
            "pcr_vol": None, "pcr_oi": None,
            "call_vol": 0, "put_vol": 0, "call_oi": 0, "put_oi": 0,
            "key_strikes": [], "atm_iv": None,
            "max_pain": None, "max_pain_exp": None, "max_pain_days": None,
            "max_pain_dist_pct": None, "max_pain_signal": "",
            "fetched_at": datetime.now().isoformat(),
        }

    try:
        t = yf.Ticker(ticker)
        price = t.fast_info.last_price
        if not price or price <= 0:
            return _empty("ERROR", "No price data")

        expiries = t.options
        if not expiries:
            return _empty("NO_OPTIONS", "No options listed (ETF or no chain)")

    except Exception as e:
        return _empty("ERROR", str(e))

    # Aggregate across nearest N expiries (most liquid, most signal)
    total_call_vol = 0
    total_put_vol  = 0
    total_call_oi  = 0
    total_put_oi   = 0
    strike_oi: dict[float, float] = {}  # strike → total OI across all expiries
    atm_iv_samples: list[float] = []

    # Max pain - nearest expiry only (weekly pinning behavior)
    max_pain: float | None = None
    max_pain_exp: str | None = None
    max_pain_days: int | None = None

    for i, exp in enumerate(expiries[:num_expiries]):
        try:
            chain = t.option_chain(exp)
            calls = chain.calls.fillna(0)
            puts  = chain.puts.fillna(0)

            total_call_vol += int(calls["volume"].sum())
            total_put_vol  += int(puts["volume"].sum())
            total_call_oi  += int(calls["openInterest"].sum())
            total_put_oi   += int(puts["openInterest"].sum())

            # Track OI by strike for gamma wall detection
            for _, row in calls.iterrows():
                s = float(row["strike"])
                strike_oi[s] = strike_oi.get(s, 0) + float(row["openInterest"])
            for _, row in puts.iterrows():
                s = float(row["strike"])
                strike_oi[s] = strike_oi.get(s, 0) + float(row["openInterest"])

            # ATM IV: nearest strike to current price, first expiry only
            if i == 0:
                near_calls = calls.iloc[
                    (calls["strike"] - price).abs().argsort()[:3]
                ]
                ivs = near_calls["impliedVolatility"].replace(0, float("nan")).dropna()
                atm_iv_samples.extend(ivs.tolist())

                # Max pain: nearest expiry only (most relevant for weekly pin)
                mp = calc_max_pain(calls, puts)
                if mp is not None:
                    max_pain = mp
                    max_pain_exp = exp
                    try:
                        max_pain_days = max(
                            1, (datetime.strptime(exp, "%Y-%m-%d") - datetime.now()).days + 1
                        )
                    except Exception:
                        max_pain_days = None

        except Exception:
            continue  # bad expiry data - skip, don't abort

    if total_call_vol == 0 and total_call_oi == 0:
        return _empty("NO_DATA", "Options chain returned empty data")

    pcr_vol = round(total_put_vol / max(total_call_vol, 1), 3)
    pcr_oi  = round(total_put_oi  / max(total_call_oi,  1), 3)
    atm_iv  = round(sum(atm_iv_samples) / len(atm_iv_samples) * 100, 1) if atm_iv_samples else None

    # Top gamma strikes (dealer magnet levels)
    key_strikes = sorted(
        [
            {
                "strike": s,
                "oi": int(oi),
                "dist_pct": round(((s - price) / price) * 100, 1),
            }
            for s, oi in strike_oi.items()
            if oi > 0
        ],
        key=lambda x: x["oi"],
        reverse=True,
    )[:6]

    signal, note = _classify_flow(
        pcr_vol, pcr_oi, total_call_vol, total_put_vol, days_to_earnings
    )

    # Max pain derived signals
    mp_dist_pct = round(((max_pain - price) / price) * 100, 1) if max_pain and price else None
    mp_signal   = _max_pain_signal(price, max_pain, max_pain_days or 0) if max_pain else ""

    return {
        "ticker":    ticker,
        "price":     round(price, 2),
        "signal":    signal,
        "note":      note,
        "pcr_vol":   pcr_vol,
        "pcr_oi":    pcr_oi,
        "call_vol":  total_call_vol,
        "put_vol":   total_put_vol,
        "call_oi":   total_call_oi,
        "put_oi":    total_put_oi,
        "key_strikes": key_strikes,
        "atm_iv":    atm_iv,
        # ── Max pain ──────────────────────────────────────────────────────
        "max_pain":         max_pain,          # strike price (float)
        "max_pain_exp":     max_pain_exp,      # expiry date string
        "max_pain_days":    max_pain_days,     # days until expiry
        "max_pain_dist_pct": mp_dist_pct,      # % distance from current price
        "max_pain_signal":  mp_signal,         # human-readable drift signal
        "fetched_at": datetime.now().isoformat(),
    }


# ── batch with cache ─────────────────────────────────────────────────────────

def get_options_flows(
    tickers: list[str],
    force_refresh: bool = False,
    verbose: bool = True,
    dte_map: dict[str, int | None] | None = None,
) -> dict[str, dict]:
    """
    Batch fetch with 4hr cache.
    dte_map: {ticker: days_to_earnings} - used to detect pre-earnings hedging.
    Returns {ticker: flow_dict}.
    """
    cache: dict = {}
    if CACHE.exists() and not force_refresh:
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    ttl = timedelta(hours=CACHE_TTL_HOURS)
    results: dict[str, dict] = {}
    to_fetch: list[str] = []

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

    for ticker in to_fetch:
        if verbose:
            print(f"  [options] fetching {ticker}...", flush=True)
        dte = (dte_map or {}).get(ticker)
        result = fetch_options_flow(ticker, days_to_earnings=dte)
        results[ticker] = result
        cache[ticker] = result

    if to_fetch:
        try:
            CACHE.write_text(json.dumps(cache, indent=2, default=str), encoding="utf-8")
            CACHE.chmod(0o600)
        except Exception:
            pass

    return results


# ── display ──────────────────────────────────────────────────────────────────

SIGNAL_ICONS = {
    "UNUSUAL_CALLS": "🚀",
    "BULLISH_FLOW":  "🟢",
    "MILD_BULLISH":  "🟡",
    "NEUTRAL":       "⚪",
    "HEDGING":       "🛡",
    "BEARISH_FLOW":  "🔴",
    "NO_OPTIONS":    "-",
    "NO_DATA":       "-",
    "ERROR":         "❌",
}

SIGNAL_COLORS = {
    "UNUSUAL_CALLS": "bold magenta",
    "BULLISH_FLOW":  "bold green",
    "MILD_BULLISH":  "yellow",
    "NEUTRAL":       "white",
    "HEDGING":       "cyan",
    "BEARISH_FLOW":  "bold red",
}


def format_flow_line(flow: dict) -> str:
    """Single-line summary for terminal output."""
    signal = flow.get("signal", "ERROR")
    icon = SIGNAL_ICONS.get(signal, "?")
    ticker = flow.get("ticker", "???")
    pcr_v = flow.get("pcr_vol")
    pcr_o = flow.get("pcr_oi")
    atm_iv = flow.get("atm_iv")

    parts = [f"{icon} {ticker:6s} [{signal:15s}]"]
    if pcr_v is not None:
        parts.append(f"P/C vol {pcr_v:.2f}")
    if pcr_o is not None:
        parts.append(f"OI {pcr_o:.2f}")
    if atm_iv is not None:
        parts.append(f"ATM IV {atm_iv:.0f}%")
    parts.append(f"  {flow.get('note', '')[:60]}")
    return "  ".join(parts)


def format_strikes(flow: dict, max_show: int = 4) -> str:
    """Format key gamma strikes as compact string."""
    strikes = flow.get("key_strikes", [])[:max_show]
    if not strikes:
        return ""
    parts = []
    for s in strikes:
        dist = s["dist_pct"]
        arrow = "↑" if dist > 0 else "↓" if dist < 0 else "●"
        parts.append(f"${s['strike']:.0f}{arrow}({dist:+.0f}%)")
    return "Gamma walls: " + "  ".join(parts)


def format_max_pain_line(flow: dict) -> str:
    """Compact max pain line for display."""
    mp = flow.get("max_pain")
    mp_sig = flow.get("max_pain_signal", "")
    mp_days = flow.get("max_pain_days")
    mp_dist = flow.get("max_pain_dist_pct")
    if not mp:
        return ""
    exp_str = f"exp {mp_days}d" if mp_days else ""
    dist_str = f"{mp_dist:+.1f}%" if mp_dist is not None else ""
    return f"Max pain ${mp:.0f} ({dist_str}, {exp_str}) → {mp_sig}"


def print_report(flows: dict[str, dict]) -> None:
    print()
    print("📊  OPTIONS FLOW + MAX PAIN ANALYSIS")
    print("=" * 80)
    print("  P/C vol < 0.7 = calls dominating | P/C > 1.3 = puts dominating")
    print("  Max pain = strike where most options expire worthless → institutions pin price here")
    print("  Gamma walls = highest OI strikes → dealer hedging magnets")
    print()

    actionable = {t: f for t, f in flows.items()
                  if f["signal"] in ("UNUSUAL_CALLS", "BULLISH_FLOW", "BEARISH_FLOW")}
    rest = {t: f for t, f in flows.items() if t not in actionable}

    if actionable:
        print("  SIGNAL:")
        for ticker, flow in actionable.items():
            print("  " + format_flow_line(flow))
            strikes_str = format_strikes(flow)
            if strikes_str:
                print(f"          ↳ {strikes_str}")
            mp_line = format_max_pain_line(flow)
            if mp_line:
                print(f"          ↳ {mp_line}")
        print()

    print("  ALL POSITIONS:")
    for ticker, flow in {**actionable, **rest}.items():
        mp = flow.get("max_pain")
        mp_dist = flow.get("max_pain_dist_pct")
        mp_days = flow.get("max_pain_days")
        price = flow.get("price", 0) or 0
        mp_str = f"  MP${mp:.0f}({mp_dist:+.1f}%,{mp_days}d)" if mp and mp_dist is not None else ""
        print("  " + format_flow_line(flow) + mp_str)
    print()


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    force = "--refresh" in args
    tickers_arg = [a for a in args if not a.startswith("--")]

    if not tickers_arg:
        tickers_arg = [
            "BJ", "CRM", "EPD", "GLD", "MDT", "MP", "NKE", "NOC", "RTX",
            "AAPL", "AMD", "AMZN", "ASML", "BBAI", "GOOGL", "META",
            "MSFT", "NFLX", "NVDA", "NVO", "TSM",
        ]

    flows = get_options_flows(tickers_arg, force_refresh=force, verbose=True)
    print_report(flows)
