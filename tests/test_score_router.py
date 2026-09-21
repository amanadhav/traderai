"""
tests/test_score_router.py - 10 tests for spec/regular routing logic.

Tests `is_spec_candidate()` routing conditions and the `--force-regular` bypass.
All tests are pure unit tests - no network, no real snapshots.
"""

import pytest
from spec_score import is_spec_candidate, score_spec, SpecScoreResult
from score import score_ticker, ScoreResult


# ── is_spec_candidate() routing tests ────────────────────────────────────────

class TestSpecRouter:

    def test_large_cap_positive_fcf_not_spec(self):
        """NVDA-type: large cap, positive FCF, price >$10 → regular scorer."""
        snap = {
            "ticker": "NVDA",
            "market_cap": 2_500_000_000_000,  # $2.5T
            "free_cash_flow": 50_000_000_000,   # positive FCF
            "revenue_growth": 0.12,              # 12%, not high-growth
            "price": 900.0,
        }
        assert is_spec_candidate(snap) is False

    def test_negative_fcf_small_cap_is_spec(self):
        """Neg FCF + small cap → spec."""
        snap = {
            "market_cap": 800_000_000,   # $800M
            "free_cash_flow": -50_000_000,
            "revenue_growth": 0.20,
            "price": 8.0,
        }
        assert is_spec_candidate(snap) is True

    def test_high_growth_small_cap_is_spec(self):
        """Rev growth >50% even with positive FCF → spec (hyper-growth startup)."""
        snap = {
            "market_cap": 2_000_000_000,  # $2B
            "free_cash_flow": 10_000_000,  # positive FCF
            "revenue_growth": 0.75,         # 75% growth
            "price": 15.0,
        }
        assert is_spec_candidate(snap) is True

    def test_penny_stock_is_spec(self):
        """Price <$10 + small cap → spec regardless of FCF."""
        snap = {
            "market_cap": 200_000_000,
            "free_cash_flow": 5_000_000,  # positive FCF
            "revenue_growth": 0.10,
            "price": 4.50,
        }
        assert is_spec_candidate(snap) is True

    def test_large_cap_neg_fcf_not_spec(self):
        """Large cap (>$5B) always routes to regular scorer, even neg FCF."""
        snap = {
            "market_cap": 40_000_000_000,   # $40B - like RKT
            "free_cash_flow": -500_000_000,  # neg FCF
            "revenue_growth": 0.60,
            "price": 15.0,
        }
        assert is_spec_candidate(snap) is False

    def test_zero_market_cap_not_spec(self):
        """No market cap data → cannot classify as spec → False."""
        snap = {
            "market_cap": 0,
            "free_cash_flow": -1_000_000,
            "price": 5.0,
        }
        assert is_spec_candidate(snap) is False

    def test_none_market_cap_not_spec(self):
        """None market cap → False."""
        snap = {
            "market_cap": None,
            "free_cash_flow": -1_000_000,
            "price": 5.0,
        }
        assert is_spec_candidate(snap) is False

    def test_boundary_5b_cap_not_spec(self):
        """Exactly $5B market cap → NOT spec (threshold is strictly <$5B)."""
        snap = {
            "market_cap": 5_000_000_000,
            "free_cash_flow": -10_000_000,
            "revenue_growth": 0.20,
            "price": 8.0,
        }
        assert is_spec_candidate(snap) is False

    def test_just_under_5b_cap_with_neg_fcf_is_spec(self):
        """$4.99B + neg FCF → spec."""
        snap = {
            "market_cap": 4_999_999_999,
            "free_cash_flow": -10_000_000,
            "revenue_growth": 0.20,
            "price": 8.0,
        }
        assert is_spec_candidate(snap) is True


# ── Growth carve-out tests ($5B-$50B pre-profit infrastructure) ──────────────

class TestGrowthCarveOut:
    """Pre-profit growth-stage plays in the $5B-$50B gap (RKLB, ASTS, JOBY).
    Carve-out requires ALL: neg FCF + rev_growth >=25% + runway >=8q."""

    def _rklb_like(self, **overrides) -> dict:
        """RKLB-like base snap: $42B mkt cap, neg FCF, 30% growth, 10q runway."""
        snap = {
            "market_cap":          42_000_000_000,   # $42B
            "free_cash_flow":      -271_000_000,      # neg FCF
            "revenue_growth":      0.30,              # 30% YoY
            "price":               78.0,
            "total_cash":          800_000_000,       # $800M cash
            "operating_cashflow":  -320_000_000,      # ~$80M/q burn → 10q runway
        }
        snap.update(overrides)
        return snap

    def test_rklb_like_gets_carve_out(self):
        """$42B + neg FCF + 30% growth + 10q runway → spec via carve-out."""
        assert is_spec_candidate(self._rklb_like()) is True

    def test_carve_out_fails_with_low_growth(self):
        """$42B + neg FCF but only 5% growth → not spec (melting ice cube)."""
        snap = self._rklb_like(revenue_growth=0.05)
        assert is_spec_candidate(snap) is False

    def test_carve_out_fails_over_50b_ceiling(self):
        """$55B + neg FCF + high growth → over carve-out ceiling, regular scorer."""
        snap = self._rklb_like(market_cap=55_000_000_000)
        assert is_spec_candidate(snap) is False

    def test_carve_out_fails_with_short_runway(self):
        """$42B + neg FCF + 30% growth but 4q runway → not spec (will dilute)."""
        snap = self._rklb_like(
            total_cash=200_000_000,
            operating_cashflow=-200_000_000,  # 4q runway
        )
        assert is_spec_candidate(snap) is False

    def test_carve_out_fails_with_positive_fcf(self):
        """$42B + positive FCF → not spec (no carve-out needed, regular handles it)."""
        snap = self._rklb_like(free_cash_flow=100_000_000)
        assert is_spec_candidate(snap) is False

    def test_carve_out_boundary_50b_not_spec(self):
        """Exactly $50B → NOT spec (carve-out is strictly <$50B)."""
        snap = self._rklb_like(market_cap=50_000_000_000)
        assert is_spec_candidate(snap) is False

    def test_carve_out_boundary_25pct_growth_is_spec(self):
        """Exactly 25% growth at boundary → spec (>= threshold)."""
        snap = self._rklb_like(revenue_growth=0.25)
        assert is_spec_candidate(snap) is True

    def test_carve_out_just_under_25pct_not_spec(self):
        """24% growth → just under threshold → not spec."""
        snap = self._rklb_like(revenue_growth=0.24)
        assert is_spec_candidate(snap) is False


# ── score_ticker routes correctly (type check) ───────────────────────────────

class TestScoreRouterTypes:

    def _make_regular_snap(self) -> dict:
        """Large cap snap that should stay in regular scorer."""
        return {
            "ticker": "NVDA",
            "market_cap": 2_500_000_000_000,
            "free_cash_flow": 50_000_000_000,
            "revenue_growth": 0.12,
            "price": 900.0,
            "rsi": 50,
            "macd_crossover": False,
            "bb_pct": 0.50,
            "vol_ratio": 1.0,
            "dividend_yield": 0.01,
            "low_52w": 500.0,
            "high_52w": 1000.0,
            "rel_strength_vs_sp": 0.0,
            "debt_to_equity": 50,
            "short_pct_float": 0.02,
            "analyst_target": None,
            "ma200": 700.0,
            "days_to_earnings": 60,
            "operatingCashflow": 60_000_000_000,
            "totalRevenue": 90_000_000_000,
        }

    def _make_spec_snap(self) -> dict:
        """Small cap neg-FCF snap that should route to spec scorer."""
        return {
            "ticker": "BBAI",
            "market_cap": 400_000_000,
            "free_cash_flow": -30_000_000,
            "revenue_growth": 0.35,
            "price": 3.50,
            "rsi": 45,
            "days_to_earnings": 45,
            "totalRevenue": 50_000_000,
            "totalCash": 80_000_000,
            "operatingCashflow": -28_000_000,
            "sharesOutstanding": 100_000_000,
            "grossMargins": 0.25,
            "shortPercentOfFloat": 0.18,
            "averageVolume": 5_000_000,
            "industry": "defense analytics",
        }

    def test_regular_snap_returns_score_result(self):
        snap = self._make_regular_snap()
        assert is_spec_candidate(snap) is False
        result = score_ticker(snap)
        assert isinstance(result, ScoreResult)

    def test_spec_snap_routes_to_spec_scorer(self):
        snap = self._make_spec_snap()
        assert is_spec_candidate(snap) is True
        result = score_spec(snap)
        assert isinstance(result, SpecScoreResult)

    def test_spec_result_shows_150_not_180(self):
        snap = self._make_spec_snap()
        result = score_spec(snap)
        s = str(result)
        assert "/150" in s
        assert "/180" not in s
