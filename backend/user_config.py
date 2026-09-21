"""
user_config.py - Per-user configuration for TraderAI.

Everything that used to be one person's hardcoded rules lives here as a
config file (user_config.json, gitignored) with presets. The engine modules
(score.py, action_engine.py, ai_analyst.py) read live values through
get_config() / rule(); the DEFAULTS preserve the original system's behavior
exactly, so an un-onboarded install behaves like the classic system.

Schema (user_config.json):
  profile     - name, experience, risk_tolerance, horizon_years, objective
  preset      - which preset the rules started from
  rules       - every tunable trading rule (see DEFAULT_RULES)
  accounts    - [{name, policy, stops_required, sector_limits}]
                policy: active | lifetime | income | spec
  narratives  - macro narrative keys the user tracks (subset of score.ACTIVE_NARRATIVES)
  ai          - briefing_tone (terse|detailed), recommendation_style (explicit|suggestive)
  appearance  - theme (dark|light)
  paper_mode  - bool, portfolio is simulated
  onboarded   - bool, wizard completed
"""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CONFIG_FILE = BASE / "user_config.json"

_lock = threading.Lock()
_cache: dict | None = None

# ── Rule defaults = the original system's exact behavior ─────────────────────

DEFAULT_RULES = {
    # Entry scoring thresholds (score.py signal labels + action gating)
    "score_entry_threshold": 70,
    "score_strong_threshold": 110,
    "score_conviction_threshold": 140,
    # Risk discipline
    "max_risk_per_trade_pct": 1.5,     # % of account equity risked per trade
    "max_portfolio_heat_pct": 8.0,     # total open risk across positions
    "max_drawdown_pct": 15.0,          # hard stop from peak equity
    "max_position_pct": 20.0,          # single position as % of account
    "max_positions": 30,
    "cash_floor_pct": 0.0,             # never deploy below this cash %
    # Stops
    "default_stop_pct": 15.0,          # default stop distance for new buys
    "stop_style": "fixed_pct",         # fixed_pct | trailing | none
    # Behavior
    "earnings_blackout_days": 15,      # never add within N days of earnings
    "averaging_down": "only_high_score",  # never | only_high_score | allowed
    "min_add_signals": 2,              # signals required before an ADD fires
    # Risk engine (ATR-based)
    "atr_stop_multiple": 2.0,          # stop = entry - N x ATR(14) when stop_style=atr
    "reward_risk_target": 2.0,         # take-profit at N x risk distance
    "swing_max_hold_days": 60,         # flag Swing (S) positions held longer than this
}

# Generic starter: one active account. Users define their real accounts
# (any names, any count) in the setup wizard.
DEFAULT_ACCOUNTS = [
    {"name": "MAIN", "policy": "active", "stops_required": True,
     "sector_limits": {}},
]

DEFAULTS = {
    "profile": {"name": "", "experience": "intermediate",
                "risk_tolerance": "balanced", "horizon_years": 10,
                "objective": "balanced"},
    "preset": "balanced_swing",
    "rules": DEFAULT_RULES,
    "accounts": DEFAULT_ACCOUNTS,
    "narratives": [],          # empty = all narratives active (classic behavior)
    "etf_watchlist": ["SPY", "QQQ", "IWM", "GLD", "XLE", "XLU", "SMH"],
    "ai": {"briefing_tone": "terse", "recommendation_style": "explicit",
           "model_tier": "budget",      # budget = Haiku everywhere | quality = Sonnet for reasoning
           "daily_budget_usd": 1.0},    # hard daily cap on AI spend
    "appearance": {"theme": "dark"},
    "paper_mode": False,
    "onboarded": False,
}

# ── Presets - starting points the wizard offers ──────────────────────────────

PRESETS = {
    "conservative_income": {
        "label": "Conservative Income",
        "description": "Capital preservation and dividends. Tight stops, low heat, no speculation.",
        "rules": {**DEFAULT_RULES,
                  "score_entry_threshold": 90,
                  "max_risk_per_trade_pct": 0.5,
                  "max_portfolio_heat_pct": 4.0,
                  "max_drawdown_pct": 8.0,
                  "max_position_pct": 10.0,
                  "default_stop_pct": 8.0,
                  "cash_floor_pct": 15.0,
                  "earnings_blackout_days": 21,
                  "averaging_down": "never",
                  "min_add_signals": 3},
    },
    "balanced_swing": {
        "label": "Balanced Swing",
        "description": "The classic TraderAI ruleset - swing trades with stops plus long-term compounders.",
        "rules": dict(DEFAULT_RULES),
    },
    "aggressive_growth": {
        "label": "Aggressive Growth",
        "description": "Higher heat, wider stops, faster adds. For experienced traders comfortable with drawdowns.",
        "rules": {**DEFAULT_RULES,
                  "score_entry_threshold": 60,
                  "max_risk_per_trade_pct": 2.0,
                  "max_portfolio_heat_pct": 12.0,
                  "max_drawdown_pct": 25.0,
                  "max_position_pct": 30.0,
                  "default_stop_pct": 20.0,
                  "earnings_blackout_days": 7,
                  "averaging_down": "allowed",
                  "min_add_signals": 1},
    },
    "spec_hunter": {
        "label": "Spec Hunter",
        "description": "Small-cap and pre-profit names. Strict runway/dilution discipline, small position sizes.",
        "rules": {**DEFAULT_RULES,
                  "score_entry_threshold": 60,
                  "max_risk_per_trade_pct": 1.0,
                  "max_portfolio_heat_pct": 6.0,
                  "max_position_pct": 8.0,
                  "default_stop_pct": 25.0,
                  "earnings_blackout_days": 15,
                  "averaging_down": "never",
                  "min_add_signals": 2},
    },
}

# Maps the wizard's risk-tolerance answer to a starting preset
TOLERANCE_TO_PRESET = {
    "conservative": "conservative_income",
    "balanced": "balanced_swing",
    "aggressive": "aggressive_growth",
    "speculative": "spec_hunter",
}


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_config(refresh: bool = False) -> dict:
    """Full config: DEFAULTS overlaid with user_config.json. Cached per process."""
    global _cache
    with _lock:
        if _cache is not None and not refresh:
            return _cache
        user = {}
        if CONFIG_FILE.exists():
            try:
                user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                user = {}
        _cache = _merge(DEFAULTS, user)
        return _cache


def save_config(update: dict) -> dict:
    """Merge `update` into the stored config, persist, refresh cache."""
    global _cache
    with _lock:
        current = {}
        if CONFIG_FILE.exists():
            try:
                current = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        # accounts and narratives are replaced wholesale, not merged element-wise
        merged = _merge(current, update)
        for key in ("accounts", "narratives", "etf_watchlist"):
            if key in update:
                merged[key] = update[key]
        CONFIG_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        _cache = None
    return get_config()


def rule(name: str):
    """Read one trading rule with default fallback - the engine's entry point."""
    return get_config()["rules"].get(name, DEFAULT_RULES.get(name))


def account_policy(account_name: str) -> dict:
    """Policy dict for an account name; sensible default when unknown."""
    for a in get_config()["accounts"]:
        if a["name"] == account_name:
            return a
    return {"name": account_name, "policy": "active", "stops_required": True,
            "sector_limits": {}}


def lifetime_accounts() -> set[str]:
    return {a["name"] for a in get_config()["accounts"] if a["policy"] == "lifetime"}


def active_narratives(all_narratives: dict[str, str]) -> dict[str, str]:
    """User-selected subset of narratives; empty selection = all (classic)."""
    chosen = get_config().get("narratives") or []
    if not chosen:
        return all_narratives
    return {k: v for k, v in all_narratives.items() if k in chosen}
