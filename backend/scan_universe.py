#!/usr/bin/env python3
"""
Daily Universe Scanner - runs at 8:30 AM MST via cron.
Scans ~350 stocks across macro-relevant sectors.
Scores each with 180-pt algorithm + patterns + earnings check.
Saves top candidates to scan_results.json.
Updates watchlist.json (auto-add qualifying, auto-remove stale).

Usage:
    python3 scan_universe.py              # Full scan (~5-8 min)
    python3 scan_universe.py --quick      # SP500 top 100 only (~2 min)
    python3 scan_universe.py --test       # 20 tickers, verify setup
"""

from __future__ import annotations
import json
import socket
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date as _date, timezone, timedelta
from pathlib import Path
from typing import Optional

socket.setdefaulttimeout(12)

import yfinance as yf

BASE = Path(__file__).resolve().parents[1]
RESULTS_FILE   = BASE / "scan_results.json"
WATCHLIST_FILE = BASE / "watchlist.json"
POSITIONS_FILE = BASE / "positions.json"

# ── Universe ───────────────────────────────────────────────────────────────────
# Curated by macro narrative + sector + thesis areas.
# Refreshed here manually when new sectors become relevant.

SP500_CORE = [
    # Mega-cap / broad market anchors
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
    "UNH","XOM","MA","JNJ","PG","HD","AVGO","MRK","ABBV","KO",
    "PEP","LLY","COST","WMT","CVX","ADBE","NFLX","ACN","MCD","TMO",
    "CSCO","ABT","DHR","TXN","QCOM","UNP","PM","HON","GE","LOW",
    "INTU","AMGN","ISRG","BKNG","GS","SPGI","SYK","GILD","AXP","CAT",
    "RTX","LMT","DE","MDLZ","PLD","AMT","DUK","SO","NEE","D",
    "CL","EL","ZTS","REGN","VRTX","BIIB","ILMN","MRNA","IDXX","A",
]

SEMIS_AI = [
    # Semiconductors + AI infrastructure - core thesis
    "INTC","MU","AMAT","KLAC","LRCX","ASML","TSM","AMD","NVDA","AVGO",
    "MRVL","SMCI","ARM","ON","WOLF","SWKS","QRVO","TER","ENTG","ONTO",
    "CAMT","AEHR","ACLS","COHU","FORM","ICHR","MKSI","RMBS","SITM","SLAB",
    "MPWR","ALGM","AMBA","AXTI","DIOD","IOSP","MCHP","MTSI","NXPI","POWI",
    "SYNA","TOWR","VSH","WOLF","XPER","ARIS","CRUS","HIMX","IMOS","LSCC",
]

DEFENSE_AEROSPACE = [
    # Defense - Iran war + Europe rearmament thesis
    "RTX","NOC","LMT","GD","BA","HII","TDG","KTOS","LDOS","SAIC",
    "CACI","BAH","DRS","AXON","PLTR","RCAT","JOBY","ACHR","ASTS","RDW",
    "BWXT","CVW","HXL","MOOG","HEICO","TransDigm","SPR","AIR","TGI","DRS",
    "MSCI","KTOS","AVAV","FLIR","KRATOS","VSAT","MAXR","DigitalGlobe",
]

ENERGY_MATERIALS = [
    # Energy / Iran-Hormuz / rare earth / nuclear
    "EPD","ET","KMI","ENB","WMB","OKE","MMP","PAA","TRGP","DT",
    "XOM","CVX","COP","EOG","PXD","DVN","MRO","HES","SLB","HAL",
    "MP","LITE","REE","NB","USA","UUUU","DNN","CCJ","LEU","NNE",
    "SMR","OKLO","NANO","BWXT","CEG","VST","NRG","ETR","PEG","EXC",
    "GLD","SLV","GDX","GOLD","NEM","AEM","WPM","FNV","KGC","PAAS",
]

HEALTHCARE_BIOTECH = [
    # Healthcare + GLP-1 + medtech
    "NVO","LLY","VRTX","REGN","AMGN","BIIB","GILD","MRNA","BNTX","PFE",
    "MDT","ABT","BSX","SYK","EW","DXCM","ISRG","RMD","HOLX","PODD",
    "TDOC","HIMS","NTLA","CRSP","BEAM","EDIT","BLUE","FATE","ALNY","SRPT",
    "INCY","SGEN","EXEL","BMRN","ARWR","AGEN","IMVT","KYMR","ROIV","RXRX",
]

CONSUMER_RETAIL = [
    # Oversold consumer / retail bounce plays
    "NKE","LULU","DECK","ONON","SKX","RL","PVH","HBI","UA","COLM",
    "COST","BJ","WMT","TGT","ROST","TJX","BURL","GPS","ANF","AEO",
    "SBUX","MCD","CMG","DPZ","YUM","QSR","DINE","DRI","TXRH","WING",
]

FINTECH_FINANCE = [
    # Financial / fintech
    "V","MA","PYPL","SQ","AFRM","UPST","SOFI","NU","COIN","HOOD",
    "GS","MS","JPM","BAC","WFC","C","USB","TFC","FITB","RF",
]

USER_WATCHLIST = [
    # Semis / AI infra
    "SNDK","NVMI","ALAB","CRDO","FN","ANET","CRWV","NBIS","QUBT","IONQ","STX","CLS",
    "WDC","APLD","MRVL",
    # Cybersecurity / networking
    "CRWD","S","NET","UI","AKAM","NOK","OKTA","ZS","HPE",
    # AI enterprise / cloud
    "NOW","ORCL","IBM","ADSK","DOCN","U","APP","SYM","MANH","TEM",
    # Space / defense / robotics
    "RKLB","SERV","LHX","SANM",
    # Quantum computing
    "RGTI","QBTS",
    # Energy / materials / rare earth
    "IREN","FMST","ABAT","LBRT","CVE","AA","HMY","LYC","UCU","LAC","UEC","VRT",
    "USAR","PLUG","IMPP",
    # Consumer / retail / lifestyle
    "ABNB","DIS","UBER","VITL","TOST","MELI","LRN","OPEN",
    # Finance / fintech
    "BLK","BX","SCHW","VIRT","FISV","WM","VEEV","TTI",
    # Biotech
    "KSCP",
    # Misc
    "FDX",
]

# Full universe = deduplicated union of all sector lists
FULL_UNIVERSE = list(dict.fromkeys(
    SP500_CORE + SEMIS_AI + DEFENSE_AEROSPACE +
    ENERGY_MATERIALS + HEALTHCARE_BIOTECH +
    CONSUMER_RETAIL + FINTECH_FINANCE + USER_WATCHLIST
))

QUICK_UNIVERSE = SP500_CORE + SEMIS_AI[:20] + DEFENSE_AEROSPACE[:15] + ENERGY_MATERIALS[:20]
QUICK_UNIVERSE = list(dict.fromkeys(QUICK_UNIVERSE))

# ── Scoring thresholds ─────────────────────────────────────────────────────────
ADD_THRESHOLD    = 55   # score >= 55 → add to candidates / watchlist
REMOVE_THRESHOLD = 40   # score < 40 AND on watchlist → remove
STRONG_SIGNAL    = 75   # score >= 75 → "strong" label

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_positions() -> set[str]:
    """Return set of tickers already in positions.json."""
    try:
        data = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
        tickers = set()
        for acct in data.get("accounts", {}).values():
            for pos in acct.get("positions", []):
                tickers.add(pos["ticker"])
        return tickers
    except Exception:
        return set()


def load_watchlist() -> dict:
    """Load watchlist.json → {ticker: {reason, score, added, last_seen, signals}}"""
    try:
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_watchlist(wl: dict) -> None:
    WATCHLIST_FILE.write_text(json.dumps(wl, indent=2), encoding="utf-8")


def _get_days_to_earnings(ticker: str, yf_ticker, info: dict) -> tuple[Optional[int], str]:
    today = datetime.now(timezone.utc).date()
    candidates: list[tuple[int, str]] = []

    def _add(d, src: str):
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

    for key, src in [("earningsTimestampStart","ts_start"),("earningsTimestampEnd","ts_end"),("earningsTimestamp","ts_legacy")]:
        try:
            ts = info.get(key)
            if ts:
                _add(datetime.fromtimestamp(ts, tz=timezone.utc), src)
        except Exception:
            pass

    if not candidates:
        return None, "none"
    future = [(d,s) for d,s in candidates if d >= 0]
    pool = future if future else candidates
    pool.sort(key=lambda x: x[0])
    days, src = pool[0]
    if len(pool) > 1 and (pool[-1][0] - pool[0][0]) > 7:
        src = f"{src}[CONFLICT]"
    return days, src


def fetch_snapshot(ticker: str) -> dict:
    """Lightweight snapshot for scanning - no patterns, no enrichment."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period="1y", interval="1d")
        if hist.empty or len(hist) < 50:
            return {"ticker": ticker, "error": "insufficient history"}

        prices  = hist["Close"]
        volume  = hist["Volume"]
        price   = float(prices.iloc[-1])
        prev    = float(prices.iloc[-2])

        # RSI
        delta = prices.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs    = gain / loss
        rsi_s = 100 - (100 / (1 + rs))
        rsi   = float(rsi_s.iloc[-1]) if not rsi_s.iloc[-1] != rsi_s.iloc[-1] else 50.0

        # MACD hist
        ema12 = prices.ewm(span=12, adjust=False).mean()
        ema26 = prices.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        sig   = macd.ewm(span=9, adjust=False).mean()
        hist_s = macd - sig
        macd_now  = float(hist_s.iloc[-1])
        macd_prev = float(hist_s.iloc[-2])

        # BB%
        sma20 = prices.rolling(20).mean()
        std20 = prices.rolling(20).std()
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20
        bb_pct = float(((prices - lower) / (upper - lower) * 100).iloc[-1])

        ma50  = float(prices.rolling(50).mean().iloc[-1])
        ma200 = float(prices.rolling(200).mean().iloc[-1])

        vol_today = float(volume.iloc[-1])
        vol_avg   = float(info.get("averageDailyVolume3Month") or 1) or 1
        vol_ratio = vol_today / vol_avg

        days_earn, earn_src = _get_days_to_earnings(ticker, t, info)

        pct_chg = (price - prev) / prev * 100

        low_52  = float(info.get("fiftyTwoWeekLow")  or price)
        high_52 = float(info.get("fiftyTwoWeekHigh") or price)
        pct_from_52w_low = (price - low_52) / low_52 * 100 if low_52 else 0

        # Short squeeze potential
        short_pct = float((info.get("shortPercentOfFloat") or 0) * 100)

        return {
            "ticker": ticker,
            "price": round(price, 2),
            "pct_chg_today": round(pct_chg, 2),
            "rsi": round(rsi, 1),
            "ma50": round(ma50, 2),
            "ma200": round(ma200, 2),
            "macd_hist": round(macd_now, 3),
            "macd_prev": round(macd_prev, 3),
            "macd_crossover": bool(macd_now > 0 and macd_prev < 0),
            "macd_improving": bool(macd_now > macd_prev),
            "bb_pct": round(bb_pct, 1),
            "vol_ratio": round(vol_ratio, 2),
            "days_to_earnings": days_earn,
            "earnings_date_src": earn_src,
            "short_pct_float": round(short_pct, 1),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cash_flow": info.get("freeCashflow"),
            "forward_pe": info.get("forwardPE"),
            "beta": info.get("beta"),
            "market_cap": info.get("marketCap"),
            "52w_high": round(high_52, 2),
            "52w_low": round(low_52, 2),
            "pct_from_52w_low": round(pct_from_52w_low, 1),
            "analyst_rating": info.get("averageAnalystRating"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "name": info.get("shortName", ticker),
            "prices": prices,
            "rsi_series": rsi_s,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def build_signal_summary(snap: dict, score_result) -> list[str]:
    """Return list of human-readable signal strings for this ticker."""
    signals = []
    rsi = snap.get("rsi", 50)
    bb  = snap.get("bb_pct", 50)
    vol = snap.get("vol_ratio", 1)
    macd_x = snap.get("macd_crossover", False)
    macd_i = snap.get("macd_improving", False)
    pct    = snap.get("pct_chg_today", 0)
    dte    = snap.get("days_to_earnings")
    pct52  = snap.get("pct_from_52w_low", 0)

    if rsi < 30:
        signals.append(f"RSI {rsi} - deeply oversold")
    elif rsi < 40:
        signals.append(f"RSI {rsi} - oversold")
    if bb < 10:
        signals.append(f"BB% {bb} - near lower band (buy zone)")
    if macd_x:
        signals.append("MACD bullish crossover ✅")
    elif macd_i:
        signals.append("MACD histogram improving")
    if vol > 1.5:
        signals.append(f"Volume {vol:.1f}x avg - above-avg interest")
    if pct52 < 15:
        signals.append(f"Near 52-week low ({pct52:.0f}% above) - deep value zone")
    if pct > 3:
        signals.append(f"Up {pct:.1f}% today - momentum")
    if pct < -3:
        signals.append(f"Down {pct:.1f}% today - potential oversold entry")
    if dte is not None and 3 <= dte <= 15:
        signals.append(f"⚠️  Earnings in {dte}d - wait or skip")
    if hasattr(score_result, "pattern_note") and score_result.pattern_note:
        signals.append(f"Pattern: {score_result.pattern_note}")
    if hasattr(score_result, "regime_note") and score_result.regime_note:
        signals.append(f"Regime: {score_result.regime_note}")
    return signals


def sector_label(snap: dict) -> str:
    """Map ticker to macro narrative label."""
    t = snap.get("ticker", "")
    sector = snap.get("sector", "")
    if t in ("INTC","MU","AMAT","KLAC","LRCX","ASML","TSM","AMD","NVDA","AVGO","MRVL","SMCI","ARM"):
        return "AI/Semis 🤖"
    if t in ("RTX","NOC","LMT","GD","BA","HII","KTOS","LDOS","SAIC","CACI","BAH","DRS","AXON","PLTR"):
        return "Defense 🛡️"
    if t in ("MP","REE","NB","UUUU","DNN","CCJ","LEU","NNE","SMR","OKLO","BWXT","CEG","VST"):
        return "Rare Earth/Nuclear ⚛️"
    if t in ("EPD","ET","KMI","ENB","WMB","OKE","XOM","CVX","COP"):
        return "Energy/Hormuz 🛢️"
    if t in ("GLD","SLV","GDX","GOLD","NEM","AEM","WPM"):
        return "Gold/Inflation hedge"
    if t in ("NVO","LLY","VRTX","REGN","AMGN"):
        return "Healthcare/GLP-1 💊"
    if t in ("NKE","LULU","DECK","ONON","BJ","COST"):
        return "Consumer/Retail bounce"
    if "Health" in sector:
        return "Healthcare 💊"
    if "Tech" in sector or "Semiconductor" in sector:
        return "Tech/AI 🤖"
    if "Energy" in sector:
        return "Energy 🛢️"
    if "Indus" in sector:
        return "Industrials/Defense 🛡️"
    return sector or "General"


# ── Main scan ──────────────────────────────────────────────────────────────────

def run_scan(universe: list[str], label: str = "full") -> None:
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M MST")
    existing_positions = load_positions()
    watchlist = load_watchlist()

    print(f"\n🔍 DAILY UNIVERSE SCAN - {today_str}")
    print(f"   Universe: {len(universe)} tickers | Mode: {label}")
    print(f"   Scoring threshold: {ADD_THRESHOLD}+ = candidate | {STRONG_SIGNAL}+ = strong")
    print(f"   Excluding {len(existing_positions)} tickers already in positions\n")

    # ── Parallel fetch ─────────────────────────────────────────────────────
    print(f"Fetching data (parallel, 12 workers)...")
    snapshots: dict[str, dict] = {}
    errors = 0

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fetch_snapshot, t): t for t in universe}
        done = 0
        for f in as_completed(futures, timeout=600):
            t = futures[f]
            done += 1
            try:
                snap = f.result(timeout=12)
            except Exception as e:
                snap = {"ticker": t, "error": str(e)}
            snapshots[t] = snap
            if snap.get("error"):
                errors += 1
            if done % 50 == 0 or done == len(universe):
                ok = done - errors
                print(f"  {done}/{len(universe)} fetched - {ok} ok, {errors} errors")

    # ── Score each ticker ──────────────────────────────────────────────────
    print(f"\nScoring {len(snapshots)} tickers...")
    try:
        import score as sc
        import patterns as pat
        from spec_score import is_spec_candidate, score_spec
    except ImportError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    candidates: list[dict] = []
    spec_candidates: list[dict] = []
    scored_count = 0

    for t, snap in snapshots.items():
        if snap.get("error") or t in existing_positions:
            continue

        # Pattern detection
        pr = None
        if snap.get("prices") is not None:
            try:
                pr = pat.detect(snap["prices"], rsi_series=snap.get("rsi_series"))
            except Exception:
                pr = None

        # Route: spec ticker → spec_score, regular → score_ticker
        if is_spec_candidate(snap):
            try:
                spec_result = score_spec(snap, pattern_result=pr)
            except Exception:
                continue
            scored_count += 1
            if not spec_result.disqualified and spec_result.total >= 60:
                spec_candidates.append({
                    "ticker": t,
                    "name": snap.get("name", t),
                    "score": spec_result.total,
                    "score_type": "spec",
                    "signal": spec_result.signal,
                    "disqualified": spec_result.disqualified,
                    "disqualify_reason": spec_result.disqualify_reason,
                    "sector_label": sector_label(snap),
                    "price": snap.get("price"),
                    "rsi": snap.get("rsi"),
                    "bb_pct": snap.get("bb_pct"),
                    "pct_chg_today": snap.get("pct_chg_today"),
                    "days_to_earnings": snap.get("days_to_earnings"),
                    "vol_ratio": snap.get("vol_ratio"),
                    "ma50": snap.get("ma50"),
                    "ma200": snap.get("ma200"),
                    "pattern": pr.get("pattern") if pr else None,
                    "pattern_confidence": pr.get("confidence") if pr else None,
                    "pattern_signal": pr.get("signal") if pr else None,
                    "signals": f"SPEC {spec_result.total}/150 | {spec_result.runway_note}",
                    "scanned_at": today_str,
                })
            continue  # don't also run regular scorer on spec tickers

        # Score - scan_mode=True relaxes FCF/D/E to penalties
        try:
            result = sc.score_ticker(snap, pattern_result=pr, scan_mode=True)
        except Exception:
            continue

        scored_count += 1
        score = result.total  # includes penalties from scan_mode
        if score >= ADD_THRESHOLD and not result.disqualified:
            signals = build_signal_summary(snap, result)
            candidates.append({
                "ticker": t,
                "name": snap.get("name", t),
                "score": score,
                "signal": result.signal,
                "disqualified": result.disqualified,
                "disqualify_reason": result.disqualify_reason,
                "sector_label": sector_label(snap),
                "price": snap.get("price"),
                "rsi": snap.get("rsi"),
                "bb_pct": snap.get("bb_pct"),
                "pct_chg_today": snap.get("pct_chg_today"),
                "days_to_earnings": snap.get("days_to_earnings"),
                "vol_ratio": snap.get("vol_ratio"),
                "ma50": snap.get("ma50"),
                "ma200": snap.get("ma200"),
                "pattern": pr.get("pattern") if pr else None,
                "pattern_confidence": pr.get("confidence") if pr else None,
                "pattern_signal": pr.get("signal") if pr else None,
                "signals": signals,
                "breakdown": result.breakdown,
                "regime": result.regime,
                "regime_note": result.regime_note,
                "scanned_at": today_str,
            })

    # Sort by score desc
    candidates.sort(key=lambda x: x["score"], reverse=True)
    spec_candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:30]  # keep top 30
    top_spec = spec_candidates[:15]   # top 15 spec candidates

    print(f"  Scored {scored_count} tickers → {len(candidates)} regular (≥{ADD_THRESHOLD}) + {len(spec_candidates)} spec (≥60/150)")

    # ── Update watchlist ───────────────────────────────────────────────────
    today_iso = datetime.now().strftime("%Y-%m-%d")
    added_to_wl, removed_from_wl = [], []

    # Add qualifying candidates
    for c in candidates[:20]:  # top 20 go into watchlist consideration
        t = c["ticker"]
        dte = c.get("days_to_earnings")
        # Don't auto-add if earnings <7 days
        if dte is not None and 0 <= dte <= 7:
            continue
        if t not in watchlist:
            watchlist[t] = {
                "ticker": t,
                "name": c.get("name", t),
                "score": c["score"],
                "signal": c["signal"],
                "sector": c["sector_label"],
                "signals": c["signals"][:3],
                "date_added": today_iso,
                "date_last_seen": today_iso,
                "days_on_list": 1,
            }
            added_to_wl.append(t)
        else:
            watchlist[t]["score"] = c["score"]
            watchlist[t]["signal"] = c["signal"]
            watchlist[t]["signals"] = c["signals"][:3]
            watchlist[t]["date_last_seen"] = today_iso
            watchlist[t]["days_on_list"] = watchlist[t].get("days_on_list", 1) + 1

    # Remove stale / below threshold
    scored_tickers = {s["ticker"]: s for s in snapshots.values() if not s.get("error")}
    for t in list(watchlist.keys()):
        if t in existing_positions:
            # Graduated to position - remove from watchlist
            removed_from_wl.append(f"{t} (now in positions)")
            del watchlist[t]
            continue
        if t in scored_tickers:
            snap = scored_tickers[t]
            try:
                result = sc.score_ticker(snap)
                if result.disqualified or result.total < REMOVE_THRESHOLD:
                    removed_from_wl.append(f"{t} (score {result.total} < {REMOVE_THRESHOLD})")
                    del watchlist[t]
            except Exception:
                pass

    save_watchlist(watchlist)

    # ── Save results ───────────────────────────────────────────────────────
    output = {
        "scanned_at": today_str,
        "universe_size": len(universe),
        "scored": scored_count,
        "candidates_found": len(candidates),
        "candidates": top_candidates,
        "spec_candidates_found": len(spec_candidates),
        "spec_candidates": top_spec,
        "watchlist_added": added_to_wl,
        "watchlist_removed": removed_from_wl,
        "watchlist_size": len(watchlist),
    }
    RESULTS_FILE.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")

    # ── Terminal output ────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  TOP CANDIDATES - {today_str}")
    print(f"{'='*70}")

    strong  = [c for c in top_candidates if c["score"] >= STRONG_SIGNAL and not c["disqualified"]]
    regular = [c for c in top_candidates if ADD_THRESHOLD <= c["score"] < STRONG_SIGNAL and not c["disqualified"]]

    if strong:
        print(f"\n🟢 STRONG SIGNALS (score ≥ {STRONG_SIGNAL})")
        for c in strong:
            _print_candidate(c)

    if regular:
        print(f"\n🟡 CANDIDATES (score {ADD_THRESHOLD}-{STRONG_SIGNAL-1})")
        for c in regular[:15]:
            _print_candidate(c)

    if not strong and not regular:
        print("\n  No regular candidates above threshold today.")

    # ── Spec candidates section ────────────────────────────────────────────
    if top_spec:
        print(f"\n{'='*70}")
        print(f"  SPEC CANDIDATES (≥60/150) - pre-profit / penny / startup")
        print(f"{'='*70}")
        spec_strong = [c for c in top_spec if c["score"] >= 90]
        spec_regular = [c for c in top_spec if 60 <= c["score"] < 90]
        if spec_strong:
            print(f"\n🔵 SPEC STRONG (≥90/150)")
            for c in spec_strong:
                _print_spec_candidate(c)
        if spec_regular:
            print(f"\n🔷 SPEC CANDIDATES (60-89/150)")
            for c in spec_regular[:10]:
                _print_spec_candidate(c)

    if added_to_wl:
        print(f"\n✅ Added to watchlist: {', '.join(added_to_wl)}")
    if removed_from_wl:
        print(f"🗑️  Removed from watchlist: {', '.join(removed_from_wl)}")

    print(f"\n📋 Watchlist size: {len(watchlist)} tickers")
    print(f"💾 Results saved → scan_results.json")
    print(f"{'='*70}\n")


def _print_candidate(c: dict) -> None:
    dte_str = f" | earn {c['days_to_earnings']}d" if c.get("days_to_earnings") is not None else ""
    pct_str = f" {c['pct_chg_today']:+.1f}%" if c.get("pct_chg_today") is not None else ""
    print(f"  {c['ticker']:6} [{c['score']:3}] ${c['price']:<8.2f} RSI {c['rsi']:<5.1f} BB {c['bb_pct']:<5.1f} vol {c.get('vol_ratio',1):.1f}x{pct_str}{dte_str}")
    print(f"         {c['sector_label']} | {c['name']}")
    sigs = c["signals"] if isinstance(c["signals"], list) else [c["signals"]]
    for sig in sigs[:2]:
        print(f"         → {sig}")


def _print_spec_candidate(c: dict) -> None:
    dte_str = f" | earn {c['days_to_earnings']}d" if c.get("days_to_earnings") is not None else ""
    pct_str = f" {c['pct_chg_today']:+.1f}%" if c.get("pct_chg_today") is not None else ""
    price_str = f"${c['price']:.2f}" if c.get("price") else "n/a"
    rsi_str = f" RSI {c['rsi']:.1f}" if c.get("rsi") else ""
    print(f"  {c['ticker']:6} [{c['score']:3}/150] {price_str:<9}{rsi_str}{pct_str}{dte_str} [SPEC]")
    print(f"         {c.get('sector_label','')} | {c['name']}")
    if c.get("signals"):
        print(f"         → {c['signals']}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="SP500 top 100 + key sectors (~2 min)")
    parser.add_argument("--test",  action="store_true", help="20 tickers only - verify setup")
    args = parser.parse_args()

    if args.test:
        universe = ["INTC","NVDA","AMD","RTX","NOC","LMT","KTOS","CCJ","MP","NVO",
                    "NKE","MDT","AAPL","MSFT","GOOGL","META","AMZN","EPD","GLD","BJ"]
        label = "test (20 tickers)"
    elif args.quick:
        universe = QUICK_UNIVERSE
        label = "quick (~150 tickers)"
    else:
        universe = FULL_UNIVERSE
        label = "full (~350 tickers)"

    run_scan(universe, label)
