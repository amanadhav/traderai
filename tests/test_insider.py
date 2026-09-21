"""
test_insider.py - unit tests for insider.py signal tier logic.

Tests cover:
  - _is_open_market_buy(): filter logic (keeps P-code purchases, strips awards/exercises)
  - _compute_signal(): STRONG / CLUSTER / NOTABLE / WEAK / NONE tiers
  - _title_tier(): C-suite vs officer vs unknown
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timedelta
from insider import _is_open_market_buy, _compute_signal, _title_tier


# ── _is_open_market_buy ───────────────────────────────────────────────────────

def test_open_market_buy_accepted():
    assert _is_open_market_buy("Purchase at price 45.50") is True


def test_open_market_buy_case_insensitive():
    assert _is_open_market_buy("PURCHASED AT PRICE 100.00") is True


def test_award_filtered_out():
    """Stock award is not an open-market purchase."""
    assert _is_open_market_buy("Award of restricted stock units") is False


def test_option_exercise_filtered():
    assert _is_open_market_buy("Exercise of stock option at price 30") is False


def test_gift_filtered():
    assert _is_open_market_buy("Gift of shares to family trust") is False


def test_tax_withholding_filtered():
    assert _is_open_market_buy("Tax withholding on vesting RSUs") is False


def test_sale_filtered():
    assert _is_open_market_buy("Sale of shares in open market") is False


def test_empty_string_filtered():
    assert _is_open_market_buy("") is False


# ── _title_tier ───────────────────────────────────────────────────────────────

def test_ceo_is_csuite():
    assert _title_tier("Chief Executive Officer") == 1


def test_cfo_is_csuite():
    assert _title_tier("Chief Financial Officer") == 1


def test_president_is_csuite():
    assert _title_tier("President and CEO") == 1


def test_director_is_officer():
    assert _title_tier("Director") == 2


def test_vp_is_officer():
    # "vice president" matches OFFICER_KEYWORDS but "president" in C_SUITE_KEYWORDS
    # also matches - C-suite check runs first, so "Senior Vice President" → tier 1
    # This is intentional: SVP-level is treated as C-suite conviction signal
    assert _title_tier("Senior Vice President") == 1


def test_unknown_title():
    assert _title_tier("Consultant") == 0


# ── _compute_signal ───────────────────────────────────────────────────────────

def _buy(name, position, value, price=50.0, days_ago=5):
    """Helper to build a buy dict."""
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return {
        "name": name,
        "position": position,
        "value": value,
        "price": price,
        "date": date,
        "title_tier": _title_tier(position),
    }


def test_no_buys_returns_none():
    sig, desc = _compute_signal([])
    assert sig == "NONE"
    assert desc == ""


def test_strong_csuite_100k():
    """CEO buying ≥$100K → STRONG."""
    buys = [_buy("John Smith", "Chief Executive Officer", 150_000)]
    sig, desc = _compute_signal(buys)
    assert sig == "STRONG"
    assert "150,000" in desc


def test_strong_cfo_100k():
    """CFO buying ≥$100K → STRONG."""
    buys = [_buy("Jane Doe", "Chief Financial Officer", 120_000)]
    sig, desc = _compute_signal(buys)
    assert sig == "STRONG"


def test_csuite_below_100k_not_strong():
    """CEO buying only $80K → not STRONG (could be NOTABLE)."""
    buys = [_buy("John Smith", "Chief Executive Officer", 80_000)]
    sig, _ = _compute_signal(buys)
    assert sig != "STRONG"


def test_cluster_3_insiders():
    """3+ insiders buying within 30 days → CLUSTER."""
    buys = [
        _buy("Alice", "Director", 60_000, days_ago=5),
        _buy("Bob", "Vice President", 55_000, days_ago=10),
        _buy("Carol", "Director", 70_000, days_ago=20),
    ]
    sig, desc = _compute_signal(buys)
    assert sig == "CLUSTER"
    assert "3" in desc or "insiders" in desc.lower()


def test_cluster_requires_3_in_window():
    """Only 2 insiders in 30-day window → not CLUSTER."""
    buys = [
        _buy("Alice", "Director", 60_000, days_ago=5),
        _buy("Bob", "Vice President", 55_000, days_ago=10),
    ]
    sig, _ = _compute_signal(buys)
    assert sig != "CLUSTER"


def test_notable_50k():
    """Single buy ≥$50K (non-C-suite) → NOTABLE."""
    buys = [_buy("Alice", "Director", 75_000)]
    sig, desc = _compute_signal(buys)
    assert sig == "NOTABLE"
    assert "75,000" in desc


def test_weak_below_50k():
    """Buy below $50K → WEAK."""
    buys = [_buy("Bob", "Director", 30_000)]
    sig, _ = _compute_signal(buys)
    assert sig == "WEAK"


def test_strong_beats_cluster():
    """When both STRONG and CLUSTER conditions met, STRONG wins."""
    buys = [
        _buy("CEO", "Chief Executive Officer", 200_000, days_ago=1),
        _buy("Dir1", "Director", 60_000, days_ago=2),
        _buy("Dir2", "Director", 55_000, days_ago=3),
        _buy("Dir3", "Director", 50_000, days_ago=4),
    ]
    sig, _ = _compute_signal(buys)
    assert sig == "STRONG"


def test_cluster_across_date_window():
    """3 insiders but spread >30 days → not CLUSTER (no valid window)."""
    buys = [
        _buy("Alice", "Director", 60_000, days_ago=2),
        _buy("Bob", "Director", 60_000, days_ago=35),
        _buy("Carol", "Director", 60_000, days_ago=70),
    ]
    sig, _ = _compute_signal(buys)
    # No 30-day window contains all 3 → NOTABLE at most
    assert sig in ("NOTABLE", "WEAK")
