"""Tests for the portfolio setup endpoint and cash deposit/withdraw modes."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with positions.json redirected to a temp file."""
    import persistence
    import morning_run as mr
    import api
    pos_file = tmp_path / "positions.json"
    monkeypatch.setattr(persistence, "POSITIONS_FILE", pos_file)
    monkeypatch.setattr(mr, "POSITIONS_FILE", pos_file)
    monkeypatch.setenv("TRADING_API_TOKEN", "test-token")
    monkeypatch.setattr(api, "_API_TOKEN", "test-token")
    from fastapi.testclient import TestClient
    return TestClient(api.app)


def test_fresh_install_returns_empty_portfolio(client):
    r = client.get("/api/positions")
    assert r.status_code == 200
    assert r.json()["accounts"] == {}


def test_setup_creates_portfolio(client):
    r = client.post("/api/setup/portfolio", json={"accounts": [
        {"name": "roth ira", "cash": 5000,
         "positions": [{"ticker": "aapl", "shares": 10, "avg_cost": 150.5}]},
        {"name": "BROKERAGE", "cash": 250.555, "positions": []},
    ]})
    assert r.status_code == 200
    data = client.get("/api/positions").json()
    assert set(data["accounts"]) == {"ROTH_IRA", "BROKERAGE"}
    assert data["accounts"]["BROKERAGE"]["cash"] == 250.56  # rounded
    pos = data["accounts"]["ROTH_IRA"]["positions"][0]
    assert pos["ticker"] == "AAPL" and pos["shares"] == 10
    assert pos["type"] == "L"  # default


def test_setup_requires_accounts(client):
    assert client.post("/api/setup/portfolio", json={"accounts": []}).status_code == 400


def test_setup_skips_invalid_positions(client):
    client.post("/api/setup/portfolio", json={"accounts": [
        {"name": "A", "cash": 100, "positions": [
            {"ticker": "", "shares": 5, "avg_cost": 10},      # no ticker
            {"ticker": "OK", "shares": 0, "avg_cost": 10},    # zero shares
            {"ticker": "GOOD", "shares": 1, "avg_cost": 10},
        ]},
    ]})
    positions = client.get("/api/positions").json()["accounts"]["A"]["positions"]
    assert [p["ticker"] for p in positions] == ["GOOD"]


def test_setup_locked_after_onboarding(client, tmp_path, monkeypatch):
    import user_config
    monkeypatch.setattr(user_config, "CONFIG_FILE", tmp_path / "cfg.json")
    user_config._cache = None
    user_config.save_config({"onboarded": True})
    body = {"accounts": [{"name": "X", "cash": 1, "positions": []}]}
    assert client.post("/api/setup/portfolio", json=body).status_code == 401
    # with the token it works even after onboarding
    r = client.post("/api/setup/portfolio", json=body,
                    headers={"X-API-Token": "test-token"})
    assert r.status_code == 200


def _seed(client):
    client.post("/api/setup/portfolio", json={"accounts": [
        {"name": "MAIN", "cash": 1000, "positions": []}]})


def test_cash_deposit_and_withdraw(client):
    _seed(client)
    h = {"X-API-Token": "test-token"}
    r = client.post("/api/cash", json={"account": "MAIN", "amount": 500, "mode": "deposit"}, headers=h)
    assert r.status_code == 200 and r.json()["cash"] == 1500.0
    r = client.post("/api/cash", json={"account": "MAIN", "amount": 200, "mode": "withdraw"}, headers=h)
    assert r.status_code == 200 and r.json()["cash"] == 1300.0


def test_cash_overdraw_blocked(client):
    _seed(client)
    h = {"X-API-Token": "test-token"}
    r = client.post("/api/cash", json={"account": "MAIN", "amount": 99999, "mode": "withdraw"}, headers=h)
    assert r.status_code == 400
    assert "insufficient" in r.json()["detail"]


def test_cash_set_and_bad_mode(client):
    _seed(client)
    h = {"X-API-Token": "test-token"}
    r = client.post("/api/cash", json={"account": "MAIN", "amount": 42, "mode": "set"}, headers=h)
    assert r.json()["cash"] == 42.0
    r = client.post("/api/cash", json={"account": "MAIN", "amount": 1, "mode": "bogus"}, headers=h)
    assert r.status_code == 400
    r = client.post("/api/cash", json={"account": "MAIN", "amount": -5, "mode": "deposit"}, headers=h)
    assert r.status_code == 400


def test_search_tickers_empty_query_no_network(client):
    r = client.get("/api/search-tickers?q=")
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_search_tickers_filters_and_shapes(client, monkeypatch):
    import api

    class FakeResp:
        def json(self):
            return {"quotes": [
                {"symbol": "NVDA", "shortname": "NVIDIA Corporation",
                 "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
                {"symbol": "NVDA24C", "shortname": "some option",
                 "exchDisp": "OPR", "quoteType": "OPTION"},   # filtered out
                {"shortname": "no symbol", "quoteType": "EQUITY"},  # filtered out
            ]}

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp())
    r = client.get("/api/search-tickers?q=nvidia")
    results = r.json()["results"]
    assert results == [{"symbol": "NVDA", "name": "NVIDIA Corporation",
                        "exchange": "NASDAQ", "type": "EQUITY"}]
