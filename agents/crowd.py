"""The Concierge's one narrow Claude call: the events list → a crowd effect category + a short reason.

The answer is a category (none | small | medium | large), never a number: the engine maps it to its crowd multiplier.
Claude is asked through structured output whose `value` is an enum, so nothing else can come back. No key, a refusal,
an error or no answer within CLASSIFY_TIMEOUT_S → None, and the crowd effect stays as it was (last known).
Recorded mode (DEMO_MODE) answers with the recorded crowd effect from contracts/fixtures/agents/context_post.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Callable

from common import load_fixture

log = logging.getLogger("agents.crowd")

CROWD_EFFECTS = ("none", "small", "medium", "large")
DEFAULT_MODEL = "claude-opus-5-5"
CLASSIFY_TIMEOUT_S = 10.0
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # on a refusal the API re-runs the request on a fallback model

# events (Context.events) → {"value", "reason"} | None
Classifier = Callable[[dict], Awaitable[dict | None]]

SYSTEM_PROMPT = """You classify how much nearby events will raise customer traffic at a restaurant in the next hours.
Answer with a crowd effect category: none, small, medium or large. Give a reason of at most 12 words. In the reason,
quote only facts that appear in the event data, exactly as written; never estimate, add or convert numbers."""

SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "string", "enum": list(CROWD_EFFECTS)},
        "reason": {"type": "string"},
    },
    "required": ["value", "reason"],
    "additionalProperties": False,
}


def recorded_crowd_effect() -> dict:
    ce = load_fixture("context_post.json")["body"]["crowd_effect"]
    return {"value": ce["value"], "reason": ce["reason"]}


async def recorded_classifier(events: dict) -> dict | None:
    return recorded_crowd_effect()


class ClaudeClassifier:
    def __init__(self, client: Any, model: str):
        self._client = client  # anthropic.AsyncAnthropic
        self.model = model

    async def __call__(self, events: dict) -> dict | None:
        try:
            return await asyncio.wait_for(self._ask(events), CLASSIFY_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("Claude gave no crowd effect within %.0f s", CLASSIFY_TIMEOUT_S)
        except Exception as e:  # any API or parse failure: the crowd effect stays as it was
            log.warning("Claude crowd effect failed: %s", e)
        return None

    async def _ask(self, events: dict) -> dict | None:
        message = await self._client.beta.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Events:\n" + json.dumps(events.get("items", []), indent=1)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if message.stop_reason == "refusal":
            log.warning("Claude declined the crowd effect")
            return None
        text = next((b.text for b in message.content if b.type == "text"), None)
        if text is None:
            return None
        data = json.loads(text)
        if data.get("value") not in CROWD_EFFECTS or not isinstance(data.get("reason"), str):
            return None
        return {"value": data["value"], "reason": data["reason"]}


def create_classifier(use_recorded: bool) -> Classifier | None:
    """Recorded mode → the recorded answer. No ANTHROPIC_API_KEY → None (Claude off; the loop skips the call)."""
    if use_recorded:
        return recorded_classifier
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("no ANTHROPIC_API_KEY; crowd effect is left as it is")
        return None
    import anthropic

    client = anthropic.AsyncAnthropic(timeout=CLASSIFY_TIMEOUT_S, max_retries=1)
    return ClaudeClassifier(client, os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL)
