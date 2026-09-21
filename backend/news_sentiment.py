"""
news_sentiment.py - News sentiment classifier + macro narrative pulse
No LLM, no API cost. Pure keyword matching on already-fetched headlines.

Two functions:
  classify_ticker_news(headlines, ticker) → POSITIVE / NEGATIVE / NEUTRAL
  classify_macro_pulse(ticker, macro_results) → STRONG / WEAK / SILENT

Used by generate_action_items_v3() to:
  - Block ADD on negative thesis news
  - Boost conviction on positive catalyst news
  - Flag macro tailwind active/cooling per position
  - Explain big movers with news context
"""

from __future__ import annotations

# ── Narrative → macro query key mapping ─────────────────────────────────────
# Maps ACTIVE_NARRATIVES keys (from score.py) to MACRO_QUERIES keys (morning_run.py)
NARRATIVE_TO_MACRO_KEY: dict[str, str] = {
    "iran_hormuz":      "Iran War / Hormuz",
    "defense":          "Europe Rearmament",
    "rare_earth":       "Rare Earth Decoupling",
    "china_decoupling": "Rare Earth Decoupling",
    "ai_infra":         "AI Infrastructure",
    "chip_independence":"AI Infrastructure",
    "nuclear_energy":   "Nuclear Energy",
    "energy_grid":      "Nuclear Energy",
    "glp1_obesity":     None,   # no macro query yet
    "dedollarization":  "Iran War / Hormuz",  # gold/dollar tied to geopolitics
    "defense_it":       "Europe Rearmament",
}

# ── Sentiment keywords ────────────────────────────────────────────────────────

# Strong negative - thesis-level danger
THESIS_NEGATIVE = [
    "ceo resign", "ceo depart", "ceo fired", "executive depart",
    "fda reject", "fda refuse", "fda warning", "recall",
    "fraud", "investigation", "sec probe", "accounting",
    "bankruptcy", "chapter 11", "default", "debt covenant",
    "guidance cut", "guidance withdraw", "warning", "profit warning",
    "contract cancel", "contract terminate", "deal fall",
    "lawsuit", "class action", "settlement",
    "major miss", "revenue decline", "sales drop",
    "market share loss", "losing market", "competition intensify",
]

# Moderate negative - watch signal, don't panic
MODERATE_NEGATIVE = [
    "job cut", "layoff", "restructur", "reduct", "cost cut",
    "downgrade", "price target cut", "lower target",
    "miss estimate", "below expect", "disappoint",
    "decline", "drop", "fall", "shrink", "slow",
    "tariff", "ban", "sanction", "trade war",
    "pressure", "headwind", "challeng", "weak demand",
    "inventory build", "supply glut",
    "struggle", "concern", "worry", "fear",
]

# Strong positive - thesis accelerating
THESIS_POSITIVE = [
    "beat estimate", "earnings beat", "revenue beat", "strong beat",
    "record revenue", "record profit", "record sales",
    "guidance raise", "raised guidance", "outlook raise",
    "fda approve", "fda clear", "fda grant",
    "major contract", "billion contract", "government contract",
    "partnership", "strategic deal", "acquisition",
    "market share gain", "market expansion",
    "breakthrough", "revolutionary", "first-in-class",
    "dividend increase", "buyback", "special dividend",
]

# Moderate positive - supports thesis
MODERATE_POSITIVE = [
    "beat", "exceed", "surpass", "outperform", "top estimate",
    "upgrade", "price target raise", "raise target",
    "strong demand", "robust", "solid", "resilient",
    "growth", "expansion", "momentum",
    "new product", "launch", "release",
    "deal", "agreement", "partner",
    "recover", "rebound", "turnaround",
    "bullish", "positive outlook",
]

# Thesis-specific keywords per narrative
NARRATIVE_KEYWORDS: dict[str, list[str]] = {
    "iran_hormuz":      ["iran", "hormuz", "oil supply", "tanker", "persian gulf",
                         "strait", "shipping", "crude", "opec", "middle east war"],
    "rare_earth":       ["rare earth", "dysprosium", "terbium", "neodymium", "cobalt",
                         "china export ban", "mp materials", "critical mineral", "mining"],
    "china_decoupling": ["china", "decoupl", "tariff", "trade war", "chips act",
                         "export control", "semiconductor", "supply chain"],
    "ai_infra":         ["data center", "artificial intelligence", "gpu", "compute",
                         "hyperscaler", "inference", "training", "capex", "ai demand"],
    "defense":          ["defense", "military", "dod", "ndaa", "nato", "patriot",
                         "missile", "f-35", "rearm", "pentagon", "contract award"],
    "nuclear_energy":   ["nuclear", "uranium", "smr", "reactor", "nuscale",
                         "three mile", "watts bar", "power purchase"],
    "energy_grid":      ["grid", "transmission", "utility", "electricity", "power",
                         "load growth", "data center power", "electrification"],
    "glp1_obesity":     ["ozempic", "wegovy", "glp-1", "semaglutide", "obesity",
                         "weight loss", "diabetes", "novo nordisk", "eli lilly"],
    "dedollarization":  ["gold", "dollar", "brics", "central bank buy", "reserve",
                         "inflation", "federal reserve", "rate cut"],
    "chip_independence":["chips act", "tsmc", "fab", "foundry", "semiconductor",
                         "intel fab", "domestic chip", "supply chain"],
    "defense_it":       ["ai defense", "dod ai", "ndaa", "defense contract",
                         "pentagon", "battlespace", "c2", "surveillance"],
}


# ── classifier ───────────────────────────────────────────────────────────────

def classify_ticker_news(
    headlines: list[str | dict],
    ticker: str,
    narratives: list[str] | None = None,
) -> dict:
    """
    Classify news headlines for a ticker.

    Args:
        headlines: list of strings or dicts with 'title'/'headline' keys
        ticker: used for context (logged, not used in matching)
        narratives: list of narrative keys from TICKER_NARRATIVES - used to
                    detect thesis-specific news (good or bad)

    Returns:
        {
          signal: POSITIVE / NEGATIVE / NEUTRAL
          strength: THESIS / MODERATE / WEAK
          trigger: headline that drove the signal
          thesis_news: True if news directly relates to position thesis
          narrative_mention: list of narratives mentioned in headlines
          headline_count: int
          summary: one-line human-readable
        }
    """
    # Normalize headlines to strings
    texts: list[str] = []
    for h in headlines or []:
        if isinstance(h, str):
            texts.append(h.lower())
        elif isinstance(h, dict):
            t = h.get("title") or h.get("headline") or h.get("content", {}).get("title", "")
            if t:
                texts.append(str(t).lower())

    if not texts:
        return {
            "signal": "NEUTRAL", "strength": "WEAK", "trigger": "",
            "thesis_news": False, "narrative_mention": [],
            "headline_count": 0, "summary": "No headlines available",
        }

    full_text = " | ".join(texts)

    # Check thesis-level negative first (highest priority)
    for kw in THESIS_NEGATIVE:
        if kw in full_text:
            trigger = next((t for t in texts if kw in t), texts[0])
            return {
                "signal": "NEGATIVE", "strength": "THESIS",
                "trigger": trigger[:120],
                "thesis_news": True,
                "narrative_mention": _find_narrative_mentions(full_text, narratives or []),
                "headline_count": len(texts),
                "summary": f"THESIS RISK: '{kw}' detected - verify position before adding",
            }

    # Check thesis-level positive
    thesis_pos_trigger = None
    for kw in THESIS_POSITIVE:
        if kw in full_text:
            thesis_pos_trigger = kw
            trigger = next((t for t in texts if kw in t), texts[0])
            return {
                "signal": "POSITIVE", "strength": "THESIS",
                "trigger": trigger[:120],
                "thesis_news": True,
                "narrative_mention": _find_narrative_mentions(full_text, narratives or []),
                "headline_count": len(texts),
                "summary": f"CATALYST: '{kw}' - thesis accelerating",
            }

    # Moderate signals - count hits, majority wins
    neg_hits = sum(1 for kw in MODERATE_NEGATIVE if kw in full_text)
    pos_hits = sum(1 for kw in MODERATE_POSITIVE if kw in full_text)

    narrative_mentions = _find_narrative_mentions(full_text, narratives or [])

    if neg_hits > pos_hits and neg_hits >= 2:
        trigger = next((t for t in texts if any(kw in t for kw in MODERATE_NEGATIVE)), texts[0])
        return {
            "signal": "NEGATIVE", "strength": "MODERATE",
            "trigger": trigger[:120],
            "thesis_news": bool(narrative_mentions),
            "narrative_mention": narrative_mentions,
            "headline_count": len(texts),
            "summary": f"Negative tone ({neg_hits} signals) - watch, don't add blindly",
        }

    if pos_hits > neg_hits and pos_hits >= 2:
        trigger = next((t for t in texts if any(kw in t for kw in MODERATE_POSITIVE)), texts[0])
        return {
            "signal": "POSITIVE", "strength": "MODERATE",
            "trigger": trigger[:120],
            "thesis_news": bool(narrative_mentions),
            "narrative_mention": narrative_mentions,
            "headline_count": len(texts),
            "summary": f"Positive tone ({pos_hits} signals) - supports thesis",
        }

    return {
        "signal": "NEUTRAL", "strength": "WEAK",
        "trigger": texts[0][:120] if texts else "",
        "thesis_news": bool(narrative_mentions),
        "narrative_mention": narrative_mentions,
        "headline_count": len(texts),
        "summary": "Mixed/neutral news - no strong signal",
    }


def _find_narrative_mentions(full_text: str, narratives: list[str]) -> list[str]:
    """Return which narratives are explicitly mentioned in headlines."""
    mentioned = []
    for narr in narratives:
        kws = NARRATIVE_KEYWORDS.get(narr, [])
        if any(kw in full_text for kw in kws):
            mentioned.append(narr)
    return mentioned


# ── macro pulse ──────────────────────────────────────────────────────────────

def classify_macro_pulse(
    ticker: str,
    narratives: list[str],
    macro_results: dict,
) -> dict:
    """
    Check if a ticker's macro narratives are actively in the news today.

    Args:
        ticker: position ticker (for logging)
        narratives: list from TICKER_NARRATIVES[ticker]
        macro_results: dict from morning_run - {query_name: [articles]}

    Returns:
        {
          pulse: STRONG / ACTIVE / SILENT
          active_narratives: list of narrative keys with coverage today
          silent_narratives: list of narrative keys with NO coverage today
          summary: one-line
        }
    """
    if not narratives:
        return {
            "pulse": "NEUTRAL",
            "active_narratives": [],
            "silent_narratives": [],
            "summary": "No macro narratives assigned to this ticker",
        }

    active, silent = [], []
    for narr in narratives:
        macro_key = NARRATIVE_TO_MACRO_KEY.get(narr)
        if macro_key is None:
            continue  # narrative not tracked in macro feed
        articles = macro_results.get(macro_key, [])
        if articles:
            active.append(narr)
        else:
            silent.append(narr)

    if len(active) >= 2:
        pulse = "STRONG"
        summary = f"Multiple macro tailwinds active today: {', '.join(active)}"
    elif len(active) == 1:
        pulse = "ACTIVE"
        summary = f"Macro tailwind active: {active[0]}"
    elif silent:
        pulse = "SILENT"
        summary = f"Macro narrative(s) QUIET today: {', '.join(silent)}. Thesis cooling?"
    else:
        pulse = "NEUTRAL"
        summary = "Macro narratives not tracked in daily feed"

    return {
        "pulse": pulse,
        "active_narratives": active,
        "silent_narratives": silent,
        "summary": summary,
    }


# ── big mover context ─────────────────────────────────────────────────────────

def explain_big_mover(
    ticker: str,
    pct_move: float,
    headlines: list,
    narratives: list[str],
) -> str:
    """
    One-line explanation of why a position moved >2%.
    Checks headlines for catalyst, then macro narrative.
    """
    direction = "UP" if pct_move >= 0 else "DOWN"
    news = classify_ticker_news(headlines, ticker, narratives)

    if news["signal"] == "POSITIVE" and news["strength"] == "THESIS":
        return f"{ticker} {direction} {abs(pct_move):.1f}% - THESIS CATALYST: {news['trigger'][:80]}"
    elif news["signal"] == "NEGATIVE" and news["strength"] == "THESIS":
        return f"{ticker} {direction} {abs(pct_move):.1f}% - THESIS RISK: {news['trigger'][:80]}"
    elif news["narrative_mention"]:
        narr = news["narrative_mention"][0].replace("_", " ")
        return f"{ticker} {direction} {abs(pct_move):.1f}% - Macro catalyst ({narr}): {news['trigger'][:60]}"
    elif news["signal"] != "NEUTRAL":
        return f"{ticker} {direction} {abs(pct_move):.1f}% - {news['summary']}"
    else:
        return f"{ticker} {direction} {abs(pct_move):.1f}% - No clear catalyst in headlines"
