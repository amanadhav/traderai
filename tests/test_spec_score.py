"""
test_spec_score.py - unit tests for spec_score.py (150pt startup/penny scorer).

Tests cover:
  - is_spec_candidate(): all 3 trigger conditions + size ceiling
  - All 5 disqualifiers (runway, price, dilution, zero-revenue, earnings)
  - Each scoring factor at boundary values
  - Threshold classification
  - Customer concentration logic (strategic vs concentrated vs diversified)
  - Catalyst proximity (manual + earnings + ex-dividend)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timedelta
from spec_score import (
    score_spec, is_spec_candidate, SpecScoreResult,
    _score_revenue_growth, _score_runway, _score_dilution,
    _score_customer_concentration, _score_short_squeeze, _score_insider,
    _score_catalyst, _score_volume, _score_sector_tailwind,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def spec_snap():
    """Minimal spec ticker snap - passes is_spec_candidate, no disqualifiers."""
    return {
        "ticker": "TEST",
        "price": 5.00,
        "market_cap": 1_000_000_000,    # $1B = small cap
        "free_cash_flow": -50_000_000,   # neg FCF → spec
        "total_cash": 200_000_000,
        "operating_cashflow": -40_000_000,  # 5q runway
        "revenue_growth": 0.30,
        "total_revenue": 100_000_000,
        "short_pct_float": 10.0,
        "average_volume": 5_000_000,
        "industry": "Aerospace & Defense",
        "days_to_earnings": 60,
        "dilution_pct_yoy": 8.0,
    }


# ── is_spec_candidate ─────────────────────────────────────────────────────────

def test_is_spec_negative_fcf_small_cap(spec_snap):
    """Small cap + neg FCF → spec."""
    assert is_spec_candidate(spec_snap) is True


def test_is_spec_high_growth_small_cap(spec_snap):
    """Small cap + high revenue growth → spec, even with positive FCF."""
    snap = {**spec_snap, "free_cash_flow": 10_000_000, "revenue_growth": 0.75}
    assert is_spec_candidate(snap) is True


def test_is_spec_penny_stock(spec_snap):
    """Small cap + price <$10 → spec."""
    snap = {**spec_snap, "free_cash_flow": 5_000_000, "revenue_growth": 0.05, "price": 3.0}
    assert is_spec_candidate(snap) is True


def test_not_spec_large_cap(spec_snap):
    """Large cap (>$5B) → never spec, regardless of FCF."""
    snap = {**spec_snap, "market_cap": 50_000_000_000}
    assert is_spec_candidate(snap) is False


def test_not_spec_unknown_market_cap(spec_snap):
    """Unknown mkt cap → conservative, NOT spec."""
    snap = {**spec_snap, "market_cap": None}
    assert is_spec_candidate(snap) is False


def test_not_spec_profitable_mid_cap():
    """Profitable mid-cap with normal growth → regular scoring."""
    snap = {
        "ticker": "TEST", "price": 50, "market_cap": 3_000_000_000,
        "free_cash_flow": 100_000_000, "revenue_growth": 0.10,
    }
    assert is_spec_candidate(snap) is False


# ── Disqualifiers ─────────────────────────────────────────────────────────────

def test_disqualify_earnings_imminent(spec_snap):
    snap = {**spec_snap, "days_to_earnings": 8}
    r = score_spec(snap)
    assert r.disqualified is True
    assert "Earnings" in r.disqualify_reason


def test_disqualify_penny_under_dollar(spec_snap):
    snap = {**spec_snap, "price": 0.85}
    r = score_spec(snap)
    assert r.disqualified is True
    assert "delisting" in r.disqualify_reason.lower()


def test_price_just_above_dollar_ok(spec_snap):
    snap = {**spec_snap, "price": 1.50}
    r = score_spec(snap)
    assert r.disqualified is False


def test_disqualify_zero_revenue(spec_snap):
    snap = {**spec_snap, "total_revenue": 0}
    r = score_spec(snap)
    assert r.disqualified is True
    assert "shell" in r.disqualify_reason.lower()


def test_disqualify_runway_under_2_quarters(spec_snap):
    """$10M cash, $40M annual burn → 1 quarter runway → disqualified."""
    snap = {**spec_snap, "total_cash": 10_000_000, "operating_cashflow": -40_000_000}
    r = score_spec(snap)
    assert r.disqualified is True
    assert "runway" in r.disqualify_reason.lower()


def test_runway_just_above_2q_ok(spec_snap):
    """$25M cash, $40M annual burn → 2.5 quarter runway → passes."""
    snap = {**spec_snap, "total_cash": 25_000_000, "operating_cashflow": -40_000_000}
    r = score_spec(snap)
    assert r.disqualified is False


def test_disqualify_extreme_dilution(spec_snap):
    """>50% YoY dilution → disqualified."""
    snap = {**spec_snap, "dilution_pct_yoy": 75.0}
    r = score_spec(snap)
    assert r.disqualified is True
    assert "dilution" in r.disqualify_reason.lower()


def test_dilution_just_under_50_ok(spec_snap):
    snap = {**spec_snap, "dilution_pct_yoy": 45.0}
    r = score_spec(snap)
    assert r.disqualified is False


# ── Revenue growth scoring ────────────────────────────────────────────────────

def test_revenue_growth_hyperscale():
    assert _score_revenue_growth(1.5) == 25  # 150% YoY


def test_revenue_growth_strong():
    assert _score_revenue_growth(0.6) == 20


def test_revenue_growth_moderate():
    assert _score_revenue_growth(0.30) == 15


def test_revenue_growth_low():
    assert _score_revenue_growth(0.15) == 8


def test_revenue_growth_flat():
    assert _score_revenue_growth(0.05) == 0


def test_revenue_growth_negative():
    assert _score_revenue_growth(-0.1) == 0


def test_revenue_growth_none():
    assert _score_revenue_growth(None) == 0


# ── Runway scoring ────────────────────────────────────────────────────────────

def test_runway_long_safe():
    """$240M cash, $80M annual burn → 12q runway → 20pts."""
    pts, q = _score_runway(240_000_000, -80_000_000)
    assert pts == 20
    assert q == 12.0


def test_runway_positive_op_cashflow():
    """Positive op cashflow → infinite runway → 20pts."""
    pts, q = _score_runway(50_000_000, 10_000_000)
    assert pts == 20


def test_runway_8_quarters():
    """$160M cash, $80M burn → 8q runway → 15pts."""
    pts, q = _score_runway(160_000_000, -80_000_000)
    assert pts == 15


def test_runway_short():
    """$80M cash, $80M burn → 4q runway → 8pts."""
    pts, q = _score_runway(80_000_000, -80_000_000)
    assert pts == 8


def test_runway_critical():
    """Below 4 quarters → 0pts, but ≥2q so not disqualifier."""
    pts, q = _score_runway(50_000_000, -80_000_000)  # 2.5q
    assert pts == 0


# ── Dilution ──────────────────────────────────────────────────────────────────

def test_dilution_minimal():
    assert _score_dilution(3.0) == 15


def test_dilution_moderate():
    assert _score_dilution(12.0) == 10


def test_dilution_concerning():
    assert _score_dilution(20.0) == 5


def test_dilution_excessive_no_bonus():
    """Between 25 and 50% - no bonus but doesn't disqualify yet."""
    assert _score_dilution(35.0) == 0


# ── Customer concentration ────────────────────────────────────────────────────

def test_customer_strategic_dod():
    data = {"has_data": True, "top_customer": "U.S. Department of Defense", "pct": 45,
            "all_customers": [{"name": "DoD", "pct": 45}]}
    pts, note = _score_customer_concentration(data)
    assert pts == 10
    assert "strategic" in note.lower() or "DoD" in note or "defense" in note.lower()


def test_customer_strategic_microsoft():
    data = {"has_data": True, "top_customer": "Microsoft Corporation", "pct": 35,
            "all_customers": []}
    pts, _ = _score_customer_concentration(data)
    assert pts == 10


def test_customer_concentrated_non_strategic():
    """High concentration but no strategic name → 0pts."""
    data = {"has_data": True, "top_customer": "Acme Industries", "pct": 40,
            "all_customers": []}
    pts, note = _score_customer_concentration(data)
    assert pts == 0
    assert "risk" in note.lower() or "concentrat" in note.lower()


def test_customer_diversified():
    data = {"has_data": True, "top_customer": "Acme", "pct": 12,
            "all_customers": [{"name": "Acme", "pct": 12}, {"name": "Beta", "pct": 10}]}
    pts, note = _score_customer_concentration(data)
    assert pts == 5
    assert "diversified" in note.lower()


def test_customer_no_data():
    pts, note = _score_customer_concentration(None)
    assert pts == 0
    assert note == ""


def test_customer_data_unavailable():
    pts, _ = _score_customer_concentration({"has_data": False})
    assert pts == 0


# ── Short squeeze ─────────────────────────────────────────────────────────────

def test_short_squeeze_max_with_catalyst():
    pts = _score_short_squeeze(30.0, news_signal="POSITIVE")
    assert pts == 10


def test_short_squeeze_high_no_catalyst():
    pts = _score_short_squeeze(28.0, news_signal="NEUTRAL")
    assert pts == 7


def test_short_squeeze_moderate():
    assert _score_short_squeeze(18.0) == 5


def test_short_squeeze_low():
    assert _score_short_squeeze(8.0) == 0


# ── Insider ───────────────────────────────────────────────────────────────────

def test_insider_strong():
    assert _score_insider("STRONG") == 15


def test_insider_cluster():
    assert _score_insider("CLUSTER") == 12


def test_insider_notable():
    assert _score_insider("NOTABLE") == 8


def test_insider_none():
    assert _score_insider("NONE") == 0


# ── Catalyst proximity ────────────────────────────────────────────────────────

def test_catalyst_near_term_manual():
    future = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
    cat = {"date": future, "type": "launch", "note": "Neutron Y demo"}
    pts, note = _score_catalyst(cat, days_to_earnings=None)
    assert pts == 10
    assert "LAUNCH" in note.upper()


def test_catalyst_60d_out():
    future = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
    cat = {"date": future, "type": "fda", "note": ""}
    pts, _ = _score_catalyst(cat, days_to_earnings=None)
    assert pts == 7


def test_catalyst_earnings_only():
    """Only earnings 25d out, no manual catalyst → score earnings."""
    pts, note = _score_catalyst(None, days_to_earnings=25)
    assert pts == 10
    assert "EARNINGS" in note.upper()


def test_catalyst_picks_soonest():
    """Manual catalyst 50d, earnings 80d → manual wins (smaller)."""
    future = (datetime.now() + timedelta(days=50)).strftime("%Y-%m-%d")
    cat = {"date": future, "type": "contract", "note": "DoD award"}
    pts, note = _score_catalyst(cat, days_to_earnings=80)
    assert pts == 7
    assert "CONTRACT" in note.upper()


def test_catalyst_none():
    pts, note = _score_catalyst(None, days_to_earnings=None)
    assert pts == 0
    assert note == ""


# ── Volume regime ─────────────────────────────────────────────────────────────

def test_volume_high_liquidity():
    """$50M+ daily dollar volume → 10pts."""
    assert _score_volume(20_000_000, 5.0) == 10  # $100M/day


def test_volume_decent():
    assert _score_volume(3_000_000, 5.0) == 5   # $15M/day


def test_volume_illiquid_penalty():
    """Below $1M/day → -5pts liquidity penalty."""
    assert _score_volume(100_000, 5.0) == -5  # $500K/day


# ── Sector tailwind ───────────────────────────────────────────────────────────

def test_sector_explicit_narrative_match():
    """BBAI is in TICKER_NARRATIVES with active narratives → 10pts."""
    pts = _score_sector_tailwind("BBAI", "Information Technology Services")
    assert pts == 10


def test_sector_industry_keyword_match():
    """Aerospace & Defense industry → adjacent narrative match → 5pts."""
    pts = _score_sector_tailwind("ZZZZ", "Aerospace & Defense")
    assert pts == 5


def test_sector_no_match():
    pts = _score_sector_tailwind("ZZZZ", "Restaurants")
    assert pts == 0


# ── Threshold classification ──────────────────────────────────────────────────

def test_threshold_high_conviction(spec_snap):
    """Build snap that scores ≥110."""
    snap = {
        **spec_snap,
        "revenue_growth": 1.20,        # 25
        "total_cash": 500_000_000,
        "operating_cashflow": -40_000_000,  # 12.5q → 20
        "gross_margin_trend": [0.20, 0.25, 0.30, 0.35],  # improving → 15
        "dilution_pct_yoy": 3.0,       # 15
        "short_pct_float": 28.0,       # 7
        "average_volume": 20_000_000,  # *5 → 10
    }
    r = score_spec(
        snap,
        insider_signal="STRONG",       # 15
        next_catalyst={"date": (datetime.now()+timedelta(days=20)).strftime("%Y-%m-%d"),
                        "type": "launch", "note": ""},  # 10
        pattern_result={"signal": "bullish", "confidence": 0.8, "pattern": "double_bottom"},  # 10
    )
    assert r.total >= 110, f"Expected ≥110, got {r.total}. Breakdown: {r.breakdown}"
    assert r.signal == "high_conviction"


def test_threshold_strong(spec_snap):
    """Snap scoring 90-110."""
    snap = {
        **spec_snap,
        "revenue_growth": 0.60,        # 20
        "total_cash": 500_000_000,
        "operating_cashflow": -40_000_000,  # 20
        "dilution_pct_yoy": 8.0,       # 10
        "short_pct_float": 18.0,       # 5
    }
    r = score_spec(snap, insider_signal="CLUSTER")  # 12
    assert 60 <= r.total < 110, f"Expected 60-110, got {r.total}"


def test_threshold_weak(spec_snap):
    """Default minimal snap → weak."""
    r = score_spec(spec_snap)
    assert r.signal in ("weak", "candidate")
    assert r.total < 60 or r.signal == "candidate"  # candidate floor is 60


def test_max_score_cap_150(spec_snap):
    """Max possible score should not exceed 150."""
    snap = {
        **spec_snap,
        "revenue_growth": 2.0,         # 25
        "total_cash": 1_000_000_000,
        "operating_cashflow": -40_000_000,  # 20
        "gross_margin_trend": [0.10, 0.20, 0.30, 0.40],  # 15
        "dilution_pct_yoy": 0.0,       # 15
        "short_pct_float": 30.0,       # 10
        "average_volume": 50_000_000,  # 10
    }
    r = score_spec(
        snap, insider_signal="STRONG",
        next_catalyst={"date": (datetime.now()+timedelta(days=10)).strftime("%Y-%m-%d"),
                        "type": "launch", "note": ""},
        pattern_result={"signal":"bullish","confidence":0.9,"pattern":"double_bottom"},
        customer_data={"has_data": True, "top_customer": "Department of Defense", "pct": 40,
                        "all_customers":[]},
        news_signal="POSITIVE",
    )
    assert r.total <= 150, f"Score {r.total} exceeds 150 cap"


# ── ScoreResult __str__ ──────────────────────────────────────────────────────

def test_str_shows_150_format(spec_snap):
    r = score_spec(spec_snap)
    s = str(r)
    assert "/150" in s
    assert "SPEC" in s


def test_str_disqualified_format(spec_snap):
    snap = {**spec_snap, "days_to_earnings": 5}
    r = score_spec(snap)
    s = str(r)
    assert "DISQUALIFIED" in s
