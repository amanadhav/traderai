"""
test_score.py - unit tests for score.py (180pt entry scoring algorithm).

Tests cover:
  - RSI point tiers
  - Auto-disqualifiers (earnings, FCF, D/E)
  - Signal threshold classification
  - Insider buying bonus
  - ScoreResult.__str__ format
  - size_position() VIX scaling and beta tiers
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from score import score_ticker, size_position, ScoreResult


# ── RSI point tiers ───────────────────────────────────────────────────────────

def test_rsi_deeply_oversold(minimal_snap):
    snap = {**minimal_snap, "rsi": 28}
    r = score_ticker(snap)
    assert r.breakdown["RSI"] == 25


def test_rsi_oversold(minimal_snap):
    snap = {**minimal_snap, "rsi": 36}
    r = score_ticker(snap)
    assert r.breakdown["RSI"] == 15


def test_rsi_neutral_zone(minimal_snap):
    snap = {**minimal_snap, "rsi": 55}
    r = score_ticker(snap)
    assert r.breakdown["RSI"] == 0


def test_rsi_mild_oversold(minimal_snap):
    snap = {**minimal_snap, "rsi": 48}
    r = score_ticker(snap)
    assert r.breakdown["RSI"] == 5


# ── Auto-disqualifiers ────────────────────────────────────────────────────────

def test_disqualify_earnings_imminent(minimal_snap):
    snap = {**minimal_snap, "days_to_earnings": 10}
    r = score_ticker(snap)
    assert r.disqualified is True
    assert r.total == 0


def test_disqualify_earnings_3_days(minimal_snap):
    snap = {**minimal_snap, "days_to_earnings": 3}
    r = score_ticker(snap)
    assert r.disqualified is True


def test_earnings_far_away_ok(minimal_snap):
    snap = {**minimal_snap, "days_to_earnings": 60}
    r = score_ticker(snap)
    assert r.disqualified is False


def test_disqualify_negative_fcf(minimal_snap):
    # score_ticker uses 'free_cash_flow' (dollar amount), not 'fcf_yield'
    snap = {**minimal_snap, "free_cash_flow": -50_000_000}
    r = score_ticker(snap)
    assert r.disqualified is True


def test_disqualify_high_debt(minimal_snap):
    # score_ticker uses 'debt_to_equity' (not 'de_ratio')
    snap = {**minimal_snap, "debt_to_equity": 250}
    r = score_ticker(snap)
    assert r.disqualified is True


def test_debt_under_limit_ok(minimal_snap):
    snap = {**minimal_snap, "debt_to_equity": 1.5}
    r = score_ticker(snap)
    assert r.disqualified is False


# ── Signal threshold classification ──────────────────────────────────────────

def test_threshold_candidate(strong_snap):
    """Score ≥70 → candidate signal."""
    r = score_ticker(strong_snap)
    assert r.total >= 70
    assert r.signal in ("candidate", "strong", "high_conviction")


def test_threshold_strong(strong_snap):
    """Fully bullish snap + insider + pattern → strong or high_conviction."""
    r = score_ticker(
        strong_snap,
        insider_buy=True,
        pattern_result={"signal": "bullish", "confidence": 0.8, "pattern": "double_bottom"},
    )
    assert r.total >= 110, f"Expected ≥110, got {r.total}. Breakdown: {r.breakdown}"
    assert r.signal in ("strong", "high_conviction")


def test_weak_signal(minimal_snap):
    """Neutral snap → weak signal."""
    r = score_ticker(minimal_snap)
    assert r.signal == "weak"


# ── Insider buying bonus ──────────────────────────────────────────────────────

def test_insider_bonus_adds_points(minimal_snap):
    without = score_ticker(minimal_snap, insider_buy=False)
    with_insider = score_ticker(minimal_snap, insider_buy=True)
    assert with_insider.total - without.total == 10  # max 10pts after fix


def test_insider_no_bonus_when_false(minimal_snap):
    r = score_ticker(minimal_snap, insider_buy=False)
    assert r.breakdown["Insider buying"] == 0


def test_insider_bonus_when_true(minimal_snap):
    r = score_ticker(minimal_snap, insider_buy=True)
    assert r.breakdown["Insider buying"] == 10


# ── ScoreResult.__str__ format ────────────────────────────────────────────────

def test_str_shows_180_not_130(minimal_snap):
    r = score_ticker(minimal_snap)
    s = str(r)
    assert "/180" in s, f"Expected '/180' in ScoreResult.__str__, got: {s!r}"
    assert "/130" not in s, f"Found stale '/130' in ScoreResult.__str__: {s!r}"


# ── Falling-knife guard ───────────────────────────────────────────────────────

def test_falling_knife_guard_fires_on_tech_only():
    """Tech ≥50pts with zero fundamentals → -10pt soft penalty."""
    snap = {
        "ticker": "FAKE_NO_NARRATIVE",
        "rsi": 25,                  # 25pts
        "macd_crossover": True,     # 20pts
        "bb_pct": 15,               # 20pts
        "price": 100,
        "ma200": 110,               # 10pts (below 200MA)
    }
    r = score_ticker(snap)
    # Tech sum = 25+20+20+10 = 75. Penalty = -10. Final = 65.
    assert "Falling-knife guard" in r.breakdown
    assert r.breakdown["Falling-knife guard"] == -10
    assert "FALLING-KNIFE" in (r.regime_note or "")
    # Soft penalty preserves directional signal: still has score, but reduced
    raw_tech = sum(r.breakdown.get(f, 0) for f in
                   ["RSI", "MACD", "BB%", "Volume", "Rel strength",
                    "Below 200MA", "52W low", "Pattern"])
    assert r.total == raw_tech - 10


def test_falling_knife_guard_pass_with_narrative():
    """Ticker with active macro narrative → no penalty."""
    snap = {
        "ticker": "NVDA",  # has ai_infra narrative
        "rsi": 25,
        "macd_crossover": True,
        "bb_pct": 15,
        "price": 100,
        "ma200": 110,
    }
    r = score_ticker(snap)
    assert "Falling-knife guard" not in r.breakdown


def test_falling_knife_guard_pass_with_fcf():
    """High tech + positive FCF yield → fundamental confirmation, no penalty."""
    snap = {
        "ticker": "FAKE",
        "rsi": 25, "macd_crossover": True, "bb_pct": 15,
        "price": 100, "ma200": 110,
        "free_cash_flow": 500_000_000,   # positive FCF
        "market_cap":     5_000_000_000,  # 10% FCF yield = 10pts
    }
    r = score_ticker(snap)
    assert "Falling-knife guard" not in r.breakdown


def test_falling_knife_guard_does_not_fire_low_tech():
    """Tech <50pts → guard never fires regardless of fundamentals."""
    snap = {
        "ticker": "FAKE",
        "rsi": 45,       # 5pts, below 50 tech threshold
    }
    r = score_ticker(snap)
    assert "Falling-knife guard" not in r.breakdown


def test_falling_knife_guard_soft_penalty_preserves_strong_setups():
    """Tech 80pts + no fund → 70pts (still candidate). Was: capped to 60 (weak)."""
    snap = {
        "ticker": "FAKE_NO_DICT",
        "rsi": 25,                  # 25pts
        "macd_crossover": True,     # 20pts
        "bb_pct": 15,               # 20pts
        "rel_strength_vs_sp": 6,    # 10pts
        "price": 100,
        "ma200": 110,               # 10pts
    }
    r = score_ticker(snap)
    # Tech = 25+20+20+10+10 = 85. Penalty -10. Final = 75 → still candidate.
    assert r.breakdown["Falling-knife guard"] == -10
    assert r.total >= 70, f"Soft guard should preserve candidate signal, got {r.total}"
    assert r.signal == "candidate"


def test_str_disqualified_format(minimal_snap):
    snap = {**minimal_snap, "days_to_earnings": 5}
    r = score_ticker(snap)
    s = str(r)
    assert "DISQUALIFIED" in s


def test_str_includes_ticker(minimal_snap):
    snap = {**minimal_snap, "ticker": "NVDA"}
    r = score_ticker(snap)
    s = str(r)
    assert "NVDA" in s


# ── Macro narrative bonus ─────────────────────────────────────────────────────

def test_macro_narrative_multi_active(minimal_snap):
    """Ticker with 2+ active narratives → 10pts."""
    snap = {**minimal_snap, "ticker": "NVDA"}  # ai_infra + chip_independence
    r = score_ticker(snap)
    assert r.breakdown["Macro narrative"] == 10


def test_macro_narrative_single(minimal_snap):
    """Ticker with 1 active narrative → 7pts."""
    snap = {**minimal_snap, "ticker": "NVO"}  # glp1_obesity only
    r = score_ticker(snap)
    assert r.breakdown["Macro narrative"] == 7


def test_macro_narrative_none(minimal_snap):
    """Unknown ticker → 0pts."""
    snap = {**minimal_snap, "ticker": "ZZZZZ"}
    r = score_ticker(snap)
    assert r.breakdown["Macro narrative"] == 0


# ── Max points cap ────────────────────────────────────────────────────────────

def test_max_score_does_not_exceed_180(strong_snap):
    """Even with all factors, score ≤ 180."""
    r = score_ticker(
        strong_snap,
        insider_buy=True,
        pattern_result={"signal": "bullish", "confidence": 0.9, "pattern": "cup_handle"},
    )
    assert r.total <= 180, f"Score {r.total} exceeds 180pt cap"


# ── size_position() ───────────────────────────────────────────────────────────

def test_size_position_vix_extreme(minimal_snap):
    """VIX > 35 → 50% of base size."""
    normal = size_position(minimal_snap, vix=15)
    extreme = size_position(minimal_snap, vix=40)
    assert extreme == pytest.approx(normal * 0.5, rel=0.1)


def test_size_position_vix_elevated(minimal_snap):
    """VIX > 25 → 75% of base size."""
    normal = size_position(minimal_snap, vix=15)
    elevated = size_position(minimal_snap, vix=28)
    assert elevated == pytest.approx(normal * 0.75, rel=0.1)


def test_size_position_high_beta(minimal_snap):
    """Beta > 1.6 → $500 base."""
    snap = {**minimal_snap, "beta": 2.0}
    sz = size_position(snap, vix=15)
    assert sz == 500


def test_size_position_medium_beta(minimal_snap):
    """Beta 1.3-1.6 → $750 base."""
    snap = {**minimal_snap, "beta": 1.5}
    sz = size_position(snap, vix=15)
    assert sz == 750


def test_size_position_low_beta(minimal_snap):
    """Beta ≤ 1.3 → $1000 base."""
    snap = {**minimal_snap, "beta": 0.8}
    sz = size_position(snap, vix=15)
    assert sz == 1000


def test_size_position_high_short_interest(minimal_snap):
    """short_pct_float > 5% → 75% size penalty (field is 'short_pct_float' not 'short_pct')."""
    snap_low  = {**minimal_snap, "short_pct_float": 3, "beta": 0.8}
    snap_high = {**minimal_snap, "short_pct_float": 8, "beta": 0.8}
    low  = size_position(snap_low,  vix=15)
    high = size_position(snap_high, vix=15)
    assert high < low
