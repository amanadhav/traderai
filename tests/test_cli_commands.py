"""
tests/test_cli_commands.py - Unit tests for trade-execution CLI subcommands.

These guard the highest-blast-radius code path: cmd_buy, cmd_sell, cmd_stop
all mutate positions.json. A bug here costs real money. Tests use
monkeypatched _load_data/_save_data so no real file I/O.

Coverage:
  cmd_buy        - new position, add to existing, weighted avg cost,
                   default position type, --stop / --type / --thesis flags
  cmd_sell       - partial sell, full close, oversell rejection, P&L log,
                   ticker-not-found rejection
  cmd_stop       - set stop on existing, ticker-not-found rejection
  _find_position - case insensitive lookup, missing account, missing ticker
"""
import pytest
from datetime import datetime

import cli_commands
from positions import _find_position


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_data():
    """In-memory positions.json shape with 2 ROTH + 1 TOD position."""
    return {
        "accounts": {
            "ROTH": {
                "id": "TEST_ROTH",
                "cash": 5000.00,
                "positions": [
                    {"ticker": "RTX", "shares": 6, "avg_cost": 173.36,
                     "stop": 147.00, "stop_type": "GTC Stop Market",
                     "stop_shares": 6, "type": "L",
                     "entry_date": "2026-04-15", "thesis": "Defense",
                     "notes": "", "pending_orders": []},
                    {"ticker": "MP", "shares": 7, "avg_cost": 60.58,
                     "stop": 51.49, "stop_type": "GTC Stop Market",
                     "stop_shares": 7, "type": "L",
                     "entry_date": "2026-04-01", "thesis": "Rare earth",
                     "notes": "", "pending_orders": []},
                ],
                "watchlist_orders": [],
            },
            "TOD": {
                "id": "TEST_TOD",
                "cash": 2000.00,
                "positions": [
                    {"ticker": "NVDA", "shares": 7, "avg_cost": 166.00,
                     "stop": None, "stop_type": None, "stop_shares": 0,
                     "type": "Lifetime", "entry_date": "2023-06-01",
                     "thesis": "AI", "notes": "", "pending_orders": []},
                ],
                "watchlist_orders": [],
            },
        },
        "watchlist": [],
    }


@pytest.fixture
def patched_io(monkeypatch, fake_data):
    """Replace _load_data + _save_data + log_trade with in-memory captures.
    Returns dict with `state`, `saves` (list of saved data snapshots),
    `trades` (list of logged trade events)."""
    state = {"data": fake_data}
    saves: list[dict] = []
    trades: list[dict] = []

    def fake_load():
        # Return the live state so mutations are visible
        return state["data"]

    def fake_save(data, console=None):
        # Just record the save; don't actually write
        saves.append({"shape": "saved",
                      "roth_positions": [p["ticker"] for p in data["accounts"]["ROTH"]["positions"]],
                      "tod_positions":  [p["ticker"] for p in data["accounts"]["TOD"]["positions"]]})

    def fake_log_trade(account, ticker, shares, avg_cost, sell_price, entry_date=None):
        trades.append({"account": account, "ticker": ticker, "shares": shares,
                       "avg_cost": avg_cost, "sell_price": sell_price,
                       "entry_date": entry_date,
                       "pl": round((sell_price - avg_cost) * shares, 2)})

    # Patch in cli_commands namespace (it imports these at module load)
    monkeypatch.setattr(cli_commands, "_load_data", fake_load)
    monkeypatch.setattr(cli_commands, "_save_data", lambda d: fake_save(d))
    monkeypatch.setattr(cli_commands, "log_trade",  fake_log_trade)

    return {"state": state, "saves": saves, "trades": trades}


# ── _find_position ──────────────────────────────────────────────────────────

class TestFindPosition:
    def test_finds_existing_position(self, fake_data):
        pos, pos_list = _find_position(fake_data, "ROTH", "RTX")
        assert pos is not None
        assert pos["ticker"] == "RTX"
        assert pos["shares"] == 6
        assert pos_list is fake_data["accounts"]["ROTH"]["positions"]

    def test_case_insensitive_ticker(self, fake_data):
        pos, _ = _find_position(fake_data, "ROTH", "rtx")
        assert pos is not None and pos["ticker"] == "RTX"

    def test_case_insensitive_account(self, fake_data):
        pos, _ = _find_position(fake_data, "roth", "RTX")
        assert pos is not None

    def test_missing_ticker_returns_none_and_position_list(self, fake_data):
        pos, pos_list = _find_position(fake_data, "ROTH", "FAKE")
        assert pos is None
        # pos_list still returned so caller can append a new position
        assert pos_list is fake_data["accounts"]["ROTH"]["positions"]

    def test_missing_account_returns_none_none(self, fake_data):
        pos, pos_list = _find_position(fake_data, "MARGIN", "RTX")
        assert pos is None and pos_list is None


# ── cmd_buy ─────────────────────────────────────────────────────────────────

class TestCmdBuy:
    def test_add_to_existing_position_weighted_avg(self, patched_io):
        """RTX already has 6sh @173.36. Add 4sh @160.00 → 10sh @ weighted avg."""
        cli_commands.cmd_buy(["ROTH", "RTX", "4", "160.00"])

        rtx = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                   if p["ticker"] == "RTX")
        assert rtx["shares"] == 10
        # weighted avg = (6*173.36 + 4*160) / 10 = 167.96
        expected_avg = round((6 * 173.36 + 4 * 160.00) / 10, 4)
        assert rtx["avg_cost"] == expected_avg
        assert len(patched_io["saves"]) == 1

    def test_add_with_new_stop_overrides(self, patched_io):
        cli_commands.cmd_buy(["ROTH", "RTX", "4", "160.00", "--stop", "150.00"])
        rtx = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                   if p["ticker"] == "RTX")
        assert rtx["stop"] == 150.00

    def test_new_position_default_type_spec_under_600(self, patched_io):
        """5sh × $100 = $500 < $600 → defaults to Spec type."""
        cli_commands.cmd_buy(["ROTH", "FAKE", "5", "100.00"])
        new_pos = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                       if p["ticker"] == "FAKE")
        assert new_pos["shares"] == 5
        assert new_pos["avg_cost"] == 100.00
        assert new_pos["type"] == "Spec"
        assert new_pos["entry_date"] == datetime.now().strftime("%Y-%m-%d")

    def test_new_position_default_type_long_above_600(self, patched_io):
        """5sh × $200 = $1000 > $600 → defaults to L."""
        cli_commands.cmd_buy(["ROTH", "FAKE", "5", "200.00"])
        new_pos = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                       if p["ticker"] == "FAKE")
        assert new_pos["type"] == "L"

    def test_new_position_explicit_type(self, patched_io):
        cli_commands.cmd_buy(["TOD", "FAKE", "1", "1000.00", "--type", "Lifetime"])
        new_pos = next(p for p in patched_io["state"]["data"]["accounts"]["TOD"]["positions"]
                       if p["ticker"] == "FAKE")
        assert new_pos["type"] == "Lifetime"

    def test_new_position_with_stop_sets_stop_shares(self, patched_io):
        cli_commands.cmd_buy(["ROTH", "FAKE", "4", "100.00", "--stop", "85.00"])
        new_pos = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                       if p["ticker"] == "FAKE")
        assert new_pos["stop"] == 85.00
        assert new_pos["stop_shares"] == 4
        assert new_pos["stop_type"] == "GTC Stop Market"

    def test_new_position_no_stop(self, patched_io):
        cli_commands.cmd_buy(["TOD", "FAKE", "1", "1000.00"])
        new_pos = next(p for p in patched_io["state"]["data"]["accounts"]["TOD"]["positions"]
                       if p["ticker"] == "FAKE")
        assert new_pos["stop"] is None
        assert new_pos["stop_shares"] == 0

    def test_thesis_recorded(self, patched_io):
        cli_commands.cmd_buy(["TOD", "FAKE", "1", "100", "--thesis", "AI play"])
        new_pos = next(p for p in patched_io["state"]["data"]["accounts"]["TOD"]["positions"]
                       if p["ticker"] == "FAKE")
        assert new_pos["thesis"] == "AI play"

    def test_invalid_type_rejected(self, patched_io):
        with pytest.raises(SystemExit):
            # argparse choices=[...] rejects "X"
            cli_commands.cmd_buy(["ROTH", "FAKE", "1", "100", "--type", "X"])


# ── cmd_sell ────────────────────────────────────────────────────────────────

class TestCmdSell:
    def test_partial_sell_logs_pl_and_reduces_shares(self, patched_io):
        """RTX 6sh @173.36. Sell 2sh @180. Pos becomes 4sh, log gain."""
        cli_commands.cmd_sell(["ROTH", "RTX", "2", "180.00"])
        rtx = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                   if p["ticker"] == "RTX")
        assert rtx["shares"] == 4
        # P&L = (180 - 173.36) * 2 = +13.28
        assert len(patched_io["trades"]) == 1
        trade = patched_io["trades"][0]
        assert trade["ticker"] == "RTX"
        assert trade["shares"] == 2
        assert trade["sell_price"] == 180.00
        assert trade["pl"] == round((180 - 173.36) * 2, 2)

    def test_full_close_removes_position(self, patched_io):
        """Selling all shares removes the position entirely from the account."""
        cli_commands.cmd_sell(["TOD", "NVDA", "7", "200.00"])
        tod_tickers = [p["ticker"] for p in
                       patched_io["state"]["data"]["accounts"]["TOD"]["positions"]]
        assert "NVDA" not in tod_tickers
        # Trade still logged
        assert len(patched_io["trades"]) == 1
        assert patched_io["trades"][0]["ticker"] == "NVDA"
        assert patched_io["trades"][0]["pl"] == round((200 - 166) * 7, 2)

    def test_oversell_rejected_no_save(self, patched_io):
        """Sell 10sh of position with 6sh → reject, no save, no log."""
        cli_commands.cmd_sell(["ROTH", "RTX", "10", "180.00"])
        rtx = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                   if p["ticker"] == "RTX")
        assert rtx["shares"] == 6  # unchanged
        assert len(patched_io["saves"]) == 0
        assert len(patched_io["trades"]) == 0

    def test_unknown_ticker_rejected(self, patched_io):
        cli_commands.cmd_sell(["ROTH", "ZZZZ", "1", "100.00"])
        assert len(patched_io["saves"]) == 0
        assert len(patched_io["trades"]) == 0

    def test_loss_recorded_correctly(self, patched_io):
        """Sell at loss → pl is negative, still logged."""
        cli_commands.cmd_sell(["ROTH", "MP", "3", "55.00"])  # buy 60.58, sell 55
        trade = patched_io["trades"][0]
        assert trade["pl"] == round((55.00 - 60.58) * 3, 2)
        assert trade["pl"] < 0


# ── cmd_stop ────────────────────────────────────────────────────────────────

class TestCmdStop:
    def test_set_stop_on_existing_full_shares(self, patched_io):
        """Set stop on RTX, default to current shares (6)."""
        cli_commands.cmd_stop(["ROTH", "RTX", "150.00"])
        rtx = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                   if p["ticker"] == "RTX")
        assert rtx["stop"] == 150.00
        assert rtx["stop_shares"] == 6
        assert rtx["stop_type"] == "GTC Stop Market"
        assert len(patched_io["saves"]) == 1

    def test_set_stop_with_custom_shares(self, patched_io):
        """Set stop on subset of shares."""
        cli_commands.cmd_stop(["ROTH", "RTX", "150.00", "4"])
        rtx = next(p for p in patched_io["state"]["data"]["accounts"]["ROTH"]["positions"]
                   if p["ticker"] == "RTX")
        assert rtx["stop"] == 150.00
        assert rtx["stop_shares"] == 4

    def test_unknown_ticker_rejected(self, patched_io):
        cli_commands.cmd_stop(["ROTH", "ZZZZ", "100"])
        assert len(patched_io["saves"]) == 0
