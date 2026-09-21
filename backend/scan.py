#!/usr/bin/env python3
"""
Tan's Full US Market Morning Scan
Scans ALL US-listed stocks (NYSE + NASDAQ + AMEX) + upcoming IPOs
Runs your 180-pt algorithm and outputs top candidates

Usage:
    python3 morning_scan.py              # Full scan (~30-45 min)
    python3 morning_scan.py --quick      # S&P 500 only (~8 min)
    python3 morning_scan.py --positions  # Active positions only (~1 min)

Requirements:
    pip3 install yfinance pandas requests tqdm
"""

import socket
import yfinance as yf
import pandas as pd
import requests
import json
import sys
import time
import argparse
from datetime import datetime, timezone, date

socket.setdefaulttimeout(12)
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# YOUR ACTIVE POSITIONS - UPDATE WHEN FILLS CHANGE
# ─────────────────────────────────────────────
ACTIVE_POSITIONS = {
    'EPD': {'status': 'FILLED',  'entry': 36.80, 'shares': 27,  'stop': 33.86, 'day': 2},
    'ET':  {'status': 'PENDING', 'limit': 18.50, 'stop_if_fills': 17.02},
    'MDT': {'status': 'PENDING', 'limit': 85.50},
    'NKE': {'status': 'PENDING', 'limit': 44.00},
}
WATCHLIST = ['PODD', 'GD', 'VEEV', 'ABT', 'KMI']

# ─────────────────────────────────────────────
# TECHNICALS
# ─────────────────────────────────────────────
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
    upper = sma + 2*std
    lower = sma - 2*std
    pct = (prices.iloc[-1] - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]) * 100
    return pct

# ─────────────────────────────────────────────
# FULL SNAPSHOT (single ticker)
# ─────────────────────────────────────────────
def get_snapshot(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period='1y', interval='1d')
        if len(hist) < 50:
            return None

        prices = hist['Close']
        volume = hist['Volume']
        price = prices.iloc[-1]

        if price < 5 or price > 2000:
            return None

        avg_vol = info.get('averageDailyVolume3Month', 0) or 0
        if avg_vol < 500_000:
            return None  # not liquid enough

        ma20  = prices.rolling(20).mean().iloc[-1]
        ma50  = prices.rolling(50).mean().iloc[-1]
        ma200 = prices.rolling(200).mean().iloc[-1]
        rsi = get_rsi(prices).iloc[-1]
        macd_now, macd_prev = get_macd_hist(prices)
        bb_pct = get_bb_pct(prices)

        vol_today = volume.iloc[-1]
        vol_ratio = vol_today / avg_vol if avg_vol else None

        # Earnings
        earnings_ts = info.get('earningsTimestamp')
        days_to_earnings = None
        if earnings_ts:
            try:
                ed = datetime.fromtimestamp(earnings_ts, tz=timezone.utc)
                days_to_earnings = (ed - datetime.now(timezone.utc)).days
            except:
                pass

        # Relative strength vs S&P
        sp_52w  = (info.get('SandP52WeekChange') or 0) * 100
        stk_52w = (info.get('52WeekChange') or 0) * 100
        rel_str = stk_52w - sp_52w

        w52_low  = info.get('fiftyTwoWeekLow')  or price
        w52_high = info.get('fiftyTwoWeekHigh') or price
        pct_from_low = ((price - w52_low) / w52_low * 100) if w52_low else None

        # Financials
        fcf   = info.get('freeCashflow')
        de    = info.get('debtToEquity')
        fpe   = info.get('forwardPE')
        tpe   = info.get('trailingPE')
        peg   = info.get('pegRatio')
        beta  = info.get('beta')
        div_y = (info.get('trailingAnnualDividendYield') or 0) * 100
        short_pct  = (info.get('shortPercentOfFloat') or 0) * 100
        short_ratio = info.get('shortRatio')
        inst_own   = (info.get('heldPercentInstitutions') or 0) * 100
        analyst    = info.get('averageAnalystRating')  # e.g. "1.9 - Buy"
        eg = (info.get('earningsGrowth') or 0) * 100
        rg = (info.get('revenueGrowth')  or 0) * 100
        sector  = info.get('sector', 'Unknown')
        mktcap  = info.get('marketCap', 0) or 0
        name    = info.get('shortName', ticker)

        return {
            'ticker': ticker, 'name': name, 'sector': sector,
            'price': price, 'mktcap': mktcap,
            'ma20': ma20, 'ma50': ma50, 'ma200': ma200,
            'rsi': rsi, 'macd_now': macd_now, 'macd_prev': macd_prev,
            'macd_crossover': bool(macd_now > 0 and macd_prev < 0),
            'bb_pct': bb_pct, 'vol_ratio': vol_ratio,
            'days_to_earnings': days_to_earnings,
            'rel_strength': rel_str,
            'pct_from_52w_low': pct_from_low,
            'w52_high': w52_high, 'w52_low': w52_low,
            'fcf': fcf, 'debt_equity': de,
            'forward_pe': fpe, 'trailing_pe': tpe, 'peg': peg,
            'beta': beta or 1.0, 'div_yield': div_y,
            'short_pct': short_pct, 'short_ratio': short_ratio,
            'inst_own': inst_own, 'analyst': analyst,
            'earnings_growth': eg, 'revenue_growth': rg,
        }
    except:
        return None

# ─────────────────────────────────────────────
# SCORING (180 pts max)
# ─────────────────────────────────────────────
def score(s):
    pts = 0
    flags = []

    # AUTO-DISQUALIFIERS
    if s['days_to_earnings'] is not None and 0 < s['days_to_earnings'] < 15:
        return 0, ['❌ Earnings in <15 days']
    if s['debt_equity'] and s['debt_equity'] > 200:
        return 0, ['❌ Debt/Equity >200']
    if s['fcf'] is not None and s['fcf'] < 0:
        return 0, ['❌ Negative FCF']

    # RSI (25 pts)
    rsi = s['rsi']
    if rsi < 30:   pts += 25; flags.append(f'RSI {rsi:.0f} oversold 🔥')
    elif rsi < 40: pts += 15; flags.append(f'RSI {rsi:.0f} low')
    elif rsi < 50: pts += 5;  flags.append(f'RSI {rsi:.0f} neutral-low')

    # MACD (20 pts)
    if s['macd_crossover']:      pts += 20; flags.append('MACD crossover ✅')
    elif s['macd_now'] > s['macd_prev'] and s['macd_now'] < 0:
        pts += 10; flags.append('MACD improving')

    # Bollinger Band % (20 pts)
    bb = s['bb_pct']
    if bb < 20:   pts += 20; flags.append(f'BB% {bb:.0f} near lower band 🔥')
    elif bb < 40: pts += 10; flags.append(f'BB% {bb:.0f}')

    # Upside to 52W high as proxy for target (20 pts)
    if s['w52_high'] and s['price']:
        upside = (s['w52_high'] - s['price']) / s['price'] * 100
        if upside > 20:   pts += 20; flags.append(f'Upside {upside:.0f}% to 52W high 🎯')
        elif upside > 10: pts += 10; flags.append(f'Upside {upside:.0f}%')
        elif upside > 5:  pts += 5;  flags.append(f'Upside {upside:.0f}%')

    # Dividend yield (10 pts)
    dy = s['div_yield']
    if dy > 4:   pts += 10; flags.append(f'Div {dy:.1f}%')
    elif dy > 2: pts += 5;  flags.append(f'Div {dy:.1f}%')

    # Near 52W low (5 pts)
    if s['pct_from_52w_low'] is not None:
        if s['pct_from_52w_low'] < 10:
            pts += 5; flags.append('Near 52W low')

    # Volume confirmation (10 pts)
    vr = s['vol_ratio']
    if vr:
        if vr > 1.5:   pts += 10; flags.append(f'Vol {vr:.1f}x avg 📊')
        elif vr > 1.0: pts += 5;  flags.append(f'Vol {vr:.1f}x avg')

    # Relative strength vs S&P (10 pts)
    rs = s['rel_strength']
    if rs > 5:    pts += 10; flags.append(f'Outperforming S&P +{rs:.0f}%')
    elif rs > 0:  pts += 5;  flags.append(f'Inline with S&P')

    # Analyst rating (5 pts)
    ar = s['analyst']
    if ar:
        try:
            rating_num = float(ar.split(' ')[0])
            if rating_num <= 2.0:   pts += 5;  flags.append(f'Analyst: {ar}')
            elif rating_num <= 2.5: pts += 3;  flags.append(f'Analyst: {ar}')
        except:
            pass

    # Short interest - squeeze fuel (5 pts)
    if s['short_pct'] > 10: pts += 5; flags.append(f'Short {s["short_pct"]:.0f}% float 🚀')

    return pts, flags

# ─────────────────────────────────────────────
# POSITION SIZING
# ─────────────────────────────────────────────
def get_position_size(beta, vix):
    size = 1000
    if beta > 1.6:   size = 500
    elif beta > 1.3: size = 750
    if vix > 35:     size = int(size * 0.5)
    elif vix > 25:   size = int(size * 0.75)
    return size

# ─────────────────────────────────────────────
# GET ALL US TICKERS
# ─────────────────────────────────────────────
def get_all_us_tickers():
    """Fetch all US-listed securities from NASDAQ trader directory."""
    print("📋 Fetching full US ticker list from NASDAQ...")
    tickers = set()

    try:
        # NASDAQ listed
        r = requests.get('https://ftp.nasdaqtrader.com/symboldirectory/nasdaqlisted.txt', timeout=15)
        lines = r.text.strip().split('\n')
        for line in lines[1:]:  # skip header
            parts = line.split('|')
            if len(parts) >= 3 and parts[0] and parts[2] != 'Y':  # Y = ETF
                sym = parts[0].strip()
                if sym and sym.isalpha() and len(sym) <= 5:
                    tickers.add(sym)
        print(f"  NASDAQ: {len(tickers)} symbols")
    except Exception as e:
        print(f"  NASDAQ fetch failed: {e}")

    try:
        # Other listed (NYSE, AMEX, etc.)
        r2 = requests.get('https://ftp.nasdaqtrader.com/symboldirectory/otherlisted.txt', timeout=15)
        before = len(tickers)
        lines2 = r2.text.strip().split('\n')
        for line in lines2[1:]:
            parts = line.split('|')
            if len(parts) >= 5 and parts[0] and parts[4] != 'Y':  # Y = ETF
                sym = parts[0].strip()
                if sym and sym.replace('.', '').isalpha() and len(sym) <= 5:
                    tickers.add(sym)
        print(f"  NYSE/AMEX/Other: +{len(tickers)-before} symbols")
    except Exception as e:
        print(f"  Other fetch failed: {e}")

    # Fallback: S&P 500 from Wikipedia if FTP fails
    if len(tickers) < 100:
        print("  Using S&P 500 fallback...")
        try:
            sp500 = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')[0]
            for t in sp500['Symbol'].tolist():
                tickers.add(t.replace('.', '-'))
        except:
            pass

    result = sorted(list(tickers))
    print(f"  Total unique tickers: {len(result)}")
    return result

def get_sp500_tickers():
    """S&P 500 tickers - multi-source fallback chain."""
    print("📋 Fetching S&P 500 tickers...")

    # Source 1: GitHub-hosted CSV (datasets/s-and-p-500-companies)
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
        df = pd.read_csv(url, timeout=10) if False else pd.read_csv(url)
        tickers = [t.replace('.', '-') for t in df['Symbol'].tolist()]
        print(f"  ✓ {len(tickers)} tickers from datasets/s-and-p-500-companies")
        return tickers
    except Exception as e:
        print(f"  GitHub source failed: {e}")

    # Source 2: Wikipedia with browser headers
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        r = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers, timeout=10)
        tables = pd.read_html(StringIO(r.text))
        tickers = [t.replace('.', '-') for t in tables[0]['Symbol'].tolist()]
        print(f"  ✓ {len(tickers)} tickers from Wikipedia")
        return tickers
    except Exception as e:
        print(f"  Wikipedia failed: {e}")

    # Source 3: Finnhub (free tier supports /stock/symbol)
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        key = os.environ.get("FINNHUB_KEY", "")
        if key:
            r = requests.get("https://finnhub.io/api/v1/index/constituents",
                             params={"symbol": "^GSPC", "token": key}, timeout=10)
            data = r.json()
            if data.get("constituents"):
                tickers = [t.replace('.', '-') for t in data["constituents"]]
                print(f"  ✓ {len(tickers)} tickers from Finnhub")
                return tickers
    except Exception as e:
        print(f"  Finnhub failed: {e}")

    # Source 4: hardcoded mega-cap list (fallback floor - covers your themes)
    print("  ⚠️ All sources failed - using hardcoded mega-cap list")
    return [
        "AAPL","MSFT","NVDA","GOOGL","GOOG","AMZN","META","TSLA","BRK-B","AVGO",
        "JPM","V","WMT","XOM","UNH","MA","PG","JNJ","HD","COST","ORCL","ABBV",
        "BAC","KO","PEP","CVX","TMO","CSCO","WFC","CRM","ACN","ADBE","DIS","ABT",
        "MRK","NFLX","AMD","TXN","CMCSA","DHR","NKE","VZ","INTC","PFE","QCOM",
        "MCD","UPS","INTU","UNP","BMY","NEE","T","RTX","HON","LOW","COP","SBUX",
        "LIN","CAT","SPGI","IBM","AXP","PM","GS","BLK","ELV","DE","BA","GE","LMT",
        "MS","NOC","GD","HII","BWXT","KTOS","PANW","CRWD","NOW","SHOP","SNOW",
        "MU","ASML","TSM","ARM","SMCI","AVGO","ANET","CCJ","CEG","VST","SMR","OKLO",
        "MP","ALB","FCX","NEM","GOLD","FNV","WPM","AEM","KGC","XLE","XLF","XLK",
        "EPD","ET","KMI","WMB","OXY","VLO","MPC","PSX","SLB","HAL","BKR","DVN",
    ]

# ─────────────────────────────────────────────
# UPCOMING IPOs
# ─────────────────────────────────────────────
def get_upcoming_ipos():
    """Fetch upcoming IPO calendar."""
    print("\n📅 Fetching upcoming IPOs...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get('https://stockanalysis.com/ipos/upcoming/', headers=headers, timeout=10)
        tables = pd.read_html(StringIO(r.text))
        if tables:
            ipo_df = tables[0]
            print(f"  Found {len(ipo_df)} upcoming IPOs")
            return ipo_df.head(15)
    except Exception as e:
        print(f"  IPO fetch failed: {e}")
    return None

# ─────────────────────────────────────────────
# MARKET PULSE (SPY, QQQ, VIX)
# ─────────────────────────────────────────────
def get_market_pulse():
    print("\n📈 Market Pulse...")
    pulse = {}
    for sym in ['SPY', 'QQQ', '^VIX']:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period='3mo', interval='1d')
            price = hist['Close'].iloc[-1]
            rsi = get_rsi(hist['Close']).iloc[-1]
            pct_1d = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
            label = sym.replace('^', '')
            pulse[label] = {'price': price, 'rsi': rsi, 'pct_1d': pct_1d}
            print(f"  {label}: ${price:.2f} ({pct_1d:+.1f}%) | RSI {rsi:.0f}")
        except:
            pass
    vix = pulse.get('VIX', {}).get('price', 20)
    return pulse, vix

# ─────────────────────────────────────────────
# ACTIVE POSITIONS CHECK
# ─────────────────────────────────────────────
def check_positions(vix):
    print("\n💼 Active Positions & Pending Orders...")
    positions_data = {}
    for ticker, pos in ACTIVE_POSITIONS.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period='5d', interval='1d')
            price = hist['Close'].iloc[-1]
            pct_1d = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100

            if pos['status'] == 'FILLED':
                entry = pos['entry']
                pnl = (price - entry) / entry * 100
                day  = pos.get('day', '?')
                stop = pos.get('stop', entry * 0.92)
                pct_to_stop = (price - stop) / price * 100

                # Profit ladder check
                ladder = ''
                if pnl >= 20:  ladder = '🎯 SELL ALL (+20%)'
                elif pnl >= 15: ladder = '⚡ SELL 75% (+15%)'
                elif pnl >= 10: ladder = '✅ SELL 50% (+10%)'
                elif pnl >= 5:  ladder = '🔒 MOVE STOP TO BREAKEVEN (+5%)'
                elif pnl <= -8: ladder = '🛑 STOP TRIGGERED (-8%)'

                print(f"\n  {ticker} [FILLED @ ${entry:.2f} | Day {day}]")
                print(f"    Price: ${price:.2f} ({pct_1d:+.1f}% today) | P&L: {pnl:+.1f}%")
                print(f"    Stop:  ${stop:.2f} ({pct_to_stop:.1f}% cushion)")
                if ladder: print(f"    ⚠️  ACTION: {ladder}")

            elif pos['status'] == 'PENDING':
                limit = pos.get('limit', 0)
                gap = price - limit
                gap_pct = gap / price * 100
                alert = ' ⚡ CLOSE TO FILLING!' if abs(gap) < 0.30 else ''
                stop_price = pos.get('stop_if_fills', limit * 0.92)
                print(f"\n  {ticker} [GTC LIMIT @ ${limit:.2f}]")
                print(f"    Current: ${price:.2f} | Gap: ${gap:+.2f} ({gap_pct:+.1f}%){alert}")
                print(f"    Stop if fills: ${stop_price:.2f}")

        except Exception as e:
            print(f"  {ticker}: error - {e}")

    # Watchlist
    print(f"\n👁  Watchlist: {', '.join(WATCHLIST)}")
    watchlist_data = {}
    for ticker in WATCHLIST:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period='5d', interval='1d')
            price = hist['Close'].iloc[-1]
            pct_1d = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100
            rsi = get_rsi(hist['Close'].tail(60)).iloc[-1]
            print(f"  {ticker}: ${price:.2f} ({pct_1d:+.1f}%) | RSI {rsi:.0f}")
            watchlist_data[ticker] = {'price': round(price,2), 'pct_1d': round(pct_1d,2), 'rsi': round(rsi,1)}
        except:
            pass
    positions_data['watchlist'] = watchlist_data
    return positions_data

# ─────────────────────────────────────────────
# MAIN SCAN
# ─────────────────────────────────────────────
def run_scan(tickers, vix, max_workers=20):
    results = []
    total = len(tickers)
    done = 0
    errors = 0

    print(f"\n🔍 Scanning {total} tickers with {max_workers} workers...")
    print("    Progress: ", end='', flush=True)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(get_snapshot, t): t for t in tickers}
        for future in as_completed(futures):
            done += 1
            if done % 50 == 0:
                print(f"{done}..", end='', flush=True)
            try:
                s = future.result()
                if s:
                    pts, flags = score(s)
                    if pts >= 55:  # only keep candidates
                        pos_size = get_position_size(s['beta'], vix)
                        results.append({**s, 'score': pts, 'flags': flags, 'pos_size': pos_size})
            except:
                errors += 1

    print(f" done. ({errors} errors)")
    results.sort(key=lambda x: x['score'], reverse=True)
    return results

# ─────────────────────────────────────────────
# REPORT OUTPUT
# ─────────────────────────────────────────────
def save_json(results, pulse, ipos, positions_data):
    """Save scan results to JSON so Claude can read it directly in Cowork."""
    output = {
        'scan_time': datetime.now().isoformat(),
        'market_pulse': pulse,
        'top_candidates': [
            {k: v for k, v in r.items() if k != 'flags'} | {'flags': r.get('flags', []), 'score': r['score']}
            for r in results[:30]
        ],
        'high_conviction': [r['ticker'] for r in results if r['score'] >= 100],
        'strong_buy':      [r['ticker'] for r in results if 80 <= r['score'] < 100],
        'candidates':      [r['ticker'] for r in results if 60 <= r['score'] < 80],
        'ipos': ipos.to_dict('records') if ipos is not None else [],
        'positions': positions_data,
    }
    path = 'scan_results.json'
    with open(path, 'w', encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n💾 Results saved → {path}")
    print(f"   Share with Claude in Cowork: select folder containing this file,")
    print(f"   then say 'read scan results and run trading system'")

def print_report(results, pulse, ipos, args):
    now = datetime.now()
    print(f"\n{'='*65}")
    print(f"  TAN'S MORNING SCAN - {now.strftime('%A %b %d %Y, %I:%M %p MST')}")
    print(f"{'='*65}")

    # Market pulse summary
    spy = pulse.get('SPY', {})
    qqq = pulse.get('QQQ', {})
    vix = pulse.get('VIX', {})
    spy_rsi = spy.get('rsi', 0)
    regime = '🔴 OVERBOUGHT - be selective' if spy_rsi > 75 else \
             '🟡 NEUTRAL' if spy_rsi > 45 else \
             '🟢 OVERSOLD - ideal hunting ground'
    print(f"\n  SPY ${spy.get('price',0):.0f} RSI {spy_rsi:.0f} | QQQ RSI {qqq.get('rsi',0):.0f} | VIX {vix.get('price',0):.1f}")
    print(f"  Market regime: {regime}")

    # Top candidates
    top = [r for r in results if r['score'] >= 60]
    high_conviction = [r for r in results if r['score'] >= 100]
    strong = [r for r in results if 80 <= r['score'] < 100]
    candidates = [r for r in results if 60 <= r['score'] < 80]

    print(f"\n{'─'*65}")
    print(f"  SCAN RESULTS: {len(top)} candidates from {sum(1 for r in results if r)+ len(results)} scanned")
    print(f"  🔥 High conviction (≥100): {len(high_conviction)}")
    print(f"  ✅ Strong buy (80-99):     {len(strong)}")
    print(f"  👀 Candidate (60-79):      {len(candidates)}")

    for tier, label in [(high_conviction, '🔥 HIGH CONVICTION'), (strong, '✅ STRONG BUY'), (candidates[:5], '👀 CANDIDATES (top 5)')]:
        if not tier:
            continue
        print(f"\n  {label}")
        print(f"  {'Ticker':<8} {'Score':<7} {'Price':<9} {'RSI':<7} {'Sector':<22} {'Size':<7} Notes")
        print(f"  {'─'*8} {'─'*6} {'─'*8} {'─'*6} {'─'*22} {'─'*6} {'─'*30}")
        for r in tier[:10]:
            notes = ' | '.join(r['flags'][:2])
            sector = (r['sector'] or 'Unknown')[:20]
            print(f"  {r['ticker']:<8} {r['score']:<7} ${r['price']:<8.2f} {r['rsi']:<7.0f} {sector:<22} ${r['pos_size']:<5} {notes}")

    # IPO section
    if ipos is not None and not args.positions:
        print(f"\n{'─'*65}")
        print(f"  📅 UPCOMING IPOs")
        print(ipos.to_string(index=False, max_rows=10))

    print(f"\n{'='*65}")
    print(f"  Run completed: {datetime.now().strftime('%I:%M:%S %p')}")
    print(f"  Tip: Add new candidates to WATCHLIST in this script")
    print(f"{'='*65}\n")

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Tan's Morning Scan")
    parser.add_argument('--quick',     action='store_true', help='S&P 500 only (~8 min)')
    parser.add_argument('--positions', action='store_true', help='Active positions only (~1 min)')
    parser.add_argument('--workers',   type=int, default=20, help='Parallel workers (default 20)')
    args = parser.parse_args()

    print("\n🌅 TAN'S MORNING SCAN STARTING...")
    print(f"   Mode: {'Positions only' if args.positions else 'S&P 500 quick' if args.quick else 'Full US market'}")

    # Market pulse + VIX first
    pulse, vix = get_market_pulse()

    # Active positions check always
    positions_data = check_positions(vix)

    if args.positions:
        # Save positions-only JSON
        save_json([], pulse, None, positions_data or {})
        print("\n✅ Positions check complete.")
        return

    # Get tickers
    if args.quick:
        tickers = get_sp500_tickers()
    else:
        tickers = get_all_us_tickers()

    # Upcoming IPOs
    ipos = get_upcoming_ipos() if not args.quick else None

    # Run scan
    start = time.time()
    results = run_scan(tickers, vix, max_workers=args.workers)
    elapsed = time.time() - start
    print(f"   Scan completed in {elapsed/60:.1f} minutes")

    # Print report + save JSON
    print_report(results, pulse, ipos, args)
    save_json(results, pulse, ipos, {})

if __name__ == '__main__':
    main()
