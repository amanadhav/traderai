"""
ETF Sector Thesis Scorer
========================
Scores ETFs on 5-factor framework designed for sector ETFs and long-term compounding.
NOT the same as stock score.py - ETFs don't have FCF/D-E/earnings risk.

Scoring (100 pts max):
  1. Policy Tailwind      (0-25) - legislation, government direction, bipartisan support
  2. Catalyst Pipeline    (0-25) - near-term events driving the sector in next 12 months
  3. Macro Event Align    (0-20) - war, pandemic, AI wave, geopolitical events
  4. Valuation/Cycle      (0-20) - LIVE from yfinance: RSI + BB%
  5. Trend Duration       (0-10) - 1yr trade vs 10yr compounding

Thresholds:
  ≥70 = BUY  ·  ≥85 = STRONG  ·  ≥95 = CONVICTION

Usage:
  python3 etf_score.py XLU
  python3 etf_score.py --all
  python3 etf_score.py --sector energy
  python3 etf_score.py --sector defense
  python3 etf_score.py --sector ai
"""

from __future__ import annotations
import sys
import socket
from pathlib import Path

socket.setdefaulttimeout(15)

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()

# ── Sector Knowledge Base ──────────────────────────────────────────────────
# Qualitative scores: policy (0-25) + catalysts (0-25) + macro (0-20) + duration (0-10)
# Valuation (0-20) fetched live from yfinance
# Last updated: 2026-05

SECTOR_DB: dict[str, dict] = {

    # ══ ENERGY - GRID / UTILITIES ═════════════════════════════════════════
    "GRID": {
        "name": "First Trust NASDAQ Smart Grid & Energy Storage",
        "sector": "Energy - Grid Infrastructure",
        "group": "energy",
        "holdings": "ITRI, Eaton, ABB, Hubbell, ENPH",
        "policy_score": 24,
        "policy_note": "Bipartisan Infrastructure Bill $65B grid. Both parties want energy independence. Grid Modernization Act.",
        "catalyst_score": 24,
        "catalyst_note": "AI data centers demand grid upgrades now. EV charging infra. DOE grid hardening grants. Extreme weather events forcing upgrades.",
        "macro_score": 20,
        "macro_note": "US grid built in 1960s. AI needs 10x power by 2035. Every electrification trend flows through grid. Bottleneck = maximum pricing power.",
        "duration_score": 10,
        "duration_note": "10-15yr - grid upgrades are multi-decade capital programs. Highest visibility of any sector.",
    },
    "XLU": {
        "name": "Utilities Select SPDR",
        "sector": "Energy - Utilities / Power",
        "group": "energy",
        "holdings": "NEE, DUK, SO, D, AEP, EXC",
        "policy_score": 22,
        "policy_note": "Bipartisan: nuclear licensing fast-tracked, IRA grid investment, grid hardening bills.",
        "catalyst_score": 22,
        "catalyst_note": "AI data center power demand explosion (+30% US electricity by 2035). Nuclear PPAs. Regulated utilities = guaranteed returns on grid capex.",
        "macro_score": 18,
        "macro_note": "AI needs 10x power. EVs need grid. Defense needs power. Manufacturing reshoring needs power. All roads lead to utilities.",
        "duration_score": 10,
        "duration_note": "10-15yr structural - US electricity demand was flat 20 years, now parabolic.",
    },
    "NUCL": {
        "name": "VanEck Uranium + Nuclear ETF",
        "sector": "Energy - Nuclear",
        "group": "energy",
        "holdings": "CCJ, Cameco, NuScale, uranium miners, nuclear operators",
        "policy_score": 23,
        "policy_note": "Bipartisan nuclear renaissance. Trump nuclear EO + SMR fast-track legislation. Biden-era licensing reform intact. Both parties want nuclear.",
        "catalyst_score": 24,
        "catalyst_note": "MSFT 20yr Three Mile Island PPA. Google 500MW SMR deal. Amazon 5GW nuclear. DOE $900M loan guarantees. Trump: US gets uranium from Iran deal.",
        "macro_score": 20,
        "macro_note": "AI data centers need 24/7 baseload power - solar/wind can't do it. Nuclear = only carbon-free baseload. Forced renaissance. Early entry = max compounding.",
        "duration_score": 10,
        "duration_note": "10-20yr - nuclear plants take 7-10 years to build. Get in now or miss the build cycle.",
    },
    "LIT": {
        "name": "Global X Lithium & Battery Tech ETF",
        "sector": "Energy - Battery / Critical Minerals",
        "group": "energy",
        "holdings": "ALB, SQM, LTHM, BYD, Panasonic, Ganfeng",
        "policy_score": 16,
        "policy_note": "IRA battery credits intact. Some Trump EV headwind but grid storage is separate from EV policy.",
        "catalyst_score": 18,
        "catalyst_note": "Grid storage explosion (solar/wind need storage). EV ramp. Critical mineral strategic reserves. China decoupling = domestic battery supply chain.",
        "macro_score": 15,
        "macro_note": "China controls 85% lithium processing. US decoupling = domestic critical minerals push. Battery cost curves still declining - inflection 2026-2028.",
        "duration_score": 7,
        "duration_note": "5-7yr - grid storage inflection imminent. EV adoption still early.",
    },
    "XLE": {
        "name": "Energy Select SPDR",
        "sector": "Energy - Oil + Gas",
        "group": "energy",
        "holdings": "XOM, CVX, COP, EOG, SLB, PXD",
        "policy_score": 18,
        "policy_note": "Trump 'drill baby drill' + LNG exports. Iran war = oil price support. Some IRA headwind on renewables.",
        "catalyst_score": 18,
        "catalyst_note": "Iran war disrupting supply. Hormuz risk premium. LNG export terminals. OPEC+ production discipline.",
        "macro_score": 16,
        "macro_note": "Iran war active - 10.1 mb/d supply disruption. Peace deal risk = near-term headwind. Structural: global energy demand still rising.",
        "duration_score": 6,
        "duration_note": "3-5yr hold. Long-term EV transition is headwind but 2026-2030 oil still dominant.",
    },
    "ICLN": {
        "name": "iShares Global Clean Energy ETF",
        "sector": "Energy - Clean / Renewable",
        "group": "energy",
        "holdings": "ENPH, FSLR, NEE, Vestas, Orsted, SolarEdge",
        "policy_score": 12,
        "policy_note": "IRA tailwind but Trump EO headwinds on offshore wind. Partial policy support - politically contested.",
        "catalyst_score": 14,
        "catalyst_note": "Solar cost curves, corporate PPA demand, IRA tax credits, European renewable mandates.",
        "macro_score": 12,
        "macro_note": "Real tailwinds but politically volatile. Orsted offshore wind cancellations show policy risk is real.",
        "duration_score": 7,
        "duration_note": "5-10yr real trend but more volatile with political cycles than nuclear/grid.",
    },
    "URNM": {
        "name": "Sprott Uranium Miners ETF",
        "sector": "Energy - Uranium Miners (pure play)",
        "group": "energy",
        "holdings": "CCJ, NXE, DNN, UEC, Kazatomprom",
        "policy_score": 22,
        "policy_note": "Same nuclear tailwinds as NUCL. Pure uranium miners = higher beta on nuclear theme.",
        "catalyst_score": 23,
        "catalyst_note": "Utility uranium contracts locked in long-term. Spot price driven by nuclear PPA demand.",
        "macro_score": 19,
        "macro_note": "Uranium supply constrained. Kazakhstan supply risk. US utility demand locked in decades.",
        "duration_score": 10,
        "duration_note": "10-20yr - uranium contracts are 10-15 year deals. Visibility = maximum.",
    },

    # ══ DEFENSE ════════════════════════════════════════════════════════════
    "ITA": {
        "name": "iShares US Aerospace & Defense ETF",
        "sector": "Defense - Broad",
        "group": "defense",
        "holdings": "RTX, NOC, LMT, GD, HII, L3Harris",
        "policy_score": 20,
        "policy_note": "Bipartisan - NDAA defense budgets increase every year regardless of party. NATO 5% GDP target locked in.",
        "catalyst_score": 20,
        "catalyst_note": "Iran war active. Europe rearmament supercycle. Ukraine rebuild contracts. US shipbuilding backlog 9+ years.",
        "macro_score": 18,
        "macro_note": "Active shooting war (Iran). Germany defense +154%. Global military $2.89T in 2025. Structural not cyclical.",
        "duration_score": 10,
        "duration_note": "10yr+ - rearmament cycles last decades once started. Rheinmetall 9.5yr backlog tells you everything.",
    },
    "DFEN": {
        "name": "Direxion Daily Aerospace & Defense 3x Bull",
        "sector": "Defense - 3x Leveraged",
        "group": "defense",
        "holdings": "3x ITA components",
        "policy_score": 20,
        "policy_note": "Same thesis as ITA - 3x leveraged.",
        "catalyst_score": 20,
        "catalyst_note": "Same catalysts as ITA - amplified.",
        "macro_score": 18,
        "macro_note": "Same macro as ITA. Decay risk on leveraged ETF - max 12 month hold.",
        "duration_score": 3,
        "duration_note": "⚠️ Leveraged = daily decay. 1-2yr MAX. Trade, not invest.",
    },

    # ══ AI / SEMICONDUCTORS ════════════════════════════════════════════════
    "SMH": {
        "name": "VanEck Semiconductor ETF",
        "sector": "AI - Semiconductors",
        "group": "ai",
        "holdings": "NVDA, TSM, ASML, AMD, AVGO, INTC, QCOM",
        "policy_score": 22,
        "policy_note": "CHIPS Act $52B. Bipartisan semiconductor independence. Export controls on China = US fab investment boom.",
        "catalyst_score": 23,
        "catalyst_note": "AI training demand parabolic. AMD Q1 +57% data center. TSMC 2nm ramp H2 2025. ASML EUV SK Hynix + Samsung $8B each.",
        "macro_score": 20,
        "macro_note": "AI infrastructure = generational capex cycle. Every hyperscaler spending $100B+ annually on AI chips. No slowdown visible.",
        "duration_score": 10,
        "duration_note": "10yr+ - semiconductor cycles are long. AI demand is structural, not hype.",
    },
    "SOXX": {
        "name": "iShares Semiconductor ETF",
        "sector": "AI - Semiconductors",
        "group": "ai",
        "holdings": "NVDA, AVGO, AMD, QCOM, TSM, INTC, MRVL",
        "policy_score": 22,
        "policy_note": "Same as SMH - CHIPS Act + AI infrastructure bipartisan.",
        "catalyst_score": 23,
        "catalyst_note": "Same catalysts as SMH - slightly different weighting.",
        "macro_score": 20,
        "macro_note": "Same as SMH.",
        "duration_score": 10,
        "duration_note": "10yr+ structural.",
    },
    "BOTZ": {
        "name": "Global X Robotics & AI ETF",
        "sector": "AI - Robotics / Physical AI",
        "group": "ai",
        "holdings": "FANUC, Intuitive Surgical, Keyence, ABB, NVDA",
        "policy_score": 18,
        "policy_note": "Manufacturing reshoring + automation incentives. Bipartisan industrial policy (CHIPS, IRA, Inflation Reduction Act manufacturing).",
        "catalyst_score": 20,
        "catalyst_note": "Tesla Optimus 50K units 2026. NVIDIA Isaac platform (robotics OS). Labor shortage = automation demand surge. Humanoid robot cost -40% in one year.",
        "macro_score": 18,
        "macro_note": "Physical AI wave - Jensen named it the next market. Factory automation = structural labor replacement. Every manufacturer building robotics roadmap.",
        "duration_score": 10,
        "duration_note": "10yr+ - humanoid robots are the iPhone moment for manufacturing. We are at 2007.",
    },
    "ARKQ": {
        "name": "ARK Autonomous Tech & Robotics ETF",
        "sector": "AI - Autonomous / Robotics",
        "group": "ai",
        "holdings": "TSLA, Kratos, UIPATH, Trimble, Iridium",
        "policy_score": 15,
        "policy_note": "Mixed - heavy TSLA exposure = Musk/Trump political sensitivity. ARK fund management risk.",
        "catalyst_score": 16,
        "catalyst_note": "Autonomous vehicles, drones, robotics. Real catalysts but ARK concentration adds fund-specific risk.",
        "macro_score": 15,
        "macro_note": "Real underlying trends. Fund manager risk (ARK track record volatile).",
        "duration_score": 7,
        "duration_note": "5-10yr - real but higher fund-specific risk than passive sector ETFs.",
    },

    # ══ HEALTHCARE ═════════════════════════════════════════════════════════
    "XLV": {
        "name": "Health Care Select SPDR",
        "sector": "Healthcare - Broad",
        "group": "healthcare",
        "holdings": "LLY, UNH, JNJ, ABT, MDT, BMY, PFE",
        "policy_score": 14,
        "policy_note": "Mixed - drug pricing legislation headwind (IRA drug price negotiation). Aging population = structural tailwind.",
        "catalyst_score": 16,
        "catalyst_note": "GLP-1 obesity treatment boom. AI drug discovery acceleration. Aging Baby Boomers peak healthcare spend 2025-2040.",
        "macro_score": 14,
        "macro_note": "Aging demographics = demand doesn't stop. AI drug discovery compressing 10yr timelines to 2yr.",
        "duration_score": 10,
        "duration_note": "10yr+ - demographics don't reverse. GLP-1 is a 20yr revenue stream.",
    },
    "ARKG": {
        "name": "ARK Genomic Revolution ETF",
        "sector": "Healthcare - Genomics",
        "group": "healthcare",
        "holdings": "CRISPR Therapeutics, Intellia, BEAM, Pacbio, Twist",
        "policy_score": 14,
        "policy_note": "NIH funding. FDA fast-track pathways for gene therapies. Bipartisan rare disease support.",
        "catalyst_score": 18,
        "catalyst_note": "CRISPR sickle cell cure approved. First gene therapies becoming commercial. Cost curves declining = more indications.",
        "macro_score": 16,
        "macro_note": "Gene editing = next pharmaceutical wave. CRISPR cost curve following same path as sequencing. Early innings.",
        "duration_score": 10,
        "duration_note": "10-15yr - genetic medicine is at 2010 smartphone moment. Most value still ahead.",
    },

    # ══ MATERIALS / CRITICAL MINERALS ══════════════════════════════════════
    "REMX": {
        "name": "VanEck Rare Earth / Strategic Metals ETF",
        "sector": "Materials - Rare Earth",
        "group": "materials",
        "holdings": "MP Materials, Lynas, Iluka, Energy Fuels",
        "policy_score": 24,
        "policy_note": "Executive orders on critical minerals. NDAA domestic rare earth mandates. Both parties: national security asset.",
        "catalyst_score": 22,
        "catalyst_note": "China dysprosium/terbium export ban 2026. MP Materials Apple $500M deal. Pentagon NDAA contracts. Rare earth supply chain decoupling.",
        "macro_score": 20,
        "macro_note": "China controls 85-90% RE processing. EV motors + wind turbines + weapons systems all need rare earth magnets. Cannot substitute.",
        "duration_score": 10,
        "duration_note": "10yr+ - building domestic RE supply chain takes a decade. REMX captures the whole ecosystem.",
    },

    # ══ MACRO HEDGES ═══════════════════════════════════════════════════════
    "GLD": {
        "name": "SPDR Gold Shares",
        "sector": "Macro Hedge - Gold",
        "group": "macro",
        "holdings": "Physical gold",
        "policy_score": 20,
        "policy_note": "De-dollarization = central banks buying gold at record pace. No political headwind - both parties accept gold.",
        "catalyst_score": 18,
        "catalyst_note": "Iran war, BRICS gold accumulation, Fed uncertainty, bond vigilante risk, dollar reserve share declining.",
        "macro_score": 18,
        "macro_note": "Real rates uncertain. Dollar reserve share declining. Multiple geopolitical tail risks. Gold at all-time highs for a reason.",
        "duration_score": 10,
        "duration_note": "Permanent hedge - no exit thesis. Hold forever as % of portfolio.",
    },
    "SLV": {
        "name": "iShares Silver Trust",
        "sector": "Macro Hedge - Silver",
        "group": "macro",
        "holdings": "Physical silver",
        "policy_score": 16,
        "policy_note": "Industrial + monetary hedge. Solar panels use silver - IRA solar demand = silver industrial bid.",
        "catalyst_score": 16,
        "catalyst_note": "Solar demand for silver (each panel uses ~20g). Gold/silver ratio historically elevated = silver catch-up potential.",
        "macro_score": 15,
        "macro_note": "Iran peace news May 2026 sent silver +5% to $76-77. Industrial + monetary = dual demand driver.",
        "duration_score": 8,
        "duration_note": "5-10yr - solar build-out drives industrial demand for decade.",
    },
}


def get_valuation_score(ticker: str) -> tuple[int, str, dict]:
    """Fetch live RSI + BB% + below 200MA → valuation score (0-25)."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y", interval="1d")
        if hist.empty:
            return 0, "No price data", {}
        prices = hist["Close"]
        price = float(prices.iloc[-1])

        # RSI
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        rsi = float((100 - (100 / (1 + gain / loss))).iloc[-1])

        # BB%
        sma = prices.rolling(20).mean()
        std = prices.rolling(20).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        denom = float(upper.iloc[-1] - lower.iloc[-1])
        bb_pct = float((prices.iloc[-1] - lower.iloc[-1]) / denom * 100) if denom != 0 else 50.0

        # MACD
        ema12 = prices.ewm(span=12, adjust=False).mean()
        ema26 = prices.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist_vals = macd - signal
        macd_improving = bool(hist_vals.iloc[-1] > hist_vals.iloc[-2])

        # Day change
        day_chg = float((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2] * 100) if len(prices) >= 2 else 0.0

        # 52W + 200MA
        high_52 = float(prices.rolling(252).max().iloc[-1])
        low_52  = float(prices.rolling(252).min().iloc[-1])
        ma200   = float(prices.rolling(200).mean().iloc[-1])
        pct_from_low = ((price - low_52) / low_52 * 100) if low_52 else 0
        below_200ma  = price < ma200

        # RSI + BB% base score (0-20)
        if rsi < 30 and bb_pct < 20:
            score = 20
            note = f"RSI {rsi:.1f} + BB% {bb_pct:.1f} - deeply oversold. BEST entry."
        elif rsi < 30:
            score = 17
            note = f"RSI {rsi:.1f} oversold. BB% {bb_pct:.1f} - not yet at lower band."
        elif rsi < 40 and bb_pct < 20:
            score = 15
            note = f"RSI {rsi:.1f} + BB% {bb_pct:.1f} - good entry zone."
        elif rsi < 40:
            score = 12
            note = f"RSI {rsi:.1f} near oversold. BB% {bb_pct:.1f}."
        elif rsi < 50:
            score = 8
            note = f"RSI {rsi:.1f} neutral. Acceptable entry."
        elif rsi < 60:
            score = 4
            note = f"RSI {rsi:.1f} slightly elevated. Better to wait."
        else:
            score = 0
            note = f"RSI {rsi:.1f} overbought. Wait for pullback."

        # Below 200MA bonus (0-5) - sector ETF below 200MA = mean reversion room
        if below_200ma:
            score += 5
            note += f" | Below 200MA (${ma200:.2f}) +5."

        live = {
            "price": price, "rsi": rsi, "bb_pct": bb_pct,
            "macd_improving": macd_improving, "day_chg": day_chg,
            "52w_high": high_52, "52w_low": low_52, "pct_from_low": pct_from_low,
            "ma200": ma200, "below_200ma": below_200ma,
        }
        return score, note, live

    except Exception as e:
        return 0, f"Fetch error: {e}", {}


def score_etf(ticker: str) -> dict | None:
    ticker = ticker.upper()
    db = SECTOR_DB.get(ticker)
    if not db:
        console.print(f"[yellow]{ticker} not in sector knowledge base. Add to SECTOR_DB in etf_score.py.[/]")
        return None

    val_score, val_note, live = get_valuation_score(ticker)

    total = (
        db["policy_score"]
        + db["catalyst_score"]
        + db["macro_score"]
        + val_score
        + db["duration_score"]
    )
    qual_max = 25 + 25 + 20 + 10  # qualitative max (no valuation). Val adds 0-25 (20 RSI/BB + 5 below 200MA)
    qual_total = db["policy_score"] + db["catalyst_score"] + db["macro_score"] + db["duration_score"]

    return {
        "ticker": ticker,
        "name": db["name"],
        "sector": db["sector"],
        "group": db["group"],
        "holdings": db["holdings"],
        "policy_score": db["policy_score"],
        "policy_note": db["policy_note"],
        "catalyst_score": db["catalyst_score"],
        "catalyst_note": db["catalyst_note"],
        "macro_score": db["macro_score"],
        "macro_note": db["macro_note"],
        "val_score": val_score,
        "val_note": val_note,
        "duration_score": db["duration_score"],
        "duration_note": db["duration_note"],
        "qual_total": qual_total,
        "qual_max": qual_max,
        "total": total,
        "live": live,
    }


def print_etf_score(r: dict) -> None:
    live = r["live"]
    total = r["total"]

    # Thresholds scaled to 105pt max (25+25+20+25+10)
    if total >= 98:
        verdict = "[bold red]🔥 CONVICTION BUY"
        color = "red"
    elif total >= 85:
        verdict = "[bold green]💪 STRONG BUY"
        color = "green"
    elif total >= 70:
        verdict = "[bold yellow]✅ BUY"
        color = "yellow"
    elif total >= 55:
        verdict = "[yellow]⏳ WATCH - almost there"
        color = "yellow"
    else:
        verdict = "[dim]⛔ WAIT"
        color = "white"

    price_str = f"${live.get('price', 0):.2f}" if live else "N/A"
    rsi_str = f"{live.get('rsi', 0):.1f}" if live else "N/A"
    day_str = f"{live.get('day_chg', 0):+.1f}%" if live else ""

    console.print()
    console.rule(f"[bold]ETF THESIS SCORE: {r['ticker']}[/]")
    console.print(f"  {r['name']}")
    console.print(f"  {r['sector']}")
    console.print(f"  Holdings: [dim]{r['holdings']}[/]")
    if live:
        console.print(f"  Price: {price_str}  RSI: {rsi_str}  Day: {day_str}  52W low+{live.get('pct_from_low', 0):.0f}%")
    console.print()

    rows = [
        ("Policy Tailwind",   r["policy_score"],   25, r["policy_note"]),
        ("Catalyst Pipeline", r["catalyst_score"],  25, r["catalyst_note"]),
        ("Macro Alignment",   r["macro_score"],     20, r["macro_note"]),
        ("Valuation/Cycle",   r["val_score"],       20, r["val_note"]),
        ("Trend Duration",    r["duration_score"],  10, r["duration_note"]),
    ]

    for label, pts, mx, note in rows:
        bar = "█" * pts + "░" * (mx - pts)
        console.print(f"  [bold]{label:20s}[/] [{color}]{pts:2d}/{mx}[/]  {bar[:25]}  [dim]{note[:80]}[/]")

    console.print()
    console.print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    console.print(f"  TOTAL: [{color}][bold]{total}/100[/][/]   {verdict}[/]")
    console.print(f"  Thesis strength (no valuation): {r['qual_total']}/{r['qual_max']}")
    console.print(f"  ≥70=BUY  ≥85=STRONG  ≥98=CONVICTION  (105pt max)")
    console.print()


def print_summary_table(results: list[dict]) -> None:
    results_sorted = sorted(results, key=lambda x: x["total"], reverse=True)

    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
    t.add_column("ETF", style="bold", width=6)
    t.add_column("Sector", width=28)
    t.add_column("Score", justify="right", width=6)
    t.add_column("Signal", width=14)
    t.add_column("Price", justify="right", width=8)
    t.add_column("RSI", justify="right", width=5)
    t.add_column("Day%", justify="right", width=7)
    t.add_column("Policy", justify="right", width=7)
    t.add_column("Catalyst", justify="right", width=9)
    t.add_column("Macro", justify="right", width=6)
    t.add_column("Val", justify="right", width=4)

    for r in results_sorted:
        live = r.get("live", {})
        total = r["total"]
        if total >= 98:   signal = "🔥 CONVICTION"
        elif total >= 85: signal = "💪 STRONG BUY"
        elif total >= 70: signal = "✅ BUY"
        elif total >= 55: signal = "⏳ WATCH"
        else:             signal = "⛔ WAIT"

        t.add_row(
            r["ticker"],
            r["sector"][:28],
            f"[bold]{total}[/]",
            signal,
            f"${live.get('price', 0):.2f}" if live else "-",
            f"{live.get('rsi', 0):.1f}" if live else "-",
            f"{live.get('day_chg', 0):+.1f}%" if live else "-",
            str(r["policy_score"]),
            str(r["catalyst_score"]),
            str(r["macro_score"]),
            str(r["val_score"]),
        )

    console.print(t)


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        console.print(__doc__)
        return

    if args[0] == "--all":
        console.print("\n[bold]Scoring all ETFs in knowledge base...[/]\n")
        results = []
        for ticker in SECTOR_DB:
            console.print(f"[dim]  {ticker}...[/]", end="\r")
            r = score_etf(ticker)
            if r:
                results.append(r)
        console.print()
        print_summary_table(results)
        return

    if args[0] == "--sector":
        group = args[1].lower() if len(args) > 1 else ""
        tickers = [k for k, v in SECTOR_DB.items() if v.get("group") == group]
        if not tickers:
            console.print(f"[red]Unknown sector '{group}'. Options: energy, defense, ai, healthcare, materials, macro[/]")
            return
        console.print(f"\n[bold]Scoring {group.upper()} ETFs...[/]\n")
        results = []
        for ticker in tickers:
            r = score_etf(ticker)
            if r:
                results.append(r)
        print_summary_table(results)
        # Also print detail on top scorer
        if results:
            best = max(results, key=lambda x: x["total"])
            print_etf_score(best)
        return

    # Single ticker
    ticker = args[0].upper()
    r = score_etf(ticker)
    if r:
        print_etf_score(r)


if __name__ == "__main__":
    main()
