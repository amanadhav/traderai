"""Tests for risk_engine, guardian, macro cache, ml_calibrate walk-forward,
and the AI budget guard. All offline - no network."""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import ai_client
import guardian
import risk_engine
import user_config


# ── risk_engine ───────────────────────────────────────────────────────────────

def test_stop_fixed_pct_default():
    out = risk_engine.suggest_stop(100.0, atr=None)
    assert out["stop"] == 85.0  # default 15%


def test_stop_atr_style(monkeypatch):
    user_config.save_config({"rules": {"stop_style": "atr", "atr_stop_multiple": 2.0}})
    out = risk_engine.suggest_stop(100.0, atr=3.0)
    assert out["stop"] == 94.0
    assert "ATR" in out["basis"]


def test_stop_atr_falls_back_without_atr(monkeypatch):
    user_config.save_config({"rules": {"stop_style": "atr"}})
    out = risk_engine.suggest_stop(100.0, atr=None)
    assert out["stop"] == 85.0  # falls back to fixed pct


def test_stop_style_none():
    user_config.save_config({"rules": {"stop_style": "none"}})
    assert risk_engine.suggest_stop(100.0, 2.0)["stop"] is None


def test_position_size_risk_based():
    # equity 10k, risk 1.5% = $150 budget; entry 100 stop 90 → $10/share → 15 shares
    user_config.save_config({"rules": {"max_risk_per_trade_pct": 1.5, "max_position_pct": 50}})
    out = risk_engine.position_size(10000, 100.0, 90.0)
    assert out["shares"] == 15
    assert out["capped_by"] == "risk budget"


def test_position_size_cap_binds():
    # risk budget alone would allow 100 shares, but 10% cap = $1000 → 10 shares
    user_config.save_config({"rules": {"max_risk_per_trade_pct": 10, "max_position_pct": 10}})
    out = risk_engine.position_size(10000, 100.0, 90.0)
    assert out["shares"] == 10
    assert out["capped_by"] == "position cap"


def test_build_trade_setup_math():
    user_config.save_config({"rules": {"stop_style": "fixed_pct", "default_stop_pct": 10,
                                       "reward_risk_target": 2.0,
                                       "max_risk_per_trade_pct": 1.0, "max_position_pct": 100}})
    snap = {"ticker": "TEST", "price": 100.0, "atr": 2.5, "atr_pct": 2.5}
    s = risk_engine.build_trade_setup(snap, 10000)
    assert s["stop"] == 90.0
    assert s["target"] == 120.0  # entry + 2 x $10 risk
    assert s["shares"] == 10     # $100 budget / $10 per-share risk
    assert s["dollar_risk"] == 100.0
    assert s["dollar_reward"] == 200.0


def test_stale_positions():
    user_config.save_config({"rules": {"swing_max_hold_days": 30}})
    old = (date.today() - timedelta(days=45)).isoformat()
    fresh = (date.today() - timedelta(days=5)).isoformat()
    data = {"accounts": {"A": {"positions": [
        {"ticker": "OLD", "type": "S", "entry_date": old, "shares": 1, "avg_cost": 1},
        {"ticker": "NEW", "type": "S", "entry_date": fresh, "shares": 1, "avg_cost": 1},
        {"ticker": "LT", "type": "Lifetime", "entry_date": old, "shares": 1, "avg_cost": 1},
    ]}}}
    stale = risk_engine.stale_positions(data)
    assert [s["ticker"] for s in stale] == ["OLD"]


# ── guardian ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def portfolio():
    return {"accounts": {
        "ROTH": {"cash": 100, "positions": [
            {"ticker": "BIG", "shares": 10, "avg_cost": 100, "stop": None, "type": "L"},
            {"ticker": "OK", "shares": 1, "avg_cost": 50, "stop": 45, "type": "L"},
        ]},
    }}


def test_guardian_position_cap_and_stops(portfolio):
    user_config.save_config({"rules": {"max_position_pct": 20, "cash_floor_pct": 0,
                                       "max_portfolio_heat_pct": 100}})
    prices = {"BIG": {"price": 100}, "OK": {"price": 50}}
    v = guardian.check_all(portfolio, prices)
    rules = {x["rule"] for x in v}
    assert "max_position_pct" in rules       # BIG is ~87% of account
    assert "stop_required" in rules          # BIG has no stop (ROTH default policy requires)
    urgent = [x for x in v if x["rule"] == "stop_required"]
    assert urgent[0]["severity"] == "URGENT"


def test_guardian_cash_floor(portfolio):
    user_config.save_config({"rules": {"cash_floor_pct": 50, "max_position_pct": 100,
                                       "max_portfolio_heat_pct": 100}})
    prices = {"BIG": {"price": 100}, "OK": {"price": 50}}
    v = guardian.check_all(portfolio, prices)
    assert any(x["rule"] == "cash_floor" for x in v)


def test_guardian_drawdown():
    user_config.save_config({"rules": {"max_drawdown_pct": 10}})
    data = {"accounts": {"A": {"cash": 800, "positions": []}}}
    history = [{"total": 1000}, {"total": 950}]
    v = guardian.check_all(data, {}, history)
    dd = [x for x in v if x["rule"] == "max_drawdown"]
    assert dd and dd[0]["severity"] == "URGENT"


def test_guardian_clean_portfolio():
    user_config.save_config({"rules": {"max_position_pct": 90, "cash_floor_pct": 0,
                                       "max_portfolio_heat_pct": 100, "max_drawdown_pct": 99}})
    data = {"accounts": {"A": {"cash": 500, "positions": [
        {"ticker": "OK", "shares": 1, "avg_cost": 50, "stop": 45, "type": "L"},
    ]}}}
    assert guardian.check_all(data, {"OK": {"price": 50}}, [{"total": 550}]) == []


# ── macro cache ───────────────────────────────────────────────────────────────

def test_macro_uses_fresh_cache(tmp_path, monkeypatch):
    import macro_data
    cache = tmp_path / "macro.json"
    payload = {"_fetched": time.time(), "yield_10y": 4.5, "regime_note": "cached"}
    cache.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(macro_data, "CACHE", cache)
    out = macro_data.get_macro()
    assert out["regime_note"] == "cached"  # no network hit


# ── ml_calibrate walk-forward ────────────────────────────────────────────────

def test_walk_forward_detects_regime_flip():
    import ml_calibrate
    # 100 train entries where score>=50 wins big, 40 test entries where it loses
    entries = []
    for i in range(100):
        entries.append({"entry_date": f"2025-01-{(i % 28) + 1:02d}", "tech_score": 60,
                        "alpha": 5.0, "win": True})
    for i in range(40):
        entries.append({"entry_date": f"2026-06-{(i % 28) + 1:02d}", "tech_score": 60,
                        "alpha": -8.0, "win": False})
    wf = ml_calibrate.walk_forward(entries)
    assert wf["available"]
    assert wf["train_median_alpha"] > 0
    assert wf["test_median_alpha"] < 0  # the curve-fit warning case


def test_to_live_scale():
    import ml_calibrate
    assert ml_calibrate.to_live_scale(70) == 114
    assert ml_calibrate.to_live_scale(110) == 180


# ── ai budget guard ──────────────────────────────────────────────────────────

def test_budget_guard_blocks_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(ai_client, "USAGE_FILE", tmp_path / "usage.json")
    user_config.save_config({"ai": {"daily_budget_usd": 0.01}})
    # simulate spend past the cap
    ai_client._record_usage(ai_client.MODEL_SMART, 10_000, 1_000)
    assert ai_client.budget_exceeded() is True
    assert ai_client.complete("hi") is None
    with pytest.raises(RuntimeError, match="budget"):
        ai_client.chat_with_tools([{"role": "user", "content": "hi"}], tools=[], tool_handlers={})


def test_model_tier_selection():
    user_config.save_config({"ai": {"model_tier": "budget"}})
    assert ai_client.model_for("briefing") == ai_client.MODEL_FAST
    assert ai_client.model_for("classify") == ai_client.MODEL_FAST
    user_config.save_config({"ai": {"model_tier": "quality"}})
    assert ai_client.model_for("briefing") == ai_client.MODEL_SMART
    assert ai_client.model_for("chat") == ai_client.MODEL_SMART
    assert ai_client.model_for("explain") == ai_client.MODEL_FAST
