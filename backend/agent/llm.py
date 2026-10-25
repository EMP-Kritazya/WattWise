"""The models behind the agent, one interface (`LLM.turn`), and the provider chain Claude → ASI:One → templates.

- Claude: `CLAUDE_PROVIDER=anthropic` (default) | `foundry` (STUB), key `ANTHROPIC_API_KEY`, model `ANTHROPIC_MODEL`.
- ASI:One: OpenAI-compatible Chat Completions (docs.asi1.ai), key `ASI1_API_KEY`, model `ASI1_MODEL` (default `asi1`).
  Used for chat and explanations only when Claude is off, fails or times out; never for escalations, which stay
  Claude → the engine's default.
- Templates (`agent/templates.py`) when every model is off or fails.

Messages and Turns stay in the Anthropic shape (text / tool_use / tool_result blocks), so the tool loop in
`claude_agent.py` is the same for every provider; `ASI1LLM` converts at its edge.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

log = logging.getLogger("agent.llm")

DEFAULT_MODEL = "claude-opus-5-5"
PROVIDERS = ("anthropic", "foundry")
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # on a refusal the API re-runs the request on a fallback model

ASI1_BASE_URL = "https://api.asi1.ai/v1"
ASI1_DEFAULT_MODEL = "asi1"
ASI1_MAX_TOKENS = 4000
ASI1_HTTP_TIMEOUT_S = 30.0  # the agent's own per-answer timeouts are shorter where they matter
ASI1_STOP_REASONS = {"tool_calls": "tool_use", "length": "max_tokens", "stop": "end_turn"}


@dataclass
class Turn:
    content: list[Any]  # the assistant's content blocks, passed back unchanged on the next request
    tool_uses: list[tuple[str, str, dict]] = field(default_factory=list)  # (tool_use_id, name, input)
    stop_reason: str | None = None

    @property
    def text(self) -> str:
        return "".join(_field(b, "text") or "" for b in self.content if _field(b, "type") == "text")


def _field(block: Any, name: str) -> Any:
    return block.get(name) if isinstance(block, dict) else getattr(block, name, None)


OnText = Callable[[str], Awaitable[None]]


class LLM(Protocol):
    name: str  # "claude" | "asi1", for logs
    model: str

    async def turn(self, *, system: str, messages: list[dict], tools: list[dict], effort: str,
                   on_text: OnText | None = None) -> Turn: ...


# ---------------------------------------------------------------- Claude


class AnthropicLLM:
    """One streamed Messages API call per turn (anthropic >= 2.3)."""

    name = "claude"

    def __init__(self, client: Any, model: str):
        self._client = client  # anthropic.AsyncAnthropic
        self.model = model

    async def turn(self, *, system: str, messages: list[dict], tools: list[dict], effort: str,
                   on_text: OnText | None = None) -> Turn:
        async with self._client.beta.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            async for event in stream:
                if event.type == "text" and on_text is not None:
                    await on_text(event.text)
            message = await stream.get_final_message()
        uses = [(b.id, b.name, b.input) for b in message.content if b.type == "tool_use"]
        return Turn(list(message.content), uses, message.stop_reason)


def create_llm(provider: str, api_key: str | None, model: str | None) -> LLM | None:
    """Claude, or None = Claude off. Logged once, never raised: the kitchen runs without Claude."""
    if provider not in PROVIDERS:
        raise ValueError(f"CLAUDE_PROVIDER={provider!r}; expected one of {PROVIDERS}")
    if provider == "foundry":
        log.warning("STUB: CLAUDE_PROVIDER=foundry is not built yet; Claude is off")
        return None
    if not api_key:
        log.info("no ANTHROPIC_API_KEY; Claude is off")
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("the anthropic package is not installed; Claude is off")
        return None
    return AnthropicLLM(anthropic.AsyncAnthropic(api_key=api_key), model or DEFAULT_MODEL)


# ---------------------------------------------------------------- ASI:One


class ASI1LLM:
    """One Chat Completions call per turn (not streamed: the answer's text arrives as one delta)."""

    name = "asi1"

    def __init__(self, client: Any, model: str):
        self._client = client  # httpx.AsyncClient with base_url and the Bearer header
        self.model = model

    async def turn(self, *, system: str, messages: list[dict], tools: list[dict], effort: str,
                   on_text: OnText | None = None) -> Turn:
        body = {"model": self.model, "max_tokens": ASI1_MAX_TOKENS,
                "messages": [{"role": "system", "content": system}, *_to_openai_messages(messages)]}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["input_schema"]}} for t in tools]
        resp = await self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        choice = resp.json()["choices"][0]
        message = choice["message"]
        content: list[dict] = []
        if message.get("content"):
            content.append({"type": "text", "text": message["content"]})
        uses = []
        for call in message.get("tool_calls") or ():
            tool_input = json.loads(call["function"]["arguments"] or "{}")  # bad JSON → this answer fails over
            uses.append((call["id"], call["function"]["name"], tool_input))
            content.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                            "input": tool_input})
        stop = "tool_use" if uses else ASI1_STOP_REASONS.get(choice.get("finish_reason"), "end_turn")
        if on_text is not None and message.get("content"):
            await on_text(message["content"])
        return Turn(content, uses, stop)


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Anthropic-shaped history → Chat Completions messages (tool_use → tool_calls, tool_result → role "tool")."""
    out: list[dict] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "".join(_field(b, "text") or "" for b in content if _field(b, "type") == "text")
            calls = [{"id": _field(b, "id"), "type": "function",
                      "function": {"name": _field(b, "name"), "arguments": json.dumps(_field(b, "input"))}}
                     for b in content if _field(b, "type") == "tool_use"]
            out.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
            continue
        for b in content:
            if _field(b, "type") == "tool_result":
                result = b["content"]
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                            "content": json.dumps({"error": result}) if b.get("is_error") else result})
            elif _field(b, "type") == "text":
                out.append({"role": "user", "content": b["text"]})
    return out


def create_asi1_llm(api_key: str | None, model: str | None, base_url: str | None = None,
                    transport: Any = None) -> LLM | None:
    """ASI:One, or None = off. `transport` is an httpx transport (tests)."""
    if not api_key:
        log.info("no ASI1_API_KEY; the ASI:One fallback is off")
        return None
    import httpx

    client = httpx.AsyncClient(base_url=base_url or ASI1_BASE_URL, timeout=ASI1_HTTP_TIMEOUT_S, transport=transport,
                               headers={"Authorization": f"Bearer {api_key}"})
    return ASI1LLM(client, model or ASI1_DEFAULT_MODEL)
