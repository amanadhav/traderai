# TraderAI - Roadmap

Single source of truth for what's shipped, what's pending, and what's next.
Update on every meaningful commit. Future Claude sessions: read this first before suggesting work.

---

## Last updated
2026-09-21

## Current state
- 180-pt entry algorithm (score.py) with falling-knife guard + sector-narrative coverage
- 150-pt spec algorithm (spec_score.py) for pre-FCF / small-cap names + $5B-$50B growth carve-out
- 5-factor ETF algorithm (etf_score.py)
- Backtest infrastructure (backtest.py + analyze_blocked.py) - 730d × 96-ticker validation
- 182 tests passing
- Universe: 343 tickers (327 base + 16 from Google watchlists)

## Latest backtest verdict (2026-05-09, post-refactor)
| Hold | Tier | Med α (no guard) | Med α (guard) | Δ | n |
|------|------|------------------|---------------|---|---|
| 60d | ≥30/110 | +1.01% | +1.63% | +0.62pp ↑ | 637 |
| 60d | ≥50/110 | +2.95% | **+13.98%** | **+11.03pp ↑** ⭐ | 233 |
| 60d | ≥65/110 | +2.95% | **+13.99%** | **+11.04pp ↑** ⭐ | 61 |

All tiers positive pre-guard now. Sample sizes ~2x prior (universe expansion + recent rally window). Refactor (steps 1-3) had zero structural impact - improvement is market data, not code.

Prior verdict (2026-05-08, pre-refactor, 1207 entries):
- ≥50/110 60d: -2.82% → +2.16% (+4.98pp). Same guard, different window.

---

## Shipped

### 2026-09-21 (batch 3) - Research-sourced features + cost controls
- [x] AI budget guard: hard daily spend cap + model tiers (budget=Haiku default / quality=Sonnet) in ai_client + Settings
- [x] risk_engine.py: ATR stops, risk-based sizing, structured trade setups, stale-swing detection (+ATR in snapshots)
- [x] guardian.py: discipline compliance vs user rules (caps, stops, cash floor, heat, drawdown, time exits)
- [x] macro_data.py: yield curve via yfinance ($0) + optional FRED (CPI/Fed/unemployment), 24h cache
- [x] ml_calibrate: walk-forward validation (caught threshold-50 as curve-fit) + bull/bear regime segmentation (>=70 robust in both)
- [x] ai_analyst: earnings_debate (bull/bear/judge), explain_scan_candidates, 4 new chat tools (trade setup, discipline, macro, run_backtest)
- [x] API: /api/trade-setup, /api/guardian, /api/macro, /api/chart/{t}, /api/debate/{t}, /api/scan-explanations; parallel /api/prices; optional REQUIRE_READ_AUTH
- [x] Frontend: ticker chart dialog w/ stop line + trade setup, macro + guardian dashboard cards, scan AI explanations, trades churn monitor, debate UI, new settings fields
- [x] 17 new tests (289 total)

### 2026-09-21 (later) - Personalization + remaining roadmap
- [x] user_config.py - per-user profile/accounts/rules/narratives/AI behavior, 4 presets, engine + AI prompts config-driven
- [x] Setup wizard (5 steps, tolerance→preset mapping) + Settings page + onboarding gate + theme + PAPER badge
- [x] Backtest UI (run/status/results endpoints + page with tier table and alpha chart)
- [x] positions_lock() file locking on all mutations; reset-portfolio endpoint
- [x] ml_calibrate.py - logistic win-prob fit + threshold sweep, --apply writes to config
- [x] conftest isolates user_config per test; 272 tests passing
- Deferred: SQLite migration (JSON + locking is adequate single-user), async routes/WebSockets, auth on read endpoints

### 2026-09-21 - TraderAI overhaul: Windows + shadcn/ui + AI layer
- [x] Windows compatibility: UTF-8 file I/O everywhere, cross-platform open, npm.cmd, UTF-8 stdout
- [x] Packaging: pyproject.toml, requirements.txt, .gitattributes, .env template
- [x] Frontend rebuilt on Tailwind v4 + shadcn/ui (monochrome neutral dark theme): sidebar shell, header market bar, all 13 pages converted, TanStack Query
- [x] AI layer: ai_client.py (model tiers, usage/cost tracking), ai_analyst.py (AI morning briefing with pre-earnings decision cards; portfolio chat with 7 tools)
- [x] jev_signals.py: TypeSafe Jev typed judgments (thesis-negative/positive, narrative pulse, mover explanation) - pending live test, typesafe.ai was down
- [x] New endpoints: /api/briefing, /api/briefing/latest, /api/chat, /api/ai-status, /api/sentiment/{ticker}
- [x] New pages: Briefing, Chat
- [x] Fixes: ScoreResult.disqualify_reason 500 in /api/score, change_pct alias in /api/prices, secrets.compare_digest token check
- [x] 19 new AI-layer tests - 261 total passing

### 2026-05-09 - community_score.py shipped (Reddit + YouTube + combiner)
- [x] `community_reddit.py` (275L) - public JSON endpoints, 6h cache, Haiku sentiment
- [x] `community_youtube.py` (362L) - Data API v3, 24h cache, channel allowlist tiers (a/b/c)
- [x] `community_score.py` (322L) - combiner, display-only v1, forward log for 60d validation
- [x] data_fetch.load_env bug fix (setdefault skipped empty-string env vars)

Design: Q1 display-only, Q2 WSB-fade RSI-gated, Q3 absence penalty whitelist-gated.
Live test: AMD 22/100 (RSI 80.7 = euphoric fade), RKLB/NVDA 44/100 (mature).

### 2026-05-09 - morning_run.py split COMPLETE (steps 1-9 of 9)

**All 9 modules extracted. morning_run.py: 4440 → 786 lines (-82%).**

| Module | Lines | Functions |
|--------|-------|-----------|
| `persistence.py` | 388 | _load_data, _save_data, write_daily_brief, record_portfolio_snapshot, log_trade + path constants |
| `data_fetch.py` | 335 | yfinance helpers, RSI/MACD/BB, earnings detection, news, market indicators, dividend calendar |
| `positions.py` | 192 | load_positions, all_tickers, all_pending_orders, calc_pnl, check_gtc_proximity, check_probable_fills, _find_position |
| `alerts_check.py` | 335 | detect_order_fills, check_watchlist_entries, print_probable_fills_terminal, print_watchlist_terminal, print_lead_indicators_terminal |
| `terminal_ui.py` | 281 | print_header, print_positions_table, print_market_indicators, print_news_section, print_patterns_section, print_alerts, print_action_items_terminal, _gamma_walls_str |
| `action_engine.py` | 821 | generate_action_items_v2, generate_action_items_v3, render_action_items_html, _PRIO_ORDER |
| `html_render.py` | 1362 | POSITION_MACRO, generate_daily_read, render_daily_read_html, generate_html, _build_html |
| `cli_commands.py` | 342 | cmd_buy/sell/stop/score/positions/scan/news/breadth/server/help |
| `morning_run.py` | 786 | run() orchestrator + back-compat re-exports for api.py/data_client.py |

**Validation:** 182 tests pass. Structural fingerprint matched baseline at every step (22 positions, 5 actions, 4 watchlist). Final backtest gate: tier alphas unchanged from pre-refactor.

Bonus tooling shipped: `refactor_validate.py` (structural fingerprint replaces text-diff), `refactor_baseline.json` (locked baseline).

### 2026-05-08 - Backtest day
- [x] backtest.py - 730d historical validation, CSV cache, 96-ticker default
- [x] analyze_blocked.py - bootstrap CI hypothesis test for guard effectiveness
- [x] Falling-knife guard in score.py (soft -10pt penalty, not hard cap)
- [x] SECTOR_NARRATIVES dict - narrative coverage 32% → ~70% via industry defaults
- [x] Doc cleanup: 6 stale "130-pt" → "180-pt" references (incl. GitHub repo description)
- [x] 16 tickers from Google watchlists added to universe (327 → 343)
- [x] $5B-$50B growth carve-out in is_spec_candidate (RKLB-gap fix) - `morning_run.py` snapshot now exposes `revenue_growth`, `total_cash`, `operating_cashflow`, `industry`, `sector`

### Earlier
- [x] spec_score.py - 150-pt algorithm for pre-profit names (no FCF disqualifier)
- [x] customer_concentration.py - SEC EDGAR 10-K parser, annual cache
- [x] Tests: test_spec_score, test_customer_concentration, test_score_router

---

## Pending - ordered by leverage

### 1. ~~morning_run.py split~~ ✅ COMPLETE 2026-05-09
Shipped all 9 steps in single session. See "Shipped 2026-05-09" entry above.

### 2. ~~community_score.py - YouTube + Reddit signals~~ ✅ COMPLETE 2026-05-09
Shipped 3 modules: `community_reddit.py`, `community_youtube.py`, `community_score.py`.
v1 = display-only per design (Q1). 60d forward log written to `data/community_cache/_forward_log.jsonl` for post-hoc validation. Promote to additive after observation.

WSB-fade RSI gate working (AMD 22/100 due to RSI 80.7 → -20 fade triggered).
Tech-creator absence penalty whitelist-gated to consumer-facing sectors.

### 3. ~~innovation_score.py - arXiv + USPTO signals~~ ✅ COMPLETE 2026-05-09 (v1)
Shipped `innovation_arxiv.py` + `innovation_score.py`. Sparse-by-design - only frontier-tech tickers in 35-entry ARXIV_SEARCH_TERMS map score; rest correctly return has_data=False.

Live test: GOOGL 90/100 (DeepMind firehose), IONQ 80/100 (quantum), MSFT/META 50/100, NVDA 0 (search term too narrow - v1.1).

USPTO patent signal: deferred to v1.1. PatentsView API redesigned 2024 - non-trivial setup. arXiv signal alone meaningful for eligible tickers.

Mode flag `INNOVATION_MODE = "display_only"` per pluggable design.

### 4. ~~narrative_score.py - combiner~~ ✅ COMPLETE 2026-05-09
SignalLayer schema locked. Lead-time-aware aggregation: structural→1.0, mid→0.7, near→0.5/0.3.

Pluggable mode flags per user directive 2026-05-09:
- `NARRATIVE_MODE`  = "display_only" | "additive" | "gate" | "disabled"
- `COMMUNITY_MODE`  = "display_only" (controls how community signal contributes)
- `INNOVATION_MODE` = "display_only" (controls how innovation signal contributes)

Double-count detection: 3+ signals within 7d flagged as possible same-event echo.

Live test: IONQ 48/100 BULLISH (arXiv 80 + insider NOTABLE), GOOGL 25/100 MIXED (arXiv firehose vs WSB fade), AMD 0/100 BEARISH (RSI-80 fade).

Forward log: `data/narrative_cache/_forward_log.jsonl` for 60d evaluation (2026-07-08).

### 5. ~~Option 2 - RelStr 10→15 / BB% 20→15~~ ❌ REJECTED 2026-05-09
**Tested.** Reverted after data showed worse results across all tiers:
| Tier | Baseline (BB20/RS10) | Rebalanced (BB15/RS15) |
|------|----------------------|------------------------|
| ≥30/110 60d | +1.63% (n=637) | +0.90% (n=606) ↓ |
| ≥50/110 60d | **+13.98%** (n=233) | +12.12% (n=168) ↓ |
| ≥65/110 60d | +13.99% (n=61) | +4.91% (n=35) ↓ |

Why: BB% 20→15 made fewer entries hit the threshold (sample size dropped 28%
at ≥50, 43% at ≥65). RelStr increase didn't compensate for shrunken pool.

Validates the decision-log entry "Don't ship Option 2 yet - wait for cleaner
instrumentation." Cleaner instrumentation came, signal said no, we listened.

### 6. ~~Expand TICKER_NARRATIVES beyond sector defaults~~ ✅ COMPLETE 2026-05-09
TICKER_NARRATIVES grew 31 → 120 entries. Added quantum + auto_ev to ACTIVE_NARRATIVES.

**Bonus bug found:** SECTOR_NARRATIVES used em-dash (`"Software-Infrastructure"`) but yfinance returns hyphen-space (`"Software - Infrastructure"`). All Software/Utilities/etc sector defaults silently never matched until today. PLTR/NOW/CRWD/SNOW etc were getting falling-knife penalty when they should have matched ai_infra.

Blocked-entry analysis: 142 (7%) → 82 (4%). Blocked median α = -1.95% (still negative - guard still catches losers, just fires more selectively).

### 7. Tests for 6 new signal modules
**Why:** Reviewer flagged. cli + action gap closed today (+41 tests = 223), but community_reddit/community_youtube/community_score/innovation_arxiv/innovation_score/narrative_score shipped untested. None mutate trades, so risk profile lower than cli_commands - but they shape recommendations that drive trades.
**Scope:** 3-5 smoke tests per module - schema check, happy path, missing-data graceful return.
**Effort:** ~2hr via Claude Code.
**Validation:** `pytest tests/ -v` shows ~250 tests, all green. Mock external APIs (Reddit JSON, YouTube Data API, arXiv) - never burn quota in CI.

### 8. Em-dash style audit (audit_unicode_strings.py)
**Why:** Em-dash bug in SECTOR_NARRATIVES almost certainly has siblings - any string-matched field could have similar unicode-vs-ASCII mismatches.
**Scope:** One-shot scanner. Walk all `.py` files, find string literals containing em-dash/en-dash/curly-quote, cross-reference against likely upstream data sources (yfinance industry strings, JSON keys).
**Effort:** 30min.
**Output:** Either confirms no other instances, or surfaces specific lines to fix.

### 9. Fix score_router for spec tickers (RKLB-class display bug)
**Why:** When spec tickers route through `score.py`, the regular-score output leads, with spec_score as supplement. Should be inverted - spec_score is the lead result, regular score is "DISQUALIFIED - neg FCF" footnote.
**Scope:** `score.py` CLI dispatch + `print(...)` flow. Spec route already detects correctly via `is_spec_candidate()`; just need to swap output ordering. ~10 lines.
**Validation:** `python3 score.py RKLB` should show "RKLB SPEC [STRONG] 95/150" prominently first, regular DISQUALIFIED message below as audit trail.
**Effort:** 30min.

### 10. Fix asymmetric earnings disqualifier
**Why:** Current rule blocks entries within 15 days of earnings - symmetric (treats pre-earnings and post-earnings identically). Real risk is asymmetric: pre-earnings = gap risk (don't enter), post-earnings = gap risk resolved (entries safer than usual).
**Scope:** `score.py` `days_to_earnings` check. Currently `if 0 <= dte <= 15: disqualify`. Should be `if 0 <= dte <= 15: disqualify` (block forward) but allow `dte < 0` (post-earnings, days_since_earnings < 7) as no-block.
**Edge case:** "today" = 0 days_to. Could be either pre-call or post-call. Need to treat dte=0 as block (call is today).
**Validation:** Add tests covering: dte=14 (block), dte=16 (allow), dte=-3 (allow, post-call), dte=0 (block, today is uncertain).
**Effort:** 30min including test additions.

---

## Decision log - why we chose what we chose

| Decision | Reasoning | Date |
|----------|-----------|------|
| Soft -10pt penalty over hard cap-60 for falling-knife guard | Hard cap blocked real winners (MRVL +16%, KSCP +12%) along with falling knives. Coverage problem in TICKER_NARRATIVES, not signal problem. | 2026-05-08 |
| Sector defaults instead of expanding individual ticker dict | 32% → 70% coverage in 5 lines of code vs hours of curation per ticker. | 2026-05-08 |
| Don't ship Option 2 yet | Can't isolate which change moved tier alphas if both ship together. Wait for cleaner instrumentation post-refactor. | 2026-05-08 |
| morning_run.py split before community/innovation modules | Adding modules to a 4,400-line monolith makes the refactor harder later. Pay debt down first. | 2026-05-08 |
| customer_concentration via SEC EDGAR | yfinance doesn't have it. Manual entry burden too high. EDGAR 10-K disclosures are mandatory, free, parseable. | 2026-05-08 |
| Skip "catalyst proximity" auto factor in spec_score | Earnings already covered (yfinance + score.py disqualifier). Non-earnings catalysts manually entered as `next_catalyst` in positions.json. | 2026-05-08 |
| Growth carve-out at $5B-$50B with 25% rev growth + 8q runway gates | RKLB +30% gap exposed gap between scorers. Carve-out catches future analogous setups (ASTS verified live). 15-day earnings rule still blocks any actual entry - fix is for surfacing, not entry timing. | 2026-05-08 |
| Structural fingerprint validation over text-diff for refactor checkpoints | Two-pass baseline diff revealed pervasive output non-determinism (cache load order, pattern block ordering, S/R values). Text-diff produces false alarms. `daily_brief.json` keys/counts give deterministic signal. | 2026-05-09 |
| Stop after step 3, don't push to step 4 | Steps 1-3 are pure-boundary modules (I/O, data, state). Step 4 (alerts_check) introduces cross-module orchestration where right API isn't obvious until called from new structure. Refactoring trading code while tired = silent bugs. | 2026-05-09 |
| Spec-track output should LEAD when score.py routes to spec (#9) | Current behavior: regular-score output comes first, spec_score as supplement. For spec tickers (RKLB-class) the regular path is meaningless - neg FCF auto-DQ. Surfacing the DQ line first signals "system can't score this" when actually spec_score has a clean answer. Lead with spec result; relegate regular DQ to audit footnote. | 2026-05-09 |
| Earnings disqualifier asymmetric - block pre, allow post (#10) | Pre-earnings: gap risk unresolved (don't enter the lottery). Post-earnings: gap risk has already played out - entries actually have BETTER signal-to-noise (one major uncertainty resolved, not added). Symmetric 15-day block treats both as identical risk, which is wrong. Adjust: block dte ∈ [0, 15], allow dte < 0. Edge case dte=0 → keep blocked (today's call uncertain until close). | 2026-05-09 |
| Tests for new signal modules (#7) before any new feature work | Closing trade-execution gap today opened a new gap on signal modules. Reviewer flagged "you closed one and opened another in parallel." Write smoke tests now while design intent is fresh - cheaper than reverse-engineering it 2 months from now. Don't ship more layers until #7 done. | 2026-05-09 |

---

## Honest caveats - read before deploying anything

1. **30d hold improvement is marginal.** Falling-knife guard moved 30d ≥50 from -0.64% → -0.30%. Still negative. For Type S swing trades (your primary ROTH horizon), guard barely helps. Win is concentrated in 60d holds - weight evidence toward Type L decisions.

2. **n=9 cells are noise - both directions.** Don't quote ≥65 backtest results. The +4.14pp on 60d ≥65 is as meaningless as the -0.15pp on 30d ≥65. Real evidence is at ≥30 (n=241) and ≥50 (n=34).

3. **Backtest tests a degenerate config.** Live system has 6 fundamental gates (FCF, Insider, Analyst, Short, Div, Upside) that the backtest can't reconstruct historically. So even after improvements, backtest will likely show negative-ish median. Don't let that falsely invalidate live performance.

4. **TICKER_NARRATIVES is hand-curated.** That means it's a lagging tool - narratives must be added before they fire in scoring. When a new macro narrative emerges (next pandemic / war / tech shift), you need to *add it to the dict* before the system rewards it. That's a known limitation, not a bug.

---

## How to use this file

- Update on every commit that lands work in "Pending" or unblocks new work
- Move items from "Pending" → "Shipped" with date + commit reference
- Add to "Decision log" any non-obvious choice that future Claude (or future Tan) might second-guess
- Reference from `PROMPT.md` so Claude sessions auto-load this context
