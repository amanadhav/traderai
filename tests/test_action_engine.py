"""
tests/test_action_engine.py - Tests for action item generators.

v2 = original 5-signal engine (used by no live caller after v2/v3 fork fix).
v3 = full 6-signal synthesis engine (used by morning_run, html_render, api).

Test coverage:
  - Output schema (v2 keys, v3 superset with 'signals')
  - Priority sort order (URGENT > ACTION > WATCH > INFO)
  - Market-wide signals (VIX, SPY RSI, QQQ RSI thresholds)
  - Numbering (post-sort)
  - Empty/missing-data inputs don't crash
"""
import pytest

from action_engine import (
    generate_action_items_v2,
    generate_action_items_v3,
    _PRIO_ORDER,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def empty_data():
    return {"accounts": {"ROTH": {"positions": [], "watchlist_orders": []},
                         "TOD":  {"positions": [], "watchlist_orders": []}},
            "watchlist": []}


@pytest.fixture
def two_positions_data():
    return {
        "accounts": {
            "ROTH": {
                "positions": [
                    {"ticker": "RTX", "shares": 6, "avg_cost": 173.36,
                     "stop": 147.00, "type": "L", "thesis": "Defense",
                     "pending_orders": []},
                ],
                "watchlist_orders": [],
            },
            "TOD": {
                "positions": [
                    {"ticker": "NVDA", "shares": 7, "avg_cost": 166.00,
                     "stop": None, "type": "Lifetime", "thesis": "AI",
                     "pending_orders": []},
                ],
                "watchlist_orders": [],
            },
        },
        "watchlist": [],
    }


@pytest.fixture
def normal_market_snaps():
    """VIX 15, SPY 50 RSI, QQQ 50 RSI - quiet market, no market-wide alerts."""
    return {
        "^VIX": {"price": 15.0},
        "SPY":  {"rsi": 50.0, "price": 500.0},
        "QQQ":  {"rsi": 50.0, "price": 450.0},
    }


@pytest.fixture
def normal_snapshots():
    return {
        "RTX": {"price": 180.0, "rsi": 50.0, "days_to_earnings": 60,
                "ma200": 170.0, "vol_ratio": 1.0, "pct_chg_today": 0.5,
                "macd_improving": True, "bb_pct": 50},
        "NVDA": {"price": 200.0, "rsi": 50.0, "days_to_earnings": 60,
                 "ma200": 180.0, "vol_ratio": 1.0, "pct_chg_today": 0.5,
                 "macd_improving": True, "bb_pct": 50},
    }


# ── v2 schema + sort order ──────────────────────────────────────────────────

class TestV2Schema:
    def test_returns_list(self, empty_data, normal_market_snaps):
        items = generate_action_items_v2(empty_data, {}, None,
                                          normal_market_snaps, {})
        assert isinstance(items, list)

    def test_each_item_has_required_keys(self, two_positions_data,
                                         normal_snapshots, normal_market_snaps):
        items = generate_action_items_v2(two_positions_data, normal_snapshots,
                                          None, normal_market_snaps, {})
        required = {"priority", "ticker", "account", "verb", "detail", "color", "num"}
        for item in items:
            assert required.issubset(item.keys()), \
                f"item missing keys: {required - item.keys()}"

    def test_items_numbered_starting_at_1(self, two_positions_data,
                                           normal_snapshots, normal_market_snaps):
        items = generate_action_items_v2(two_positions_data, normal_snapshots,
                                          None, normal_market_snaps, {})
        if items:
            assert items[0]["num"] == 1
            for i, item in enumerate(items, start=1):
                assert item["num"] == i


# ── Market-wide signals ─────────────────────────────────────────────────────

class TestMarketRegime:
    def _vix_only(self, vix):
        return {"^VIX": {"price": vix}, "SPY": {"rsi": 50.0},
                "QQQ": {"rsi": 50.0}}

    def test_vix_extreme_fires_urgent(self, empty_data):
        ms = self._vix_only(40)
        items = generate_action_items_v2(empty_data, {}, None, ms, {})
        urgent = [i for i in items if i["priority"] == "URGENT"]
        assert any("REDUCE" in i["verb"] for i in urgent)

    def test_vix_elevated_fires_watch(self, empty_data):
        ms = self._vix_only(28)
        items = generate_action_items_v2(empty_data, {}, None, ms, {})
        watch = [i for i in items if i["priority"] == "WATCH"
                 and "REDUCE" in i["verb"]]
        assert len(watch) >= 1

    def test_vix_normal_no_alert(self, empty_data, normal_market_snaps):
        items = generate_action_items_v2(empty_data, {}, None,
                                          normal_market_snaps, {})
        # No VIX-related alerts in normal regime
        assert not any("VIX" in i.get("detail", "") for i in items)

    def test_spy_overbought(self, empty_data):
        ms = {"^VIX": {"price": 15}, "SPY": {"rsi": 80.0}, "QQQ": {"rsi": 50}}
        items = generate_action_items_v2(empty_data, {}, None, ms, {})
        assert any("OVERBOUGHT" in i["verb"] for i in items)

    def test_spy_oversold_action(self, empty_data):
        ms = {"^VIX": {"price": 15}, "SPY": {"rsi": 25.0}, "QQQ": {"rsi": 50}}
        items = generate_action_items_v2(empty_data, {}, None, ms, {})
        oversold_actions = [i for i in items if i["priority"] == "ACTION"
                            and "OVERSOLD" in i["verb"]]
        assert len(oversold_actions) == 1
        assert oversold_actions[0]["color"] == "green"

    def test_qqq_overbought_separate_signal(self, empty_data):
        ms = {"^VIX": {"price": 15}, "SPY": {"rsi": 50}, "QQQ": {"rsi": 80.0}}
        items = generate_action_items_v2(empty_data, {}, None, ms, {})
        assert any("TECH OVERBOUGHT" in i["verb"] for i in items)


# ── Sort order ──────────────────────────────────────────────────────────────

class TestSortOrder:
    def test_urgent_before_action_before_watch(self, empty_data):
        """Craft market state hitting all 3 priorities, verify ordering."""
        ms = {
            "^VIX": {"price": 40.0},   # URGENT (REDUCE 50%)
            "SPY":  {"rsi": 25.0},      # ACTION (OVERSOLD)
            "QQQ":  {"rsi": 80.0},      # WATCH (TECH OVERBOUGHT)
        }
        items = generate_action_items_v2(empty_data, {}, None, ms, {})
        priorities = [i["priority"] for i in items]
        # Verify ordering monotonically non-decreasing per _PRIO_ORDER
        ranks = [_PRIO_ORDER[p] for p in priorities]
        assert ranks == sorted(ranks), \
            f"Not sorted by priority: got {priorities}"

    def test_prio_order_constants(self):
        """Ordering: URGENT(0) < ACTION(1) < WATCH(2) < INFO(3)."""
        assert _PRIO_ORDER["URGENT"] < _PRIO_ORDER["ACTION"]
        assert _PRIO_ORDER["ACTION"] < _PRIO_ORDER["WATCH"]
        assert _PRIO_ORDER["WATCH"]  < _PRIO_ORDER["INFO"]


# ── v3 schema (superset of v2) ──────────────────────────────────────────────

class TestV3Schema:
    """v3 returns same shape as v2 plus 'signals' field - required for
    backward compat with React frontend that reads v2 keys."""

    def test_v3_returns_list(self, empty_data, normal_market_snaps):
        items = generate_action_items_v3(empty_data, {}, None,
                                          normal_market_snaps, {})
        assert isinstance(items, list)

    def test_v3_items_have_v2_keys_plus_signals(self, empty_data):
        ms = {"^VIX": {"price": 40}, "SPY": {"rsi": 50}, "QQQ": {"rsi": 50}}
        items = generate_action_items_v3(empty_data, {}, None, ms, {})
        assert items, "VIX>35 should produce at least one item"
        v2_keys = {"priority", "ticker", "account", "verb", "detail", "color"}
        for item in items:
            assert v2_keys.issubset(item.keys())
            assert "signals" in item, "v3 must add 'signals' field"

    def test_v3_market_regime_matches_v2(self, empty_data):
        """Same VIX → both engines fire the same URGENT verb."""
        ms = {"^VIX": {"price": 40}, "SPY": {"rsi": 50}, "QQQ": {"rsi": 50}}
        v2 = generate_action_items_v2(empty_data, {}, None, ms, {})
        v3 = generate_action_items_v3(empty_data, {}, None, ms, {})
        v2_urgent = [i["verb"] for i in v2 if i["priority"] == "URGENT"]
        v3_urgent = [i["verb"] for i in v3 if i["priority"] == "URGENT"]
        assert v2_urgent == v3_urgent

    def test_v3_handles_missing_optional_signals(self, empty_data,
                                                  normal_market_snaps):
        """v3 should not crash when insider/options/news/macro are None."""
        items = generate_action_items_v3(
            empty_data, {}, None, normal_market_snaps, {},
            insider_signals=None, options_flows=None,
            ticker_news=None, macro_results=None,
        )
        assert isinstance(items, list)


# ── Empty/None inputs don't crash ───────────────────────────────────────────

class TestRobustness:
    def test_v2_handles_none_market_snaps(self, empty_data):
        items = generate_action_items_v2(empty_data, {}, None, None, None)
        assert isinstance(items, list)

    def test_v2_handles_none_pattern_results(self, two_positions_data,
                                              normal_snapshots,
                                              normal_market_snaps):
        items = generate_action_items_v2(two_positions_data, normal_snapshots,
                                          None, normal_market_snaps, None)
        assert isinstance(items, list)

    def test_v2_handles_empty_snapshots(self, two_positions_data,
                                         normal_market_snaps):
        """Position with no live snapshot - should fall back gracefully."""
        items = generate_action_items_v2(two_positions_data, {},
                                          None, normal_market_snaps, {})
        assert isinstance(items, list)

    def test_v3_handles_none_market_snaps(self, empty_data):
        items = generate_action_items_v3(empty_data, {}, None, None, None)
        assert isinstance(items, list)
