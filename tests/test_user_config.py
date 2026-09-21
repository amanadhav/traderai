"""Tests for user_config.py and its integration with the engine."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import user_config


@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    f = tmp_path / "user_config.json"
    monkeypatch.setattr(user_config, "CONFIG_FILE", f)
    user_config._cache = None
    yield f
    user_config._cache = None


def test_defaults_without_file(tmp_config):
    cfg = user_config.get_config(refresh=True)
    assert cfg["onboarded"] is False
    assert cfg["rules"]["earnings_blackout_days"] == 15
    assert cfg["rules"]["score_entry_threshold"] == 70
    assert {a["name"] for a in cfg["accounts"]} == {"MAIN"}


def test_save_and_merge(tmp_config):
    user_config.save_config({"rules": {"earnings_blackout_days": 7}, "onboarded": True})
    cfg = user_config.get_config(refresh=True)
    assert cfg["rules"]["earnings_blackout_days"] == 7
    # untouched rules keep defaults
    assert cfg["rules"]["score_entry_threshold"] == 70
    assert cfg["onboarded"] is True


def test_accounts_replaced_wholesale(tmp_config):
    user_config.save_config({"accounts": [{"name": "MAIN", "policy": "active",
                                           "stops_required": True, "sector_limits": {}}]})
    cfg = user_config.get_config(refresh=True)
    assert [a["name"] for a in cfg["accounts"]] == ["MAIN"]


def test_rule_helper_fallback(tmp_config):
    assert user_config.rule("earnings_blackout_days") == 15
    assert user_config.rule("nonexistent_rule") is None


def test_account_policy_lookup(tmp_config):
    assert user_config.account_policy("MAIN")["policy"] == "active"
    unknown = user_config.account_policy("MYSTERY")
    assert unknown["policy"] == "active"


def test_lifetime_accounts(tmp_config):
    assert user_config.lifetime_accounts() == set()
    user_config.save_config({"accounts": [
        {"name": "LT", "policy": "lifetime", "stops_required": False, "sector_limits": {}}]})
    assert user_config.lifetime_accounts() == {"LT"}


def test_active_narratives_empty_means_all(tmp_config):
    all_n = {"a": "x", "b": "y"}
    assert user_config.active_narratives(all_n) == all_n
    user_config.save_config({"narratives": ["a"]})
    assert user_config.active_narratives(all_n) == {"a": "x"}


def test_presets_are_complete():
    for key, preset in user_config.PRESETS.items():
        assert set(preset["rules"]) == set(user_config.DEFAULT_RULES), key
        assert preset["label"] and preset["description"]
    # every tolerance answer maps to a real preset
    for preset_key in user_config.TOLERANCE_TO_PRESET.values():
        assert preset_key in user_config.PRESETS


def test_corrupt_config_falls_back_to_defaults(tmp_config):
    tmp_config.write_text("{not json", encoding="utf-8")
    cfg = user_config.get_config(refresh=True)
    assert cfg["rules"]["score_entry_threshold"] == 70


# ── Engine integration ────────────────────────────────────────────────────────

def test_score_uses_config_blackout(tmp_config):
    import score as sc
    snap = {"ticker": "TEST", "price": 100.0, "rsi": 50, "days_to_earnings": 10,
            "debt_to_equity": 50, "free_cash_flow": 1e9, "market_cap": 1e11}
    # default 15-day blackout → 10 days out is disqualified
    r = sc.score_ticker(dict(snap))
    assert r.disqualified and "10 days" in r.disqualify_reason
    # aggressive 7-day blackout → 10 days out is allowed
    user_config.save_config({"rules": {"earnings_blackout_days": 7}})
    r2 = sc.score_ticker(dict(snap))
    assert not r2.disqualified


def test_score_signal_uses_config_thresholds(tmp_config):
    import score as sc
    snap = {"ticker": "TEST", "price": 100.0, "rsi": 50,
            "debt_to_equity": 50, "free_cash_flow": 1e9, "market_cap": 1e11}
    base = sc.score_ticker(dict(snap))
    # force an absurdly low entry threshold → same score becomes at least candidate
    user_config.save_config({"rules": {"score_entry_threshold": 0}})
    r = sc.score_ticker(dict(snap))
    assert r.signal in ("candidate", "strong", "high_conviction")
    assert base.total == r.total  # thresholds change labels, never the score
