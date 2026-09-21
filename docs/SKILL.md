# Example Strategy Playbook
# This is the EXAMPLE ruleset that ships with the "Balanced Swing" preset -
# a starting point, not a prescription. Your live rules come from the setup
# wizard (user_config.json) and override anything here. Edit freely.

---

## Position Types

| Type | Description | Stop rule | Exit rule |
|------|-------------|-----------|-----------|
| **S - Swing** | 1-30 day momentum trade | Hard −8% GTC stop | +5%→move stop to BE, +10%→sell 50%, +15%→sell 75%, +20%→sell all. Day 30 auto-exit. |
| **L - Long** | Medium-term thesis hold | Disaster stop −15% | At −8% = ADD ZONE not exit. +15%→sell 25%, +30%→sell 50%. |
| **I - Income** | Dividend/distribution income | No stop | Exit only on distribution cut or pipeline collapse. |
| **Lifetime** | Permanent compounding core | No stop. Ever. | Never exit on volatility. Exit only on business collapse. |
| **Spec** | High-risk speculative bet | No stop | Exit if drops below defined floor OR thesis gone. |

### Type S - Swing (ROTH only)
- Entry: RSI 35-50, score 60-79, $750-$1K
- Stop: hard −8% GTC Stop Market immediately on fill
- Profit ladder: +5% stop to BE · +10% sell 50% · +15% sell 75% · +20% sell all
- Day 30 auto-exit, no exceptions
- NEVER average down a Type S

### Type L - Long (ROTH or TOD)
- Entry: RSI <35, score 80+, $1K-$2K
- No hard stop - disaster stop at −15% (fraud/collapse only)
- At −8%: this is ADD ZONE not exit
- Profit ladder: +15% sell 25% · +30% sell 50%
- Max 2 adds per position if thesis intact

### Type I - Income/MLP (ROTH only)
- Entry: yield 4%+, EPD, ET, KMI
- No stop ever. Oil price drop ≠ exit.
- Exit only on distribution cut
- MLP note: K-1 filing, UBTI in IRA - manage size

### Lifetime (TOD only)
- Irreplaceable moat, 5-15 year hold
- No stop. Ever. Market selloffs ≠ exit trigger.
- Add on dips if moat intact
- Exit only: fraud, moat broken, tech obsolete

### Spec (TOD only)
- Max $500 - sized to lose entirely
- No stop. Accept binary outcome.
- Exit at defined floor (e.g. BBAI <$2.50) or 5x gain
- 3-5 year hold. NEVER add to losing spec.

---

## 180-Point Entry Scoring

| Factor | Points |
|--------|--------|
| RSI <30 | 25 · <40=15 · <50=5 |
| MACD hist neg→pos crossover | 20 · improving=10 |
| BB% <20 | 20 · <40=10 |
| Upside to target >20% | 20 · >10%=10 · >5%=5 |
| Div yield >4% | 10 · >2%=5 |
| Near 52W low (<10% above) | 5 |
| Volume confirmation (vol_ratio >1.5 on down day) | 10 · 1.0-1.5=5 |
| Relative strength vs S&P (outperforming) | 10 · neutral=5 |
| Analyst rating ≤2.0 | 5 · ≤2.5=3 |
| Short interest >10% float | 5 |
| Bullish reversal pattern (confidence ≥65%) | +10 |
| Bullish continuation pattern (confidence ≥65%) | +5 |
| Insider buying (open-market purchase, Form 4) | +10 |
| Active macro narrative (ACTIVE_NARRATIVES match) | +10 |

**Thresholds:** ≥70 = candidate · ≥110 = strong · ≥140 = high conviction

### Auto-Disqualifiers (score = 0 regardless)
- Earnings within 15 days
- Debt/equity > 200
- Free cash flow negative
- Fundamental reason for drop (guidance cut, M&A dilution, FDA rejection)
- Bearish chart pattern with confidence ≥65% - flag even if score passes

---

## ETF Scoring Formula (separate - no FCF/earnings checks)

| Factor | Points |
|--------|--------|
| RSI <30 | 30 pts |
| RSI <40 | 15 pts |
| BB% <20 | 25 pts |
| BB% <40 | 10 pts |
| MACD histogram improving | 20 pts |
| Macro tailwind confirmed | 15 pts |
| VIX >20 (fear = opportunity) | 10 pts |

≥60 = buy · ≥80 = aggressive buy

---

## Position Sizing

Base: **$1,000**

| Condition | Adjustment |
|-----------|-----------|
| Beta 1.0-1.3 | $1,000 |
| Beta 1.3-1.6 | $750 |
| Beta >1.6 | $500 |
| VIX >25 | −25% all positions |
| VIX >35 | −50% all positions |
| 2nd stock same sector | max $500 |
| Short ratio >5 | −25% |

---

## Market Conditions

| Signal | Action |
|--------|--------|
| SPY RSI >75 | No new lump sum entries |
| SPY RSI <35 | Buy aggressively |
| VIX >25 | Reduce all sizing 25% |
| VIX >35 | Reduce all sizing 50% |

---

## Sector Limits (max 2 per sector per account)

| Sector | ROTH | TOD | Status |
|--------|------|-----|--------|
| Defense | RTX, NOC | - | ROTH FULL 2/2 |
| Technology | CRM | ASML, AMD, TSM, NVDA, AAPL, MSFT, BBAI | TOD concentrated - FREEZE |
| Comm Services | - | META, GOOGL, NFLX | ~71% TOD = intentional AI bet |
| Healthcare | MDT | NVO (pending) | OK |
| Energy/MLP | EPD | - | OK - Iran tailwind confirmed |
| Materials/RE | MP | - | OK |
| Consumer Staples | BJ | - | OK - recession hedge |
| Macro Hedge | GLD | - | Lifetime hold |
| Financials | ❌ NONE | ❌ NONE | 🚨 GAP - add V or BRK-B |

Fill priority: Financials (V or BRK-B) → Healthcare depth (ISRG) → Nuclear (CCJ)

---

## 7 Active Macro Situations (as of 2026-05)

### 1. Iran War / Hormuz Disruption (ACTIVE)
- US strikes on Iranian nuclear/military sites started Feb 28, 2026
- Hormuz disrupted · Qatar LNG offline (12.8 MTPA, 3-5 years)
- UAE exited OPEC May 1. Global oil supply down 10.1 mb/d
- EPD Q1 confirmed: $14.39B beat vs $13.19B estimate
- **Plays**: EPD (own ✅), GLD (own ✅), RTX (own ✅), ITA (watch - deeply oversold)
- **Buy trigger**: Any new US strikes on Iran → buy GLD immediately

### 2. US-China Rare Earth Decoupling (ACTIVE)
- China controls 85-90% of RE processing, restricting dysprosium/terbium exports
- MP Materials = only large-scale US producer. National security asset. NDAA contracts.
- **Plays**: MP (own ✅, ROTH), REMX (MP covers thesis for now)
- **Buy trigger**: Any China RE export restriction → BUY MP same day, no waiting for RSI

### 3. Europe Rearmament Supercycle (STRUCTURAL 10YR)
- Global military spending $2.89T in 2025. EU €800B by 2030. NATO targeting 5% GDP.
- Rheinmetall: 9.5 YEARS backlog. German defense +154% in 2025.
- **Plays**: RTX (own ✅), NOC (own ✅), ITA (RSI 26.4 = triple setup with Iran)
- **Rule**: Defense spending does NOT stop regardless of who's in power

### 4. BRICS De-Dollarization (5-10YR)
- USD reserve share declining. Central banks buying gold at record pace.
- GLD is best multi-year hold in negative real rates environment
- **Buy trigger**: Major oil deal priced in yuan → BUY GLD aggressively

### 5. Taiwan / TSMC Risk (TAIL RISK)
- TSMC fabs 90% of world's advanced chips. Any Taiwan conflict = global chip famine.
- TSM currently 11.8% of TOD = AT LIMIT. Do NOT add more TSM.
- **Sell trigger**: PLA military drills near Taiwan → trim TSM 1-2sh, buy INTC/GLD

### 6. US Consumer Crunch (BUILDING)
- Credit card debt at all-time high. Savings near zero. Jobs −92K Apr 2026.
- Market rising because S&P earns globally and AI capex = corporate/govt money
- **Risk**: NKE (most vulnerable). BJ = recession HEDGE (consumers downgrade)

### 7. Trump Fed / Bond Vigilante Risk (HIGH RISK 2026-2027)
- Trump appoints dovish Fed chair → cuts rates at 3%+ inflation
- Bond market sells Treasuries = worst of both: loose monetary + rising long rates
- **GLD is best asset in this environment**

---

## Trump Signal Framework

| Signal | Action | Speed |
|--------|--------|-------|
| Tariff threat on country X | Avoid importers, buy domestic alternatives | Same day |
| Tariff pause / trade deal | BUY beaten-down tech, consumer disc, TSM, ASML | Immediate |
| Iran escalation language | BUY EPD, GLD, RTX, NOC | Immediate |
| Rare earth executive order | BUY MP aggressively - no RSI wait | Immediate |
| Government equity stake announced | BUY that company - govt won't let it fail | Same day |
| NATO criticism / pull back | BUY European defense | Same day |
| Nuclear EO / SMR fast-track | BUY CCJ, OKLO, NUCL | Same day |
| Social media pump, no policy doc | DO NOT TRADE. Wait 48h for confirmation. | 48hr wait |

**Government-backed stocks (do not short, dip = add):** NVDA, INTC, AMD, MP

---

## 5 Mega Themes

### 1. Humanoid Robots - Physical AI (2026-2030)
- Manufacturing cost down 40% in one year. Tesla: 50K Optimus units 2026.
- NVIDIA Isaac = Android OS for every humanoid robot
- **Watch**: NVIDIA GTC (March annual) - Jensen's keynote = 2-year roadmap
- **Plays**: NVDA (own ✅), MSFT (own ✅), BOTZ (wait RSI <45)

### 2. Nuclear Energy Renaissance (2026-2035)
- Every big tech signing nuclear PPAs: MSFT 20yr TMI deal, Google 500MW SMR, Amazon 5GW
- **Buy trigger**: Any new tech nuclear PPA → CCJ goes up
- **Plays**: CCJ (RSI 50.5 watch), NUCL ETF (wait pullback <50 RSI)

### 3. Quantum Computing (2028-2032 commercial)
- IBM quantum advantage expected end of 2026. Google Willow error correction proven.
- **Watch**: arXiv.org (quant-ph). Papers today = products in 18 months.
- **Plays**: IONQ (wait RSI <45, $28-35 zone, $200-300 TOD lottery)

### 4. Rare Earth / Critical Minerals (NOW)
- China restricting dysprosium/terbium in 2026. MP = first US permanent magnets since 1980s.
- **Rule**: China restriction = buy MP same day, no RSI wait

### 5. Agentic AI Infrastructure (2025-2028)
- Wave 1 = ChatGPT. Wave 2 = AI agents in enterprises. CRM's 25yr data = moat.
- Agentforce ARR: $800M, +169% YoY. 3.2T tokens processed.
- **Plays**: CRM (own ✅), MSFT/GOOGL/AMZN (own ✅), PLTR (research needed)
- **Watch signal**: When MSFT, GOOGL, AMZN all use same new word in same quarter → that's the next trade

---

## NVDA Early-Catch Framework

How to find the next NVDA before the crowd:
1. **Track arXiv.org (cs.AI, quant-ph)** - research papers 12-18 months before products
2. **NVIDIA GTC keynote** - Jensen names the next platform wave explicitly ("Physical AI" 2025 = buy robotics)
3. **Follow the picks** - what companies does NVDA invest in? (Figure AI = next signal)
4. **Patent filings** - USPTO patents 2-3 years before products ship. NVDA robotics patents 2022 → Isaac 2025.
5. **Earnings call word frequency** - when all 3 hyperscalers (MSFT/GOOGL/AMZN) use same new term in same quarter → they all bought the same thing

---

## Adversarial Debate Protocol

Before any buy >$1K, run the debate:

**Bull case (30 sec):** Why buy now? What catalyst? What's the exact thesis?

**Bear case (30 sec):** Why will it go down from here? What am I missing? What does the market know that I don't?

**Verdict:** Does the bull case survive honest bear scrutiny? If not - don't buy.

**Exception to wait:** China RE restriction, Trump executive order, confirmed geopolitical escalation = buy same day without debate.

---

## Hard Lessons (Real Losses)

1. **The Meta mistake**: Had 8sh ~$560 avg. Sold thinking market would drop. Market went up. NEVER sell without simultaneously placing the re-entry limit order.

2. **April 2026 Rule**: Panic sold META, MSFT, SOXX, QQQ, GLD on macro fear. All came back. Cost ~$2,000-2,500 in 3 weeks. **IF the headline is "market crashed because of [tariffs/Fed/geopolitical]" - that is NOT a thesis breaker. HOLD or ADD.**

3. **The timing killer**: Missing the 10 best trading days out of 5,000 cuts 20-year returns roughly in half. 7 of 10 best days happen within 2 weeks of 10 worst days. Being in cash during fear spike = missing the snap-back.

4. **FOMO rule**: 3 consecutive green days does NOT mean buy. It means your entry price is 3 days worse. Wait for your limit to come to you.

5. **The re-entry rule**: Never sell without knowing the exact price you buy back at. Write it in the order the same moment you sell.

---

## Investor Principles

- **Buffett**: "Be fearful when others are greedy, greedy when others are fearful."
- **Munger**: "The big money is in the waiting." But: "By the time you're comfortable, the price is gone."
- **Klarman**: Define margin of safety BEFORE buying. 15-20% below fair value = acceptable entry.
- **Marks**: "You can't predict. You can prepare." Limit orders + tranche plans = preparation.
- **Druckenmiller**: "Concentration is the key to great performance." TOD tech concentration = intentional.
- **Lynch**: Know what you own and why. Write 2 sentences: why you own it, what makes you sell.

---

## Chart Patterns & Technical Signals

### Indicator signals (confidence ≥65% required)

| Signal | Meaning | Action |
|--------|---------|--------|
| Golden cross | 50MA crossed above 200MA | Add to position if other factors align |
| Death cross | 50MA crossed below 200MA | Reduce - momentum shift |
| BB squeeze | Bandwidth below 10th percentile | Watch for breakout - direction unclear |
| Bullish RSI divergence | Price lower low, RSI higher low | Potential reversal up - Type L = add zone |
| Bearish RSI divergence | Price higher high, RSI lower high | Potential reversal down - tighten stop |

### Classical chart patterns

| Pattern | Signal | Entry implication |
|---------|--------|-------------------|
| Double bottom | Bullish reversal | Confirm break above neckline before entry |
| Inverse head & shoulders | Bullish reversal | Confirm neckline breakout |
| Cup & handle | Bullish continuation | Buy on handle breakout above cup rim |
| Ascending triangle | Bullish continuation | Buy on resistance breakout with volume |
| Flag (bull) | Bullish continuation | Buy on flag breakout, stop below pole |
| Double top | Bearish reversal | Exit / tighten stop |
| Head & shoulders | Bearish reversal | Exit on neckline break |
| Descending triangle | Bearish | Tighten stops, reduce if pattern confirms |

Confidence threshold: ≥0.65. Bearish patterns = flag even if overall score passes.

---

## Morning Protocol (Arizona Time, UTC−7)

| Time | Step | Detail |
|------|------|--------|
| 6:15 AM | Pre-market check | VIX, futures SPY/QQQ, overnight gaps >2% |
| 6:25 AM | News sweep | Position tickers + macro themes |
| 6:30 AM | Market open | Watch first 5 min - do NOT trade opening candle |
| 6:35 AM | GTC check | Any pending orders within $0.50 of current price? |
| 7:00 AM | Action decision | ONE decision per position max |
| 1:00 PM | Market close | Final check. Place GTC orders for tomorrow. |

**Never place market orders in first 5 minutes. One decision per position per day.**

---

## Fidelity Order Types

| Order type | When to use |
|------------|------------|
| Limit | Buying - set exact price, don't overpay |
| Stop Market (GTC) | Exit stops - triggers market order when price hit |
| Stop Limit | When slippage risk on stop market is too high (illiquid stocks) |

GTC = Good 'Til Canceled. Fidelity cancels at year end - review annually.

---

## Research & Intelligence Sources (Lead Time)

| Source | What it signals | Lead time |
|--------|----------------|-----------|
| NVIDIA GTC (annual March) | Next 2-year market roadmap | 0 days - act now |
| arXiv.org (cs.AI, quant-ph) | Research before products | 12-18 months early |
| Truth Social / X (Trump) | Tariff/trade/EO hints | 12-48 hours early |
| IAEA Bulletins | Nuclear deals, new capacity | 1-3 months early |
| G7/G20 Communiqués | RE, sanctions, trade policy | 1-6 months early |
| Congressional NDAA markup | Defense contract winners | 6-12 months early |
| Earnings call transcripts | CEO pivot signals | 1-2 quarters early |
| USPTO Patent Filings | R&D priorities | 2-3 years early |
| China MOFCOM | RE export restrictions | 0 days - act now |

---

## Action Items v3 - 6-Signal Synthesis Engine

`generate_action_items_v3()` combines ALL signals into ONE specific action per position.

### Signal Stack (per position, every morning run)
| Signal | Source | Weight in decision |
|--------|--------|--------------------|
| 180pt score | score.py | ADD requires ≥70 |
| RSI | yfinance | <45 = oversold = bullish signal |
| Insider buying | insider.py (SEC Form 4) | STRONG/CLUSTER = override dip, +1 add_signal |
| Options flow | options_flow.py | BULLISH_FLOW/UNUSUAL_CALLS = +1 add_signal |
| Max pain drift | options_flow.py | >4% pull ≤3d = WATCH with price target |
| Gamma walls | options_flow.py | limit price for ADD, target for exits |
| News sentiment | news_sentiment.py | NEGATIVE/THESIS = block ADD; POSITIVE/THESIS = +1 add_signal |
| Macro pulse | news_sentiment.py | SILENT = "MACRO CHECK" flag; ACTIVE = signals_str context |
| Chart pattern | patterns.py | Bearish ≥65% = downgrade; Bullish = +1 add_signal |
| Earnings DTE | earnings_calendar.py | ≤15d = hard disqualifier; ≤3d = URGENT |

### ADD Rule (Type L/S in add zone −5% to −15%)
**Requires ALL of:**
1. Score ≥70
2. Earnings >15 days away
3. News sentiment NOT NEGATIVE/THESIS
4. add_signal_count ≥2 (count: RSI oversold, bullish options, max pain pulling up, insider, positive news)

**ADD quantity:** `size_position(snap, vix) // price` shares  
**ADD limit price:** nearest put wall strike below (gamma floor) or current price if no wall within 5%

### Signal Priority Order
1. THESIS NEGATIVE news → block everything, URGENT flag
2. Earnings ≤15d → DO NOT ADD (hard disqualifier)
3. Stop imminent (<5% buffer) → URGENT
4. Insider STRONG + down >5% → HOLD THROUGH DIP (overrides bearish signals)
5. Max pain drift >4% ≤3d → WATCH with target
6. Type-specific rules (S/L/I/Spec/Lifetime)
7. Bearish pattern + no insider → WATCH tighten stop
8. Macro SILENT → WATCH narrative check

---

## News Sentiment Rules (news_sentiment.py)

**No LLM, no API cost** - pure keyword matching on yfinance headlines.

### Keyword Tiers
| Tier | Examples | v3 action |
|------|---------|----------|
| THESIS NEGATIVE | CEO resign, FDA reject, fraud, guidance cut, contract cancel, class action, bankruptcy | Block ADD · URGENT alert |
| THESIS POSITIVE | Beat estimates, record revenue, FDA approve, billion contract, guidance raise, major partnership | ACTION "CATALYST NEWS" · +1 add_signal |
| MODERATE NEGATIVE | Layoffs, downgrade, miss, decline, tariff, pressure, headwind | WATCH "NEWS HEADWIND" |
| MODERATE POSITIVE | Beat, upgrade, growth, deal, recover, expansion | +1 add_signal if 2+ hits |

### Macro Pulse
- **STRONG** (2+ narratives active in today's news) → high conviction, shown in signals_str
- **ACTIVE** (1 narrative covered) → noted in signals_str
- **SILENT** (narratives assigned but none in today's feed) → WATCH "MACRO CHECK - NARRATIVE QUIET"
- **NEUTRAL** (no narratives assigned) → no flag

### Narrative → Ticker Mapping (11 narratives)
| Narrative | Tickers |
|-----------|---------|
| iran_hormuz | EPD, RTX, NOC, GLD |
| defense | RTX, NOC, BBAI |
| rare_earth | MP |
| china_decoupling | MP, AAPL, AMD, ASML, TSM |
| ai_infra | NVDA, AMD, ASML, TSM, CRM, MSFT, GOOGL, META, AMZN |
| chip_independence | NVDA, AMD, ASML, TSM |
| nuclear_energy | (CCJ, NEE if added) |
| energy_grid | (NEE, DUK if added) |
| glp1_obesity | NVO |
| dedollarization | GLD, EPD |
| defense_it | BBAI |

---

## Options Flow Rules (options_flow.py)

### Signal Tiers
| Signal | Condition | Action |
|--------|-----------|--------|
| UNUSUAL_CALLS | Call vol >3× put vol | Alert bar + WATCH for Lifetime, +1 add_signal for L/S |
| BULLISH_FLOW | PCR_vol <0.7 | +1 add_signal |
| MILD_BULLISH | PCR_vol <0.85 | +1 add_signal |
| NEUTRAL | PCR_vol 0.85-1.15 | No signal |
| HEDGING | PCR_OI high AND earnings ≤14d | Flag: institutions buying puts before earnings |
| BEARISH_FLOW | PCR_vol >1.3 | Reduces trim target; no ADD |

### Max Pain
- Calculated per expiry: for each strike S → call_pain + put_pain → find minimum = max pain
- **DRIFT UP:** price below max pain → mechanical upward pressure before expiry
- **DRIFT DOWN:** price above max pain → price may drift toward it
- **PINNED:** within 1% → price likely stays flat through expiry
- **Alert threshold:** >4% away AND ≤3 days to expiry → WATCH with price target

### Gamma Walls
- High OI call strikes above = dealer resistance (hard to break through before expiry)
- High OI put strikes below = dealer support (soft floor)
- Used as: ADD limit = nearest put wall, SELL target = nearest call wall, TRIM target = above current call wall

---

## Insider Buying Rules (insider.py)

**Source:** yfinance `insider_transactions` (SEC Form 4). Finnhub fallback. Open-market purchases only - strips awards, exercises, gifts, tax withholding.

### Signal Tiers
| Tier | Condition | Score bonus | v3 action |
|------|-----------|-------------|----------|
| STRONG | C-suite (CEO/CFO/Director) ≥$100K single purchase | +15pts | Override dip; +1 add_signal; HOLD alert if down >5% |
| CLUSTER | 3+ insiders buying in 30 days | +15pts | Same as STRONG |
| NOTABLE | Any insider ≥$50K | +15pts | +1 add_signal |
| WEAK | Small purchase <$50K | 0 | Noted only |
| NONE | No open-market buys in 90d | 0 | No action |

**Cache:** 24hr TTL (`insider_cache.json`). `--refresh` forces new fetch.  
**Key rule:** Insider buying STRONG + position down >5% → HOLD signal overrides bearish chart/news unless thesis fundamentally broken.

---

## Universe Scanner (scan_universe.py)

Scans ~350 stocks daily at 8:30 AM MST (launchd cron). Scores each with 180pt algorithm. Top 30 saved to `scan_results.json`. Morning run shows "TODAY'S CANDIDATES" automatically.

**Filters applied:**
- Score ≥70
- Earnings >15 days away
- Not already held in ROTH or TOD
- No THESIS NEGATIVE news (if ticker_news available)

**Quick scan:** `--quick` flag = ~150 stocks, faster, same filters.

---

## Spec Scoring - 150pt Algorithm (spec_score.py)

Auto-triggered when `is_spec_candidate()` returns True: `market_cap <$5B AND (neg FCF OR rev_growth >50% OR price <$10)`.

### Factors

| Factor | Max Pts | Logic |
|--------|---------|-------|
| Revenue growth YoY | 25 | >100%=25, >50%=20, >25%=15, >10%=8, ≤0=0 |
| Cash runway | 20 | >12q=20, >8q=15, >4q=8, <2q=DISQUALIFY |
| Gross margin trend | 15 | improving 3q+: 15, flat: 8, declining: 0 |
| Share dilution | 15 | <5%/yr=15, <15%=10, <25%=5, >50%=DISQUALIFY |
| Insider buying | 15 | STRONG=15, CLUSTER=12, NOTABLE=8, WEAK=3 |
| Customer concentration | 10 | DoD/hyperscaler ≥30%=10, diversified=5, unknown=0 |
| Short squeeze | 10 | >25% float+positive news=10, >15%=5 |
| Catalyst proximity | 10 | <30d=10, <60d=7, <90d=4 |
| Volume regime | 10 | >$50M/day=10, >$10M=5, <$1M=penalty |
| Sector tailwind | 10 | narrative match=10, adjacent=5 |
| Pattern bonus | 10 | bullish reversal=10, continuation=5 |

### Thresholds

≥60 = candidate · ≥90 = strong · ≥110 = high conviction

### Hard Disqualifiers

- Runway <2 quarters → DELISTING RISK
- Price <$1 → NYSE/NASDAQ delisting threshold
- Dilution >50% in 12 months → SHAREHOLDER DESTRUCTION
- Zero revenue → SHELL COMPANY
- Earnings <15 days → same as regular scorer rule

### Rules

- **Never add to losing spec** - ADD only when: spec_score ≥90 AND P&L ≥-15% AND no THESIS NEGATIVE news
- Customer concentration is bonus only - EDGAR failure → 0pts, never disqualifies
- Manual catalyst in positions.json overrides auto-detected earnings when sooner
- Spec tickers appear in separate "SPEC CANDIDATES" section of scan output
- `--both` flag on score.py shows regular (DISQUALIFIED) + spec score side by side

### Customer Concentration (customer_concentration.py)

- Pulls latest 10-K from SEC EDGAR (free, no API key)
- Regex extracts "accounted for X% of revenue" sentences
- Haiku fallback ($0.001/ticker) when regex finds nothing
- Cache: `data/edgar_cache/{TICKER}_10k.json` - 365-day TTL
- DoD/government anchor = revenue stability (contract predictability)
- Hyperscaler anchor (AWS/Azure/GCP ≥30%) = also +10 (enterprise SaaS signal)

---

## Lead-Time Signal Stack (display-only v1, 2026-05-09)

Three new modules layer on top of the 180pt entry score. **All three are
display-only in v1** - they don't affect score.py math. Forward logs collect
data through 2026-07-08; promote to additive after evaluation.

### community_score.py - Reddit + YouTube combiner

Sources:
- **Reddit** (`community_reddit.py`) - WSB / r/stocks / r/investing mention count + Haiku sentiment, 6h cache
- **YouTube** (`community_youtube.py`) - tech-creator allowlist (Lex/MKBHD/Acquired/Two Min Papers tier_a-c) + Haiku sentiment, 24h cache

Scoring (raw -30..+60 → 0-100):
| Factor | Range |
|--------|-------|
| YT tech-creator early signal | 0..+30 (tier_a/b/c match) |
| YT general coverage | 0..+20 |
| WSB retail (RSI-gated) | -20..+10 |
| Tech-creator absence (whitelisted sectors) | -10..0 |

**WSB-fade RSI gate** (Q2 design 2026-05-09):
- top-5 mention + BULLISH + RSI<50 → +10 (real awakening)
- top-5 + BULLISH + RSI 50-70 → 0 (mature, neutral)
- top-5 + BULLISH + RSI>70 → -20 (euphoric peak fade)

**Absence penalty whitelist** (Q3): only fires for community-eligible sectors
(Semis, Consumer Electronics, Auto/EV, Gaming, Mass-market Biotech, Aerospace,
Quantum, Robotics). B2B SaaS exempted to avoid false negatives.

### innovation_score.py - arXiv research signal

Sparse-by-design: only frontier-tech tickers in 35-entry ARXIV_SEARCH_TERMS
map score; rest correctly return has_data=False (no narrative needed for
retail/midstream/MLP).

Scoring (raw 0..+50 → 0-100):
| Factor | Range |
|--------|-------|
| arXiv volume (12mo) | 0..+25 (firehose=25, 0 papers=0) |
| Category breadth | 0..+15 (>=4 cats=15) |
| Frontier match (cs.AI/cs.LG/quant-ph/cs.RO present) | 0..+10 |

USPTO patents deferred to v1.1 (PatentsView API redesign 2024).

### narrative_score.py - multi-signal combiner

Aggregates lead-time-aware signal stack:
| Source | Lead | Weight |
|--------|------|--------|
| arXiv | ~18mo | 1.0 |
| YouTube tech-creator | ~4mo | 0.7 |
| Insider | ~2mo | 0.5 |
| Options flow | ~0.25mo | 0.3 |
| WSB (can be negative for fade) | ~0.25mo | 0.3 |

Aggregation: weighted sum of (raw/max) × weight, normalized 0-100.

**Pluggable mode flags** (per Tan directive 2026-05-09):
```
NARRATIVE_MODE   = "display_only" | "additive" | "gate" | "disabled"
COMMUNITY_MODE   = "display_only"
INNOVATION_MODE  = "display_only"
```

Flip individual constants after 2026-07-08 forward-log evaluation. No
rebuild required.

**Double-count detection:** 3+ signals within 7 days flagged as possible
same-event echo (avoid counting one event across three layers as three
independent confirmations).
