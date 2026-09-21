"""
test_news_sentiment.py - unit tests for news_sentiment.py.

Tests cover:
  - classify_ticker_news(): THESIS/MODERATE tiers, both directions
  - classify_macro_pulse(): ACTIVE/SILENT/NEUTRAL
  - Narrative keyword detection
  - explain_big_mover(): output format
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from news_sentiment import (
    classify_ticker_news,
    classify_macro_pulse,
    explain_big_mover,
)


# ── classify_ticker_news - THESIS NEGATIVE ────────────────────────────────────

def test_thesis_negative_ceo_resign():
    headlines = [{"title": "Company CEO resigns after fraud investigation revealed"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEGATIVE"
    assert r["strength"] == "THESIS"


def test_thesis_negative_fda_reject():
    headlines = [{"title": "FDA reject company's new drug application, shares fall"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEGATIVE"
    assert r["strength"] == "THESIS"


def test_thesis_negative_guidance_cut():
    headlines = [{"title": "Company issues profit warning and guidance cut for full year"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEGATIVE"
    assert r["strength"] == "THESIS"


def test_thesis_negative_class_action():
    headlines = [{"title": "Class action lawsuit filed against company for securities fraud"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEGATIVE"
    assert r["strength"] == "THESIS"


# ── classify_ticker_news - THESIS POSITIVE ────────────────────────────────────

def test_thesis_positive_earnings_beat():
    headlines = [{"title": "Company beat estimate with record revenue and raised guidance"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "POSITIVE"
    assert r["strength"] == "THESIS"


def test_thesis_positive_fda_approve():
    headlines = [{"title": "FDA approve new cancer drug, major milestone for company"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "POSITIVE"
    assert r["strength"] == "THESIS"


def test_thesis_positive_major_contract():
    headlines = [{"title": "Company wins billion contract with Department of Defense"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "POSITIVE"
    assert r["strength"] == "THESIS"


def test_thesis_positive_guidance_raise():
    headlines = [{"title": "Company raised guidance and outlook on strong demand"}]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "POSITIVE"
    assert r["strength"] == "THESIS"


# ── classify_ticker_news - MODERATE NEGATIVE ─────────────────────────────────

def test_moderate_negative_layoff():
    headlines = [
        {"title": "Company announces layoff of 1,000 employees"},
        {"title": "Analysts downgrade stock on weak demand outlook"},
    ]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEGATIVE"
    assert r["strength"] == "MODERATE"


def test_moderate_negative_downgrade():
    headlines = [
        {"title": "Goldman downgrades stock, cuts price target"},
        {"title": "Revenue miss estimate, weak guidance disappoints market"},
    ]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEGATIVE"


# ── classify_ticker_news - NEUTRAL ───────────────────────────────────────────

def test_neutral_empty_headlines():
    r = classify_ticker_news([], "TEST")
    assert r["signal"] == "NEUTRAL"
    assert r["headline_count"] == 0
    assert r["strength"] == "WEAK"


def test_neutral_no_keywords():
    headlines = [
        {"title": "Company holds annual general meeting in New York"},
        {"title": "Market update: stocks mixed ahead of economic data"},
    ]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEUTRAL"


def test_neutral_string_headlines():
    """Plain string headlines should work, not just dicts."""
    headlines = ["Company holds annual general meeting"]
    r = classify_ticker_news(headlines, "TEST")
    assert r["signal"] == "NEUTRAL"


# ── Narrative keyword detection ───────────────────────────────────────────────

def test_narrative_mention_rare_earth():
    headlines = [{"title": "MP Materials signs rare earth supply agreement with US DoD"}]
    r = classify_ticker_news(headlines, "MP", narratives=["rare_earth", "china_decoupling"])
    assert "rare_earth" in r["narrative_mention"]


def test_narrative_mention_ai_infra():
    headlines = [{"title": "NVDA GPU demand from hyperscalers hits record as AI training expands"}]
    r = classify_ticker_news(headlines, "NVDA", narratives=["ai_infra"])
    assert "ai_infra" in r["narrative_mention"]


def test_narrative_mention_defense():
    headlines = [{"title": "NATO countries increase defense spending on missile systems"}]
    r = classify_ticker_news(headlines, "RTX", narratives=["defense"])
    assert "defense" in r["narrative_mention"]


def test_narrative_mention_glp1():
    headlines = [{"title": "Ozempic semaglutide shows new benefits beyond weight loss"}]
    r = classify_ticker_news(headlines, "NVO", narratives=["glp1_obesity"])
    assert "glp1_obesity" in r["narrative_mention"]


def test_thesis_news_flag_when_narrative_mentioned():
    headlines = [{"title": "Rare earth supply disruption from China export ban"}]
    r = classify_ticker_news(headlines, "MP", narratives=["rare_earth"])
    assert r["thesis_news"] is True


# ── classify_macro_pulse ──────────────────────────────────────────────────────

def test_macro_pulse_active_single(mock_macro_results):
    """1 narrative covered → ACTIVE."""
    r = classify_macro_pulse("MP", ["rare_earth"], mock_macro_results)
    assert r["pulse"] == "ACTIVE"
    assert "rare_earth" in r["active_narratives"]


def test_macro_pulse_strong_multi(mock_macro_results):
    """2+ narratives covered → STRONG."""
    r = classify_macro_pulse("NVDA", ["ai_infra", "rare_earth"], mock_macro_results)
    assert r["pulse"] == "STRONG"
    assert len(r["active_narratives"]) >= 2


def test_macro_pulse_silent():
    """Narratives assigned but no coverage today → SILENT."""
    r = classify_macro_pulse("MP", ["rare_earth"], {})
    assert r["pulse"] == "SILENT"
    assert "rare_earth" in r["silent_narratives"]


def test_macro_pulse_neutral_no_narratives():
    """No narratives assigned → NEUTRAL."""
    r = classify_macro_pulse("AAPL", [], {})
    assert r["pulse"] == "NEUTRAL"


def test_macro_pulse_neutral_no_macro_key():
    """Narrative with no macro mapping → skipped, not counted as silent."""
    r = classify_macro_pulse("NVO", ["glp1_obesity"], {})
    # glp1_obesity maps to None → not tracked → NEUTRAL not SILENT
    assert r["pulse"] == "NEUTRAL"


# ── explain_big_mover ─────────────────────────────────────────────────────────

def test_explain_big_mover_up_catalyst():
    headlines = [{"title": "Company beat estimate with record revenue"}]
    result = explain_big_mover("NVDA", 3.5, headlines, ["ai_infra"])
    assert "NVDA" in result
    assert "UP" in result
    assert "3.5" in result


def test_explain_big_mover_down_thesis_risk():
    headlines = [{"title": "CEO resign amid fraud investigation"}]
    result = explain_big_mover("TEST", -4.2, headlines, [])
    assert "DOWN" in result
    assert "4.2" in result


def test_explain_big_mover_no_catalyst():
    headlines = [{"title": "Company holds routine investor day"}]
    result = explain_big_mover("TEST", 2.5, headlines, [])
    assert "No clear catalyst" in result or "catalyst" in result.lower()


def test_explain_big_mover_narrative_context():
    headlines = [{"title": "Rare earth supply disruption from China export restriction"}]
    result = explain_big_mover("MP", 5.0, headlines, ["rare_earth"])
    assert "rare" in result.lower() or "Macro" in result
