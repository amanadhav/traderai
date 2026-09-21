# TraderAI - Claude Code Instructions

Self-hosted AI trading intelligence platform. Python/FastAPI backend,
React 19 + shadcn/ui frontend, two-model AI layer (Claude + TypeSafe Jev).
Everything is per-user configurable - nothing about the portfolio, accounts,
or rules is hardcoded.

---

## GROUND TRUTH - READ FILES, NEVER GUESS

- `positions.json` - the user's portfolio (accounts, cash, positions). Gitignored.
- `user_config.json` - the user's rules, accounts, AI settings. Gitignored.
- `daily_brief.json` - stateless anchor written by every morning run. Re-read it
  whenever context is long or any recommendation is being made.
- `morning_run_log.txt` - full untruncated output of the last morning run.

**HARD RULE: never estimate or guess any price, RSI, or P&L. If a value is
missing, the fetch failed - say so.** Code = ground truth. Conversation =
unreliable cache.

## SESSION START

```bash
cat positions.json
cat daily_brief.json
cat user_config.json
```

If positions.json doesn't exist, this is a fresh install - the user onboards
through the web wizard (`/setup`), which creates it.

---

## ARCHITECTURE

| Layer | Files | Notes |
|---|---|---|
| Config | `user_config.py` | ALL trading rules, accounts, presets. The engine and AI prompts derive from it - never hardcode a rule. |
| Engine | `score.py`, `spec_score.py`, `action_engine.py`, `risk_engine.py`, `guardian.py` | Scoring (180-pt / 150-pt spec), action synthesis, ATR stops + risk sizing, rule compliance |
| Pipeline | `morning_run.py` → `persistence.py`, `data_fetch.py`, `positions.py`, `alerts_check.py` | Daily run; writes daily_brief.json + SQLite signal log |
| Data | `data_client.py` (fallback chain), `insider.py`, `options_flow.py`, `macro_data.py`, `transcripts.py`, `signal_store.py` | All free-tier sources |
| AI | `ai_client.py` (ONLY Anthropic entry point), `ai_analyst.py`, `jev_signals.py` | See AI LAYER below |
| Validation | `backtest.py`, `ml_calibrate.py`, `analyze_blocked.py` | Walk-forward + regime segmentation |
| API | `api.py` | Reads open (localhost), mutations token-auth, optional REQUIRE_READ_AUTH |
| Frontend | `frontend/` | Plain JSX, shadcn/ui, Tailwind v4, TanStack Query, monochrome theme (color = P&L only) |

## AI LAYER

| Feature | Where | Model policy |
|---------|-------|--------------|
| Morning briefing | `GET /api/briefing`, Briefing page | `model_for("briefing")` |
| Portfolio chat (11 tools) | `POST /api/chat`, Chat page | `model_for("chat")` |
| Bull/bear debate + judge | `GET /api/debate/{t}` | `model_for("debate"/"judge")` |
| Scan explanations | `GET /api/scan-explanations` | `model_for("explain")` |
| Jev typed probabilities | `jev_signals.py`, `GET /api/sentiment/{t}` | TypeSafe; falls back to keyword classifier |

**Rules that must never break:**
- Every Anthropic call goes through `ai_client.py` - it enforces the user's
  hard daily budget cap (`ai.daily_budget_usd`) and model tier. Never
  instantiate an Anthropic client anywhere else.
- The AI never states a number it didn't get from a tool or payload.
- Every AI feature degrades gracefully without keys.
- The system NEVER auto-executes trades. The user confirms at their broker.

## USER RULES DRIVE EVERYTHING

`user_config.rule(name)` is the engine's entry point for every tunable:
score thresholds, earnings blackout, risk %, stops, position caps, heat,
drawdown, hold limits. Defaults preserve classic behavior; presets in
`user_config.PRESETS`. When adding engine logic, pull limits from config -
never hardcode a number a user might reasonably want to change.

## PRE-EARNINGS PROTOCOL

For any held position with earnings within the user's blackout window, the
briefing must produce a decision card: bull case, bear case, current P&L,
explicit recommendation. The debate endpoint automates this on demand and
includes the latest earnings-call transcript when available.

## FILL PROTOCOL

When the user confirms a fill: update `positions.json` through the API or
`persistence` (always under `positions_lock()`), weighted avg cost on adds,
`log_trade` on sells. Commit with a `fill:` message if they ask.

## CLI REFERENCE

```bash
python backend/morning_run.py               # full daily pipeline (also scheduled weekdays 7:00)
python backend/score.py TICKER              # score (auto-routes spec names); --both for dual
python backend/scan_universe.py --quick     # universe scan
python backend/backtest.py --full --lookback 730 --hold 60 --save
python backend/ml_calibrate.py [--apply]    # threshold + walk-forward + regime report
python backend/insider.py / options_flow.py / etf_score.py / recap.py / dividends.py
pytest tests/ -q                    # 306 tests, offline
```

Server: `python -m uvicorn api:app --app-dir backend --reload --port 8000` + `cd frontend && npm run dev`.

## CONVENTIONS

- UTF-8 encoding on every file open/write (Windows compatibility).
- Tests are hermetic: conftest isolates `user_config`; no network in tests.
- Frontend: numbers get `tnum`, tickers `font-semibold`, monochrome except
  `text-gain`/`text-loss`/`text-warn`; data via TanStack Query.
- Never commit: `.env`, `positions.json`, `user_config.json`, any cache or
  data file matching .gitignore. Never reproduce account numbers or keys.
- SKILL.md and playbook.json are EXAMPLE strategy content (the "Balanced
  Swing" default playbook) - editable by users, not personal to anyone.
