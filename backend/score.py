"""
180-point entry scoring algorithm.
Usage: from score import score_ticker, explain_score

Scoring factors (180 pts max):
  RSI (25) · MACD (20) · BB% (20) · Upside (20) · Div yield (10)
  52W low (5) · Volume (10) · Rel strength (10) · Analyst (5) · Short squeeze (5)
  Pattern bonus (10) · Below 200MA (10) · FCF yield >5% (10)
  Macro narrative (10) · Insider buying (10)

Thresholds: ≥70=candidate · ≥110=strong · ≥140=high conviction
Auto-disqualifiers: earnings <15d · D/E >200 · negative FCF · bearish pattern
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

# ── Macro Narrative Alignment ────────────────────────────────────────────────
# Active structural themes as of 2026-05. Update when narratives change.
# Tickers aligned with these = structural tailwind already in place.

ACTIVE_NARRATIVES: dict[str, str] = {
    "iran_hormuz":      "Iran War / Hormuz disruption - active shooting war, oil supply constrained",
    "rare_earth":       "US rare earth decoupling - China export bans on dysprosium/terbium escalating",
    "china_decoupling": "US-China decoupling - semiconductor independence, CHIPS Act, export controls",
    "ai_infra":         "AI infrastructure supercycle - hyperscaler capex $100B+ each, parabolic",
    "defense":          "Global rearmament supercycle - NATO 5% GDP, Europe €800B, 9.5yr backlogs",
    "nuclear_energy":   "Nuclear renaissance - MSFT/Google/Amazon PPAs, Trump nuclear EO, SMR fast-track",
    "energy_grid":      "Grid modernization - AI + EV demanding 10x US electricity by 2035",
    "dedollarization":  "BRICS de-dollarization - central banks buying gold at record pace",
    "glp1_obesity":     "GLP-1 obesity revolution - Wegovy prescriptions +65% new scripts YoY",
    "chip_independence":"Semiconductor independence - CHIPS Act $52B, US fab investment boom",
    "defense_it":       "AI defense analytics - NDAA contracts, national security AI spending",
    "quantum":          "Quantum computing race - IBM/Google/IonQ verified quantum advantage 2026, NSF funding",
    "auto_ev":          "EV/AV supercycle - Tesla FSD, China EV price war, charging infra buildout",
}

# ── Sector-default narratives ───────────────────────────────────────────────
# Hand-curated TICKER_NARRATIVES is high-quality but slow to maintain (32%
# universe coverage as of 2026-05). Sector defaults give baseline coverage
# for tickers we haven't curated yet. yfinance `industry` field drives lookup.
# Combined with TICKER_NARRATIVES via union - explicit overrides still win.
SECTOR_NARRATIVES: dict[str, list[str]] = {
    # NOTE: yfinance returns industry strings with hyphen-space ("Software - Infrastructure")
    # not em-dash ("Software-Infrastructure"). Bug fix 2026-05-09: matched correctly now.
    # Semis - every chip-adjacent ticker gets AI infra + chip independence
    "Semiconductors":                       ["ai_infra", "chip_independence"],
    "Semiconductor Equipment & Materials":  ["ai_infra", "chip_independence"],
    # Defense
    "Aerospace & Defense":                  ["defense"],
    # Energy / midstream - Hormuz disruption beneficiaries
    "Oil & Gas Midstream":                  ["iran_hormuz"],
    "Oil & Gas E&P":                        ["iran_hormuz"],
    "Oil & Gas Refining & Marketing":       ["iran_hormuz"],
    "Oil & Gas Integrated":                 ["iran_hormuz"],
    "Oil & Gas Equipment & Services":       ["iran_hormuz"],
    # Software - broad AI infra wave (yfinance uses hyphen-space)
    "Software - Infrastructure":            ["ai_infra"],
    "Software - Application":               ["ai_infra"],
    "Information Technology Services":      ["ai_infra"],
    # Communications - AI + ad-driven
    "Internet Content & Information":       ["ai_infra"],
    "Telecom Services":                     ["energy_grid"],
    # Utilities - grid + nuclear renaissance
    "Utilities - Regulated Electric":       ["energy_grid"],
    "Utilities - Diversified":              ["energy_grid"],
    "Utilities - Renewable":                ["energy_grid", "nuclear_energy"],
    "Utilities - Independent Power Producers": ["nuclear_energy", "energy_grid"],
    # Mining / minerals
    "Other Industrial Metals & Mining":     ["rare_earth", "china_decoupling"],
    "Specialty Industrial Machinery":       ["china_decoupling"],
    "Uranium":                              ["nuclear_energy"],
    # Hardware / cloud-adjacent
    "Computer Hardware":                    ["ai_infra"],
    "Electronic Components":                ["ai_infra", "chip_independence"],
    "Communication Equipment":              ["ai_infra", "chip_independence"],
    # Healthcare GLP-1 / biotech (broad - most biotech is too varied)
    "Drug Manufacturers - General":         ["glp1_obesity"],
    # Auto / EV
    "Auto Manufacturers":                   ["auto_ev"],
    "Auto Parts":                           ["auto_ev"],
    # Precious metals
    "Gold":                                 ["dedollarization"],
    "Silver":                               ["dedollarization"],
}


def get_narratives(ticker: str, sector: str = "", industry: str = "") -> list[str]:
    """Combined narrative lookup: explicit ticker overrides + sector defaults.
    Order: TICKER_NARRATIVES (precise) UNION SECTOR_NARRATIVES (broad)."""
    explicit = TICKER_NARRATIVES.get(ticker.upper(), [])
    sector_match = SECTOR_NARRATIVES.get(industry, []) or SECTOR_NARRATIVES.get(sector, [])
    # Union, preserve order, dedupe
    seen, out = set(), []
    for n in explicit + sector_match:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


TICKER_NARRATIVES: dict[str, list[str]] = {
    # Energy / Iran
    "EPD":  ["iran_hormuz"],
    "GLD":  ["iran_hormuz", "dedollarization"],
    "SLV":  ["dedollarization"],
    # Defense
    "RTX":  ["iran_hormuz", "defense"],
    "NOC":  ["iran_hormuz", "defense"],
    "HII":  ["iran_hormuz", "defense"],
    "LMT":  ["defense"],
    "GD":   ["defense"],
    "LDOS": ["defense", "defense_it"],
    "BBAI": ["defense", "defense_it"],
    # Rare earth
    "MP":   ["rare_earth", "china_decoupling"],
    # AI infrastructure
    "NVDA": ["ai_infra", "chip_independence"],
    "AMD":  ["ai_infra", "chip_independence"],
    "ASML": ["ai_infra", "chip_independence"],
    "TSM":  ["ai_infra", "chip_independence"],
    "CRM":  ["ai_infra"],
    "MSFT": ["ai_infra"],
    "GOOGL":["ai_infra"],
    "META": ["ai_infra"],
    "AMZN": ["ai_infra"],
    "AAPL": ["ai_infra", "china_decoupling"],
    # Nuclear / energy grid
    "CCJ":  ["nuclear_energy"],
    "NEE":  ["nuclear_energy", "energy_grid"],
    "DUK":  ["energy_grid"],
    # Healthcare / GLP-1
    "NVO":  ["glp1_obesity"],
    "LLY":  ["glp1_obesity"],
    "VRTX": ["glp1_obesity"],
    # Consumer
    "NKE":  [],
    "BJ":   [],
    "MDT":  [],
    "NFLX": [],
    # ── Expanded 2026-05-09 - high-priority hand-curated overrides ──────────
    # Auto / EV - sector default catches most via Auto Manufacturers, these add
    # ai_infra overlay for autonomy/FSD ticker-specifics
    "TSLA": ["auto_ev", "ai_infra"],
    "RIVN": ["auto_ev"],
    "LCID": ["auto_ev"],
    # Defense + defense_it (sector default catches base "defense", overlay adds it)
    "PLTR": ["defense_it", "ai_infra"],
    "KTOS": ["defense", "defense_it"],
    "AXON": ["defense_it"],
    "SAIC": ["defense", "defense_it"],
    "CACI": ["defense", "defense_it"],
    "BAH":  ["defense", "defense_it"],
    "DRS":  ["defense"],
    "RCAT": ["defense"],
    # Aerospace consumer - sector default "Aerospace & Defense" catches some;
    # these are eVTOL/orbital not classic defense, manual is clearer
    "JOBY": ["auto_ev"],   # eVTOL - analog to auto_ev
    "ACHR": ["auto_ev"],
    "ASTS": ["defense", "ai_infra"],   # space-as-defense
    "RKLB": ["defense"],
    "RDW":  ["defense"],
    "BWXT": ["nuclear_energy", "defense"],
    "SPCE": ["auto_ev"],
    # Quantum
    "IONQ": ["quantum", "ai_infra"],
    "RGTI": ["quantum"],
    "QBTS": ["quantum"],
    "QUBT": ["quantum"],
    # AI infra - additional semis + cloud-adjacent
    "AVGO": ["ai_infra", "chip_independence"],
    "MRVL": ["ai_infra", "chip_independence"],
    "INTC": ["ai_infra", "chip_independence"],
    "MU":   ["ai_infra", "chip_independence"],
    "AMAT": ["ai_infra", "chip_independence"],
    "KLAC": ["ai_infra", "chip_independence"],
    "LRCX": ["ai_infra", "chip_independence"],
    "ARM":  ["ai_infra", "chip_independence"],
    "SMCI": ["ai_infra"],
    "ANET": ["ai_infra"],   # data center networking
    "VRT":  ["ai_infra", "energy_grid"],   # cooling/power for AI DC
    "ALAB": ["ai_infra", "chip_independence"],
    "CRWV": ["ai_infra"],
    "NBIS": ["ai_infra"],
    # Software - sector default catches most; these add specifics
    "NOW":  ["ai_infra"],
    "ORCL": ["ai_infra"],
    "ADBE": ["ai_infra"],
    "SNOW": ["ai_infra"],
    "DDOG": ["ai_infra"],
    "NET":  ["ai_infra"],
    "CRWD": ["defense_it", "ai_infra"],   # cybersecurity-as-defense
    "S":    ["defense_it", "ai_infra"],
    "PANW": ["defense_it", "ai_infra"],
    "ZS":   ["ai_infra"],
    "OKTA": ["ai_infra"],
    # Energy - sector default catches midstream; these are explicit anchors
    "ET":   ["iran_hormuz"],
    "KMI":  ["iran_hormuz"],
    "ENB":  ["iran_hormuz"],
    "WMB":  ["iran_hormuz"],
    "OKE":  ["iran_hormuz"],
    "XOM":  ["iran_hormuz"],
    "CVX":  ["iran_hormuz"],
    "COP":  ["iran_hormuz"],
    "OXY":  ["iran_hormuz"],
    # Rare earth / critical minerals
    "REMX": ["rare_earth", "china_decoupling"],
    "LAC":  ["china_decoupling"],     # lithium
    "ABAT": ["china_decoupling", "auto_ev"],
    "UEC":  ["nuclear_energy"],
    "URA":  ["nuclear_energy"],
    "NUCL": ["nuclear_energy"],
    "LIT":  ["china_decoupling", "auto_ev"],
    # Healthcare device / diagnostics - explicit (sector default doesn't catch)
    "ABT":  [],
    "DHR":  [],
    "SYK":  [],
    "ISRG": ["ai_infra"],   # surgical robotics → AI overlay
    "BSX":  [],
    "EW":   [],
    "DXCM": ["glp1_obesity"],   # CGM benefits from GLP-1 wave
    # Biotech / pharma
    "REGN": [],
    "AMGN": [],
    "MRK":  [],
    "PFE":  [],
    "BIIB": [],
    "GILD": [],
    "MRNA": [],
    "BNTX": [],
    # ETFs - high-conviction theme tracking
    "ITA":  ["defense"],
    "DFEN": ["defense"],
    "XLE":  ["iran_hormuz"],
    "ARKQ": ["auto_ev", "ai_infra"],
    "BOTZ": ["ai_infra"],   # robotics
    "SMH":  ["ai_infra", "chip_independence"],
    "SOXX": ["ai_infra", "chip_independence"],
    "ARKG": [],
    "QQQ":  ["ai_infra"],
    "QQQM": ["ai_infra"],
    "IGV":  ["ai_infra"],
}


@dataclass
class ScoreResult:
    ticker: str
    total: int
    breakdown: dict[str, int] = field(default_factory=dict)
    disqualified: bool = False
    disqualify_reason: str = ""
    signal: str = ""          # "strong" / "candidate" / "weak" / "disqualified"
    pattern_bonus: int = 0
    pattern_note: str = ""
    regime: str = ""          # "strong_uptrend" / "downtrend" / "ranging" / ""
    regime_note: str = ""

    def __str__(self):
        if self.disqualified:
            return f"{self.ticker} DISQUALIFIED: {self.disqualify_reason}"
        bar = "█" * (self.total // 5) + "░" * (20 - self.total // 5)
        return (
            f"{self.ticker} [{self.signal.upper()}] {self.total}/180\n"
            f"  {bar}\n"
            + "\n".join(f"  {k}: +{v}" for k, v in self.breakdown.items() if v > 0)
        )


def score_ticker(snapshot: dict, target_price: Optional[float] = None,
                 pattern_result: Optional[dict] = None,
                 scan_mode: bool = False,
                 insider_buy: bool = False) -> ScoreResult:
    """
    scan_mode=True: FCF and D/E become penalties instead of hard disqualifiers.
    Used by scan_universe.py to surface turnarounds / capex-heavy stocks.
    Earnings window disqualifier always applies regardless of mode.
    """
    """
    Score a ticker using the 180-point algorithm.

    Args:
        snapshot: dict from get_full_snapshot() in morning_run.py
        target_price: analyst/user target price for upside calculation
        pattern_result: dict from patterns.detect() - optional

    Returns:
        ScoreResult
    """
    t = snapshot.get("ticker", "???")
    result = ScoreResult(ticker=t, total=0)

    # ── Trend-regime overlay (FAILURE MODE 3 mitigation) ────────────────────
    # When stock is in strong uptrend (ADX>30 + price>50MA>200MA), oversold
    # rules ("RSI<30 = buy") DON'T APPLY - momentum stocks ignore RSI for months.
    # Example: AMD up 75% in April with RSI 65+ all month. Don't buy that dip.
    price_x = snapshot.get("price") or 0
    ma50_x  = snapshot.get("ma50") or 0
    ma200_x = snapshot.get("ma200") or 0
    adx_x   = snapshot.get("adx") or 0
    rsi_x   = snapshot.get("rsi") or 50
    if adx_x > 30 and price_x > ma50_x > ma200_x:
        if rsi_x > 60:
            # Strong uptrend regime - RSI overbought signals are NOISE, not exits.
            # Wait for MA50 retest before entering on "dip".
            result.regime = "strong_uptrend"
            result.regime_note = "Strong uptrend (ADX>30, P>50MA>200MA). Oversold rules suppressed. Wait for MA50 retest."
    elif adx_x > 30 and price_x < ma50_x < ma200_x:
        result.regime = "strong_downtrend"
        result.regime_note = "Strong downtrend. RSI<30 may catch falling knife. Wait for MACD turn AND BB% rise BEFORE entry."

    # ── Auto-disqualifiers ──────────────────────────────────────────────────
    from user_config import rule as _rule
    earnings_blackout = _rule("earnings_blackout_days")
    days_to_earn = snapshot.get("days_to_earnings")
    if days_to_earn is not None and 0 <= days_to_earn <= earnings_blackout:
        result.disqualified = True
        result.disqualify_reason = f"Earnings in {days_to_earn} days (<{earnings_blackout} day window)"
        result.signal = "disqualified"
        return result

    de = snapshot.get("debt_to_equity") or 0
    if de and de > 200:
        if scan_mode:
            # Penalty instead of hard kill - surface turnarounds with high leverage
            result.breakdown["D/E penalty"] = -10
        else:
            result.disqualified = True
            result.disqualify_reason = f"Debt/equity {de:.0f} > 200"
            result.signal = "disqualified"
            return result

    fcf = snapshot.get("free_cash_flow")
    if fcf is not None and fcf < 0:
        if scan_mode:
            # Penalty instead of hard kill - semis / capex-heavy in investment cycle
            result.breakdown["FCF penalty"] = -15
        else:
            result.disqualified = True
            result.disqualify_reason = f"Negative free cash flow (${fcf:,.0f})"
            result.signal = "disqualified"
            return result

    # ── RSI (max 25 pts) ────────────────────────────────────────────────────
    rsi = snapshot.get("rsi") or 50
    if rsi < 30:
        pts = 25
    elif rsi < 40:
        pts = 15
    elif rsi < 50:
        pts = 5
    else:
        pts = 0
    result.breakdown["RSI"] = pts

    # ── MACD (max 20 pts) ──────────────────────────────────────────────────
    if snapshot.get("macd_crossover"):
        pts = 20
    elif snapshot.get("macd_improving"):
        pts = 10
    else:
        pts = 0
    result.breakdown["MACD"] = pts

    # ── Bollinger Band % (max 20 pts) ──────────────────────────────────────
    bb = snapshot.get("bb_pct") or 50
    if bb < 20:
        pts = 20
    elif bb < 40:
        pts = 10
    else:
        pts = 0
    result.breakdown["BB%"] = pts

    # ── Upside to target (max 20 pts) ──────────────────────────────────────
    price = snapshot.get("price") or 0
    if target_price and price > 0:
        upside_pct = ((target_price - price) / price) * 100
        if upside_pct > 20:
            pts = 20
        elif upside_pct > 10:
            pts = 10
        elif upside_pct > 5:
            pts = 5
        else:
            pts = 0
        result.breakdown["Upside"] = pts
    else:
        result.breakdown["Upside"] = 0

    # ── Dividend yield (max 10 pts) ─────────────────────────────────────────
    div = snapshot.get("div_yield") or 0
    if div > 4:
        pts = 10
    elif div > 2:
        pts = 5
    else:
        pts = 0
    result.breakdown["Div yield"] = pts

    # ── Near 52W low (max 5 pts) ───────────────────────────────────────────
    pct_from_low = snapshot.get("pct_from_52w_low") or 100
    pts = 5 if pct_from_low < 10 else 0
    result.breakdown["52W low"] = pts

    # ── Volume confirmation (max 10 pts) ───────────────────────────────────
    vol = snapshot.get("vol_ratio") or 1
    pct_chg = snapshot.get("pct_chg_today") or 0
    if pct_chg < 0:  # volume matters on down days
        if vol > 1.5:
            pts = 10
        elif vol >= 1.0:
            pts = 5
        else:
            pts = 0
    else:
        pts = 0
    result.breakdown["Volume"] = pts

    # ── Relative strength vs S&P (max 10 pts) ─────────────────────────────
    rel = snapshot.get("rel_strength_vs_sp") or 0
    if rel > 5:
        pts = 10
    elif rel >= 0:
        pts = 5
    else:
        pts = 0
    result.breakdown["Rel strength"] = pts

    # ── Analyst rating (max 5 pts) ─────────────────────────────────────────
    rating_str = snapshot.get("analyst_rating") or ""
    try:
        rating = float(str(rating_str).split(" ")[0])
        if rating <= 2.0:
            pts = 5
        elif rating <= 2.5:
            pts = 3
        else:
            pts = 0
    except (ValueError, IndexError):
        pts = 0
    result.breakdown["Analyst"] = pts

    # ── Short interest (max 5 pts) ─────────────────────────────────────────
    short_pct = snapshot.get("short_pct_float") or 0
    pts = 5 if short_pct > 10 else 0
    result.breakdown["Short squeeze"] = pts

    # ── Chart pattern bonus (max 10 pts) ──────────────────────────────────
    if pattern_result:
        signal = pattern_result.get("signal", "")
        pattern_name = pattern_result.get("pattern", "")
        confidence = pattern_result.get("confidence", 0)
        if confidence >= 0.65:
            reversal = {"double_bottom", "inverse_head_shoulders", "cup_and_handle"}
            continuation = {"ascending_triangle", "flag", "pennant"}
            if signal == "bullish" and pattern_name in reversal:
                pts = 10
            elif signal == "bullish" and pattern_name in continuation:
                pts = 5
            else:
                pts = 0
            result.breakdown["Pattern"] = pts
            result.pattern_bonus = pts
            result.pattern_note = f"{pattern_name} ({confidence:.0%} confidence)"

    # ── Below 200MA (max 10 pts) ───────────────────────────────────────────
    # Stocks below 200MA have more mean-reversion room when they turn.
    # Classic: buy when price crosses back above 200MA = institutional buy signal.
    price  = snapshot.get("price") or 0
    ma200  = snapshot.get("ma200") or 0
    if price > 0 and ma200 > 0 and price < ma200:
        pts = 10
    else:
        pts = 0
    result.breakdown["Below 200MA"] = pts

    # ── FCF yield >5% (max 10 pts) ─────────────────────────────────────────
    # FCF yield = free cash flow / market cap. >5% = cheap + generating real cash.
    # Filters out value traps that look cheap on P/E but burn cash.
    fcf        = snapshot.get("free_cash_flow") or 0
    mkt_cap    = snapshot.get("market_cap") or 0
    if fcf > 0 and mkt_cap > 0:
        fcf_yield = (fcf / mkt_cap) * 100
        if fcf_yield >= 8:
            pts = 10
        elif fcf_yield >= 5:
            pts = 7
        elif fcf_yield >= 3:
            pts = 3
        else:
            pts = 0
    else:
        pts = 0
    result.breakdown["FCF yield"] = pts

    # ── Macro narrative alignment (max 10 pts) ─────────────────────────────
    # Structural tailwind already in place = thesis doesn't need to be invented.
    # Stock aligned with active war / AI wave / policy shift = higher conviction.
    # Lookup combines explicit ticker map with sector-default narratives.
    ticker_upper = (snapshot.get("ticker") or "").upper()
    sector       = snapshot.get("sector") or ""
    industry     = snapshot.get("industry") or ""
    narratives   = get_narratives(ticker_upper, sector=sector, industry=industry)
    from user_config import active_narratives as _active_narratives
    _user_narratives = _active_narratives(ACTIVE_NARRATIVES)
    active_count = sum(1 for n in narratives if n in _user_narratives)
    if active_count >= 2:
        pts = 10
    elif active_count == 1:
        pts = 7
    else:
        pts = 0
    result.breakdown["Macro narrative"] = pts
    if narratives:
        result.regime_note = (result.regime_note + " | " if result.regime_note else "") + \
            "Narratives: " + ", ".join(n for n in narratives if n in _user_narratives)

    # ── Insider buying (max 10 pts) ────────────────────────────────────────
    # Management buying own shares = highest conviction signal per academic research.
    # They know the business better than anyone. Cluster buys (3+ insiders) = strongest.
    # Pass insider_buy=True when Finnhub/openinsider shows recent cluster buy.
    if insider_buy:
        pts = 10
    else:
        pts = 0
    result.breakdown["Insider buying"] = pts

    result.total = sum(result.breakdown.values())

    # ── Falling-knife guard ────────────────────────────────────────────────
    # Backtest finding (730d × 96 tickers, 1207 entries): tech-only signals
    # fire on falling knives (NVO/CRM/NKE/DHR pattern). Median alpha was
    # negative across tech tiers because oversold-without-thesis = trap.
    #
    # Hypothesis test (analyze_blocked.py, 197 blocked entries):
    #   blocked median α: -1.17% (CI [-3.69%, +0.36%], straddles 0)
    #   confirmed coverage gap - 6 of top 15 blocked tickers were winners
    #   (MRVL +16%, KSCP +12%, AKAM +3%) outside the narrative dict.
    #
    # Soft penalty (-10pts) instead of hard cap - keeps guard's teeth on
    # falling knives without nuking real setups in tickers we haven't curated
    # macro narratives for yet. A 70pt tech-only score becomes 60 (weak), an
    # 80pt becomes 70 (still candidate, but flagged as suspect thesis).
    TECH_FACTORS = ("RSI", "MACD", "BB%", "Volume", "Rel strength",
                    "Below 200MA", "52W low", "Pattern")
    FUND_FACTORS = ("Upside", "Div yield", "FCF yield", "Macro narrative",
                    "Analyst", "Short squeeze", "Insider buying")
    tech_pts = sum(result.breakdown.get(f, 0) for f in TECH_FACTORS)
    fund_pts = sum(result.breakdown.get(f, 0) for f in FUND_FACTORS)
    if tech_pts >= 50 and fund_pts == 0:
        result.breakdown["Falling-knife guard"] = -10
        result.total -= 10
        guard_note = (f"⚠ FALLING-KNIFE GUARD: tech={tech_pts}pts but 0 "
                      f"fundamental confirmation → -10pt penalty")
        result.regime_note = (result.regime_note + " | " if result.regime_note
                              else "") + guard_note

    # Thresholds (user-configurable; defaults ≥70/≥110/≥140 out of 180)
    if result.total >= _rule("score_conviction_threshold"):
        result.signal = "high_conviction"
    elif result.total >= _rule("score_strong_threshold"):
        result.signal = "strong"
    elif result.total >= _rule("score_entry_threshold"):
        result.signal = "candidate"
    else:
        result.signal = "weak"

    return result


def explain_score(result: ScoreResult) -> str:
    lines = [f"\n{'═'*50}", f"  ENTRY SCORE: {result.ticker}", f"{'═'*50}"]
    if result.disqualified:
        lines.append(f"  ❌ DISQUALIFIED: {result.disqualify_reason}")
        return "\n".join(lines)

    signal_icons = {
        "high_conviction": "🔥",
        "strong": "✅",
        "candidate": "👀",
        "weak": "⚠️",
    }
    icon = signal_icons.get(result.signal, "")
    lines.append(f"  {icon} {result.signal.upper().replace('_', ' ')}: {result.total}/180 pts")
    lines.append("")
    for factor, pts in result.breakdown.items():
        if pts > 0:
            lines.append(f"  +{pts:>3}  {factor}")
    if result.pattern_note:
        lines.append(f"        Pattern: {result.pattern_note}")
    lines.append(f"{'─'*50}")
    thresholds = "≥70=candidate  ≥110=strong  ≥140=high conviction  (180pt max)"
    lines.append(f"  {thresholds}")
    return "\n".join(lines)


def size_position(snapshot: dict, vix: float = 15) -> int:
    """Return recommended position size in dollars."""
    beta = snapshot.get("beta") or 1.0
    if beta <= 1.3:
        size = 1000
    elif beta <= 1.6:
        size = 750
    else:
        size = 500

    if vix > 35:
        size = int(size * 0.5)
    elif vix > 25:
        size = int(size * 0.75)

    short_ratio = snapshot.get("short_pct_float") or 0
    if short_ratio > 5:
        size = int(size * 0.75)

    return size


if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Usage: python score.py TICKER [target_price] [--both] [--force-regular]")
        sys.exit(1)

    args = sys.argv[1:]
    flag_both = "--both" in args
    flag_force_regular = "--force-regular" in args
    args = [a for a in args if not a.startswith("--")]

    ticker = args[0].upper()
    target = float(args[1]) if len(args) > 1 else None

    # Auto-load insider signal from cache (written by morning_run.py or insider.py)
    insider_buy = False
    insider_note = ""
    cache_path = Path(__file__).resolve().parents[1] / "insider_cache.json"
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            sig = cache.get(ticker, {})
            if sig.get("has_signal"):
                insider_buy = True
                insider_note = f"  🔍 Insider: [{sig['signal']}] {sig['description']}"
        except Exception:
            pass

    # Import here to avoid circular deps when score.py used as module
    from morning_run import get_full_snapshot
    from spec_score import is_spec_candidate, score_spec

    snap = get_full_snapshot(ticker)
    snap["ticker"] = ticker

    use_spec = is_spec_candidate(snap) and not flag_force_regular

    # ── Dual-score mode (--both) ─────────────────────────────────────────────
    if flag_both:
        reg_result  = score_ticker(snap, target_price=target, insider_buy=insider_buy)
        spec_result = score_spec(snap, insider_buy=insider_buy)
        reg_str  = f"DISQUALIFIED - {reg_result.disqualify_reason}" if reg_result.disqualified else f"{reg_result.total}/180 [{reg_result.signal.upper()}]"
        spec_str = f"DISQUALIFIED - {spec_result.disqualify_reason}" if spec_result.disqualified else f"{spec_result.total}/150 [{spec_result.signal.upper()}]"
        print("╔══════════════════════════════════════════╗")
        print(f"║  {ticker} DUAL-SCORE ANALYSIS{' '*(42-len(ticker)-17)}║")
        print("╠══════════════════════════════════════════╣")
        print(f"║  Regular (180pt): {reg_str:<24} ║")
        print(f"║  Spec    (150pt): {spec_str:<24} ║")
        print("║                                          ║")
        verdict = "SPEC TRACK" if (use_spec and not spec_result.disqualified) else "REGULAR TRACK"
        print(f"║  VERDICT: {verdict:<32}║")
        print("╚══════════════════════════════════════════╝")
        if use_spec and not spec_result.disqualified:
            print("\n" + str(spec_result))
        else:
            print("\n" + explain_score(reg_result))
        sys.exit(0)

    # ── Single-score mode (auto-route) ───────────────────────────────────────
    if use_spec:
        spec_result = score_spec(snap, insider_buy=insider_buy)
        print(str(spec_result))
    else:
        result = score_ticker(snap, target_price=target, insider_buy=insider_buy)
        print(explain_score(result))
    if not use_spec:
        # Insider line only shown for regular score (spec score already includes it)
        if insider_note:
            print(insider_note)
        elif cache_path.exists():
            print(f"  🔍 Insider: [NONE] No open-market buys in last 90 days")
        else:
            print(f"  🔍 Insider: [NO CACHE] Run 'python insider.py {ticker}' to fetch")

    # Options flow - informational (market microstructure, not scored)
    options_cache_path = Path(__file__).resolve().parents[1] / "options_flow_cache.json"
    if options_cache_path.exists():
        try:
            ocache = json.loads(options_cache_path.read_text(encoding="utf-8"))
            oflow = ocache.get(ticker, {})
            if oflow:
                signal = oflow.get("signal", "-")
                pcr_v = oflow.get("pcr_vol")
                pcr_o = oflow.get("pcr_oi")
                atm_iv = oflow.get("atm_iv")
                strikes = oflow.get("key_strikes", [])[:3]
                pcr_str = f"P/C {pcr_v:.2f}vol/{pcr_o:.2f}oi" if pcr_v else ""
                iv_str  = f" | ATM IV {atm_iv:.0f}%" if atm_iv else ""
                icon = {"UNUSUAL_CALLS":"🚀","BULLISH_FLOW":"🟢","MILD_BULLISH":"🟡",
                        "NEUTRAL":"⚪","HEDGING":"🛡","BEARISH_FLOW":"🔴"}.get(signal,"-")
                print(f"  {icon} Options: [{signal}] {pcr_str}{iv_str}")
                if strikes and signal in ("UNUSUAL_CALLS","BULLISH_FLOW","BEARISH_FLOW"):
                    walls = "  ".join(f"${s['strike']:.0f}({s['dist_pct']:+.0f}%)" for s in strikes)
                    print(f"     Gamma walls: {walls}")
                mp = oflow.get("max_pain")
                mp_dist = oflow.get("max_pain_dist_pct")
                mp_days = oflow.get("max_pain_days")
                mp_sig  = oflow.get("max_pain_signal", "")
                if mp:
                    day_str = f"{mp_days}d to exp" if mp_days else ""
                    print(f"     Max pain: ${mp:.0f} ({mp_dist:+.1f}%, {day_str}) → {mp_sig}")
            else:
                print(f"  ⚪ Options: [NO CACHE] Run 'python options_flow.py {ticker}' to fetch")
        except Exception:
            pass
    else:
        print(f"  ⚪ Options: [NO CACHE] Run 'python options_flow.py {ticker}' to fetch")

    size = size_position(snap)
    print(f"\n  Recommended position size: ${size:,}")
