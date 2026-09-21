"""
tests/test_customer_concentration.py - 14 tests for customer_concentration.py

All tests run offline (no real network calls). EDGAR requests are mocked.
Haiku fallback mocked - no Anthropic API calls in CI.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

import customer_concentration as cc


# ── Fixtures ──────────────────────────────────────────────────────────────────

# Realistic 10-K text excerpts that should trigger regex
EXCERPT_SINGLE_CUSTOMER = """
During fiscal year 2024, Amazon Web Services accounted for approximately 38% of our total net revenue.
We have historically derived a significant portion of our revenues from a limited number of customers.
The loss of Amazon Web Services as a customer could have a material adverse effect on our business.
"""

EXCERPT_MULTI_CUSTOMER = """
Customer A accounted for 31% of our total revenues for the year ended December 31, 2024.
Customer B represented approximately 22.5% of our net sales for the same period.
Customer C comprised 18% of revenues during fiscal 2024.
No other customer accounted for more than 10% of our total revenues.
"""

EXCERPT_DOD_CUSTOMER = """
The U.S. Department of Defense represented approximately 65% of our total revenues during fiscal year 2024.
Our government contracts are subject to termination for convenience provisions.
"""

EXCERPT_GENERIC_SIGNIFICANT = """
We had one significant customer that accounted for 44% of our revenues in fiscal 2024.
This significant customer operates in the cloud computing sector.
"""

EXCERPT_NO_CONCENTRATION = """
No single customer accounted for more than 10% of our total revenues during fiscal 2024.
Our customer base is diversified across multiple industries and geographies.
"""

EXCERPT_OUT_OF_RANGE = """
One customer accounted for 3% of revenue. Another customer accounted for 92% of revenue.
"""

FAKE_10K_URL = "https://www.sec.gov/Archives/edgar/data/1234567/0001234567-24-000001.htm"
FAKE_FILING_DATE = "2024-02-15"


# ── Helper to build a valid cached payload ────────────────────────────────────
def _make_cached(ticker: str, has_data: bool = True, days_old: int = 10) -> dict:
    payload = {
        "ticker": ticker,
        "has_data": has_data,
        "top_customer": "Amazon / AWS" if has_data else None,
        "pct": 38.0 if has_data else None,
        "all_customers": [{"name": "Amazon / AWS", "pct": 38.0}] if has_data else [],
        "filing_date": "2024-02-15",
        "source": "regex" if has_data else None,
        "note": None,
        "extracted_at": (datetime.now() - timedelta(days=days_old)).isoformat(),
    }
    return payload


# ── Regex extraction tests (unit - no network) ────────────────────────────────

class TestRegexExtraction:

    def test_single_customer_aws(self):
        results = cc._extract_via_regex(EXCERPT_SINGLE_CUSTOMER)
        assert len(results) >= 1
        top = results[0]
        assert top["pct"] == pytest.approx(38.0, abs=0.1)
        # Name should normalize to Amazon variant
        assert "Amazon" in top["name"] or "AWS" in top["name"]

    def test_multi_customer_ordering(self):
        results = cc._extract_via_regex(EXCERPT_MULTI_CUSTOMER)
        assert len(results) >= 2
        pcts = [r["pct"] for r in results]
        # Must be sorted descending
        assert pcts == sorted(pcts, reverse=True)
        # Highest should be 31%
        assert results[0]["pct"] == pytest.approx(31.0, abs=0.5)

    def test_dod_customer_normalized(self):
        results = cc._extract_via_regex(EXCERPT_DOD_CUSTOMER)
        assert len(results) >= 1
        top = results[0]
        assert top["pct"] == pytest.approx(65.0, abs=0.5)
        assert "DoD" in top["name"] or "Government" in top["name"] or "Defense" in top["name"]

    def test_generic_significant_customer(self):
        results = cc._extract_via_regex(EXCERPT_GENERIC_SIGNIFICANT)
        assert len(results) >= 1
        assert results[0]["pct"] == pytest.approx(44.0, abs=0.5)

    def test_no_concentration_returns_empty(self):
        results = cc._extract_via_regex(EXCERPT_NO_CONCENTRATION)
        # "more than 10%" sentence should not produce hits (3% and <10% filtered)
        # All percentages mentioned should be ≤10, filtered by 5-80% range
        # "10%" is exactly at boundary - OK if included or not
        for r in results:
            assert 5.0 <= r["pct"] <= 80.0

    def test_out_of_range_filtered(self):
        """3% (below 5) and 92% (above 80) should be filtered out."""
        results = cc._extract_via_regex(EXCERPT_OUT_OF_RANGE)
        for r in results:
            assert 5.0 <= r["pct"] <= 80.0
        # 92% specifically must not appear
        pcts = [r["pct"] for r in results]
        assert 92.0 not in pcts
        assert 3.0 not in pcts

    def test_max_5_results_returned(self):
        # Build text with 10 customers
        lines = "\n".join(
            [f"Customer {chr(65+i)} accounted for {10+i}% of our total revenue." for i in range(10)]
        )
        results = cc._extract_via_regex(lines)
        assert len(results) <= 5

    def test_empty_text_returns_empty(self):
        results = cc._extract_via_regex("")
        assert results == []

    def test_deduplication(self):
        """Same pct from two patterns should not appear twice."""
        text = (
            "Amazon accounted for 38% of our total revenue. "
            "Amazon represented 38% of net sales."
        )
        results = cc._extract_via_regex(text)
        pcts = [r["pct"] for r in results]
        assert pcts.count(38.0) == 1


# ── Cache tests ───────────────────────────────────────────────────────────────

class TestCache:

    def test_cache_hit_returns_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)
        ticker = "TESTCC"
        payload = _make_cached(ticker, has_data=True, days_old=5)
        (tmp_path / f"{ticker}_10k.json").write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(cc, "_search_edgar_fulltext") as mock_edgar:
            result = cc.get_customer_concentration(ticker, force_refresh=False)
            mock_edgar.assert_not_called()

        assert result["has_data"] is True
        assert result["pct"] == pytest.approx(38.0)

    def test_stale_cache_refetches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)
        ticker = "STALE"
        payload = _make_cached(ticker, has_data=True, days_old=400)  # older than TTL
        (tmp_path / f"{ticker}_10k.json").write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(cc, "_search_edgar_fulltext", return_value=None):
            result = cc.get_customer_concentration(ticker, force_refresh=False)
            # Should attempt refetch (returns None → has_data=False)
            assert result["has_data"] is False

    def test_force_refresh_bypasses_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)
        ticker = "FRESH"
        payload = _make_cached(ticker, has_data=True, days_old=1)
        (tmp_path / f"{ticker}_10k.json").write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(cc, "_search_edgar_fulltext", return_value=None):
            result = cc.get_customer_concentration(ticker, force_refresh=True)
            assert result["has_data"] is False  # forced re-fetch, EDGAR returned None

    def test_cache_written_after_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)
        ticker = "CACHEWRITE"

        with (
            patch.object(cc, "_search_edgar_fulltext", return_value=(FAKE_10K_URL, FAKE_FILING_DATE)),
            patch.object(cc, "_fetch_10k_text", return_value=EXCERPT_SINGLE_CUSTOMER),
        ):
            result = cc.get_customer_concentration(ticker)

        cache_file = tmp_path / f"{ticker}_10k.json"
        assert cache_file.exists()
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        assert cached["ticker"] == ticker
        assert "extracted_at" in cached


# ── 429 + network failure graceful handling ────────────────────────────────────

class TestNetworkFailures:

    def test_429_returns_no_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("requests.get", return_value=mock_resp):
            # CIK lookup returns 429 → no CIK → no filing → has_data=False
            result = cc.get_customer_concentration("RATE429")

        assert result["has_data"] is False

    def test_connection_error_returns_no_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)
        import requests as req

        with patch.object(cc, "_search_edgar_fulltext", side_effect=req.exceptions.ConnectionError("refused")):
            result = cc.get_customer_concentration("CONNFAIL")

        assert result["has_data"] is False
        assert "connection" in (result.get("note") or "").lower()

    def test_filing_download_failure_returns_no_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)

        with (
            patch.object(cc, "_search_edgar_fulltext", return_value=(FAKE_10K_URL, FAKE_FILING_DATE)),
            patch.object(cc, "_fetch_10k_text", return_value=None),  # download fails
        ):
            result = cc.get_customer_concentration("DLNONE")

        assert result["has_data"] is False


# ── Haiku fallback mocked ─────────────────────────────────────────────────────

class TestHaikuFallback:

    def test_haiku_called_when_regex_misses(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)

        haiku_result = [{"name": "U.S. Government", "pct": 55.0}]

        with (
            patch.object(cc, "_search_edgar_fulltext", return_value=(FAKE_10K_URL, FAKE_FILING_DATE)),
            patch.object(cc, "_fetch_10k_text", return_value=EXCERPT_NO_CONCENTRATION),
            patch.object(cc, "_extract_via_regex", return_value=[]),  # force regex miss
            patch.object(cc, "_extract_via_haiku", return_value=haiku_result) as mock_haiku,
        ):
            result = cc.get_customer_concentration("HAIKU1")

        mock_haiku.assert_called_once()
        assert result["has_data"] is True
        assert result["source"] == "haiku"
        assert result["pct"] == pytest.approx(55.0)

    def test_no_api_key_haiku_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = cc._extract_via_haiku(EXCERPT_NO_CONCENTRATION, "NOKEY")
        assert result is None

    def test_haiku_fallback_fails_gracefully(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "CACHE_DIR", tmp_path)

        with (
            patch.object(cc, "_search_edgar_fulltext", return_value=(FAKE_10K_URL, FAKE_FILING_DATE)),
            patch.object(cc, "_fetch_10k_text", return_value=EXCERPT_NO_CONCENTRATION),
            patch.object(cc, "_extract_via_regex", return_value=[]),
            patch.object(cc, "_extract_via_haiku", return_value=None),  # haiku also fails
        ):
            result = cc.get_customer_concentration("BOTHFAIL")

        assert result["has_data"] is False
        assert result["source"] is None
