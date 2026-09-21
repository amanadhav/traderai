"""
jev_signals.py - TypeSafe (Jev) System One judgments for TraderAI.

Jev returns typed, calibrated probabilities instead of generated text - the
right shape for in-pipeline signals. This module upgrades the keyword-based
news classification with real semantic judgments:

  classify_headlines(ticker, headlines, thesis) →
      thesis_negative / thesis_positive probabilities + sentiment choice
  macro_pulse(narrative, description, headlines) →
      probability the narrative is actively driving today's news
  explain_mover(ticker, move_pct, headlines) →
      which actual headline explains a big move (select, never generate)

Everything degrades to None when TYPESAFE_API_KEY is missing or a call fails -
callers fall back to the keyword classifier in news_sentiment.py.
"""
from __future__ import annotations

import os
from typing import Optional

from data_fetch import load_env

load_env()


def jev_available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def _client():
    from typesafe_sdk import TypeSafeClient
    return TypeSafeClient()


def _headline_titles(headlines: list) -> list[str]:
    out = []
    for h in headlines:
        if isinstance(h, dict):
            t = h.get("title") or h.get("headline") or ""
        else:
            t = str(h)
        if t:
            out.append(t[:200])
    return out[:20]


def _answer(container, key):
    """Read one answer defensively across SDK response shapes."""
    for attr in ("answers", "nouls", "choices", "scores"):
        d = getattr(container, attr, None)
        if d and key in d:
            return d[key]
    return None


def classify_headlines(ticker: str, headlines: list, thesis: str = "") -> Optional[dict]:
    """
    Returns {
      "thesis_negative": p, "thesis_positive": p,     # 0..1 probabilities
      "sentiment": "bullish|bearish|mixed|neutral",
      "sentiment_confidence": float|None,
      "source": "jev",
    } or None when Jev is unavailable/fails.
    """
    titles = _headline_titles(headlines)
    if not jev_available() or not titles:
        return None
    try:
        from typesafe_sdk import Noul, Choice
        state = {
            "ticker": ticker,
            "investment_thesis": thesis or "not provided",
            "headlines": titles,
        }
        with _client() as client:
            resp = client.system_one(
                state=state,
                questions={
                    "thesis_negative": Noul(
                        instructions=(
                            "Do the `headlines` report thesis-breaking negative news for the "
                            "company `ticker` - e.g. CEO/CFO departure under pressure, fraud or "
                            "SEC investigation, guidance cut, FDA rejection, major contract loss, "
                            "class action over the core business?"
                        ),
                        criteria={
                            "true": "At least one headline reports a concrete negative event about this company that damages the long-term investment case (`investment_thesis`)",
                            "false": "Headlines are neutral, positive, about other companies, or only routine volatility/price commentary",
                        },
                    ),
                    "thesis_positive": Noul(
                        instructions=(
                            "Do the `headlines` report concrete thesis-strengthening news for "
                            "`ticker` - e.g. earnings beat, raised guidance, FDA approval, major "
                            "contract win, buyback, breakthrough product demand?"
                        ),
                        criteria={
                            "true": "At least one headline reports a concrete positive business event for this company",
                            "false": "Headlines are neutral, negative, about other companies, or only price commentary",
                        },
                    ),
                    "sentiment": Choice(
                        instructions="Overall, what stance do the `headlines` take toward `ticker` as an investment right now?",
                        criteria={
                            "bullish": "Predominantly positive business news or analyst optimism",
                            "bearish": "Predominantly negative business news or analyst pessimism",
                            "mixed": "Meaningful positive AND negative news at the same time",
                            "neutral": "No strong stance; routine coverage or unrelated items",
                        },
                    ),
                },
            )
        neg = _answer(resp, "thesis_negative")
        pos = _answer(resp, "thesis_positive")
        sent = _answer(resp, "sentiment")
        return {
            "thesis_negative": round(getattr(neg, "noul", 0.0), 3) if neg else None,
            "thesis_positive": round(getattr(pos, "noul", 0.0), 3) if pos else None,
            "sentiment": getattr(sent, "choice", None),
            "sentiment_confidence": getattr(sent, "confidence", None),
            "headlines_considered": len(titles),
            "source": "jev",
        }
    except Exception:
        return None


def macro_pulse(narrative: str, description: str, headlines: list) -> Optional[float]:
    """Probability (0..1) that `narrative` is actively driving today's macro news."""
    titles = _headline_titles(headlines)
    if not jev_available() or not titles:
        return None
    try:
        from typesafe_sdk import Noul
        with _client() as client:
            resp = client.system_one(
                state={"narrative": narrative, "narrative_description": description, "headlines": titles},
                questions={
                    "active": Noul(
                        instructions="Is the macro narrative described in `narrative_description` actively present in the `headlines` today?",
                        criteria={
                            "true": "One or more headlines are clearly about this narrative or its direct consequences",
                            "false": "No headline meaningfully relates to this narrative",
                        },
                    ),
                },
            )
        ans = _answer(resp, "active")
        return round(getattr(ans, "noul", 0.0), 3) if ans else None
    except Exception:
        return None


def explain_mover(ticker: str, move_pct: float, headlines: list) -> Optional[dict]:
    """
    Select which actual headline best explains a big move - a selection over
    real candidates, so the explanation can never be invented.
    Returns {"headline": str|None, "confidence": float|None} or None.
    """
    titles = _headline_titles(headlines)
    if not jev_available() or not titles:
        return None
    try:
        from typesafe_sdk import Choice
        criteria = {f"h{i}": t for i, t in enumerate(titles)}
        criteria["none_of_these"] = "No headline explains the move; likely market-wide or sector flow"
        direction = "up" if move_pct >= 0 else "down"
        with _client() as client:
            resp = client.system_one(
                state={"ticker": ticker, "move": f"{ticker} moved {direction} {abs(move_pct):.1f}% today", "headlines": titles},
                questions={
                    "cause": Choice(
                        instructions="Which headline best explains the `move`?",
                        criteria=criteria,
                    ),
                },
            )
        ans = _answer(resp, "cause")
        pick = getattr(ans, "choice", None)
        if pick is None:
            return None
        headline = None if pick == "none_of_these" else criteria.get(pick)
        return {"headline": headline, "confidence": getattr(ans, "confidence", None)}
    except Exception:
        return None
