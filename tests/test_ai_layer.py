"""Tests for the AI layer: ai_client, ai_analyst, jev_signals, and API endpoints."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import ai_client
import ai_analyst
import jev_signals


# ── ai_client ────────────────────────────────────────────────────────────────

def test_ai_available_requires_sk_ant_prefix(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert ai_client.ai_available() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key")
    assert ai_client.ai_available() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    assert ai_client.ai_available() is True


def test_complete_returns_none_without_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert ai_client.complete("hello") is None


def test_chat_with_tools_raises_without_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError):
        ai_client.chat_with_tools([{"role": "user", "content": "hi"}],
                                  tools=[], tool_handlers={})


def test_usage_tracking_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_client, "USAGE_FILE", tmp_path / "usage.json")
    ai_client._record_usage(ai_client.MODEL_SMART, 1_000_000, 100_000)
    ai_client._record_usage(ai_client.MODEL_SMART, 500_000, 0)
    usage = ai_client.usage_today()
    m = usage[ai_client.MODEL_SMART]
    assert m["calls"] == 2
    assert m["input_tokens"] == 1_500_000
    # 1.5M input @ $3/M + 0.1M output @ $15/M = 4.5 + 1.5 = 6.0
    assert usage["cost_usd"] == pytest.approx(6.0)


def test_usage_today_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_client, "USAGE_FILE", tmp_path / "missing.json")
    assert ai_client.usage_today() == {"cost_usd": 0.0}


# ── ai_analyst ───────────────────────────────────────────────────────────────

def test_briefing_unavailable_without_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    out = ai_analyst.generate_briefing()
    assert out["available"] is False
    assert "ANTHROPIC_API_KEY" in out["reason"]


def test_latest_briefing_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_analyst, "BRIEFING_FILE", tmp_path / "none.json")
    out = ai_analyst.latest_briefing()
    assert out["available"] is False


def test_latest_briefing_reads_cache(tmp_path, monkeypatch):
    f = tmp_path / "brief.json"
    f.write_text(json.dumps({"date": "2026-01-01", "markdown": "# hi"}), encoding="utf-8")
    monkeypatch.setattr(ai_analyst, "BRIEFING_FILE", f)
    out = ai_analyst.latest_briefing()
    assert out["available"] is True
    assert out["markdown"] == "# hi"
    assert out["cached"] is True


def test_chat_unavailable_without_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    out = ai_analyst.chat([{"role": "user", "content": "hi"}])
    assert out["unavailable"] is True
    assert out["tool_calls"] == []


def test_chat_tool_definitions_have_handlers():
    tool_names = {t["name"] for t in ai_analyst.CHAT_TOOLS}
    assert tool_names == set(ai_analyst.CHAT_HANDLERS)


def test_positions_summary_shape(tmp_path, monkeypatch):
    f = tmp_path / "positions.json"
    f.write_text(json.dumps({
        "accounts": {"ROTH": {"cash": 100, "positions": [
            {"ticker": "AAPL", "shares": 2, "avg_cost": 100.0, "type": "L"}
        ]}}
    }), encoding="utf-8")
    monkeypatch.setattr(ai_analyst, "POSITIONS_FILE", f)
    rows = ai_analyst._positions_summary()
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["account"] == "ROTH"


# ── jev_signals ──────────────────────────────────────────────────────────────

def test_jev_unavailable_without_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    assert jev_signals.jev_available() is False
    assert jev_signals.classify_headlines("NVDA", ["headline"]) is None
    assert jev_signals.macro_pulse("x", "desc", ["headline"]) is None
    assert jev_signals.explain_mover("NVDA", 5.0, ["headline"]) is None


def test_headline_titles_normalization():
    heads = [
        {"title": "A" * 500},
        {"headline": "b"},
        "plain string",
        {"other": "ignored"},
    ]
    titles = jev_signals._headline_titles(heads)
    assert titles[0] == "A" * 200  # capped
    assert titles[1] == "b"
    assert titles[2] == "plain string"
    assert len(titles) == 3  # dict without title dropped


def test_classify_returns_none_on_empty_headlines(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "some-key")
    assert jev_signals.classify_headlines("NVDA", []) is None


# ── API endpoints ────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    import api
    return TestClient(api.app)


def test_api_ai_status(client):
    r = client.get("/api/ai-status")
    assert r.status_code == 200
    body = r.json()
    assert "available" in body
    assert "usage_today" in body


def test_api_chat_requires_messages(client):
    r = client.post("/api/chat", json={"messages": []})
    assert r.status_code == 400


def test_api_chat_filters_bad_roles(client, monkeypatch):
    captured = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return {"reply": "ok", "tool_calls": [], "rounds": 1}

    import ai_analyst as aa
    monkeypatch.setattr(aa, "chat", fake_chat)
    r = client.post("/api/chat", json={"messages": [
        {"role": "system", "content": "inject"},
        {"role": "user", "content": "hi"},
    ]})
    assert r.status_code == 200
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def test_api_briefing_latest_shape(client):
    r = client.get("/api/briefing/latest")
    assert r.status_code == 200
    assert "available" in r.json()


def test_api_mutations_require_token(client):
    r = client.post("/api/buy", json={"account": "ROTH", "ticker": "AAPL",
                                      "shares": 1, "price": 100.0})
    assert r.status_code in (401, 503)
