"""Tests for signal_store (SQLite) and transcripts caching - offline."""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import signal_store
import transcripts


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(signal_store, "DB_FILE", tmp_path / "signals.db")


def test_record_and_query(tmp_db):
    snaps = {"NVDA": {"price": 100.0, "rsi": 40.0, "atr_pct": 2.0,
                      "pct_chg_today": 1.0, "days_to_earnings": 30}}
    n = signal_store.record_day(snaps, day="2026-01-02")
    assert n == 1
    rows = signal_store.history("NVDA")
    assert rows[0]["date"] == "2026-01-02"
    assert rows[0]["rsi"] == 40.0


def test_record_is_idempotent_per_day(tmp_db):
    snaps = {"NVDA": {"price": 100.0}}
    signal_store.record_day(snaps, day="2026-01-02")
    signal_store.record_day({"NVDA": {"price": 101.0}}, day="2026-01-02")
    rows = signal_store.history("NVDA")
    assert len(rows) == 1
    assert rows[0]["price"] == 101.0  # upsert replaced


def test_skips_tickers_without_price(tmp_db):
    n = signal_store.record_day({"BAD": {"error": "no data"}}, day="2026-01-02")
    assert n == 0


def test_guardian_log_replaced_per_day(tmp_db):
    v = [{"severity": "WARN", "rule": "r", "ticker": "T", "account": "A", "message": "m"}]
    signal_store.record_day({"NVDA": {"price": 1.0}}, guardian_violations=v, day="2026-01-02")
    signal_store.record_day({"NVDA": {"price": 1.0}}, guardian_violations=v, day="2026-01-02")
    log = signal_store.guardian_history()
    assert len([x for x in log if x["date"] == "2026-01-02"]) == 1


def test_stats(tmp_db):
    signal_store.record_day({"A": {"price": 1.0}, "B": {"price": 2.0}}, day="2026-01-02")
    signal_store.record_day({"A": {"price": 1.1}}, day="2026-01-03")
    s = signal_store.stats()
    assert s["days_recorded"] == 2
    assert s["rows"] == 3
    assert s["tickers"] == 2
    assert s["since"] == "2026-01-02"


def test_transcript_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "CACHE_DIR", tmp_path)
    cached = {"_fetched": time.time(), "ticker": "AAPL", "year": 2026,
              "quarter": 3, "excerpt": "hello world", "full_length": 11}
    (tmp_path / "AAPL.json").write_text(json.dumps(cached), encoding="utf-8")
    out = transcripts.get_transcript_excerpt("AAPL")
    assert out["excerpt"] == "hello world"  # served from cache, no network


def test_transcript_cached_miss_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "CACHE_DIR", tmp_path)
    (tmp_path / "ZZZZ.json").write_text(
        json.dumps({"_fetched": time.time(), "ticker": "ZZZZ"}), encoding="utf-8")
    assert transcripts.get_transcript_excerpt("ZZZZ") is None
