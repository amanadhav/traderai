"""
spec_score.py - 150-point scorer for startup / pre-FCF / penny stocks.

Why a separate scorer:
  Regular score.py auto-disqualifies on negative FCF - kills every pre-profit name
  (RKLB, RKT, BBAI, hyperscaler-stage SaaS). Spec stocks need different DNA:
  runway, dilution, customer concentration, catalysts.

Scoring factors (150 pts max):
  Revenue growth YoY (25) · Cash runway (20) · Gross margin trend (15)
  Share dilution (15) · Customer concentration (10) · Short squeeze (10)
  Insider buying (15) · Catalyst proximity (10) · Volume regime (10)
  Sector tailwind (10) · Pattern bonus (10)

Thresholds: ≥60=candidate · ≥90=strong · ≥110=high conviction
(Lower than regular score.py - spec scoring is inherently noisier.)

Disqualifiers (score = 0, hard kill, no overrides):
  - Cash runway < 2 quarters
  - Stock price < $1 (delisting risk)
  - Share dilution > 50% in last 12 months
  - Zero revenue (shell company)
  - Earnings within 15 days

Auto-classifier:
  is_spec_candidate(snap) → True if mkt cap <$5B AND
                            (negative FCF OR rev growth >50% OR price <$10)

Usage:
  from spec_score import score_spec, is_spec_candidate
  if is_spec_candidate(snap):
      result = score_spec(snap, insider_buy=True, next_catalyst={...})
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

# Reuse narratives from score.py for sector tailwind matching
from score import ACTIVE_NARRATIVES, TICKER_NARRATIVES


# ── Spec universe classifier ──────────────────────────────────────────────────

SPEC_MARKET_CAP_CEILING        = 5_000_000_000    # $5B classic spec
SPEC_GROWTH_CARVE_OUT_CEILING  = 50_000_000_000   # $50B pre-profit growth
SPEC_REV_GROWTH_THRESHOLD      = 0.50             # 50% YoY (classic hyperscale)
SPEC_CARVE_OUT_REV_GROWTH      = 0.25             # 25% YoY (carve-out floor)
SPEC_CARVE_OUT_RUNWAY_Q        = 8                # 8 quarters cash required
SPEC_PRICE_PENNY               = 10.00            # $10


def is_spec_candidate(snapshot: dict) -> bool:
    """
    Auto-classify ticker for spec scoring track.

    Two routes into spec scoring:

    A) Classic spec (mkt cap <$5B): Returns True if any of:
         - free_cash_flow < 0 (pre-profit)
         - revenue_growth > 50% YoY (hyperscale stage)
         - price < $10 (penny territory)

    B) Growth carve-out ($5B-$50B mkt cap): Returns True only if ALL of:
         - free_cash_flow < 0 (pre-profit)
         - revenue_growth >= 25% YoY (real growth, not melting ice cube)
         - cash runway >= 8 quarters (not about to dilute or collapse)

       This catches pre-profit infrastructure plays (RKLB, ASTS, JOBY-likes)
       that fall into the gap: too big for classic spec, too unprofitable
       for regular score.py (which hard-DQs on neg FCF).

    Large caps (>$50B) always use regular score.py. Established small/mid
    caps with positive FCF and slow growth also use regular scorer.
    """
    mkt_cap = snapshot.get("market_cap") or 0
    if mkt_cap == 0:
        # Unknown market cap - be conservative, don't auto-classify
        return False

    fcf      = snapshot.get("free_cash_flow")
    rev_grow = snapshot.get("revenue_growth") or 0
    price    = snapshot.get("price") or 0

    # ── Route A: classic spec (small caps) ──────────────────────────────
    if mkt_cap < SPEC_MARKET_CAP_CEILING:
        if fcf is not None and fcf < 0:
            return True
        if rev_grow > SPEC_REV_GROWTH_THRESHOLD:
            return True
        if 0 < price < SPEC_PRICE_PENNY:
            return True
        return False

    # ── Route B: growth carve-out ($5B-$50B pre-profit infrastructure) ──
    if mkt_cap < SPEC_GROWTH_CARVE_OUT_CEILING:
        if fcf is None or fcf >= 0:
            return False  # carve-out requires neg FCF (pre-profit)
        if rev_grow < SPEC_CARVE_OUT_REV_GROWTH:
            return False  # not enough growth to be "pre-profit-by-choice"
        # Check cash runway
        _, runway_q = _score_runway(snapshot.get("total_cash"),
                                    snapshot.get("operating_cashflow"))
        if runway_q < SPEC_CARVE_OUT_RUNWAY_Q:
            return False  # too short - likely melting ice cube
        return True

    # mkt cap >= $50B: always regular scorer
    return False


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class SpecScoreResult:
    ticker: str
    total: int = 0
    breakdown: dict = field(default_factory=dict)
    disqualified: bool = False
    disqualify_reason: str = ""
    signal: str = ""    # "candidate" / "strong" / "high_conviction" / "weak" / "disqualified"
    pattern_note: str = ""
    runway_quarters: float = 0.0
    customer_data_available: bool = False
    catalyst_note: str = ""

    def __str__(self):
        if self.disqualified:
            return f"{self.ticker} SPEC DISQUALIFIED: {self.disqualify_reason}"
        bar = "█" * (self.total // 5) + "░" * (30 - self.total // 5)
        bar = bar[:30]  # cap at 30 chars
        lines = [
            f"{self.ticker} [SPEC {self.signal.upper()}] {self.total}/150",
            f"  {bar}",
        ]
        for k, v in self.breakdown.items():
            if v > 0:
                lines.append(f"  {k}: +{v}")
            elif v < 0:
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _score_revenue_growth(rev_growth: float | None) -> int:
    """YoY revenue growth → 0-25pts."""
    if rev_growth is None:
        return 0
    if rev_growth >= 1.00:   # 100%+ → hyperscale
        return 25
    if rev_growth >= 0.50:   # 50-100%
        return 20
    if rev_growth >= 0.25:   # 25-50%
        return 15
    if rev_growth >= 0.10:   # 10-25%
        return 8
    return 0  # ≤10% YoY = no growth bonus for spec


def _score_runway(total_cash: float | None, op_cashflow: float | None) -> tuple[int, float]:
    """
    Cash runway in quarters → 0-20pts.
    Returns (points, runway_quarters) for disqualifier logic.

    Runway = total_cash / abs(quarterly_burn)
    where quarterly_burn = abs(annual operating cashflow) / 4
    """
    if total_cash is None or op_cashflow is None:
        return 0, 0.0
    if op_cashflow >= 0:
        return 20, 999.0  # positive op cashflow = infinite runway
    quarterly_burn = abs(op_cashflow) / 4
    if quarterly_burn == 0:
        return 20, 999.0
    runway = total_cash / quarterly_burn
    if runway >= 12:
        return 20, runway
    if runway >= 8:
        return 15, runway
    if runway >= 4:
        return 8, runway
    return 0, runway


def _score_gross_margin_trend(margin_trend: list[float] | None) -> int:
    """
    Gross margin trend over last 4 quarters → 0-15pts.
    margin_trend = [oldest_q, ..., newest_q]
    """
    if not margin_trend or len(margin_trend) < 3:
        return 0
    # Strip None values
    clean = [m for m in margin_trend if m is not None]
    if len(clean) < 3:
        return 0
    # Improving = each quarter higher than the one before (allow 1 dip)
    improvements = sum(1 for i in range(1, len(clean)) if clean[i] > clean[i-1])
    declines    = sum(1 for i in range(1, len(clean)) if clean[i] < clean[i-1])
    if improvements >= len(clean) - 2:  # mostly improving
        return 15
    if abs(improvements - declines) <= 1:  # flat
        return 8
    return 0  # declining


def _score_dilution(dilution_pct: float | None) -> int:
    """
    Share dilution YoY → 0-15pts.
    dilution_pct = (shares_now - shares_year_ago) / shares_year_ago × 100
    """
    if dilution_pct is None:
        return 0
    if dilution_pct < 5:
        return 15
    if dilution_pct < 15:
        return 10
    if dilution_pct < 25:
        return 5
    return 0


def _score_customer_concentration(customer_data: dict | None) -> tuple[int, str]:
    """
    Customer concentration → 0-10pts.
    Returns (points, note). Note empty if no data.

    Bonus for:
      - Top customer is DoD/government ≥30%: +10 (revenue stability)
      - Top customer is hyperscaler (Microsoft/Google/AWS) ≥30%: +10
      - Diversified (no customer >20%): +5
      - High concentration without strategic importance: 0
    """
    if not customer_data or not customer_data.get("has_data"):
        return 0, ""

    top_customer = (customer_data.get("top_customer") or "").lower()
    pct          = customer_data.get("pct") or 0

    strategic_keywords = [
        "department of defense", "dod", "u.s. government", "u.s. air force",
        "u.s. navy", "u.s. army", "nasa", "space force", "general services",
        "microsoft", "google", "amazon web services", "aws", "alphabet",
        "apple", "meta", "oracle",
    ]

    if pct >= 30:
        if any(k in top_customer for k in strategic_keywords):
            return 10, f"Strategic anchor: {customer_data.get('top_customer','?')} {pct}%"
        # High concentration without strategic name = neutral, no bonus
        return 0, f"Concentrated: {customer_data.get('top_customer','?')} {pct}% - risk"

    # Diversified: no customer >20%
    all_customers = customer_data.get("all_customers", [])
    max_pct = max([c.get("pct", 0) for c in all_customers], default=pct)
    if max_pct < 20:
        return 5, "Diversified customer base (no >20%)"

    return 0, ""


def _score_short_squeeze(short_pct: float | None, news_signal: str = "NEUTRAL") -> int:
    """
    Short interest squeeze potential → 0-10pts.
    >25% AND positive catalyst news = max squeeze setup.
    """
    if short_pct is None:
        return 0
    if short_pct >= 25 and news_signal == "POSITIVE":
        return 10
    if short_pct >= 25:
        return 7  # squeeze fuel without catalyst yet
    if short_pct >= 15:
        return 5
    return 0


def _score_insider(ins_signal: str) -> int:
    """Reuse insider tier values, cap at 15pts to match regular score.py."""
    return {
        "STRONG":  15,
        "CLUSTER": 12,
        "NOTABLE": 8,
        "WEAK":    3,
        "NONE":    0,
    }.get(ins_signal, 0)


def _score_catalyst(next_catalyst: dict | None,
                    days_to_earnings: int | None) -> tuple[int, str]:
    """
    Catalyst proximity → 0-10pts.
    Picks the soonest catalyst from: earnings, ex-dividend, manual next_catalyst.
    """
    candidates = []
    if next_catalyst and next_catalyst.get("date"):
        try:
            dt = datetime.strptime(next_catalyst["date"][:10], "%Y-%m-%d")
            days = (dt - datetime.now()).days
            if days >= 0:
                candidates.append((days, next_catalyst.get("type", "catalyst"),
                                   next_catalyst.get("note", "")))
        except (ValueError, TypeError):
            pass

    # Earnings counts as catalyst even though it's also a disqualifier <15d
    # Disqualifier handled separately - here it just adds points if 30-90d out
    if days_to_earnings is not None and 16 <= days_to_earnings <= 90:
        candidates.append((days_to_earnings, "earnings", ""))

    if not candidates:
        return 0, ""

    days, ctype, note = min(candidates, key=lambda x: x[0])
    if days < 30:
        return 10, f"{ctype.upper()} in {days}d{(' - '+note) if note else ''}"
    if days < 60:
        return 7, f"{ctype.upper()} in {days}d{(' - '+note) if note else ''}"
    if days < 90:
        return 4, f"{ctype.upper()} in {days}d"
    return 0, ""


def _score_volume(avg_volume: float | None, price: float | None) -> int:
    """
    Daily dollar volume → 0-10pts.
    Liquidity matters for spec - illiquid penny stocks = trap.
    """
    if avg_volume is None or price is None:
        return 0
    daily_dollar = avg_volume * price
    if daily_dollar >= 50_000_000:
        return 10
    if daily_dollar >= 10_000_000:
        return 5
    if daily_dollar < 1_000_000:
        return -5  # liquidity penalty: hard to enter/exit
    return 0


def _score_sector_tailwind(ticker: str, industry: str | None) -> int:
    """
    Sector / industry alignment with active narratives → 0-10pts.
    """
    industry_lower = (industry or "").lower()
    narratives = TICKER_NARRATIVES.get(ticker.upper(), [])
    active_narratives = [n for n in narratives if n in ACTIVE_NARRATIVES]

    if active_narratives:
        return 10  # explicit narrative match

    # Fallback: industry keyword match for spec tickers not in TICKER_NARRATIVES
    industry_narrative_map = {
        "aerospace & defense":        ["defense", "iran_hormuz"],
        "defense":                    ["defense"],
        "semiconductors":             ["ai_infra", "chip_independence"],
        "information technology":     ["ai_infra", "defense_it"],
        "biotechnology":              ["glp1_obesity"],
        "drug manufacturers":         ["glp1_obesity"],
        "uranium":                    ["nuclear_energy"],
        "utilities-renewable":        ["energy_grid"],
        "oil & gas midstream":        ["iran_hormuz"],
    }
    for key, narrs in industry_narrative_map.items():
        if key in industry_lower:
            if any(n in ACTIVE_NARRATIVES for n in narrs):
                return 5  # adjacent match (industry-level, not explicit)
    return 0


def _score_pattern(pattern_result: dict | None) -> tuple[int, str]:
    """Pattern bonus 0-10pts. Bullish reversal = full bonus."""
    if not pattern_result:
        return 0, ""
    sig  = pattern_result.get("signal", "")
    conf = pattern_result.get("confidence", 0)
    pat  = pattern_result.get("pattern", "")
    if conf < 0.65:
        return 0, ""
    if sig == "bullish":
        bonus = 10 if "reversal" in pat or pat in ("double_bottom", "inverse_head_shoulders", "cup_handle") else 5
        return bonus, f"{pat} ({int(conf*100)}% conf)"
    if sig == "bearish":
        # Bearish doesn't disqualify spec but flag it
        return 0, f"BEARISH PATTERN {pat} ({int(conf*100)}% conf) - caution"
    return 0, ""


# ── Main scoring function ─────────────────────────────────────────────────────

def score_spec(snapshot: dict,
               insider_buy: bool = False,
               insider_signal: str = "NONE",
               pattern_result: Optional[dict] = None,
               next_catalyst: Optional[dict] = None,
               customer_data: Optional[dict] = None,
               news_signal: str = "NEUTRAL") -> SpecScoreResult:
    """
    Score a spec ticker.

    Args:
        snapshot: dict with at minimum 'ticker', 'price', 'market_cap'
        insider_buy: bool - convenience flag (overrides if True with no signal)
        insider_signal: str - 'STRONG'/'CLUSTER'/'NOTABLE'/'WEAK'/'NONE'
        pattern_result: dict from patterns.py
        next_catalyst: dict from positions.json {date, type, note}
        customer_data: dict from customer_concentration.py
        news_signal: str - for short squeeze bonus

    Returns SpecScoreResult.
    """
    ticker = (snapshot.get("ticker") or "???").upper()
    result = SpecScoreResult(ticker=ticker)

    # ── Disqualifiers (hard kill, run BEFORE scoring) ────────────────────────

    # Earnings within 15 days - same rule as score.py
    days_to_earn = snapshot.get("days_to_earnings")
    if days_to_earn is not None and 0 <= days_to_earn <= 15:
        result.disqualified = True
        result.disqualify_reason = f"Earnings in {days_to_earn} days (<15 day window)"
        result.signal = "disqualified"
        return result

    # Stock price < $1 (NYSE/NASDAQ delisting territory)
    price = snapshot.get("price") or 0
    if 0 < price < 1.0:
        result.disqualified = True
        result.disqualify_reason = f"Price ${price:.2f} < $1.00 - delisting risk"
        result.signal = "disqualified"
        return result

    # Zero revenue (shell company)
    total_revenue = snapshot.get("total_revenue")
    if total_revenue is not None and total_revenue == 0:
        result.disqualified = True
        result.disqualify_reason = "Zero revenue - shell company"
        result.signal = "disqualified"
        return result

    # Cash runway < 2 quarters
    runway_pts, runway_q = _score_runway(snapshot.get("total_cash"),
                                          snapshot.get("operating_cashflow"))
    result.runway_quarters = runway_q
    if runway_q < 2.0 and runway_q > 0:
        result.disqualified = True
        result.disqualify_reason = f"Cash runway {runway_q:.1f} quarters < 2 quarters"
        result.signal = "disqualified"
        return result

    # Share dilution > 50% in last 12 months
    dilution = snapshot.get("dilution_pct_yoy")
    if dilution is not None and dilution > 50:
        result.disqualified = True
        result.disqualify_reason = f"Dilution {dilution:.0f}% YoY > 50% - shareholder destruction"
        result.signal = "disqualified"
        return result

    # ── Score each factor ────────────────────────────────────────────────────

    result.breakdown["Revenue growth"]   = _score_revenue_growth(snapshot.get("revenue_growth"))
    result.breakdown["Cash runway"]      = runway_pts
    result.breakdown["Gross margin trend"] = _score_gross_margin_trend(snapshot.get("gross_margin_trend"))
    result.breakdown["Dilution"]         = _score_dilution(dilution)

    cust_pts, cust_note = _score_customer_concentration(customer_data)
    result.breakdown["Customer concentration"] = cust_pts
    result.customer_data_available = customer_data is not None and customer_data.get("has_data", False)

    result.breakdown["Short squeeze"]    = _score_short_squeeze(snapshot.get("short_pct_float"),
                                                                  news_signal)

    # Insider - accept either signal string or fallback bool
    if insider_signal == "NONE" and insider_buy:
        insider_signal = "NOTABLE"  # legacy bool → minimal tier
    result.breakdown["Insider buying"]   = _score_insider(insider_signal)

    cat_pts, cat_note = _score_catalyst(next_catalyst, days_to_earn)
    result.breakdown["Catalyst proximity"] = cat_pts
    result.catalyst_note = cat_note

    result.breakdown["Volume regime"]    = _score_volume(snapshot.get("average_volume"),
                                                          snapshot.get("price"))
    result.breakdown["Sector tailwind"]  = _score_sector_tailwind(ticker, snapshot.get("industry"))

    pat_pts, pat_note = _score_pattern(pattern_result)
    result.breakdown["Pattern"]          = pat_pts
    result.pattern_note                  = pat_note

    # ── Total + signal classification ────────────────────────────────────────
    result.total = sum(v for v in result.breakdown.values() if v > 0) + \
                   sum(v for v in result.breakdown.values() if v < 0)
    # Cap at 150 (sanity check, shouldn't trigger if weights correct)
    result.total = min(result.total, 150)

    if result.total >= 110:
        result.signal = "high_conviction"
    elif result.total >= 90:
        result.signal = "strong"
    elif result.total >= 60:
        result.signal = "candidate"
    else:
        result.signal = "weak"

    return result


# ── Pretty-print explanation (matches explain_score in score.py) ─────────────

def explain_spec_score(result: SpecScoreResult) -> str:
    """Human-readable spec score with breakdown + verdict."""
    if result.disqualified:
        return f"❌ SPEC DISQUALIFIED ({result.ticker}): {result.disqualify_reason}"

    icon = {"high_conviction": "🟢", "strong": "🟢",
            "candidate": "🟡", "weak": "⚪"}.get(result.signal, "⚪")
    lines = [
        f"  {icon} SPEC {result.signal.upper().replace('_',' ')}: {result.total}/150 pts",
        f"  Runway: {result.runway_quarters:.1f} quarters" if result.runway_quarters > 0 else "",
        f"  Catalyst: {result.catalyst_note}" if result.catalyst_note else "",
        f"  Pattern: {result.pattern_note}" if result.pattern_note else "",
    ]
    lines.append("  ── Breakdown ──")
    for k, v in result.breakdown.items():
        if v != 0:
            sign = "+" if v > 0 else ""
            lines.append(f"    {k}: {sign}{v}")
    return "\n".join(l for l in lines if l)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import yfinance as yf

    if len(sys.argv) < 2:
        print("Usage: python3 spec_score.py <TICKER> [TICKER...]")
        sys.exit(1)

    for ticker in sys.argv[1:]:
        ticker = ticker.upper()
        print()
        print("═" * 50)
        print(f"  SPEC ENTRY SCORE: {ticker}")
        print("═" * 50)

        try:
            t = yf.Ticker(ticker)
            info = t.info

            # Build snapshot from yfinance fields
            cal = {}
            try:
                cal = t.calendar or {}
            except Exception:
                cal = {}

            earn_dates = cal.get("Earnings Date", []) if isinstance(cal, dict) else []
            days_to_earn = None
            if earn_dates:
                try:
                    earn_d = earn_dates[0] if isinstance(earn_dates, list) else earn_dates
                    if hasattr(earn_d, "year"):
                        delta = (datetime(earn_d.year, earn_d.month, earn_d.day)
                                 - datetime.now()).days
                        days_to_earn = delta
                except Exception:
                    pass

            snap = {
                "ticker":             ticker,
                "price":              info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap":         info.get("marketCap"),
                "free_cash_flow":     info.get("freeCashflow"),
                "total_cash":         info.get("totalCash"),
                "operating_cashflow": info.get("operatingCashflow"),
                "revenue_growth":     info.get("revenueGrowth"),
                "total_revenue":      info.get("totalRevenue"),
                "gross_margin_trend": None,  # populated by integration with quarterly data later
                "dilution_pct_yoy":   None,  # populated later
                "short_pct_float":    info.get("shortPercentOfFloat") and info["shortPercentOfFloat"]*100,
                "average_volume":     info.get("averageVolume"),
                "industry":           info.get("industry"),
                "days_to_earnings":   days_to_earn,
            }

            # Check spec classification
            if not is_spec_candidate(snap):
                print(f"  ℹ️  {ticker} is NOT a spec candidate.")
                print(f"     Market cap: ${(snap.get('market_cap') or 0)/1e9:.1f}B")
                print(f"     FCF: ${(snap.get('free_cash_flow') or 0)/1e6:.0f}M")
                print(f"     Use 'python3 score.py {ticker}' for regular 180pt scoring.")
                continue

            # Try to fetch insider signal (cached)
            ins_signal = "NONE"
            try:
                from insider import _load_cache
                cache = _load_cache()
                if ticker in cache.get("signals", {}):
                    ins_signal = cache["signals"][ticker].get("signal", "NONE")
            except Exception:
                pass

            result = score_spec(snap, insider_signal=ins_signal)
            print(explain_spec_score(result))

        except Exception as e:
            print(f"  ⚠️  Error scoring {ticker}: {e}")
        print()
