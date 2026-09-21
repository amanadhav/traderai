"""
Trading dashboard API - FastAPI backend.
Run: uvicorn api:app --reload --port 8000
Or:  trading server
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parents[1]
load_dotenv(BASE / ".env")

_API_TOKEN = os.getenv("TRADING_API_TOKEN", "")

def _require_token(x_api_token: str = Header(default="")) -> None:
    import secrets
    if not _API_TOKEN:
        raise HTTPException(status_code=503, detail="TRADING_API_TOKEN not set in .env - mutations disabled")
    if not secrets.compare_digest(x_api_token, _API_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid API token")

def _maybe_read_guard(x_api_token: str = Header(default="")) -> None:
    """Optional auth on ALL endpoints: set REQUIRE_READ_AUTH=1 in .env when
    exposing the API beyond localhost. Off by default (localhost CORS only)."""
    if os.getenv("REQUIRE_READ_AUTH", "") in ("1", "true", "yes"):
        _require_token(x_api_token)

# Reuse all existing logic from morning_run
sys.path.insert(0, str(Path(__file__).parent))
import morning_run as mr

app = FastAPI(title="TraderAI", version="2.0",
              dependencies=[Depends(_maybe_read_guard)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ────────────────────────────────────────────────────────────────

_EMPTY_PORTFOLIO = {"accounts": {}, "watchlist": [], "last_updated": None}

def load_positions() -> dict:
    """Portfolio state; a fresh install (no positions.json yet) is empty, not an error."""
    if not Path(mr.POSITIONS_FILE).exists():
        return dict(_EMPTY_PORTFOLIO)
    with open(mr.POSITIONS_FILE, encoding="utf-8") as f:
        return json.load(f)

def load_history() -> list:
    if mr.HISTORY_FILE.exists():
        with open(mr.HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def load_trades() -> list:
    if mr.TRADES_FILE.exists():
        with open(mr.TRADES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def all_tickers(data: dict) -> list[str]:
    tickers = []
    for acct in data["accounts"].values():
        for p in acct.get("positions", []):
            tickers.append(p["ticker"])
    return list(set(tickers))

# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/api/positions")
def get_positions():
    data = load_positions()
    return data

@app.get("/api/history")
def get_history():
    return load_history()

@app.get("/api/trades")
def get_trades():
    return load_trades()

@app.get("/api/market")
def get_market():
    """VIX, SPY RSI, QQQ RSI - live fetch."""
    snaps = mr.get_market_indicators()
    return {
        "vix":     (snaps.get("^VIX") or {}).get("price"),
        "spy_rsi": (snaps.get("SPY")  or {}).get("rsi"),
        "qqq_rsi": (snaps.get("QQQ")  or {}).get("rsi"),
        "spy_price": (snaps.get("SPY") or {}).get("price"),
        "qqq_price": (snaps.get("QQQ") or {}).get("price"),
    }

@app.get("/api/prices")
def get_prices():
    """Live snapshot for all current positions (parallel fetch)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    data = load_positions()
    tickers = all_tickers(data)
    snapshots = {}

    def fetch(t):
        snap = mr.get_full_snapshot(t)
        # Strip non-serializable pandas objects
        snap.pop("prices", None)
        snap.pop("rsi_series", None)
        snap.pop("volume", None)
        snap.setdefault("change_pct", snap.get("pct_chg_today"))
        return t, snap

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fetch, t) for t in tickers]
        for f in as_completed(futs, timeout=120):
            try:
                t, snap = f.result()
                snapshots[t] = snap
            except Exception:
                pass
    return snapshots

@app.get("/api/snapshot/{ticker}")
def get_snapshot(ticker: str):
    snap = mr.get_full_snapshot(ticker.upper())
    snap.pop("prices", None)
    snap.pop("rsi_series", None)
    snap.pop("volume", None)
    try:
        import data_client as dc
        t = ticker.upper()
        sr = dc.get_support_resistance(t)
        snap["support"]    = sr.get("support", [])
        snap["resistance"] = sr.get("resistance", [])
        snap["candlestick_patterns"] = dc.get_candlestick_patterns(t)
    except Exception:
        pass
    return snap

@app.get("/api/support-resistance/{ticker}")
def get_sr(ticker: str):
    try:
        import data_client as dc
        return dc.get_support_resistance(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/insider/{ticker}")
def get_insider(ticker: str):
    try:
        import data_client as dc
        return {"ticker": ticker.upper(), "transactions": dc.get_insider_activity(ticker.upper())}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/provider-status")
def get_provider_status():
    try:
        import data_client as dc
        return dc.status()
    except Exception:
        return {}

@app.get("/api/score/{ticker}")
def get_score(ticker: str):
    import score as sc
    import patterns as pat_mod
    snap = mr.get_full_snapshot(ticker.upper())
    prices  = snap.pop("prices", None)
    rsi_s   = snap.pop("rsi_series", None)
    snap.pop("volume", None)
    pat_res = pat_mod.detect(prices, rsi_series=rsi_s) if prices is not None else {}
    result  = sc.score_ticker(snap, pattern_result=pat_res)
    return {
        "ticker":       ticker.upper(),
        "score":        result.total,
        "disqualified": result.disqualified,
        "disq_reason":  result.disqualify_reason,
        "breakdown":    result.breakdown,
        "explanation":  sc.explain_score(result),
    }

@app.get("/api/action-items")
def get_action_items():
    """Full action items - requires live price fetch.
    Uses generate_action_items_v3 (same as CLI briefing + tracker.html) so the
    React frontend gets identical recommendations to every other surface."""
    data      = load_positions()
    tickers   = all_tickers(data)
    snapshots = {}
    for t in tickers:
        snap = mr.get_full_snapshot(t)
        snapshots[t] = snap

    market_snaps = mr.get_market_indicators()

    import patterns as pat_mod
    pattern_results = {}
    for t, snap in snapshots.items():
        if snap.get("prices") is not None:
            pattern_results[t] = pat_mod.detect(snap["prices"], rsi_series=snap.get("rsi_series"))

    # Fetch additional v3 signals (cached - fast on second call)
    insider_signals: dict = {}
    options_flows:  dict = {}
    ticker_news:    dict = {}
    try:
        from insider import get_insider_signals
        insider_signals = get_insider_signals(tickers, force_refresh=False, verbose=False) or {}
    except Exception:
        pass
    try:
        from options_flow import get_options_flows
        options_flows = get_options_flows(tickers, force_refresh=False, verbose=False) or {}
    except Exception:
        pass
    try:
        for t in tickers:
            ticker_news[t] = mr.get_ticker_news(t, max_items=5)
    except Exception:
        pass

    from action_engine import generate_action_items_v3
    items = generate_action_items_v3(
        data, snapshots, pattern_results, market_snaps, {},
        insider_signals=insider_signals,
        options_flows=options_flows,
        ticker_news=ticker_news,
        macro_results={},
    )

    # Strip non-serializable fields
    for snap in snapshots.values():
        snap.pop("prices", None)
        snap.pop("rsi_series", None)
        snap.pop("volume", None)

    return {"items": items, "snapshots": snapshots, "market": {
        "vix":     (market_snaps.get("^VIX") or {}).get("price"),
        "spy_rsi": (market_snaps.get("SPY")  or {}).get("rsi"),
        "qqq_rsi": (market_snaps.get("QQQ")  or {}).get("rsi"),
    }}

# ── Trade mutation endpoints ───────────────────────────────────────────────

class BuyRequest(BaseModel):
    account: str
    ticker: str
    shares: float
    price: float
    stop: float | None = None
    ptype: str = "L"
    thesis: str = ""
    notes: str = ""

class SellRequest(BaseModel):
    account: str
    ticker: str
    shares: float
    price: float

class StopRequest(BaseModel):
    account: str
    ticker: str
    stop_price: float
    shares: float | None = None

class CashRequest(BaseModel):
    account: str
    amount: float
    mode: str = "set"  # set | deposit | withdraw

class SetupPosition(BaseModel):
    ticker: str
    shares: float
    avg_cost: float
    ptype: str = "L"
    stop: float | None = None
    thesis: str = ""

class SetupAccount(BaseModel):
    name: str
    cash: float = 0.0
    positions: list[SetupPosition] = []

class PortfolioSetup(BaseModel):
    accounts: list[SetupAccount]

@app.post("/api/setup/portfolio")
def setup_portfolio(req: PortfolioSetup, x_api_token: str = Header(default="")):
    """Create the initial portfolio from the setup wizard.

    Open during first-run onboarding (no portfolio secrets exist yet);
    once onboarded it requires the API token like every other mutation."""
    import user_config
    from persistence import positions_lock
    if user_config.get_config(refresh=True).get("onboarded"):
        _require_token(x_api_token)
    if not req.accounts:
        raise HTTPException(400, "at least one account required")

    data = {"accounts": {}, "watchlist": [], "last_updated": datetime.now().isoformat()}
    for acct in req.accounts:
        name = acct.name.strip().upper().replace(" ", "_")
        if not name:
            raise HTTPException(400, "account name required")
        data["accounts"][name] = {
            "cash": round(acct.cash, 2),
            "positions": [
                {
                    "ticker": p.ticker.strip().upper(),
                    "shares": p.shares,
                    "avg_cost": round(p.avg_cost, 4),
                    "stop": p.stop,
                    "stop_type": "GTC Stop Market" if p.stop else None,
                    "stop_shares": p.shares if p.stop else 0,
                    "type": p.ptype,
                    "entry_date": datetime.now().strftime("%Y-%m-%d"),
                    "thesis": p.thesis,
                    "notes": "",
                    "pending_orders": [],
                }
                for p in acct.positions if p.ticker.strip() and p.shares > 0
            ],
        }
    with positions_lock():
        mr._save_data(data)
    n_pos = sum(len(a["positions"]) for a in data["accounts"].values())
    return {"ok": True,
            "message": f"Portfolio created: {len(data['accounts'])} account(s), {n_pos} position(s)"}

@app.post("/api/buy")
def api_buy(req: BuyRequest, _: None = Depends(_require_token)):
    from persistence import positions_lock
    with positions_lock():
        data = load_positions()
        ticker = req.ticker.upper()
        acct   = req.account.upper()
        pos, pos_list = mr._find_position(data, acct, ticker)

        if pos:
            old_sh  = pos["shares"]
            old_avg = pos["avg_cost"]
            new_sh  = old_sh + req.shares
            new_avg = round((old_sh * old_avg + req.shares * req.price) / new_sh, 4)
            pos["shares"]   = new_sh
            pos["avg_cost"] = new_avg
            if req.stop is not None:
                pos["stop"] = req.stop
            msg = f"Updated {ticker}: {old_sh}sh @${old_avg:.2f} + {req.shares}sh @${req.price:.2f} → {new_sh}sh @${new_avg:.2f}"
        else:
            new_pos = {
                "ticker": ticker, "shares": req.shares, "avg_cost": round(req.price, 4),
                "stop": req.stop, "stop_type": "GTC Stop Market" if req.stop else None,
                "stop_shares": req.shares if req.stop else 0,
                "type": req.ptype, "entry_date": datetime.now().strftime("%Y-%m-%d"),
                "thesis": req.thesis, "notes": req.notes, "pending_orders": [],
            }
            data["accounts"][acct]["positions"].append(new_pos)
            msg = f"Added {ticker} to {acct}: {req.shares}sh @${req.price:.2f}"

        mr._save_data(data)
    return {"ok": True, "message": msg}

@app.post("/api/sell")
def api_sell(req: SellRequest, _: None = Depends(_require_token)):
    from persistence import positions_lock
    with positions_lock():
        data = load_positions()
        ticker = req.ticker.upper()
        acct   = req.account.upper()
        pos, pos_list = mr._find_position(data, acct, ticker)

        if not pos:
            raise HTTPException(404, f"{ticker} not found in {acct}")
        if req.shares > pos["shares"]:
            raise HTTPException(400, f"Can't sell {req.shares}sh - only have {pos['shares']}sh")

        avg_cost = pos["avg_cost"]
        pl       = round((req.price - avg_cost) * req.shares, 2)
        pl_pct   = round((req.price - avg_cost) / avg_cost * 100, 2)
        remaining = pos["shares"] - req.shares

        if remaining == 0:
            pos_list.remove(pos)
        else:
            pos["shares"] = remaining

        mr.log_trade(acct, ticker, req.shares, avg_cost, req.price, pos.get("entry_date"))
        mr._save_data(data)

    return {
        "ok": True,
        "message": f"Sold {req.shares}sh {ticker} @${req.price:.2f}",
        "pl_dollar": pl,
        "pl_pct":    pl_pct,
        "remaining": remaining,
    }

@app.post("/api/stop")
def api_stop(req: StopRequest, _: None = Depends(_require_token)):
    from persistence import positions_lock
    with positions_lock():
        data = load_positions()
        pos, _ = mr._find_position(data, req.account.upper(), req.ticker.upper())
        if not pos:
            raise HTTPException(404, f"{req.ticker} not found in {req.account}")
        pos["stop"]        = req.stop_price
        pos["stop_type"]   = "GTC Stop Market"
        pos["stop_shares"] = req.shares if req.shares is not None else pos["shares"]
        mr._save_data(data)
    return {"ok": True, "message": f"{req.ticker} stop → ${req.stop_price:.2f}"}

@app.post("/api/cash")
def api_cash(req: CashRequest, _: None = Depends(_require_token)):
    """Manage account cash: deposit / withdraw funds, or set the balance outright."""
    from persistence import positions_lock
    with positions_lock():
        data = load_positions()
        acct = req.account.upper()
        if acct not in data["accounts"]:
            raise HTTPException(404, f"Account {acct} not found")
        current = data["accounts"][acct].get("cash") or 0.0
        if req.mode == "deposit":
            if req.amount <= 0:
                raise HTTPException(400, "deposit amount must be positive")
            new_cash = current + req.amount
            msg = f"Deposited ${req.amount:,.2f} into {acct} - cash now ${new_cash:,.2f}"
        elif req.mode == "withdraw":
            if req.amount <= 0:
                raise HTTPException(400, "withdrawal amount must be positive")
            if req.amount > current:
                raise HTTPException(400, f"insufficient cash: {acct} has ${current:,.2f}")
            new_cash = current - req.amount
            msg = f"Withdrew ${req.amount:,.2f} from {acct} - cash now ${new_cash:,.2f}"
        elif req.mode == "set":
            if req.amount < 0:
                raise HTTPException(400, "cash cannot be negative")
            new_cash = req.amount
            msg = f"{acct} cash → ${new_cash:,.2f}"
        else:
            raise HTTPException(400, f"unknown mode {req.mode!r} - use set|deposit|withdraw")
        data["accounts"][acct]["cash"] = round(new_cash, 2)
        mr._save_data(data)
    return {"ok": True, "message": msg, "cash": round(new_cash, 2)}

@app.get("/api/news/{ticker}")
def get_news(ticker: str):
    articles = mr.get_ticker_news(ticker.upper(), max_items=8)
    return {"ticker": ticker.upper(), "articles": articles}

@app.get("/api/etfs")
def get_etfs():
    """Live snapshots for the user's ETF watchlist (edit it in Settings)."""
    import user_config
    from concurrent.futures import ThreadPoolExecutor, as_completed
    tickers = user_config.get_config().get("etf_watchlist") or []
    result = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(mr.get_full_snapshot, t): t for t in tickers}
        for f in as_completed(futs, timeout=120):
            t = futs[f]
            try:
                snap = f.result()
                for k in ("prices", "rsi_series", "volume"):
                    snap.pop(k, None)
                result[t] = {"ticker": t, **snap}
            except Exception:
                result[t] = {"ticker": t}
    return {"etfs": [result[t] for t in tickers if t in result]}

@app.get("/api/scan-results")
def get_scan_results():
    path = BASE / "scan_results.json"
    if not path.exists():
        return {"available": False, "message": "No scan results. Run: trading scan --quick"}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {"available": True, **data}

@app.get("/api/news-all")
def get_all_news():
    data = load_positions()
    tickers = all_tickers(data)
    result = {}
    for t in tickers:
        try:
            result[t] = mr.get_ticker_news(t, max_items=5)
        except Exception:
            result[t] = []
    return result

# ── Risk engine, guardian, macro, charts ─────────────────────────────────────

@app.get("/api/search-tickers")
def search_tickers(q: str = ""):
    """Ticker autocomplete via Yahoo Finance search (free, no key)."""
    import requests
    q = q.strip()
    if len(q) < 1:
        return {"results": []}
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": 8, "newsCount": 0, "listsCount": 0},
            headers={"User-Agent": "Mozilla/5.0 (TraderAI local)"},
            timeout=8,
        )
        quotes = r.json().get("quotes", [])
    except Exception:
        return {"results": []}
    results = [
        {
            "symbol": x.get("symbol"),
            "name": x.get("shortname") or x.get("longname") or "",
            "exchange": x.get("exchDisp") or x.get("exchange") or "",
            "type": x.get("quoteType") or "",
        }
        for x in quotes
        if x.get("symbol") and x.get("quoteType") in ("EQUITY", "ETF")
    ]
    return {"results": results[:8]}

@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    """Lightweight live quote (fast_info - no heavy snapshot)."""
    import yfinance as yf
    t = ticker.upper()
    try:
        fi = yf.Ticker(t).fast_info
        price = fi.last_price
        return {"symbol": t, "price": round(float(price), 2) if price else None,
                "currency": getattr(fi, "currency", None)}
    except Exception:
        return {"symbol": t, "price": None, "currency": None}

@app.get("/api/trade-setup/{ticker}")
def get_trade_setup(ticker: str, equity: float = 10000.0):
    """Structured trade setup computed from the user's own risk rules."""
    import risk_engine
    snap = mr.get_full_snapshot(ticker.upper())
    for k in ("prices", "rsi_series", "volume"):
        snap.pop(k, None)
    return risk_engine.build_trade_setup(snap, equity)

@app.get("/api/guardian")
def get_guardian():
    """Discipline guardian - portfolio vs the user's configured rules."""
    import guardian
    data = load_positions()
    tickers = all_tickers(data)
    prices = {}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(mr.get_full_snapshot, t): t for t in tickers}
        for f in as_completed(futs, timeout=120):
            try:
                prices[futs[f]] = {"price": f.result().get("price")}
            except Exception:
                pass
    return {"violations": guardian.check_all(data, prices, load_history())}

@app.get("/api/macro")
def get_macro_data(force: bool = False):
    """Free macro regime data: yield curve (yfinance) + CPI/Fed/unemployment (FRED)."""
    import macro_data
    return macro_data.get_macro(force=force)

@app.get("/api/chart/{ticker}")
def get_chart(ticker: str, days: int = 180):
    """OHLC + MA50/MA200 + RSI series for the ticker detail chart."""
    import yfinance as yf
    from data_fetch import get_rsi
    t = ticker.upper()
    days = max(30, min(days, 730))
    hist = yf.Ticker(t).history(period="2y", interval="1d")
    if hist.empty:
        raise HTTPException(404, f"no history for {t}")
    close_full = hist["Close"]
    ma50 = close_full.rolling(50).mean()
    ma200 = close_full.rolling(200).mean()
    rsi = get_rsi(close_full)
    tail = hist.tail(days)
    idx = tail.index
    def col(series):
        s = series.loc[idx]
        return [round(float(x), 2) if x == x else None for x in s]
    stop = None
    try:
        data = load_positions()
        for acct in data["accounts"].values():
            for p in acct.get("positions", []):
                if p["ticker"] == t and p.get("stop"):
                    stop = p["stop"]
    except Exception:
        pass
    return {
        "ticker": t,
        "dates": [d.strftime("%Y-%m-%d") for d in idx],
        "close": col(tail["Close"]),
        "ma50": col(ma50),
        "ma200": col(ma200),
        "rsi": col(rsi),
        "stop": stop,
    }

@app.get("/api/signal-history/{ticker}")
def get_signal_history(ticker: str, days: int = 90):
    """Daily signal rows recorded by the morning run (SQLite signal store)."""
    import signal_store
    return {"ticker": ticker.upper(),
            "rows": signal_store.history(ticker, days=min(days, 730)),
            "stats": signal_store.stats()}

@app.get("/api/signal-stats")
def get_signal_stats():
    import signal_store
    return signal_store.stats()

@app.get("/api/debate/{ticker}")
def get_debate(ticker: str):
    """Bull vs Bear earnings debate with a judge verdict (3 small AI calls)."""
    import ai_analyst
    return ai_analyst.earnings_debate(ticker)

@app.get("/api/scan-explanations")
def get_scan_explanations():
    """AI one-liner per top scan candidate (cached per scan run)."""
    import ai_analyst
    return ai_analyst.explain_scan_candidates()

# ── User configuration ──────────────────────────────────────────────────────

@app.get("/api/config")
def get_user_config():
    import user_config
    return user_config.get_config(refresh=True)

class ConfigUpdate(BaseModel):
    config: dict

@app.put("/api/config")
def put_user_config(req: ConfigUpdate):
    import user_config
    ALLOWED = {"profile", "preset", "rules", "accounts", "narratives",
               "etf_watchlist", "ai", "appearance", "paper_mode", "onboarded"}
    update = {k: v for k, v in req.config.items() if k in ALLOWED}
    if not update:
        raise HTTPException(400, "no valid config keys in update")
    # validate rule keys against known defaults
    if "rules" in update:
        bad = set(update["rules"]) - set(user_config.DEFAULT_RULES)
        if bad:
            raise HTTPException(400, f"unknown rules: {sorted(bad)}")
    return user_config.save_config(update)

@app.get("/api/config/presets")
def get_presets():
    import user_config
    import score as sc
    return {
        "presets": user_config.PRESETS,
        "tolerance_to_preset": user_config.TOLERANCE_TO_PRESET,
        "available_narratives": sc.ACTIVE_NARRATIVES,
        "default_rules": user_config.DEFAULT_RULES,
    }

@app.post("/api/reset-portfolio")
def reset_portfolio(_: None = Depends(_require_token)):
    """Reset positions.json to the example template (paper-mode restart)."""
    from persistence import positions_lock
    example = BASE / "positions.example.json"
    if not example.exists():
        raise HTTPException(404, "positions.example.json missing")
    with positions_lock():
        (BASE / "positions.json").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return {"ok": True, "message": "Portfolio reset to example template"}

# ── Scan runner ──────────────────────────────────────────────────────────────

_scan_state = {"running": False, "started": None, "finished": None,
               "returncode": None, "quick": None, "log_tail": ""}

class ScanRequest(BaseModel):
    quick: bool = True

@app.post("/api/scan/run")
def run_scan(req: ScanRequest):
    """Run the universe scanner in the background (quick ~2-5 min, full ~8-30)."""
    import subprocess
    import threading
    if _scan_state["running"]:
        raise HTTPException(409, "scan already running")

    cmd = [sys.executable, str(Path(__file__).parent / "scan_universe.py")]
    if req.quick:
        cmd.append("--quick")

    def worker():
        _scan_state.update(running=True, started=datetime.now().isoformat(timespec="seconds"),
                           finished=None, returncode=None, quick=req.quick, log_tail="")
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=3600, env=env)
            _scan_state["returncode"] = proc.returncode
            _scan_state["log_tail"] = (proc.stdout or "")[-2000:]
        except Exception as e:
            _scan_state["returncode"] = -1
            _scan_state["log_tail"] = f"{type(e).__name__}: {e}"
        finally:
            _scan_state["running"] = False
            _scan_state["finished"] = datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "message": f"{'quick' if req.quick else 'full'} scan started"}

@app.get("/api/scan/status")
def scan_status():
    return _scan_state

# ── Macro themes: live market headlines + narrative pulse ────────────────────

@app.get("/api/macro-news")
def get_macro_news_feed():
    """Top market headlines (Finnhub general news when keyed, else yfinance
    index news) + a live pulse per tracked macro narrative from keyword hits."""
    headlines = []
    fh_key = os.getenv("FINNHUB_KEY", "")
    if fh_key:
        try:
            import requests
            r = requests.get("https://finnhub.io/api/v1/news",
                             params={"category": "general", "token": fh_key}, timeout=10)
            for a in (r.json() or [])[:30]:
                if a.get("headline"):
                    headlines.append({
                        "title": a["headline"], "url": a.get("url") or "",
                        "source": a.get("source") or "", "datetime": a.get("datetime"),
                        "summary": (a.get("summary") or "")[:220],
                    })
        except Exception:
            pass
    if not headlines:
        try:
            headlines = [
                {"title": n["title"], "url": n.get("url") or "",
                 "source": n.get("source") or "", "datetime": None, "summary": ""}
                for n in mr.get_ticker_news("^GSPC", max_items=20) if n.get("title")
            ]
        except Exception:
            pass

    # Pulse per tracked narrative: keyword hits over today's headlines (free),
    # calibrated Jev probability layered on top when TypeSafe is configured.
    import news_sentiment
    import score as sc
    import user_config
    tracked = user_config.active_narratives(sc.ACTIVE_NARRATIVES)
    titles = [h["title"] for h in headlines]
    text = " ".join(titles).lower()
    pulses = []
    jev_ok = False
    try:
        import jev_signals
        jev_ok = jev_signals.jev_available() and bool(titles)
    except Exception:
        jev_ok = False
    for key, desc in tracked.items():
        kws = news_sentiment.NARRATIVE_KEYWORDS.get(key, [])
        hits = [kw for kw in kws if kw.lower() in text]
        pulse = {"narrative": key, "description": desc,
                 "keyword_hits": hits[:5], "active": len(hits) >= 1}
        if jev_ok and len(pulses) < 6:  # cap Jev calls per request
            try:
                import jev_signals
                p = jev_signals.macro_pulse(key, desc, titles)
                if p is not None:
                    pulse["jev_probability"] = p
                    pulse["active"] = p >= 0.5 or pulse["active"]
            except Exception:
                pass
        pulses.append(pulse)
    pulses.sort(key=lambda p: (not p["active"], -(p.get("jev_probability") or len(p["keyword_hits"]))))
    return {"headlines": headlines, "narratives": pulses,
            "source": "finnhub" if fh_key and headlines else "yfinance"}

# ── Backtest runner ──────────────────────────────────────────────────────────

_backtest_state = {"running": False, "started": None, "finished": None,
                   "returncode": None, "args": None, "log_tail": ""}

class BacktestRequest(BaseModel):
    lookback: int = 365
    hold: int = 60
    full: bool = False
    tickers: list[str] | None = None

@app.post("/api/backtest/run")
def run_backtest(req: BacktestRequest):
    import subprocess
    import threading
    if _backtest_state["running"]:
        raise HTTPException(409, "backtest already running")

    cmd = [sys.executable, str(Path(__file__).parent / "backtest.py"),
           "--lookback", str(req.lookback), "--hold", str(req.hold),
           "--save", "--quiet"]
    if req.full:
        cmd.append("--full")
    if req.tickers:
        cmd += ["--tickers"] + [t.upper() for t in req.tickers][:50]

    def worker():
        import time
        _backtest_state.update(running=True, started=datetime.now().isoformat(timespec="seconds"),
                               finished=None, returncode=None, args=cmd[2:], log_tail="")
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=3600, env=env)
            _backtest_state["returncode"] = proc.returncode
            _backtest_state["log_tail"] = (proc.stdout or "")[-3000:]
        except Exception as e:
            _backtest_state["returncode"] = -1
            _backtest_state["log_tail"] = f"{type(e).__name__}: {e}"
        finally:
            _backtest_state["running"] = False
            _backtest_state["finished"] = datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "message": "backtest started", "args": cmd[2:]}

@app.get("/api/backtest/status")
def backtest_status():
    return _backtest_state

@app.get("/api/backtest/results")
def backtest_results():
    path = BASE / "backtest_results.json"
    if not path.exists():
        return {"available": False, "message": "No backtest results yet - run one first."}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # keep the response light: cap the raw entry list
    entries = data.get("all_entries", [])
    data["all_entries"] = entries[:500]
    data["n_entries_total"] = len(entries)
    return {"available": True, **data}

@app.get("/api/sentiment/{ticker}")
def get_sentiment(ticker: str):
    """News sentiment for a ticker: keyword classifier + Jev (TypeSafe)
    calibrated probabilities side by side. Jev fields are null without a key."""
    t = ticker.upper()
    articles = mr.get_ticker_news(t, max_items=10)
    headlines = [a.get("title") or a.get("headline") or "" for a in articles]

    import news_sentiment
    keyword = news_sentiment.classify_ticker_news(headlines, t)

    thesis = ""
    try:
        data = load_positions()
        for acct in data["accounts"].values():
            for p in acct.get("positions", []):
                if p["ticker"] == t:
                    thesis = p.get("thesis", "")
    except Exception:
        pass

    import jev_signals
    jev = jev_signals.classify_headlines(t, headlines, thesis=thesis)

    return {
        "ticker": t,
        "headlines": headlines,
        "keyword": keyword,
        "jev": jev,
        "jev_available": jev_signals.jev_available(),
    }

# ── AI analyst ──────────────────────────────────────────────────────────────

@app.get("/api/briefing")
def get_briefing(force: bool = False):
    """AI morning briefing - returns today's cached briefing or generates one
    (generation fetches live market + news and can take 30-60s)."""
    import ai_analyst
    return ai_analyst.generate_briefing(force=force)

@app.get("/api/briefing/latest")
def get_briefing_latest():
    """Last generated briefing without triggering generation."""
    import ai_analyst
    return ai_analyst.latest_briefing()

class ChatRequest(BaseModel):
    messages: list[dict]

@app.post("/api/chat")
def post_chat(req: ChatRequest):
    """Portfolio chat - Claude with tool use over the system's own functions."""
    import ai_analyst
    msgs = [m for m in req.messages if m.get("role") in ("user", "assistant") and m.get("content")]
    if not msgs:
        raise HTTPException(400, "messages required")
    try:
        return ai_analyst.chat(msgs[-20:])
    except Exception as e:
        raise HTTPException(500, f"chat failed: {type(e).__name__}: {e}")

@app.get("/api/ai-status")
def get_ai_status():
    import ai_client
    return {
        "available": ai_client.ai_available(),
        "model": ai_client.MODEL_SMART,
        "usage_today": ai_client.usage_today(),
    }

@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}
