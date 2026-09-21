"""
ai_client.py - Shared AI layer for TraderAI.

One place for every Anthropic call: model selection, lazy client, graceful
degradation when no key is configured, and per-day usage/cost tracking
(reported in the morning briefing, same ethos as the API USAGE section).

Division of labor:
  MODEL_FAST  - cheap classification (sentiment, yes/no judgments)
  MODEL_SMART - narrative + reasoning (morning briefing, portfolio chat)
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional

from data_fetch import load_env

load_env()

BASE = Path(__file__).resolve().parents[1]
USAGE_FILE = BASE / "ai_usage.json"

MODEL_FAST = "claude-haiku-4-5"
MODEL_SMART = "claude-sonnet-5"

# $/million tokens (input, output) - used for the cost line in usage reports
_PRICING = {
    MODEL_FAST: (1.00, 5.00),
    MODEL_SMART: (3.00, 15.00),
}


def model_for(task: str) -> str:
    """Pick a model per task honoring the user's model_tier setting.

    budget  (default) - Haiku for everything; pennies per day
    quality - Sonnet for reasoning tasks (briefing, chat, debate judge),
              Haiku for cheap classification either way
    """
    try:
        from user_config import get_config
        tier = get_config().get("ai", {}).get("model_tier", "budget")
    except Exception:
        tier = "budget"
    if tier == "quality" and task in ("briefing", "chat", "judge"):
        return MODEL_SMART
    return MODEL_FAST


def daily_budget_usd() -> float:
    try:
        from user_config import get_config
        return float(get_config().get("ai", {}).get("daily_budget_usd", 1.0))
    except Exception:
        return 1.0


def budget_exceeded() -> bool:
    """True when today's AI spend has reached the user's daily cap."""
    return usage_today().get("cost_usd", 0.0) >= daily_budget_usd()

_client = None
_client_lock = Lock()


def ai_available() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return key.startswith("sk-ant")


def get_anthropic():
    """Lazy singleton Anthropic client, or None when no key is configured."""
    global _client
    if not ai_available():
        return None
    with _client_lock:
        if _client is None:
            from anthropic import Anthropic
            _client = Anthropic()
        return _client


# ── Usage tracking ───────────────────────────────────────────────────────────

_usage_lock = Lock()


def _record_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    today = date.today().isoformat()
    with _usage_lock:
        data = {}
        if USAGE_FILE.exists():
            try:
                data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        day = data.setdefault(today, {})
        m = day.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        m["calls"] += 1
        m["input_tokens"] += input_tokens
        m["output_tokens"] += output_tokens
        # keep only the last 30 days
        for k in sorted(data)[:-30]:
            del data[k]
        USAGE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def usage_today() -> dict:
    """{model: {calls, input_tokens, output_tokens}, "cost_usd": float} for today."""
    if not USAGE_FILE.exists():
        return {"cost_usd": 0.0}
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"cost_usd": 0.0}
    day = data.get(date.today().isoformat(), {})
    cost = 0.0
    for model, m in day.items():
        inp, outp = _PRICING.get(model, (3.0, 15.0))
        cost += m["input_tokens"] / 1e6 * inp + m["output_tokens"] / 1e6 * outp
    return {**day, "cost_usd": round(cost, 4)}


# ── Completion helpers ───────────────────────────────────────────────────────

def complete(
    prompt: str,
    *,
    system: str = "",
    model: str = MODEL_SMART,
    max_tokens: int = 2048,
) -> Optional[str]:
    """Single-turn text completion. Returns None when AI is unavailable or errors."""
    client = get_anthropic()
    if client is None:
        return None
    if budget_exceeded():
        return None  # hard stop: never spend past the daily cap
    try:
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        _record_usage(model, msg.usage.input_tokens, msg.usage.output_tokens)
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception:
        return None


def chat_with_tools(
    messages: list[dict],
    *,
    tools: list[dict],
    tool_handlers: dict[str, Callable[..., Any]],
    system: str = "",
    model: str = MODEL_SMART,
    max_tokens: int = 2048,
    max_rounds: int = 8,
) -> dict:
    """
    Agentic loop: let the model call local functions until it produces a final
    text answer (or max_rounds is hit).

    Returns {"reply": str, "tool_calls": [tool names], "rounds": int}.
    Raises RuntimeError when AI is unavailable.
    """
    client = get_anthropic()
    if client is None:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    if budget_exceeded():
        raise RuntimeError(
            f"Daily AI budget (${daily_budget_usd():.2f}) reached - raise it in Settings or try tomorrow"
        )

    convo = list(messages)
    called: list[str] = []
    for round_no in range(1, max_rounds + 1):
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system or None,
            tools=tools,
            messages=convo,
        )
        _record_usage(model, msg.usage.input_tokens, msg.usage.output_tokens)

        if msg.stop_reason != "tool_use":
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            return {"reply": text, "tool_calls": called, "rounds": round_no}

        convo.append({"role": "assistant", "content": msg.content})
        results = []
        for block in msg.content:
            if block.type != "tool_use":
                continue
            called.append(block.name)
            handler = tool_handlers.get(block.name)
            try:
                if handler is None:
                    raise KeyError(f"no handler for tool {block.name}")
                out = handler(**(block.input or {}))
                content = json.dumps(out, default=str)[:20000]
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
            except Exception as e:
                results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": f"error: {type(e).__name__}: {e}", "is_error": True,
                })
        convo.append({"role": "user", "content": results})

    return {"reply": "I hit the tool-call limit before finishing - try a narrower question.",
            "tool_calls": called, "rounds": max_rounds}
