"""
conftest.py - shared pytest fixtures for trading system tests.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path, monkeypatch):
    """Every test runs against pristine default config, never the developer's
    real user_config.json (which would silently change engine behavior)."""
    import user_config
    monkeypatch.setattr(user_config, "CONFIG_FILE", tmp_path / "user_config.json")
    user_config._cache = None
    yield
    user_config._cache = None


@pytest.fixture
def minimal_snap():
    """Minimal snapshot dict - only fields score_ticker absolutely requires."""
    return {
        "ticker": "TEST",
        "price": 100.0,
        "rsi": 50,
        "macd_hist": 0.0,
        "bb_pct": 0.5,
        "analyst_upside": 0,
        "div_yield": 0.0,
        "pct_from_52w_low": 20,
        "volume_ratio": 1.0,
        "rel_strength": 1.0,
        "analyst_rating": 3.0,
        "short_pct": 3.0,
        "pct_below_200ma": None,
        "fcf_yield": 2.0,
        "pe_ratio": 20,
        "de_ratio": 0.5,
        "days_to_earnings": 60,
    }


@pytest.fixture
def oversold_snap(minimal_snap):
    """Snap with strong RSI oversold signal."""
    return {**minimal_snap, "rsi": 28, "bb_pct": 0.10, "volume_ratio": 1.8}


@pytest.fixture
def strong_snap(minimal_snap):
    """Snap crafted to hit ≥110 score. Uses exact field names from score.py."""
    return {
        **minimal_snap,
        "ticker": "NVDA",
        "rsi": 28,               # 25pts (RSI <30)
        "macd_crossover": True,  # 20pts (MACD histogram crossover)
        "bb_pct": 0.10,          # 20pts (BB% <20)
        "div_yield": 5.0,        # 10pts (div yield >4%)
        "pct_from_52w_low": 8,   # 5pts (near 52W low)
        "vol_ratio": 2.0,        # 10pts (volume_ratio >1.5)
        "rel_strength_vs_sp": 1.2, # 10pts (outperforming S&P)
        "analyst_rating": 1.8,   # 5pts (analyst ≤2.0)
        "short_pct_float": 12,   # 5pts (short interest >10%)
        "price": 400.0,
        "ma200": 430.0,          # price < ma200 → below 200MA bonus (10pts)
        "free_cash_flow": 5_000_000_000,  # positive FCF
        "market_cap": 100_000_000_000,   # → fcf_yield 5% (10pts)
        "days_to_earnings": 60,
    }


@pytest.fixture
def mock_headlines_negative():
    return [
        {"title": "Company CEO resigns amid accounting investigation"},
    ]


@pytest.fixture
def mock_headlines_positive():
    return [
        {"title": "Company beats estimates with record revenue and raised guidance"},
    ]


@pytest.fixture
def mock_headlines_neutral():
    return [
        {"title": "Company holds annual general meeting"},
        {"title": "Market update: stocks mixed ahead of Fed decision"},
    ]


@pytest.fixture
def mock_macro_results():
    return {
        "Rare Earth Decoupling": [
            {"title": "China restricts rare earth exports, US scrambles for alternatives"}
        ],
        "AI Infrastructure": [
            {"title": "Hyperscalers announce record capex for data center buildout"}
        ],
    }
